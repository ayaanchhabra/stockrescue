"""Tenant context helpers shared by API-facing service functions."""
from sqlalchemy.orm import Session


def retailer_id_for(db: Session) -> str:
    # The fallback keeps direct single-tenant unit tests/service calls compatible.
    # Every HTTP database request receives this value from auth middleware.
    return str(db.info.get("retailer_id", "demo"))
