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
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product, QlooEntityMapping
from app.models import RescuePlan as RescuePlanRow
from app.schemas.experiments import ExperimentCreate
from app.schemas.rescue import EvidenceSource, QlooStatus, RescuePlan, Strategy
from app.services import entity_resolution_service as ers
from app.services.qloo_service import QlooError
from app.services.constraints_service import ProductRef
from app.services.matcher_service import QlooRelatedEntity, StockItem

from .workflow import QlooResolution

log = logging.getLogger(__name__)

EVIDENCE_PREFIX = "qloo_evidence:"
MAX_ALTERNATIVES = 5
# Keep each rescue run bounded while genuinely exploring beyond books.
CROSS_CATEGORY_INSIGHT_TYPES = (
    "urn:entity:book",
    "urn:entity:movie",
    "urn:entity:artist",
    "urn:entity:tv_show",
    "urn:entity:videogame",
)
HUMAN_DECISIONS = ("confirmed", "rejected")  # verification_status values set by a person

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
    return db.get(Product, product_pk)


def load_products(db: Session, product_pks: Sequence[int]) -> Dict[int, Product]:
    rows = db.scalars(select(Product).where(Product.id.in_(list(product_pks))))
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

    resolve() reuses a stored mapping, so Qloo is not called again. refresh=True
    re-resolves only mappings nobody has judged (unverified or missing). A
    mapping a person CONFIRMED or REJECTED is always kept as it is: refresh must
    never undo a human decision (entity_resolution_service.resolve_product would
    reset a rejected mapping to "unverified"). To change a human decision, use
    the confirm/reject/resolve endpoints.
    Any exception rolls back the session and is re-raised; the pipeline then
    records the stage failure and marks Qloo as unavailable.
    """

    def __init__(self, db: Session, *, refresh: bool = False, insights_take: int = 10,
                 insight_target_types: Sequence[str] = CROSS_CATEGORY_INSIGHT_TYPES) -> None:
        self.db = db
        self.refresh = refresh
        self.insights_take = insights_take
        self.insight_target_types = tuple(dict.fromkeys(insight_target_types))
        if not self.insight_target_types or len(self.insight_target_types) > 7:
            raise ValueError("insight_target_types must contain between 1 and 7 categories")
        self.evidence_ids: List[int] = []
        self.category_failures: Dict[str, str] = {}
        self._pk: Optional[int] = None

    def _note_evidence(self, evidence_id: Optional[int]) -> None:
        if evidence_id is not None and evidence_id not in self.evidence_ids:
            self.evidence_ids.append(evidence_id)

    def resolve(self, target: StockItem) -> QlooResolution:
        pk = int(target.product.product_id)
        self._pk = pk
        try:
            mapping = ers.get_mapping(self.db, pk)
            judged = mapping is not None and mapping.verification_status in HUMAN_DECISIONS
            if mapping is None or (self.refresh and not judged):
                mapping = ers.resolve_product(self.db, pk, force=False)
        except Exception:
            self.db.rollback()
            raise
        self._note_evidence(mapping.evidence_id)
        return mapping_to_resolution(mapping)

    def get_insights(self, resolution: QlooResolution) -> Tuple[QlooRelatedEntity, ...]:
        if self._pk is None:
            raise RuntimeError("resolve() must run before get_insights()")
        out: List[QlooRelatedEntity] = []
        successes = 0
        for target_type in self.insight_target_types:
            try:
                evidence_id, result = ers.insights_for_product(
                    self.db, self._pk, take=self.insights_take, target_type=target_type
                )
            except Exception as exc:
                # A missing category/temporary provider error must not discard
                # successful evidence from the other supported categories.
                self.db.rollback()
                self.category_failures[target_type] = f"{type(exc).__name__}: {str(exc)[:160]}"
                log.warning("Qloo Insights category %s failed: %s", target_type, type(exc).__name__)
                continue
            successes += 1
            self._note_evidence(evidence_id)
            ref = _ref(evidence_id)
            for e in result.entities:
                tags = tuple(
                    t["name"].strip() for t in e.tags
                    if isinstance(t, dict) and isinstance(t.get("name"), str) and t["name"].strip()
                )
                out.append(QlooRelatedEntity(
                    entity_id=e.entity_id,
                    name=e.name,
                    entity_type=e.types[0] if e.types else target_type,
                    creators=(),  # Qloo book entities do not reliably carry creator fields
                    tags=tags,
                    raw_ref=ref,
                    affinity=e.affinity,
                ))
        if successes == 0 and self.category_failures:
            raise QlooError("Qloo Insights failed for every configured target category", kind="upstream")
        # Deduplicate provider entity IDs while retaining first-seen category order.
        unique: Dict[str, QlooRelatedEntity] = {}
        for entity in out:
            unique.setdefault(entity.entity_id, entity)
        return tuple(unique.values())



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
    """Store the plan in Person 1's rescue_plans table and return its id."""
    product_ids = _int_ids([plan.product_id] + [p.product_id for s in plan.strategies for p in s.products])
    row = RescuePlanRow(
        retailer_id=retailer_id,
        product_ids=product_ids,
        status="draft",
        generated_at=plan.generated_at,
        evidence_ids=list(evidence_ids),
        constraints_snapshot=plan.constraints_snapshot,
        ranking_rationale={str(s.rank): s.rank_reason.model_dump(mode="json") for s in plan.strategies},
        plan_json=plan.model_dump(mode="json"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def load_plan(db: Session, plan_id: int) -> Optional[Tuple[RescuePlanRow, RescuePlan]]:
    row = db.get(RescuePlanRow, plan_id)
    if row is None or not row.plan_json:
        return None
    return row, RescuePlan.model_validate(row.plan_json)


def strategy_evidence_ids(strategy: Strategy) -> List[int]:
    ids: List[int] = []
    for e in strategy.evidence:
        if e.source == EvidenceSource.QLOO:
            i = parse_evidence_ref(e.raw_ref)
            if i is not None and i not in ids:
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
