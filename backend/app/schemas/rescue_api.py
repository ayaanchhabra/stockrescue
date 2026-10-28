"""Request/response models for the rescue API (Person 2, app/api/rescue.py).

The RescuePlan contract itself stays in schemas/rescue.py (unchanged).
Requires Pydantic v2.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.rescue import Economics, StrategyType
from app.services.rescue_config import DEFAULT_CONSTRAINTS, DEFAULT_STRATEGY_SETTINGS, Constraints


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConstraintsIn(_In):
    """Optional overrides of the store-wide rules. Omitted fields keep the defaults."""

    min_margin_pct: Optional[float] = None
    max_discount_pct: Optional[float] = None
    max_campaign_budget: Optional[float] = None
    restricted_product_ids: list[str] = Field(default_factory=list)

    def to_constraints(self) -> Constraints:
        """Merge over the defaults. Raises ValueError for out-of-range values."""
        d = DEFAULT_CONSTRAINTS
        return Constraints(
            min_margin_pct=d.min_margin_pct if self.min_margin_pct is None else self.min_margin_pct,
            max_discount_pct=d.max_discount_pct if self.max_discount_pct is None else self.max_discount_pct,
            max_campaign_budget=(
                d.max_campaign_budget if self.max_campaign_budget is None else self.max_campaign_budget
            ),
            restricted_product_ids=frozenset(self.restricted_product_ids) | d.restricted_product_ids,
        )


def constraints_from(body: Optional[ConstraintsIn]) -> Constraints:
    return body.to_constraints() if body is not None else DEFAULT_CONSTRAINTS


class RescueRunIn(_In):
    constraints: Optional[ConstraintsIn] = None
    refresh_qloo: bool = Field(
        False, description="Re-run Qloo entity resolution even if a mapping is stored."
    )


class EvaluateIn(_In):
    """A retailer-edited strategy to re-check (Rescue Lab workspace)."""

    strategy_type: StrategyType
    product_ids: list[str] = Field(
        ..., min_length=1, max_length=5,
        description="Same ids as in RescuePlan (str of the product pk); target first.",
    )
    proposed_price: float = Field(..., gt=0, description="Price for ONE unit of the strategy.")
    estimated_experiment_cost: float = Field(0, ge=0)
    planned_units: int = Field(DEFAULT_STRATEGY_SETTINGS.test_units, ge=1)
    constraints: Optional[ConstraintsIn] = None


class ViolationOut(BaseModel):
    code: str
    message: str


class EvaluateOut(BaseModel):
    passed: bool
    violations: list[ViolationOut] = Field(default_factory=list)
    economics: Optional[Economics] = Field(
        None, description="Calculated by deterministic code; None when inputs were invalid."
    )
    effective_min_margin: Optional[float] = None
    effective_max_discount: Optional[float] = None
