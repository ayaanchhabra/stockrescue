"""Prompt text for the optional LLM explanation step.

Kept in one place so the wording can be reviewed without reading the guard
code. The model only ever writes words: every number reaches the user through
a placeholder that deterministic code fills from the strategy's Economics.
"""

from __future__ import annotations

from typing import Tuple

# Placeholders the model may use. Each is filled by app.agent.explanation.
MONEY_PLACEHOLDERS: Tuple[str, ...] = (
    "selling_price",
    "unit_cost",
    "profit_per_unit",
    "estimated_experiment_cost",
)
PERCENT_PLACEHOLDERS: Tuple[str, ...] = ("margin_pct", "discount_pct")
INTEGER_PLACEHOLDERS: Tuple[str, ...] = ("units_available", "rank")

ALLOWED_PLACEHOLDERS: Tuple[str, ...] = (
    MONEY_PLACEHOLDERS + PERCENT_PLACEHOLDERS + INTEGER_PLACEHOLDERS
)

SYSTEM_INSTRUCTIONS = """\
You explain stock-rescue experiments to the owner of a small independent bookshop.
For EACH strategy below, write 2-3 plain, friendly sentences: why it might be worth
testing, what to watch out for, and how the test works.

STRICT RULES
- Do not write any digits yourself. When you need a number, use ONLY these
  placeholders exactly as written: {placeholders}.
  Placeholders already include their unit: {{selling_price}} becomes "Rs 810" and
  {{margin_pct}} becomes "32.1%". Do not add "Rs" or "%" yourself.
- Qloo links are hypotheses for what to test. They do NOT prove anything will sell.
- Do not promise, predict or estimate sales, uplift or conversion.
- Do not invent facts that are not listed below.
- {qloo_rule}
- Reply with ONLY this JSON and nothing else:
  {{"strategies": {{"1": "...", "2": "..."}}}}
  using each strategy's rank as the key.
"""

QLOO_RULE_AVAILABLE = (
    "You may mention the listed cultural links, always as hypotheses to test."
)
QLOO_RULE_UNAVAILABLE = (
    "Qloo gave no usable cultural evidence for this plan, so do not mention "
    "cultural links or Qloo evidence at all."
)

STRATEGY_HEADER = "STRATEGY {rank}"
