"""Rescue API (Person 2).

    POST /rescue/evaluate                                  re-check an edited strategy (workspace)
    POST /rescue/{product_pk}                              run the pipeline -> RescuePlan
    GET  /rescue/plans/{plan_id}                           a stored RescuePlan
    POST /rescue/plans/{plan_id}/strategies/{rank}/experiment
                                                           hand a strategy to the experiment tracker

Static routes are declared BEFORE /{product_pk}; otherwise "evaluate" would be
parsed as a product pk and fail validation.

Errors use Person 1's format {"error": "<code>", "message": "<text>"} and are
returned directly, so they look the same with or without main.py's handlers.
No route ever returns a stack trace.

To enable (Person 1, app/main.py):
    from app.api import rescue
    app.include_router(rescue.router)
and add expose_headers=["X-Rescue-Plan-Id"] to the CORSMiddleware call.
"""

from __future__ import annotations

import functools
import logging
from typing import Callable, Optional

from fastapi import APIRouter, Body, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.agent import adapters
from app.agent.adapters import DbQlooGateway
from app.agent.explanation import explain_plan
from app.agent.llm import completer_from_env
from app.agent.workflow import ExplainFn, RescueRequest, run_rescue
from app.db.session import get_db
from app.errors import NotFound
from app.schemas.experiments import ExperimentOut
from app.schemas.rescue import Economics, RescuePlan
from app.schemas.rescue_api import (
    EvaluateIn,
    EvaluateOut,
    RescueRunIn,
    ViolationOut,
    constraints_from,
)
from app.services import experiment_service
from app.services.constraints_service import CandidateStrategy, check_candidate

log = logging.getLogger(__name__)

router = APIRouter(prefix="/rescue", tags=["rescue"])

PLAN_ID_HEADER = "X-Rescue-Plan-Id"

GatewayFactory = Callable[[Session, bool], object]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def _internal_error() -> JSONResponse:
    return _err(500, "internal_error", "Something went wrong on our side.")


def _safe(fn):
    """Any unexpected exception -> logged stack trace + plain 500 body."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001
            log.exception("Unhandled error in rescue API")
            return _internal_error()

    return wrapper


# ---------------------------------------------------------------------------
# Dependencies (overridable in tests)
# ---------------------------------------------------------------------------

def _default_gateway_factory(db: Session, refresh: bool) -> DbQlooGateway:
    return DbQlooGateway(db, refresh=refresh)


def get_gateway_factory() -> GatewayFactory:
    return _default_gateway_factory


@functools.lru_cache(maxsize=1)
def _cached_completer():
    return completer_from_env()


def get_explainer() -> Optional[ExplainFn]:
    complete = _cached_completer()
    if complete is None:
        return None
    return functools.partial(explain_plan, complete=complete)


# ---------------------------------------------------------------------------
# Routes (static paths first)
# ---------------------------------------------------------------------------

@router.post("/evaluate", response_model=EvaluateOut)
@_safe
def evaluate(body: EvaluateIn, db: Session = Depends(get_db)):
    """Re-check a strategy after the retailer edits its products or price.
    Every number comes from constraints_service.check_candidate."""
    try:
        constraints = constraints_from(body.constraints)
    except ValueError as e:
        return _err(422, "invalid_constraints", str(e))
    try:
        pks = [int(pid) for pid in body.product_ids]
    except ValueError:
        return _err(422, "invalid_product_id", "Product ids must be the integer product pk.")
    found = adapters.load_products(db, pks)
    missing = [pk for pk in pks if pk not in found]
    if missing:
        return _err(404, "not_found", f"Product {missing[0]} not found")

    candidate = CandidateStrategy(
        strategy_type=body.strategy_type.value,
        name="Edited strategy",
        products=tuple(adapters.product_to_ref(found[pk]) for pk in pks),
        proposed_price=body.proposed_price,
        estimated_experiment_cost=body.estimated_experiment_cost,
        planned_units=body.planned_units,
    )
    result = check_candidate(candidate, constraints)
    m = result.metrics
    economics = None
    if m:
        economics = Economics(
            selling_price=m["proposed_price"],
            unit_cost=m["unit_cost"],
            profit_per_unit=m["profit_per_unit"],
            margin_pct=m["margin_pct"],
            discount_pct=m["discount_pct"],
            estimated_experiment_cost=m["estimated_experiment_cost"],
            units_available=int(m["units_available"]),
        )
    return EvaluateOut(
        passed=result.passed,
        violations=[ViolationOut(code=v.code, message=v.message) for v in result.violations],
        economics=economics,
        effective_min_margin=m.get("effective_min_margin"),
        effective_max_discount=m.get("effective_max_discount"),
    )


@router.get("/plans/{plan_id}", response_model=RescuePlan)
@_safe
def get_plan(plan_id: int, db: Session = Depends(get_db)):
    found = adapters.load_plan(db, plan_id)
    if found is None:
        return _err(404, "not_found", f"Rescue plan {plan_id} not found")
    return found[1]


@router.post("/plans/{plan_id}/strategies/{rank}/experiment", response_model=ExperimentOut,
             status_code=201)
@_safe
def create_experiment_from_strategy(plan_id: int, rank: int, db: Session = Depends(get_db)):
    """Create a 'proposed' experiment in Person 1's tracker from one strategy.
    The retailer still approves it with POST /experiments/{id}/approve."""
    found = adapters.load_plan(db, plan_id)
    if found is None:
        return _err(404, "not_found", f"Rescue plan {plan_id} not found")
    try:
        data = adapters.strategy_to_experiment_create(found[1], rank, plan_id)
    except KeyError:
        return _err(404, "not_found", f"Rescue plan {plan_id} has no strategy ranked {rank}")
    except ValueError as e:
        return _err(422, "invalid_plan", f"Plan cannot be turned into an experiment: {e}")
    try:
        exp = experiment_service.create_experiment(db, data)
    except NotFound as e:
        return _err(404, "not_found", str(e))
    return ExperimentOut.model_validate(exp)


@router.post("/{product_pk}", response_model=RescuePlan)
@_safe
def rescue_product(
    product_pk: int,
    response: Response,
    body: Optional[RescueRunIn] = Body(None),
    db: Session = Depends(get_db),
    gateway_factory: GatewayFactory = Depends(get_gateway_factory),
    explainer: Optional[ExplainFn] = Depends(get_explainer),
):
    """Run the rescue pipeline for one product and return its RescuePlan.
    Qloo or LLM failures give a partial plan (see stages_failed), not an error."""
    body = body or RescueRunIn()
    try:
        constraints = constraints_from(body.constraints)
    except ValueError as e:
        return _err(422, "invalid_constraints", str(e))

    target = adapters.load_target(db, product_pk)
    if target is None:
        return _err(404, "not_found", f"Product {product_pk} not found")

    retailer_id = target.retailer_id
    target_item = adapters.product_to_stock_item(target, None)
    stock = adapters.load_stock(db, retailer_id)
    target_item = next((s for s in stock if s.product.product_id == str(product_pk)), target_item)

    gateway = gateway_factory(db, body.refresh_qloo)
    request = RescueRequest(target_item, stock, constraints, adapters.has_sales_history(target))
    plan = run_rescue(request, gateway, explain=explainer)

    try:
        plan_id = adapters.save_plan(db, plan, retailer_id, list(getattr(gateway, "evidence_ids", [])))
    except Exception:  # noqa: BLE001 - persisted plans are required for downstream experiments
        db.rollback()
        log.exception("Could not persist rescue plan for product %s", product_pk)
        return _err(500, "plan_persistence_failed",
                    "The rescue plan could not be saved. No experiment can be created from this result.")
    response.headers[PLAN_ID_HEADER] = str(plan_id)
    return plan
