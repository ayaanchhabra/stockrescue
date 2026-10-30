"""Test setup. These tests use MOCKED Qloo responses (isolated unit tests only).
Nothing here is shown in the demo; the demo uses the real Qloo API."""
import os
import hashlib
import json

os.environ["DATABASE_URL"] = "sqlite://"      # in-memory DB
os.environ["QLOO_API_KEY"] = "test-key"
# Deterministic test-only credentials; never used outside these isolated tests.
TEST_RETAILER_TOKEN = "test-retailer-token-32-characters-minimum"
OTHER_RETAILER_TOKEN = "other-retailer-token-32-characters-min"
os.environ["RETAILER_API_TOKEN_HASHES"] = json.dumps({
    hashlib.sha256(TEST_RETAILER_TOKEN.encode()).hexdigest(): "demo",
    hashlib.sha256(OTHER_RETAILER_TOKEN.encode()).hexdigest(): "other",
})       # fake key; httpx.get is mocked below

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Product  # noqa: E402
from app.services import qloo_service  # noqa: E402


class FakeResponse:
    def __init__(self, status: int = 200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeQloo:
    """Queue of canned responses per path. An Exception in the queue is raised."""

    def __init__(self):
        self.queue: dict[str, list] = {"/search": [], "/v2/insights": []}
        self.calls: list[tuple] = []

    def push(self, path: str, *items):
        self.queue[path].extend(items)

    def __call__(self, url, params=None, headers=None, timeout=None):
        path = url.replace(qloo_service.settings.qloo_base_url, "")
        self.calls.append((path, params, headers))
        item = self.queue[path].pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def entity(eid, name, ratings=None, popularity=None, year=None, **props):
    """Shaped like a real Qloo /search result (see qloo_inspect.py output)."""
    p = dict(props)
    if ratings is not None:
        p["external"] = {"goodreads": {"user_ratings_count": ratings}}
    if year is not None:
        p["publication_year"] = year
    item = {"entity_id": eid, "name": name, "types": ["urn:entity:book"], "properties": p}
    if popularity is not None:
        item["popularity"] = popularity
    return item


def search_payload(*entities):
    return {"results": list(entities)}


def insights_payload(*entities):
    return {"results": {"entities": list(entities)}}


@pytest.fixture(autouse=True)
def fresh_state():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    qloo_service.clear_cache()
    yield


@pytest.fixture
def fake(monkeypatch):
    f = FakeQloo()
    monkeypatch.setattr(qloo_service.httpx, "get", f)
    monkeypatch.setattr(qloo_service.time, "sleep", lambda s: None)
    return f


@pytest.fixture
def client():
    with TestClient(app, headers={"Authorization": f"Bearer {TEST_RETAILER_TOKEN}"}) as c:
        yield c


@pytest.fixture
def other_client():
    with TestClient(app, headers={"Authorization": f"Bearer {OTHER_RETAILER_TOKEN}"}) as c:
        yield c


def make_product(name="The God of Small Things", creator="Arundhati Roy", qty=24, sku="B001", retailer_id="demo") -> int:
    with SessionLocal() as db:
        p = Product(sku=sku, retailer_id=retailer_id, product_name=name, creator_or_brand=creator,
                    quantity_in_stock=qty, unit_cost=350.0, selling_price=499.0)
        db.add(p)
        db.commit()
        return p.id
