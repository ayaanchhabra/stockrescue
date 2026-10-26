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

### T07 — Missing sales history

**Input:** An inventory product with unknown recent sales.

**Expected result:**
- Missing history remains unknown rather than becoming zero.
- The application does not infer that the product is unpopular solely
  because sales data is missing.
- The dashboard indicates that its sales assessment is limited.

### T08 — Qloo request timeout

**Input:** A Qloo request that times out or fails.

**Expected result:**
- The failure is handled gracefully.
- The application avoids exposing stack traces or secrets.
- A failed request is not represented as a successful Qloo result.

### T09 — Invalid CSV rows

**Input:** A CSV containing malformed or invalid inventory rows.

**Expected result:**
- Validation errors identify the affected row, field, and reason.
- Invalid data is not silently accepted.
- The import is rejected as a whole if any row is invalid.
- Preview does not modify persisted inventory.

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
