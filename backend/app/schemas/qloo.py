from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MatchStatus(str, Enum):
    STRONG = "strong"
    AMBIGUOUS = "ambiguous"
    NONE = "none"


class QlooCandidate(BaseModel):
    entity_id: str
    name: str
    types: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    internal_name_similarity: float = 0.0  # OUR string similarity, NOT a Qloo score


class ResolveResult(BaseModel):
    status: MatchStatus
    query: str
    chosen: QlooCandidate | None = None
    candidates: list[QlooCandidate] = Field(default_factory=list)
    reason: str
    endpoint: str = "/search"
    request_params: dict[str, Any] = Field(default_factory=dict)
    fetched_at: str
    from_cache: bool = False
    raw: Any = None


class InsightEntity(BaseModel):
    entity_id: str
    name: str
    types: list[str] = Field(default_factory=list)
    affinity: float | None = None  # only if Qloo returned it; never invented
    properties: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class InsightsResult(BaseModel):
    source_entity_id: str
    target_type: str
    endpoint: str = "/v2/insights"
    request_params: dict[str, Any]
    entities: list[InsightEntity]  # empty list == "no useful results"
    fetched_at: str
    from_cache: bool = False
    raw: Any = None


class MappingOut(BaseModel):
    model_config = {"from_attributes": True}
    product_pk: int
    qloo_entity_id: str | None
    qloo_entity_type: str | None
    matched_name: str | None
    match_status: str          # strong | ambiguous | none  (our classification)
    match_reason: str
    verification_status: str   # unverified | confirmed | rejected
    candidates: list[Any]
    evidence_id: int | None
    last_checked_at: Any
    coverage_gap: bool = False  # True when Qloo has no usable entity for this product


class ConfirmIn(BaseModel):
    entity_id: str


class InsightsIn(BaseModel):
    take: int = Field(default=10, ge=1, le=30)


class InsightsOut(BaseModel):
    evidence_id: int
    result: InsightsResult
