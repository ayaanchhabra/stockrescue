from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConstraintViolation, DuplicateExperiment, IdempotencyConflict, InvalidTransition, NotFound
from app.db.session import commit_or_rollback
from app.models import (ExperimentOutcome, IdempotencyRecord, Product, QlooEvidence,
                        RescueExperiment, RescuePlan)
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


def _product_snapshot(db: Session, product_pks: list[int]) -> dict:
    products = []
    for pk in dict.fromkeys(product_pks):
        p = db.get(Product, pk)
        if p is None:
            raise NotFound(f"Product {pk} not found")
        products.append({
            "product_pk": p.id,
            "sku": p.sku,
            "unit_cost": str(Decimal(str(p.unit_cost))),
            "selling_price": str(Decimal(str(p.selling_price))),
            "quantity_in_stock": int(p.quantity_in_stock),
        })
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "capture_point": "current_inventory_snapshot",
        "products": products,
    }


def _strategy_evidence_ids(strategy: dict) -> list[int]:
    ids: list[int] = []
    for evidence in strategy.get("evidence", []):
        if evidence.get("source") != "qloo":
            continue
        raw_ref = evidence.get("raw_ref") or ""
        prefix = "qloo_evidence:"
        if raw_ref.startswith(prefix):
            try:
                evidence_id = int(raw_ref[len(prefix):])
            except ValueError:
                continue
            if evidence_id not in ids:
                ids.append(evidence_id)
    return ids


def _validate_plan_relationship(
    db: Session,
    *,
    plan: RescuePlan,
    product: Product,
    strategy_type: str,
    title: str,
    proposed_action: str | None = None,
    bundle_product_pks: list[int],
    qloo_evidence_ids: list[int],
) -> None:
    """Prove that this experiment is an action from the selected saved plan."""
    if product.retailer_id != plan.retailer_id:
        raise ConstraintViolation(["The target product and rescue plan belong to different retailers."])
    plan_json = plan.plan_json if isinstance(plan.plan_json, dict) else {}
    try:
        planned_target_pk = int(plan_json.get("product_id"))
    except (TypeError, ValueError):
        raise ConstraintViolation(["The saved rescue plan has no valid target product reference."])
    if planned_target_pk != product.id:
        raise ConstraintViolation(["The experiment target product does not match the saved rescue plan."])
    plan_product_ids = {int(x) for x in (plan.product_ids or []) if str(x).isdigit()}
    if product.id not in plan_product_ids:
        raise ConstraintViolation(["The target product is not part of the saved rescue plan."])

    strategies = plan_json.get("strategies", [])
    if not isinstance(strategies, list):
        raise ConstraintViolation(["The saved rescue plan strategies are malformed."])
    selected = None
    for candidate in strategies:
        if not isinstance(candidate, dict) or candidate.get("type") != strategy_type:
            continue
        if str(candidate.get("name", ""))[:200] != title:
            continue
        products = candidate.get("products", [])
        target_roles = [x for x in products if isinstance(x, dict) and x.get("role") == "target"]
        partner_ids = []
        for item in products:
            if isinstance(item, dict) and item.get("role") == "partner":
                try:
                    partner_ids.append(int(item.get("product_id")))
                except (TypeError, ValueError):
                    pass
        if len(target_roles) != 1:
            continue
        try:
            strategy_target = int(target_roles[0].get("product_id"))
        except (TypeError, ValueError):
            continue
        if strategy_target == product.id and sorted(partner_ids) == sorted(bundle_product_pks):
            selected = candidate
            break
    if selected is None:
        raise ConstraintViolation([
            "The selected strategy, target product or bundle partners do not belong together in the saved plan."
        ])

    expected_evidence = sorted(_strategy_evidence_ids(selected))
    supplied_evidence = sorted(dict.fromkeys(int(x) for x in qloo_evidence_ids))
    if supplied_evidence != expected_evidence:
        raise ConstraintViolation(["Qloo evidence IDs do not match the selected strategy in the saved plan."])

    all_plan_evidence = set()
    for raw_id in plan.evidence_ids or []:
        try:
            evidence_id = int(raw_id)
        except (TypeError, ValueError):
            raise ConstraintViolation(["The saved plan contains an invalid evidence reference."])
        ev = db.get(QlooEvidence, evidence_id)
        if ev is None or ev.product_pk != product.id:
            raise ConstraintViolation(["The saved plan references missing or unrelated Qloo evidence."])
        all_plan_evidence.add(evidence_id)
    if not set(expected_evidence).issubset(all_plan_evidence):
        raise ConstraintViolation(["The selected strategy references evidence that is not attached to its plan."])
    for evidence_id in supplied_evidence:
        ev = db.get(QlooEvidence, evidence_id)
        if ev is None or ev.product_pk != product.id:
            raise ConstraintViolation(["Qloo evidence must belong to the experiment target product."])

    for partner_pk in bundle_product_pks:
        partner = db.get(Product, partner_pk)
        if partner is None:
            raise NotFound(f"Product {partner_pk} not found")
        if partner.retailer_id != product.retailer_id:
            raise ConstraintViolation(["A bundle partner belongs to a different retailer."])
        if partner_pk == product.id:
            raise ConstraintViolation(["The target product cannot also be a bundle partner."])
        if partner_pk not in plan_product_ids:
            raise ConstraintViolation(["A bundle partner is not included in the saved rescue plan."])



def _validate_product_relationships(
    db: Session, *, product: Product, strategy_type: str,
    bundle_product_pks: list[int], qloo_evidence_ids: list[int], plan: RescuePlan | None,
    title: str = "", proposed_action: str | None = None,
) -> None:
    if len(set(bundle_product_pks)) != len(bundle_product_pks):
        raise ConstraintViolation(["A bundle partner may only be included once."])
    if product.id in bundle_product_pks:
        raise ConstraintViolation(["The target product cannot also be a bundle partner."])
    if strategy_type == "bundle" and not bundle_product_pks:
        raise ConstraintViolation(["A bundle experiment must include at least one partner product."])
    if strategy_type != "bundle" and bundle_product_pks:
        raise ConstraintViolation(["Only bundle experiments may include partner products."])
    for partner_pk in bundle_product_pks:
        partner = db.get(Product, partner_pk)
        if partner is None:
            raise NotFound(f"Product {partner_pk} not found")
        if partner.retailer_id != product.retailer_id:
            raise ConstraintViolation(["A bundle partner belongs to a different retailer."])
    if plan is None:
        if qloo_evidence_ids:
            raise ConstraintViolation(["Qloo evidence cannot be attached without a saved rescue plan."])
        return
    _validate_plan_relationship(
        db, plan=plan, product=product, strategy_type=strategy_type, title=title,
        proposed_action=proposed_action, bundle_product_pks=bundle_product_pks,
        qloo_evidence_ids=qloo_evidence_ids,
    )


def _idempotency_fingerprint(data: ExperimentCreate) -> str:
    canonical = json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _existing_idempotent_experiment(
    db: Session, *, retailer_id: str, key: str, request_hash: str
) -> RescueExperiment | None:
    record = db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.retailer_id == retailer_id,
        IdempotencyRecord.idempotency_key == key,
    ))
    if record is None:
        return None
    if record.request_hash != request_hash:
        raise IdempotencyConflict(
            "This Idempotency-Key was already used with a different request body. "
            "Use a new key for a new operation."
        )
    if record.resource_type != "experiment" or record.resource_id is None:
        raise IdempotencyConflict("The idempotent operation exists but has no completed resource.")
    experiment = db.get(RescueExperiment, record.resource_id)
    if experiment is None:
        raise IdempotencyConflict("The resource associated with this Idempotency-Key no longer exists.")
    setattr(experiment, "_idempotent_replay", True)
    return experiment


def create_experiment(
    db: Session, data: ExperimentCreate, *, idempotency_key: str | None = None
) -> RescueExperiment:
    """Create one experiment atomically, optionally replayable by Idempotency-Key.

    The key is scoped to the retailer derived from the target product, never a
    caller-supplied retailer ID. The key row and experiment row commit together.
    """
    product = db.get(Product, data.product_pk)
    if product is None:
        raise NotFound(f"Product {data.product_pk} not found")
    plan = db.get(RescuePlan, data.plan_id) if data.plan_id is not None else None
    if data.plan_id is not None and plan is None:
        raise NotFound(f"Rescue plan {data.plan_id} not found")
    _validate_product_relationships(
        db, product=product, strategy_type=data.strategy_type,
        bundle_product_pks=data.bundle_product_pks, qloo_evidence_ids=data.qloo_evidence_ids,
        plan=plan, title=data.title, proposed_action=data.proposed_action,
    )

    request_hash = _idempotency_fingerprint(data)
    if idempotency_key is not None and not idempotency_key.strip():
        raise IdempotencyConflict("Idempotency-Key cannot be blank.")
    key = idempotency_key.strip() if idempotency_key else None
    if key:
        if not 1 <= len(key) <= 128:
            raise IdempotencyConflict("Idempotency-Key must contain between 1 and 128 characters.")
        replay = _existing_idempotent_experiment(
            db, retailer_id=product.retailer_id, key=key, request_hash=request_hash
        )
        if replay is not None:
            return replay

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
    values["calculated_margin_pct"] = margin
    values["product_snapshot"] = _product_snapshot(db, [data.product_pk, *data.bundle_product_pks])
    experiment = RescueExperiment(**values, status="proposed")
    db.add(experiment)

    if key:
        db.add(IdempotencyRecord(
            retailer_id=product.retailer_id,
            idempotency_key=key,
            request_hash=request_hash,
            resource_type="experiment",
        ))
    try:
        db.flush()
        if key:
            record = db.scalar(select(IdempotencyRecord).where(
                IdempotencyRecord.retailer_id == product.retailer_id,
                IdempotencyRecord.idempotency_key == key,
            ))
            record.resource_id = experiment.id
        commit_or_rollback(db)
        return experiment
    except IntegrityError:
        db.rollback()
        if key:
            replay = _existing_idempotent_experiment(
                db, retailer_id=product.retailer_id, key=key, request_hash=request_hash
            )
            if replay is not None:
                return replay
        raise DuplicateExperiment("A concurrent request already created this experiment.")
    except Exception:
        db.rollback()
        raise


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
    product = db.get(Product, e.product_pk)
    if product is None:
        raise NotFound(f"Product {e.product_pk} not found")
    plan = db.get(RescuePlan, e.plan_id) if e.plan_id is not None else None
    _validate_product_relationships(
        db, product=product, strategy_type=e.strategy_type,
        bundle_product_pks=merged["bundle_product_pks"] or [],
        qloo_evidence_ids=e.qloo_evidence_ids or [], plan=plan, title=e.title,
    )
    margin = _enforce_rules(
        db, plan_id=e.plan_id, product_pk=e.product_pk, strategy_type=e.strategy_type,
        bundle_product_pks=merged["bundle_product_pks"] or [],
        proposed_price=merged["proposed_price"], estimated_cost=merged["estimated_cost"],
    )
    for k, v in changes.items():
        setattr(e, k, v)
    e.calculated_margin_pct = margin
    commit_or_rollback(db)
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
    commit_or_rollback(db)
    return e


def reject(db: Session, exp_id: int) -> RescueExperiment:
    e = get_experiment(db, exp_id)
    _move(e, "rejected")
    commit_or_rollback(db)
    return e


def cancel(db: Session, exp_id: int) -> RescueExperiment:
    e = get_experiment(db, exp_id)
    _move(e, "cancelled")
    commit_or_rollback(db)
    return e


def start(db: Session, exp_id: int, start_date, end_date) -> RescueExperiment:
    e = get_experiment(db, exp_id)
    if end_date < start_date:
        raise ConstraintViolation(["Experiment end date must be on or after its start date."])
    e.calculated_margin_pct = _enforce_rules(
        db, plan_id=e.plan_id, product_pk=e.product_pk, strategy_type=e.strategy_type,
        bundle_product_pks=e.bundle_product_pks or [], proposed_price=e.proposed_price,
        estimated_cost=e.estimated_cost,
    )
    e.product_snapshot = _product_snapshot(db, [e.product_pk, *(e.bundle_product_pks or [])])
    e.product_snapshot["capture_point"] = "experiment_start"
    _move(e, "running")
    e.start_date, e.end_date = start_date, end_date
    commit_or_rollback(db)
    return e


def record_outcome(db: Session, exp_id: int, data: OutcomeIn) -> ExperimentOutcome:
    e = get_experiment(db, exp_id)
    if e.status != "running":
        raise InvalidTransition(f"Outcomes can only be recorded for running experiments (this one is '{e.status}')")

    expected_days = (e.end_date - e.start_date).days + 1 if e.start_date and e.end_date else None
    if expected_days is None:
        raise ConstraintViolation(["The experiment has no saved start/end dates; its duration cannot be verified."])
    if data.actual_days != expected_days:
        raise ConstraintViolation([
            f"actual_days ({data.actual_days}) must match the saved experiment date range ({expected_days} inclusive days)."
        ])

    snapshot = e.product_snapshot or {}
    snapshot_items = snapshot.get("products") if isinstance(snapshot, dict) else None
    if not isinstance(snapshot_items, list) or not snapshot_items:
        raise ConstraintViolation(["This experiment has no saved product/cost/stock snapshot; outcomes cannot be audited safely."])
    by_sku = {str(row.get("sku")): row for row in snapshot_items if isinstance(row, dict) and row.get("sku")}
    expected_pks = [e.product_pk, *(e.bundle_product_pks or [])]
    expected_rows = [row for row in snapshot_items if isinstance(row, dict) and row.get("product_pk") in expected_pks]
    expected_skus = {str(row["sku"]) for row in expected_rows}
    if len(expected_rows) != len(set(expected_pks)) or not expected_skus:
        raise ConstraintViolation(["The saved experiment snapshot does not cover every experiment product."])

    incoming = [item.model_dump() for item in data.items]
    incoming_skus = [str(item.get("sku", "")).strip() for item in incoming]
    if len(set(incoming_skus)) != len(incoming_skus):
        raise ConstraintViolation(["Each SKU may appear only once in an experiment outcome."])
    if set(incoming_skus) != expected_skus:
        missing = sorted(expected_skus - set(incoming_skus))
        extra = sorted(set(incoming_skus) - expected_skus)
        details = []
        if missing:
            details.append("missing SKU(s): " + ", ".join(missing))
        if extra:
            details.append("unrelated SKU(s): " + ", ".join(extra))
        raise ConstraintViolation(["Outcome products must exactly match the experiment snapshot (" + "; ".join(details) + ")."])

    normalized_items = []
    units_by_sku: dict[str, int] = {}
    for item in incoming:
        sku = str(item["sku"]).strip()
        snap = by_sku.get(sku)
        if snap is None:
            raise ConstraintViolation([f"SKU {sku} is not part of this experiment."])
        units = item["units_sold"]
        stock = int(snap["quantity_in_stock"])
        if units > stock:
            raise ConstraintViolation([f"SKU {sku} sold {units} units but only {stock} were in stock at experiment start."])
        if item.get("unit_cost") is not None:
            # The request field remains accepted for old clients, but never drives accounting.
            pass
        units_by_sku[sku] = units
        normalized_items.append({
            "sku": sku,
            "units_sold": units,
            "actual_selling_price": item["actual_selling_price"],
            "unit_cost": snap["unit_cost"],
        })

    target_snapshot = next((row for row in expected_rows if row.get("product_pk") == e.product_pk), None)
    if target_snapshot is None:
        raise ConstraintViolation(["The target product is missing from the saved experiment snapshot."])
    target_sku = str(target_snapshot["sku"])
    derived_target_units = units_by_sku[target_sku]
    if data.target_units_sold is not None and data.target_units_sold != derived_target_units:
        raise ConstraintViolation([
            f"target_units_sold ({data.target_units_sold}) does not match the target SKU sales ({derived_target_units})."
        ])
    if e.strategy_type == "bundle":
        component_quantities = set(units_by_sku.values())
        if len(component_quantities) != 1:
            raise ConstraintViolation(["Bundle component units_sold must agree; each bundle sale consumes one unit of every component."])
    target_stock = int(target_snapshot["quantity_in_stock"])
    if data.stock_at_start is not None and data.stock_at_start != target_stock:
        raise ConstraintViolation([
            f"stock_at_start ({data.stock_at_start}) does not match the saved target stock ({target_stock})."
        ])

    calc = compute_outcome(
        items=normalized_items,
        additional_costs=data.additional_costs,
        target_units_sold=derived_target_units,
        actual_days=data.actual_days,
        baseline_units=data.baseline_units,
        baseline_days=data.baseline_days,
        stock_at_start=target_stock,
        control=data.control.model_dump() if data.control else None,
        is_simulated=data.is_simulated,
    )
    inputs = data.model_dump(mode="json")
    # Store the canonical, server-priced rows as the submitted item list too;
    # do not preserve an untrusted client unit_cost as if it were authoritative.
    inputs["items"] = normalized_items
    inputs["normalized_items"] = normalized_items
    inputs["server_accounting_snapshot"] = snapshot
    inputs["target_units_sold_derived_from_sku"] = target_sku
    out = ExperimentOutcome(
        experiment_id=e.id, is_simulated=data.is_simulated,
        inputs=inputs, calculated=calc, limitations=calc["limitations"], notes=data.notes,
    )
    db.add(out)
    _move(e, "completed")
    commit_or_rollback(db)
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
