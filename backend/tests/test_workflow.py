"""Tests for the rescue pipeline (app.agent.workflow).

Every gateway here is a TEST DOUBLE. Entity ids, names and relationships are
illustrative (NOT real Qloo data).
"""

import pytest

pytest.importorskip("pydantic")

from app.agent import workflow  # noqa: E402
from app.agent.workflow import (  # noqa: E402
    STAGE_BUILD,
    STAGE_CHECK,
    STAGE_EXPLAIN,
    STAGE_GENERATE,
    STAGE_INSIGHTS,
    STAGE_MATCH,
    STAGE_RANK,
    STAGE_RESOLVE,
    QlooResolution,
    RescueRequest,
    run_rescue,
)
from app.schemas.rescue import EvidenceSource, QlooStatus, RescuePlan  # noqa: E402
from app.services.constraints_service import ProductRef  # noqa: E402
from app.services.matcher_service import QlooRelatedEntity, StockItem  # noqa: E402
from app.services.rescue_config import Constraints  # noqa: E402

# --- illustrative fixtures (NOT real Qloo data) ----------------------------

TARGET = StockItem(ProductRef("B001", "Slow Literary Novel", 24, 350, 500), (), ("literary",))
PARTNER = StockItem(ProductRef("B002", "Companion Essays", 5, 200, 400), (), ("literary",))
STOCK = [TARGET, PARTNER]
CONSTRAINTS = Constraints()

ENTITY = QlooRelatedEntity(
    "ent-1", "Companion Essays", "urn:entity:book", (), ("literary",), "qloo_evidence:7",
    qloo_affinity=0.72, source_entity_id="ent-0", source_entity_type="urn:entity:book",
    evidence_id=7, request_params={"signal.interests.entities": "ent-0"},
    fetched_at="2026-10-30T06:00:00+00:00",
)
STRONG = QlooResolution(QlooStatus.STRONG_MATCH, "ent-0", "Slow Literary Novel")


def request(**kw):
    return RescueRequest(TARGET, STOCK, kw.pop("constraints", CONSTRAINTS), **kw)


# --- test doubles ----------------------------------------------------------

class FakeGateway:
    """TEST DOUBLE: returns canned values or raises canned errors."""

    def __init__(self, resolution=STRONG, entities=(ENTITY,), resolve_exc=None, insights_exc=None):
        self.resolution, self.entities = resolution, entities
        self.resolve_exc, self.insights_exc = resolve_exc, insights_exc
        self.insights_calls = 0

    def resolve(self, target):
        if self.resolve_exc:
            raise self.resolve_exc
        return self.resolution

    def get_insights(self, resolution):
        self.insights_calls += 1
        if self.insights_exc:
            raise self.insights_exc
        return self.entities


def qloo_evidence(plan):
    return [e for s in plan.strategies for e in s.evidence if e.source == EvidenceSource.QLOO]


def assert_valid(plan):
    assert isinstance(plan, RescuePlan)
    RescuePlan.model_validate(plan.model_dump())


# --- happy path ------------------------------------------------------------

def test_happy_path_completes_all_stages_with_qloo_evidence():
    plan = run_rescue(request(), FakeGateway())
    assert_valid(plan)
    assert plan.qloo_status == QlooStatus.STRONG_MATCH
    assert plan.stages_completed == [
        STAGE_RESOLVE, STAGE_INSIGHTS, STAGE_MATCH, STAGE_GENERATE, STAGE_CHECK, STAGE_RANK,
    ]
    assert plan.stages_failed == {}
    assert plan.strategies
    assert qloo_evidence(plan)
    assert all(e.entity_id for e in qloo_evidence(plan))


# --- Qloo outcomes ---------------------------------------------------------

def test_no_match_skips_insights_and_uses_retailer_data_only():
    gw = FakeGateway(resolution=QlooResolution(QlooStatus.NO_MATCH))
    plan = run_rescue(request(), gw)
    assert_valid(plan)
    assert gw.insights_calls == 0
    assert plan.qloo_status == QlooStatus.NO_MATCH
    assert STAGE_INSIGHTS not in plan.stages_completed + list(plan.stages_failed)
    assert STAGE_MATCH not in plan.stages_completed + list(plan.stages_failed)
    assert plan.stages_completed == [STAGE_RESOLVE, STAGE_GENERATE, STAGE_CHECK, STAGE_RANK]
    assert plan.stages_failed == {}
    assert plan.strategies  # promotion still feasible from retailer data
    assert qloo_evidence(plan) == []
    assert "no matching entity" in plan.qloo_note


def test_resolve_timeout_gives_error_status_and_skips_insights():
    gw = FakeGateway(resolve_exc=TimeoutError("qloo timed out"))
    plan = run_rescue(request(), gw)
    assert_valid(plan)
    assert gw.insights_calls == 0
    assert plan.qloo_status == QlooStatus.ERROR
    assert plan.stages_failed == {STAGE_RESOLVE: "TimeoutError: qloo timed out"}
    assert STAGE_RESOLVE not in plan.stages_completed
    assert "unavailable" in plan.qloo_note
    assert qloo_evidence(plan) == []
    assert "resolve" in plan.limitations  # failed stage is disclosed


def test_insights_timeout_gives_error_status_and_no_qloo_evidence():
    gw = FakeGateway(insights_exc=TimeoutError("slow"))
    plan = run_rescue(request(), gw)
    assert_valid(plan)
    assert plan.qloo_status == QlooStatus.ERROR
    assert plan.stages_completed[0] == STAGE_RESOLVE
    assert plan.stages_failed == {STAGE_INSIGHTS: "TimeoutError: slow"}
    assert qloo_evidence(plan) == []
    assert plan.strategies  # still returns a partial but useful plan


def test_empty_insights_keep_status_and_make_no_qloo_claims():
    plan = run_rescue(request(), FakeGateway(entities=()))
    assert_valid(plan)
    assert plan.qloo_status == QlooStatus.STRONG_MATCH
    assert STAGE_INSIGHTS in plan.stages_completed
    assert STAGE_MATCH not in plan.stages_completed  # nothing to match
    assert plan.stages_failed == {}
    assert "no related entities" in plan.qloo_note
    assert qloo_evidence(plan) == []


def test_ambiguous_with_entity_id_calls_insights_and_lists_alternatives():
    res = QlooResolution(
        QlooStatus.AMBIGUOUS, "ent-0", "Slow Literary Novel", alternatives=("Slow Novel (2019)", "The Slow Novel")
    )
    gw = FakeGateway(resolution=res)
    plan = run_rescue(request(), gw)
    assert_valid(plan)
    assert gw.insights_calls == 1
    assert plan.qloo_status == QlooStatus.AMBIGUOUS
    assert "Slow Novel (2019)" in plan.qloo_note and "The Slow Novel" in plan.qloo_note
    assert plan.stages_failed == {}


def test_ambiguous_without_entity_id_skips_insights():
    gw = FakeGateway(resolution=QlooResolution(QlooStatus.AMBIGUOUS, alternatives=("A", "B")))
    plan = run_rescue(request(), gw)
    assert_valid(plan)
    assert gw.insights_calls == 0
    assert plan.qloo_status == QlooStatus.AMBIGUOUS
    assert qloo_evidence(plan) == []
    assert "A; B" in plan.qloo_note


def test_strong_match_without_entity_id_is_treated_as_error():
    gw = FakeGateway(resolution=QlooResolution(QlooStatus.STRONG_MATCH))
    plan = run_rescue(request(), gw)
    assert_valid(plan)
    assert gw.insights_calls == 0
    assert plan.qloo_status == QlooStatus.ERROR
    assert qloo_evidence(plan) == []


def test_gateway_returning_wrong_type_is_a_resolve_failure():
    class BadGateway(FakeGateway):
        def resolve(self, target):
            return "strong_match"

    plan = run_rescue(request(), BadGateway())
    assert_valid(plan)
    assert plan.qloo_status == QlooStatus.ERROR
    assert STAGE_RESOLVE in plan.stages_failed
    assert plan.stages_failed[STAGE_RESOLVE].startswith("TypeError")


# --- sales history ---------------------------------------------------------

def test_missing_sales_history_adds_limitation():
    plan = run_rescue(request(has_sales_history=False), FakeGateway())
    assert "No sales history was available" in plan.limitations
    assert "not evidence that the product is unpopular" in plan.limitations
    assert "no sales-based comparison was made" in plan.limitations


@pytest.mark.parametrize("flag", [None, True])
def test_known_or_unknown_history_adds_no_history_limitation(flag):
    plan = run_rescue(request(has_sales_history=flag), FakeGateway())
    assert "sales history" not in plan.limitations


# --- mid-pipeline failures -------------------------------------------------

def _boom(*_a, **_k):
    raise RuntimeError("boom " + "x" * 500)


def test_match_failure_continues_with_empty_matches(monkeypatch):
    monkeypatch.setattr(workflow, "match_candidates", _boom)
    plan = run_rescue(request(), FakeGateway())
    assert_valid(plan)
    assert plan.stages_failed[STAGE_MATCH].startswith("RuntimeError: boom")
    assert len(plan.stages_failed[STAGE_MATCH]) <= len("RuntimeError: ") + 200
    assert STAGE_MATCH not in plan.stages_completed
    assert STAGE_GENERATE in plan.stages_completed and STAGE_RANK in plan.stages_completed
    assert qloo_evidence(plan) == []
    assert plan.strategies


def test_generate_failure_skips_check_and_rank_and_returns_empty_plan(monkeypatch):
    monkeypatch.setattr(workflow, "generate_strategies", _boom)
    plan = run_rescue(request(), FakeGateway())
    assert_valid(plan)
    assert list(plan.stages_failed) == [STAGE_GENERATE]
    assert plan.stages_completed == [STAGE_RESOLVE, STAGE_INSIGHTS, STAGE_MATCH]
    assert plan.strategies == []
    assert "generate" in plan.limitations


def test_check_failure_skips_rank(monkeypatch):
    monkeypatch.setattr(workflow, "check_candidate", _boom)
    plan = run_rescue(request(), FakeGateway())
    assert_valid(plan)
    assert list(plan.stages_failed) == [STAGE_CHECK]
    assert STAGE_RANK not in plan.stages_completed
    assert plan.strategies == []


def test_rank_failure_returns_plan_without_strategies(monkeypatch):
    monkeypatch.setattr(workflow, "rank_strategies", _boom)
    plan = run_rescue(request(), FakeGateway())
    assert_valid(plan)
    assert list(plan.stages_failed) == [STAGE_RANK]
    assert STAGE_CHECK in plan.stages_completed
    assert plan.strategies == []


def test_build_failure_returns_minimal_plan(monkeypatch):
    monkeypatch.setattr(workflow, "build_rescue_plan", _boom)
    plan = run_rescue(request(), FakeGateway())
    assert_valid(plan)
    assert plan.strategies == [] and plan.rejected == []
    assert STAGE_BUILD in plan.stages_failed
    assert plan.limitations == RescuePlan.model_fields["limitations"].default
    assert plan.product_id == "B001"
    assert plan.stages_completed[0] == STAGE_RESOLVE


# --- explain stage ---------------------------------------------------------

def test_explain_success_is_recorded_and_used():
    def explain(plan):
        return plan.model_copy(update={"qloo_note": "explained"})

    plan = run_rescue(request(), FakeGateway(), explain=explain)
    assert_valid(plan)
    assert plan.qloo_note == "explained"
    assert plan.stages_completed[-1] == STAGE_EXPLAIN


def test_explain_failure_keeps_plan_and_records_failure():
    base = run_rescue(request(), FakeGateway())

    def explain(plan):
        raise ConnectionError("provider down")

    plan = run_rescue(request(), FakeGateway(), explain=explain)
    assert_valid(plan)
    assert plan.stages_failed == {STAGE_EXPLAIN: "ConnectionError: provider down"}
    assert STAGE_EXPLAIN not in plan.stages_completed
    assert [s.name for s in plan.strategies] == [s.name for s in base.strategies]
    assert "explanation step failed" in plan.limitations


def test_explain_returning_non_plan_is_a_failure():
    plan = run_rescue(request(), FakeGateway(), explain=lambda p: "text")
    assert_valid(plan)
    assert STAGE_EXPLAIN in plan.stages_failed
    assert plan.strategies


# --- invariants across scenarios -------------------------------------------

SCENARIOS = {
    "happy": FakeGateway(),
    "no_match": FakeGateway(resolution=QlooResolution(QlooStatus.NO_MATCH)),
    "resolve_error": FakeGateway(resolve_exc=TimeoutError("t")),
    "insights_error": FakeGateway(insights_exc=TimeoutError("t")),
    "empty_insights": FakeGateway(entities=()),
    "ambiguous": FakeGateway(resolution=QlooResolution(QlooStatus.AMBIGUOUS, "ent-0")),
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_validates_and_has_consistent_stage_lists(name):
    plan = run_rescue(request(), SCENARIOS[name])
    assert_valid(plan)
    assert not set(plan.stages_completed) & set(plan.stages_failed)
    assert len(plan.stages_completed) == len(set(plan.stages_completed))
    assert set(plan.stages_completed) | set(plan.stages_failed) <= set(workflow.STAGES)
    if plan.qloo_status in (QlooStatus.ERROR, QlooStatus.NO_MATCH):
        assert qloo_evidence(plan) == []


def test_run_rescue_never_raises_even_on_bad_request():
    class Broken:
        target = None
        stock = None
        constraints = None
        has_sales_history = None

    plan = run_rescue(Broken(), FakeGateway())  # type: ignore[arg-type]
    assert_valid(plan)
    assert plan.strategies == []
    assert plan.stages_failed
