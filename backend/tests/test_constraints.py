import pytest

from app.services import constraints_service as cs
from app.services.constraints_service import (
    BUNDLE,
    PROMOTION,
    REPOSITION,
    CandidateStrategy,
    ProductRef,
    check_candidate,
    max_allowed_discount_pct,
)
from app.services.rescue_config import Constraints, RankingWeights

# --- illustrative test fixtures (NOT Qloo data) ------------------------------

SLOW = ProductRef("B001", "Slow Literary Novel", quantity=24, unit_cost=350, selling_price=500)
PARTNER = ProductRef("B002", "Companion Essays", quantity=5, unit_cost=200, selling_price=400)
OUT_OF_STOCK = ProductRef("B003", "Sold Out Title", quantity=0, unit_cost=100, selling_price=300)

RULES = Constraints(min_margin_pct=15, max_discount_pct=25, max_campaign_budget=2000)


def bundle(price=800, units=3, cost=0.0, products=(SLOW, PARTNER)):
    return CandidateStrategy(BUNDLE, "Bundle", tuple(products), price, cost, units)


def promo(price, units=3, cost=0.0, product=SLOW):
    return CandidateStrategy(PROMOTION, "Promo", (product,), price, cost, units)


# --- passing cases ----------------------------------------------------------

def test_feasible_bundle_passes_and_reports_metrics():
    r = check_candidate(bundle(800), RULES)
    assert r.passed and r.violations == ()
    assert r.metrics["unit_cost"] == 550
    assert r.metrics["margin_pct"] == 31.25
    assert r.metrics["discount_pct"] == 11.11
    assert r.metrics["units_available"] == 5


def test_reposition_at_full_price_passes():
    r = check_candidate(CandidateStrategy(REPOSITION, "Display", (SLOW,), 500, 0, 3), RULES)
    assert r.passed
    assert r.metrics["discount_pct"] == 0


def test_modest_promotion_passes():
    r = check_candidate(promo(425), RULES)  # 15% off, margin ~17.6%
    assert r.passed


def test_margin_exactly_at_minimum_passes():
    p = ProductRef("X1", "Edge Case", 10, unit_cost=85, selling_price=100)
    r = check_candidate(CandidateStrategy(REPOSITION, "Edge", (p,), 100, 0, 1), RULES)
    assert r.passed and r.metrics["margin_pct"] == 15.0


# --- failing cases (the demo's "rejected option") ----------------------------

def test_bundle_failing_margin_is_rejected_with_reason():
    r = check_candidate(bundle(600), RULES)  # cost 550 -> margin 8.33%
    assert not r.passed
    assert cs.BELOW_MIN_MARGIN in r.codes
    assert any("below the 15.00% minimum" in m for m in r.reasons)


def test_bundle_with_insufficient_stock_is_rejected():
    r = check_candidate(bundle(800, units=10), RULES)
    assert not r.passed
    assert cs.INSUFFICIENT_STOCK in r.codes
    assert any("Companion Essays" in m for m in r.reasons)


def test_out_of_stock_item_blocks_bundle():
    r = check_candidate(bundle(700, units=1, products=(SLOW, OUT_OF_STOCK)), RULES)
    assert cs.INSUFFICIENT_STOCK in r.codes


def test_deep_discount_fails_margin_and_discount_cap():
    r = check_candidate(promo(350), RULES)  # 30% off, margin 0%
    assert cs.BELOW_MIN_MARGIN in r.codes
    assert cs.DISCOUNT_TOO_HIGH in r.codes


def test_discount_over_cap_but_margin_ok():
    cheap = ProductRef("C1", "High Margin Book", 20, unit_cost=100, selling_price=500)
    r = check_candidate(promo(300, product=cheap), RULES)  # 40% off, margin 66%
    assert cs.DISCOUNT_TOO_HIGH in r.codes
    assert cs.BELOW_MIN_MARGIN not in r.codes


def test_over_budget_is_rejected():
    r = check_candidate(bundle(800, cost=2500), RULES)
    assert cs.OVER_BUDGET in r.codes


def test_restricted_product_is_rejected():
    rules = Constraints(restricted_product_ids=frozenset({"B002"}))
    r = check_candidate(bundle(800), rules)
    assert cs.RESTRICTED_PRODUCT in r.codes


# --- invalid inputs ---------------------------------------------------------

@pytest.mark.parametrize("bad_price", [0, -50, None])
def test_invalid_proposed_price(bad_price):
    r = check_candidate(bundle(bad_price), RULES)
    assert not r.passed and cs.INVALID_PRICE in r.codes
    assert r.metrics == {}  # nothing calculated on bad input


def test_invalid_product_data():
    broken = ProductRef("Z1", "Broken Row", quantity=5, unit_cost=100, selling_price=0)
    r = check_candidate(bundle(500, units=1, products=(broken,)), RULES)
    assert cs.INVALID_PRODUCT_DATA in r.codes


def test_empty_strategy_and_duplicates():
    r = check_candidate(CandidateStrategy(BUNDLE, "Empty", (), 100), RULES)
    assert cs.EMPTY_STRATEGY in r.codes
    r2 = check_candidate(bundle(800, products=(SLOW, SLOW)), RULES)
    assert cs.DUPLICATE_PRODUCT in r2.codes


def test_invalid_planned_units():
    r = check_candidate(bundle(800, units=0), RULES)
    assert cs.INVALID_PLAN in r.codes


# --- per-product overrides --------------------------------------------------

def test_product_specific_margin_floor_is_stricter():
    strict = ProductRef("S1", "Strict", 10, unit_cost=350, selling_price=500, min_margin_pct=40)
    r = check_candidate(CandidateStrategy(REPOSITION, "x", (strict,), 500, 0, 1), RULES)
    assert cs.BELOW_MIN_MARGIN in r.codes  # 30% < 40%


def test_product_specific_discount_cap_is_stricter():
    strict = ProductRef("S2", "Strict", 10, unit_cost=100, selling_price=500, max_discount_pct=10)
    r = check_candidate(promo(425, product=strict), RULES)  # 15% > 10%
    assert cs.DISCOUNT_TOO_HIGH in r.codes


# --- max_allowed_discount_pct ----------------------------------------------

def test_max_allowed_discount_limited_by_margin_floor():
    # price 500, cost 350, 15% floor => ~17.65% (below the 25% cap)
    d = max_allowed_discount_pct(SLOW, RULES)
    assert 17.5 < d < 17.8


def test_max_allowed_discount_limited_by_product_cap():
    capped = ProductRef("S3", "Capped", 10, unit_cost=100, selling_price=500, max_discount_pct=10)
    assert max_allowed_discount_pct(capped, RULES) == 10


def test_max_allowed_discount_zero_when_no_headroom():
    thin = ProductRef("S4", "Thin", 10, unit_cost=95, selling_price=100)
    assert max_allowed_discount_pct(thin, RULES) == 0


# --- config validation ------------------------------------------------------

def test_invalid_constraint_values_rejected():
    with pytest.raises(ValueError):
        Constraints(min_margin_pct=100)
    with pytest.raises(ValueError):
        Constraints(max_discount_pct=150)
    with pytest.raises(ValueError):
        Constraints(max_campaign_budget=-1)


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError):
        RankingWeights(0.5, 0.5, 0.5, 0.5)
    assert RankingWeights().as_dict()["evidence"] == 0.30


def test_constraints_snapshot_is_serialisable():
    snap = Constraints(restricted_product_ids=frozenset({"B9", "B2"})).as_dict()
    assert snap["restricted_product_ids"] == ["B2", "B9"]
