from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.errors import NotFound
from app.schemas.qloo import (ConfirmIn, InsightsIn, InsightsOut, MappingOut, MatchStatus)
from app.services import entity_resolution_service as ers
from app.services import qloo_service
from app.services.qloo_service import QlooError

router = APIRouter(tags=["qloo"])


def _mapping_out(m) -> MappingOut:
    out = MappingOut.model_validate(m)
    out.coverage_gap = (m.match_status == MatchStatus.NONE.value) or m.verification_status == "rejected"
    return out


@router.get("/qloo/status")
def qloo_status():
    """Connectivity test: makes one tiny real Qloo search. Never fakes success."""
    try:
        cands, _, params, cached = qloo_service.search_entities("1984", take=1)
    except QlooError as e:
        return {"ok": False, "error": e.kind, "message": str(e), "status_code": e.status_code}
    return {"ok": True, "sample_results": len(cands), "from_cache": cached,
            "base_url": qloo_service.settings.qloo_base_url}


@router.get("/qloo/search")
def search(query: str = Query(min_length=1, max_length=200),
           type: str = Query(default=qloo_service.BOOK, pattern=r"^urn:entity:[a-z_]+$"),
           take: int = Query(default=5, ge=1, le=10)):
    """Entity search (real Qloo /search), with our internal name similarity attached."""
    cands, raw, params, cached = qloo_service.search_entities(query, type, take)
    return {"query": query, "candidates": cands, "request_params": params, "from_cache": cached}


@router.post("/products/{product_pk}/qloo/resolve", response_model=MappingOut)
def resolve(product_pk: int, force: bool = False, db: Session = Depends(get_db)):
    return _mapping_out(ers.resolve_product(db, product_pk, force=force))


@router.get("/products/{product_pk}/qloo/mapping", response_model=MappingOut)
def mapping(product_pk: int, db: Session = Depends(get_db)):
    m = ers.get_mapping(db, product_pk)
    if not m:
        raise NotFound("This product has not been resolved yet")
    return _mapping_out(m)


@router.post("/products/{product_pk}/qloo/confirm", response_model=MappingOut)
def confirm(product_pk: int, body: ConfirmIn, db: Session = Depends(get_db)):
    return _mapping_out(ers.confirm_mapping(db, product_pk, body.entity_id))


@router.post("/products/{product_pk}/qloo/reject", response_model=MappingOut)
def reject(product_pk: int, db: Session = Depends(get_db)):
    return _mapping_out(ers.reject_mapping(db, product_pk))


@router.post("/products/{product_pk}/qloo/insights", response_model=InsightsOut)
def insights(product_pk: int, body: InsightsIn | None = None, db: Session = Depends(get_db)):
    evidence_id, result = ers.insights_for_product(db, product_pk, take=(body.take if body else 10))
    return InsightsOut(evidence_id=evidence_id, result=result)
