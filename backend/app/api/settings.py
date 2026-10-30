"""Authenticated retailer settings endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.retailer_settings import RetailerSettingsIn
from app.services.retailer_settings_service import load_decision_settings, save_retailer_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    """Return saved settings or documented MVP defaults for this retailer."""
    return load_decision_settings(db).payload


@router.put("")
def put_settings(body: RetailerSettingsIn, db: Session = Depends(get_db)):
    """Replace the authenticated retailer's complete decision-settings document."""
    return save_retailer_settings(db, body)
