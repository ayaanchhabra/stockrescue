"""Plan builder: converts the ranked output into the RescuePlan contract.

Inputs come from the pieces already built:

  strategy_generator.generate_strategies  -> drafts + skipped options
  rank_drafts() (below)                   -> constraint checks + ranking
  build_rescue_plan()                     -> the RescuePlan the frontend consumes

Every number in a strategy's Economics block is copied from the constraint
engine's calculated metrics. This module never calculates or edits money.

What the plan guarantees (also enforced by the RescuePlan validators):
- no strategy cites Qloo evidence when Qloo found nothing or failed;
- every Qloo-sourced evidence item carries a Qloo entity id;
- ranks are consecutive from 1;
- rejected options keep their reasons;
- the limitations text states every known gap (Qloo status, failed stages,
  limited ranking confidence) instead of hiding it.

Requires pydantic (imports app.schemas.rescue).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Union

from app.schemas.rescue import (
    CandidateProduct,
    Economics,
    Evidence,
    EvidenceSource,
    MatchKind,
    QlooStatus,
    RejectedOption,
    RescuePlan,
    Strategy,
    StrategyType,
)

from .constraints_service import CandidateStrategy, ProductRef, check_candidate
from .matcher_service import CandidateMatch
from .ranking_service import RankingOutput, RankInput, ScoredStrategy, rank_strategies
from .rescue_config import DEFAULT_RANKING_SETTINGS, Constraints, RankingSettings
from .strategy_generator import SkippedOption, StrategyDraft

MAX_STRATEGIES = 3  # RescuePlan.strategies allows at most three

_BASE_LIMITATIONS: str = RescuePlan.model_fields["limitations"].default

_QLOO_NOTES = {
    QlooStatus.NO_MATCH: (
        "Qloo found no matching entity for this product, so no cultural evidence is "
        "used. These options rest on retailer data and commercial rules only."
    ),
    QlooStatus.ERROR: (
        "Qloo could not be used for this plan (service error or timeout), so no cultural "
        "evidence is used. These options rest on retailer data and commercial rules only."
    ),
    QlooStatus.AMBIGUOUS: (
        "Qloo returned more than one plausible match for this product. Cultural links are "
        "treated as low-confidence until a person confirms the right entity."
    ),
}
_AMBIGUOUS_NO_EVIDENCE = (
    "Qloo returned more than one plausible match for this product and none is confirmed, "
    "so no cultural evidence is used until a person confirms the right entity."
)


# ---------------------------------------------------------------------------
# Check + rank
# ---------------------------------------------------------------------------

def rank_drafts(
    drafts: Sequence[StrategyDraft],
    qloo_status: Union[str, QlooStatus],
    constraints: Constraints,
    settings: RankingSettings = DEFAULT_RANKING_SETTINGS,
) -> RankingOutput:
    """Run the hard constraints on every draft, then rank the ones that pass."""
    status = QlooStatus(qloo_status).value
    inputs = [
        RankInput(
            d.candidate,
            check_candidate(d.candidate, constraints),
            d.match_kinds,
            d.effort,
        )
        for d in drafts
    ]
    return rank_strategies(inputs, status, constraints, settings)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

_KIND_LABEL = {"exact": "exact", "fuzzy": "fuzzy", "theme_only": "theme-only"}


def _qloo_evidence(target: ProductRef, links: Sequence[CandidateMatch]) -> List[Evidence]:
    out: List[Evidence] = []
    seen = set()
    for m in links:
        key = (m.entity.entity_id, m.product.product_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Evidence(
                source=EvidenceSource.QLOO,
                note=(
                    f"Qloo returned '{m.entity.name}' among entities related to "
                    f"'{target.name}'. Our own matching linked it to the stocked title "
                    f"'{m.product.name}' ({_KIND_LABEL.get(m.match_kind, m.match_kind)} match): "
                    f"{m.reason}"
                    + (f" Qloo-reported affinity: {m.entity.affinity:.4f}." if m.entity.affinity is not None
                       else " Qloo did not return an affinity value for this result.")
                ),
                entity_id=m.entity.entity_id,
                entity_name=m.entity.name,
                entity_type=m.entity.entity_type,
                affinity=m.entity.affinity,
                raw_ref=m.entity.raw_ref,
            )
        )
    return out


def _retailer_evidence(products: Sequence[ProductRef]) -> List[Evidence]:
    return [
        Evidence(
            source=EvidenceSource.RETAILER_DATA,
            note=(
                f"'{p.name}': {p.quantity} in stock, unit cost Rs {p.unit_cost:.2f}, "
                f"selling price Rs {p.selling_price:.2f}."
            ),
        )
        for p in products
    ]


def _calculation_evidence(scored: ScoredStrategy) -> Evidence:
    m = scored.result.metrics
    return Evidence(
        source=EvidenceSource.CALCULATION,
        note=(
            f"Price Rs {m['proposed_price']:.2f} against cost Rs {m['unit_cost']:.2f} gives "
            f"Rs {m['profit_per_unit']:.2f} gross profit per unit, a {m['margin_pct']:.2f}% margin "
            f"versus the {m['effective_min_margin']:.2f}% minimum. Discount versus normal "
            f"prices: {m['discount_pct']:.2f}% (maximum {m['effective_max_discount']:.2f}%). "
            f"{int(m['units_available'])} unit(s) can be supplied."
        ),
    )


# ---------------------------------------------------------------------------
# One strategy
# ---------------------------------------------------------------------------

def _economics(scored: ScoredStrategy) -> Economics:
    m = scored.result.metrics
    return Economics(
        selling_price=m["proposed_price"],
        unit_cost=m["unit_cost"],
        profit_per_unit=m["profit_per_unit"],
        margin_pct=m["margin_pct"],
        discount_pct=m["discount_pct"],
        estimated_experiment_cost=m["estimated_experiment_cost"],
        units_available=int(m["units_available"]),
    )


def _products(
    target: ProductRef, draft: StrategyDraft, use_qloo: bool
) -> List[CandidateProduct]:
    link_kind: Dict[str, str] = {}
    if use_qloo:
        for m in draft.links:  # links are ordered strongest first
            link_kind.setdefault(m.product.product_id, m.match_kind)
    out = []
    for p in draft.candidate.products:
        is_target = p.product_id == target.product_id
        kind = link_kind.get(p.product_id)
        out.append(
            CandidateProduct(
                product_id=p.product_id,
                product_name=p.name,
                match_kind=None if is_target or kind is None else MatchKind(kind),
                role="target" if is_target else "partner",
            )
        )
    return out


def _strategy(
    target: ProductRef, scored: ScoredStrategy, draft: StrategyDraft, use_qloo: bool
) -> Strategy:
    evidence: List[Evidence] = []
    if use_qloo:
        evidence += _qloo_evidence(target, draft.links)
    evidence += _retailer_evidence(draft.candidate.products)
    evidence.append(_calculation_evidence(scored))

    return Strategy(
        rank=scored.rank,
        type=StrategyType(draft.candidate.strategy_type),
        name=draft.candidate.name,
        summary=draft.summary,
        products=_products(target, draft, use_qloo),
        economics=_economics(scored),
        evidence=evidence,
        assumptions=list(draft.assumptions),
        risks=[*draft.risks, *scored.result.warning_messages],
        operational_effort=draft.effort,
        test_plan=draft.test_plan,
        rank_reason=scored.to_rank_reason(),
    )


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

def build_rescue_plan(
    target: ProductRef,
    qloo_status: Union[str, QlooStatus],
    drafts: Sequence[StrategyDraft],
    ranking: RankingOutput,
    constraints: Constraints,
    *,
    skipped: Sequence[SkippedOption] = (),
    qloo_note: Optional[str] = None,
    stages_completed: Sequence[str] = (),
    stages_failed: Optional[Mapping[str, str]] = None,
    extra_limitations: Sequence[str] = (),
    generated_at: Optional[datetime] = None,
) -> RescuePlan:
    """Assemble the RescuePlan.

    `drafts` must be the drafts that were ranked (they supply the text and the
    Qloo links); `ranking` is the output of rank_drafts / rank_strategies for
    them. `skipped` are options the generator could not build; they are listed
    with the constraint-rejected ones. `extra_limitations` lets the pipeline add
    facts only it knows (for example "no sales history was available").
    """
    status = QlooStatus(qloo_status)
    use_qloo = status in (QlooStatus.STRONG_MATCH, QlooStatus.AMBIGUOUS)

    by_candidate: Dict[CandidateStrategy, StrategyDraft] = {d.candidate: d for d in drafts}

    shown = list(ranking.ranked)[:MAX_STRATEGIES]
    strategies: List[Strategy] = []
    for scored in shown:
        draft = by_candidate.get(scored.candidate)
        if draft is None:
            raise ValueError(
                f"ranked strategy '{scored.candidate.name}' has no matching draft; "
                "pass the same drafts that were ranked"
            )
        strategies.append(_strategy(target, scored, draft, use_qloo))

    rejected: List[RejectedOption] = []
    for item in ranking.rejected:
        rejected.append(
            RejectedOption(
                type=StrategyType(item.candidate.strategy_type),
                name=item.candidate.name,
                reasons=list(item.reasons) or ["Failed a hard constraint."],
            )
        )
    for sk in skipped:
        rejected.append(
            RejectedOption(
                type=StrategyType(sk.strategy_type),
                name=sk.name,
                reasons=list(sk.reasons) or ["Could not be built."],
            )
        )

    failed = dict(stages_failed or {})

    limitations = [_BASE_LIMITATIONS]
    if status in _QLOO_NOTES:
        has_qloo_evidence = any(
            e.source == EvidenceSource.QLOO for s in strategies for e in s.evidence
        )
        if status == QlooStatus.AMBIGUOUS and not has_qloo_evidence:
            limitations.append(_AMBIGUOUS_NO_EVIDENCE)  # nothing was borrowed from Qloo
        else:
            limitations.append(_QLOO_NOTES[status])
    if failed:
        limitations.append(
            "Incomplete analysis: these stages failed - " + ", ".join(sorted(failed)) + "."
        )
    if ranking.note:
        limitations.append(ranking.note)
    if len(ranking.ranked) > MAX_STRATEGIES:
        limitations.append(
            f"{len(ranking.ranked) - MAX_STRATEGIES} further feasible option(s) not shown."
        )
    limitations.extend(extra_limitations)

    plan_kwargs = {}
    if generated_at is not None:
        plan_kwargs["generated_at"] = generated_at

    return RescuePlan(
        product_id=target.product_id,
        product_name=target.name,
        qloo_status=status,
        qloo_note=qloo_note if qloo_note is not None else _QLOO_NOTES.get(status),
        strategies=strategies,
        rejected=rejected,
        constraints_snapshot=constraints.as_dict(),
        stages_completed=list(stages_completed),
        stages_failed=failed,
        limitations=" ".join(limitations),
        **plan_kwargs,
    )
