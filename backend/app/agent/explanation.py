"""Optional LLM explanation for a RescuePlan, behind a numeric guard.

The language model writes plain sentences only. It may refer to numbers
solely through placeholders ({selling_price}, {margin_pct}, ...), which this
module fills from the strategy's Economics block (computed by deterministic
code). A text is discarded when it:

- is empty after cleaning,
- uses a placeholder that is not on the allowed list,
- contains a number that the system did not calculate, or
- is longer than ExplanationSettings.max_chars after filling.

Numbers the guard accepts in the raw model text:
  (a) the strategy's Economics values and rank, in common formats
      (810, 810.0, 810.00; 32.14 -> 32, 32.1, 32.14);
  (b) any digit sequence that already appears in deterministic text of the
      SAME strategy: its name, summary, test plan, assumptions, risks, product
      names and evidence notes/entity names (e.g. "Catch-22", "14 days").
      All of that text is written by code, so the number was calculated by
      the system, not by the model.

A discarded text leaves Strategy.llm_explanation as None and adds one
sentence to the plan's limitations. Invalid JSON discards every explanation.

Provider-agnostic: the only dependency is `complete: Callable[[str], str]`.
Exceptions raised by `complete` are NOT caught here; the pipeline's explain
stage records them (see app.agent.workflow). Use with run_rescue as
    explain=functools.partial(explain_plan, complete=my_completer)

Requires pydantic (imports app.schemas.rescue).
"""

from __future__ import annotations

import json
import re
from typing import Callable, Dict, Iterable, List, Optional, Set

from app.schemas.rescue import QlooStatus, RescuePlan, Strategy

from app.services.rescue_config import DEFAULT_EXPLANATION_SETTINGS, ExplanationSettings

from .prompts import (
    ALLOWED_PLACEHOLDERS,
    INTEGER_PLACEHOLDERS,
    MONEY_PLACEHOLDERS,
    PERCENT_PLACEHOLDERS,
    QLOO_RULE_AVAILABLE,
    QLOO_RULE_UNAVAILABLE,
    STRATEGY_HEADER,
    SYSTEM_INSTRUCTIONS,
)

CompleteFn = Callable[[str], str]

DISCARD_NOTE = (
    "An LLM explanation was discarded because it contained numbers or placeholders "
    "the system did not calculate."
)
INVALID_JSON_NOTE = (
    "LLM explanations were discarded because the model's reply was not valid JSON "
    "in the expected format."
)

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*(.*?)\s*```$", re.DOTALL)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _money(x: float) -> str:
    """Same style as strategy_generator: 'Rs 1,250' or 'Rs 1,250.50'."""
    return f"Rs {x:,.2f}".replace(".00", "")


def _value(strategy: Strategy, name: str) -> float:
    if name == "rank":
        return float(strategy.rank)
    return float(getattr(strategy.economics, name))


def _render(strategy: Strategy, name: str) -> str:
    v = _value(strategy, name)
    if name in MONEY_PLACEHOLDERS:
        return _money(v)
    if name in PERCENT_PLACEHOLDERS:
        return f"{v:.1f}%"
    return str(int(round(v)))


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def _strategy_facts(s: Strategy) -> str:
    target = [p.product_name for p in s.products if p.role == "target"]
    partners = [p.product_name for p in s.products if p.role != "target"]
    links = [
        f"'{e.entity_name}'" for e in s.evidence
        if e.source.value == "qloo" and e.entity_name
    ]
    lines = [
        STRATEGY_HEADER.format(rank=s.rank),
        f"- type: {s.type.value}",
        f"- name: {s.name}",
        f"- summary: {s.summary}",
        f"- target product: {', '.join(target) or 'none'}",
        f"- partner products: {', '.join(partners) or 'none'}",
        f"- cultural links (Qloo, hypotheses only): {', '.join(links) or 'none'}",
        f"- operational effort: {s.operational_effort}",
        "- numbers (write ONLY the placeholder on the right):",
    ]
    for name in ALLOWED_PLACEHOLDERS:
        lines.append(f"    {_render(s, name)} -> {{{name}}}")
    return "\n".join(lines)


def build_prompt(plan: RescuePlan) -> str:
    """The full prompt for one plan (facts for every strategy plus the rules)."""
    qloo_ok = plan.qloo_status in (QlooStatus.STRONG_MATCH, QlooStatus.AMBIGUOUS)
    header = SYSTEM_INSTRUCTIONS.format(
        placeholders=", ".join(f"{{{p}}}" for p in ALLOWED_PLACEHOLDERS),
        qloo_rule=QLOO_RULE_AVAILABLE if qloo_ok else QLOO_RULE_UNAVAILABLE,
    )
    body = "\n\n".join(_strategy_facts(s) for s in sorted(plan.strategies, key=lambda s: s.rank))
    return f"{header}\nPRODUCT: {plan.product_name}\n\n{body}\n"


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

def _number_forms(v: float) -> Set[str]:
    forms = {f"{v:.0f}", f"{v:.1f}", f"{v:.2f}", f"{v:g}"}
    if float(v).is_integer():
        forms.add(str(int(v)))
    return forms


def _tokens(text: Optional[str]) -> Set[str]:
    return {t.replace(",", "").rstrip(".") for t in _NUMBER_RE.findall(text or "")}


def _deterministic_texts(s: Strategy) -> Iterable[str]:
    yield s.name
    yield s.summary
    yield s.test_plan
    yield from s.assumptions
    yield from s.risks
    for p in s.products:
        yield p.product_name
    for e in s.evidence:
        yield e.note
        if e.entity_name:
            yield e.entity_name


def allowed_numbers(s: Strategy) -> Set[str]:
    """Every number string the model may write for this strategy."""
    allowed: Set[str] = set()
    for name in ALLOWED_PLACEHOLDERS:
        allowed |= _number_forms(_value(s, name))
    for text in _deterministic_texts(s):
        allowed |= _tokens(text)
    return allowed


def _clean(text: str) -> str:
    return " ".join(_CONTROL_RE.sub(" ", text).split())


def guard_text(text: object, s: Strategy, settings: ExplanationSettings) -> Optional[str]:
    """Return the filled, safe explanation, or None if it must be discarded."""
    if not isinstance(text, str):
        return None
    cleaned = _clean(text)
    if not cleaned:
        return None
    names = _PLACEHOLDER_RE.findall(cleaned)
    if any(n not in ALLOWED_PLACEHOLDERS for n in names):
        return None
    if not _tokens(cleaned) <= allowed_numbers(s):
        return None
    filled = _PLACEHOLDER_RE.sub(lambda m: _render(s, m.group(1)), cleaned)
    filled = re.sub(r"\bRs\s+Rs\b", "Rs", filled).replace("%%", "%")
    filled = filled.strip()
    if not filled or len(filled) > settings.max_chars:
        return None
    return filled


def parse_reply(raw: object) -> Optional[Dict[str, object]]:
    """{"strategies": {...}} -> the inner dict, or None if the reply is unusable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    fence = _FENCE_RE.match(text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("strategies"), dict):
        return None
    inner = data["strategies"]
    if not all(isinstance(v, str) for v in inner.values()):
        return None
    return {str(k): v for k, v in inner.items()}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def explain_plan(
    plan: RescuePlan,
    complete: CompleteFn,
    settings: ExplanationSettings = DEFAULT_EXPLANATION_SETTINGS,
) -> RescuePlan:
    """Return a copy of `plan` with guarded llm_explanation fields. Never mutates
    the input. Errors from `complete` propagate (the pipeline records them)."""
    if not plan.strategies:
        return plan

    reply = complete(build_prompt(plan))
    parsed = parse_reply(reply)

    strategies: List[Strategy] = []
    note: Optional[str] = None
    if parsed is None:
        note = INVALID_JSON_NOTE
        strategies = [s.model_copy(update={"llm_explanation": None}) for s in plan.strategies]
    else:
        for s in plan.strategies:
            key = str(s.rank)
            if key not in parsed:
                strategies.append(s.model_copy(update={"llm_explanation": None}))
                continue
            text = guard_text(parsed[key], s, settings)
            if text is None:
                note = DISCARD_NOTE
            strategies.append(s.model_copy(update={"llm_explanation": text}))

    update: Dict[str, object] = {"strategies": strategies}
    if note:
        update["limitations"] = f"{plan.limitations} {note}"
    return plan.model_copy(update=update)
