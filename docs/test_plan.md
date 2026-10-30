# StockRescue End-to-End Test Plan

**Status:** Partially executed — automated test baseline and health smoke test recorded; T01–T10 not yet individually executed

## 1. Purpose

Verify that StockRescue handles inventory data, Qloo results,
commercial constraints, API failures, and experiment outcomes correctly.

## 2. Test cases

### T01 — Valid Qloo entity match

**Input:** A bookstore product with a verified Qloo entity match.

**Expected result:**
- The correct matched entity is displayed.
- The returned entity ID and relevant metadata are preserved.
- The application distinguishes verified evidence from generated explanations.

### T02 — Ambiguous entity match

**Input:** A product whose name returns multiple plausible Qloo matches.

**Expected result:**
- The application does not blindly select the first result.
- Ambiguity is disclosed.
- The retailer can verify or select an appropriate candidate.

### T03 — No Qloo match

**Input:** A product for which no suitable Qloo entity is found.

**Expected result:**
- The missing match is disclosed.
- The application remains usable.
- No Qloo entity ID or cultural evidence is fabricated.

### T04 — No useful Insights results

**Input:** A successfully resolved entity with no useful returned Insights.

**Expected result:**
- Empty or insufficient evidence is handled gracefully.
- No cultural relationships or affinity scores are invented.
- Unsupported Qloo-based recommendations are not presented as verified.

### T05 — Bundle fails margin constraints

**Input:** A proposed bundle that violates the retailer's minimum margin.

**Expected result:**
- Deterministic backend code rejects the infeasible proposal.
- The violated constraint is communicated clearly.
- The LLM cannot override the constraint.

### T06 — Insufficient inventory for a bundle

**Input:** A proposed bundle requiring more units than are available.

**Expected result:**
- The infeasible bundle is rejected.
- The application does not claim unavailable stock can be supplied.
- Other feasible strategies may still be considered.

### T07 — Slow-moving rules and insufficient sales data

**Input:** Inventory products representing missing sales and stock-age data,
zero sales over 30 days, stock aged at least 90 days, positive sales with
stock cover above 180 days, and products too new to assess against a longer
sales window.

**Expected result:**
- If sales data and `days_in_stock` are both missing, the dashboard shows
  "Not enough data to assess"; missing sales are not treated as zero.
- No recent sales is flagged when `units_sold_30d` is 0 and
  `days_in_stock` is at least 30 or unknown.
- Aged stock is flagged when `days_in_stock` is at least 90.
- Low sales velocity is flagged when `units_sold_30d` is above 0 and
  stock cover exceeds 180 days.
- A product needs attention when at least one applicable rule fires.
- A product too new for a sales window is not judged using that window.
- The dashboard displays the rule and supporting values, and ranks flagged
  products by `quantity_in_stock * unit_cost`, highest first.
- Default thresholds are presented as configurable team choices, not
  industry facts.

**Automated coverage note (2026-10-28):** The inventory metrics unit
tests and the dashboard API regression test cover the implemented rules
for missing sales and stock-age data, zero recent sales, aged stock,
stock cover above 180 days, products too new for the 30-day sales window,
inventory-cost ranking, rule counts, thresholds, and supporting explanations.

The dashboard API regression test passed. The full T07 end-to-end scenario
remains unverified; this automated coverage does not establish that the
complete application flow has passed.

### T08 — Qloo request timeout

**Input:** A Qloo request that times out or fails.

**Expected result:**
- The failure is handled gracefully.
- The application avoids exposing stack traces or secrets.
- A failed request is not represented as a successful Qloo result.

### T09 — CSV preview, import validation, and duplicate handling

**Input:** A CSV containing valid rows, invalid rows, a repeated
`product_id`, and an SKU that already exists for the same retailer.
Run separate subcases for file-level errors and transaction failure.

**Expected result:**
- Preview does not modify persisted inventory.
- Preview labels valid rows as `new` or `will update`.
- Duplicate `product_id` occurrences are reported with row numbers. The
  first valid occurrence may be imported; subsequent duplicate occurrences
  are skipped and reported.
- An existing SKU is updated without replacing its Product row or changing
  its internal `Product.id`.
- Row-level validation failures skip those rows while valid rows can import.
- Each skipped row reports its row number, field, invalid value, readable
  reason, and suggested correction.
- Missing required columns, unsupported file type, files over 2 MB, or more
  than 2,000 rows reject the whole upload.
- Valid changes are committed in one database transaction; an induced
  transaction failure leaves no partially imported file.
- Optional blank-cell updates follow the implemented rules documented
  in `docs/inventory_data_contract.md` and `docs/business_rules.md`.
- For new products, blank optional cells become `NULL`.
- For existing products, ordinary blank optional cells preserve current
  values, while non-blank optional cells update them.
- If any of the four sales-snapshot fields is supplied, all four fields
  are replaced together; blank fields within that group become `NULL`.
  If all four are blank, the existing snapshot is preserved.

**Implementation alignment note:** The current row-issue response includes
`row_number`, `field`, `value`, `message`, and `severity`. It does not
currently expose a separate `suggested_correction` field. Confirm with
Person 3 whether the message satisfies the frontend requirement or whether
the response contract needs an additional field. Do not mark T09 as passed
until the required behavior has been verified.

### T10 — Successful experiment outcome submission

**Input:** An approved experiment with valid outcome data.

**Expected result:**
- The outcome is saved and linked to the correct experiment.
- Actual sales and financial metrics are calculated consistently.
- Comparisons use an appropriate baseline when available.
- Before-and-after differences are not presented as proof of causation.

## 3. Test execution record

For every test, record:

- Test case ID
- Test data and preconditions
- Steps performed
- Expected result
- Actual result
- Status: Not run, Pass, or Fail
- Evidence: test output, API response, screenshot, or log
- Related issue or blocker

## 4. Testing principles

- Do not mark tests as passed until they have actually been executed.
- Use mocks for isolated tests and clearly label mocked responses.
- Verify real Qloo behavior separately from mocked behavior.
- Test financial calculations and hard constraints independently of
  the LLM.
- Never fabricate sales history, Qloo evidence, or measured outcomes.
- Report defects and blockers to the relevant teammate.

## 5. Completion criteria

The test plan is complete when all ten scenarios have been executed,
their results recorded, critical failures addressed, and supporting
evidence retained.

The test plan itself does not establish that any scenario has passed.

## 6. Automated Backend Test Baseline

**Date:** 2026-10-26

**Command:** `python -m pytest` (run from `backend/`)

**Environment:** Python 3.14.6, pytest 9.1.1, isolated `.venv`.

**Result:** 202 passed, 0 failed, 1 warning.

**Warning:** Starlette reports that using `httpx` with its current
`TestClient` is deprecated and recommends `httpx2`. The warning did not
cause test failures; dependency compatibility should be reviewed separately.

**Scope limitation:** This run covers the existing automated test suite.
It does not establish that the ten end-to-end scenarios in Section 2
have passed. Those scenarios remain unverified until individually executed
and documented with their results and evidence.

## 7. Manual Health Endpoint Smoke Test

**Date:** 2026-10-26

**Command:** `python -m uvicorn app.main:app --reload` from `backend/`,
followed by `curl -i http://127.0.0.1:8000/health`.

**Result:** PASS — application startup completed and the health endpoint
returned HTTP 200 OK.

**Observed response:** `{"status":"ok","qloo_key_configured":false}`

**Scope limitation:** This verifies local application startup and the
health route only. It does not verify live Qloo connectivity or other API
routes. The ten end-to-end scenarios in Section 2 remain individually
unverified.


## 8. Automated Backend Test Run — 2026-10-27

**Date:** 2026-10-27

**Command:** `python -m pytest` (run from `backend/`)

**Environment:** Python 3.14.6, pytest 9.1.1, isolated `.venv`.

**Result:** 244 passed, 0 failed, 1 warning in 0.25 seconds.

**Coverage added since the earlier 202-test baseline:** Seven inventory
import tests and six inventory API tests cover import behavior, updates,
duplicate handling, transaction rollback, CSV preview/import routes, and
dashboard responses.

**Warning:** Starlette reports that using `httpx` with its current
`TestClient` is deprecated and recommends `httpx2`. This did not cause test
failures; dependency compatibility should be reviewed separately.

**Scope limitation:** This is an automated backend test run. It does not
establish that the ten end-to-end scenarios in Section 2 have passed.
Those scenarios remain unverified until individually executed and recorded
with their results and evidence.

## 9. Latest Automated Backend Test Run — 2026-10-28

**Command:** `python -m pytest` (run from `backend/`)

**Environment:** Python 3.14.6, pytest 9.1.1, isolated `.venv`.

**Result:** 245 passed, 0 failed, 1 warning in 0.26 seconds.

**New coverage:** One dashboard API regression test verifies serialized
results for missing sales and stock-age data, zero recent sales, aged stock,
stock cover above 180 days, products too new for the sales window, inventory
cost ranking, thresholds, rule counts, and supporting explanations.

**Warning:** Starlette reports that using `httpx` with its current
`TestClient` is deprecated and recommends `httpx2`. The warning did not
cause test failures; dependency compatibility should be reviewed separately.

**Scope limitation:** This run covers the automated backend test suite.
It does not establish that all ten end-to-end scenarios in Section 2 have
passed. Those scenarios remain unverified until individually executed and
recorded with actual results and evidence.

## 10. Integrated Backend Test Run — 2026-10-28

Command: python -m pytest (run from backend/).

Environment: Python 3.14.6; pytest 9.1.1.

Result: 381 passed, 0 failed, 1 warning in 0.49 seconds (latest rerun; the earlier run completed in 0.57 seconds).

Scope: Full backend test suite after syncing and merging the updated remote branch, including inventory tests and integrated rescue/explanation API tests.

Warning: One Starlette deprecation warning related to httpx usage in starlette.testclient. It did not cause test failure.

End-to-end status: The automated backend suite passed, but scenarios T01–T10 in this plan have not all been manually executed end-to-end. Do not mark those manual scenarios as passed based solely on this run.

## 11. T09 API Regression Test Run — 2026-10-28

Local command: python -m pytest (run from backend/).

Environment: Python 3.14.6; pytest 9.1.1.

Result: 382 passed, 0 failed, 1 warning in 0.94 seconds.

Coverage added: The inventory import API test now verifies row-level validation error details, including row number, field, invalid value, severity, and readable message. A new duplicate-SKU API test verifies that the first row is retained, the later duplicate is skipped, and the duplicate error includes the expected row and field details.

CI: GitHub Actions Backend tests run 40739195828 succeeded after commit 2860476 was pushed.

Warning: One Starlette deprecation warning related to httpx usage in starlette.testclient. It did not cause test failure.

T09 status: These automated API regression checks passed. The complete T09 end-to-end scenario remains unverified. The separate suggested_correction field requirement also remains pending confirmation from Person 3.

## 12. Evaluation Regression Test Run — 2026-10-29

Focused command after the latest Case 11 adjustment: `python -m pytest tests/test_evaluation_cases.py -q` (run from `backend/`).

Focused result: **11 passed, 0 failed in 0.08 seconds.**

Full-suite command after the latest test edits: `python -m pytest` (run from `backend/`).

Full-suite result: **384 passed, 0 failed, 1 warning in 0.54 seconds.**

Coverage:
- Case 10 records the current behavior for a target with fewer than three units in stock: no feasible strategies are returned.
- Case 11 checks that a bundle can pass when its combined margin satisfies the minimum floor, even if the target product's standalone margin is below that floor. Promotion remains rejected for the tested setup.

Business-rule confirmations from Person 2:
- The current `test_units` default is 3. This is a team default, not a permanent measured requirement.
- A bundle is evaluated using its combined selling price and combined cost. The strictest applicable per-product margin floor and discount cap still apply.

Pending integration from Person 2's `fix/margin-floor-and-stock-rule` branch:
- A below-floor but profitable target should be eligible for normal-price display with a warning in the strategy risks.
- Promotion remains rejected when it violates applicable constraints.
- A target priced at or below cost should receive no strategy.
- After the fix merges, strengthen the low-stock test to assert the stable `INSUFFICIENT_STOCK` code, not message text, and add regression coverage for the display warning.

Warning on the most recent full-suite run: One Starlette deprecation warning involving `httpx` and `starlette.testclient`. It did not cause test failure.

End-to-end status: These are automated backend test results. They do not establish that manual scenarios T01–T10 have all passed end-to-end.
