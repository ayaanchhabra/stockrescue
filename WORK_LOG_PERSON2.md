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

# Person 2 — Phase 1 / Phase 2 follow-on work log

Date: 2026-10-30

## Phase 1 — P0-26: RescuePlan persistence failure

- Changed `POST /rescue/{product_pk}` so a plan persistence exception triggers rollback and returns HTTP 503 `plan_persistence_failed`.
- The failure response intentionally contains neither an unsaved RescuePlan nor `X-Rescue-Plan-Id`; downstream experiment creation therefore cannot treat the response as a saved plan.
- Added a regression test that forces persistence failure and checks the safe 503 response.

## Phase 1 — P0-25: Event-approved Qloo access verification

- Replaced the previous direct-HTTP smoke check with a CLI-based smoke-test script for the event-supported `qloo api` surface. It reports only sanitized status/metadata and does not print credentials, headers or raw provider responses.
- **Not fully complete / live verification outstanding.** The runtime `qloo_service` still uses its Python HTTP transport; this archive does not claim that transport is event-approved. The official harness CLI is not installed in this environment, there is no configured event key, and the installed Node runtime is v22.16.0 (below the event kit's stated v22.19.0 minimum). Running the smoke test returned `BLOCKED: qloo CLI not found`. Before representing live Qloo as verified, install the supported harness, configure an individually attributable event credential, obtain organizer approval for the backend's current transport or migrate it to the harness, and capture a successful live response.

## Phase 2 — P1-13: Alembic migrations

- Added `alembic.ini`, the migration environment/template and an initial migration for the current database schema.
- Initial migration includes the idempotency table and the partial unique index for active plan/strategy experiments.
- Added a safe bootstrap path for complete legacy `create_all()` databases, preserving existing rows while adding the migration-era schema elements. Partial legacy schemas fail clearly rather than being guessed at.
- Removed implicit production schema creation from application startup and from `seed_dev.py`.
- Added fresh-database and legacy-database migration integration tests.

## Phase 2 — P1-30: Transactional persistence

- Added a shared `commit_or_rollback()` helper and applied it to plan writes, Qloo mapping/evidence writes, experiment lifecycle changes and outcomes.
- Evidence creation + mapping update, experiment creation + idempotency record, and outcome creation + experiment completion now share transaction boundaries.
- Removed unnecessary post-commit refresh queries from these paths to avoid a secondary read error after a successful commit.

## Phase 2 — P1-33: Idempotency and database uniqueness

- Added `idempotency_records` with unique `(retailer_id, idempotency_key)`.
- `POST /experiments` and create-from-saved-strategy accept an optional `Idempotency-Key` header.
- Same key + same request returns the original experiment (HTTP 200); same key + different request returns HTTP 409 `idempotency_conflict`.
- Experiment and idempotency record are saved atomically. A partial unique index also blocks concurrent duplicate active experiments for the same plan/target/title/strategy, while allowing rejected/cancelled records to be retried.
- Added tests for replay, mismatched key reuse and rollback after simulated commit failure.

## Phase 2 — P1-31: Readiness checks

- `/health` is liveness only.
- `/ready` checks database connectivity, required tables and whether the current Alembic revision matches the configured migration head. It returns HTTP 503 when any check fails and does not call Qloo.
- Updated README and API contract documentation.

## Verification

- `cd backend && PYTHONPATH=. python -m pytest -q` — **478 passed**.
- `python -m compileall -q backend/app` — passed.
- `python -m py_compile backend/qloo_smoke_test.py` — passed.
- Fresh SQLite database: `alembic upgrade head` — passed; `alembic current` — `27c4190e336d (head)`; `alembic check` — `No new upgrade operations detected`.
- Legacy database migration preservation and schema check — covered by passing migration integration test.
- Live Qloo harness smoke test — blocked because `qloo` CLI is unavailable; no live response claimed.
