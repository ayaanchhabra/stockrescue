# Person 2 — Calculations & recommendation logic work log

Date: 2026-10-30

## Task 04 — Experiment quantity and calculation consistency

- Outcomes now use a persisted product snapshot containing each allowed product's database ID, SKU, unit cost, selling price and starting stock; the snapshot is refreshed when an approved experiment starts.
- Outcome SKUs must exactly match the experiment products. Duplicate, unrelated, missing, or over-stock rows are rejected. Bundle component sales quantities must agree.
- Target units sold and remaining stock are derived from the target SKU's sale row and saved stock. Conflicting optional client assertions are rejected. Outcome duration must match the saved inclusive date range.
- Client-supplied unit costs are ignored; stored outcome input rows are normalized to server-sourced snapshot costs. Simulated/observed separation remains intact.

## Task 05 — Financial precision and margin rounding

- Hard margin, discount and campaign-budget decisions use `Decimal` values derived from source values, not rounded display metrics.
- Display metrics remain rounded. Promotion discount caps are rounded down to a safe two-decimal percentage.
- Added near-boundary regression coverage, including a 14.996% margin that displays as 15.00% but must fail a 15% floor.

## Task 06 — Unsupported `other` strategy

- Removed `other` from the experiment API strategy enum. API callers receive validation 422.
- Service-level and candidate constraint guards fail closed for unknown values. Bundles require at least one partner; non-bundle actions cannot carry partners.

## Task 07 — Plan/product/evidence integrity

- Experiment creation verifies plan target, plan retailer, selected strategy type/name/target, exact bundle partner set, plan membership and evidence references.
- Qloo evidence IDs must correspond to the selected strategy, exist in the database, be attached to the plan and belong to the experiment target product. No evidence can be attached to a planless direct experiment.
- Invalid relationships fail with 422 before an experiment row is committed.

## Task 10 — Live Qloo connectivity

- Added/updated `backend/qloo_smoke_test.py` to make a sanitized live `/search` check and two cross-category Insights checks (movie and artist). It prints no API key, headers, raw payload or secret-bearing URL.
- Attempted the live check from this execution environment using the configured key from the uploaded archive, held only in process memory. It failed before an HTTP response with `ConnectError` (outbound network connection unavailable here). Therefore current live connectivity and current credential validity remain UNVERIFIED in this environment.
- The repository records a previous successful live check dated 2026-10-26; that historical record is not represented as a fresh verification. Re-run the smoke test from the team's network-enabled machine and save the sanitized result.

## Task 11 — Cross-category cultural discovery

- The main Qloo gateway now makes a bounded allowlisted set of Insights requests for books, movies, artists, TV shows and video games.
- Each returned related entity carries its actual entity type, nullable Qloo affinity and response-evidence reference. Affinity is not conflated with internal match similarity or ranking scores.
- Category failures are recorded while successful category results remain usable; all-category failure still surfaces a Qloo error. Bundle eligibility remains tied to matched, actually stocked inventory.
- The allowlist was checked against Qloo's current public Insights API reference; do not assume an arbitrary `filter.type` is supported.

## Verification

- `cd backend && python -m pytest -q` — **468 passed**.
- Live `python qloo_smoke_test.py` — attempted; **not verified** because this environment returned `ConnectError` before an HTTP response.
- `python -m compileall -q backend/app` — passed.
- `python -m py_compile backend/qloo_smoke_test.py` — passed.
