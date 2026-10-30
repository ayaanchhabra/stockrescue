"""Security, bearer auth, and tenant isolation integration tests."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import SessionLocal
from app.main import app
from app.models import ExperimentStockReservation, Product, QlooEntityMapping, QlooEvidence
from app.services import qloo_service
from app.tests.conftest import OTHER_RETAILER_TOKEN, TEST_RETAILER_TOKEN, make_product, FakeResponse, search_payload, entity
from app.security import rate_limiter


def test_health_is_public_but_api_requires_bearer_token():
    with TestClient(app) as anonymous:
        assert anonymous.get("/health").status_code == 200
        denied = anonymous.get("/inventory/dashboard")
        assert denied.status_code == 401
        assert denied.json()["error"] == "unauthorized"


def test_unknown_token_is_rejected():
    with TestClient(app, headers={"Authorization": "Bearer totally-invalid-token-000000000000"}) as c:
        response = c.get("/inventory/dashboard")
    assert response.status_code == 401


def test_retailer_scoping_hides_products_evidence_and_experiments(client, other_client):
    demo_pk = make_product(sku="TENANT-DEMO", name="Demo Tenant Book")
    other_pk = make_product(sku="TENANT-OTHER", name="Other Tenant Book", retailer_id="other")
    with SessionLocal() as db:
        demo_evidence = QlooEvidence(
            product_pk=demo_pk, kind="resolve", request_path="/search",
            request_params={"query": "Demo Tenant Book"}, response_json={"results": []},
            from_cache=False,
        )
        demo_mapping = QlooEntityMapping(
            product_pk=demo_pk, qloo_entity_id=None, match_status="none",
            match_reason="no match", verification_status="unverified", candidates=[],
            evidence_id=None,
        )
        db.add_all([demo_evidence, demo_mapping])
        db.commit()
        evidence_id = demo_evidence.id
        mapping_id = demo_mapping.id

    assert client.get("/inventory/dashboard").json()["total_products"] == 1
    assert other_client.get("/inventory/dashboard").json()["total_products"] == 1
    assert other_client.get(f"/products/{demo_pk}/qloo/mapping").status_code == 404
    assert client.get(f"/products/{other_pk}/qloo/mapping").status_code == 404
    assert other_client.get(f"/qloo/evidence/{evidence_id}").status_code == 404
    assert client.get(f"/qloo/evidence/{evidence_id}").status_code == 200

    exp = client.post("/experiments", json={
        "product_pk": demo_pk, "strategy_type": "reposition", "title": "Demo plan",
        "proposed_action": "Reposition", "proposed_price": 499,
        "estimated_cost": 0, "calculated_margin_pct": 29.9,
    })
    assert exp.status_code == 201, exp.text
    assert other_client.get(f"/experiments/{exp.json()['id']}").status_code == 404
    assert other_client.post("/experiments", json={
        "product_pk": demo_pk, "strategy_type": "reposition", "title": "Cross tenant",
        "proposed_action": "No", "proposed_price": 499,
    }).status_code == 404


def test_expensive_qloo_endpoint_is_rate_limited(client, fake, monkeypatch):
    rate_limiter.clear()
    monkeypatch.setattr(qloo_service.settings, "qloo_requests_per_minute", 1)
    fake.push("/search", FakeResponse(200, search_payload(entity("Q1", "1984"))))
    first = client.get("/qloo/status")
    second = client.get("/qloo/status")
    assert first.status_code == 200 and first.json()["ok"] is True
    assert second.status_code == 429 and second.json()["error"] == "rate_limited"
    assert second.headers.get("retry-after") == "60"
    rate_limiter.clear()


def test_mapping_final_human_decision_survives_refresh_and_opposite_action(client, fake):
    from app.errors import InvalidTransition
    from app.services import entity_resolution_service as ers
    from app.tests.conftest import FakeResponse, entity, search_payload

    pk = make_product(name="Dune", creator=None, sku="DUNE-REVIEW")
    fake.push("/search", FakeResponse(200, search_payload(entity("D1", "Dune"), entity("D2", "Dune"))))
    mapping = client.post(f"/products/{pk}/qloo/resolve").json()
    assert mapping["match_status"] == "ambiguous"
    assert client.post(f"/products/{pk}/qloo/confirm", json={"entity_id": "D1"}).json()["verification_status"] == "confirmed"
    # A forced refresh does not call Qloo and cannot switch the human decision.
    refreshed = client.post(f"/products/{pk}/qloo/resolve?force=true").json()
    assert refreshed["verification_status"] == "confirmed" and refreshed["qloo_entity_id"] == "D1"
    assert client.post(f"/products/{pk}/qloo/reject").status_code == 409



def test_auth_configuration_fails_closed(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "retailer_api_token_hashes", "{}")
    with TestClient(app) as anonymous:
        response = anonymous.get("/inventory/dashboard")
    assert response.status_code == 503
    assert response.json()["error"] == "auth_not_configured"
