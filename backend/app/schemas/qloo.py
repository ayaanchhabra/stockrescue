from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MatchStatus(str, Enum):
    STRONG = "strong"
    AMBIGUOUS = "ambiguous"
    NONE = "none"


class QlooCandidate(BaseModel):
    """One entity returned by Qloo /search (slimmed; the full response is stored as evidence)."""
    entity_id: str
    name: str
    types: list[str] = Field(default_factory=list)
    publication_year: int | None = None
    isbn13: str | None = None
    image_url: str | None = None
    short_description: str | None = None
    qloo_popularity: float | None = None          # Qloo's own field, exactly as returned
    goodreads_ratings_count: int | None = None    # Goodreads data relayed by Qloo
    creator_in_description: bool | None = None    # only set when a creator was supplied
    internal_name_similarity: float = 0.0         # OUR string similarity, NOT a Qloo score


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
    affinity: float | None = None   # Qloo's query.affinity, only if returned; never invented
    popularity: float | None = None  # Qloo's own field
    tags: list[dict[str, Any]] = Field(default_factory=list)  # e.g. {"id","name","type"} genre tags
    publication_year: int | None = None
    image_url: str | None = None
    short_description: str | None = None


class InsightsResult(BaseModel):
    source_entity_id: str
    target_type: str
    endpoint: str = "/v2/insights"
    request_params: dict[str, Any]
    entities: list[InsightEntity]   # empty list == "no useful results"
    filtered_same_title_count: int = 0  # other editions of the same book we removed
    fetched_at: str
    from_cache: bool = False
    raw: Any = None                 # full Qloo response (omitted in HTTP output; see evidence endpoint)


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


class EvidenceOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    product_pk: int | None
    kind: str
    request_path: str
    request_params: dict[str, Any]
    response_json: Any
    from_cache: bool
    fetched_at: Any
