from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import InvalidTransition, NotFound, StockCommitmentConflict
from app.models import (ExperimentOutcome, ExperimentStockReservation, Product,
                        QlooEvidence, RescueExperiment, RescuePlan)
from app.schemas.experiments import ExperimentCreate, ExperimentUpdate, OutcomeIn
from app.services.experiment_calc import compute_outcome
from app.tenant import retailer_id_for

TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"approved", "rejected"},
    "approved": {"running", "cancelled"},
    "running": {"completed", "cancelled"},
    "completed": set(),
    "rejected": set(),
    "cancelled": set(),
}
ACTIVE_STATES = ("approved", "running")


def get_experiment(db: Session, exp_id: int) -> RescueExperiment:
    e = db.scalar(
        select(RescueExperiment)
        .join(Product, Product.id == RescueExperiment.product_pk)
        .where(RescueExperiment.id == exp_id,
               Product.retailer_id == retailer_id_for(db))
    )
    if not e:
        raise NotFound(f"Experiment {exp_id} not found")
    return e


def _move(exp: RescueExperiment, new_status: str) -> None:
    if new_status not in TRANSITIONS[exp.status]:
        raise InvalidTransition(f"Cannot change an experiment from '{exp.status}' to '{new_status}'")
    exp.status = new_status


def _product_ids(exp: RescueExperiment) -> set[int]:
    return {int(exp.product_pk), *(int(pk) for pk in (exp.bundle_product_pks or []))}


def _products_for_experiment(db: Session, exp: RescueExperiment, lock: bool = False) -> dict[int, Product]:
    ids = sorted(_product_ids(exp))
    stmt = (select(Product)
            .where(Product.id.in_(ids), Product.retailer_id == retailer_id_for(db))
            .order_by(Product.id))
    if lock:
        stmt = stmt.with_for_update()
    products = {p.id: p for p in db.scalars(stmt).all()}
    if set(products) != set(ids):
        raise NotFound("An experiment product is missing or belongs to another retailer")
    return products


def _reserve_experiment_stock(db: Session, exp: RescueExperiment) -> None:
    """Reserve SKUs exclusively for an approved/running experiment.

    The current data contract has no planned-unit quantity per component. To
    fail safely, this version permits at most one active experiment to include
    any given SKU. It does not decrement physical on-hand inventory. Product
    rows are locked in primary-key order; the reservation table has a unique
    product_pk constraint as a second concurrency guard.
    """
    products = _products_for_experiment(db, exp, lock=True)
    unavailable = [p.sku for p in products.values() if p.quantity_in_stock <= 0]
    if unavailable:
        raise StockCommitmentConflict([f"{sku} (no stock available)" for sku in unavailable])

    tenant = retailer_id_for(db)
    requested_ids = set(products)

    # Also inspect active experiments so legacy approved/running rows created
    # before the reservation table existed cannot be bypassed.
    active = db.scalars(
        select(RescueExperiment)
        .join(Product, Product.id == RescueExperiment.product_pk)
        .where(Product.retailer_id == tenant,
               RescueExperiment.status.in_(ACTIVE_STATES),
               RescueExperiment.id != exp.id)
        .with_for_update()
    ).all()
    conflicts: set[int] = set()
    for other in active:
        conflicts.update(requested_ids.intersection(_product_ids(other)))

    existing_reservations = db.scalars(
        select(ExperimentStockReservation)
        .where(ExperimentStockReservation.product_pk.in_(requested_ids))
        .with_for_update()
    ).all()
    conflicts.update(r.product_pk for r in existing_reservations if r.experiment_id != exp.id)

    if conflicts:
        raise StockCommitmentConflict([products[pk].sku for pk in conflicts if pk in products])

    existing_for_this = {r.product_pk for r in existing_reservations if r.experiment_id == exp.id}
    try:
        for product_pk in sorted(requested_ids - existing_for_this):
            db.add(ExperimentStockReservation(
                experiment_id=exp.id,
                product_pk=product_pk,
                retailer_id=tenant,
            ))
        db.flush()
    except IntegrityError as exc:
        # The caller wraps this in a SAVEPOINT; do not roll back unrelated work.
        # A concurrent transaction may have won the unique product reservation.
        raise StockCommitmentConflict([products[pk].sku for pk in requested_ids]) from exc


def _release_reservations(db: Session, experiment_id: int) -> None:
    db.query(ExperimentStockReservation).filter(
        ExperimentStockReservation.experiment_id == experiment_id
    ).delete(synchronize_session=False)


def list_experiments(db: Session, status: str | None = None) -> list[RescueExperiment]:
    q = (select(RescueExperiment)
         .join(Product, Product.id == RescueExperiment.product_pk)
         .where(Product.retailer_id == retailer_id_for(db))
         .order_by(RescueExperiment.id.desc()))
    if status:
        q = q.where(RescueExperiment.status == status)
    return list(db.scalars(q))


def create_experiment(db: Session, data: ExperimentCreate) -> RescueExperiment:
    tenant = retailer_id_for(db)
    product_ids = {data.product_pk, *(int(pk) for pk in data.bundle_product_pks)}
    products = db.scalars(select(Product).where(
        Product.id.in_(product_ids), Product.retailer_id == tenant
    )).all()
    if len(products) != len(product_ids):
        raise NotFound("A target or bundle product does not exist for this retailer")

    if data.plan_id is not None:
        plan = db.scalar(select(RescuePlan).where(
            RescuePlan.id == data.plan_id, RescuePlan.retailer_id == tenant
        ))
        if plan is None:
            raise NotFound(f"Rescue plan {data.plan_id} not found")
        if data.product_pk not in {int(pid) for pid in (plan.product_ids or [])}:
            raise InvalidTransition("Experiment target does not belong to the selected rescue plan")
        if not product_ids.issubset({int(pid) for pid in (plan.product_ids or [])}):
            raise InvalidTransition("A bundle product does not belong to the selected rescue plan")

    evidence_ids = set(int(i) for i in data.qloo_evidence_ids)
    if evidence_ids:
        evidence = db.scalars(select(QlooEvidence).where(
            QlooEvidence.id.in_(evidence_ids), QlooEvidence.product_pk == data.product_pk
        )).all()
        if len(evidence) != len(evidence_ids):
            raise NotFound("Qloo evidence is missing or does not belong to the experiment target")

    e = RescueExperiment(**data.model_dump(), status="proposed")
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def update_proposal(db: Session, exp_id: int, data: ExperimentUpdate) -> RescueExperiment:
    e = get_experiment(db, exp_id)
    if e.status != "proposed":
        raise InvalidTransition("Only proposed experiments can be edited")
    changes = data.model_dump(exclude_unset=True)
    proposed_bundle = changes.get("bundle_product_pks", e.bundle_product_pks)
    proposed_ids = {e.product_pk, *(int(pk) for pk in (proposed_bundle or []))}
    products = db.scalars(select(Product).where(
        Product.id.in_(proposed_ids), Product.retailer_id == retailer_id_for(db)
    )).all()
    if len(products) != len(proposed_ids):
        raise NotFound("A target or bundle product does not exist for this retailer")
    for k, v in changes.items():
        setattr(e, k, v)
    db.commit()
    db.refresh(e)
    return e


def approve(db: Session, exp_id: int, approved_by: str) -> RescueExperiment:
    e = get_experiment(db, exp_id)
    with db.begin_nested():
        _reserve_experiment_stock(db, e)
        _move(e, "approved")
        e.approved_by = approved_by
        e.approved_at = datetime.now(timezone.utc)
        db.flush()
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
    _release_reservations(db, e.id)
    db.commit()
    db.refresh(e)
    return e


def start(db: Session, exp_id: int, start_date, end_date) -> RescueExperiment:
    e = get_experiment(db, exp_id)
    # Recheck under product-row locks at start as well as at approval.
    with db.begin_nested():
        _reserve_experiment_stock(db, e)
        _move(e, "running")
        e.start_date, e.end_date = start_date, end_date
        db.flush()
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
    _release_reservations(db, e.id)
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
    """Retailer-scoped counts and totals. Real and simulated outcomes are NEVER mixed."""
    tenant = retailer_id_for(db)
    by_status = dict(db.execute(
        select(RescueExperiment.status, func.count())
        .join(Product, Product.id == RescueExperiment.product_pk)
        .where(Product.retailer_id == tenant)
        .group_by(RescueExperiment.status)
    ).all())
    out: dict = {
        "plans_generated": db.scalar(select(func.count()).select_from(RescuePlan).where(RescuePlan.retailer_id == tenant)) or 0,
        "experiments_by_status": by_status,
        "experiments_total": sum(by_status.values()),
    }
    for label, flag in (("observed", False), ("simulated", True)):
        rows = db.scalars(
            select(ExperimentOutcome)
            .join(RescueExperiment, RescueExperiment.id == ExperimentOutcome.experiment_id)
            .join(Product, Product.id == RescueExperiment.product_pk)
            .where(Product.retailer_id == tenant, ExperimentOutcome.is_simulated == flag)
        ).all()
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
