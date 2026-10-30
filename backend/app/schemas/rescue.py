"""RescuePlan contract between the decision engine (P2) and the frontend (P3).

Change this file only after a message in the team chat: P3 builds against it.
Requires Pydantic v2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class QlooStatus(str, Enum):
    STRONG_MATCH = "strong_match"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"
    ERROR = "error"  # timeout, auth failure, rate limit, etc.


class StrategyType(str, Enum):
    BUNDLE = "bundle"
    REPOSITION = "reposition"
    PROMOTION = "promotion"


class EvidenceSource(str, Enum):
    """Where a piece of information came from. The UI colours these differently."""

    QLOO = "qloo"                    # returned by the Qloo API
    RETAILER_DATA = "retailer_data"  # from the uploaded inventory
    CALCULATION = "calculation"      # computed by deterministic code
    LLM = "llm"                      # written by the language model
    ASSUMPTION = "assumption"        # unverified hypothesis


class MatchKind(str, Enum):
    """How a stocked product was linked to a Qloo result."""

    EXACT = "exact"          # same entity / same title or creator
    FUZZY = "fuzzy"          # similar name or creator, needs a human check
    THEME_ONLY = "theme_only"  # connected only through a genre or theme


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class Evidence(_Base):
    source: EvidenceSource
    note: str = Field(..., description="What this evidence says, in plain language.")
    entity_id: Optional[str] = Field(None, description="Qloo entity id, if source=qloo.")
    entity_name: Optional[str] = None
    entity_type: Optional[str] = None
    # Provider-returned signal; never conflated with internal title similarity/rank scores.
    qloo_affinity: Optional[float] = None
    source_entity_id: Optional[str] = None
    source_entity_type: Optional[str] = None
    evidence_id: Optional[int] = None
    request_params: Optional[dict] = None
    fetched_at: Optional[datetime] = None
    raw_ref: Optional[str] = Field(
        None,
        description="Pointer to the stored raw Qloo response (provenance).",
    )

    @model_validator(mode="after")
    def qloo_evidence_needs_verifiable_provenance(self) -> "Evidence":
        # A provider label is not enough: every Qloo claim must point back to
        # the exact stored response and identify the entity used as the source.
        if self.source == EvidenceSource.QLOO:
            if not self.entity_id:
                raise ValueError("Evidence with source='qloo' must include destination entity_id")
            if not self.source_entity_id:
                raise ValueError("Qloo evidence must include its source_entity_id")
            if self.evidence_id is None or self.evidence_id <= 0:
                raise ValueError("Qloo evidence must include a positive stored evidence_id")
            if self.raw_ref != f"qloo_evidence:{self.evidence_id}":
                raise ValueError("Qloo evidence raw_ref must match its stored evidence_id")
            if self.request_params is None:
                raise ValueError("Qloo evidence must preserve request_params (an empty object is valid)")
            if self.fetched_at is None:
                raise ValueError("Qloo evidence must preserve its provider fetch timestamp")
        return self


class Economics(_Base):
    """All values are computed by economics_service.py, never by the LLM."""

    selling_price: float = Field(..., gt=0, description="Bundle/proposed price.")
    unit_cost: float = Field(..., ge=0, description="Total unit cost for one sale.")
    profit_per_unit: float
    margin_pct: float
    discount_pct: float = Field(0, ge=0, le=100)
    estimated_experiment_cost: float = Field(0, ge=0)
    units_available: int = Field(..., ge=0, description="Complete units/bundles possible.")
    currency: str = "INR"
    assumptions_note: str = (
        "Gross profit before rent, labour, packaging and platform fees."
    )


class RankReason(_Base):
    """Per-dimension scores, each 0..1. No single 'magic' total is hidden."""

    feasibility: float = Field(..., ge=0, le=1)
    evidence: float = Field(..., ge=0, le=1)
    simplicity: float = Field(..., ge=0, le=1)
    cost: float = Field(..., ge=0, le=1)
    weights: dict[str, float] = Field(
        default_factory=dict, description="Weights used, so the ranking is auditable."
    )
    weighted_total: float = Field(..., ge=0, le=1)
    explanation: str = Field(..., description="Why it ranked here, in plain language.")


class CandidateProduct(_Base):
    product_id: str
    product_name: str
    match_kind: Optional[MatchKind] = None  # None for the target product itself
    role: str = "target"  # "target" or "partner"


class Strategy(_Base):
    rank: int = Field(..., ge=1, le=3)
    type: StrategyType
    name: str
    summary: str
    products: list[CandidateProduct] = Field(..., min_length=1)
    economics: Economics
    evidence: list[Evidence] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    operational_effort: str = Field("low", description="low | medium | high")
    test_plan: str
    rank_reason: RankReason
    llm_explanation: Optional[str] = Field(
        None, description="Plain-language explanation written by the LLM (optional)."
    )
    outcome_disclaimer: str = (
        "Commercial outcomes are unproven until measured in a real test."
    )


class RejectedOption(_Base):
    type: StrategyType
    name: str
    reasons: list[str] = Field(..., min_length=1)


class RescuePlan(_Base):
    product_id: str
    product_name: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    qloo_status: QlooStatus
    qloo_note: Optional[str] = Field(
        None,
        description="Coverage gap or error message shown to the user when Qloo is unavailable.",
    )
    strategies: list[Strategy] = Field(default_factory=list, max_length=3)
    rejected: list[RejectedOption] = Field(default_factory=list)
    constraints_snapshot: dict = Field(
        default_factory=dict, description="Constraint values used for this plan."
    )
    stages_completed: list[str] = Field(
        default_factory=list, description="Pipeline stages that ran successfully."
    )
    stages_failed: dict[str, str] = Field(
        default_factory=dict, description="Stage name -> short error, for partial plans."
    )
    limitations: str = (
        "Qloo associations are signals for generating hypotheses, not proof of sales. "
        "Outcomes are unproven until measured."
    )

    @model_validator(mode="after")
    def ranks_are_consecutive(self) -> "RescuePlan":
        ranks = sorted(s.rank for s in self.strategies)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("strategy ranks must be 1..n with no gaps or duplicates")
        return self

    @model_validator(mode="after")
    def no_qloo_evidence_without_a_match(self) -> "RescuePlan":
        # If Qloo failed or found nothing, no strategy may claim Qloo evidence.
        if self.qloo_status in (QlooStatus.NO_MATCH, QlooStatus.ERROR):
            for s in self.strategies:
                if any(e.source == EvidenceSource.QLOO for e in s.evidence):
                    raise ValueError(
                        "Strategy cites Qloo evidence but qloo_status is "
                        f"{self.qloo_status.value}"
                    )
        return self