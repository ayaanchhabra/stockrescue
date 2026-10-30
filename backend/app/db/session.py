from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

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


def commit_or_rollback(db):
    """Commit one business operation atomically or reset the failed unit of work."""
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
