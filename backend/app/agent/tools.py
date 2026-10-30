"""Named tool registry for the decision engine (master plan deliverable #2).

Each tool is a plain function with a JSON-schema description of its arguments,
named as in the master plan. Tools contain NO new business logic: they call
the existing deterministic services, Person 1's code through the adapters, and
run_rescue. They exist so the engine's capabilities are discoverable and
callable by name (for example by a future LLM tool-calling loop, a CLI or a
debug endpoint).

What this is NOT: there is no LLM choosing tools today. The rescue workflow is
the bounded pipeline in app.agent.workflow; this registry does not change it.

Usage:
    list_tools()                                    -> [{"name", "description", "parameters"}]
    call_tool("calculate_bundle_economics", {...}, db=session)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.services import economics_service as eco
from app.services.constraints_service import CandidateStrategy, check_candidate
from app.services.matcher_service import match_candidates
from app.services.retailer_settings_service import load_decision_settings
from app.tenant import retailer_id_for

from . import adapters
from .workflow import RescueRequest, run_rescue


class ToolError(ValueError):
    """Unknown tool, bad arguments or a missing product."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON schema (type=object)
    fn: Callable[..., Any]
    needs_db: bool = True


_REGISTRY: Dict[str, Tool] = {}

_JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
}


def _schema(required: Dict[str, Any], optional: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    props = {**required, **(optional or {})}
    return {"type": "object", "properties": props, "required": sorted(required),
            "additionalProperties": False}


def _tool(name: str, description: str, parameters: Dict[str, Any], needs_db: bool = True):
    def register(fn):
        _REGISTRY[name] = Tool(name, description, parameters, fn, needs_db)
        return fn
    return register


STR = {"type": "string"}
INT = {"type": "integer"}
NUM = {"type": "number"}
BOOL = {"type": "boolean"}
IDS = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _product(db: Session, product_id: str):
    try:
        pk = int(product_id)
    except (TypeError, ValueError):
        raise ToolError(f"product_id must be the integer product pk as a string (got {product_id!r})")
    p = adapters.load_target(db, pk)
    if p is None:
        raise ToolError(f"Product {product_id} not found")
    return p


def _refs(db: Session, product_ids: List[str]):
    return [adapters.product_to_ref(_product(db, pid)) for pid in product_ids]


def _request(db: Session, product_id: str) -> RescueRequest:
    p = _product(db, product_id)
    stock = adapters.load_stock(db, p.retailer_id)
    target = next(s for s in stock if s.product.product_id == str(p.id))
    decision_settings = load_decision_settings(db, p.retailer_id)
    return RescueRequest(target, stock, decision_settings.constraints, adapters.has_sales_history(p))


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@_tool("get_inventory", "All products belonging to the authenticated retailer with stock, cost and price.",
       _schema({}))
def get_inventory(db: Session):
    return [
        {"product_id": s.product.product_id, "name": s.product.name, "quantity": s.product.quantity,
         "unit_cost": s.product.unit_cost, "selling_price": s.product.selling_price,
         "creators": list(s.creators), "tags": list(s.tags), "qloo_entity_id": s.qloo_entity_id}
        for s in adapters.load_stock(db, retailer_id_for(db))
    ]


@_tool("get_product_sales_history",
       "Recorded sales snapshot for one product. Missing values stay null; nothing is estimated.",
       _schema({"product_id": STR}))
def get_product_sales_history(db: Session, product_id: str):
    p = _product(db, product_id)
    return {"product_id": str(p.id), "units_sold_30d": p.units_sold_30d,
            "units_sold_60d": p.units_sold_60d, "units_sold_90d": p.units_sold_90d,
            "days_in_stock": p.days_in_stock, "has_sales_history": adapters.has_sales_history(p)}


@_tool("resolve_qloo_entity", "Resolve a product to a Qloo entity (strong / ambiguous / no match).",
       _schema({"product_id": STR}, {"refresh": BOOL}))
def resolve_qloo_entity(db: Session, product_id: str, refresh: bool = False):
    req = _request(db, product_id)
    gw = adapters.DbQlooGateway(db, refresh=refresh)
    r = gw.resolve(req.target)
    return {"status": r.status.value, "entity_id": r.entity_id, "entity_name": r.entity_name,
            "note": r.note, "alternatives": list(r.alternatives), "raw_ref": r.raw_ref}


@_tool("get_qloo_insights",
       "Entities Qloo relates to the product. Needs a strong or human-confirmed match.",
       _schema({"product_id": STR}))
def get_qloo_insights(db: Session, product_id: str):
    req = _request(db, product_id)
    gw = adapters.DbQlooGateway(db)
    res = gw.resolve(req.target)
    if not res.entity_id:
        return {"status": res.status.value, "entities": [],
                "note": "No usable Qloo entity for this product, so insights were not requested."}
    ents = gw.get_insights(res)
    return {"status": res.status.value,
            "entities": [{"entity_id": e.entity_id, "name": e.name, "entity_type": e.entity_type,
                          "tags": list(e.tags), "qloo_affinity": e.affinity,
                          "raw_ref": e.raw_ref} for e in ents]}


@_tool("find_available_inventory_candidates",
       "Stocked products linked to what Qloo returned (exact / fuzzy / theme-only, our own labels).",
       _schema({"product_id": STR}))
def find_available_inventory_candidates(db: Session, product_id: str):
    req = _request(db, product_id)
    gw = adapters.DbQlooGateway(db)
    res = gw.resolve(req.target)
    ents = gw.get_insights(res) if res.entity_id else ()
    matches = match_candidates(ents, req.stock, [req.target.product.product_id])
    return [{"product_id": m.product.product_id, "name": m.product.name, "match_kind": m.match_kind,
             "qloo_entity_id": m.entity.entity_id, "qloo_entity_name": m.entity.name,
             "qloo_affinity": m.entity.affinity,
             "reason": m.reason, "in_stock": m.product.quantity} for m in matches]


@_tool("calculate_bundle_economics",
       "Deterministic economics for selling these products together at one price.",
       _schema({"product_ids": IDS, "proposed_price": NUM}))
def calculate_bundle_economics(db: Session, product_ids: List[str], proposed_price: float):
    refs = _refs(db, product_ids)
    costs = [r.unit_cost for r in refs]
    try:
        return {
            "bundle_unit_cost": eco.bundle_unit_cost(costs),
            "gross_profit_per_unit": eco.bundle_gross_profit(proposed_price, costs),
            "margin_pct": eco.bundle_margin_pct(proposed_price, costs),
            "discount_vs_separate_pct": eco.bundle_discount_vs_separate_pct(
                proposed_price, [r.selling_price for r in refs]),
            "complete_units_available": eco.max_complete_bundles([r.quantity for r in refs]),
            "assumptions": "Gross profit before rent, labour, packaging and platform fees.",
        }
    except eco.EconomicsError as e:
        raise ToolError(str(e))


@_tool("evaluate_business_constraints",
       "Run the hard constraints (stock, margin floor, discount cap, budget, restrictions).",
       _schema({"strategy_type": {"type": "string", "enum": ["bundle", "reposition", "promotion"]},
                "product_ids": IDS, "proposed_price": NUM},
               {"estimated_experiment_cost": NUM, "planned_units": INT}))
def evaluate_business_constraints(db: Session, strategy_type: str, product_ids: List[str],
                                  proposed_price: float, estimated_experiment_cost: float = 0.0,
                                  planned_units: int | None = None):
    decision_settings = load_decision_settings(db)
    cand = CandidateStrategy(strategy_type, "Tool check", tuple(_refs(db, product_ids)),
                             proposed_price, estimated_experiment_cost,
                             planned_units or decision_settings.strategy.test_units)
    r = check_candidate(cand, decision_settings.constraints)
    return {"passed": r.passed, "violations": [{"code": v.code, "message": v.message} for v in r.violations],
            "metrics": dict(r.metrics)}


@_tool("rank_rescue_experiments",
       "Ranked feasible experiments for a product, with per-dimension scores (not a forecast).",
       _schema({"product_id": STR}))
def rank_rescue_experiments(db: Session, product_id: str):
    decision_settings = load_decision_settings(db)
    plan = run_rescue(
        _request(db, product_id), adapters.DbQlooGateway(db),
        ranking_settings=decision_settings.ranking, strategy_settings=decision_settings.strategy,
    )
    return {"qloo_status": plan.qloo_status.value,
            "ranked": [{"rank": s.rank, "type": s.type.value, "name": s.name,
                        "weighted_total": s.rank_reason.weighted_total,
                        "explanation": s.rank_reason.explanation} for s in plan.strategies],
            "rejected": [{"type": o.type.value, "name": o.name, "reasons": o.reasons} for o in plan.rejected]}


@_tool("generate_experiment_plan", "The full RescuePlan for a product (same as POST /rescue/{pk}).",
       _schema({"product_id": STR}))
def generate_experiment_plan(db: Session, product_id: str):
    decision_settings = load_decision_settings(db)
    plan = run_rescue(
        _request(db, product_id), adapters.DbQlooGateway(db),
        ranking_settings=decision_settings.ranking, strategy_settings=decision_settings.strategy,
    )
    snapshot = dict(plan.constraints_snapshot)
    snapshot["settings_snapshot"] = decision_settings.payload
    return plan.model_copy(update={"constraints_snapshot": snapshot}).model_dump(mode="json")


@_tool("save_rescue_plan", "Generate and store a RescuePlan; returns its plan id.",
       _schema({"product_id": STR}))
def save_rescue_plan(db: Session, product_id: str):
    req = _request(db, product_id)
    gw = adapters.DbQlooGateway(db)
    decision_settings = load_decision_settings(db)
    plan = run_rescue(
        req, gw, ranking_settings=decision_settings.ranking,
        strategy_settings=decision_settings.strategy,
    )
    snapshot = dict(plan.constraints_snapshot)
    snapshot["settings_snapshot"] = decision_settings.payload
    plan = plan.model_copy(update={"constraints_snapshot": snapshot})
    retailer = _product(db, product_id).retailer_id
    return {"plan_id": adapters.save_plan(db, plan, retailer, gw.evidence_ids)}


# ---------------------------------------------------------------------------
# Registry API
# ---------------------------------------------------------------------------

def list_tools() -> List[Dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in _REGISTRY.values()]


def _validate(tool: Tool, args: Dict[str, Any]) -> None:
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")
    schema = tool.parameters
    props = schema["properties"]
    unknown = sorted(set(args) - set(props))
    if unknown:
        raise ToolError(f"{tool.name}: unknown argument(s) {unknown}")
    missing = [k for k in schema["required"] if k not in args]
    if missing:
        raise ToolError(f"{tool.name}: missing argument(s) {missing}")
    for key, value in args.items():
        spec = props[key]
        expected = _JSON_TYPES[spec["type"]]
        bad_bool = isinstance(value, bool) and spec["type"] in ("integer", "number")
        if bad_bool or not isinstance(value, expected):
            raise ToolError(f"{tool.name}: '{key}' must be {spec['type']}")
        if spec["type"] == "array":
            if not all(isinstance(v, str) for v in value):
                raise ToolError(f"{tool.name}: '{key}' items must be strings")
            if not spec.get("minItems", 0) <= len(value) <= spec.get("maxItems", 10**6):
                raise ToolError(f"{tool.name}: '{key}' has the wrong number of items")
        if "enum" in spec and value not in spec["enum"]:
            raise ToolError(f"{tool.name}: '{key}' must be one of {spec['enum']}")


def call_tool(name: str, args: Optional[Dict[str, Any]] = None, *, db: Optional[Session] = None) -> Any:
    tool = _REGISTRY.get(name)
    if tool is None:
        raise ToolError(f"unknown tool '{name}'; available: {sorted(_REGISTRY)}")
    args = dict(args or {})
    _validate(tool, args)
    if tool.needs_db:
        if db is None:
            raise ToolError(f"{name} needs a database session")
        return tool.fn(db, **args)
    return tool.fn(**args)
