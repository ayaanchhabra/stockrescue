import csv
import io

import pytest

from app.services.inventory_csv import (
    ALL_COLUMNS,
    MAX_ROWS,
    InventoryFileError,
    preview_inventory_csv,
)


REQUIRED_HEADERS = [
    "product_id",
    "product_name",
    "category",
    "quantity_in_stock",
    "unit_cost",
    "selling_price",
]

BASE_ROW = {
    "product_id": "B001",
    "product_name": "Test Book",
    "category": "Books",
    "quantity_in_stock": "5",
    "unit_cost": "10.00",
    "selling_price": "20.00",
}


def make_csv(rows, headers=REQUIRED_HEADERS):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)

    for row in rows:
        if isinstance(row, dict):
            writer.writerow([row.get(header, "") for header in headers])
        else:
            writer.writerow(row)

    return output.getvalue().encode("utf-8")


def test_valid_required_fields_and_sku_mapping():
    preview = preview_inventory_csv(make_csv([BASE_ROW]))

    assert len(preview.valid_rows) == 1
    row = preview.valid_rows[0]
    assert row.values["sku"] == "B001"
    assert row.values["product_name"] == "Test Book"
    assert row.values["quantity_in_stock"] == 5
    assert row.values["unit_cost"] == 10.0
    assert row.values["selling_price"] == 20.0


def test_blank_optional_values_remain_none():
    headers = REQUIRED_HEADERS + [
        "creator_or_brand",
        "units_sold_30d",
        "units_sold_60d",
        "units_sold_90d",
        "days_in_stock",
    ]
    preview = preview_inventory_csv(make_csv([BASE_ROW], headers))
    row = preview.valid_rows[0]

    assert row.values["creator_or_brand"] is None
    assert row.values["units_sold_30d"] is None
    assert row.values["units_sold_60d"] is None
    assert row.values["units_sold_90d"] is None
    assert row.values["days_in_stock"] is None
    assert row.updates_sales_snapshot is False


def test_snapshot_is_marked_when_any_snapshot_value_is_supplied():
    headers = REQUIRED_HEADERS + [
        "units_sold_30d",
        "units_sold_60d",
        "units_sold_90d",
        "days_in_stock",
    ]
    row_data = {**BASE_ROW, "units_sold_30d": "0"}
    row = preview_inventory_csv(make_csv([row_data], headers)).valid_rows[0]

    assert row.updates_sales_snapshot is True
    assert row.values["units_sold_30d"] == 0
    assert row.values["units_sold_60d"] is None
    assert row.values["units_sold_90d"] is None
    assert row.values["days_in_stock"] is None


def test_invalid_row_is_reported_without_invalidating_other_rows():
    invalid = {**BASE_ROW, "product_id": "BAD1", "quantity_in_stock": "-2"}
    valid = {**BASE_ROW, "product_id": "GOOD1"}

    preview = preview_inventory_csv(make_csv([invalid, valid]))

    assert len(preview.invalid_rows) == 1
    assert len(preview.valid_rows) == 1
    assert preview.invalid_rows[0].row_number == 2
    assert preview.invalid_rows[0].errors[0].field == "quantity_in_stock"


def test_duplicate_product_id_flags_later_occurrence():
    first = {**BASE_ROW, "product_id": "DUP1"}
    second = {**BASE_ROW, "product_id": "DUP1", "product_name": "Second title"}

    preview = preview_inventory_csv(make_csv([first, second]))

    assert preview.rows[0].is_valid
    assert not preview.rows[1].is_valid
    assert preview.rows[1].row_number == 3
    assert any("row 2" in issue.message for issue in preview.rows[1].errors)


def test_invalid_margin_and_discount_are_rejected():
    headers = REQUIRED_HEADERS + [
        "minimum_acceptable_margin",
        "maximum_discount_percentage",
    ]
    row_data = {
        **BASE_ROW,
        "minimum_acceptable_margin": "100",
        "maximum_discount_percentage": "101",
    }

    row = preview_inventory_csv(make_csv([row_data], headers)).invalid_rows[0]
    error_fields = {issue.field for issue in row.errors}

    assert "minimum_acceptable_margin" in error_fields
    assert "maximum_discount_percentage" in error_fields


def test_sales_inconsistency_and_loss_are_warnings():
    headers = REQUIRED_HEADERS + [
        "units_sold_30d",
        "units_sold_60d",
        "units_sold_90d",
    ]
    row_data = {
        **BASE_ROW,
        "unit_cost": "20",
        "selling_price": "10",
        "units_sold_30d": "10",
        "units_sold_60d": "5",
        "units_sold_90d": "4",
    }

    row = preview_inventory_csv(make_csv([row_data], headers)).valid_rows[0]
    warning_fields = {issue.field for issue in row.warnings}

    assert "units_sold_60d" in warning_fields
    assert "units_sold_90d" in warning_fields
    assert "selling_price" in warning_fields
    assert row.errors == []


def test_missing_required_header_rejects_entire_file():
    headers = [
        "product_id",
        "product_name",
        "quantity_in_stock",
        "unit_cost",
        "selling_price",
    ]

    with pytest.raises(InventoryFileError, match="Missing required columns"):
        preview_inventory_csv(make_csv([BASE_ROW], headers))


def test_file_size_limit_is_enforced():
    with pytest.raises(InventoryFileError, match="2 MB"):
        preview_inventory_csv(b"x" * (2 * 1024 * 1024 + 1))


def test_row_limit_is_enforced():
    rows = [
        {**BASE_ROW, "product_id": f"B{i:04d}"}
        for i in range(MAX_ROWS + 1)
    ]

    with pytest.raises(InventoryFileError, match="2,000"):
        preview_inventory_csv(make_csv(rows))


def test_invalid_date_is_reported():
    headers = REQUIRED_HEADERS + ["publication_or_release_date"]
    row_data = {
        **BASE_ROW,
        "publication_or_release_date": "26-10-2026",
    }

    row = preview_inventory_csv(make_csv([row_data], headers)).invalid_rows[0]

    assert any(
        issue.field == "publication_or_release_date"
        for issue in row.errors
    )


def test_validation_error_includes_row_field_value_and_fix():
    invalid = {**BASE_ROW, "quantity_in_stock": "-2"}
    preview = preview_inventory_csv(make_csv([invalid]))

    issue = next(
        issue
        for issue in preview.invalid_rows[0].errors
        if issue.field == "quantity_in_stock"
    )

    assert issue.row_number == 2
    assert issue.value == "-2"
    assert issue.severity == "error"
    assert "0 or a positive" in issue.message


def test_recorded_zero_is_distinct_from_blank_sales_data():
    headers = REQUIRED_HEADERS + ["units_sold_30d"]

    zero_row = {**BASE_ROW, "product_id": "ZERO", "units_sold_30d": "0"}
    blank_row = {**BASE_ROW, "product_id": "BLANK", "units_sold_30d": ""}

    preview = preview_inventory_csv(make_csv([zero_row, blank_row], headers))
    zero, blank = preview.rows

    assert zero.values["units_sold_30d"] == 0
    assert "units_sold_30d" in zero.provided_fields
    assert zero.updates_sales_snapshot is True

    assert blank.values["units_sold_30d"] is None
    assert "units_sold_30d" not in blank.provided_fields
    assert blank.updates_sales_snapshot is False


def test_utf8_bom_is_accepted():
    content = b"\xef\xbb\xbf" + make_csv([BASE_ROW])
    preview = preview_inventory_csv(content)

    assert len(preview.valid_rows) == 1
    assert preview.valid_rows[0].values["sku"] == "B001"


def test_extremely_large_numeric_value_is_rejected():
    row_data = {**BASE_ROW, "unit_cost": "1e9999"}
    preview = preview_inventory_csv(make_csv([row_data]))

    assert len(preview.invalid_rows) == 1
    assert any(
        issue.field == "unit_cost"
        for issue in preview.invalid_rows[0].errors
    )
