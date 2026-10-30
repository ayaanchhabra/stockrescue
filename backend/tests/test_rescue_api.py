"""Tests for the rescue API (app.api.rescue).

A fresh FastAPI app with ONLY the rescue router is used (main.py does not
include it yet). The Qloo gateway and the LLM explainer are TEST DOUBLES
injected with dependency overrides. All data is illustrative (NOT real Qloo data).
"""

import json
from dataclasses import replace
from datetime import datetime

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.agent.explanation import explain_plan  # noqa: E402
from app.agent.workflow import QlooResolution  # noqa: E402
from app.api import rescue  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.models import QlooEvidence, RescueExperiment  # noqa: E402
from app.schemas.rescue import QlooStatus, RescuePlan  # noqa: E402
from app.services.matcher_service import QlooRelatedEntity  # noqa: E402
from p2_helpers import add_product  # noqa: E402


class Gateway:
    """TEST DOUBLE gateway: canned resolution and related entities."""

    def __init__(self, entities=(), resolution=None, resolve_exc=None):
        self.entities, self.resolve_exc = entities, resolve_exc
        self.resolution = resolution or QlooResolution(QlooStatus.STRONG_MATCH, "ent-t", "Target")
        self.evidence_ids = []
        self.refresh = None
        self.db = None
        self.target_pk = None

    def resolve(self, target):
        if self.resolve_exc:
            raise self.resolve_exc
        self.target_pk = int(target.product.product_id)
        return self.resolution

    def get_insights(self, resolution):
        params = {"filter.type": "urn:entity:book", "signal.interests.entities": resolution.entity_id,
                  "take": 10}
        fetched_at = "2026-10-27T00:00:00+00:00"
        entities = [replace(
            entity, raw_ref="qloo_evidence:41", qloo_affinity=entity.affinity,
            source_entity_id=resolution.entity_id, source_entity_type="urn:entity:book",
            evidence_id=41, request_params=params, fetched_at=fetched_at,
        ) for entity in self.entities]
        raw_entities = [{"entity_id": entity.entity_id, "name": entity.name} for entity in entities]
        self.db.add(QlooEvidence(
            id=41, product_pk=self.target_pk, kind="insights", request_path="/v2/insights",
            request_params=params, response_json={"results": {"entities": raw_entities}},
            from_cache=False, fetched_at=datetime.fromisoformat(fetched_at),
        ))
        self.db.flush()
        self.evidence_ids = [41]
        return tuple(entities)


@pytest.fixture
def shop(db):
    """Illustrative shop: slow target, one Qloo-linked partner, one other title."""
    t = add_product(db, "T1", "Slow Novel", qty=24, cost=350, price=500)
    p = add_product(db, "P1", "Companion Essays", qty=5, cost=200, price=400, units_sold_30d=2)
    o = add_product(db, "P2", "Unrelated Atlas", qty=9, cost=300, price=600)
    return {"target": t, "partner": p, "other": o,
            "entity": QlooRelatedEntity("ent-ce", "Companion Essays", "urn:entity:book", (), (),
                                        "qloo_evidence:41")}


@pytest.fixture
def make_client(db):
    def factory(gateway=None, explainer=None, raise_server_exceptions=True):
        app = FastAPI()
        app.include_router(rescue.router)
        gw = gateway or Gateway()

        def gateway_factory(session, refresh):
            gw.refresh = refresh
            gw.db = session
            return gw

        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[rescue.get_gateway_factory] = lambda: gateway_factory
        app.dependency_overrides[rescue.get_explainer] = lambda: explainer
        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    return factory


# --- POST /rescue/{product_pk} ---------------------------------------------

def test_happy_path_returns_valid_plan_and_saves_it(make_client, shop):
    client = make_client(Gateway(entities=(shop["entity"],)))
    r = client.post(f"/rescue/{shop['target']}")
    assert r.status_code == 200
    plan = RescuePlan.model_validate(r.json())
    assert plan.qloo_status == QlooStatus.STRONG_MATCH
    assert plan.product_id == str(shop["target"])
    assert any(s.type.value == "bundle" for s in plan.strategies)
    plan_id = r.headers[rescue.PLAN_ID_HEADER]
    stored = client.get(f"/rescue/plans/{plan_id}")
    assert stored.status_code == 200 and stored.json() == r.json()



def test_body_is_optional_and_refresh_is_passed(make_client, shop):
    gw = Gateway()
    client = make_client(gw)
    assert client.post(f"/rescue/{shop['target']}", json={"refresh_qloo": True}).status_code == 200
    assert gw.refresh is True


def test_unknown_product_is_404_in_person1_format(make_client, shop):
    r = make_client().post("/rescue/9999")
    assert r.status_code == 404
    assert r.json() == {"error": "not_found", "message": "Product 9999 not found"}


@pytest.mark.parametrize("bad", [{"min_margin_pct": 150}, {"max_discount_pct": -1},
                                 {"max_campaign_budget": -5}])
def test_invalid_constraints_are_422(make_client, shop, bad):
    r = make_client().post(f"/rescue/{shop['target']}", json={"constraints": bad})
    assert r.status_code == 422 and r.json()["error"] == "invalid_constraints"


def test_unknown_body_field_is_rejected(make_client, shop):
    r = make_client().post(f"/rescue/{shop['target']}", json={"surprise": 1})
    assert r.status_code == 422


def test_restricted_partner_is_rejected_not_proposed(make_client, shop):
    client = make_client(Gateway(entities=(shop["entity"],)))
    body = {"constraints": {"restricted_product_ids": [str(shop["partner"])]}}
    plan = RescuePlan.model_validate(client.post(f"/rescue/{shop['target']}", json=body).json())
    assert not any(s.type.value == "bundle" for s in plan.strategies)
    assert any("Restricted" in reason for rej in plan.rejected for reason in rej.reasons)
    assert plan.constraints_snapshot["restricted_product_ids"] == [str(shop["partner"])]


def test_gateway_failure_gives_partial_plan_not_an_error(make_client, shop):
    client = make_client(Gateway(resolve_exc=TimeoutError("qloo timed out")))
    r = client.post(f"/rescue/{shop['target']}")
    assert r.status_code == 200
    plan = RescuePlan.model_validate(r.json())
    assert plan.qloo_status == QlooStatus.ERROR
    assert plan.stages_failed["resolve"] == "TimeoutError: qloo timed out"


def test_explainer_failure_is_recorded(make_client, shop):
    def broken(plan):  # TEST DOUBLE explainer
        raise RuntimeError("llm down")

    plan = RescuePlan.model_validate(
        make_client(explainer=broken).post(f"/rescue/{shop['target']}").json())
    assert plan.stages_failed["explain"] == "RuntimeError: llm down"


def test_fake_explainer_sets_llm_explanation(make_client, shop):
    def complete(prompt):  # TEST DOUBLE LLM
        return json.dumps({"strategies": {"1": "Worth a small test at {selling_price}."}})

    explainer = lambda plan: explain_plan(plan, complete)  # noqa: E731
    plan = RescuePlan.model_validate(
        make_client(explainer=explainer).post(f"/rescue/{shop['target']}").json())
    top = next(s for s in plan.strategies if s.rank == 1)
    assert top.llm_explanation and "Rs" in top.llm_explanation
    assert "explain" in plan.stages_completed


def test_missing_sales_history_is_disclosed(make_client, shop):
    plan = RescuePlan.model_validate(make_client().post(f"/rescue/{shop['target']}").json())
    assert "No sales history" in plan.limitations


def test_unexpected_error_is_500_without_traceback(make_client, shop, monkeypatch):
    def boom(*a, **k):
        raise ZeroDivisionError("secret internals")

    monkeypatch.setattr(rescue, "run_rescue", boom)
    r = make_client(raise_server_exceptions=False).post(f"/rescue/{shop['target']}")
    assert r.status_code == 500
    assert r.json() == {"error": "internal_error", "message": "Something went wrong on our side."}
    assert "Traceback" not in r.text and "secret" not in r.text


def test_save_failure_does_not_return_an_unsaved_plan(make_client, shop, monkeypatch):
    monkeypatch.setattr(rescue.adapters, "save_plan",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db full")))
    r = make_client().post(f"/rescue/{shop['target']}")
    assert r.status_code == 500
    assert r.json() == {
        "error": "plan_persistence_failed",
        "message": "The rescue plan could not be saved. No experiment can be created from this result.",
    }
    assert rescue.PLAN_ID_HEADER not in r.headers


# --- POST /rescue/evaluate -------------------------------------------------

def test_evaluate_route_is_not_parsed_as_a_product_pk(make_client, shop):
    body = {"strategy_type": "promotion", "product_ids": [str(shop["target"])], "proposed_price": 450}
    r = make_client().post("/rescue/evaluate", json=body)
    assert r.status_code == 200 and "passed" in r.json()


def test_evaluate_feasible_bundle_numbers_come_from_the_engine(make_client, shop):
    body = {"strategy_type": "bundle", "proposed_price": 810,
            "product_ids": [str(shop["target"]), str(shop["partner"])],
            "estimated_experiment_cost": 100, "planned_units": 3}
    out = make_client().post("/rescue/evaluate", json=body).json()
    assert out["passed"] is True and out["violations"] == []
    eco = out["economics"]
    assert eco["unit_cost"] == 550 and eco["profit_per_unit"] == 260
    assert eco["margin_pct"] == pytest.approx(32.1, abs=0.01)
    assert eco["discount_pct"] == 10 and eco["units_available"] == 5
    assert out["effective_min_margin"] == 15


def test_evaluate_infeasible_lists_violation_codes(make_client, shop):
    body = {"strategy_type": "bundle", "proposed_price": 560,
            "product_ids": [str(shop["target"]), str(shop["partner"])], "planned_units": 9}
    out = make_client().post("/rescue/evaluate", json=body).json()
    codes = {v["code"] for v in out["violations"]}
    assert out["passed"] is False
    assert {"BELOW_MIN_MARGIN", "DISCOUNT_TOO_HIGH", "INSUFFICIENT_STOCK"} <= codes


def test_evaluate_respects_constraint_overrides(make_client, shop):
    body = {"strategy_type": "promotion", "product_ids": [str(shop["target"])],
            "proposed_price": 450, "constraints": {"max_discount_pct": 5}}
    out = make_client().post("/rescue/evaluate", json=body).json()
    assert [v["code"] for v in out["violations"]] == ["DISCOUNT_TOO_HIGH"]


def test_evaluate_unknown_and_invalid_ids(make_client, shop):
    client = make_client()
    base = {"strategy_type": "promotion", "proposed_price": 450}
    assert client.post("/rescue/evaluate", json={**base, "product_ids": ["9999"]}).status_code == 404
    assert client.post("/rescue/evaluate", json={**base, "product_ids": ["SKU-1"]}).status_code == 422
    assert client.post("/rescue/evaluate", json={**base, "product_ids": []}).status_code == 422


# --- plans and experiment hand-off -----------------------------------------

def test_unknown_plan_is_404(make_client, shop):
    r = make_client().get("/rescue/plans/12345")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_experiment_hand_off_creates_a_proposed_experiment(make_client, shop, db):
    # The gateway double writes the provider response and provenance itself.
    client = make_client(Gateway(entities=(shop["entity"],)))
    r = client.post(f"/rescue/{shop['target']}")
    plan = RescuePlan.model_validate(r.json())
    plan_id = int(r.headers[rescue.PLAN_ID_HEADER])
    bundle = next(s for s in plan.strategies if s.type.value == "bundle")

    out = client.post(f"/rescue/plans/{plan_id}/strategies/{bundle.rank}/experiment")
    assert out.status_code == 201
    exp = out.json()
    assert exp["status"] == "proposed" and exp["plan_id"] == plan_id
    assert exp["product_pk"] == shop["target"] and exp["bundle_product_pks"] == [shop["partner"]]
    assert exp["proposed_price"] == bundle.economics.selling_price
    assert exp["calculated_margin_pct"] == bundle.economics.margin_pct
    assert exp["qloo_evidence_ids"] == [41]
    assert db.get(RescueExperiment, exp["id"]) is not None


def test_experiment_hand_off_unknown_rank_or_plan(make_client, shop):
    client = make_client()
    r = client.post(f"/rescue/{shop['target']}")
    plan_id = r.headers[rescue.PLAN_ID_HEADER]
    assert client.post(f"/rescue/plans/{plan_id}/strategies/3/experiment").status_code in (201, 404)
    assert client.post(f"/rescue/plans/{plan_id}/strategies/9/experiment").status_code == 404
    assert client.post("/rescue/plans/777/strategies/1/experiment").status_code == 404
