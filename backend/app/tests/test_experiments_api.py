from app.tests.conftest import (FakeResponse, entity, insights_payload, make_product,
                                search_payload)
from app.db.session import SessionLocal
from app.models import Product
import httpx


def new_experiment(client, product_pk, **over):
    body = {"product_pk": product_pk, "strategy_type": "promotion", "title": "Promotion",
            "proposed_action": "Run a short controlled promotion", "proposed_price": 449.0, "estimated_cost": 200.0,
            "calculated_margin_pct": 37.5}
    body.update(over)
    r = client.post("/experiments", json=body)
    assert r.status_code == 201, r.text
    return r.json()


OUTCOME = {
    "items": [{"product_id": "B001", "units_sold": 20, "actual_selling_price": 500.0, "unit_cost": 350.0}],
    "additional_costs": 200.0, "target_units_sold": 20, "actual_days": 14,
    "baseline_units": 18, "baseline_days": 14, "stock_at_start": 24,
}


def run_to_running(client, pk):
    e = new_experiment(client, pk)
    assert client.post(f"/experiments/{e['id']}/approve", json={"approved_by": "owner"}).json()["status"] == "approved"
    r = client.post(f"/experiments/{e['id']}/start", json={"start_date": "2026-11-01", "end_date": "2026-11-14"})
    assert r.json()["status"] == "running"
    return e["id"]


def test_full_lifecycle_and_calculations(client):
    eid = run_to_running(client, make_product())
    r = client.post(f"/experiments/{eid}/outcome", json=OUTCOME)
    assert r.status_code == 201, r.text
    calc = r.json()["calculated"]
    assert calc["revenue"] == 10000.0 and calc["gross_profit"] == 2800.0 and calc["gross_margin_pct"] == 28.0
    assert calc["baseline_comparison"]["units_above_baseline_rate"] == 2.0
    assert client.get(f"/experiments/{eid}").json()["status"] == "completed"
    assert client.get(f"/experiments/{eid}/outcome").status_code == 200


def test_cannot_start_before_approval(client):
    e = new_experiment(client, make_product())
    r = client.post(f"/experiments/{e['id']}/start", json={"start_date": "2026-11-01", "end_date": "2026-11-14"})
    assert r.status_code == 409 and r.json()["error"] == "invalid_state"


def test_cannot_record_outcome_unless_running(client):
    e = new_experiment(client, make_product())
    assert client.post(f"/experiments/{e['id']}/outcome", json=OUTCOME).status_code == 409


def test_edit_only_while_proposed(client):
    e = new_experiment(client, make_product())
    assert client.patch(f"/experiments/{e['id']}", json={"proposed_price": 749.0}).json()["proposed_price"] == 749.0
    client.post(f"/experiments/{e['id']}/approve")
    assert client.patch(f"/experiments/{e['id']}", json={"proposed_price": 699.0}).status_code == 409


def test_reject_is_final(client):
    e = new_experiment(client, make_product())
    assert client.post(f"/experiments/{e['id']}/reject").json()["status"] == "rejected"
    assert client.post(f"/experiments/{e['id']}/approve").status_code == 409


def test_validation_errors(client):
    pk = make_product()
    assert client.post("/experiments", json={"product_pk": pk, "strategy_type": "bundle", "title": "x",
                                             "proposed_action": "y", "proposed_price": -5}).status_code == 422
    assert client.post("/experiments", json={"product_pk": 9999, "strategy_type": "bundle", "title": "x",
                                             "proposed_action": "y"}).status_code == 404
    eid = run_to_running(client, pk)
    bad = {**OUTCOME, "items": [{**OUTCOME["items"][0], "units_sold": -1}]}
    assert client.post(f"/experiments/{eid}/outcome", json=bad).status_code == 422


def test_units_exceeding_stock_rejected(client):
    eid = run_to_running(client, make_product(qty=24))
    bad = {**OUTCOME, "target_units_sold": 30, "stock_at_start": 24,
           "items": [{**OUTCOME["items"][0], "units_sold": 30}]}
    r = client.post(f"/experiments/{eid}/outcome", json=bad)
    assert r.status_code == 422 and r.json()["error"] == "constraint_violation"


def test_summary_keeps_simulated_separate(client):
    pk = make_product()
    real = run_to_running(client, pk)
    sim_pk = make_product(sku="B002")
    sim = run_to_running(client, sim_pk)
    client.post(f"/experiments/{real}/outcome", json=OUTCOME)
    simulated_outcome = {**OUTCOME, "items": [{**OUTCOME["items"][0], "product_id": "B002"}],
                         "is_simulated": True}
    client.post(f"/experiments/{sim}/outcome", json=simulated_outcome)
    s = client.get("/experiments/summary").json()
    assert s["observed"]["completed_experiments"] == 1 and s["simulated"]["completed_experiments"] == 1
    assert s["observed"]["gross_profit"] == 2800.0
    assert client.get(f"/experiments/{sim}/outcome").json()["limitations"][0].startswith("SIMULATED")


# ---------------- Qloo endpoints (mocked Qloo) ----------------
def test_resolve_then_insights_stores_evidence(client, fake):
    pk = make_product()
    fake.push("/search", FakeResponse(200, search_payload(entity("A1", "The God of Small Things", description="A novel by Arundhati Roy"))))
    m = client.post(f"/products/{pk}/qloo/resolve").json()
    assert m["match_status"] == "strong" and m["qloo_entity_id"] == "A1" and m["coverage_gap"] is False
    fake.push("/v2/insights", FakeResponse(200, insights_payload(
        {"entity_id": "B1", "name": "Norwegian Wood", "query": {"affinity": 0.9}})))
    r = client.post(f"/products/{pk}/qloo/insights", json={"take": 5})
    assert r.status_code == 200 and r.json()["result"]["entities"][0]["name"] == "Norwegian Wood"
    assert r.json()["evidence_id"] > 0


def test_ambiguous_blocks_insights_until_confirmed(client, fake):
    pk = make_product(name="Dune", creator=None)
    fake.push("/search", FakeResponse(200, search_payload(entity("X1", "Dune"), entity("X2", "Dune"))))
    assert client.post(f"/products/{pk}/qloo/resolve").json()["match_status"] == "ambiguous"
    r = client.post(f"/products/{pk}/qloo/insights", json={})
    assert r.status_code == 409 and r.json()["error"] == "needs_resolution"
    assert client.post(f"/products/{pk}/qloo/confirm", json={"entity_id": "X2"}).json()["verification_status"] == "confirmed"
    fake.push("/v2/insights", FakeResponse(200, insights_payload({"entity_id": "B1", "name": "Foundation"})))
    assert client.post(f"/products/{pk}/qloo/insights", json={}).status_code == 200


def test_force_resolve_cannot_overwrite_a_rejected_human_decision(client, fake):
    pk = make_product()
    fake.push("/search", FakeResponse(200, search_payload(entity("A1", "The God of Small Things", description="A novel by Arundhati Roy"))))
    initial = client.post(f"/products/{pk}/qloo/resolve").json()
    rejected = client.post(f"/products/{pk}/qloo/reject")
    assert rejected.status_code == 200 and rejected.json()["verification_status"] == "rejected"

    # No fake Qloo response is queued after the human decision. A force refresh
    # must return the stored mapping without making another upstream call.
    refreshed = client.post(f"/products/{pk}/qloo/resolve?force=true")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["verification_status"] == "rejected"
    assert refreshed.json()["qloo_entity_id"] == initial["qloo_entity_id"]
    assert len([call for call in fake.calls if call[0] == "/search"]) == 1


def test_force_resolve_cannot_overwrite_a_confirmed_human_decision(client, fake):
    pk = make_product()
    fake.push("/search", FakeResponse(200, search_payload(entity("A1", "The God of Small Things", description="A novel by Arundhati Roy"))))
    initial = client.post(f"/products/{pk}/qloo/resolve").json()
    chosen = initial["qloo_entity_id"]
    confirmed = client.post(f"/products/{pk}/qloo/confirm", json={"entity_id": chosen})
    assert confirmed.status_code == 200 and confirmed.json()["verification_status"] == "confirmed"

    refreshed = client.post(f"/products/{pk}/qloo/resolve?force=true")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["verification_status"] == "confirmed"
    assert refreshed.json()["qloo_entity_id"] == chosen
    assert len([call for call in fake.calls if call[0] == "/search"]) == 1


def test_qloo_human_decision_cannot_be_switched_after_confirmation_or_rejection(client, fake):
    pk_confirmed = make_product(name="Confirmed title", creator="A. Writer")
    with SessionLocal() as db:
        other = Product(sku="R002", product_name="Rejected title", creator_or_brand="B. Writer",
                        quantity_in_stock=8, unit_cost=100.0, selling_price=250.0)
        db.add(other)
        db.commit()
        pk_rejected = other.id
    fake.push("/search", FakeResponse(200, search_payload(entity("C1", "Confirmed title", description="A novel by A. Writer"))))
    fake.push("/search", FakeResponse(200, search_payload(entity("R1", "Rejected title", description="A novel by B. Writer"))))
    c = client.post(f"/products/{pk_confirmed}/qloo/resolve").json()
    r = client.post(f"/products/{pk_rejected}/qloo/resolve").json()

    assert client.post(f"/products/{pk_confirmed}/qloo/confirm", json={"entity_id": c["qloo_entity_id"]}).status_code == 200
    assert client.post(f"/products/{pk_confirmed}/qloo/reject").status_code == 409
    assert client.post(f"/products/{pk_rejected}/qloo/reject").status_code == 200
    # Confirmation on the rejected map is disallowed even if that entity was a candidate.
    assert client.post(
        f"/products/{pk_rejected}/qloo/confirm", json={"entity_id": r["qloo_entity_id"]}
    ).status_code == 409


def test_no_match_is_reported_as_coverage_gap(client, fake):
    pk = make_product(name="Obscure Local Poetry")
    fake.push("/search", FakeResponse(200, search_payload()))
    m = client.post(f"/products/{pk}/qloo/resolve").json()
    assert m["match_status"] == "none" and m["coverage_gap"] is True
    assert client.post(f"/products/{pk}/qloo/insights", json={}).status_code == 409


def test_qloo_timeout_maps_to_504(client, fake):
    pk = make_product()
    t = httpx.TimeoutException("slow")
    fake.push("/search", t, t, t)
    r = client.post(f"/products/{pk}/qloo/resolve")
    assert r.status_code == 504 and r.json()["error"] == "qloo_timeout"


def test_status_endpoint_reports_failure_honestly(client, fake):
    fake.push("/search", FakeResponse(401, {}))
    r = client.get("/qloo/status").json()
    assert r["ok"] is False and r["error"] == "auth"


def test_quantity_mismatch_between_item_and_target_is_rejected(client):
    eid = run_to_running(client, make_product())
    bad = {**OUTCOME, "target_units_sold": 99,
           "items": [{**OUTCOME["items"][0], "units_sold": 5}]}
    r = client.post(f"/experiments/{eid}/outcome", json=bad)
    assert r.status_code == 422 and "does not match" in r.json()["message"]


def test_client_cannot_spoof_unit_cost(client):
    eid = run_to_running(client, make_product())
    spoofed = {**OUTCOME, "items": [{**OUTCOME["items"][0], "unit_cost": 1.0}]}
    r = client.post(f"/experiments/{eid}/outcome", json=spoofed)
    assert r.status_code == 201
    assert r.json()["calculated"]["cost_of_goods_sold"] == 7000.0
    # Historical audit inputs show the server-bound cost, not the spoofed request value.
    assert r.json()["inputs"]["items"][0]["unit_cost"] == "350.0"


def test_actual_days_must_match_saved_experiment_dates(client):
    eid = run_to_running(client, make_product())
    r = client.post(f"/experiments/{eid}/outcome", json={**OUTCOME, "actual_days": 13})
    assert r.status_code == 422 and "must match the saved experiment date range" in r.json()["message"]


def test_active_experiments_cannot_double_commit_same_sku(client):
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models import ExperimentStockReservation, Product

    pk = make_product(qty=24, sku="STOCK-LOCK-1")
    first = new_experiment(client, pk)
    second = new_experiment(client, pk)

    approved = client.post(f"/experiments/{first['id']}/approve", json={"approved_by": "owner"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    conflict = client.post(f"/experiments/{second['id']}/approve", json={"approved_by": "owner"})
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "stock_commitment_conflict"
    assert "STOCK-LOCK-1" in conflict.json()["conflicting_skus"]

    with SessionLocal() as db:
        quantity = db.scalar(select(Product.quantity_in_stock).where(Product.id == pk))
        reservations = db.scalars(select(ExperimentStockReservation).where(
            ExperimentStockReservation.product_pk == pk
        )).all()
    assert quantity == 24  # reservations never decrement physical on-hand stock
    assert len(reservations) == 1 and reservations[0].experiment_id == first["id"]

    assert client.post(f"/experiments/{first['id']}/cancel").json()["status"] == "cancelled"
    retry = client.post(f"/experiments/{second['id']}/approve", json={"approved_by": "owner"})
    assert retry.status_code == 200 and retry.json()["status"] == "approved"


def test_bundle_reserves_target_and_each_component(client):
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models import ExperimentStockReservation

    target = make_product(sku="BUNDLE-TARGET")
    partner = make_product(sku="BUNDLE-PARTNER", name="Bundle Partner")
    experiment = new_experiment(client, target, strategy_type="bundle", proposed_price=850.0,
                                estimated_cost=200.0, bundle_product_pks=[partner])
    response = client.post(f"/experiments/{experiment['id']}/approve")
    assert response.status_code == 200
    with SessionLocal() as db:
        reserved = set(db.scalars(select(ExperimentStockReservation.product_pk).where(
            ExperimentStockReservation.experiment_id == experiment["id"]
        )).all())
    assert reserved == {target, partner}


def test_completion_releases_all_bundle_reservations(client):
    from sqlalchemy import select
    from app.db.session import SessionLocal
    from app.models import ExperimentStockReservation

    target = make_product(sku="BUNDLE-COMPLETE-TARGET", qty=10)
    partner = make_product(sku="BUNDLE-COMPLETE-PARTNER", name="Bundle Partner")
    experiment = new_experiment(client, target, strategy_type="bundle", proposed_price=850.0,
                                estimated_cost=200.0, bundle_product_pks=[partner])
    eid = experiment["id"]
    assert client.post(f"/experiments/{eid}/approve").status_code == 200
    assert client.post(f"/experiments/{eid}/start", json={
        "start_date": "2026-11-01", "end_date": "2026-11-14"
    }).status_code == 200
    outcome = {
        "items": [
            {"product_id": "BUNDLE-COMPLETE-TARGET", "units_sold": 2, "actual_selling_price": 799},
            {"product_id": "BUNDLE-COMPLETE-PARTNER", "units_sold": 2, "actual_selling_price": 400},
        ],
        "additional_costs": 0, "target_units_sold": 2, "actual_days": 14,
        "baseline_units": 1, "baseline_days": 14,
        "stock_at_start": 10,
    }
    result = client.post(f"/experiments/{eid}/outcome", json=outcome)
    assert result.status_code == 201, result.text
    with SessionLocal() as db:
        remaining = db.scalars(select(ExperimentStockReservation).where(
            ExperimentStockReservation.experiment_id == eid
        )).all()
    assert remaining == []
