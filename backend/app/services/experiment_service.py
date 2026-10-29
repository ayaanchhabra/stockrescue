from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ConstraintViolation, DuplicateExperiment, InvalidTransition, NotFound
from app.models import ExperimentOutcome, Product, RescueExperiment, RescuePlan
from app.schemas.experiments import (ExperimentCreate, ExperimentUpdate, OutcomeIn)
from app.services.experiment_calc import compute_outcome
from app.services.experiment_guard import check_experiment, margin_from

TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"approved", "rejected"},
    "approved": {"running", "cancelled"},
    "running": {"completed", "cancelled"},
    "completed": set(),
    "rejected": set(),
    "cancelled": set(),
}


def get_experiment(db: Session, exp_id: int) -> RescueExperiment:
    e = db.get(RescueExperiment, exp_id)
    if not e:
        raise NotFound(f"Experiment {exp_id} not found")
    return e


def _require_transition(exp: RescueExperiment, new_status: str) -> None:
    if new_status not in TRANSITIONS[exp.status]:
        raise InvalidTransition(f"Cannot change an experiment from '{exp.status}' to '{new_status}'")


def _move(exp: RescueExperiment, new_status: str) -> None:
    _require_transition(exp, new_status)
    exp.status = new_status


def _enforce_rules(db: Session, *, plan_id, product_pk, strategy_type, bundle_product_pks,
                   proposed_price, estimated_cost):
    """Hard constraints on the CURRENT inventory. Returns the server-side margin."""
    result = check_experiment(
        db, plan_id=plan_id, product_pk=product_pk, strategy_type=strategy_type,
        bundle_product_pks=bundle_product_pks, proposed_price=proposed_price,
        estimated_cost=estimated_cost,
    )
    if result is not None and not result.passed:
        raise ConstraintViolation(result.reasons)
    return margin_from(result)


def list_experiments(db: Session, status: str | None = None) -> list[RescueExperiment]:
    q = select(RescueExperiment).order_by(RescueExperiment.id.desc())
    if status:
        q = q.where(RescueExperiment.status == status)
    return list(db.scalars(q))


def create_experiment(db: Session, data: ExperimentCreate) -> RescueExperiment:
    if not db.get(Product, data.product_pk):
        raise NotFound(f"Product {data.product_pk} not found")
    if data.plan_id is not None and not db.get(RescuePlan, data.plan_id):
        raise NotFound(f"Rescue plan {data.plan_id} not found")
    if data.plan_id is not None:
        twin = db.scalar(select(RescueExperiment).where(
            RescueExperiment.plan_id == data.plan_id,
            RescueExperiment.product_pk == data.product_pk,
            RescueExperiment.title == data.title,
            RescueExperiment.strategy_type == data.strategy_type,
            RescueExperiment.status.notin_(("rejected", "cancelled")),
        ))
        if twin is not None:
            raise DuplicateExperiment(
                f"Experiment {twin.id} already exists for this strategy of this plan "
                f"(status '{twin.status}')."
            )
    margin = _enforce_rules(
        db, plan_id=data.plan_id, product_pk=data.product_pk, strategy_type=data.strategy_type,
        bundle_product_pks=data.bundle_product_pks, proposed_price=data.proposed_price,
        estimated_cost=data.estimated_cost,
    )
    values = data.model_dump()
    values["calculated_margin_pct"] = margin  # a client-supplied margin is never stored
    e = RescueExperiment(**values, status="proposed")
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def update_proposal(db: Session, exp_id: int, data: ExperimentUpdate) -> RescueExperiment:
    e = get_experiment(db, exp_id)
    if e.status != "proposed":
        raise InvalidTransition("Only proposed experiments can be edited")
    changes = data.model_dump(exclude_unset=True)
    changes.pop("calculated_margin_pct", None)  # always recomputed below
    merged = {
        "bundle_product_pks": e.bundle_product_pks, "proposed_price": e.proposed_price,
        "estimated_cost": e.estimated_cost, **changes,
    }
    margin = _enforce_rules(
        db, plan_id=e.plan_id, product_pk=e.product_pk, strategy_type=e.strategy_type,
        bundle_product_pks=merged["bundle_product_pks"] or [],
        proposed_price=merged["proposed_price"], estimated_cost=merged["estimated_cost"],
    )
    for k, v in changes.items():
        setattr(e, k, v)
    e.calculated_margin_pct = margin
    db.commit()
    db.refresh(e)
    return e


def approve(db: Session, exp_id: int, approved_by: str) -> RescueExperiment:
    e = get_experiment(db, exp_id)
    _require_transition(e, "approved")
    # Stock, prices and rules may have changed since the proposal was made.
    e.calculated_margin_pct = _enforce_rules(
        db, plan_id=e.plan_id, product_pk=e.product_pk, strategy_type=e.strategy_type,
        bundle_product_pks=e.bundle_product_pks or [], proposed_price=e.proposed_price,
        estimated_cost=e.estimated_cost,
    )
    _move(e, "approved")
    e.approved_by = approved_by
    e.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(e)
    return e


def reject(db: Session, exp_id: int) -> RescueExperiment:
    e = get_experiment(db, exp_id)
    _move(e, "rejected")
    db.commit()
    db.refresh(e)
    return e


def cancel(db: Session, exp_id: int) -> RescueExperiment:
    e = get_experiment(db, exp_id)
    _move(e, "cancelled")
    db.commit()
    db.refresh(e)
    return e


def start(db: Session, exp_id: int, start_date, end_date) -> RescueExperiment:
    e = get_experiment(db, exp_id)
    _move(e, "running")
    e.start_date, e.end_date = start_date, end_date
    db.commit()
    db.refresh(e)
    return e


def record_outcome(db: Session, exp_id: int, data: OutcomeIn) -> ExperimentOutcome:
    e = get_experiment(db, exp_id)
    if e.status != "running":
        raise InvalidTransition(f"Outcomes can only be recorded for running experiments (this one is '{e.status}')")
    calc = compute_outcome(
        items=[i.model_dump() for i in data.items],
        additional_costs=data.additional_costs,
        target_units_sold=data.target_units_sold,
        actual_days=data.actual_days,
        baseline_units=data.baseline_units,
        baseline_days=data.baseline_days,
        stock_at_start=data.stock_at_start,
        control=data.control.model_dump() if data.control else None,
        is_simulated=data.is_simulated,
    )
    out = ExperimentOutcome(
        experiment_id=e.id, is_simulated=data.is_simulated,
        inputs=data.model_dump(mode="json"), calculated=calc,
        limitations=calc["limitations"], notes=data.notes,
    )
    db.add(out)
    _move(e, "completed")
    db.commit()
    db.refresh(out)
    return out


def get_outcome(db: Session, exp_id: int) -> ExperimentOutcome:
    get_experiment(db, exp_id)
    o = db.scalar(select(ExperimentOutcome).where(ExperimentOutcome.experiment_id == exp_id))
    if not o:
        raise NotFound(f"No outcome recorded for experiment {exp_id}")
    return o


def impact_summary(db: Session) -> dict:
    """Counts and totals. Real and simulated outcomes are NEVER mixed."""
    by_status = dict(db.execute(select(RescueExperiment.status, func.count()).group_by(RescueExperiment.status)).all())
    out: dict = {
        "plans_generated": db.scalar(select(func.count()).select_from(RescuePlan)) or 0,
        "experiments_by_status": by_status,
        "experiments_total": sum(by_status.values()),
    }
    for label, flag in (("observed", False), ("simulated", True)):
        rows = db.scalars(select(ExperimentOutcome).where(ExperimentOutcome.is_simulated == flag)).all()
        out[label] = {
            "completed_experiments": len(rows),
            "units_sold": sum(r.calculated.get("target_units_sold", 0) for r in rows),
            "revenue": round(sum(r.calculated.get("revenue", 0) for r in rows), 2),
            "gross_profit": round(sum(r.calculated.get("gross_profit", 0) for r in rows), 2),
            "campaign_costs": round(sum(r.calculated.get("additional_direct_campaign_costs", 0) for r in rows), 2),
        }
    out["note"] = ("'observed' = retailer-entered results; 'simulated' = demo data. "
                   "Totals describe recorded experiments, not proven causal impact.")
    return out
