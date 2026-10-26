from datetime import datetime, timezone

import pytest

pytest.importorskip("pydantic")

from app.schemas.rescue import (  # noqa: E402
    EvidenceSource,
    MatchKind,
    QlooStatus,
    RescuePlan,
    StrategyType,
)
from app.services.constraints_service import ProductRef  # noqa: E402
from app.services.matcher_service import (  # noqa: E402
    EXACT,
    FUZZY,
    THEME_ONLY,
    CandidateMatch,
    QlooRelatedEntity,
)
from app.services.plan_builder import build_rescue_plan, rank_drafts  # noqa: E402
from app.services.rescue_config import (  # noqa: E402
    DEFAULT_RANKING_SETTINGS,
    Constraints,
    RankingSettings,
)
from app.services.strategy_generator import generate_strategies  # noqa: E402

# --- illustrative test fixtures (NOT real Qloo data) --------------------------

SLOW = ProductRef("B001", "Slow Literary Novel", quantity=24, unit_cost=350, selling_price=500)
PARTNER = ProductRef("B002", "Companion Essays", quantity=5, unit_cost=200, selling_price=400)
RULES = Constraints(min_margin_pct=15, max_discount_pct=25, max_campaign_budget=2000)


def link(product, kind=EXACT, entity_name="Related Work", similarity=1.0):
    entity = QlooRelatedEntity(
        f"ent-{product.product_id}-{entity_name}", entity_name, "book", (), (), f"raw/{product.product_id}"
    )
    return CandidateMatch(product, kind, entity, f"test link to {product.name}", similarity)


def make_plan(matches, status=QlooStatus.STRONG_MATCH, rules=RULES, target=SLOW,
              ranking_settings=DEFAULT_RANKING_SETTINGS, **kw):
    gen = generate_strategies(target, matches, rules)
    ranking = rank_drafts(gen.drafts, status, rules, ranking_settings)
    return build_rescue_plan(target, status, gen.drafts, ranking, rules, skipped=gen.skipped, **kw)


def types(plan):
    return [s.type for s in plan.strategies]


def get(plan, strategy_type):
    """The ranked strategy of one type (the order itself is the ranking service's job)."""
    found = [s for s in plan.strategies if s.type == strategy_type]
    assert len(found) == 1, f"expected exactly one {strategy_type}, got {types(plan)}"
    return found[0]


# --- the normal case ------------------------------------------------------------

def test_strong_match_gives_three_ranked_strategies_with_discount_last():
    plan = make_plan([link(PARTNER)])
    assert isinstance(plan, RescuePlan)
    assert [s.rank for s in plan.strategies] == [1, 2, 3]
    assert set(types(plan)) == {StrategyType.BUNDLE, StrategyType.REPOSITION, StrategyType.PROMOTION}
    assert plan.strategies[-1].type == StrategyType.PROMOTION  # discount last
    assert plan.qloo_status == QlooStatus.STRONG_MATCH
    assert plan.rejected == []
    assert plan.product_id == "B001" and plan.product_name == "Slow Literary Novel"


def test_economics_are_copied_from_the_constraint_engine():
    plan = make_plan([link(PARTNER)])
    bundle = get(plan, StrategyType.BUNDLE).economics
    assert bundle.selling_price == 810
    assert bundle.unit_cost == 550
    assert bundle.profit_per_unit == 260
    assert bundle.margin_pct == pytest.approx(32.1, abs=0.1)
    assert bundle.discount_pct == 10
    assert bundle.units_available == 5
    assert bundle.estimated_experiment_cost == 100
    promo = get(plan, StrategyType.PROMOTION).economics
    assert promo.selling_price == 425 and promo.discount_pct == 15
    display = get(plan, StrategyType.REPOSITION).economics
    assert display.selling_price == 500 and display.discount_pct == 0 and display.margin_pct == 30


def test_rank_reason_shows_scores_and_the_weights_used():
    plan = make_plan([link(PARTNER)])
    rr = plan.strategies[0].rank_reason
    assert rr.weights == DEFAULT_RANKING_SETTINGS.weights.as_dict()
    assert 0 <= rr.weighted_total <= 1 and rr.explanation.startswith("Ranked #1")
    totals = [s.rank_reason.weighted_total for s in plan.strategies[:2]]
    assert totals == sorted(totals, reverse=True)


def test_qloo_evidence_carries_the_entity_id_and_provenance():
    plan = make_plan([link(PARTNER, EXACT, "Related Work")])
    bundle = get(plan, StrategyType.BUNDLE)
    qloo = [e for e in bundle.evidence if e.source == EvidenceSource.QLOO]
    assert len(qloo) == 1
    assert qloo[0].entity_id == "ent-B002-Related Work"
    assert qloo[0].entity_name == "Related Work" and qloo[0].raw_ref == "raw/B002"
    assert "Related Work" in qloo[0].note and "Companion Essays" in qloo[0].note
    assert "(exact match)" in qloo[0].note


def test_every_strategy_labels_its_evidence_sources():
    plan = make_plan([link(PARTNER)])
    for s in plan.strategies:
        sources = {e.source for e in s.evidence}
        assert EvidenceSource.RETAILER_DATA in sources
        assert EvidenceSource.CALCULATION in sources
    promo = get(plan, StrategyType.PROMOTION)
    assert EvidenceSource.QLOO not in {e.source for e in promo.evidence}


def test_partner_is_labelled_with_how_it_was_matched():
    plan = make_plan([link(PARTNER, FUZZY)])
    products = {p.product_id: p for p in get(plan, StrategyType.BUNDLE).products}
    assert products["B001"].role == "target" and products["B001"].match_kind is None
    assert products["B002"].role == "partner" and products["B002"].match_kind == MatchKind.FUZZY


def test_text_fields_come_through_and_no_llm_text_is_invented():
    plan = make_plan([link(PARTNER)])
    for s in plan.strategies:
        assert s.summary and s.test_plan and s.assumptions
        assert s.llm_explanation is None
        assert "unproven until measured" in s.outcome_disclaimer


def test_constraints_snapshot_records_the_rules_used():
    plan = make_plan([link(PARTNER)])
    assert plan.constraints_snapshot == {
        "min_margin_pct": 15, "max_discount_pct": 25,
        "max_campaign_budget": 2000, "restricted_product_ids": [],
    }


def test_plan_round_trips_through_json_for_the_frontend():
    plan = make_plan([link(PARTNER)])
    again = RescuePlan.model_validate_json(plan.model_dump_json())
    assert again == plan


def test_generated_at_can_be_pinned():
    when = datetime(2026, 10, 28, 9, 30, tzinfo=timezone.utc)
    assert make_plan([link(PARTNER)], generated_at=when).generated_at == when


# --- Qloo found nothing / failed / ambiguous ------------------------------------------

def test_no_match_plan_has_no_qloo_evidence_and_says_why():
    plan = make_plan([], status=QlooStatus.NO_MATCH)
    assert plan.qloo_status == QlooStatus.NO_MATCH
    assert "no matching entity" in plan.qloo_note
    assert "no matching entity" in plan.limitations
    assert types(plan) == [StrategyType.REPOSITION, StrategyType.PROMOTION]
    for s in plan.strategies:
        assert EvidenceSource.QLOO not in {e.source for e in s.evidence}
        assert s.rank_reason.evidence == 0
    # the bundle that could not be built is shown as a rejected option
    assert [r.type for r in plan.rejected] == [StrategyType.BUNDLE]
    assert "no partner" in plan.rejected[0].reasons[0]


def test_error_status_strips_qloo_evidence_even_if_links_were_passed_in():
    # Defensive: a stale link must never turn into Qloo evidence after a failure.
    plan = make_plan([link(PARTNER)], status=QlooStatus.ERROR)
    assert plan.qloo_status == QlooStatus.ERROR
    for s in plan.strategies:
        assert EvidenceSource.QLOO not in {e.source for e in s.evidence}
        assert all(p.match_kind is None for p in s.products)
        assert s.rank_reason.evidence == 0
    assert "service error or timeout" in plan.qloo_note


def test_ambiguous_match_keeps_evidence_but_caps_its_weight_and_warns():
    plan = make_plan([link(PARTNER, EXACT)], status=QlooStatus.AMBIGUOUS)
    bundle = get(plan, StrategyType.BUNDLE)
    assert any(e.source == EvidenceSource.QLOO for e in bundle.evidence)
    assert bundle.rank_reason.evidence <= DEFAULT_RANKING_SETTINGS.ambiguous_evidence_cap
    assert "more than one plausible match" in plan.qloo_note
    assert "low-confidence" in plan.limitations


def test_strong_match_has_no_qloo_note_by_default():
    assert make_plan([link(PARTNER)]).qloo_note is None


def test_a_given_qloo_note_wins():
    plan = make_plan([], status=QlooStatus.NO_MATCH, qloo_note="Title not found in Qloo.")
    assert plan.qloo_note == "Title not found in Qloo."


# --- rejected options ---------------------------------------------------------------

def test_constraint_rejections_keep_their_reasons():
    low = ProductRef("B003", "Low Stock Partner", quantity=1, unit_cost=200, selling_price=400)
    plan = make_plan([link(low, EXACT), link(PARTNER, FUZZY)])
    rejected = [r for r in plan.rejected if r.type == StrategyType.BUNDLE]
    assert len(rejected) == 1
    assert "Low Stock Partner" in rejected[0].name
    assert any("needs 3" in reason for reason in rejected[0].reasons)
    # and the feasible bundle with the next partner is still ranked
    assert "Companion Essays" in get(plan, StrategyType.BUNDLE).name


def test_options_the_generator_could_not_build_are_listed_as_rejected():
    tight = ProductRef("B009", "Thin Margin Book", 24, 480, 500)
    plan = make_plan([], status=QlooStatus.NO_MATCH, target=tight)
    names = {r.name for r in plan.rejected}
    assert any(n.startswith("Controlled promotion") for n in names)
    assert all(r.reasons for r in plan.rejected)


def test_when_nothing_is_feasible_the_plan_still_returns_with_the_reasons():
    broke = ProductRef("B009", "Loss Making Book", 24, 600, 500)  # cost above price
    plan = make_plan([], status=QlooStatus.NO_MATCH, target=broke)
    assert plan.strategies == []
    assert plan.rejected and all(r.reasons for r in plan.rejected)
    assert "No feasible strategy" in plan.limitations


# --- limitations, failed stages, extras ----------------------------------------------

def test_failed_stages_are_recorded_and_called_out():
    plan = make_plan(
        [], status=QlooStatus.ERROR,
        stages_completed=["resolve"], stages_failed={"insights": "timeout after 8s"},
    )
    assert plan.stages_completed == ["resolve"]
    assert plan.stages_failed == {"insights": "timeout after 8s"}
    assert "insights" in plan.limitations and "Incomplete" in plan.limitations


def test_extra_limitations_from_the_pipeline_are_appended():
    note = "No sales history was available; that is not evidence the product is unpopular."
    plan = make_plan([link(PARTNER)], extra_limitations=[note])
    assert note in plan.limitations
    assert plan.limitations.startswith("Qloo associations are signals")


def test_limits_on_ranking_confidence_reach_the_plan():
    plan = make_plan([], status=QlooStatus.NO_MATCH)
    assert "order reflects commercial feasibility" in plan.limitations


# --- guards ----------------------------------------------------------------------------

def test_never_more_than_three_strategies_even_if_ranking_returns_more():
    gen = generate_strategies(SLOW, [link(PARTNER)], RULES)
    extra_partners = [
        ProductRef(f"P{i}", f"Extra Partner {i}", 10, 200, 400) for i in range(3)
    ]
    more = []
    for p in extra_partners:
        more += list(generate_strategies(SLOW, [link(p)], RULES).drafts)
    drafts = list(gen.drafts) + [d for d in more if d.candidate.strategy_type == "bundle"]
    assert len(drafts) >= 6

    wide = RankingSettings(max_results=10)
    ranking = rank_drafts(drafts, QlooStatus.STRONG_MATCH, RULES, wide)
    plan = build_rescue_plan(SLOW, QlooStatus.STRONG_MATCH, drafts, ranking, RULES)
    assert len(plan.strategies) == 3
    assert [s.rank for s in plan.strategies] == [1, 2, 3]
    assert "further feasible option(s) not shown" in plan.limitations


def test_ranked_strategy_without_its_draft_is_an_error_not_a_silent_gap():
    gen = generate_strategies(SLOW, [link(PARTNER)], RULES)
    ranking = rank_drafts(gen.drafts, QlooStatus.STRONG_MATCH, RULES)
    with pytest.raises(ValueError):
        build_rescue_plan(SLOW, QlooStatus.STRONG_MATCH, gen.drafts[:1], ranking, RULES)


def test_status_may_be_given_as_a_plain_string():
    gen = generate_strategies(SLOW, [link(PARTNER)], RULES)
    ranking = rank_drafts(gen.drafts, "strong_match", RULES)
    plan = build_rescue_plan(SLOW, "strong_match", gen.drafts, ranking, RULES)
    assert plan.qloo_status == QlooStatus.STRONG_MATCH


def test_unknown_status_is_rejected():
    with pytest.raises(ValueError):
        rank_drafts([], "maybe", RULES)


def test_weaker_link_scores_lower_evidence_in_the_plan():
    strong = get(make_plan([link(PARTNER, EXACT)]), StrategyType.BUNDLE).rank_reason.evidence
    weak = get(make_plan([link(PARTNER, THEME_ONLY)]), StrategyType.BUNDLE).rank_reason.evidence
    assert strong > weak


def test_strategy_types_serialise_as_plain_strings_for_the_frontend():
    plan = make_plan([link(PARTNER)])
    dumped = {s["type"] for s in plan.model_dump(mode="json")["strategies"]}
    assert dumped == {"bundle", "reposition", "promotion"}
    assert isinstance(plan.strategies[0].type, StrategyType)
