"""Test setup. These tests use MOCKED Qloo responses (isolated unit tests only).
Nothing here is shown in the demo; the demo uses the real Qloo API."""
import os

os.environ["DATABASE_URL"] = "sqlite://"      # in-memory DB
os.environ["QLOO_API_KEY"] = "test-key"       # fake key; httpx.get is mocked below

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


def entity(eid, name, **props):
    return {"entity_id": eid, "name": name, "types": ["urn:entity:book"], "properties": props}


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
    with TestClient(app) as c:
        yield c


def make_product(name="The God of Small Things", creator="Arundhati Roy", qty=24) -> int:
    with SessionLocal() as db:
        p = Product(sku="B001", product_name=name, creator_or_brand=creator,
                    quantity_in_stock=qty, unit_cost=350.0, selling_price=499.0)
        db.add(p)
        db.commit()
        return p.id
