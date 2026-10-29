"""Experiments obey the retailer's hard rules on every path (create, edit, approve),
the margin is always computed by the server, and a plan's strategy cannot be turned
into two live experiments. Uses the same TestClient setup as the other API tests."""
from app.db.session import SessionLocal
from app.models import Product
from app.models import RescuePlan as PlanRow
from app.tests.conftest import make_product

# make_product(): cost 350, price 499, 24 in stock. Default rule: margin >= 15%,
# discount <= 25%, budget Rs 2000, 3 units needed.


def body(pk, **over):
    b = {"product_pk": pk, "strategy_type": "promotion", "title": "Promo", "proposed_action": "do it",
         "proposed_price": 449.0, "estimated_cost": 50.0}
    b.update(over)
    return b


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


def _second_product():
    with SessionLocal() as db:
        p = Product(sku="B002", product_name="Partner", quantity_in_stock=10, unit_cost=100.0,
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


def test_other_strategy_without_checks_still_works(client):
    pk = make_product()
    r = client.post("/experiments", json=body(pk, strategy_type="other", proposed_price=None))
    assert r.status_code == 201 and r.json()["calculated_margin_pct"] is None


def test_plan_rules_are_used_when_the_experiment_belongs_to_a_plan(client):
    pk = make_product()
    with SessionLocal() as db:
        plan = PlanRow(retailer_id="demo", product_ids=[pk], status="draft",
                       constraints_snapshot={"min_margin_pct": 40.0, "max_discount_pct": 25.0,
                                             "max_campaign_budget": 2000.0, "restricted_product_ids": []})
        db.add(plan)
        db.commit()
        plan_id = plan.id
    r = client.post("/experiments", json=body(pk, plan_id=plan_id, proposed_price=449.0))  # margin 22%
    assert r.status_code == 422 and "40.00%" in r.json()["message"]


def test_restricted_product_in_the_plan_rules_blocks_the_experiment(client):
    pk = make_product()
    with SessionLocal() as db:
        plan = PlanRow(retailer_id="demo", product_ids=[pk], status="draft",
                       constraints_snapshot={"restricted_product_ids": [str(pk)]})
        db.add(plan)
        db.commit()
        plan_id = plan.id
    assert client.post("/experiments", json=body(pk, plan_id=plan_id)).status_code == 422


def test_same_plan_strategy_cannot_become_two_live_experiments(client):
    pk = make_product()
    with SessionLocal() as db:
        plan = PlanRow(retailer_id="demo", product_ids=[pk], status="draft")
        db.add(plan)
        db.commit()
        plan_id = plan.id
    first = client.post("/experiments", json=body(pk, plan_id=plan_id))
    assert first.status_code == 201
    again = client.post("/experiments", json=body(pk, plan_id=plan_id))
    assert again.status_code == 409 and again.json()["error"] == "duplicate_experiment"
    client.post(f"/experiments/{first.json()['id']}/reject")  # a rejected one may be re-proposed
    assert client.post("/experiments", json=body(pk, plan_id=plan_id)).status_code == 201
