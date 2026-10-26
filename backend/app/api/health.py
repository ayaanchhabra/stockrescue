from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok", "qloo_key_configured": bool(settings.qloo_api_key)}
