from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import Request

from app.config import settings

_url = settings.sqlalchemy_url
_kwargs: dict = {"pool_pre_ping": True}
if _url.startswith("sqlite"):
    _kwargs["connect_args"] = {"check_same_thread": False}
    if _url in ("sqlite://", "sqlite:///:memory:"):
        _kwargs["poolclass"] = StaticPool  # one shared in-memory DB (used by tests)

engine = create_engine(_url, **_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db(request: Request):
    db = SessionLocal()
    # HTTP requests receive their tenant exclusively from the auth middleware.
    retailer_id = getattr(request.state, "retailer_id", None)
    if retailer_id:
        db.info["retailer_id"] = retailer_id
    try:
        yield db
    finally:
        db.close()
