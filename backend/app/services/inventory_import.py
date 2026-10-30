"""Transactional CSV import service for StockRescue inventory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import InventorySalesSnapshot, Product
from app.services.inventory_csv import (
    InventoryCSVRow,
    InventoryIssue,
    preview_inventory_csv,
    SALES_SNAPSHOT_COLUMNS,
)

DEFAULT_RETAILER_ID = "demo"

ImportAction = Literal["created", "updated", "skipped"]

REQUIRED_UPDATE_FIELDS = (
    "sku",
    "product_name",
    "category",
    "quantity_in_stock",
    "unit_cost",
    "selling_price",
)

ORDINARY_OPTIONAL_FIELDS = (
    "creator_or_brand",
    "product_description",
    "genre_or_subcategory",
    "publication_or_release_date",
    "seasonality",
    "minimum_acceptable_margin",
    "maximum_discount_percentage",
)


@dataclass
class ImportRowResult:
    row_number: int
    product_id: str | None
    action: ImportAction
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]


@dataclass
class InventoryImportResult:
    created_count: int
    updated_count: int
    skipped_count: int
    rows: list[ImportRowResult]

    @property
    def imported_count(self) -> int:
        return self.created_count + self.updated_count


def _issue_to_dict(issue: InventoryIssue) -> dict[str, Any]:
    return {
        "row_number": issue.row_number,
        "field": issue.field,
        "value": issue.value,
        "message": issue.message,
        "severity": issue.severity,
    }


def _row_result(
    row: InventoryCSVRow,
    action: ImportAction,
) -> ImportRowResult:
    return ImportRowResult(
        row_number=row.row_number,
        product_id=row.product_id,
        action=action,
        errors=[_issue_to_dict(issue) for issue in row.errors],
        warnings=[_issue_to_dict(issue) for issue in row.warnings],
    )


def _update_existing_product(
    product: Product,
    row: InventoryCSVRow,
) -> None:
    """Apply the team's required-field and blank-cell rules."""
    values = row.values

    for field_name in REQUIRED_UPDATE_FIELDS:
        setattr(product, field_name, values[field_name])

    # Blank ordinary optional fields preserve current values.
    for field_name in ORDINARY_OPTIONAL_FIELDS:
        if field_name in row.provided_fields:
            setattr(product, field_name, values[field_name])

    # Sales history and stock age are one time-sensitive snapshot.
    # If any of the four cells was supplied, replace all four.
    # Blank cells within this supplied snapshot become NULL.
    if row.updates_sales_snapshot:
        for field_name in SALES_SNAPSHOT_COLUMNS:
            setattr(product, field_name, values[field_name])


def import_inventory_csv(
    db: Session,
    content: bytes,
    retailer_id: str = DEFAULT_RETAILER_ID,
) -> InventoryImportResult:
    """Validate and import a CSV in one database transaction.

    File-level validation errors reject the upload before any writes.
    Invalid rows are skipped while valid rows can still be imported.
    Unexpected database errors roll back all writes in this import.

    Call with a fresh SQLAlchemy session. This function owns the
    transaction and commits it on successful completion.
    """
    # Validate the whole file before opening a write transaction.
    preview = preview_inventory_csv(content)

    valid_skus = {
        row.product_id
        for row in preview.valid_rows
        if row.product_id is not None
    }
    results_by_row: dict[int, ImportRowResult] = {}
    snapshot_candidates: list[Product] = []
    imported_at = datetime.now(timezone.utc)

    with db.begin():
        existing_by_sku: dict[str, Product] = {}

        if valid_skus:
            statement = select(Product).where(
                Product.retailer_id == retailer_id,
                Product.sku.in_(valid_skus),
            )
            products = db.scalars(statement).all()
            existing_by_sku = {product.sku: product for product in products}

        for row in preview.rows:
            if not row.is_valid:
                results_by_row[row.row_number] = _row_result(row, "skipped")
                continue

            sku = row.product_id
            if not sku:
                # Defensive assertion: the validator should catch this.
                raise RuntimeError(
                    f"Validated CSV row {row.row_number} has no product ID."
                )

            existing = existing_by_sku.get(sku)

            if existing is not None:
                _update_existing_product(existing, row)
                action: ImportAction = "updated"
            else:
                # New products store blank optional cells as NULL.
                product = Product(
                    retailer_id=retailer_id,
                    **row.values,
                )
                db.add(product)
                existing_by_sku[sku] = product
                existing = product
                action = "created"

            # Preserve every valid imported row as a dated sales snapshot. NULL
            # values remain NULL: a missing sales field is not a zero.
            snapshot_candidates.append(existing)
            results_by_row[row.row_number] = _row_result(row, action)

        # Execute pending INSERT/UPDATE statements while still in the
        # transaction, so database constraint failures trigger rollback.
        db.flush()
        db.add_all([
            InventorySalesSnapshot(
                retailer_id=retailer_id,
                product_pk=product.id,
                imported_at=imported_at,
                source="inventory_csv",
                units_sold_30d=product.units_sold_30d,
                units_sold_60d=product.units_sold_60d,
                units_sold_90d=product.units_sold_90d,
                days_in_stock=product.days_in_stock,
            )
            for product in snapshot_candidates
        ])
        db.flush()

    ordered_results = [
        results_by_row[row.row_number]
        for row in preview.rows
    ]

    return InventoryImportResult(
        created_count=sum(r.action == "created" for r in ordered_results),
        updated_count=sum(r.action == "updated" for r in ordered_results),
        skipped_count=sum(r.action == "skipped" for r in ordered_results),
        rows=ordered_results,
    )


__all__ = [
    "DEFAULT_RETAILER_ID",
    "ImportRowResult",
    "InventoryImportResult",
    "import_inventory_csv",
]
