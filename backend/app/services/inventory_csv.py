"""CSV parsing and validation for StockRescue inventory imports.

This module performs no database writes. Endpoint and persistence behavior
will be implemented separately once the shared API contract is aligned.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal


MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2_000

REQUIRED_COLUMNS = (
    "product_id",
    "product_name",
    "category",
    "quantity_in_stock",
    "unit_cost",
    "selling_price",
)

OPTIONAL_COLUMNS = (
    "creator_or_brand",
    "product_description",
    "genre_or_subcategory",
    "units_sold_30d",
    "units_sold_60d",
    "units_sold_90d",
    "days_in_stock",
    "publication_or_release_date",
    "seasonality",
    "minimum_acceptable_margin",
    "maximum_discount_percentage",
)

ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

SALES_SNAPSHOT_COLUMNS = (
    "units_sold_30d",
    "units_sold_60d",
    "units_sold_90d",
    "days_in_stock",
)

STRING_MAX_LENGTHS = {
    "product_id": 64,
    "product_name": 300,
    "category": 100,
    "creator_or_brand": 200,
    "genre_or_subcategory": 100,
    "seasonality": 100,
}

INTEGER_COLUMNS = (
    "quantity_in_stock",
    "units_sold_30d",
    "units_sold_60d",
    "units_sold_90d",
    "days_in_stock",
)

NUMBER_COLUMNS = (
    "unit_cost",
    "selling_price",
    "minimum_acceptable_margin",
    "maximum_discount_percentage",
)


class InventoryFileError(ValueError):
    """A file-level problem that prevents the entire CSV from being used."""


@dataclass(frozen=True)
class InventoryIssue:
    row_number: int
    field: str
    value: str | None
    message: str
    severity: Literal["error", "warning"]


@dataclass
class InventoryCSVRow:
    row_number: int
    product_id: str | None
    # Keys use database/model names: product_id becomes sku.
    values: dict[str, Any]
    # Nonblank CSV cells, retained to distinguish blanks from explicit values.
    provided_fields: set[str] = field(default_factory=set)
    errors: list[InventoryIssue] = field(default_factory=list)
    warnings: list[InventoryIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def updates_sales_snapshot(self) -> bool:
        """Whether any field in the four-field snapshot was supplied."""
        return any(
            column in self.provided_fields
            for column in SALES_SNAPSHOT_COLUMNS
        )


@dataclass
class InventoryCSVPreview:
    rows: list[InventoryCSVRow]

    @property
    def valid_rows(self) -> list[InventoryCSVRow]:
        return [row for row in self.rows if row.is_valid]

    @property
    def invalid_rows(self) -> list[InventoryCSVRow]:
        return [row for row in self.rows if not row.is_valid]


def preview_inventory_csv(content: bytes) -> InventoryCSVPreview:
    """Decode, parse, and validate CSV content without modifying any data."""
    if len(content) > MAX_UPLOAD_BYTES:
        raise InventoryFileError("File exceeds the 2 MB upload limit.")

    if not content:
        raise InventoryFileError("The uploaded CSV is empty.")

    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InventoryFileError(
            "The CSV must be UTF-8 encoded. Save it as UTF-8 and retry."
        ) from exc

    try:
        reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
        original_headers = reader.fieldnames
        if not original_headers:
            raise InventoryFileError("The CSV must contain a header row.")

        headers = [header.strip() if header else "" for header in original_headers]

        if any(not header for header in headers):
            raise InventoryFileError(
                "The header row contains an empty column name."
            )

        if len(headers) != len(set(headers)):
            raise InventoryFileError(
                "The header row contains duplicate column names."
            )

        missing = sorted(set(REQUIRED_COLUMNS) - set(headers))
        if missing:
            raise InventoryFileError(
                "Missing required columns: " + ", ".join(missing) + "."
            )

        unknown = sorted(set(headers) - set(ALL_COLUMNS))
        if unknown:
            raise InventoryFileError(
                "Unrecognized columns: " + ", ".join(unknown)
                + ". Use the StockRescue CSV template."
            )

        reader.fieldnames = headers
        raw_rows: list[tuple[int, dict[str | None, Any]]] = []

        for row_number, raw_row in enumerate(reader, start=2):
            if not raw_row:
                continue

            # Ignore completely blank records.
            if not any(
                str(value or "").strip()
                for key, value in raw_row.items()
                if key is not None
            ):
                continue

            raw_rows.append((row_number, raw_row))
            if len(raw_rows) > MAX_ROWS:
                raise InventoryFileError(
                    "File exceeds the 2,000 data-row limit."
                )

    except csv.Error as exc:
        raise InventoryFileError(
            f"Malformed CSV data: {exc}. Check quoting and delimiters."
        ) from exc

    rows: list[InventoryCSVRow] = []
    first_occurrence: dict[str, int] = {}

    for row_number, raw_row in raw_rows:
        cells = {
            key: value
            for key, value in raw_row.items()
            if key is not None
        }

        issues: list[InventoryIssue] = []
        errors: list[InventoryIssue] = []
        warnings: list[InventoryIssue] = []

        def add_issue(
            field_name: str,
            raw_value: Any,
            message: str,
            severity: Literal["error", "warning"] = "error",
        ) -> None:
            issue = InventoryIssue(
                row_number=row_number,
                field=field_name,
                value=None if raw_value is None else str(raw_value),
                message=message,
                severity=severity,
            )
            issues.append(issue)
            if severity == "error":
                errors.append(issue)
            else:
                warnings.append(issue)

        extra_values = raw_row.get(None)
        if extra_values:
            add_issue(
                "_row",
                ", ".join(str(value) for value in extra_values),
                "This row has more values than the header. Remove the extra cells.",
            )

        provided_fields = {
            column
            for column in ALL_COLUMNS
            if str(cells.get(column) or "").strip()
        }

        def raw_cell(column: str) -> Any:
            return cells.get(column)

        def cleaned_cell(column: str) -> str:
            value = raw_cell(column)
            return "" if value is None else str(value).strip()

        values: dict[str, Any] = {}

        # product_id is a textual SKU, not the internal Product.id.
        sku = cleaned_cell("product_id")
        if not sku:
            add_issue(
                "product_id",
                raw_cell("product_id"),
                "This field is required. Enter a product identifier.",
            )
        elif len(sku) > STRING_MAX_LENGTHS["product_id"]:
            add_issue(
                "product_id",
                sku,
                "Maximum length is 64 characters. Shorten the identifier.",
            )
        values["sku"] = sku or None

        first_row = first_occurrence.get(sku) if sku else None
        if sku and first_row is None:
            first_occurrence[sku] = row_number
        elif sku:
            add_issue(
                "product_id",
                sku,
                f"Duplicate product_id: first occurrence is on row {first_row}. "
                "This later row will be skipped; keep one occurrence per ID.",
            )

        # Required and optional text fields.
        text_fields = (
            ("product_name", True),
            ("category", True),
            ("creator_or_brand", False),
            ("product_description", False),
            ("genre_or_subcategory", False),
            ("seasonality", False),
        )

        for column, required in text_fields:
            raw = raw_cell(column)
            cleaned = cleaned_cell(column)

            if required and not cleaned:
                add_issue(
                    column,
                    raw,
                    "This field is required. Enter a value.",
                )
                values[column] = None
                continue

            if column == "product_description":
                value = raw if cleaned else None
            else:
                value = cleaned or None

            maximum = STRING_MAX_LENGTHS.get(column)
            if value is not None and maximum and len(value) > maximum:
                add_issue(
                    column,
                    str(value),
                    f"Maximum length is {maximum} characters. Shorten the value.",
                )

            values[column] = value

        # Non-negative whole-number fields.
        for column in INTEGER_COLUMNS:
            raw = raw_cell(column)
            cleaned = cleaned_cell(column)

            if not cleaned:
                if column == "quantity_in_stock":
                    add_issue(
                        column,
                        raw,
                        "This field is required. Enter a whole number of 0 or more.",
                    )
                values[column] = None
                continue

            try:
                # Strictly require integer notation: 3.0 is not a whole-number
                # entry under this CSV contract.
                if not cleaned.lstrip("+-").isdigit():
                    raise ValueError
                value = int(cleaned)
            except ValueError:
                add_issue(
                    column,
                    raw,
                    "Enter a whole number without decimals or text.",
                )
                values[column] = None
                continue

            if value < 0:
                add_issue(
                    column,
                    raw,
                    "Enter 0 or a positive whole number.",
                )
                values[column] = None
                continue

            values[column] = value

        # Financial fields use percentages in the range 0–100, not fractions.
        for column in NUMBER_COLUMNS:
            raw = raw_cell(column)
            cleaned = cleaned_cell(column)
            required = column in {"unit_cost", "selling_price"}

            if not cleaned:
                if required:
                    add_issue(
                        column,
                        raw,
                        "This field is required. Enter a valid number.",
                    )
                values[column] = None
                continue

            try:
                number = Decimal(cleaned)
                if not number.is_finite():
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                add_issue(
                    column,
                    raw,
                    "Enter a finite number without currency symbols or commas.",
                )
                values[column] = None
                continue

            if column == "unit_cost" and number < 0:
                add_issue(column, raw, "Unit cost must be 0 or greater.")
                values[column] = None
                continue

            if column == "selling_price" and number <= 0:
                add_issue(column, raw, "Selling price must be greater than 0.")
                values[column] = None
                continue

            if column == "minimum_acceptable_margin" and not (
                Decimal("0") <= number < Decimal("100")
            ):
                add_issue(
                    column,
                    raw,
                    "Minimum acceptable margin must be at least 0 and less than 100.",
                )
                values[column] = None
                continue

            if column == "maximum_discount_percentage" and not (
                Decimal("0") <= number <= Decimal("100")
            ):
                add_issue(
                    column,
                    raw,
                    "Maximum discount percentage must be between 0 and 100.",
                )
                values[column] = None
                continue

            float_value = float(number)
            if not math.isfinite(float_value):
                add_issue(
                    column,
                    raw,
                    "Number is too large to store safely. Enter a smaller finite number.",
                )
                values[column] = None
                continue

            values[column] = float_value

        # Dates are optional and must use YYYY-MM-DD.
        raw_date = raw_cell("publication_or_release_date")
        cleaned_date = cleaned_cell("publication_or_release_date")
        if not cleaned_date:
            values["publication_or_release_date"] = None
        else:
            try:
                parsed_date = date.fromisoformat(cleaned_date)
                if parsed_date.isoformat() != cleaned_date:
                    raise ValueError
                values["publication_or_release_date"] = parsed_date
            except ValueError:
                add_issue(
                    "publication_or_release_date",
                    raw_date,
                    "Use YYYY-MM-DD format, for example 2026-10-26.",
                )
                values["publication_or_release_date"] = None

        row = InventoryCSVRow(
            row_number=row_number,
            product_id=sku or None,
            values=values,
            provided_fields=provided_fields,
            errors=errors,
            warnings=warnings,
        )

        sold_30 = values["units_sold_30d"]
        sold_60 = values["units_sold_60d"]
        sold_90 = values["units_sold_90d"]

        if sold_30 is not None and sold_60 is not None and sold_60 < sold_30:
            add_issue(
                "units_sold_60d",
                raw_cell("units_sold_60d"),
                "60-day cumulative sales are below 30-day sales. Check the figures.",
                severity="warning",
            )

        if sold_60 is not None and sold_90 is not None and sold_90 < sold_60:
            add_issue(
                "units_sold_90d",
                raw_cell("units_sold_90d"),
                "90-day cumulative sales are below 60-day sales. Check the figures.",
                severity="warning",
            )

        unit_cost = values["unit_cost"]
        selling_price = values["selling_price"]
        if (
            unit_cost is not None
            and selling_price is not None
            and selling_price < unit_cost
        ):
            add_issue(
                "selling_price",
                raw_cell("selling_price"),
                "Selling price is below unit cost; each sale loses money before other costs.",
                severity="warning",
            )

        minimum_margin = values["minimum_acceptable_margin"]
        if (
            minimum_margin is not None
            and unit_cost is not None
            and selling_price is not None
            and selling_price > 0
        ):
            current_margin = (selling_price - unit_cost) / selling_price * 100
            if current_margin < minimum_margin:
                add_issue(
                    "minimum_acceptable_margin",
                    raw_cell("minimum_acceptable_margin"),
                    "Current gross margin is already below this product's minimum; "
                    "the product cannot be discounted under this constraint.",
                    severity="warning",
                )

        rows.append(row)

    return InventoryCSVPreview(rows=rows)
