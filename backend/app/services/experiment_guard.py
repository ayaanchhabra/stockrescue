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
from app.services.retailer_settings_service import load_decision_settings

CHECKED_TYPES = ("bundle", "reposition", "promotion")


def constraints_for_plan(
    db: Session, plan_id: Optional[int], settings_snapshot: dict | None = None
) -> Constraints:
    """Resolve the saved experiment/plan rules, falling back to current retailer settings.

    An experiment snapshot takes precedence because it records the configuration
    under which the proposal was created. Older experiments fall back to the plan
    snapshot, then to the retailer's current configuration for direct proposals.
    """
    raw = None
    if isinstance(settings_snapshot, dict):
        raw = settings_snapshot.get("constraints")
    if raw is None and plan_id is not None:
        row = db.get(RescuePlanRow, plan_id)
        if row is None:
            raise NotFound(f"Rescue plan {plan_id} not found")
        plan_rules = row.constraints_snapshot
        if plan_rules in (None, {}):
            return load_decision_settings(db).constraints
        if not isinstance(plan_rules, dict):
            from app.errors import ConstraintViolation
            raise ConstraintViolation(["Saved plan constraints must be a JSON object."])
        plan_settings = plan_rules.get("settings_snapshot")
        raw = plan_settings.get("constraints") if isinstance(plan_settings, dict) else plan_rules
    if raw is None:
        return load_decision_settings(db).constraints
    if not isinstance(raw, dict):
        from app.errors import ConstraintViolation
        raise ConstraintViolation(["Saved experiment constraints must be a JSON object."])
    try:
        return Constraints(
            min_margin_pct=raw.get("min_margin_pct", DEFAULT_CONSTRAINTS.min_margin_pct),
            max_discount_pct=raw.get("max_discount_pct", DEFAULT_CONSTRAINTS.max_discount_pct),
            max_campaign_budget=raw.get("max_campaign_budget", DEFAULT_CONSTRAINTS.max_campaign_budget),
            restricted_product_ids=frozenset(str(x) for x in raw.get("restricted_product_ids", [])),
        )
    except (TypeError, ValueError) as exc:
        from app.errors import ConstraintViolation
        raise ConstraintViolation([f"Saved experiment constraints are invalid: {exc}"]) from exc


def check_experiment(
    db: Session,
    *,
    plan_id: Optional[int],
    product_pk: int,
    strategy_type: str,
    bundle_product_pks: Sequence[int],
    proposed_price: Optional[float],
    estimated_cost: float,
    settings_snapshot: dict | None = None,
) -> Optional[ConstraintResult]:
    """Check an experiment against the rules.

    Unknown strategy types fail closed. Every actionable strategy must have a
    price; unsupported values are never treated as constraint-free.
    """
    if strategy_type not in CHECKED_TYPES:
        return ConstraintResult(
            passed=False,
            violations=(Violation("INVALID_PLAN", f"Unsupported strategy type: {strategy_type!r}."),),
        )
    if strategy_type == "bundle" and not bundle_product_pks:
        return ConstraintResult(
            passed=False,
            violations=(Violation("INVALID_PLAN", "A bundle experiment must include at least one partner product."),),
        )
    if strategy_type != "bundle" and bundle_product_pks:
        return ConstraintResult(
            passed=False,
            violations=(Violation("INVALID_PLAN", "Only bundle experiments may include partner products."),),
        )
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
    saved_strategy = (settings_snapshot or {}).get("strategy", {}) if isinstance(settings_snapshot, dict) else {}
    planned_units = saved_strategy.get("test_units", DEFAULT_STRATEGY_SETTINGS.test_units)
    candidate = CandidateStrategy(
        strategy_type=strategy_type,
        name="Experiment",
        products=tuple(refs),
        proposed_price=proposed_price,
        estimated_experiment_cost=estimated_cost,
        planned_units=planned_units,
    )
    return check_candidate(candidate, constraints_for_plan(db, plan_id, settings_snapshot))


def margin_from(result: Optional[ConstraintResult]) -> Optional[float]:
    """The deterministic margin, or None when it could not be calculated."""
    if result is None or "margin_pct" not in result.metrics:
        return None
    return round(result.metrics["margin_pct"], 2)
