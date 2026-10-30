"""Load and persist the single effective decision configuration per retailer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RetailerSettings
from app.schemas.retailer_settings import RetailerSettingsIn
from app.services.inventory_metrics import SlowMovingSettings
from app.services.rescue_config import (
    Constraints, RankingSettings, RankingWeights, StrategySettings,
)
from app.tenant import retailer_id_for


@dataclass(frozen=True)
class DecisionSettings:
    payload: dict[str, Any]
    constraints: Constraints
    strategy: StrategySettings
    ranking: RankingSettings
    slow_moving: SlowMovingSettings


def default_settings_payload() -> dict[str, Any]:
    return RetailerSettingsIn().model_dump(mode="json")


def decision_settings_from_payload(raw: dict[str, Any]) -> DecisionSettings:
    payload = RetailerSettingsIn.model_validate(raw).model_dump(mode="json")
    c = payload["constraints"]
    s = payload["strategy"]
    r = payload["ranking"]
    w = r["weights"]
    m = payload["slow_moving"]
    return DecisionSettings(
        payload=payload,
        constraints=Constraints(
            min_margin_pct=c["min_margin_pct"],
            max_discount_pct=c["max_discount_pct"],
            max_campaign_budget=c["max_campaign_budget"],
            restricted_product_ids=frozenset(c["restricted_product_ids"]),
        ),
        strategy=StrategySettings(**s),
        ranking=RankingSettings(
            weights=RankingWeights(**w),
            discount_last=r["discount_last"],
            headroom_full_pts=r["headroom_full_pts"],
            stock_cover_full_multiple=r["stock_cover_full_multiple"],
            ambiguous_evidence_cap=r["ambiguous_evidence_cap"],
            max_results=r["max_results"],
            close_score_gap=r["close_score_gap"],
        ),
        slow_moving=SlowMovingSettings(**m),
    )


def load_decision_settings(db: Session, retailer_id: str | None = None) -> DecisionSettings:
    tenant = retailer_id or retailer_id_for(db)
    row = db.scalar(select(RetailerSettings).where(RetailerSettings.retailer_id == tenant))
    return decision_settings_from_payload(row.settings_json if row else default_settings_payload())


def save_retailer_settings(db: Session, payload: RetailerSettingsIn, retailer_id: str | None = None) -> dict[str, Any]:
    tenant = retailer_id or retailer_id_for(db)
    normalized = payload.model_dump(mode="json")
    # Reconstruct dataclasses so their cross-field/domain invariants are also enforced.
    decision_settings_from_payload(normalized)
    row = db.scalar(select(RetailerSettings).where(RetailerSettings.retailer_id == tenant))
    if row is None:
        row = RetailerSettings(retailer_id=tenant, settings_json=normalized)
        db.add(row)
    else:
        row.settings_json = normalized
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return normalized
