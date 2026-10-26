"""Configuration for the decision engine (constraints + ranking).

Kept in the services package (not app/config.py) so it does not collide with
the app-level settings file P1 may create.

ALL numbers here are starting defaults chosen by the team. They are meant to be
edited, not treated as industry facts. Document the values you finally use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet


# ---------------------------------------------------------------------------
# Hard constraints (enforced by deterministic code; the LLM cannot override)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Constraints:
    min_margin_pct: float = 15.0        # no strategy may fall below this gross margin
    max_discount_pct: float = 25.0      # largest discount a customer may see
    max_campaign_budget: float = 2000.0  # max direct cost of one experiment (Rs)
    restricted_product_ids: FrozenSet[str] = frozenset()  # never include these

    def __post_init__(self) -> None:
        if not (0 <= self.min_margin_pct < 100):
            raise ValueError("min_margin_pct must be >= 0 and < 100")
        if not (0 <= self.max_discount_pct <= 100):
            raise ValueError("max_discount_pct must be between 0 and 100")
        if self.max_campaign_budget < 0:
            raise ValueError("max_campaign_budget must be >= 0")

    def as_dict(self) -> dict:
        """Snapshot stored on the RescuePlan (constraints_snapshot)."""
        return {
            "min_margin_pct": self.min_margin_pct,
            "max_discount_pct": self.max_discount_pct,
            "max_campaign_budget": self.max_campaign_budget,
            "restricted_product_ids": sorted(self.restricted_product_ids),
        }


# ---------------------------------------------------------------------------
# Ranking weights and scoring rules
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RankingWeights:
    """How much each dimension counts. Must add up to 1.0."""

    feasibility: float = 0.35
    evidence: float = 0.30
    simplicity: float = 0.20
    cost: float = 0.15

    def __post_init__(self) -> None:
        values = [self.feasibility, self.evidence, self.simplicity, self.cost]
        if any(v < 0 for v in values):
            raise ValueError("weights must be >= 0")
        if abs(sum(values) - 1.0) > 1e-6:
            raise ValueError(f"weights must add up to 1.0 (got {sum(values):.4f})")

    def as_dict(self) -> Dict[str, float]:
        return {
            "feasibility": self.feasibility,
            "evidence": self.evidence,
            "simplicity": self.simplicity,
            "cost": self.cost,
        }


def _default_effort_scores() -> Dict[str, float]:
    return {"low": 1.0, "medium": 0.6, "high": 0.3}


def _default_evidence_by_match() -> Dict[str, float]:
    # How strongly a stocked product is linked to a Qloo result.
    # These are OUR internal scores, not Qloo scores.
    return {"exact": 1.0, "fuzzy": 0.5, "theme_only": 0.3}


@dataclass(frozen=True)
class RankingSettings:
    weights: RankingWeights = field(default_factory=RankingWeights)

    # "Discount last": feasible non-markdown strategies rank above markdowns.
    discount_last: bool = True

    # Feasibility sub-scores
    headroom_full_pts: float = 20.0       # margin this many points above the minimum = 1.0
    stock_cover_full_multiple: float = 2.0  # stock for 2x the planned units = 1.0

    # Evidence
    evidence_by_match: Dict[str, float] = field(default_factory=_default_evidence_by_match)
    ambiguous_evidence_cap: float = 0.3   # ambiguous Qloo entity match caps evidence score

    # Simplicity
    effort_scores: Dict[str, float] = field(default_factory=_default_effort_scores)

    # Output
    max_results: int = 3
    close_score_gap: float = 0.02         # top two within this gap => "order is a suggestion"

    def __post_init__(self) -> None:
        if self.headroom_full_pts <= 0:
            raise ValueError("headroom_full_pts must be > 0")
        if self.stock_cover_full_multiple <= 0:
            raise ValueError("stock_cover_full_multiple must be > 0")
        if self.max_results < 1:
            raise ValueError("max_results must be >= 1")


DEFAULT_CONSTRAINTS = Constraints()
DEFAULT_RANKING_SETTINGS = RankingSettings()
