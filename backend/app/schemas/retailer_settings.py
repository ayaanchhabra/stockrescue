"""Validated retailer-level decision settings for the bookstore MVP."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConstraintsSettingsIn(_StrictModel):
    min_margin_pct: float = Field(default=15.0, ge=0, lt=100)
    max_discount_pct: float = Field(default=25.0, ge=0, le=100)
    max_campaign_budget: float = Field(default=2000.0, ge=0)
    restricted_product_ids: list[str] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_restricted_ids(self):
        cleaned = [str(item).strip() for item in self.restricted_product_ids]
        if any(not item for item in cleaned):
            raise ValueError("restricted_product_ids cannot contain blank values")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("restricted_product_ids cannot contain duplicates")
        self.restricted_product_ids = cleaned
        return self


class StrategySettingsIn(_StrictModel):
    test_units: int = Field(default=3, ge=1, le=10000)
    test_days: int = Field(default=14, ge=1, le=365)
    bundle_discount_pct: float = Field(default=10.0, ge=0, le=100)
    promo_discount_pct: float = Field(default=15.0, ge=0, le=100)
    min_promo_discount_pct: float = Field(default=5.0, ge=0, le=100)
    max_bundle_attempts: int = Field(default=3, ge=1, le=20)
    max_display_titles: int = Field(default=3, ge=1, le=20)
    bundle_campaign_cost: float = Field(default=100.0, ge=0)
    reposition_campaign_cost: float = Field(default=150.0, ge=0)
    promotion_campaign_cost: float = Field(default=50.0, ge=0)


class RankingWeightsIn(_StrictModel):
    feasibility: float = Field(default=0.35, ge=0, le=1)
    evidence: float = Field(default=0.30, ge=0, le=1)
    simplicity: float = Field(default=0.20, ge=0, le=1)
    cost: float = Field(default=0.15, ge=0, le=1)

    @model_validator(mode="after")
    def sum_to_one(self):
        total = self.feasibility + self.evidence + self.simplicity + self.cost
        if abs(total - 1.0) > 1e-6:
            raise ValueError("ranking weights must add up to 1.0")
        return self


class RankingSettingsIn(_StrictModel):
    weights: RankingWeightsIn = Field(default_factory=RankingWeightsIn)
    discount_last: bool = True
    headroom_full_pts: float = Field(default=20.0, gt=0, le=100)
    stock_cover_full_multiple: float = Field(default=2.0, gt=0, le=100)
    ambiguous_evidence_cap: float = Field(default=0.3, ge=0, le=1)
    max_results: int = Field(default=3, ge=1, le=10)
    close_score_gap: float = Field(default=0.02, ge=0, le=1)


class SlowMovingSettingsIn(_StrictModel):
    no_recent_sales_min_stock_days: int = Field(default=30, ge=1, le=3650)
    aged_stock_days: int = Field(default=90, ge=1, le=3650)
    low_sales_cover_days: int = Field(default=180, ge=1, le=3650)


class RetailerSettingsIn(_StrictModel):
    """Full replacement settings payload. Currency is fixed to INR for this MVP."""
    currency: str = Field(default="INR", pattern="^INR$")
    constraints: ConstraintsSettingsIn = Field(default_factory=ConstraintsSettingsIn)
    strategy: StrategySettingsIn = Field(default_factory=StrategySettingsIn)
    ranking: RankingSettingsIn = Field(default_factory=RankingSettingsIn)
    slow_moving: SlowMovingSettingsIn = Field(default_factory=SlowMovingSettingsIn)
