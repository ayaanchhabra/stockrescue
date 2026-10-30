"""Adapters between Person 1's real code (DB models, Qloo entity resolution,
experiments) and the decision engine's plain inputs.

This is the ONE place where database / CSV names become decision-engine names
(docs/business_rules.md section 8):

    Product.id (int pk)              -> ProductRef.product_id (as a string)
    quantity_in_stock                -> quantity
    minimum_acceptable_margin        -> min_margin_pct
    maximum_discount_percentage      -> max_discount_pct

ID decision: the decision engine uses str(Product.id), not the SKU, because
every Person 1 route and ExperimentCreate uses the integer `product_pk`. The
frontend can pass a plan's product_id straight to /products/{pk}/... and
/experiments with int(...).

Qloo is reached only through entity_resolution_service (Person 1). This module
never calls the Qloo HTTP API itself and never invents Qloo fields: book
entities have no author field, so related entities carry no creators.
Evidence provenance is kept as raw_ref = "qloo_evidence:{id}", readable via
GET /qloo/evidence/{id}.
"""

from __future__ import annotations

import logging
from datetime import timezone
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product, QlooEntityMapping, QlooEvidence
from app.models import RescuePlan as RescuePlanRow
from app.schemas.experiments import ExperimentCreate
from app.schemas.rescue import EvidenceSource, QlooStatus, RescuePlan, Strategy
from app.services import entity_resolution_service as ers
from app.services.constraints_service import ProductRef
from app.services.matcher_service import QlooRelatedEntity, StockItem
from app.tenant import retailer_id_for

from .workflow import QlooResolution

log = logging.getLogger(__name__)

EVIDENCE_PREFIX = "qloo_evidence:"
MAX_ALTERNATIVES = 5

NOTE_REJECTED = (
    "A person rejected the Qloo match for this product, so no cultural evidence is used. "
    "These options rest on retailer data and commercial rules only."
)
NOTE_CONFIRMED = "Qloo match confirmed by a person."

_TAG_SPLIT = re.compile(r"[,;/|]")


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def product_to_ref(p: Product) -> ProductRef:
    return ProductRef(
        product_id=str(p.id),
        name=p.product_name,
        quantity=p.quantity_in_stock,
        unit_cost=p.unit_cost,
        selling_price=p.selling_price,
        min_margin_pct=p.minimum_acceptable_margin,
        max_discount_pct=p.maximum_discount_percentage,
    )


def split_tags(text: Optional[str]) -> Tuple[str, ...]:
    if not text:
        return ()
    return tuple(t.strip() for t in _TAG_SPLIT.split(text) if t.strip())


def usable_entity_id(m: Optional[QlooEntityMapping]) -> Optional[str]:
    """The mapping's entity id, only if it is strong or human-confirmed and not rejected."""
    if m is None or not m.qloo_entity_id or m.verification_status == "rejected":
        return None
    if m.verification_status == "confirmed" or m.match_status == "strong":
        return m.qloo_entity_id
    return None


def product_to_stock_item(p: Product, mapping: Optional[QlooEntityMapping] = None) -> StockItem:
    creator = (p.creator_or_brand or "").strip()
    return StockItem(
        product=product_to_ref(p),
        creators=(creator,) if creator else (),
        tags=split_tags(p.genre_or_subcategory),
        qloo_entity_id=usable_entity_id(mapping),
    )


def has_sales_history(p: Product) -> bool:
    """True if any sales window was recorded. NULL means unknown; never guessed."""
    return any(v is not None for v in (p.units_sold_30d, p.units_sold_60d, p.units_sold_90d))


def load_target(db: Session, product_pk: int) -> Optional[Product]:
    return db.scalar(select(Product).where(
        Product.id == product_pk, Product.retailer_id == retailer_id_for(db)
    ))


def load_products(db: Session, product_pks: Sequence[int]) -> Dict[int, Product]:
    rows = db.scalars(select(Product).where(Product.id.in_(list(product_pks)), Product.retailer_id == retailer_id_for(db)))
    return {p.id: p for p in rows}


def load_stock(db: Session, retailer_id: str) -> List[StockItem]:
    """All products of one retailer (zero-stock included: they are rejected visibly later)."""
    products = list(db.scalars(
        select(Product).where(Product.retailer_id == retailer_id).order_by(Product.id)
    ))
    pks = [p.id for p in products]
    mappings: Dict[int, QlooEntityMapping] = {}
    if pks:
        for m in db.scalars(select(QlooEntityMapping).where(QlooEntityMapping.product_pk.in_(pks))):
            mappings[m.product_pk] = m
    return [product_to_stock_item(p, mappings.get(p.id)) for p in products]


# ---------------------------------------------------------------------------
# Qloo gateway over Person 1's entity resolution
# ---------------------------------------------------------------------------

def _ref(evidence_id: Optional[int]) -> Optional[str]:
    return f"{EVIDENCE_PREFIX}{evidence_id}" if evidence_id is not None else None


def parse_evidence_ref(raw_ref: Optional[str]) -> Optional[int]:
    if not raw_ref or not raw_ref.startswith(EVIDENCE_PREFIX):
        return None
    try:
        return int(raw_ref[len(EVIDENCE_PREFIX):])
    except ValueError:
        return None


def _alternatives(candidates: Iterable[object]) -> Tuple[str, ...]:
    out: List[str] = []
    for c in candidates or ():
        if not isinstance(c, dict) or not c.get("name"):
            continue
        year = c.get("publication_year")
        out.append(f"{c['name']} ({year})" if year else str(c["name"]))
        if len(out) >= MAX_ALTERNATIVES:
            break
    return tuple(out)


def mapping_to_resolution(m: QlooEntityMapping) -> QlooResolution:
    """Translate Person 1's classification (strong/ambiguous/none + human
    verification) into the pipeline's QlooStatus."""
    raw_ref = _ref(m.evidence_id)
    if m.verification_status == "rejected":
        return QlooResolution(QlooStatus.NO_MATCH, note=NOTE_REJECTED, raw_ref=raw_ref)
    if m.verification_status == "confirmed" and m.qloo_entity_id:
        return QlooResolution(QlooStatus.STRONG_MATCH, m.qloo_entity_id, m.matched_name,
                              NOTE_CONFIRMED, raw_ref=raw_ref)
    if m.match_status == "strong" and m.qloo_entity_id:
        return QlooResolution(QlooStatus.STRONG_MATCH, m.qloo_entity_id, m.matched_name,
                              m.match_reason or None, raw_ref=raw_ref)
    if m.match_status == "ambiguous":
        return QlooResolution(QlooStatus.AMBIGUOUS, None, None, m.match_reason or None,
                              _alternatives(m.candidates), raw_ref)
    return QlooResolution(QlooStatus.NO_MATCH, note=None, raw_ref=raw_ref)


class DbQlooGateway:
    """QlooGateway backed by Person 1's entity_resolution_service.

    resolve() reuses a stored mapping unless refresh=True (so a person's
    confirm/reject choice is respected and Qloo is not called again).
    Any exception rolls back the session and is re-raised; the pipeline then
    records the stage failure and marks Qloo as unavailable.
    """

    def __init__(self, db: Session, *, refresh: bool = False, insights_take: int = 10) -> None:
        self.db = db
        self.refresh = refresh
        self.insights_take = insights_take
        self.evidence_ids: List[int] = []
        self._pk: Optional[int] = None
        self._source_entity_id: Optional[str] = None
        self._source_entity_type: Optional[str] = None

    def _note_evidence(self, evidence_id: Optional[int]) -> None:
        if evidence_id is not None and evidence_id not in self.evidence_ids:
            self.evidence_ids.append(evidence_id)

    def resolve(self, target: StockItem) -> QlooResolution:
        pk = int(target.product.product_id)
        self._pk = pk
        try:
            mapping = None if self.refresh else ers.get_mapping(self.db, pk)
            if mapping is None:
                mapping = ers.resolve_product(self.db, pk, force=False)
        except Exception:
            self.db.rollback()
            raise
        self._note_evidence(mapping.evidence_id)
        self._source_entity_id = mapping.qloo_entity_id
        self._source_entity_type = mapping.qloo_entity_type
        return mapping_to_resolution(mapping)

    def get_insights(self, resolution: QlooResolution) -> Tuple[QlooRelatedEntity, ...]:
        if self._pk is None:
            raise RuntimeError("resolve() must run before get_insights()")
        try:
            evidence_id, result = ers.insights_for_product(self.db, self._pk, take=self.insights_take)
        except Exception:
            self.db.rollback()
            raise
        self._note_evidence(evidence_id)
        ref = _ref(evidence_id)
        out: List[QlooRelatedEntity] = []
        for e in result.entities:
            tags = tuple(
                t["name"].strip() for t in e.tags
                if isinstance(t, dict) and isinstance(t.get("name"), str) and t["name"].strip()
            )
            out.append(QlooRelatedEntity(
                entity_id=e.entity_id,
                name=e.name,
                entity_type=e.types[0] if e.types else None,
                creators=(),  # Qloo book entities carry no author field
                tags=tags,
                raw_ref=ref,
                qloo_affinity=e.affinity,
                source_entity_id=result.source_entity_id or self._source_entity_id,
                source_entity_type=self._source_entity_type,
                evidence_id=evidence_id,
                request_params=dict(result.request_params),
                fetched_at=result.fetched_at,
            ))
        return tuple(out)


# ---------------------------------------------------------------------------
# Plans and experiments (Person 1's tables)
# ---------------------------------------------------------------------------

def _int_ids(values: Iterable[str]) -> List[int]:
    out: List[int] = []
    for v in values:
        try:
            i = int(v)
        except (TypeError, ValueError):
            continue
        if i not in out:
            out.append(i)
    return out


def save_plan(db: Session, plan: RescuePlan, retailer_id: str, evidence_ids: Sequence[int]) -> int:
    """Atomically persist a plan only with products/evidence owned by its retailer."""
    if retailer_id != retailer_id_for(db):
        raise ValueError("Authenticated retailer does not match the plan owner")
    product_ids = _int_ids([plan.product_id] + [p.product_id for s in plan.strategies for p in s.products])
    owned_products = db.scalars(select(Product).where(
        Product.id.in_(product_ids), Product.retailer_id == retailer_id
    )).all()
    if len(owned_products) != len(product_ids):
        raise ValueError("A plan product is missing or belongs to another retailer")

    required_evidence = {
        evidence_id for strategy in plan.strategies
        for evidence_id in strategy_evidence_ids(strategy)
    }
    supplied_evidence = set(int(i) for i in evidence_ids)
    if not required_evidence.issubset(supplied_evidence):
        raise ValueError("Plan references Qloo evidence not included in the save operation")
    if supplied_evidence:
        evidence_rows = db.scalars(select(QlooEvidence).where(
            QlooEvidence.id.in_(supplied_evidence),
            QlooEvidence.product_pk == int(plan.product_id),
        )).all()
        if len(evidence_rows) != len(supplied_evidence):
            raise ValueError("Plan evidence is missing or does not belong to its target product")
        evidence_by_id = {e.id: e for e in evidence_rows}
        for strategy in plan.strategies:
            for claim in strategy.evidence:
                if claim.source != EvidenceSource.QLOO:
                    continue
                source_row = evidence_by_id.get(claim.evidence_id)
                if source_row is None:
                    raise ValueError("Qloo claim references evidence not owned by this target")
                if source_row.kind != "insights":
                    raise ValueError("Qloo strategy evidence must reference a stored Insights response")
                if source_row.request_params != claim.request_params:
                    raise ValueError("Qloo claim request parameters do not match the stored evidence")
                if source_row.request_params.get("signal.interests.entities") != claim.source_entity_id:
                    raise ValueError("Qloo claim source entity does not match the stored request")
                if claim.fetched_at is not None and source_row.fetched_at is not None:
                    claim_time = claim.fetched_at
                    stored_time = source_row.fetched_at
                    if claim_time.tzinfo is None:
                        claim_time = claim_time.replace(tzinfo=timezone.utc)
                    if stored_time.tzinfo is None:
                        stored_time = stored_time.replace(tzinfo=timezone.utc)
                    if abs((claim_time - stored_time).total_seconds()) > 1:
                        raise ValueError("Qloo claim fetch timestamp does not match its stored evidence")
                raw = source_row.response_json if isinstance(source_row.response_json, dict) else {}
                results = raw.get("results", {})
                returned_entities = results.get("entities", []) if isinstance(results, dict) else results
                returned_ids = {
                    str(item.get("entity_id") or item.get("id"))
                    for item in (returned_entities if isinstance(returned_entities, list) else [])
                    if isinstance(item, dict) and (item.get("entity_id") or item.get("id"))
                }
                if claim.entity_id not in returned_ids:
                    raise ValueError("Qloo destination entity is absent from the stored provider response")

    row = RescuePlanRow(
        retailer_id=retailer_id, product_ids=product_ids, status="draft",
        generated_at=plan.generated_at, evidence_ids=sorted(supplied_evidence),
        constraints_snapshot=plan.constraints_snapshot,
        ranking_rationale={str(s.rank): s.rank_reason.model_dump(mode="json") for s in plan.strategies},
        plan_json=plan.model_dump(mode="json"),
    )
    db.add(row)
    db.flush()
    db.commit()
    db.refresh(row)
    return row.id


def load_plan(db: Session, plan_id: int) -> Optional[Tuple[RescuePlanRow, RescuePlan]]:
    row = db.scalar(select(RescuePlanRow).where(RescuePlanRow.id == plan_id, RescuePlanRow.retailer_id == retailer_id_for(db)))
    if row is None or not row.plan_json:
        return None
    return row, RescuePlan.model_validate(row.plan_json)


def strategy_evidence_ids(strategy: Strategy) -> List[int]:
    ids: List[int] = []
    for e in strategy.evidence:
        if e.source == EvidenceSource.QLOO:
            i = e.evidence_id
            if i is None or parse_evidence_ref(e.raw_ref) != i:
                raise ValueError("Qloo evidence ID and raw reference are inconsistent")
            if i not in ids:
                ids.append(i)
    return ids


def strategy_to_experiment_create(plan: RescuePlan, rank: int, plan_id: Optional[int]) -> ExperimentCreate:
    """Turn one ranked strategy into Person 1's ExperimentCreate (status 'proposed').
    Raises KeyError for an unknown rank, ValueError for non-integer product ids."""
    strategy = next((s for s in plan.strategies if s.rank == rank), None)
    if strategy is None:
        raise KeyError(f"plan has no strategy ranked {rank}")
    eco = strategy.economics
    return ExperimentCreate(
        plan_id=plan_id,
        product_pk=int(plan.product_id),
        strategy_type=strategy.type.value,
        title=strategy.name[:200],
        proposed_action=f"{strategy.summary} Test plan: {strategy.test_plan}",
        bundle_product_pks=[int(p.product_id) for p in strategy.products if p.role == "partner"],
        proposed_price=eco.selling_price,
        estimated_cost=eco.estimated_experiment_cost,
        calculated_margin_pct=eco.margin_pct,
        qloo_evidence_ids=strategy_evidence_ids(strategy),
    )
