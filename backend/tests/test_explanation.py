"""Tests for the guarded LLM explanation (app.agent.explanation).

`complete` is always a TEST DOUBLE. Product names, entity ids and relationships
are illustrative (NOT real Qloo data).
"""

import json
from functools import partial

import pytest

pytest.importorskip("pydantic")

from app.agent.explanation import (  # noqa: E402
    DISCARD_NOTE,
    FORMAT_NOTE,
    INVALID_JSON_NOTE,
    allowed_numbers,
    build_prompt,
    explain_plan,
)
from app.agent.workflow import STAGE_EXPLAIN, QlooResolution, RescueRequest, run_rescue  # noqa: E402
from app.schemas.rescue import QlooStatus, RescuePlan  # noqa: E402
from app.services.constraints_service import ProductRef  # noqa: E402
from app.services.matcher_service import QlooRelatedEntity, StockItem  # noqa: E402
from app.services.rescue_config import Constraints, ExplanationSettings  # noqa: E402

# --- illustrative fixtures (NOT real Qloo data) ----------------------------

TARGET = StockItem(ProductRef("1", "Catch-22", 24, 350, 500), (), ("satire",))
PARTNER = StockItem(ProductRef("2", "Slaughterhouse Companion", 6, 200, 400), (), ("satire",))
ENTITY = QlooRelatedEntity(
    "ent-7", "Slaughterhouse Companion", "urn:entity:book", (), ("satire",), "qloo_evidence:7",
    qloo_affinity=0.68, source_entity_id="ent-0", source_entity_type="urn:entity:book",
    evidence_id=7, request_params={"signal.interests.entities": "ent-0"},
    fetched_at="2026-10-30T06:00:00+00:00",
)


class Gateway:
    """TEST DOUBLE gateway: strong match with one related entity."""

    def resolve(self, target):
        return QlooResolution(QlooStatus.STRONG_MATCH, "ent-0", "Catch-22")

    def get_insights(self, resolution):
        return (ENTITY,)


def make_plan() -> RescuePlan:
    plan = run_rescue(RescueRequest(TARGET, [TARGET, PARTNER], Constraints()), Gateway())
    assert len(plan.strategies) >= 2
    return plan


def reply(**texts) -> str:
    return json.dumps({"strategies": texts})


class Complete:
    """TEST DOUBLE for an LLM: returns a canned reply and records the prompt."""

    def __init__(self, text):
        self.text, self.prompts = text, []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.text


def s1(plan):
    return next(s for s in plan.strategies if s.rank == 1)


GOOD = "Test this at {selling_price} with a {margin_pct} margin; {units_available} units can be supplied."


# --- prompt ----------------------------------------------------------------

def test_prompt_lists_facts_placeholders_and_rules():
    plan = make_plan()
    prompt = build_prompt(plan)
    for s in plan.strategies:
        assert f"STRATEGY {s.rank}" in prompt and s.name in prompt
    assert "{selling_price}" in prompt and "{margin_pct}" in prompt
    assert "do NOT prove" in prompt
    assert "uplift" in prompt
    assert '"strategies"' in prompt


def test_prompt_forbids_cultural_claims_when_qloo_failed():
    plan = make_plan().model_copy(update={"qloo_status": QlooStatus.NO_MATCH})
    assert "do not mention cultural links" in build_prompt(plan)


# --- accepted text ---------------------------------------------------------

def test_good_text_is_accepted_and_numbers_match_economics():
    plan = make_plan()
    out = explain_plan(plan, Complete(reply(**{"1": GOOD})))
    eco = s1(out).economics
    text = s1(out).llm_explanation
    assert text is not None
    assert f"Rs {eco.selling_price:,.2f}".replace(".00", "") in text
    assert f"{eco.margin_pct:.1f}%" in text
    assert f"{eco.units_available} units" in text
    assert "{" not in text
    assert DISCARD_NOTE not in out.limitations


def test_unit_duplicates_are_collapsed():
    plan = make_plan()
    out = explain_plan(plan, Complete(reply(**{"1": "Price Rs {selling_price}, margin {margin_pct}%."})))
    text = s1(out).llm_explanation
    assert "Rs Rs" not in text and "%%" not in text


def test_number_inside_a_title_is_allowed():
    plan = make_plan()
    out = explain_plan(plan, Complete(reply(**{"1": "Readers of Catch-22 may enjoy this; test it."})))
    assert s1(out).llm_explanation == "Readers of Catch-22 may enjoy this; test it."


def test_test_day_count_from_the_test_plan_is_allowed():
    plan = make_plan()
    assert "14 days" in s1(plan).test_plan
    out = explain_plan(plan, Complete(reply(**{"1": "Run it for 14 days and record sales."})))
    assert s1(out).llm_explanation is not None


def test_computed_value_in_plain_form_is_allowed():
    plan = make_plan()
    eco = s1(plan).economics
    text = f"The margin is about {eco.margin_pct:.0f} percent."
    out = explain_plan(plan, Complete(reply(**{"1": text})))
    assert s1(out).llm_explanation == text


def test_code_fenced_json_is_accepted():
    plan = make_plan()
    fenced = "```json\n" + reply(**{"1": GOOD}) + "\n```"
    assert s1(explain_plan(plan, Complete(fenced))).llm_explanation is not None


def test_control_characters_are_stripped():
    plan = make_plan()
    out = explain_plan(plan, Complete(reply(**{"1": "Good\x00 idea.\nTest\tit."})))
    assert s1(out).llm_explanation == "Good idea. Test it."


# --- rejected text ---------------------------------------------------------

def test_invented_number_is_rejected():
    plan = make_plan()
    out = explain_plan(plan, Complete(reply(**{"1": "This could lift sales by 40 percent."})))
    assert s1(out).llm_explanation is None
    assert out.limitations.count(DISCARD_NOTE) == 1


def test_changed_margin_is_rejected():
    plan = make_plan()
    eco = s1(plan).economics
    wrong = round(eco.margin_pct) + 7
    assert str(wrong) not in allowed_numbers(s1(plan))
    out = explain_plan(plan, Complete(reply(**{"1": f"The margin is {wrong}%."})))
    assert s1(out).llm_explanation is None


def test_unknown_placeholder_is_rejected():
    plan = make_plan()
    out = explain_plan(plan, Complete(reply(**{"1": "Expect {predicted_uplift} more sales."})))
    assert s1(out).llm_explanation is None
    assert DISCARD_NOTE in out.limitations


def test_oversize_text_is_rejected():
    plan = make_plan()
    long_text = "word " * 200
    out = explain_plan(plan, Complete(reply(**{"1": long_text})))
    assert s1(out).llm_explanation is None


def test_max_chars_setting_is_used():
    plan = make_plan()
    out = explain_plan(plan, Complete(reply(**{"1": "A short but fine sentence."})),
                       ExplanationSettings(max_chars=10))
    assert s1(out).llm_explanation is None


def test_empty_text_is_rejected():
    plan = make_plan()
    out = explain_plan(plan, Complete(reply(**{"1": "  \n "})))
    assert s1(out).llm_explanation is None
    assert FORMAT_NOTE in out.limitations


def test_one_note_even_when_several_texts_are_rejected():
    plan = make_plan()
    out = explain_plan(plan, Complete(reply(**{"1": "Up 50%.", "2": "Up 60%."})))
    assert out.limitations.count(DISCARD_NOTE) == 1


@pytest.mark.parametrize("bad", [
    "not json at all",
    json.dumps({"wrong": {}}),
    json.dumps({"strategies": {"1": 5}}),
    json.dumps(["strategies"]),
])
def test_invalid_json_discards_all_with_one_note(bad):
    plan = make_plan()
    out = explain_plan(plan, Complete(bad))
    assert all(s.llm_explanation is None for s in out.strategies)
    assert out.limitations.count(INVALID_JSON_NOTE) == 1


def test_missing_key_gives_none_without_a_note():
    plan = make_plan()
    out = explain_plan(plan, Complete(reply(**{"1": GOOD})))
    others = [s for s in out.strategies if s.rank != 1]
    assert others and all(s.llm_explanation is None for s in others)
    assert DISCARD_NOTE not in out.limitations and INVALID_JSON_NOTE not in out.limitations


# --- purity and integration ------------------------------------------------

def test_input_plan_is_not_mutated():
    plan = make_plan()
    before = plan.model_dump()
    explain_plan(plan, Complete(reply(**{"1": GOOD, "2": "Up 99%."})))
    assert plan.model_dump() == before


def test_plan_without_strategies_does_not_call_the_model():
    plan = make_plan().model_copy(update={"strategies": []})
    fake = Complete(reply())
    assert explain_plan(plan, fake) is plan
    assert fake.prompts == []


def test_output_revalidates_as_a_rescue_plan():
    plan = make_plan()
    out = explain_plan(plan, Complete(reply(**{"1": GOOD, "2": "Up 99%."})))
    RescuePlan.model_validate(out.model_dump())


def test_works_as_the_pipeline_explain_step():
    req = RescueRequest(TARGET, [TARGET, PARTNER], Constraints())
    plan = run_rescue(req, Gateway(), explain=partial(explain_plan, complete=Complete(reply(**{"1": GOOD}))))
    assert STAGE_EXPLAIN in plan.stages_completed
    assert s1(plan).llm_explanation is not None


def test_provider_error_is_recorded_by_the_pipeline():
    def broken(prompt):  # TEST DOUBLE: provider down
        raise TimeoutError("llm timed out")

    req = RescueRequest(TARGET, [TARGET, PARTNER], Constraints())
    plan = run_rescue(req, Gateway(), explain=partial(explain_plan, complete=broken))
    assert plan.stages_failed[STAGE_EXPLAIN] == "TimeoutError: llm timed out"
    assert plan.strategies and all(s.llm_explanation is None for s in plan.strategies)
    RescuePlan.model_validate(plan.model_dump())
