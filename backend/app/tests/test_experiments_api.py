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
    real, sim = run_to_running(client, pk), run_to_running(client, pk)
    client.post(f"/experiments/{real}/outcome", json=OUTCOME)
    client.post(f"/experiments/{sim}/outcome", json={**OUTCOME, "is_simulated": True})
    s = client.get("/experiments/summary").json()
    assert s["observed"]["completed_experiments"] == 1 and s["simulated"]["completed_experiments"] == 1
    assert s["observed"]["gross_profit"] == 2800.0
    assert client.get(f"/experiments/{sim}/outcome").json()["limitations"][0].startswith("SIMULATED")


# ---------------- Qloo endpoints (mocked Qloo) ----------------
def test_resolve_then_insights_stores_evidence(client, fake):
    pk = make_product()
    fake.push("/search", FakeResponse(200, search_payload(entity("A1", "The God of Small Things"))))
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
    fake.push("/search", FakeResponse(200, search_payload(entity("A1", "The God of Small Things"))))
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
    fake.push("/search", FakeResponse(200, search_payload(entity("A1", "The God of Small Things"))))
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
    pk_confirmed = make_product(name="Confirmed title")
    with SessionLocal() as db:
        other = Product(sku="R002", product_name="Rejected title", creator_or_brand=None,
                        quantity_in_stock=8, unit_cost=100.0, selling_price=250.0)
        db.add(other)
        db.commit()
        pk_rejected = other.id
    fake.push("/search", FakeResponse(200, search_payload(entity("C1", "Confirmed title"))))
    fake.push("/search", FakeResponse(200, search_payload(entity("R1", "Rejected title"))))
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
