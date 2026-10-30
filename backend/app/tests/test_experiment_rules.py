"""Experiments obey the retailer's hard rules on every path (create, edit, approve),
the margin is always computed by the server, and a plan's strategy cannot be turned
into two live experiments. Uses the same TestClient setup as the other API tests."""
from app.db.session import SessionLocal
from app.models import Product, QlooEvidence
from app.models import RescuePlan as PlanRow
from app.tests.conftest import make_product

# make_product(): cost 350, price 499, 24 in stock. Default rule: margin >= 15%,
# discount <= 25%, budget Rs 2000, 3 units needed.


def body(pk, **over):
    b = {"product_pk": pk, "strategy_type": "promotion", "title": "Promo", "proposed_action": "do it",
         "proposed_price": 449.0, "estimated_cost": 50.0}
    b.update(over)
    return b


def saved_plan(db, pk, *, constraints=None, strategy_type="promotion", title="Promo", partners=()):
    partner_rows = [{"product_id": str(value), "role": "partner"} for value in partners]
    plan_json = {
        "product_id": str(pk),
        "strategies": [{
            "type": strategy_type, "name": title,
            "products": [{"product_id": str(pk), "role": "target"}, *partner_rows],
            "evidence": [],
        }],
    }
    plan = PlanRow(retailer_id="demo", product_ids=[pk, *partners], status="draft",
                   constraints_snapshot=constraints or {}, plan_json=plan_json)
    db.add(plan)
    db.commit()
    return plan.id


def test_create_ignores_a_client_margin_and_stores_the_calculated_one(client):
    pk = make_product()
    r = client.post("/experiments", json=body(pk, calculated_margin_pct=99.0))
    assert r.status_code == 201
    assert r.json()["calculated_margin_pct"] == round((449 - 350) / 449 * 100, 2)


def test_create_below_the_margin_floor_is_rejected(client):
    pk = make_product()
    r = client.post("/experiments", json=body(pk, proposed_price=380.0))  # 7.9% margin
    assert r.status_code == 422 and r.json()["error"] == "constraint_violation"
    assert "minimum" in r.json()["message"]


def test_create_checked_strategy_without_price_is_rejected(client):
    pk = make_product()
    r = client.post("/experiments", json=body(pk, proposed_price=None))
    assert r.status_code == 422 and r.json()["error"] == "constraint_violation"
    assert "price is required" in r.json()["message"]


def test_edit_checked_strategy_cannot_clear_price(client):
    pk = make_product()
    e = client.post("/experiments", json=body(pk)).json()
    r = client.patch(f"/experiments/{e['id']}", json={"proposed_price": None})
    assert r.status_code == 422 and r.json()["error"] == "constraint_violation"
    saved = client.get(f"/experiments/{e['id']}").json()
    assert saved["proposed_price"] == 449.0
    assert saved["calculated_margin_pct"] == round((449 - 350) / 449 * 100, 2)


def test_edit_cannot_push_a_price_below_the_rules(client):
    pk = make_product()
    e = client.post("/experiments", json=body(pk)).json()
    r = client.patch(f"/experiments/{e['id']}", json={"proposed_price": 380.0, "calculated_margin_pct": 50.0})
    assert r.status_code == 422 and r.json()["error"] == "constraint_violation"
    assert client.get(f"/experiments/{e['id']}").json()["proposed_price"] == 449.0  # unchanged


def test_edit_recomputes_the_margin_and_ignores_the_client_value(client):
    pk = make_product()
    e = client.post("/experiments", json=body(pk)).json()
    r = client.patch(f"/experiments/{e['id']}", json={"proposed_price": 460.0, "calculated_margin_pct": 99.0})
    assert r.status_code == 200
    assert r.json()["calculated_margin_pct"] == round((460 - 350) / 460 * 100, 2)


def test_edit_cannot_add_a_discount_beyond_the_cap(client):
    pk = make_product()
    e = client.post("/experiments", json=body(pk)).json()
    other = _second_product()
    r = client.patch(f"/experiments/{e['id']}", json={"bundle_product_pks": [other], "proposed_price": 300.0})
    assert r.status_code == 422


def _second_product(sku="B002"):
    with SessionLocal() as db:
        p = Product(sku=sku, product_name="Partner", quantity_in_stock=10, unit_cost=100.0,
                    selling_price=400.0)
        db.add(p)
        db.commit()
        return p.id


def test_approve_rechecks_current_stock(client):
    pk = make_product()
    e = client.post("/experiments", json=body(pk)).json()
    with SessionLocal() as db:  # stock sold down after the proposal was made
        db.get(Product, pk).quantity_in_stock = 1
        db.commit()
    r = client.post(f"/experiments/{e['id']}/approve")
    assert r.status_code == 422 and r.json()["error"] == "constraint_violation"
    assert client.get(f"/experiments/{e['id']}").json()["status"] == "proposed"


def test_approve_rechecks_current_prices(client):
    pk = make_product()
    e = client.post("/experiments", json=body(pk)).json()
    with SessionLocal() as db:  # supplier raised the cost
        db.get(Product, pk).unit_cost = 440.0
        db.commit()
    assert client.post(f"/experiments/{e['id']}/approve").status_code == 422


def test_approve_still_works_when_the_rules_hold(client):
    pk = make_product()
    e = client.post("/experiments", json=body(pk)).json()
    r = client.post(f"/experiments/{e['id']}/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved"


def test_an_invalid_transition_is_still_reported_as_such(client):
    pk = make_product()
    e = client.post("/experiments", json=body(pk)).json()
    client.post(f"/experiments/{e['id']}/reject")
    assert client.post(f"/experiments/{e['id']}/approve").status_code == 409


def test_other_strategy_is_rejected_at_the_api_boundary(client):
    pk = make_product()
    r = client.post("/experiments", json=body(pk, strategy_type="other", proposed_price=None))
    assert r.status_code == 422


def test_plan_rules_are_used_when_the_experiment_belongs_to_a_plan(client):
    pk = make_product()
    with SessionLocal() as db:
        plan_id = saved_plan(db, pk, constraints={"min_margin_pct": 40.0, "max_discount_pct": 25.0,
                                                  "max_campaign_budget": 2000.0, "restricted_product_ids": []})
    r = client.post("/experiments", json=body(pk, plan_id=plan_id, proposed_price=449.0))  # margin 22%
    assert r.status_code == 422 and "40.00%" in r.json()["message"]


def test_restricted_product_in_the_plan_rules_blocks_the_experiment(client):
    pk = make_product()
    with SessionLocal() as db:
        plan_id = saved_plan(db, pk, constraints={"restricted_product_ids": [str(pk)]})
    assert client.post("/experiments", json=body(pk, plan_id=plan_id)).status_code == 422


def test_same_plan_strategy_cannot_become_two_live_experiments(client):
    pk = make_product()
    with SessionLocal() as db:
        plan_id = saved_plan(db, pk)
    first = client.post("/experiments", json=body(pk, plan_id=plan_id))
    assert first.status_code == 201
    again = client.post("/experiments", json=body(pk, plan_id=plan_id))
    assert again.status_code == 409 and again.json()["error"] == "duplicate_experiment"
    client.post(f"/experiments/{first.json()['id']}/reject")  # a rejected one may be re-proposed
    assert client.post("/experiments", json=body(pk, plan_id=plan_id)).status_code == 201


def test_margin_just_below_floor_is_rejected_without_display_rounding(client):
    pk = make_product()
    # (price - cost) / price = 14.996% exactly; the displayed value rounds to 15.00%.
    price = 350.0 / (1 - 0.14996)
    r = client.post("/experiments", json=body(pk, proposed_price=price))
    assert r.status_code == 422 and r.json()["error"] == "constraint_violation"


def test_saved_plan_cannot_be_combined_with_an_unrelated_target_product(client):
    target = make_product()
    with SessionLocal() as db:
        unrelated_row = Product(sku="B099", product_name="Unrelated", creator_or_brand="Another Author",
                                quantity_in_stock=24, unit_cost=350.0, selling_price=499.0)
        db.add(unrelated_row)
        db.commit()
        unrelated = unrelated_row.id
    with SessionLocal() as db:
        plan_id = saved_plan(db, target)
    r = client.post("/experiments", json=body(unrelated, plan_id=plan_id))
    assert r.status_code == 422
    assert "does not match" in r.json()["message"]


def test_saved_plan_cannot_be_combined_with_unrelated_partner(client):
    target = make_product()
    partner = _second_product()
    unrelated_partner = _second_product("B003")
    with SessionLocal() as db:
        plan_id = saved_plan(db, target, strategy_type="bundle", title="Bundle", partners=[partner])
    r = client.post("/experiments", json=body(
        target, plan_id=plan_id, strategy_type="bundle", title="Bundle",
        bundle_product_pks=[unrelated_partner],
    ))
    assert r.status_code == 422


def test_unsupported_strategy_fails_closed_in_service():
    # The API schema rejects this enum too; this protects service-level callers.
    from app.services.experiment_guard import check_experiment
    from app.tests.conftest import make_product
    pk = make_product()
    with SessionLocal() as session:
        result = check_experiment(session, plan_id=None, product_pk=pk,
                                  strategy_type="other", bundle_product_pks=[],
                                  proposed_price=None, estimated_cost=0)
        assert result is not None and not result.passed


def test_plan_cannot_attach_qloo_evidence_owned_by_another_product(client):
    target = make_product()
    foreign = _second_product("B097")
    with SessionLocal() as db:
        evidence = QlooEvidence(product_pk=foreign, kind="insights", request_path="/v2/insights",
                               request_params={"filter.type": "urn:entity:movie"},
                               response_json={"results": {"entities": []}}, from_cache=False)
        db.add(evidence)
        db.flush()
        evidence_id = evidence.id
        plan_id = saved_plan(db, target)
        row = db.get(PlanRow, plan_id)
        plan_json = dict(row.plan_json)
        plan_json["strategies"] = [dict(plan_json["strategies"][0])]
        plan_json["strategies"][0]["evidence"] = [
            {"source": "qloo", "entity_id": "movie-1", "raw_ref": f"qloo_evidence:{evidence_id}"}
        ]
        row.plan_json = plan_json
        row.evidence_ids = [evidence_id]
        db.commit()

    r = client.post("/experiments", json=body(target, plan_id=plan_id,
                                               qloo_evidence_ids=[evidence_id]))
    assert r.status_code == 422
    assert "unrelated Qloo evidence" in r.json()["message"]
