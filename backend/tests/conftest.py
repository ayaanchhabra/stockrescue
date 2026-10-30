"""Shared setup for the decision-engine tests (Person 2).

These two variables are set BEFORE any `app` import, with plain assignment (not
setdefault), so a developer's real .env or shell can never point these tests at
a real database or a real Qloo key. They are the same values Person 1's
app/tests/conftest.py uses, so both suites agree on one in-memory database.

Everything below uses illustrative data (NOT real Qloo data).
"""

import os
import hashlib
import json

os.environ["DATABASE_URL"] = "sqlite://"   # one shared in-memory DB (StaticPool)
os.environ["QLOO_API_KEY"] = "test-key"
# Deterministic test-only credentials; never used outside these isolated tests.
TEST_RETAILER_TOKEN = "test-retailer-token-32-characters-minimum"
OTHER_RETAILER_TOKEN = "other-retailer-token-32-characters-min"
os.environ["RETAILER_API_TOKEN_HASHES"] = json.dumps({
    hashlib.sha256(TEST_RETAILER_TOKEN.encode()).hexdigest(): "demo",
    hashlib.sha256(OTHER_RETAILER_TOKEN.encode()).hexdigest(): "other",
})    # fake key; the network is disabled below

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Safety net: any real Qloo HTTP call from a P2 test fails loudly."""
    try:
        from app.services import qloo_service
    except Exception:  # noqa: BLE001 - pure-Python tests still run without the app deps
        yield
        return

    def _blocked(*args, **kwargs):
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr(qloo_service.httpx, "get", _blocked)
    qloo_service.clear_cache()
    yield


@pytest.fixture
def db():
    """A fresh schema in the shared in-memory DB, and a session on it."""
    from app import models  # noqa: F401  (registers tables)
    from app.db.session import Base, SessionLocal, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
