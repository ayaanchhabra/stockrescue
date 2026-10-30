"""Glue between the Qloo client and the database: resolve, confirm, insights + provenance."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import InvalidTransition, NeedsResolution, NotFound
from app.models import Product, QlooEntityMapping, QlooEvidence
from app.schemas.qloo import InsightsResult, MatchStatus
from app.services import qloo_service


def _product(db: Session, product_pk: int) -> Product:
    p = db.get(Product, product_pk)
    if not p:
        raise NotFound(f"Product {product_pk} not found")
    return p


def get_mapping(db: Session, product_pk: int) -> QlooEntityMapping | None:
    return db.scalar(select(QlooEntityMapping).where(QlooEntityMapping.product_pk == product_pk))


def resolve_product(db: Session, product_pk: int, force: bool = False) -> QlooEntityMapping:
    """Resolve a product to a Qloo entity and store the raw evidence.
    A mapping judged by a person is final, even when force=True. The force
    flag only refreshes mappings that remain unverified."""
    product = _product(db, product_pk)
    existing = get_mapping(db, product_pk)
    if existing and existing.verification_status in ("confirmed", "rejected"):
        return existing

    result = qloo_service.resolve(product.product_name, creator=product.creator_or_brand)
    ev = QlooEvidence(product_pk=product_pk, kind="resolve", request_path=result.endpoint,
                      request_params=result.request_params, response_json=result.raw,
                      from_cache=result.from_cache)
    db.add(ev)
    db.flush()

    m = existing or QlooEntityMapping(product_pk=product_pk, match_status="none")
    chosen = result.chosen
    m.qloo_entity_id = chosen.entity_id if chosen else None
    m.qloo_entity_type = (chosen.types[0] if chosen and chosen.types else None)
    m.matched_name = chosen.name if chosen else None
    m.match_status = result.status.value
    m.match_reason = result.reason
    m.verification_status = "unverified"
    m.candidates = [c.model_dump() for c in result.candidates]
    m.evidence_id = ev.id
    m.last_checked_at = datetime.now(timezone.utc)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def confirm_mapping(db: Session, product_pk: int, entity_id: str) -> QlooEntityMapping:
    """A human picks one of the stored candidates (ambiguous case) or confirms the strong match."""
    _product(db, product_pk)
    m = get_mapping(db, product_pk)
    if not m:
        raise NotFound("Resolve this product first")
    if m.verification_status in ("confirmed", "rejected"):
        if m.verification_status == "confirmed" and m.qloo_entity_id == entity_id:
            return m  # repeated submission of the same human decision is idempotent
        raise InvalidTransition(
            "A person's Qloo match decision is final; this mapping cannot be changed."
        )
    cand = next((c for c in m.candidates if c.get("entity_id") == entity_id), None)
    if not cand:
        raise NotFound(f"Entity {entity_id} is not among the stored candidates")
    m.qloo_entity_id = cand["entity_id"]
    m.matched_name = cand.get("name")
    types = cand.get("types") or []
    m.qloo_entity_type = types[0] if types else None
    m.verification_status = "confirmed"
    db.commit()
    db.refresh(m)
    return m


def reject_mapping(db: Session, product_pk: int) -> QlooEntityMapping:
    m = get_mapping(db, product_pk)
    if not m:
        raise NotFound("Resolve this product first")
    if m.verification_status == "rejected":
        return m  # repeated submission of the same human decision is idempotent
    if m.verification_status == "confirmed":
        raise InvalidTransition(
            "A person's Qloo match decision is final; this mapping cannot be changed."
        )
    m.verification_status = "rejected"
    db.commit()
    db.refresh(m)
    return m


def insights_for_product(db: Session, product_pk: int, take: int = 10,
                         target_type: str = qloo_service.BOOK) -> tuple[int, InsightsResult]:
    """Returns (evidence_id, result) for one allowlisted Qloo category."""
    if isinstance(take, bool) or not isinstance(take, int) or not 1 <= take <= 30:
        raise ValueError("take must be an integer between 1 and 30")
    _product(db, product_pk)
    m = get_mapping(db, product_pk)
    usable = (m is not None and m.qloo_entity_id is not None and m.verification_status != "rejected"
              and (m.verification_status == "confirmed" or m.match_status == MatchStatus.STRONG.value))
    if not usable:
        raise NeedsResolution("No usable Qloo entity for this product: resolve it and confirm a match first")

    # Request a few extra because book queries can return alternate editions.
    result = qloo_service.get_insights(m.qloo_entity_id, target_type=target_type, take=min(take + 3, 30),
                                       exclude_entity_ids=[m.qloo_entity_id])
    same_title = qloo_service.norm_title(m.matched_name or "")
    kept = [e for e in result.entities if qloo_service.norm_title(e.name) != same_title]
    result = result.model_copy(update={
        "entities": kept[:take],
        "filtered_same_title_count": len(result.entities) - len(kept),
    })
    ev = QlooEvidence(product_pk=product_pk, kind="insights", request_path=result.endpoint,
                      request_params=result.request_params, response_json=result.raw,
                      from_cache=result.from_cache)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev.id, result


def get_evidence(db: Session, evidence_id: int) -> QlooEvidence:
    ev = db.get(QlooEvidence, evidence_id)
    if not ev:
        raise NotFound(f"Evidence {evidence_id} not found")
    return ev
