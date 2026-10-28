"""Evaluation cases: named feasible / infeasible scenarios run through the whole
decision engine (run_rescue). Master plan deliverable #7.

Each case reads as a small story a judge or teammate can check. The gateway is
a TEST DOUBLE; products, prices and entities are illustrative (NOT real Qloo data).
The same cases are tabulated in docs/decision-engine.md.
"""

import pytest

pytest.importorskip("pydantic")

from app.agent.workflow import QlooResolution, RescueRequest, run_rescue  # noqa: E402
from app.schemas.rescue import EvidenceSource, QlooStatus, RescuePlan, StrategyType  # noqa: E402
from app.services.constraints_service import ProductRef  # noqa: E402
from app.services.matcher_service import QlooRelatedEntity, StockItem  # noqa: E402
from app.services.rescue_config import Constraints  # noqa: E402

BUNDLE, REPOSITION, PROMOTION = StrategyType.BUNDLE, StrategyType.REPOSITION, StrategyType.PROMOTION


class Gateway:
    """TEST DOUBLE gateway."""

    def __init__(self, status=QlooStatus.STRONG_MATCH, entity_id="ent-target", entities=(),
                 alternatives=()):
        self.res = QlooResolution(status, entity_id, "Target", None, tuple(alternatives))
        self.entities = entities

    def resolve(self, target):
        return self.res

    def get_insights(self, resolution):
        return self.entities


def item(pid, name, qty, cost, price, **limits):
    return StockItem(ProductRef(pid, name, qty, cost, price, **limits))


def entity_for(stock_item):
    """An exact-title Qloo link to a stocked product (illustrative)."""
    return QlooRelatedEntity(f"ent-{stock_item.product.product_id}", stock_item.product.name,
                             "urn:entity:book", (), (), "qloo_evidence:1")


TARGET = item("1", "Slow Novel", 24, 350, 500)
PARTNER = item("2", "Companion Essays", 6, 200, 400)


def plan_for(target=TARGET, stock=None, constraints=None, gateway=None, history=None) -> RescuePlan:
    stock = [target, PARTNER] if stock is None else stock
    gateway = gateway or Gateway(entities=(entity_for(PARTNER),))
    plan = run_rescue(RescueRequest(target, stock, constraints or Constraints(), history), gateway)
    RescuePlan.model_validate(plan.model_dump())
    return plan


def types(plan):
    return [s.type for s in sorted(plan.strategies, key=lambda s: s.rank)]


def rejected(plan, kind):
    return [r for r in plan.rejected if r.type == kind]


def qloo_evidence(plan):
    return [e for s in plan.strategies for e in s.evidence if e.source == EvidenceSource.QLOO]


def test_case1_healthy_margin_exact_partner_all_three_and_discount_last():
    plan = plan_for()
    assert set(types(plan)) == {BUNDLE, REPOSITION, PROMOTION}
    assert types(plan)[-1] == PROMOTION  # discounts are tested last
    assert qloo_evidence(plan)
    assert all(s.economics.margin_pct >= 15 for s in plan.strategies)


def test_case2_thin_margin_skips_the_promotion():
    thin = item("1", "Slow Novel", 24, 440, 500)  # 12% margin, below the 15% floor already
    plan = plan_for(target=thin, stock=[thin, PARTNER])
    assert PROMOTION not in types(plan)
    reasons = " ".join(r for o in rejected(plan, PROMOTION) for r in o.reasons)
    assert "largest discount your rules allow" in reasons


def test_case3_partner_out_of_stock_rejects_the_bundle_but_keeps_the_display():
    empty = item("2", "Companion Essays", 0, 200, 400)
    plan = plan_for(stock=[TARGET, empty], gateway=Gateway(entities=(entity_for(empty),)))
    assert BUNDLE not in types(plan) and REPOSITION in types(plan)
    assert any("complete unit(s) can be supplied" in r for o in rejected(plan, BUNDLE) for r in o.reasons)


def test_case4_restricted_partner_rejects_the_bundle():
    plan = plan_for(constraints=Constraints(restricted_product_ids=frozenset({"2"})))
    assert BUNDLE not in types(plan)
    assert any("Restricted by the retailer" in r for o in rejected(plan, BUNDLE) for r in o.reasons)


def test_case5_product_level_zero_discount_means_no_promotion():
    never = item("1", "Slow Novel", 24, 350, 500, max_discount_pct=0)
    plan = plan_for(target=never, stock=[never, PARTNER])
    assert PROMOTION not in types(plan)
    assert rejected(plan, PROMOTION)
    assert all(s.economics.discount_pct == 0 for s in plan.strategies)


def test_case6_tiny_budget_rejects_everything_over_budget():
    plan = plan_for(constraints=Constraints(max_campaign_budget=60))
    assert types(plan) == [PROMOTION]  # Rs 50 placeholder cost is the only one within Rs 60
    over = [o for o in plan.rejected if any("campaign budget" in r for r in o.reasons)]
    assert {o.type for o in over} == {BUNDLE, REPOSITION}


def test_case7_no_qloo_match_uses_retailer_data_only():
    plan = plan_for(gateway=Gateway(status=QlooStatus.NO_MATCH, entity_id=None))
    assert plan.qloo_status == QlooStatus.NO_MATCH
    assert set(types(plan)) == {REPOSITION, PROMOTION}
    assert any(s.name.startswith("Face-out display") for s in plan.strategies)
    assert qloo_evidence(plan) == []


def test_case8_ambiguous_match_caps_evidence_and_lists_alternatives():
    gw = Gateway(status=QlooStatus.AMBIGUOUS, entities=(entity_for(PARTNER),),
                 alternatives=("Slow Novel (1999)", "Slow Novel (2015)"))
    plan = plan_for(gateway=gw)
    assert "Slow Novel (1999)" in plan.qloo_note
    assert all(s.rank_reason.evidence <= 0.3 for s in plan.strategies)


def test_case9_missing_sales_history_is_disclosed_not_judged():
    plan = plan_for(history=False)
    assert "Missing history is not evidence that the product is unpopular" in plan.limitations
    assert plan.strategies  # still proposes tests; it does not label the book unpopular
