"""Hard-constraint check for experiments (Person 2).

An experiment can be created, edited and approved through routes that take a
price and a list of products. The retailer's rules must hold on every one of
those paths, not only when the rescue pipeline first proposed the strategy, so
this module re-runs constraints_service.check_candidate against the CURRENT
inventory and the plan's saved rules.

It also owns the margin stored on an experiment: the number is always
recomputed here from prices and costs. A margin sent by a client is ignored.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.agent.adapters import product_to_ref
from app.errors import NotFound
from app.models import Product
from app.models import RescuePlan as RescuePlanRow
from app.services.constraints_service import (
    INVALID_PRICE,
    CandidateStrategy,
    ConstraintResult,
    Violation,
    check_candidate,
)
from app.services.rescue_config import (
    DEFAULT_CONSTRAINTS,
    DEFAULT_STRATEGY_SETTINGS,
    Constraints,
)

CHECKED_TYPES = ("bundle", "reposition", "promotion")


def constraints_for_plan(db: Session, plan_id: Optional[int]) -> Constraints:
    """The rules the plan was generated with, or the store defaults."""
    if plan_id is None:
        return DEFAULT_CONSTRAINTS
    row = db.get(RescuePlanRow, plan_id)
    snap = (row.constraints_snapshot if row is not None else None) or {}
    try:
        return Constraints(
            min_margin_pct=snap.get("min_margin_pct", DEFAULT_CONSTRAINTS.min_margin_pct),
            max_discount_pct=snap.get("max_discount_pct", DEFAULT_CONSTRAINTS.max_discount_pct),
            max_campaign_budget=snap.get(
                "max_campaign_budget", DEFAULT_CONSTRAINTS.max_campaign_budget
            ),
            restricted_product_ids=frozenset(
                str(x) for x in snap.get("restricted_product_ids", ())
            ),
        )
    except (TypeError, ValueError):
        return DEFAULT_CONSTRAINTS


def check_experiment(
    db: Session,
    *,
    plan_id: Optional[int],
    product_pk: int,
    strategy_type: str,
    bundle_product_pks: Sequence[int],
    proposed_price: Optional[float],
    estimated_cost: float,
) -> Optional[ConstraintResult]:
    """Check an experiment against the rules.

    Strategy type ``other`` has no economics contract and returns ``None``.
    Every actionable strategy must have a price; missing price is a hard
    validation failure, not a reason to skip the constraint engine.
    """
    if strategy_type not in CHECKED_TYPES:
        return None
    if proposed_price is None:
        return ConstraintResult(
            passed=False,
            violations=(Violation(
                INVALID_PRICE,
                "A proposed price is required for bundle, reposition, and promotion experiments.",
            ),),
        )
    pks = [product_pk, *[int(x) for x in bundle_product_pks]]
    refs = []
    for pk in pks:
        p = db.get(Product, pk)
        if p is None:
            raise NotFound(f"Product {pk} not found")
        refs.append(product_to_ref(p))
    candidate = CandidateStrategy(
        strategy_type=strategy_type,
        name="Experiment",
        products=tuple(refs),
        proposed_price=proposed_price,
        estimated_experiment_cost=estimated_cost,
        planned_units=DEFAULT_STRATEGY_SETTINGS.test_units,
    )
    return check_candidate(candidate, constraints_for_plan(db, plan_id))


def margin_from(result: Optional[ConstraintResult]) -> Optional[float]:
    """The deterministic margin, or None when it could not be calculated."""
    if result is None or "margin_pct" not in result.metrics:
        return None
    return round(result.metrics["margin_pct"], 2)
