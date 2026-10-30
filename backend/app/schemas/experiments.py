from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

StrategyType = Literal["bundle", "reposition", "promotion"]


class ExperimentCreate(BaseModel):
    plan_id: int | None = None
    product_pk: int
    strategy_type: StrategyType
    title: str = Field(min_length=1, max_length=200)
    proposed_action: str = Field(min_length=1)
    bundle_product_pks: list[int] = Field(default_factory=list)
    proposed_price: float | None = Field(default=None, gt=0)
    estimated_cost: float = Field(default=0, ge=0)
    calculated_margin_pct: float | None = Field(
        default=None, description="Ignored: the server recomputes the margin from prices and costs.")
    qloo_evidence_ids: list[int] = Field(default_factory=list)


class ExperimentUpdate(BaseModel):
    """Retailer edits a proposal BEFORE approving it."""
    proposed_action: str | None = Field(default=None, min_length=1)
    bundle_product_pks: list[int] | None = None
    proposed_price: float | None = Field(default=None, gt=0)
    estimated_cost: float | None = Field(default=None, ge=0)
    calculated_margin_pct: float | None = Field(
        default=None, description="Ignored: the server recomputes the margin from prices and costs.")


class ExperimentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plan_id: int | None
    product_pk: int
    strategy_type: str
    title: str
    proposed_action: str
    bundle_product_pks: list[Any]
    proposed_price: float | None
    estimated_cost: float
    calculated_margin_pct: float | None
    qloo_evidence_ids: list[Any]
    status: str
    start_date: date | None
    end_date: date | None
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime


class ApproveIn(BaseModel):
    approved_by: str = Field(default="retailer", min_length=1, max_length=100)


class StartIn(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _order(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class OutcomeItemIn(BaseModel):
    # `product_id` is accepted as a backwards-compatible input alias, but it
    # always contains the retailer SKU (never a database PK or free-form name).
    sku: str = Field(validation_alias=AliasChoices("sku", "product_id"), min_length=1, max_length=64)
    units_sold: int = Field(ge=0)
    actual_selling_price: float = Field(ge=0)  # actual price paid, net of discounts
    unit_cost: float | None = Field(default=None, ge=0, description="Deprecated/untrusted; server uses experiment snapshot.")


class ControlIn(BaseModel):
    """A comparable product (or period) that did NOT receive the intervention."""
    baseline_units: int = Field(ge=0)
    baseline_days: int = Field(ge=1)
    experiment_units: int = Field(ge=0)
    experiment_days: int = Field(ge=1)


class OutcomeIn(BaseModel):
    is_simulated: bool = False
    items: list[OutcomeItemIn] = Field(min_length=1)
    additional_costs: float = Field(default=0, ge=0)
    target_units_sold: int | None = Field(default=None, ge=0, description="Optional consistency assertion; server derives this from target SKU sales.")
    actual_days: int = Field(ge=1)
    baseline_units: int | None = Field(default=None, ge=0)
    baseline_days: int | None = Field(default=None, ge=1)
    stock_at_start: int | None = Field(default=None, ge=0, description="Deprecated consistency assertion; server uses the saved start snapshot.")
    control: ControlIn | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _baseline_pair(self):
        if (self.baseline_units is None) != (self.baseline_days is None):
            raise ValueError("baseline_units and baseline_days must be provided together")
        return self


class OutcomeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    experiment_id: int
    is_simulated: bool
    inputs: dict[str, Any]
    calculated: dict[str, Any]
    limitations: list[Any]
    notes: str | None
    recorded_at: datetime
