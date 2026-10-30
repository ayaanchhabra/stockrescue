import httpx
import pytest

from app.schemas.qloo import MatchStatus
from app.services import qloo_service
from app.services.qloo_service import QlooError
from app.tests.conftest import FakeResponse, entity, insights_payload, search_payload


def test_exact_title_alone_requires_human_confirmation(fake):
    fake.push("/search", FakeResponse(200, search_payload(entity("A1", "1984"), entity("A2", "Animal Farm"))))
    r = qloo_service.resolve("1984")
    assert r.status == MatchStatus.AMBIGUOUS and r.chosen is None
    assert "human confirmation" in r.reason
    assert r.raw is not None and r.request_params["types"] == "urn:entity:book"


def test_ambiguous_same_name(fake):
    fake.push("/search", FakeResponse(200, search_payload(
        entity("X1", "Dune", author="Frank Herbert"), entity("X2", "Dune", author="Someone Else"))))
    r = qloo_service.resolve("Dune")
    assert r.status == MatchStatus.AMBIGUOUS and r.chosen is None and len(r.candidates) == 2


def test_main_edition_requires_creator_metadata_not_popularity(fake):
    fake.push("/search", FakeResponse(200, search_payload(
        entity("F74B", "The God of Small Things", ratings=312686, popularity=0.997,
               description="A novel by Arundhati Roy"),
        entity("D24F", "The God of Small Things", ratings=46),
        entity("4F22", "Arundhati Roy's The God of Small Things: A Reader's Guide", ratings=363))))
    r = qloo_service.resolve("The God of Small Things", creator="Arundhati Roy")
    assert r.status == MatchStatus.STRONG and r.chosen.entity_id == "F74B"
    assert "creator name appears" in r.reason


def test_two_popular_editions_stay_ambiguous(fake):
    fake.push("/search", FakeResponse(200, search_payload(
        entity("E1", "Dune", ratings=5000), entity("E2", "Dune", ratings=4000))))
    assert qloo_service.resolve("Dune").status == MatchStatus.AMBIGUOUS


def test_subtitle_match_needs_corroborating_metadata(fake):
    fake.push("/search", FakeResponse(200, search_payload(
        entity("S1", "Sapiens: A Brief History of Humankind", ratings=1163646),
        entity("S2", "Sapiens: A Graphic History, Volume 2 - The Pillars of Civilization", ratings=4715),
        entity("S3", "Sapiens and Homo Deus: The E-book Collection", ratings=1282),
        entity("S4", "Simon vs. the Homo Sapiens Agenda (Simonverse, #1)", ratings=457978))))
    r = qloo_service.resolve("Sapiens")
    assert r.status == MatchStatus.AMBIGUOUS and r.chosen is None


def test_creator_metadata_corroborates_identity(fake):
    fake.push("/search", FakeResponse(200, search_payload(
        entity("A1", "1984", description="A novel by George Orwell"))))
    r = qloo_service.resolve("1984", creator="George Orwell")
    assert r.status == MatchStatus.STRONG and "creator name appears" in r.reason


def test_publication_year_corroborates_exact_title_and_conflict_stays_ambiguous(fake):
    fake.push("/search", FakeResponse(200, search_payload(entity("A1", "1984", year=1949))))
    matching = qloo_service.resolve("1984", publication_year=1949)
    assert matching.status == MatchStatus.STRONG and matching.chosen.entity_id == "A1"

    qloo_service.clear_cache()
    fake.push("/search", FakeResponse(200, search_payload(entity("A1", "1984", year=1950))))
    conflict = qloo_service.resolve("1984", publication_year=1949)
    assert conflict.status == MatchStatus.AMBIGUOUS and conflict.chosen is None
    assert "conflicts" in conflict.reason


def test_isbn13_corroborates_only_matching_provider_isbn(fake):
    fake.push("/search", FakeResponse(200, search_payload(
        entity("A1", "1984", isbn13="9780306406157"))))
    matching = qloo_service.resolve("1984", isbn13="978-0-306-40615-7")
    assert matching.status == MatchStatus.STRONG and matching.chosen.entity_id == "A1"

    qloo_service.clear_cache()
    fake.push("/search", FakeResponse(200, search_payload(
        entity("A1", "1984", isbn13="9783161484100"))))
    conflict = qloo_service.resolve("1984", isbn13="9780306406157")
    assert conflict.status == MatchStatus.AMBIGUOUS and conflict.chosen is None


def test_disambiguation_metadata_can_corroborate_creator(fake):
    fake.push("/search", FakeResponse(200, search_payload(
        {"entity_id": "A1", "name": "1984", "types": ["urn:entity:book"],
         "disambiguation": "Novel by George Orwell"})))
    matching = qloo_service.resolve("1984", creator="George Orwell")
    assert matching.status == MatchStatus.STRONG and matching.chosen.entity_id == "A1"


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
              FakeResponse(200, search_payload(
                  entity("A1", "1984", description="A novel by George Orwell"))))
    assert qloo_service.resolve("1984", creator="George Orwell").status == MatchStatus.STRONG
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


def test_insights_real_shape_type_subtype_tags_popularity(fake):
    fake.push("/v2/insights", FakeResponse(200, {"success": True, "results": {"entities": [{
        "name": "Midnight\u2019s Children", "entity_id": "04C3", "type": "urn:entity",
        "subtype": "urn:entity:book", "popularity": 0.99, "query": {"affinity": 0.9699},
        "tags": [{"id": "urn:tag:genre:media:literary_fiction", "name": "Literary Fiction",
                  "type": "urn:tag:genre:media"}],
        "properties": {"publication_year": 1981, "short_description": "Saleem Sinai...",
                       "image": {"url": "https://images.qloo.com/i/x.jpg"}}}]}}))
    e = qloo_service.get_insights("F74B").entities[0]
    assert e.types == ["urn:entity:book"] and e.affinity == 0.9699 and e.popularity == 0.99
    assert e.tags[0]["name"] == "Literary Fiction" and e.publication_year == 1981
    assert e.image_url.startswith("https://")


def test_insights_for_product_drops_other_editions_of_same_book(fake):
    from app.db.session import SessionLocal
    from app.services import entity_resolution_service as ers
    from app.tests.conftest import make_product
    pk = make_product()
    fake.push("/search", FakeResponse(200, search_payload(
        entity("F74B", "The God of Small Things", ratings=312686,
               description="A novel by Arundhati Roy"))))
    with SessionLocal() as db:
        ers.resolve_product(db, pk)
        fake.push("/v2/insights", FakeResponse(200, insights_payload(
            {"entity_id": "OTHER", "name": "The God of Small Things", "query": {"affinity": 0.99}},
            {"entity_id": "B1", "name": "Midnight's Children", "query": {"affinity": 0.97}})))
        _, result = ers.insights_for_product(db, pk, take=5)
    assert [e.name for e in result.entities] == ["Midnight's Children"]
    assert result.filtered_same_title_count == 1
    
def test_html_entities_in_names_are_decoded(fake):
    fake.push("/search", FakeResponse(200, search_payload(
        entity("H1", "Atomic Habits: Build &amp; Break"))))
    result = qloo_service.resolve("Atomic Habits")
    assert result.status == MatchStatus.AMBIGUOUS
    assert result.candidates[0].name == "Atomic Habits: Build & Break"
