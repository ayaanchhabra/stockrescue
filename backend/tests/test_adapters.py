"""Tests for the adapters onto Person 1's code (app.agent.adapters).

Products and mappings are illustrative rows in an in-memory DB. Person 1's
entity_resolution_service functions are replaced by TEST DOUBLES with
monkeypatch, so nothing reaches Qloo. Entity ids and names are illustrative
(NOT real Qloo data).
"""

import pytest

from app.agent import adapters
from app.agent.adapters import (
    NOTE_CONFIRMED,
    NOTE_REJECTED,
    DbQlooGateway,
    has_sales_history,
    load_plan,
    load_stock,
    mapping_to_resolution,
    parse_evidence_ref,
    product_to_ref,
    product_to_stock_item,
    save_plan,
    split_tags,
    strategy_to_experiment_create,
)
from app.agent.workflow import RescueRequest, run_rescue
from app.models import Product, QlooEntityMapping
from app.schemas.qloo import InsightEntity, InsightsResult
from app.schemas.rescue import EvidenceSource, QlooStatus, RescuePlan
from app.services.qloo_service import QlooError
from app.services.rescue_config import Constraints

from p2_helpers import add_mapping, add_product


def insights(*entities, evidence_id=41):
    """TEST DOUBLE result shaped like Person 1's InsightsResult."""
    return evidence_id, InsightsResult(
        source_entity_id="ent-target", target_type="urn:entity:book", request_params={},
        entities=list(entities), fetched_at="2026-10-27T00:00:00+00:00",
    )


# --- inventory mapping -----------------------------------------------------

def test_naming_map_builds_product_ref(db):
    pk = add_product(db, "SKU1", "A Book", qty=7, cost=120, price=300,
                     minimum_acceptable_margin=30, maximum_discount_percentage=10)
    ref = product_to_ref(db.get(Product, pk))
    assert ref.product_id == str(pk)
    assert (ref.name, ref.quantity, ref.unit_cost, ref.selling_price) == ("A Book", 7, 120, 300)
    assert (ref.min_margin_pct, ref.max_discount_pct) == (30, 10)


def test_blank_per_product_limits_stay_none(db):
    pk = add_product(db, "SKU1", "A Book")
    ref = product_to_ref(db.get(Product, pk))
    assert ref.min_margin_pct is None and ref.max_discount_pct is None


@pytest.mark.parametrize("text,expected", [
    (None, ()),
    ("", ()),
    ("Literary Fiction", ("Literary Fiction",)),
    ("Satire, War ; Classic/ Humour | ", ("Satire", "War", "Classic", "Humour")),
])
def test_split_tags(text, expected):
    assert split_tags(text) == expected


def test_stock_item_uses_creator_tags_and_only_usable_mapping(db):
    pk = add_product(db, "SKU1", "A Book", creator_or_brand=" Some Author ", genre_or_subcategory="Satire")
    p = db.get(Product, pk)
    strong = add_mapping(db, pk, status="strong", entity_id="ent-1")
    item = product_to_stock_item(p, strong)
    assert item.creators == ("Some Author",) and item.tags == ("Satire",)
    assert item.qloo_entity_id == "ent-1"


@pytest.mark.parametrize("status,verification,entity,expected", [
    ("strong", "unverified", "e1", "e1"),
    ("ambiguous", "confirmed", "e1", "e1"),
    ("ambiguous", "unverified", None, None),
    ("strong", "rejected", "e1", None),
    ("none", "unverified", None, None),
])
def test_usable_entity_id(status, verification, entity, expected):
    m = QlooEntityMapping(product_pk=1, qloo_entity_id=entity, match_status=status,
                          verification_status=verification)
    assert adapters.usable_entity_id(m) == expected


def test_has_sales_history(db):
    none_pk = add_product(db, "S1", "No history")
    zero_pk = add_product(db, "S2", "Zero sales", units_sold_30d=0)
    assert has_sales_history(db.get(Product, none_pk)) is False
    assert has_sales_history(db.get(Product, zero_pk)) is True  # a recorded 0 is history


def test_load_stock_is_per_retailer_and_includes_zero_stock(db):
    a = add_product(db, "S1", "Mine", qty=0)
    add_product(db, "S2", "Other shop", retailer_id="other")
    add_mapping(db, a, status="strong", entity_id="ent-a")
    stock = load_stock(db, "demo")
    assert [s.product.product_id for s in stock] == [str(a)]
    assert stock[0].product.quantity == 0 and stock[0].qloo_entity_id == "ent-a"


# --- status mapping --------------------------------------------------------

def test_strong_mapping():
    m = QlooEntityMapping(product_pk=1, qloo_entity_id="e1", matched_name="Title",
                          match_status="strong", match_reason="Exactly one entity; please verify",
                          verification_status="unverified", evidence_id=5)
    r = mapping_to_resolution(m)
    assert r.status == QlooStatus.STRONG_MATCH and r.entity_id == "e1"
    assert r.entity_name == "Title" and "please verify" in r.note
    assert r.raw_ref == "qloo_evidence:5"


def test_confirmed_mapping_is_strong():
    m = QlooEntityMapping(product_pk=1, qloo_entity_id="e2", match_status="ambiguous",
                          verification_status="confirmed")
    r = mapping_to_resolution(m)
    assert r.status == QlooStatus.STRONG_MATCH and r.entity_id == "e2" and r.note == NOTE_CONFIRMED


def test_ambiguous_mapping_lists_alternatives():
    cands = [{"entity_id": f"e{i}", "name": f"Edition {chr(65 + i)}", "publication_year": 1990 + i}
             for i in range(7)] + [{"entity_id": "x"}]
    m = QlooEntityMapping(product_pk=1, qloo_entity_id=None, match_status="ambiguous",
                          verification_status="unverified", candidates=cands)
    r = mapping_to_resolution(m)
    assert r.status == QlooStatus.AMBIGUOUS and r.entity_id is None
    assert r.alternatives[0] == "Edition A (1990)" and len(r.alternatives) == 5


def test_none_and_rejected_mappings_are_no_match():
    none = QlooEntityMapping(product_pk=1, match_status="none", verification_status="unverified")
    rej = QlooEntityMapping(product_pk=1, qloo_entity_id="e1", match_status="strong",
                            verification_status="rejected")
    assert mapping_to_resolution(none).status == QlooStatus.NO_MATCH
    r = mapping_to_resolution(rej)
    assert r.status == QlooStatus.NO_MATCH and r.note == NOTE_REJECTED and r.entity_id is None


def test_parse_evidence_ref():
    assert parse_evidence_ref("qloo_evidence:12") == 12
    assert parse_evidence_ref("qloo_evidence:x") is None
    assert parse_evidence_ref("raw/1") is None
    assert parse_evidence_ref(None) is None


# --- gateway ---------------------------------------------------------------

def test_gateway_reuses_existing_mapping(db, monkeypatch):
    pk = add_product(db, "S1", "Target")
    add_mapping(db, pk, status="strong", entity_id="ent-t", evidence_id=None)
    monkeypatch.setattr(adapters.ers, "resolve_product",
                        lambda *a, **k: pytest.fail("must not call Qloo again"))
    gw = DbQlooGateway(db)
    r = gw.resolve(product_to_stock_item(db.get(Product, pk)))
    assert r.status == QlooStatus.STRONG_MATCH and r.entity_id == "ent-t"


def test_gateway_resolves_when_no_mapping_or_refresh(db, monkeypatch):
    pk = add_product(db, "S1", "Target")
    calls = []

    def fake_resolve(session, product_pk, force=False):  # TEST DOUBLE
        calls.append(product_pk)
        return QlooEntityMapping(product_pk=product_pk, qloo_entity_id="ent-new", match_status="strong",
                                 match_reason="r", verification_status="unverified", evidence_id=9)

    monkeypatch.setattr(adapters.ers, "resolve_product", fake_resolve)
    gw = DbQlooGateway(db)
    assert gw.resolve(product_to_stock_item(db.get(Product, pk))).entity_id == "ent-new"
    assert gw.evidence_ids == [9]
    add_mapping(db, pk, status="none", entity_id=None)
    DbQlooGateway(db, refresh=True).resolve(product_to_stock_item(db.get(Product, pk)))
    assert calls == [pk, pk]


def test_gateway_rolls_back_and_reraises(db, monkeypatch):
    pk = add_product(db, "S1", "Target")
    rolled = []
    monkeypatch.setattr(db, "rollback", lambda: rolled.append(True))

    def boom(*a, **k):  # TEST DOUBLE: Qloo down
        raise QlooError("Qloo request timed out", kind="timeout")

    monkeypatch.setattr(adapters.ers, "resolve_product", boom)
    with pytest.raises(QlooError):
        DbQlooGateway(db).resolve(product_to_stock_item(db.get(Product, pk)))
    assert rolled == [True]


def test_gateway_insights_mapping(db, monkeypatch):
    pk = add_product(db, "S1", "Target")
    add_mapping(db, pk, status="strong", entity_id="ent-t", evidence_id=3)
    seen = []

    def fake_insights(session, product_pk, take=10, target_type="urn:entity:book"):  # TEST DOUBLE
        seen.append((product_pk, take, target_type))
        return insights(
            InsightEntity(entity_id="r1", name="Related One", types=[target_type],
                          affinity=0.8, tags=[{"id": "t1", "name": "Satire", "type": "genre"},
                                              {"id": "t2"}, {"name": 5}, {"name": "  "}]),
            InsightEntity(entity_id=f"r2-{target_type}", name="Related Two"),
        )

    monkeypatch.setattr(adapters.ers, "insights_for_product", fake_insights)
    gw = DbQlooGateway(db, insights_take=7)
    res = gw.resolve(product_to_stock_item(db.get(Product, pk)))
    ents = gw.get_insights(res)
    expected_types = list(adapters.CROSS_CATEGORY_INSIGHT_TYPES)
    assert seen == [(pk, 7, target_type) for target_type in expected_types]
    assert len(ents) == 1 + len(expected_types)
    assert ents[0].entity_type == "urn:entity:book" and ents[0].affinity == 0.8
    assert ents[0].tags == ("Satire",) and ents[0].creators == ()
    assert ents[0].raw_ref == "qloo_evidence:41"
    assert gw.evidence_ids == [3, 41]


def test_gateway_insights_error_rolls_back(db, monkeypatch):
    pk = add_product(db, "S1", "Target")
    add_mapping(db, pk, status="strong", entity_id="ent-t")
    rolled = []
    monkeypatch.setattr(db, "rollback", lambda: rolled.append(True))
    monkeypatch.setattr(adapters.ers, "insights_for_product",
                        lambda *a, **k: (_ for _ in ()).throw(QlooError("x", kind="upstream")))
    gw = DbQlooGateway(db)
    res = gw.resolve(product_to_stock_item(db.get(Product, pk)))
    with pytest.raises(QlooError):
        gw.get_insights(res)
    assert len(rolled) == len(adapters.CROSS_CATEGORY_INSIGHT_TYPES)


# --- end to end over the DB ------------------------------------------------

@pytest.fixture
def shop(db, monkeypatch):
    """Illustrative bookshop: a slow target and two stocked titles (NOT real Qloo data)."""
    target = add_product(db, "T1", "Slow Novel", qty=24, cost=350, price=500, genre_or_subcategory="Literary")
    partner = add_product(db, "P1", "Companion Essays", qty=5, cost=200, price=400)
    other = add_product(db, "P2", "Unrelated Atlas", qty=9, cost=300, price=600)
    add_mapping(db, target, status="strong", entity_id="ent-target", evidence_id=None)
    monkeypatch.setattr(adapters.ers, "insights_for_product", lambda *a, **k: insights(
        InsightEntity(entity_id="ent-ce", name="Companion Essays", types=[k.get("target_type", "urn:entity:book")],
                      affinity=0.91 if k.get("target_type") == "urn:entity:book" else 0.72)))
    return {"target": target, "partner": partner, "other": other}


def run(db, pk):
    p = db.get(Product, pk)
    gw = DbQlooGateway(db)
    req = RescueRequest(product_to_stock_item(p), load_stock(db, p.retailer_id), Constraints(),
                        has_sales_history(p))
    return run_rescue(req, gw), gw


def test_end_to_end_plan_has_traceable_qloo_evidence(db, shop):
    plan, gw = run(db, shop["target"])
    RescuePlan.model_validate(plan.model_dump())
    assert plan.qloo_status == QlooStatus.STRONG_MATCH and plan.stages_failed == {}
    qloo = [e for s in plan.strategies for e in s.evidence if e.source == EvidenceSource.QLOO]
    assert qloo and all(e.raw_ref == "qloo_evidence:41" for e in qloo)
    assert all(e.affinity is not None for e in qloo)
    assert gw.evidence_ids == [41]
    assert "No sales history" in plan.limitations


def test_save_and_load_plan_round_trip(db, shop):
    plan, gw = run(db, shop["target"])
    plan_id = save_plan(db, plan, "demo", gw.evidence_ids)
    row, loaded = load_plan(db, plan_id)
    assert loaded == plan
    assert row.status == "draft" and row.evidence_ids == [41]
    assert shop["target"] in row.product_ids
    assert set(row.ranking_rationale) == {str(s.rank) for s in plan.strategies}
    assert load_plan(db, 9999) is None


def test_strategy_to_experiment_create(db, shop):
    plan, gw = run(db, shop["target"])
    bundle = next(s for s in plan.strategies if s.type.value == "bundle")
    data = strategy_to_experiment_create(plan, bundle.rank, plan_id=3)
    assert data.plan_id == 3 and data.product_pk == shop["target"]
    assert data.strategy_type == "bundle" and data.bundle_product_pks == [shop["partner"]]
    assert data.proposed_price == bundle.economics.selling_price
    assert data.calculated_margin_pct == bundle.economics.margin_pct
    assert data.estimated_cost == bundle.economics.estimated_experiment_cost
    assert data.qloo_evidence_ids == [41]
    assert bundle.test_plan in data.proposed_action
    with pytest.raises(KeyError):
        strategy_to_experiment_create(plan, 99, None)
