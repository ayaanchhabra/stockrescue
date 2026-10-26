import pytest

from app.services.constraints_service import (
    BUNDLE,
    PROMOTION,
    REPOSITION,
    CandidateStrategy,
    ProductRef,
    check_candidate,
)
from app.services.ranking_service import (
    AMBIGUOUS,
    ERROR,
    NO_MATCH,
    STRONG_MATCH,
    RankInput,
    cost_score,
    evidence_score,
    feasibility_score,
    rank_strategies,
    simplicity_score,
)
from app.services.rescue_config import (
    DEFAULT_RANKING_SETTINGS,
    Constraints,
    RankingSettings,
)

# --- illustrative test fixtures (NOT Qloo data) ------------------------------

SLOW = ProductRef("B001", "Slow Literary Novel", quantity=24, unit_cost=350, selling_price=500)
PARTNER = ProductRef("B002", "Companion Essays", quantity=5, unit_cost=200, selling_price=400)
RULES = Constraints(min_margin_pct=15, max_discount_pct=25, max_campaign_budget=2000)
S = DEFAULT_RANKING_SETTINGS


def make(candidate, match_kinds=(), effort="low"):
    return RankInput(candidate, check_candidate(candidate, RULES), tuple(match_kinds), effort)


def bundle(price=800, cost=0.0, units=3, name="Bundle"):
    return CandidateStrategy(BUNDLE, name, (SLOW, PARTNER), price, cost, units)


def promo(price=425, cost=0.0, units=3, name="Promo"):
    return CandidateStrategy(PROMOTION, name, (SLOW,), price, cost, units)


def reposition(name="Display", cost=0.0):
    return CandidateStrategy(REPOSITION, name, (SLOW,), 500, cost, 3)


# --- individual scores -------------------------------------------------------

def test_evidence_score_by_match_kind():
    assert evidence_score(["exact"], STRONG_MATCH, S) == 1.0
    assert evidence_score(["fuzzy"], STRONG_MATCH, S) == 0.5
    assert evidence_score(["theme_only"], STRONG_MATCH, S) == 0.3


def test_evidence_uses_best_link_not_a_sum():
    assert evidence_score(["fuzzy", "theme_only", "fuzzy"], STRONG_MATCH, S) == 0.5


def test_no_evidence_when_qloo_failed_or_empty():
    assert evidence_score([], STRONG_MATCH, S) == 0.0
    assert evidence_score(["exact"], NO_MATCH, S) == 0.0
    assert evidence_score(["exact"], ERROR, S) == 0.0


def test_ambiguous_match_caps_evidence():
    assert evidence_score(["exact"], AMBIGUOUS, S) == 0.3


def test_cost_score():
    assert cost_score(0, 2000) == 1.0
    assert cost_score(1000, 2000) == 0.5
    assert cost_score(5000, 2000) == 0.0
    assert cost_score(0, 0) == 1.0
    assert cost_score(10, 0) == 0.0


def test_simplicity_score_and_unknown_effort():
    assert simplicity_score("low", S) == 1.0
    assert simplicity_score("high", S) == 0.3
    with pytest.raises(ValueError):
        simplicity_score("impossible", S)


def test_feasibility_rewards_headroom_and_stock():
    strong = check_candidate(bundle(800), RULES)      # margin 31%, stock 5 for 3 planned
    thin = check_candidate(promo(425), RULES)          # margin ~17.6%, stock 24 for 3 planned
    assert feasibility_score(strong, S) > feasibility_score(thin, S)


# --- ranking -----------------------------------------------------------------

def test_infeasible_candidates_are_rejected_with_reasons_not_ranked():
    out = rank_strategies(
        [make(bundle(800), ["exact"]), make(bundle(600, name="Cheap Bundle"))],
        STRONG_MATCH, RULES,
    )
    assert len(out.ranked) == 1
    assert len(out.rejected) == 1
    assert out.rejected[0].candidate.name == "Cheap Bundle"
    assert any("minimum" in r for r in out.rejected[0].reasons)


def test_ranks_are_consecutive_and_sorted_by_total():
    out = rank_strategies(
        [
            make(reposition("A"), ["theme_only"]),
            make(reposition("B"), ["exact"]),
            make(reposition("C"), []),
        ],
        STRONG_MATCH, RULES,
    )
    assert [s.rank for s in out.ranked] == [1, 2, 3]
    totals = [s.weighted_total for s in out.ranked]
    assert totals == sorted(totals, reverse=True)
    assert out.ranked[0].candidate.name == "B"


def test_discount_last_puts_non_markdown_first_even_with_lower_score():
    weak_bundle = make(bundle(800, cost=1500), [], effort="high")
    strong_promo = make(promo(425), ["exact"], effort="low")

    on = rank_strategies([weak_bundle, strong_promo], STRONG_MATCH, RULES)
    assert on.ranked[0].candidate.strategy_type == BUNDLE
    assert on.ranked[1].is_markdown
    assert on.ranked[0].weighted_total < on.ranked[1].weighted_total  # score alone would flip it
    assert "discounts are tested last" in on.ranked[1].explanation

    off_settings = RankingSettings(discount_last=False)
    off = rank_strategies([weak_bundle, strong_promo], STRONG_MATCH, RULES, off_settings)
    assert off.ranked[0].candidate.strategy_type == PROMOTION


def test_promotion_with_no_discount_is_not_a_markdown():
    full_price = CandidateStrategy(PROMOTION, "Full price feature", (SLOW,), 500, 0, 3)
    out = rank_strategies([make(full_price)], STRONG_MATCH, RULES)
    assert not out.ranked[0].is_markdown


def test_note_when_no_evidence_at_all():
    out = rank_strategies([make(reposition("A")), make(bundle(800))], NO_MATCH, RULES)
    assert out.note is not None and "No Qloo evidence" in out.note


def test_note_when_scores_are_close():
    out = rank_strategies([make(reposition("A"), ["exact"]), make(reposition("B"), ["exact"])],
                          STRONG_MATCH, RULES)
    assert out.note is not None and "very closely" in out.note


def test_no_feasible_strategy():
    out = rank_strategies([make(bundle(600))], STRONG_MATCH, RULES)
    assert out.ranked == ()
    assert len(out.rejected) == 1
    assert "No feasible strategy" in out.note


def test_empty_input():
    out = rank_strategies([], STRONG_MATCH, RULES)
    assert out.ranked == () and out.rejected == ()


def test_max_results_limits_output_and_says_so():
    inputs = [make(reposition(f"R{i}"), ["exact"]) for i in range(5)]
    out = rank_strategies(inputs, STRONG_MATCH, RULES)
    assert len(out.ranked) == 3
    assert "2 further feasible option(s) not shown" in out.note


def test_weights_are_recorded_for_auditability():
    out = rank_strategies([make(bundle(800), ["exact"])], STRONG_MATCH, RULES)
    top = out.ranked[0]
    assert abs(sum(top.weights.values()) - 1.0) < 1e-9
    expected = sum(top.weights[k] * top.scores[k] for k in top.weights)
    assert abs(top.weighted_total - round(expected, 4)) < 1e-4
    assert "Weighted total" in top.explanation


def test_to_rank_reason_matches_schema():
    pytest.importorskip("pydantic")
    out = rank_strategies([make(bundle(800), ["exact"])], STRONG_MATCH, RULES)
    reason = out.ranked[0].to_rank_reason()
    assert reason.weighted_total == out.ranked[0].weighted_total
    assert reason.weights["evidence"] == 0.30
