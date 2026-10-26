import httpx
import pytest

from app.schemas.qloo import MatchStatus
from app.services import qloo_service
from app.services.qloo_service import QlooError
from app.tests.conftest import FakeResponse, entity, insights_payload, search_payload


def test_strong_match_exact_name(fake):
    fake.push("/search", FakeResponse(200, search_payload(entity("A1", "1984"), entity("A2", "Animal Farm"))))
    r = qloo_service.resolve("1984")
    assert r.status == MatchStatus.STRONG and r.chosen.entity_id == "A1"
    assert r.raw is not None and r.request_params["types"] == "urn:entity:book"


def test_ambiguous_same_name(fake):
    fake.push("/search", FakeResponse(200, search_payload(
        entity("X1", "Dune", author="Frank Herbert"), entity("X2", "Dune", author="Someone Else"))))
    r = qloo_service.resolve("Dune")
    assert r.status == MatchStatus.AMBIGUOUS and r.chosen is None and len(r.candidates) == 2


def test_creator_disambiguates(fake):
    fake.push("/search", FakeResponse(200, search_payload(
        entity("X1", "Dune", author="Frank Herbert"), entity("X2", "Dune", author="Someone Else"))))
    r = qloo_service.resolve("Dune", creator="Frank Herbert")
    assert r.status == MatchStatus.STRONG and r.chosen.entity_id == "X1"


def test_no_match_empty_results(fake):
    fake.push("/search", FakeResponse(200, search_payload()))
    r = qloo_service.resolve("Totally Unknown Title 123")
    assert r.status == MatchStatus.NONE and r.chosen is None


def test_no_match_on_404(fake):
    fake.push("/search", FakeResponse(404, {"message": "No results"}))
    assert qloo_service.resolve("zzz").status == MatchStatus.NONE


def test_timeout_retries_then_raises(fake):
    t = httpx.TimeoutException("slow")
    fake.push("/search", t, t, t)
    with pytest.raises(QlooError) as e:
        qloo_service.resolve("1984")
    assert e.value.kind == "timeout" and len(fake.calls) == 3


def test_auth_error_fails_fast(fake):
    fake.push("/search", FakeResponse(401, {}))
    with pytest.raises(QlooError) as e:
        qloo_service.resolve("1984")
    assert e.value.kind == "auth" and len(fake.calls) == 1


def test_rate_limit_then_success(fake):
    fake.push("/search", FakeResponse(429, {}, {"Retry-After": "1"}),
              FakeResponse(200, search_payload(entity("A1", "1984"))))
    assert qloo_service.resolve("1984").status == MatchStatus.STRONG
    assert len(fake.calls) == 2


def test_not_configured(fake, monkeypatch):
    monkeypatch.setattr(qloo_service.settings, "qloo_api_key", "")
    with pytest.raises(QlooError) as e:
        qloo_service.resolve("1984")
    assert e.value.kind == "not_configured" and fake.calls == []


def test_cache_hit_makes_one_call(fake):
    fake.push("/search", FakeResponse(200, search_payload(entity("A1", "1984"))))
    first = qloo_service.resolve("1984")
    second = qloo_service.resolve("1984")
    assert first.from_cache is False and second.from_cache is True and len(fake.calls) == 1


def test_key_sent_only_as_header(fake):
    fake.push("/search", FakeResponse(200, search_payload(entity("A1", "1984"))))
    qloo_service.resolve("1984")
    path, params, headers = fake.calls[0]
    assert headers == {"X-Api-Key": "test-key"} and "test-key" not in str(params)


def test_insights_parses_affinity_and_never_invents_it(fake):
    fake.push("/v2/insights", FakeResponse(200, insights_payload(
        {"entity_id": "B1", "name": "Animal Farm", "query": {"affinity": 0.87}},
        {"entity_id": "B2", "name": "Brave New World"})))
    r = qloo_service.get_insights("A1", exclude_entity_ids=["A1"])
    assert [e.affinity for e in r.entities] == [0.87, None]
    assert r.request_params["signal.interests.entities"] == "A1"
    assert r.request_params["filter.exclude.entities"] == "A1"


def test_insights_empty_is_empty_list(fake):
    fake.push("/v2/insights", FakeResponse(200, insights_payload()))
    assert qloo_service.get_insights("A1").entities == []
