# StockRescue End-to-End Test Plan

**Status:** Planned — tests not yet executed

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
- Optional blank-cell updates follow the final agreed rule in
  `docs/business_rules.md`. The sales-snapshot exception remains pending
  Person 1 and Person 2's clarification.

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
