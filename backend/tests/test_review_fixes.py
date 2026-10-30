"""Regression tests for the logic review (restricted displays, bundle attempts,
display wording, refresh vs human decisions, ambiguous wording, sales-change rule).

All data is illustrative (NOT real Qloo data); gateways and resolvers are TEST DOUBLES.
"""

import pytest

pytest.importorskip("pydantic")

from app.agent import adapters  # noqa: E402
from app.agent.adapters import DbQlooGateway  # noqa: E402
from app.agent.workflow import QlooResolution, RescueRequest, run_rescue  # noqa: E402
from app.schemas.rescue import QlooStatus  # noqa: E402
from app.services import entity_resolution_service as ers  # noqa: E402
from app.services.constraints_service import ProductRef  # noqa: E402
from app.services.experiment_calc import compute_outcome  # noqa: E402
from app.services.matcher_service import (  # noqa: E402
    CandidateMatch,
    QlooRelatedEntity,
    StockItem,
)
from app.services.rescue_config import Constraints  # noqa: E402
from app.services.strategy_generator import generate_strategies  # noqa: E402

from p2_helpers import add_mapping, add_product  # noqa: E402

TARGET = ProductRef("1", "Slow Novel", 24, 350, 500)


def link(pid, name, qty=9, cost=200, price=400):
    ref = ProductRef(pid, name, qty, cost, price)
    ent = QlooRelatedEntity(f"e{pid}", name, "book")
    return CandidateMatch(ref, "exact", ent, f"test link to {name}", 1.0)


def kinds(result):
    return {d.candidate.strategy_type: d for d in result.drafts}


# --- restricted products stay out of displays --------------------------------

def test_restricted_partner_is_not_named_in_a_themed_display():
    c = Constraints(restricted_product_ids=frozenset({"2"}))
    res = generate_strategies(TARGET, [link("2", "Banned Book"), link("3", "Fine Book")], c)
    display = kinds(res)["reposition"]
    assert [m.product.name for m in display.links] == ["Fine Book"]
    assert "Banned Book" not in display.summary
    assert all("Banned Book" not in a for a in display.assumptions + display.risks)


def test_display_with_only_restricted_links_falls_back_to_face_out():
    c = Constraints(restricted_product_ids=frozenset({"2"}))
    display = kinds(generate_strategies(TARGET, [link("2", "Banned Book")], c))["reposition"]
    assert display.links == () and display.candidate.name.startswith("Face-out")
    assert "restricted" in display.summary  # honest reason, not "no link was available"


def test_zero_stock_links_get_the_honest_face_out_wording():
    display = kinds(generate_strategies(TARGET, [link("2", "Empty Shelf", qty=0)], Constraints()))["reposition"]
    assert "none can be shown" in display.summary
    assert "No cultural link was available" not in display.summary


def test_no_links_at_all_keeps_the_original_wording():
    display = kinds(generate_strategies(TARGET, [], Constraints()))["reposition"]
    assert "No cultural link was available" in display.summary


# --- blocked partners do not use up the bundle attempts -----------------------

def test_restricted_high_stock_partners_do_not_hide_a_workable_partner():
    restricted = frozenset({"10", "11", "12"})
    matches = [link(str(10 + i), f"Banned {i}", qty=500) for i in range(3)] + [link("99", "Good Partner", qty=9)]
    res = generate_strategies(TARGET, matches, Constraints(restricted_product_ids=restricted))
    bundles = [d.candidate.name for d in res.drafts if d.candidate.strategy_type == "bundle"]
    assert "Bundle: Slow Novel + Good Partner" in bundles


def test_blocked_partners_shown_are_capped():
    matches = [link(str(10 + i), f"Out {i}", qty=0) for i in range(8)]
    res = generate_strategies(TARGET, matches, Constraints())
    assert len([d for d in res.drafts if d.candidate.strategy_type == "bundle"]) == 3


# --- ambiguous wording --------------------------------------------------------

class AmbiguousGateway:
    """TEST DOUBLE: ambiguous match with no confirmed entity."""

    def resolve(self, target):
        return QlooResolution(QlooStatus.AMBIGUOUS, None, None, alternatives=("Dune (1965)", "Dune (1984)"))

    def get_insights(self, resolution):
        raise AssertionError("insights must not run without an entity id")


def test_ambiguous_without_entity_says_no_evidence_is_used():
    t = StockItem(TARGET)
    plan = run_rescue(RescueRequest(t, [t], Constraints()), AmbiguousGateway())
    assert plan.qloo_status == QlooStatus.AMBIGUOUS
    assert "none is confirmed" in plan.qloo_note and "Dune (1965)" in plan.qloo_note
    assert "no cultural evidence is used until a person confirms" in plan.limitations
    assert "treated as low-confidence" not in plan.limitations


# --- refresh never undoes a human decision ------------------------------------

@pytest.fixture
def resolver_calls(monkeypatch):
    calls = []

    def fake_resolve(db, pk, force=False):
        calls.append((pk, force))
        return ers.get_mapping(db, pk) or add_mapping(db, pk, status="strong", entity_id="ent-new")

    monkeypatch.setattr(ers, "resolve_product", fake_resolve)
    return calls


@pytest.mark.parametrize("verification", ["rejected", "confirmed"])
def test_refresh_keeps_a_human_decision(db, resolver_calls, verification):
    pk = add_product(db, "S1", "Slow Novel")
    add_mapping(db, pk, status="strong", entity_id="ent-1", verification=verification)
    res = DbQlooGateway(db, refresh=True).resolve(adapters.product_to_stock_item(db.get(adapters.Product, pk)))
    assert resolver_calls == []  # Qloo / resolver never called
    expected = QlooStatus.NO_MATCH if verification == "rejected" else QlooStatus.STRONG_MATCH
    assert res.status == expected


def test_refresh_re_resolves_an_unjudged_mapping(db, resolver_calls):
    pk = add_product(db, "S1", "Slow Novel")
    add_mapping(db, pk, status="strong", entity_id="ent-1", verification="unverified")
    DbQlooGateway(db, refresh=True).resolve(adapters.product_to_stock_item(db.get(adapters.Product, pk)))
    assert resolver_calls == [(pk, False)]


def test_no_refresh_reuses_the_stored_mapping(db, resolver_calls):
    pk = add_product(db, "S1", "Slow Novel")
    add_mapping(db, pk, status="strong", entity_id="ent-1", verification="unverified")
    DbQlooGateway(db, refresh=False).resolve(adapters.product_to_stock_item(db.get(adapters.Product, pk)))
    assert resolver_calls == []


# --- one rule for the sales change --------------------------------------------

def outcome(**over):
    kw = dict(items=[{"product_id": "B1", "units_sold": 10, "actual_selling_price": 500, "unit_cost": 350}],
              additional_costs=0, target_units_sold=10, actual_days=14, baseline_units=7, baseline_days=14)
    kw.update(over)
    return compute_outcome(**kw)["baseline_comparison"]


def test_comparable_periods_give_a_percentage():
    b = outcome()
    assert b["sales_change_pct"] == 42.86 and b["units_above_baseline_rate"] == 3.0


@pytest.mark.parametrize("over", [dict(actual_days=5), dict(baseline_days=5)])
def test_short_periods_give_no_percentage(over):
    b = outcome(**over)
    assert b["sales_change_pct"] is None
    assert b["units_above_baseline_rate"] is None and b["expected_units_at_baseline_rate"] is None
    assert "shorter than 7 days" in b["note"]


def test_short_period_is_listed_in_limitations():
    calc = compute_outcome(
        items=[{"product_id": "B1", "units_sold": 3, "actual_selling_price": 500, "unit_cost": 350}],
        additional_costs=0, target_units_sold=3, actual_days=5, baseline_units=7, baseline_days=14)
    assert any("no percentage change was calculated" in x for x in calc["limitations"])


def test_zero_baseline_still_gives_none_with_its_own_note():
    b = outcome(baseline_units=0)
    assert b["sales_change_pct"] is None and "zero" in b["note"]
