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

from app.schemas.rescue import EvidenceSource, QlooStatus, RescuePlan, Strategy

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
FORMAT_NOTE = (
    "An LLM explanation was discarded because it was empty, too long or not plain text."
)
CLAIMS_NOTE = (
    "An LLM explanation was discarded because it made claims the system cannot support "
    "(promised results, proof, or cultural evidence that is not available)."
)
_NOTE_FOR_REASON = {
    "numbers": DISCARD_NOTE,
    "format": FORMAT_NOTE,
    "claims": CLAIMS_NOTE,
}
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


def _has_usable_qloo_evidence(s: Strategy) -> bool:
    """Only evidence actually attached to this strategy unlocks cultural claims.

    A strong/ambiguous entity-resolution status is not itself evidence that an
    Insights request returned a useful related entity. In the real adapter,
    such evidence carries an entity id/name and a qloo_evidence provenance ref.
    """
    return any(
        evidence.source == EvidenceSource.QLOO
        and bool(
            evidence.entity_id
            and evidence.entity_name
            and evidence.raw_ref
            and re.fullmatch(r"qloo_evidence:\d+", evidence.raw_ref)
        )
        for evidence in s.evidence
    )


def build_prompt(plan: RescuePlan) -> str:
    """The full prompt for one plan (facts for every strategy plus the rules)."""
    # Resolution status alone does not prove that usable Insights evidence exists.
    qloo_ok = (
        plan.qloo_status not in (QlooStatus.NO_MATCH, QlooStatus.ERROR)
        and any(_has_usable_qloo_evidence(s) for s in plan.strategies)
    )
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


def _forms_of(s: Strategy, names: Iterable[str]) -> Set[str]:
    out: Set[str] = set()
    for name in names:
        out |= _number_forms(_value(s, name))
    return out


def _day_counts(s: Strategy) -> Set[str]:
    """Test lengths written by code in the test plan ('for 14 days')."""
    return set(re.findall(r"(\d+)\s*-?\s*days?\b", s.test_plan, flags=re.IGNORECASE))


def allowed_numbers(s: Strategy) -> Set[str]:
    """Every number string the model may write for this strategy: its computed
    values in common formats, its rank and its test length. Digits inside names
    are handled separately (the whole name must appear)."""
    return _forms_of(s, ALLOWED_PLACEHOLDERS) | _day_counts(s)


def _protected_names(s: Strategy) -> List[str]:
    names = {s.name} | {p.product_name for p in s.products}
    names |= {e.entity_name for e in s.evidence if e.entity_name}
    return sorted((n for n in names if n), key=len, reverse=True)  # longest first


_PCT_AFTER = re.compile(r"^\s*(?:%|per\s?cent)", re.IGNORECASE)
_MONEY_BEFORE = re.compile(r"(?:\brs\.?|₹|\binr)\s*$", re.IGNORECASE)
_DAYS_AFTER = re.compile(r"^\s*-?\s*days?\b", re.IGNORECASE)
_UNITS_AFTER = re.compile(
    r"^\s*(?:units?|copies|copy|books?|bundles?|titles?)\b|^\s+in\s+stock\b", re.IGNORECASE
)
_RANK_BEFORE = re.compile(r"(?:\bstrategy|\boption|\brank|\bnumber|#)\s*$", re.IGNORECASE)

_NUMBER_WORDS = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"hundreds?|thousands?|dozens?|double[sd]?|doubling|triple[sd]?|tripling|"
    r"twice|half|quarter|\w+fold)\b",
    re.IGNORECASE,
)
_CLAIMS = re.compile(
    r"\bguarantee[sd]?\b|\bsure[- ]?fire\b|\b(?:sure|certain|bound) to\b"
    r"|\bwill (?:definitely |certainly |surely |likely |easily )?"
    r"(?:sell|increase|boost|lift|raise|drive|improve|double|triple|grow|clear|move)\b"
    r"|\bproves?\b|\bproven (?:to|that)\b|\bwill be (?:a )?(?:hit|success|winner)\b",
    re.IGNORECASE,
)


def _number_in_context(token: str, before: str, after: str, s: Strategy) -> bool:
    """A raw number is only accepted if it is a value of THIS strategy AND the words
    around it say what kind of value it is (so a stock count of 24 cannot pass as a
    24% margin)."""
    if _PCT_AFTER.match(after):
        return token in _forms_of(s, ("margin_pct", "discount_pct"))
    if _MONEY_BEFORE.search(before):
        return token in _forms_of(
            s, ("selling_price", "unit_cost", "profit_per_unit", "estimated_experiment_cost")
        )
    if _DAYS_AFTER.match(after):
        return token in _day_counts(s)
    if _UNITS_AFTER.match(after):
        return token in _forms_of(s, ("units_available",))
    if _RANK_BEFORE.search(before):
        return token in _forms_of(s, ("rank",))
    return False


def _clean(text: str) -> str:
    return " ".join(_CONTROL_RE.sub(" ", text).split())


REASON_NUMBERS = "numbers"
REASON_FORMAT = "format"
REASON_CLAIMS = "claims"


def check_text(
    text: object, s: Strategy, settings: ExplanationSettings, *, qloo_usable: bool = True
):
    """Return (filled_text, None) if the text is safe, else (None, reason)."""
    if not isinstance(text, str):
        return None, REASON_FORMAT
    cleaned = _clean(text)
    if not cleaned:
        return None, REASON_FORMAT
    if any(n not in ALLOWED_PLACEHOLDERS for n in _PLACEHOLDER_RE.findall(cleaned)):
        return None, REASON_NUMBERS

    # Numbers: judged on the model's own words, with placeholders and whole names
    # (e.g. "Catch-22") taken out first.
    bare = _PLACEHOLDER_RE.sub(" ", cleaned)
    for name in _protected_names(s):
        bare = re.sub(re.escape(name), " ", bare, flags=re.IGNORECASE)
    if _NUMBER_WORDS.search(bare):
        return None, REASON_NUMBERS  # "ten", "double", "half" are numbers too
    for m in _NUMBER_RE.finditer(bare):
        token = m.group(0).replace(",", "").rstrip(".")
        before, after = bare[max(0, m.start() - 12): m.start()], bare[m.end(): m.end() + 16]
        if not _number_in_context(token, before, after, s):
            return None, REASON_NUMBERS

    if _CLAIMS.search(cleaned):
        return None, REASON_CLAIMS
    if not qloo_usable and re.search(r"\bqloo\b|\bcultural\b", cleaned, re.IGNORECASE):
        return None, REASON_CLAIMS

    filled = _PLACEHOLDER_RE.sub(lambda m: _render(s, m.group(1)), cleaned)
    filled = re.sub(r"\bRs\s+Rs\b", "Rs", filled).replace("%%", "%").strip()
    if not filled or len(filled) > settings.max_chars:
        return None, REASON_FORMAT
    return filled, None


def guard_text(
    text: object, s: Strategy, settings: ExplanationSettings, *, qloo_usable: bool = True
) -> Optional[str]:
    """Return the filled, safe explanation, or None if it must be discarded."""
    return check_text(text, s, settings, qloo_usable=qloo_usable)[0]


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
    notes: List[str] = []
    if parsed is None:
        notes.append(INVALID_JSON_NOTE)
        strategies = [s.model_copy(update={"llm_explanation": None}) for s in plan.strategies]
    else:
        for s in plan.strategies:
            key = str(s.rank)
            if key not in parsed:
                strategies.append(s.model_copy(update={"llm_explanation": None}))
                continue
            text, reason = check_text(
                parsed[key], s, settings,
                qloo_usable=(
                    plan.qloo_status not in (QlooStatus.NO_MATCH, QlooStatus.ERROR)
                    and _has_usable_qloo_evidence(s)
                ),
            )
            if text is None:
                note = _NOTE_FOR_REASON[reason]
                if note not in notes:
                    notes.append(note)
            strategies.append(s.model_copy(update={"llm_explanation": text}))

    update: Dict[str, object] = {"strategies": strategies}
    if notes:
        update["limitations"] = " ".join([plan.limitations, *notes])
    return plan.model_copy(update=update)
