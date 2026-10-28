import csv
import io

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.entities import Product
from app.services.inventory_csv import ALL_COLUMNS


def make_csv_row(product_id="SKU-1", **overrides):
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


def make_csv(*rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=ALL_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def upload(content, filename="inventory.csv"):
    return {
        "file": (filename, content, "text/csv"),
    }


def seed_product(**overrides):
    fields = {
        "retailer_id": "demo",
        "sku": "SKU-EXISTS",
        "product_name": "Existing Book",
        "category": "Books",
        "quantity_in_stock": 4,
        "unit_cost": 10.0,
        "selling_price": 20.0,
        "creator_or_brand": "Existing Author",
        "units_sold_30d": 3,
        "units_sold_60d": 6,
        "units_sold_90d": 9,
        "days_in_stock": 45,
    }
    fields.update(overrides)

    with SessionLocal() as db:
        product = Product(**fields)
        db.add(product)
        db.commit()
        db.refresh(product)
        return product.id


def test_preview_validates_without_writing(client):
    content = make_csv(
        make_csv_row("SKU-NEW"),
        make_csv_row("SKU-BAD", quantity_in_stock="-1"),
    )

    response = client.post(
        "/inventory/preview",
        files=upload(content),
    )

    assert response.status_code == 200, response.text
    data = response.json()

    assert data["total_rows"] == 2
    assert data["new_count"] == 1
    assert data["invalid_count"] == 1
    assert data["update_count"] == 0
    assert data["rows"][0]["action"] == "new"
    assert data["rows"][1]["action"] == "invalid"
    assert any(
        issue["field"] == "quantity_in_stock"
        for issue in data["rows"][1]["errors"]
    )

    # Preview must not create or update any products.
    with SessionLocal() as db:
        products = db.scalars(select(Product)).all()
        assert products == []


def test_preview_marks_existing_sku_for_update(client):
    seed_product()

    response = client.post(
        "/inventory/preview",
        files=upload(make_csv(make_csv_row("SKU-EXISTS"))),
    )

    assert response.status_code == 200, response.text
    data = response.json()

    assert data["update_count"] == 1
    assert data["new_count"] == 0
    assert data["rows"][0]["action"] == "will_update"


def test_import_creates_updates_and_skips_invalid_rows(client):
    existing_id = seed_product()

    content = make_csv(
        make_csv_row(
            "SKU-EXISTS",
            product_name="Updated Book",
            quantity_in_stock="8",
        ),
        make_csv_row("SKU-NEW"),
        make_csv_row("SKU-BAD", quantity_in_stock="-2"),
    )

    response = client.post(
        "/inventory/import",
        files=upload(content),
    )

    assert response.status_code == 200, response.text
    data = response.json()

    assert data["created_count"] == 1
    assert data["updated_count"] == 1
    assert data["skipped_count"] == 1
    assert data["imported_count"] == 2

    assert [row["action"] for row in data["rows"]] == [
        "updated", "created", "skipped"
    ]

    with SessionLocal() as db:
        updated = db.scalar(
            select(Product).where(
                Product.retailer_id == "demo",
                Product.sku == "SKU-EXISTS",
            )
        )
        new_product = db.scalar(
            select(Product).where(
                Product.retailer_id == "demo",
                Product.sku == "SKU-NEW",
            )
        )

        assert updated is not None
        assert updated.id == existing_id
        assert updated.product_name == "Updated Book"
        assert updated.quantity_in_stock == 8

        # Blank ordinary optional cells preserve existing values.
        assert updated.creator_or_brand == "Existing Author"

        assert new_product is not None
        assert new_product.creator_or_brand is None
        assert new_product.units_sold_30d is None


def test_import_rejects_file_level_error(client):
    invalid_csv = (
        b"product_name,category,quantity_in_stock,unit_cost,selling_price\n"
        b"Book,Books,2,10,20\n"
    )

    response = client.post(
        "/inventory/import",
        files=upload(invalid_csv),
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_inventory_file"

    with SessionLocal() as db:
        assert db.scalars(select(Product)).all() == []


def test_preview_rejects_non_csv_filename(client):
    response = client.post(
        "/inventory/preview",
        files=upload(make_csv(make_csv_row()), "inventory.txt"),
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_inventory_file"


def test_dashboard_returns_current_inventory_metrics(client):
    seed_product(
        sku="SLOW-1",
        units_sold_30d=0,
        units_sold_60d=0,
        units_sold_90d=0,
        days_in_stock=120,
        quantity_in_stock=10,
        unit_cost=15.0,
    )
    seed_product(
        sku="UNKNOWN-1",
        units_sold_30d=None,
        units_sold_60d=None,
        units_sold_90d=None,
        days_in_stock=None,
    )

    response = client.get("/inventory/dashboard")

    assert response.status_code == 200, response.text
    data = response.json()

    assert data["total_products"] == 2
    assert data["needs_attention_count"] >= 1
    assert data["not_enough_data_count"] == 1
    assert data["total_inventory_cost_tied_up"] == 190.0
    assert data["thresholds"]["sales_window_days"] == 30
    assert data["thresholds"]["aged_stock_days"] == 90
    assert len(data["products_needing_attention"]) >= 1


def test_dashboard_api_exposes_slow_moving_rules_and_supporting_values(client):
    seed_product(
        sku="T07-UNKNOWN",
        product_name="Unknown History",
        quantity_in_stock=7,
        unit_cost=10.0,
        units_sold_30d=None,
        units_sold_60d=None,
        units_sold_90d=None,
        days_in_stock=None,
    )
    seed_product(
        sku="T07-ZERO",
        product_name="Zero Recent Sales",
        quantity_in_stock=10,
        unit_cost=15.0,
        units_sold_30d=0,
        units_sold_60d=0,
        units_sold_90d=0,
        days_in_stock=30,
    )
    seed_product(
        sku="T07-AGED",
        product_name="Aged Stock",
        quantity_in_stock=5,
        unit_cost=20.0,
        units_sold_30d=None,
        units_sold_60d=None,
        units_sold_90d=None,
        days_in_stock=90,
    )
    seed_product(
        sku="T07-VELOCITY",
        product_name="Low Sales Velocity",
        quantity_in_stock=61,
        unit_cost=15.0,
        units_sold_30d=10,
        units_sold_60d=20,
        units_sold_90d=30,
        days_in_stock=30,
    )
    seed_product(
        sku="T07-TOO-NEW",
        product_name="Too New for Sales Window",
        quantity_in_stock=100,
        unit_cost=5.0,
        units_sold_30d=1,
        units_sold_60d=2,
        units_sold_90d=3,
        days_in_stock=20,
    )

    response = client.get("/inventory/dashboard")
    assert response.status_code == 200, response.text

    data = response.json()

    assert data["total_products"] == 5
    assert data["needs_attention_count"] == 3
    assert data["not_enough_data_count"] == 1
    assert data["total_inventory_cost_tied_up"] == 1735.0
    assert data["flagged_inventory_cost_tied_up"] == 1165.0

    assert data["thresholds"]["sales_window_days"] == 30
    assert data["thresholds"]["no_recent_sales_min_stock_days"] == 30
    assert data["thresholds"]["aged_stock_days"] == 90
    assert data["thresholds"]["low_sales_cover_days"] == 180

    attention = data["products_needing_attention"]
    by_sku = {product["sku"]: product for product in attention}

    assert [product["sku"] for product in attention] == [
        "T07-VELOCITY",
        "T07-ZERO",
        "T07-AGED",
    ]

    assert by_sku["T07-ZERO"]["rules_triggered"] == ["no_recent_sales"]
    assert any(
        "zero sales" in explanation.lower()
        for explanation in by_sku["T07-ZERO"]["explanations"]
    )

    assert by_sku["T07-AGED"]["rules_triggered"] == ["aged_stock"]
    assert any(
        "90 days" in explanation
        for explanation in by_sku["T07-AGED"]["explanations"]
    )

    velocity = by_sku["T07-VELOCITY"]
    assert velocity["rules_triggered"] == ["low_sales_velocity"]
    assert velocity["stock_cover_days"] == 183.0
    assert any(
        "183.00 days" in explanation
        for explanation in velocity["explanations"]
    )

    insufficient = data["products_not_enough_data"]
    assert len(insufficient) == 1
    assert insufficient[0]["sku"] == "T07-UNKNOWN"
    assert insufficient[0]["status"] == "not_enough_data_to_assess"
    assert any(
        "not enough data to assess" in explanation.lower()
        for explanation in insufficient[0]["explanations"]
    )

    returned_skus = {
        product["sku"]
        for product in attention + insufficient
    }
    assert "T07-TOO-NEW" not in returned_skus

    assert data["rule_counts"]["no_recent_sales"] == 1
    assert data["rule_counts"]["aged_stock"] == 1
    assert data["rule_counts"]["low_sales_velocity"] == 1
