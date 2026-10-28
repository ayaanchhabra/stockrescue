import csv
import io
from datetime import date

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.entities import Product
from app.services.inventory_csv import ALL_COLUMNS, InventoryFileError
from app.services.inventory_import import (
    DEFAULT_RETAILER_ID,
    import_inventory_csv,
)


@pytest.fixture
def db():
    """An isolated in-memory database for each test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    session = TestingSession()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def csv_row(product_id="SKU-1", **overrides):
    """Build a row containing every column from the real CSV contract."""
    row = {column: "" for column in ALL_COLUMNS}
    row.update({
        "product_id": product_id,
        "product_name": "Test Book",
        "category": "Books",
        "quantity_in_stock": "5",
        "unit_cost": "10",
        "selling_price": "20",
    })
    row.update(overrides)
    return row


def csv_bytes(*rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=ALL_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def seed_product(db, **overrides):
    fields = {
        "retailer_id": DEFAULT_RETAILER_ID,
        "sku": "SKU-1",
        "product_name": "Original Book",
        "category": "Books",
        "creator_or_brand": "Original Author",
        "product_description": "Existing description",
        "genre_or_subcategory": "Fiction",
        "quantity_in_stock": 4,
        "unit_cost": 10.0,
        "selling_price": 20.0,
        "units_sold_30d": 3,
        "units_sold_60d": 6,
        "units_sold_90d": 9,
        "days_in_stock": 45,
        "publication_or_release_date": date(2020, 1, 1),
        "seasonality": "Winter",
        "minimum_acceptable_margin": 12.0,
        "maximum_discount_percentage": 20.0,
    }
    fields.update(overrides)
    product = Product(**fields)
    db.add(product)
    db.commit()
    return product.id


def test_import_creates_valid_row_and_skips_invalid_row(db):
    content = csv_bytes(
        csv_row("SKU-1"),
        csv_row("SKU-BAD", quantity_in_stock="-1"),
    )

    result = import_inventory_csv(db, content)

    assert result.created_count == 1
    assert result.updated_count == 0
    assert result.skipped_count == 1
    assert result.imported_count == 1
    assert result.rows[0].action == "created"
    assert result.rows[1].action == "skipped"
    assert any(
        error["field"] == "quantity_in_stock"
        for error in result.rows[1].errors
    )

    products = db.scalars(select(Product)).all()
    assert len(products) == 1
    assert products[0].sku == "SKU-1"
    assert products[0].creator_or_brand is None
    assert products[0].units_sold_30d is None


def test_existing_product_updates_in_place_and_preserves_blank_optionals(db):
    original_id = seed_product(db)

    content = csv_bytes(
        csv_row(
            "SKU-1",
            product_name="Updated Book",
            quantity_in_stock="9",
        )
    )

    result = import_inventory_csv(db, content)

    assert result.created_count == 0
    assert result.updated_count == 1
    assert result.skipped_count == 0
    assert result.rows[0].action == "updated"

    updated = db.scalar(
        select(Product).where(
            Product.retailer_id == DEFAULT_RETAILER_ID,
            Product.sku == "SKU-1",
        )
    )

    assert updated is not None
    assert updated.id == original_id
    assert updated.product_name == "Updated Book"
    assert updated.quantity_in_stock == 9

    # Ordinary blank optional fields preserve existing values.
    assert updated.creator_or_brand == "Original Author"
    assert updated.product_description == "Existing description"
    assert updated.genre_or_subcategory == "Fiction"
    assert updated.publication_or_release_date == date(2020, 1, 1)
    assert updated.seasonality == "Winter"
    assert updated.minimum_acceptable_margin == 12.0
    assert updated.maximum_discount_percentage == 20.0

    # No sales-snapshot fields were supplied, so the snapshot is preserved.
    assert updated.units_sold_30d == 3
    assert updated.units_sold_60d == 6
    assert updated.units_sold_90d == 9
    assert updated.days_in_stock == 45


def test_partial_sales_snapshot_replaces_all_four_fields(db):
    seed_product(db)

    content = csv_bytes(
        csv_row("SKU-1", units_sold_30d="2")
    )

    result = import_inventory_csv(db, content)
    assert result.updated_count == 1

    updated = db.scalar(
        select(Product).where(Product.sku == "SKU-1")
    )
    assert updated is not None

    assert updated.units_sold_30d == 2
    assert updated.units_sold_60d is None
    assert updated.units_sold_90d is None
    assert updated.days_in_stock is None

    # Other blank optional fields must still preserve existing values.
    assert updated.creator_or_brand == "Original Author"


def test_duplicate_sku_keeps_first_valid_occurrence(db):
    content = csv_bytes(
        csv_row("DUP-1", product_name="First occurrence"),
        csv_row("DUP-1", product_name="Duplicate occurrence"),
    )

    result = import_inventory_csv(db, content)

    assert result.created_count == 1
    assert result.skipped_count == 1
    assert result.rows[0].action == "created"
    assert result.rows[1].action == "skipped"
    assert any(
        "Duplicate product_id" in error["message"]
        for error in result.rows[1].errors
    )

    products = db.scalars(
        select(Product).where(Product.sku == "DUP-1")
    ).all()
    assert len(products) == 1
    assert products[0].product_name == "First occurrence"


def test_file_level_error_rejects_upload_without_writes(db):
    invalid_content = (
        b"product_name,category,quantity_in_stock,unit_cost,selling_price\n"
        b"Book,Books,2,10,20\n"
    )

    with pytest.raises(InventoryFileError):
        import_inventory_csv(db, invalid_content)

    assert db.scalars(select(Product)).all() == []


def test_database_failure_rolls_back_all_import_changes(db):
    seed_product(db, product_name="Original Book")

    def fail_after_flush(session, flush_context):
        if session is db:
            raise RuntimeError("simulated failure after SQL flush")

    event.listen(Session, "after_flush", fail_after_flush)
    try:
        content = csv_bytes(
            csv_row(
                "SKU-1",
                product_name="Should roll back",
            ),
            csv_row(
                "SKU-NEW",
                product_name="Should not be inserted",
            ),
        )

        with pytest.raises(
            RuntimeError,
            match="simulated failure after SQL flush",
        ):
            import_inventory_csv(db, content)
    finally:
        event.remove(Session, "after_flush", fail_after_flush)

    # The failed transaction must have rolled back the update and insert.
    original = db.scalar(
        select(Product).where(Product.sku == "SKU-1")
    )
    new_product = db.scalar(
        select(Product).where(Product.sku == "SKU-NEW")
    )

    assert original is not None
    assert original.product_name == "Original Book"
    assert new_product is None


def test_invalid_first_duplicate_does_not_block_later_valid_row(db):
    content = csv_bytes(
        csv_row(
            "SKU-RETRY",
            product_name="Invalid first row",
            quantity_in_stock="-1",
        ),
        csv_row(
            "SKU-RETRY",
            product_name="Valid later row",
            quantity_in_stock="5",
        ),
    )

    result = import_inventory_csv(db, content)

    assert result.skipped_count == 1
    assert result.created_count == 1
    assert result.rows[0].action == "skipped"
    assert result.rows[1].action == "created"

    product = db.scalar(
        select(Product).where(Product.sku == "SKU-RETRY")
    )
    assert product is not None
    assert product.product_name == "Valid later row"
    assert product.quantity_in_stock == 5
