import pytest

from app.services.constraints_service import (
    BELOW_MIN_MARGIN,
    BUNDLE,
    INSUFFICIENT_STOCK,
    PROMOTION,
    REPOSITION,
    RESTRICTED_PRODUCT,
    ProductRef,
    check_candidate,
    max_allowed_discount_pct,
)
from app.services.matcher_service import (
    EXACT,
    FUZZY,
    THEME_ONLY,
    CandidateMatch,
    QlooRelatedEntity,
)
from app.services.rescue_config import Constraints, StrategySettings
from app.services.strategy_generator import generate_strategies

# --- illustrative test fixtures (NOT real Qloo data) --------------------------

SLOW = ProductRef("B001", "Slow Literary Novel", quantity=24, unit_cost=350, selling_price=500)
PARTNER = ProductRef("B002", "Companion Essays", quantity=5, unit_cost=200, selling_price=400)
RULES = Constraints(min_margin_pct=15, max_discount_pct=25, max_campaign_budget=2000)
S = StrategySettings()


def link(product, kind=EXACT, entity_name="Related Work", similarity=1.0):
    entity = QlooRelatedEntity(f"ent-{product.product_id}", entity_name, "book", (), (), "raw/1")
    return CandidateMatch(product, kind, entity, f"test link to {product.name}", similarity)


def partner(pid, name, qty=5, cost=200, price=400, **kw):
    return ProductRef(pid, name, quantity=qty, unit_cost=cost, selling_price=price, **kw)


def by_type(result, t):
    return [d for d in result.drafts if d.candidate.strategy_type == t]


def passes(draft, rules=RULES):
    return check_candidate(draft.candidate, rules).passed


# --- the normal case ------------------------------------------------------------

def test_full_set_has_one_of_each_type_and_all_are_feasible():
    r = generate_strategies(SLOW, [link(PARTNER)], RULES)
    assert [d.candidate.strategy_type for d in r.drafts] == [BUNDLE, REPOSITION, PROMOTION]
    assert all(passes(d) for d in r.drafts)
    assert r.skipped == ()


def test_bundle_is_priced_below_the_separate_prices_and_above_the_margin_floor():
    d = by_type(generate_strategies(SLOW, [link(PARTNER)], RULES), BUNDLE)[0]
    assert d.candidate.proposed_price == 810  # 10% under the 900 separate total
    res = check_candidate(d.candidate, RULES)
    assert res.metrics["discount_pct"] == 10
    assert res.metrics["margin_pct"] == pytest.approx(32.1, abs=0.1)
    assert d.candidate.products == (SLOW, PARTNER)
    assert d.effort == "medium"
    assert d.match_kinds == (EXACT,)


def test_promotion_is_sized_with_max_allowed_discount_pct():
    d = by_type(generate_strategies(SLOW, [], RULES), PROMOTION)[0]
    allowed = max_allowed_discount_pct(SLOW, RULES)
    assert allowed == 17.64  # rounded down so the exact margin floor cannot be breached
    assert d.candidate.proposed_price == 425  # the 15% target, which is below the allowed max
    assert passes(d)
    assert "17.64%" in d.summary  # the retailer sees the limit
    assert d.match_kinds == () and d.links == ()  # a discount carries no cultural evidence
    assert d.effort == "low"


def test_promotion_is_capped_at_the_largest_allowed_discount():
    # Per-product cap of 8% is stricter than the 15% target.
    target = ProductRef("B001", "Capped", 24, 350, 500, max_discount_pct=8)
    d = by_type(generate_strategies(target, [], RULES), PROMOTION)[0]
    assert d.candidate.proposed_price == 460  # 8% off 500
    assert passes(d)


def test_reposition_keeps_the_normal_price_and_names_linked_titles():
    r = generate_strategies(SLOW, [link(PARTNER)], RULES)
    d = by_type(r, REPOSITION)[0]
    assert d.candidate.proposed_price == SLOW.selling_price
    assert d.candidate.products == (SLOW,)
    assert d.candidate.name.startswith("Themed display")
    assert "Companion Essays" in d.summary
    assert d.match_kinds == (EXACT,)
    assert d.effort == "low"


def test_every_draft_has_a_test_plan_and_labels_the_placeholder_cost():
    r = generate_strategies(SLOW, [link(PARTNER)], RULES)
    for d in r.drafts:
        assert "14 days" in d.test_plan
        assert "not proof" in d.test_plan
        assert any("placeholder" in a for a in d.assumptions)
        assert d.summary and d.assumptions


def test_settings_flow_into_the_candidates():
    s = StrategySettings(
        test_units=2, test_days=21, bundle_discount_pct=5,
        bundle_campaign_cost=10, reposition_campaign_cost=20, promotion_campaign_cost=30,
    )
    r = generate_strategies(SLOW, [link(PARTNER)], RULES, s)
    costs = {d.candidate.strategy_type: d.candidate.estimated_experiment_cost for d in r.drafts}
    assert costs == {BUNDLE: 10, REPOSITION: 20, PROMOTION: 30}
    assert all(d.candidate.planned_units == 2 for d in r.drafts)
    assert by_type(r, BUNDLE)[0].candidate.proposed_price == 855  # 5% off 900
    assert "21 days" in r.drafts[0].test_plan


# --- no Qloo links -----------------------------------------------------------------

def test_without_links_there_is_no_bundle_and_the_reason_is_recorded():
    r = generate_strategies(SLOW, [], RULES)
    assert [d.candidate.strategy_type for d in r.drafts] == [REPOSITION, PROMOTION]
    skipped = [x for x in r.skipped if x.strategy_type == BUNDLE]
    assert len(skipped) == 1 and "no partner" in skipped[0].reasons[0]


def test_without_links_the_display_is_generic_and_says_so():
    d = by_type(generate_strategies(SLOW, [], RULES), REPOSITION)[0]
    assert d.candidate.name.startswith("Face-out display")
    assert d.match_kinds == () and d.links == ()
    assert any("no cultural evidence" in r.lower() for r in d.risks)


def test_target_is_never_its_own_bundle_partner():
    r = generate_strategies(SLOW, [link(SLOW)], RULES)
    assert by_type(r, BUNDLE) == []
    assert any(x.strategy_type == BUNDLE for x in r.skipped)


# --- choosing and trying partners -------------------------------------------------

def test_partners_are_tried_strongest_link_first():
    theme = partner("T", "Theme Partner")
    fuzzy = partner("F", "Fuzzy Partner")
    exact = partner("E", "Exact Partner", qty=1)  # fails stock (needs 3), so we keep trying
    r = generate_strategies(
        SLOW, [link(theme, THEME_ONLY, similarity=0.9), link(fuzzy, FUZZY, similarity=0.9), link(exact, EXACT)],
        RULES,
    )
    names = [d.candidate.products[1].name for d in by_type(r, BUNDLE)]
    assert names == ["Exact Partner", "Fuzzy Partner"]  # stops at the first feasible bundle


def test_failed_bundles_are_kept_so_their_rejection_reasons_stay_visible():
    low_stock = partner("L", "Low Stock Partner", qty=1)
    ok = partner("O", "Fine Partner")
    r = generate_strategies(SLOW, [link(low_stock, EXACT), link(ok, FUZZY)], RULES)
    bundles = by_type(r, BUNDLE)
    assert len(bundles) == 2
    assert INSUFFICIENT_STOCK in check_candidate(bundles[0].candidate, RULES).codes
    assert passes(bundles[1])


def test_generator_stops_after_the_first_feasible_bundle():
    a, b = partner("A", "Partner A"), partner("B", "Partner B")
    r = generate_strategies(SLOW, [link(a, EXACT), link(b, FUZZY)], RULES)
    assert [d.candidate.products[1].product_id for d in by_type(r, BUNDLE)] == ["A"]


def test_bundle_attempts_are_limited():
    bad = [partner(f"P{i}", f"Empty {i}", qty=0) for i in range(5)]
    s = StrategySettings(max_bundle_attempts=2)
    r = generate_strategies(SLOW, [link(p) for p in bad], RULES, s)
    assert len(by_type(r, BUNDLE)) == 2


def test_restricted_partner_is_proposed_then_rejected_by_the_engine_not_hidden():
    rules = Constraints(min_margin_pct=15, max_discount_pct=25, max_campaign_budget=2000,
                        restricted_product_ids=frozenset({"B002"}))
    r = generate_strategies(SLOW, [link(PARTNER)], rules)
    assert RESTRICTED_PRODUCT in check_candidate(by_type(r, BUNDLE)[0].candidate, rules).codes


def test_partner_data_problem_is_skipped_with_a_reason_and_the_next_partner_is_tried():
    broken = partner("X", "Broken Partner", price=0)
    ok = partner("O", "Fine Partner")
    r = generate_strategies(SLOW, [link(broken, EXACT), link(ok, FUZZY)], RULES)
    assert [d.candidate.products[1].product_id for d in by_type(r, BUNDLE)] == ["O"]
    assert any("Broken Partner" in x.name and "Invalid" in x.reasons[0] for x in r.skipped)


def test_several_links_to_one_partner_make_one_bundle_with_all_the_evidence():
    r = generate_strategies(SLOW, [link(PARTNER, EXACT, "Work A"), link(PARTNER, THEME_ONLY, "Work B", 0.3)], RULES)
    bundles = by_type(r, BUNDLE)
    assert len(bundles) == 1
    assert bundles[0].match_kinds == (EXACT, THEME_ONLY)
    assert {m.entity.name for m in bundles[0].links} == {"Work A", "Work B"}


def test_display_names_at_most_max_display_titles():
    ps = [partner(f"P{i}", f"Title {i}") for i in range(6)]
    s = StrategySettings(max_display_titles=2)
    d = by_type(generate_strategies(SLOW, [link(p) for p in ps], RULES, s), REPOSITION)[0]
    assert len(d.links) == 2 and len(d.match_kinds) == 2


def test_display_never_names_an_out_of_stock_title():
    gone = partner("G", "Sold Out Partner", qty=0)
    r = generate_strategies(SLOW, [link(gone, EXACT), link(PARTNER, FUZZY)], RULES)
    d = by_type(r, REPOSITION)[0]
    assert "Sold Out Partner" not in d.summary
    assert [m.product.product_id for m in d.links] == ["B002"]
    assert d.candidate.name.startswith("Themed display")


def test_display_is_generic_when_every_linked_title_is_out_of_stock():
    gone = partner("G", "Sold Out Partner", qty=0)
    d = by_type(generate_strategies(SLOW, [link(gone)], RULES), REPOSITION)[0]
    assert d.candidate.name.startswith("Face-out display")
    assert d.links == () and d.match_kinds == ()


def test_output_does_not_depend_on_input_order():
    ps = [partner(f"P{i}", f"Title {i}", qty=10 + i) for i in range(4)]
    links = [link(p, THEME_ONLY, similarity=0.3) for p in ps]
    a = generate_strategies(SLOW, links, RULES)
    b = generate_strategies(SLOW, list(reversed(links)), RULES)
    assert [d.candidate.name for d in a.drafts] == [d.candidate.name for d in b.drafts]


# --- pricing guards -----------------------------------------------------------------

def test_bundle_price_is_lifted_to_the_margin_floor_when_the_target_discount_would_break_it():
    costly = partner("C", "Costly Partner", cost=380, price=400)  # bundle cost 730
    d = by_type(generate_strategies(SLOW, [link(costly)], RULES), BUNDLE)[0]
    assert d.candidate.proposed_price == 859  # just above the 858.82 floor, below 900
    assert passes(d)


def test_bundle_with_no_room_for_a_saving_is_priced_at_full_and_rejected_with_the_reason():
    bad = partner("N", "Thin Margin Partner", cost=450, price=400)  # bundle cost 800 vs 900
    d = by_type(generate_strategies(SLOW, [link(bad)], RULES), BUNDLE)[0]
    assert d.candidate.proposed_price == 900  # no saving offered
    assert BELOW_MIN_MARGIN in check_candidate(d.candidate, RULES).codes
    assert any("no saving" in r for r in d.risks)


def test_partner_cap_from_the_csv_limits_the_bundle_saving():
    capped = partner("K", "Capped Partner", max_discount_pct=5)
    d = by_type(generate_strategies(SLOW, [link(capped)], RULES), BUNDLE)[0]
    assert d.candidate.proposed_price == 855  # 5% off 900, not 10%
    assert passes(d)


def test_global_discount_cap_limits_bundle_and_promotion():
    rules = Constraints(min_margin_pct=15, max_discount_pct=5, max_campaign_budget=2000)
    r = generate_strategies(SLOW, [link(PARTNER)], rules)
    assert by_type(r, BUNDLE)[0].candidate.proposed_price == 855
    assert by_type(r, PROMOTION)[0].candidate.proposed_price == 475
    assert all(passes(d, rules) for d in r.drafts)


def test_promotion_is_skipped_when_the_rules_allow_no_worthwhile_discount():
    tight = ProductRef("B009", "Thin Margin Book", 24, 480, 500)
    r = generate_strategies(tight, [], RULES)
    assert by_type(r, PROMOTION) == []
    skipped = [x for x in r.skipped if x.strategy_type == PROMOTION]
    assert len(skipped) == 1 and "0.00%" in skipped[0].reasons[0]


@pytest.mark.parametrize("cost,price", [(100, 500), (350, 500), (420, 500), (50, 99), (7, 13), (350, 499)])
def test_promotion_never_breaks_the_rules(cost, price):
    target = ProductRef("B009", "Any Book", 24, cost, price)
    r = generate_strategies(target, [], RULES)
    for d in by_type(r, PROMOTION):
        res = check_candidate(d.candidate, RULES)
        assert res.passed, res.reasons
        assert res.metrics["discount_pct"] <= max_allowed_discount_pct(target, RULES) + 1e-9


# --- link risks ---------------------------------------------------------------------

def test_weaker_links_carry_a_risk_note():
    exact = by_type(generate_strategies(SLOW, [link(PARTNER, EXACT)], RULES), BUNDLE)[0]
    fuzzy = by_type(generate_strategies(SLOW, [link(PARTNER, FUZZY)], RULES), BUNDLE)[0]
    theme = by_type(generate_strategies(SLOW, [link(PARTNER, THEME_ONLY)], RULES), BUNDLE)[0]
    assert not any("fuzzy" in r or "theme" in r for r in exact.risks)
    assert any("fuzzy" in r for r in fuzzy.risks)
    assert any("theme" in r for r in theme.risks)


# --- bad target -----------------------------------------------------------------------

@pytest.mark.parametrize("target", [
    ProductRef("B1", "Zero Price", 5, 100, 0),
    ProductRef("B1", "Negative Cost", 5, -1, 300),
    ProductRef("B1", "Negative Stock", -1, 100, 300),
])
def test_invalid_target_data_yields_no_drafts_and_a_reason_for_each_type(target):
    r = generate_strategies(target, [link(PARTNER)], RULES)
    assert r.drafts == ()
    assert {x.strategy_type for x in r.skipped} == {BUNDLE, REPOSITION, PROMOTION}
    assert all("Invalid" in x.reasons[0] for x in r.skipped)


def test_per_product_margin_that_cannot_be_priced_is_reported_not_raised():
    odd = ProductRef("B1", "Odd Rule", 5, 100, 300, min_margin_pct=100)
    r = generate_strategies(odd, [link(PARTNER)], RULES)
    assert by_type(r, PROMOTION) == []
    assert any(x.strategy_type == PROMOTION for x in r.skipped)
    assert any(x.strategy_type == BUNDLE for x in r.skipped)


# --- settings validation ----------------------------------------------------------------

@pytest.mark.parametrize("kwargs", [
    {"test_units": 0}, {"test_days": 0}, {"bundle_discount_pct": -1},
    {"promo_discount_pct": 101}, {"min_promo_discount_pct": -5},
    {"max_bundle_attempts": 0}, {"max_display_titles": 0}, {"bundle_campaign_cost": -1},
])
def test_invalid_strategy_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        StrategySettings(**kwargs)
