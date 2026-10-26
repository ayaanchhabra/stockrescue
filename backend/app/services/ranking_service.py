"""Transparent ranking for StockRescue.

Only strategies that PASSED the constraint engine are ranked. Infeasible ones
are returned separately, with their reasons, as "rejected options".

Four dimensions, each scored 0..1 (see rescue_config.RankingSettings):

  feasibility  average of two sub-scores:
                 - margin headroom: points above the minimum margin, scaled so
                   `headroom_full_pts` above the minimum = 1.0
                 - stock cover: units available vs planned units, scaled so
                   `stock_cover_full_multiple` x planned units = 1.0
  evidence     strength of the link between a stocked product and a Qloo result
               (exact 1.0, fuzzy 0.5, theme-only 0.3 by default). The best link
               counts, links are NOT added together. 0 when Qloo gave nothing
               usable. Capped when the Qloo entity match was ambiguous.
               This is our internal score, NOT a Qloo score.
  simplicity   from operational effort: low / medium / high
  cost         1 - (experiment cost / campaign budget)

weighted_total = sum(weight x score). It is a sorting aid, not a sales forecast.

"Discount last": when enabled, feasible non-markdown strategies are listed
before markdowns, even if a markdown has a higher weighted total.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .constraints_service import (
    PROMOTION,
    CandidateStrategy,
    ConstraintResult,
)
from .rescue_config import (
    DEFAULT_RANKING_SETTINGS,
    Constraints,
    RankingSettings,
)

# Qloo status values (match QlooStatus in schemas/rescue.py)
STRONG_MATCH = "strong_match"
AMBIGUOUS = "ambiguous"
NO_MATCH = "no_match"
ERROR = "error"


@dataclass(frozen=True)
class RankInput:
    candidate: CandidateStrategy
    result: ConstraintResult
    match_kinds: Tuple[str, ...] = ()  # "exact" | "fuzzy" | "theme_only" per Qloo link
    effort: str = "low"                # "low" | "medium" | "high"


@dataclass(frozen=True)
class ScoredStrategy:
    rank: int
    candidate: CandidateStrategy
    result: ConstraintResult
    scores: Dict[str, float]
    weights: Dict[str, float]
    weighted_total: float
    explanation: str
    is_markdown: bool

    def to_rank_reason(self):
        """Convert to the RankReason schema. Needs pydantic (imported lazily)."""
        from app.schemas.rescue import RankReason

        return RankReason(
            feasibility=self.scores["feasibility"],
            evidence=self.scores["evidence"],
            simplicity=self.scores["simplicity"],
            cost=self.scores["cost"],
            weights=self.weights,
            weighted_total=self.weighted_total,
            explanation=self.explanation,
        )


@dataclass(frozen=True)
class RejectedItem:
    candidate: CandidateStrategy
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class RankingOutput:
    ranked: Tuple[ScoredStrategy, ...]
    rejected: Tuple[RejectedItem, ...]
    note: Optional[str] = None  # shown to the user when ranking confidence is limited


# ---------------------------------------------------------------------------
# Individual scores
# ---------------------------------------------------------------------------

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def feasibility_score(result: ConstraintResult, settings: RankingSettings) -> float:
    m = result.metrics
    headroom = m["margin_pct"] - m["effective_min_margin"]
    margin_part = _clamp01(headroom / settings.headroom_full_pts)
    needed = m["planned_units"] * settings.stock_cover_full_multiple
    stock_part = _clamp01(m["units_available"] / needed) if needed > 0 else 0.0
    return (margin_part + stock_part) / 2


def evidence_score(
    match_kinds: Sequence[str], qloo_status: str, settings: RankingSettings
) -> float:
    if qloo_status in (NO_MATCH, ERROR):
        return 0.0
    values = [settings.evidence_by_match.get(k, 0.0) for k in match_kinds]
    if not values:
        return 0.0
    best = max(values)
    if qloo_status == AMBIGUOUS:
        best = min(best, settings.ambiguous_evidence_cap)
    return _clamp01(best)


def simplicity_score(effort: str, settings: RankingSettings) -> float:
    if effort not in settings.effort_scores:
        raise ValueError(
            f"unknown effort '{effort}'; expected one of {sorted(settings.effort_scores)}"
        )
    return settings.effort_scores[effort]


def cost_score(experiment_cost: float, budget: float) -> float:
    if experiment_cost <= 0:
        return 1.0
    if budget <= 0:
        return 0.0
    return _clamp01(1 - experiment_cost / budget)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def _is_markdown(candidate: CandidateStrategy, result: ConstraintResult) -> bool:
    return candidate.strategy_type == PROMOTION and result.metrics.get("discount_pct", 0) > 0


def _explain(
    rank: int,
    scores: Dict[str, float],
    total: float,
    result: ConstraintResult,
    candidate: CandidateStrategy,
    effort: str,
    budget: float,
    markdown: bool,
    any_markdown: bool,
    any_non_markdown: bool,
    settings: RankingSettings,
) -> str:
    m = result.metrics
    parts = [
        f"Ranked #{rank}.",
        f"Feasibility {scores['feasibility']:.2f} (margin {m['margin_pct']:.1f}% vs "
        f"{m['effective_min_margin']:.0f}% minimum; stock covers "
        f"{int(m['units_available'])} unit(s) for {int(m['planned_units'])} planned).",
        f"Evidence {scores['evidence']:.2f}.",
        f"Simplicity {scores['simplicity']:.2f} ({effort} effort).",
        f"Cost {scores['cost']:.2f} (Rs {candidate.estimated_experiment_cost:.0f} of "
        f"Rs {budget:.0f} budget).",
        f"Weighted total {total:.2f}.",
    ]
    if settings.discount_last:
        if markdown and any_non_markdown:
            parts.append("Placed after non-discount options because discounts are tested last.")
        elif not markdown and any_markdown:
            parts.append("Placed above markdown options because discounts are tested last.")
    return " ".join(parts)


def rank_strategies(
    inputs: Sequence[RankInput],
    qloo_status: str,
    constraints: Constraints,
    settings: RankingSettings = DEFAULT_RANKING_SETTINGS,
) -> RankingOutput:
    feasible = [i for i in inputs if i.result.passed]
    rejected = tuple(
        RejectedItem(i.candidate, tuple(i.result.reasons))
        for i in inputs
        if not i.result.passed
    )

    if not feasible:
        return RankingOutput(
            (), rejected, "No feasible strategy: every candidate failed a hard constraint."
        )

    w = settings.weights.as_dict()
    rows = []
    for i in feasible:
        scores = {
            "feasibility": feasibility_score(i.result, settings),
            "evidence": evidence_score(i.match_kinds, qloo_status, settings),
            "simplicity": simplicity_score(i.effort, settings),
            "cost": cost_score(i.candidate.estimated_experiment_cost, constraints.max_campaign_budget),
        }
        total = sum(w[k] * scores[k] for k in w)
        rows.append((i, scores, _clamp01(total), _is_markdown(i.candidate, i.result)))

    any_markdown = any(r[3] for r in rows)
    any_non_markdown = any(not r[3] for r in rows)

    rows.sort(key=lambda r: ((r[3] if settings.discount_last else False), -r[2], r[0].candidate.name))

    shown = rows[: settings.max_results]
    ranked: List[ScoredStrategy] = []
    for n, (i, scores, total, markdown) in enumerate(shown, start=1):
        rounded_scores = {k: round(v, 4) for k, v in scores.items()}
        rounded_total = round(total, 4)
        ranked.append(
            ScoredStrategy(
                rank=n,
                candidate=i.candidate,
                result=i.result,
                scores=rounded_scores,
                weights=dict(w),
                weighted_total=rounded_total,
                explanation=_explain(
                    n, rounded_scores, rounded_total, i.result, i.candidate, i.effort,
                    constraints.max_campaign_budget, markdown, any_markdown,
                    any_non_markdown, settings,
                ),
                is_markdown=markdown,
            )
        )

    notes: List[str] = []
    if all(s.scores["evidence"] == 0 for s in ranked):
        notes.append(
            "No Qloo evidence supports these strategies; the order reflects commercial "
            "feasibility, simplicity and cost only."
        )
    if len(ranked) >= 2 and abs(ranked[0].weighted_total - ranked[1].weighted_total) <= settings.close_score_gap:
        notes.append("The top options score very closely; treat the order as a suggestion.")
    if len(rows) > len(shown):
        notes.append(f"{len(rows) - len(shown)} further feasible option(s) not shown.")

    return RankingOutput(tuple(ranked), rejected, " ".join(notes) or None)
