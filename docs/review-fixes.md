# Logic review fixes (Person 2 / decision engine)

Paste the PROMPT below into a teammate's message or another AI session to explain
what changed and why. Tests: `cd backend && python -m pytest -q` -> 456 passed.

## PROMPT

I reviewed the completed StockRescue backend for logic mistakes and fixed ten of them.
Every fix has a regression test, and I broke each fix on purpose once to confirm its
tests fail. Please review the diff with these reasons in mind. Do not change economics_service,
constraints_service, ranking_service or schemas/rescue.py.

Rules the fixes protect: deterministic code owns every number and every hard rule; the
LLM never calculates; Qloo links are hypotheses; a person's confirm/reject decision on a
Qloo match is final; the retailer approves every action.

1. Restricted products in themed displays (services/strategy_generator.py).
   Why: the display strategy only passed the target to the constraint engine, so a
   restricted partner was still named in the display and cited as evidence. Now restricted
   titles are dropped from displays; if nothing usable is left the display is face-out.

2. refresh_qloo undid human decisions (agent/adapters.py, schemas/rescue_api.py).
   Why: refresh called entity_resolution_service.resolve_product(force=False), which resets
   a REJECTED mapping to "unverified" and ignores CONFIRMED ones. Now refresh re-resolves
   only unjudged mappings and never touches confirmed or rejected ones.

3. Experiments bypassed the hard rules (services/experiment_guard.py [new],
   services/experiment_service.py, errors.py, main.py, schemas/experiments.py).
   Why: PATCH could change price/bundle and approve never re-checked, and the client could
   write calculated_margin_pct. Now create, edit and approve re-run check_candidate on
   CURRENT stock/prices with the plan's saved rules (422 constraint_violation), and the
   margin is always computed server-side; a client margin is ignored.

4. LLM explanation guard accepted wrong or unsafe text (agent/explanation.py).
   Why: any digit string found anywhere in the strategy text was allowed, so "Your margin
   is 24%" passed because 24 was the stock count. Now a raw number must match a value of
   THIS strategy AND the words around it must say what it is (Rs / % / days / units /
   strategy N). Spelled-out numbers, promises ("guaranteed", "will increase sales"),
   "proves" claims, and Qloo/cultural mentions when Qloo gave nothing are rejected.

5. Stale or duplicate experiments from a saved plan (services/experiment_service.py,
   api/rescue.py). Why: creating from a stored plan used old stock/prices and could be done
   twice. Now it re-checks (422 plan_outdated) and blocks a second live experiment for the
   same plan strategy (409 duplicate_experiment); rejected/cancelled ones can be re-proposed.

6. Two rules for sales change (services/experiment_calc.py).
   Why: economics_service returns None for periods under 7 days but experiment_calc still
   showed a percentage. Now experiment_calc uses economics_service.sales_change_pct, and
   short periods show no percentage and no derived comparison.

7. Ambiguous-match wording (agent/workflow.py, services/plan_builder.py).
   Why: with no confirmed entity no insights are fetched, yet the text said links were
   "treated as low-confidence". Now it says no cultural evidence is used until a person
   confirms.

8. Face-out display wording (services/strategy_generator.py).
   Why: it said "No cultural link was available" even when links existed but none could be
   shown. Now it says why.

9. Explanation discard notes (agent/explanation.py).
   Why: one note claimed "contained numbers" even for empty or too-long text. Now there are
   three accurate notes: numbers, format, claims.

10. Bundle attempts used up by blocked partners (services/strategy_generator.py).
    Why: restricted or out-of-stock partners counted toward max_bundle_attempts, which could
    hide a workable partner. Now they do not count; a few (max 3) are still shown as
    rejected so the reason stays visible.

New tests: tests/test_review_fixes.py, tests/test_explanation_guard.py,
app/tests/test_experiment_rules.py. One existing test line changed
(tests/test_explanation.py, empty text now gives the format note).

Frontend note: two new error codes, constraint_violation (422) and duplicate_experiment
(409), plus plan_outdated (422) on POST /rescue/plans/{id}/strategies/{rank}/experiment.
Show the `message` field.

Known limits: the stricter guard discards more LLM texts (a model that writes bare digits
loses its text); campaign costs are placeholders; ranking weights are starting guesses.


## Follow-up hardening

After a second review, four remaining bypasses were closed without changing
`economics_service.py`, `constraints_service.py`, `ranking_service.py` or
`schemas/rescue.py`:

1. `services/experiment_guard.py`: bundle/reposition/promotion experiments now fail with
   `constraint_violation` when the price is missing. The `other` strategy remains exempt.
   Regression tests cover both create and edit, including preserving the saved proposal
   after a failed edit.
2. `services/entity_resolution_service.py`: `confirmed` and `rejected` Qloo mappings are
   final even through direct `force=true` resolution. Repeating the same decision is
   idempotent; attempting to switch a decision returns `invalid_state` (409).
3. `agent/explanation.py`: Qloo/cultural explanations are allowed only when the strategy
   itself has an actual Qloo-related entity and a stored `qloo_evidence:<id>` provenance
   reference. A strong or ambiguous resolution status alone is not enough; missing or
   empty Insights results do not unlock cultural claims.
4. `agent/explanation.py`: spelled-out `zero`, `one`, and ordinal number words are also
   rejected by the numeric guard.

Regression tests for these cases were added to `app/tests/test_experiment_rules.py`,
`app/tests/test_experiments_api.py` and `tests/test_explanation_guard.py`. The complete
backend suite currently reports 456 passing tests. No live Qloo or hosted end-to-end test
is implied by this automated test result.
