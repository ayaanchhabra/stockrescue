"""Guard hardening for the LLM explanation (app.agent.explanation).

A digit string is no longer enough: the words around a number must say what kind
of value it is, and it must be a value of THIS strategy. Spelled-out numbers,
promised results, "proves" claims and Qloo mentions when Qloo gave nothing are
discarded too. `complete` is a TEST DOUBLE; data is illustrative (NOT real Qloo data).
"""

import pytest

pytest.importorskip("pydantic")

from app.agent.explanation import (  # noqa: E402
    CLAIMS_NOTE,
    DISCARD_NOTE,
    FORMAT_NOTE,
    build_prompt,
    explain_plan,
    guard_text,
)
from app.agent.workflow import QlooResolution, RescueRequest, run_rescue  # noqa: E402
from app.schemas.rescue import QlooStatus  # noqa: E402
from app.services.constraints_service import ProductRef  # noqa: E402
from app.services.matcher_service import StockItem  # noqa: E402
from app.services.rescue_config import DEFAULT_EXPLANATION_SETTINGS as S  # noqa: E402
from app.services.rescue_config import Constraints  # noqa: E402

from test_explanation import Complete, make_plan, reply  # noqa: E402

# Product: 24 in stock, cost 350, price 500 -> margin 30%, 24 units, 14-day test.
T = ProductRef("1", "Slow Novel", 24, 350, 500)


class NoMatchGateway:
    """TEST DOUBLE: Qloo found nothing."""

    def resolve(self, target):
        return QlooResolution(QlooStatus.NO_MATCH)

    def get_insights(self, resolution):
        raise AssertionError("not called")


@pytest.fixture(scope="module")
def strategy():
    plan = run_rescue(RescueRequest(StockItem(T), [StockItem(T)], Constraints()), NoMatchGateway())
    s = plan.strategies[0]
    assert s.economics.margin_pct == 30.0 and s.economics.units_available == 24
    return s


# --- the reproduced bypasses are now closed --------------------------------

@pytest.mark.parametrize("text", [
    "Your margin is 24%.",                    # 24 is the stock count, not a margin
    "Selling at 14 is wise.",                 # 14 comes from '14 days'
    "It sells for Rs 24.",                    # 24 is not a price
    "About 30 units will be available.",      # 30 is the margin, not the units
    "Strategy 7 is the best one.",            # not this strategy's rank
])
def test_number_with_the_wrong_meaning_is_rejected(strategy, text):
    assert guard_text(text, strategy, S) is None


@pytest.mark.parametrize("text", [
    "This should double sales.",
    "Expect ten extra sales.",
    "Use one unit for the test.",
    "The first display is the best option.",
    "Roughly half of shoppers may buy it.",
    "A tenfold increase is possible.",
])
def test_spelled_out_numbers_are_rejected(strategy, text):
    assert guard_text(text, strategy, S) is None


@pytest.mark.parametrize("text", [
    "This is a guaranteed win.",
    "It will sell out quickly.",
    "It will increase sales.",
    "Qloo proves customers want this.",
    "It is sure to work.",
])
def test_promises_and_proof_claims_are_rejected(strategy, text):
    assert guard_text(text, strategy, S) is None


# --- honest text still passes ----------------------------------------------

@pytest.mark.parametrize("text", [
    "Test this at Rs 500 with a 30% margin.",
    "Test this at Rs 500.00 for 14 days.",
    "A 14-day test; 24 units can be supplied.",
    "This is strategy 1 in the list.",
    "A hypothesis to test, not proof of sales. Outcomes are unproven.",
    "Test this at {selling_price} with a {margin_pct} margin for 14 days.",
])
def test_correct_numbers_with_the_right_meaning_pass(strategy, text):
    assert guard_text(text, strategy, S) is not None


# --- reasons and notes -----------------------------------------------------

def _note_for(text):
    plan = make_plan()
    out = explain_plan(plan, Complete(reply(**{"1": text})))
    assert out.strategies[0].llm_explanation is None
    return out.limitations


def test_each_reason_gets_its_own_accurate_note():
    assert DISCARD_NOTE in _note_for("Expect 40 extra copies.")
    assert FORMAT_NOTE in _note_for("   ")
    assert FORMAT_NOTE in _note_for("word " * 200)
    assert CLAIMS_NOTE in _note_for("This is guaranteed.")


def test_qloo_mentions_are_rejected_when_qloo_gave_nothing():
    plan = run_rescue(RescueRequest(StockItem(T), [StockItem(T)], Constraints()), NoMatchGateway())
    out = explain_plan(plan, Complete(reply(**{"1": "Cultural links suggest shoppers will like it."})))
    assert out.strategies[0].llm_explanation is None
    assert CLAIMS_NOTE in out.limitations


def test_ambiguous_match_without_insights_does_not_unlock_qloo_claims():
    t = StockItem(T)
    ambiguous = type("AmbiguousGateway", (), {
        "resolve": lambda self, target: QlooResolution(
            QlooStatus.AMBIGUOUS, None, None, alternatives=("Slow Novel (A)", "Slow Novel (B)")
        ),
        "get_insights": lambda self, resolution: (_ for _ in ()).throw(
            AssertionError("insights must not run for an unconfirmed ambiguous match")
        ),
    })()
    plan = run_rescue(RescueRequest(t, [t], Constraints()), ambiguous)
    assert plan.qloo_status == QlooStatus.AMBIGUOUS
    assert "do not mention cultural links" in build_prompt(plan)
    out = explain_plan(plan, Complete(reply(**{"1": "Cultural links can guide a display."})))
    assert out.strategies[0].llm_explanation is None
    assert CLAIMS_NOTE in out.limitations


def test_strong_match_without_insights_does_not_unlock_qloo_claims():
    plan = run_rescue(
        RescueRequest(StockItem(T), [StockItem(T)], Constraints()),
        type("NoInsightsGateway", (), {
            "resolve": lambda self, target: QlooResolution(
                QlooStatus.STRONG_MATCH, "ent-no-insights", "Slow Novel"
            ),
            "get_insights": lambda self, resolution: (),
        })(),
    )
    assert plan.qloo_status == QlooStatus.STRONG_MATCH
    assert "do not mention cultural links" in build_prompt(plan)
    out = explain_plan(plan, Complete(reply(**{"1": "Qloo links can guide a display."})))
    assert out.strategies[0].llm_explanation is None


def test_qloo_hypothesis_wording_is_fine_when_qloo_matched():
    plan = make_plan()
    text = "The cultural link is a hypothesis to test, not proof."
    out = explain_plan(plan, Complete(reply(**{"1": text})))
    assert out.strategies[0].llm_explanation == text
