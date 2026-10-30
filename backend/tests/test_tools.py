"""Tests for the named tool registry (app.agent.tools).

Person 1's entity resolution is replaced by TEST DOUBLES; all rows are
illustrative (NOT real Qloo data).
"""

import pytest
from datetime import datetime

from app.agent import adapters
from app.agent.tools import ToolError, call_tool, list_tools
from app.models import QlooEntityMapping, QlooEvidence
from app.schemas.qloo import InsightEntity, InsightsResult
from app.schemas.rescue import RescuePlan
from p2_helpers import add_mapping, add_product

MASTER_PLAN_NAMES = {
    "get_inventory", "get_product_sales_history", "resolve_qloo_entity", "get_qloo_insights",
    "find_available_inventory_candidates", "calculate_bundle_economics",
    "evaluate_business_constraints", "rank_rescue_experiments", "generate_experiment_plan",
    "save_rescue_plan",
}


@pytest.fixture
def shop(db, monkeypatch):
    t = add_product(db, "T1", "Slow Novel", qty=24, cost=350, price=500, units_sold_30d=0)
    p = add_product(db, "P1", "Companion Essays", qty=6, cost=200, price=400)
    add_mapping(db, t, status="strong", entity_id="ent-t")
    # The mocked Insights service returns evidence ID 41, so mirror its stored row.
    db.add(QlooEvidence(id=41, product_pk=t, kind="insights", request_path="/v2/insights",
                        request_params={"signal.interests.entities": "ent-t"},
                        response_json={"results": {"entities": [{"entity_id": "ent-ce"}]}},
                        from_cache=False, fetched_at=datetime.fromisoformat("2026-10-27T00:00:00+00:00")))
    db.commit()

    def fake_insights(session, pk, take=10):  # TEST DOUBLE
        return 41, InsightsResult(source_entity_id="ent-t", target_type="urn:entity:book",
                                  request_params={"signal.interests.entities": "ent-t"},
                                  fetched_at="2026-10-27T00:00:00+00:00",
                                  entities=[InsightEntity(entity_id="ent-ce", name="Companion Essays")])

    monkeypatch.setattr(adapters.ers, "insights_for_product", fake_insights)
    return {"t": str(t), "p": str(p)}


def test_registry_has_the_master_plan_tools_with_schemas():
    tools = {t["name"]: t for t in list_tools()}
    assert set(tools) == MASTER_PLAN_NAMES
    for t in tools.values():
        assert t["description"] and t["parameters"]["type"] == "object"


def test_unknown_tool_and_bad_arguments(db):
    with pytest.raises(ToolError, match="unknown tool"):
        call_tool("delete_everything", {}, db=db)
    with pytest.raises(ToolError, match="missing"):
        call_tool("get_product_sales_history", {}, db=db)
    with pytest.raises(ToolError, match="unknown argument"):
        call_tool("get_product_sales_history", {"product_id": "1", "x": 1}, db=db)
    with pytest.raises(ToolError, match="must be number"):
        call_tool("calculate_bundle_economics", {"product_ids": ["1"], "proposed_price": "10"}, db=db)
    with pytest.raises(ToolError, match="one of"):
        call_tool("evaluate_business_constraints",
                  {"strategy_type": "magic", "product_ids": ["1"], "proposed_price": 10}, db=db)
    with pytest.raises(ToolError, match="needs a database"):
        call_tool("get_inventory", {})


def test_missing_product(db):
    with pytest.raises(ToolError, match="not found"):
        call_tool("get_product_sales_history", {"product_id": "999"}, db=db)


def test_inventory_and_sales_history(db, shop):
    inv = call_tool("get_inventory", {}, db=db)
    assert [i["product_id"] for i in inv] == [shop["t"], shop["p"]]
    hist = call_tool("get_product_sales_history", {"product_id": shop["p"]}, db=db)
    assert hist["units_sold_30d"] is None and hist["has_sales_history"] is False


def test_economics_and_constraints_match_the_engine(db, shop):
    eco = call_tool("calculate_bundle_economics",
                    {"product_ids": [shop["t"], shop["p"]], "proposed_price": 810}, db=db)
    assert eco["bundle_unit_cost"] == 550 and eco["gross_profit_per_unit"] == 260
    assert eco["discount_vs_separate_pct"] == 10 and eco["complete_units_available"] == 6
    chk = call_tool("evaluate_business_constraints",
                    {"strategy_type": "bundle", "product_ids": [shop["t"], shop["p"]],
                     "proposed_price": 560}, db=db)
    assert chk["passed"] is False
    assert {"BELOW_MIN_MARGIN", "DISCOUNT_TOO_HIGH"} <= {v["code"] for v in chk["violations"]}


def test_qloo_tools(db, shop):
    res = call_tool("resolve_qloo_entity", {"product_id": shop["t"]}, db=db)
    assert res["status"] == "strong_match" and res["entity_id"] == "ent-t"
    ins = call_tool("get_qloo_insights", {"product_id": shop["t"]}, db=db)
    assert [e["entity_id"] for e in ins["entities"]] == ["ent-ce"]
    cands = call_tool("find_available_inventory_candidates", {"product_id": shop["t"]}, db=db)
    assert cands[0]["product_id"] == shop["p"] and cands[0]["match_kind"] == "exact"


def test_insights_tool_without_usable_entity(db, shop):
    db.query(QlooEntityMapping).delete()
    add_mapping(db, int(shop["t"]), status="none", entity_id=None)
    out = call_tool("get_qloo_insights", {"product_id": shop["t"]}, db=db)
    assert out["entities"] == [] and out["status"] == "no_match"


def test_plan_tools(db, shop):
    ranked = call_tool("rank_rescue_experiments", {"product_id": shop["t"]}, db=db)
    assert [r["rank"] for r in ranked["ranked"]] == list(range(1, len(ranked["ranked"]) + 1))
    plan = RescuePlan.model_validate(call_tool("generate_experiment_plan", {"product_id": shop["t"]}, db=db))
    assert plan.strategies, (plan.qloo_status, plan.stages_failed, plan.rejected, plan.stages_completed)
    saved = call_tool("save_rescue_plan", {"product_id": shop["t"]}, db=db)
    assert adapters.load_plan(db, saved["plan_id"]) is not None


def test_inventory_tool_cannot_select_another_retailer(db):
    own = add_product(db, "OWN-TOOL", "Own retailer item")
    add_product(db, "OTHER-TOOL", "Other retailer item", retailer_id="other")
    # This mirrors the authenticated DB session context populated by get_db().
    db.info["retailer_id"] = "demo"
    inventory = call_tool("get_inventory", {}, db=db)
    assert [row["product_id"] for row in inventory] == [str(own)]
    # The tool has no caller-selectable retailer_id argument anymore.
    with pytest.raises(ToolError, match="unknown argument"):
        call_tool("get_inventory", {"retailer_id": "other"}, db=db)
