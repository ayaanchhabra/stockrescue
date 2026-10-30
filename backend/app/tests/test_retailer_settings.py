from app.db.session import SessionLocal
from app.models import RetailerSettings


def test_settings_get_returns_documented_defaults(client):
    response = client.get("/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["currency"] == "INR"
    assert data["constraints"]["min_margin_pct"] == 15.0
    assert data["strategy"]["test_units"] == 3
    assert data["ranking"]["discount_last"] is True
    assert data["slow_moving"]["aged_stock_days"] == 90


def test_settings_put_persists_for_authenticated_retailer_only(client, other_client):
    payload = {
        "currency": "INR",
        "constraints": {
            "min_margin_pct": 22, "max_discount_pct": 18,
            "max_campaign_budget": 750, "restricted_product_ids": ["SKU-BLOCKED"],
        },
        "strategy": {
            "test_units": 5, "test_days": 10, "bundle_discount_pct": 8,
            "promo_discount_pct": 12, "min_promo_discount_pct": 4,
            "max_bundle_attempts": 2, "max_display_titles": 4,
            "bundle_campaign_cost": 40, "reposition_campaign_cost": 60,
            "promotion_campaign_cost": 20,
        },
        "ranking": {
            "weights": {"feasibility": 0.4, "evidence": 0.3, "simplicity": 0.2, "cost": 0.1},
            "discount_last": True, "headroom_full_pts": 25,
            "stock_cover_full_multiple": 2, "ambiguous_evidence_cap": 0.25,
            "max_results": 2, "close_score_gap": 0.03,
        },
        "slow_moving": {
            "no_recent_sales_min_stock_days": 35, "aged_stock_days": 100,
            "low_sales_cover_days": 150,
        },
    }
    saved = client.put("/settings", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json() == payload
    assert client.get("/settings").json() == payload
    # Settings are tenant-scoped even though both are in the same database.
    assert other_client.get("/settings").json()["constraints"]["min_margin_pct"] == 15.0
    with SessionLocal() as db:
        rows = db.query(RetailerSettings).all()
        assert len(rows) == 1 and rows[0].retailer_id == "demo"


def test_settings_reject_invalid_weights_and_unknown_fields(client):
    current = client.get("/settings").json()
    current["ranking"]["weights"] = {
        "feasibility": 0.5, "evidence": 0.3, "simplicity": 0.2, "cost": 0.2,
    }
    assert client.put("/settings", json=current).status_code == 422
    current = client.get("/settings").json()
    current["unexpected"] = True
    assert client.put("/settings", json=current).status_code == 422


def test_dashboard_uses_saved_slow_moving_thresholds(client):
    payload = client.get("/settings").json()
    payload["slow_moving"]["aged_stock_days"] = 20
    payload["slow_moving"]["no_recent_sales_min_stock_days"] = 5
    assert client.put("/settings", json=payload).status_code == 200
    from app.tests.test_inventory_api import seed_product
    seed_product(sku="CUSTOM-AGE", days_in_stock=25, units_sold_30d=None,
                 units_sold_60d=None, units_sold_90d=None, quantity_in_stock=2)
    response = client.get("/inventory/dashboard")
    assert response.status_code == 200
    assert response.json()["thresholds"]["aged_stock_days"] == 20
    assert "CUSTOM-AGE" in {p["sku"] for p in response.json()["products_needing_attention"]}


def test_product_sales_history_exposes_dated_import_snapshots(client):
    from app.tests.test_inventory_api import make_csv, make_csv_row, upload
    from app.models import Product
    from sqlalchemy import select
    from app.db.session import SessionLocal

    row = make_csv_row("SNAP-1", units_sold_30d="4", units_sold_60d="9",
                       units_sold_90d="13", days_in_stock="75")
    imported = client.post("/inventory/import", files=upload(make_csv(row)))
    assert imported.status_code == 200, imported.text
    with SessionLocal() as db:
        product = db.scalar(select(Product).where(Product.sku == "SNAP-1"))
        pk = product.id
    response = client.get(f"/inventory/products/{pk}/sales-history")
    assert response.status_code == 200, response.text
    snapshots = response.json()["snapshots"]
    assert len(snapshots) == 1
    assert snapshots[0]["units_sold_30d"] == 4
    assert snapshots[0]["units_sold_90d"] == 13
    assert snapshots[0]["days_in_stock"] == 75


def test_direct_experiment_uses_and_persists_retailer_settings_snapshot(client):
    from app.db.session import SessionLocal
    from app.models import RescueExperiment
    from app.tests.conftest import make_product
    from app.services.experiment_service import create_experiment
    from app.schemas.experiments import ExperimentCreate

    settings = client.get("/settings").json()
    settings["constraints"]["max_discount_pct"] = 15.0
    assert client.put("/settings", json=settings).status_code == 200

    product_pk = make_product()
    payload = ExperimentCreate(
        product_pk=product_pk,
        strategy_type="promotion",
        title="Snapshot test",
        proposed_action="Run a controlled price test",
        proposed_price=449.0,
        estimated_cost=100.0,
    )
    with SessionLocal() as db:
        experiment = create_experiment(db, payload)
        experiment_id = experiment.id
        assert experiment.settings_snapshot["constraints"]["max_discount_pct"] == 15.0

    # Change current retailer settings after proposal creation. Approval must
    # continue using the exact validated rule snapshot captured by this proposal.
    settings["constraints"]["max_discount_pct"] = 5.0
    assert client.put("/settings", json=settings).status_code == 200
    approved = client.post(f"/experiments/{experiment_id}/approve")
    assert approved.status_code == 200, approved.text
    with SessionLocal() as db:
        saved = db.get(RescueExperiment, experiment_id)
        assert saved.settings_snapshot["constraints"]["max_discount_pct"] == 15.0


def test_direct_experiment_creation_enforces_saved_retailer_margin(client):
    from app.tests.conftest import make_product

    settings = client.get("/settings").json()
    settings["constraints"]["min_margin_pct"] = 23.0
    assert client.put("/settings", json=settings).status_code == 200
    product_pk = make_product()
    response = client.post("/experiments", json={
        "product_pk": product_pk,
        "strategy_type": "promotion",
        "title": "Must fail margin",
        "proposed_action": "Try an insufficient-margin price",
        "proposed_price": 449.0,
        "estimated_cost": 100.0,
    })
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "constraint_violation"


def test_settings_put_is_allowed_by_cors_preflight(client):
    response = client.options("/settings", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert response.status_code == 200
    assert "PUT" in response.headers.get("access-control-allow-methods", "")
