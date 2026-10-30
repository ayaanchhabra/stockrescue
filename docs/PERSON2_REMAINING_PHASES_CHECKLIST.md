# StockRescue — Person 2 Remaining Phases Checklist

**Audit basis:** `stockrescue(2).zip` uploaded on 30 October 2026  
**Owner:** Person 2 — all remaining engineering outside Person 1's six assigned security/inventory-protection tasks  
**Status rule:** A task is marked implemented only where the current source and/or automated tests support that status. A passing unit test is not treated as live integration, PostgreSQL, deployment, or manual end-to-end proof.

---

## 1. Current repository audit

### 1.1 Verification performed on this archive

| Check | Result |
|---|---|
| Backend test suite | **486 passed, 0 failed** (`PYTHONPATH=. python -m pytest -q`, from `backend/`) |
| Python compilation | Passed (`PYTHONPATH=. python -m compileall -q app`) |
| Alembic integration tests | Included in the passing backend suite; tests cover fresh SQLite migration and adoption of a legacy SQLite database |
| Frontend build/lint/type-check | **Not run** — `frontend/node_modules` is absent; package scripts do not include a type-check or frontend-test script |
| Live Qloo harness test | **Not verified** — `qloo` CLI is absent; Node in this environment is 22.16.0 while the project smoke-test instructions require Node 22.19.0 or newer |
| PostgreSQL migration/concurrency | Not verified against a real PostgreSQL instance |
| Hosted deployment | Not evidenced in the ZIP |
| Manual T01–T10 end-to-end scenarios | `docs/test_plan.md` still says they have not all been individually executed |

### 1.2 What is now present in the repository

- A real Next.js/React/TypeScript frontend exists, with dashboard, inventory upload, rescue-plan and experiment pages. This is a working starting point, not a complete frontend product.
- Person 1's bearer-token authentication, retailer scoping, stock reservations, ISBN-assisted Qloo matching and evidence/provenance validation are merged into the current source.
- The Person 2 decision engine, financial checks, experiment outcome validation, plan/experiment relationship checks, cross-category Qloo gateway and nullable affinity pipeline are present.
- Alembic configuration and an initial migration exist. Migration tests pass on SQLite.
- An idempotency table, `Idempotency-Key` handling on `POST /experiments`, and a unique active-strategy index exist.
- `/health` and `/ready` exist.
- A 40-row synthetic sample CSV and sample-data notes exist.

### 1.3 Important gaps found in the actual source

These findings change the next-work order; they must not be carried forward as completed merely because an earlier handoff document said so.

1. **Migration startup is not fully migrated:** `backend/app/main.py` still calls `Base.metadata.create_all()` and performs manual `ALTER TABLE` compatibility changes in the application lifespan. This contradicts `docs/PHASE1_PHASE2_HANDOFF.md` and `WORK_LOG_PERSON2.md`, which say production startup no longer mutates schema.
2. **Transaction helper claim is not reflected in code:** the handoff mentions `commit_or_rollback()`, but no such helper is present under `backend/app`. Services and adapters still contain direct `db.commit()` calls. Some individual operations are atomic, but all transaction boundaries and rollback cases still need to be reconciled and tested.
3. **Strategy-route idempotency is incomplete:** `POST /experiments` accepts `Idempotency-Key`, but `POST /rescue/plans/{plan_id}/strategies/{rank}/experiment` does not currently accept/pass that header, despite the work log saying it does.
4. **Refresh flag is not honoured for unverified mappings:** `entity_resolution_service.resolve_product(..., force=False)` returns early only for human-confirmed/rejected mappings. An existing unverified mapping is resolved again even when `force=False`.
5. **Retailer settings are not persisted:** `Constraints`, `RankingSettings`, `MatchSettings` and `StrategySettings` remain code defaults/dataclasses. There is no persisted retailer-settings model. Agent tools still use `DEFAULT_CONSTRAINTS` in at least the business-constraint tool path.
6. **Product CRUD endpoints are absent:** the inventory API currently exposes CSV preview/import and dashboard routes, not the general product list/detail/create/edit APIs.
7. **Dashboard aggregates are incomplete:** total stock units and potential retail value are absent from `InventoryDashboard`.
8. **Sales history is still a latest snapshot:** the `Product` row stores current 30/60/90-day values; there is no dated sales-snapshot history table.
9. **Experiment control metadata is incomplete:** outcomes contain control measurements but do not identify the control SKU/period and its baseline/test dates. There is no explicit early-stop reason/workflow.
10. **The agent is still deterministic orchestration:** tools are registered and called by the fixed workflow; the LLM does not choose tools. Tool validation is a custom broad JSON-type validator, not a strict semantic Pydantic contract.
11. **Frontend/backend authentication is not integrated:** `frontend/lib/api.ts` calls the backend directly and does not send an Authorization header or use a server-side session/proxy. Backend middleware requires bearer authentication on protected routes. Coordinate the secure session/token mechanism with Person 1; never place a retailer token in a `NEXT_PUBLIC_*` variable or browser bundle.
12. **Documentation is stale/incomplete:** the root README links to `docs/merge_resolution_2026-10-30.md`, which is not present in this archive. `frontend/README.md` is generic Next.js starter documentation. `docs/test_plan.md` has an older 384-test baseline and says T01–T10 are not complete.
13. **The uploaded archive is not a safe release archive:** it contains `.git`, `backend/.env`, `backend/stockrescue.db`, and `backend/.venv`. Use the release packaging script or exclude these items before sharing. Person 1 owns secrets/key handling; rotate credentials if the original archive was shared outside the trusted team.

---

## 2. Ownership boundary

### Person 1 — not your implementation workload

The following six responsibilities remain Person 1's ownership. Their source code is integrated in this archive, but production/deployment verification still has to be done jointly.

- API keys and secret management.
- API authorization and protected endpoints.
- Retailer/tenant isolation.
- Competing experiment stock reservations.
- Qloo entity-matching accuracy and human identity decisions.
- Evidence authenticity and provenance validation.

**Your integration responsibilities:** call the protected APIs correctly, consume the authenticated retailer context supplied by Person 1, preserve the agreed evidence contract, and include Person 1's work in the full acceptance tests. Do not build a second auth system, tenant system, reservation system or entity-matching algorithm.

### Person 2 — your ownership

Database/migration integration, transactions and idempotency, financial calculations and settings, experiment measurement, inventory CRUD/dashboard, Qloo transport reliability and decision-engine integration, agent hardening, frontend feature completion, testing, demo data, API contracts, documentation and deployment integration.

---

## 3. Already implemented — keep regression tests

These are not new feature assignments. Keep their existing tests and re-check them when related contracts change.

- [x] Experiment outcome quantities derive from the saved experiment's product/SKU snapshot; duplicate, missing, unrelated and over-stock sales rows are rejected.
- [x] Bundle component unit quantities are checked for consistency.
- [x] Target units sold and remaining stock do not use conflicting client-supplied sources of truth.
- [x] Client-provided unit cost does not drive outcome accounting; the saved snapshot is used.
- [x] `other` is not an accepted experiment strategy; unknown strategy types fail closed.
- [x] Hard margin/discount/budget checks use unrounded calculation values; display values may be rounded.
- [x] Plan, target product, strategy, bundle partners and Qloo evidence relationships are validated when creating experiments.
- [x] Rescue-plan persistence failure does not return an unsaved plan or `X-Rescue-Plan-Id`.
- [x] Cross-category Insights requests are made for the configured book/movie/artist/TV/video-game set, with per-category failures recorded.
- [x] Qloo affinity is carried through the parser, adapter, strategy/evidence output and tools when Qloo actually returns it; missing affinity remains null.
- [x] Qloo cache has a maximum size and expiry cleanup; retries and typed provider errors are present.
- [x] Initial Alembic migration and SQLite migration tests exist.
- [x] Idempotency is available on the direct `POST /experiments` route.
- [x] `/health` and `/ready` routes exist.
- [x] Person 1's authentication, tenant scoping, reservation, improved entity matching and provenance checks are integrated in source.
- [x] Basic Next.js dashboard, CSV upload, rescue-plan display and experiment lifecycle/outcome pages exist.

**Important status note:** P0-26 is implemented with HTTP **500** in the current code and regression test. Earlier handoff text says HTTP 503. Keep the actual response contract and all docs/tests consistent; do not describe it as 503 unless the code and tests are deliberately changed together.

---

# Phase 0 — Close the remaining P0 integration gate

## P0-25 — Verify event-authorized, live Qloo access

**Status: Outstanding.** A harness-based smoke-test script exists, but no successful live result is recorded in this execution environment. The runtime Qloo client still uses direct Python `httpx` requests with `X-Api-Key`; the project notes say this transport has not yet been confirmed as the event-approved access method.

- [ ] Install the event-supported Qloo harness/CLI at the minimum version documented by the team/event guide.
- [ ] Upgrade Node to the required supported version (the archive smoke-test instructions specify 22.19.0 or newer).
- [ ] Configure an individually attributable event credential without committing it or placing it in frontend code.
- [ ] Check the event's exact approved access route and quota/rate-limit rules.
- [ ] Obtain confirmation that the backend's direct HTTP transport is permitted, or migrate the runtime client to the approved harness/access method.
- [ ] Run the repository's `backend/qloo_smoke_test.py` from a network-enabled machine.
- [ ] Capture a successful live book search.
- [ ] Capture successful live movie Insights.
- [ ] Capture successful live artist Insights.
- [ ] Record sanitized result counts, status, endpoint/method and test date; do not save keys, headers or unfiltered raw payloads in logs.
- [ ] Keep mock tests separate from this live verification.

**Acceptance:** A reproducible successful live search and cross-category Insights check using the event-authorized access method, with the runtime backend transport's approval documented.

## P0-26 — RescuePlan persistence failure

**Status: Implemented; contract/documentation consistency check remains.**

- [x] Roll back when plan persistence fails.
- [x] Return an explicit error instead of a successful-looking unsaved plan.
- [x] Omit the plan ID header when persistence fails.
- [x] Regression test forces persistence failure.
- [ ] Make every handoff/API document agree with the actual HTTP 500 response and error code `plan_persistence_failed`.
- [ ] Verify the frontend treats this as a failure and never enables experiment creation without a saved plan ID.

---

# Phase 1 — Reconcile database foundation, transactions and idempotency

**Do this before adding more persistent settings/history models.** The schema migration work exists, but the current app startup still mutates the schema.

## P1-13 — Finish Alembic-only schema evolution

- [x] Alembic configuration, environment and initial migration exist.
- [x] Fresh SQLite upgrade test exists.
- [x] Legacy SQLite database adoption/data-preservation test exists.
- [x] SQLite `alembic check` is part of the migration test.
- [ ] Remove `Base.metadata.create_all()` from the FastAPI production lifespan.
- [ ] Remove the runtime `ALTER TABLE` patches for `isbn13` and `product_snapshot` from `main.py`.
- [ ] Make `alembic upgrade head` an explicit deployment/startup release step.
- [ ] Keep schema bootstrap confined to isolated tests or an explicit one-time migration command.
- [ ] Define and test the supported upgrade path for each actual legacy schema version; do not silently stamp an unknown/partial schema.
- [ ] Add migration tests for the new future settings and sales-history tables before merging those model changes.
- [ ] Test upgrade and downgrade behaviour where downgrade is supported.
- [ ] Test PostgreSQL specifically: JSON columns, partial unique index, foreign keys, check constraints and transaction behaviour.
- [ ] Back up the deployed DB before applying migrations.
- [ ] Update README and deployment configuration so production never relies on `create_all()`.

**Acceptance:** A clean database and each supported legacy database reach Alembic head without losing data; app startup does not mutate schema; PostgreSQL migration is verified.

## P1-30 — Make transaction boundaries truthful and complete

**Status: Partial.** Some business operations already group writes, but the work log claims a shared `commit_or_rollback()` helper that is not present in the current source; direct commits remain in services/adapters.

- [ ] Inventory every `db.commit()`, `db.flush()` and `db.rollback()` in API/service/adapter code.
- [ ] Define one transaction owner per business operation; avoid nested service functions committing a caller-owned session unexpectedly.
- [ ] Add a shared transaction helper only if it clarifies ownership; otherwise use explicit `try/except/rollback` consistently.
- [ ] Keep Qloo resolution evidence + mapping update atomic.
- [ ] Define the intended persistence boundary for cross-category Insights evidence (one evidence row per category is acceptable only if orphan/partial-result semantics are explicit).
- [ ] Keep plan record + evidence ID list + plan JSON consistent.
- [ ] Ensure experiment + idempotency record commit atomically.
- [ ] Ensure outcome + experiment completion + stock reservation release commit atomically.
- [ ] Ensure approve/start + reservation rows + status transition commit atomically.
- [ ] Ensure CSV import rolls back the entire file-level write transaction on database failure.
- [ ] Add failpoint tests for failure between each multi-write stage.
- [ ] Test rollback leaves no partial experiment, outcome, reservation or plan record.
- [ ] Update `WORK_LOG_PERSON2.md` so it describes the code that actually exists.

**Acceptance:** Each multi-row business operation either persists a coherent result or rolls back; failure tests prove no misleading or partial state.

## P1-31 — Complete readiness checks and deployment integration

- [x] `/health` provides lightweight liveness.
- [x] `/ready` checks database connection and migration head.
- [ ] Include every required current table in readiness validation, including `experiment_stock_reservations`.
- [ ] Return a safe structured status if the Alembic version table is missing/unreadable.
- [ ] Decide whether `/ready` is authenticated or reachable only through an internal deployment check; document and configure the host accordingly (it currently passes through bearer-auth middleware).
- [ ] Verify database URL and schema readiness in the actual hosting environment.
- [ ] Ensure readiness does not call Qloo or spend provider quota.
- [ ] Add API tests for database unavailable, missing table, unversioned DB and migration-behind-head cases.

**Acceptance:** The operator can distinguish process liveness from database/schema readiness; the deployment health checker can use the endpoint safely.

## P1-33 — Finish idempotency for all experiment-creation entry points

- [x] `idempotency_records` table and unique `(retailer_id, idempotency_key)` exist.
- [x] Direct `POST /experiments` accepts `Idempotency-Key`.
- [x] Same key/same body can replay the original experiment.
- [x] Database uniqueness prevents duplicate active plan/strategy records.
- [ ] Add `Idempotency-Key` to `POST /rescue/plans/{plan_id}/strategies/{rank}/experiment` and pass it through to the service.
- [ ] Make same-key/same-body replay and same-key/different-body conflict behaviour identical on both creation paths.
- [ ] Return a stable `idempotency_conflict` error code (not a generic `invalid_state`) for key reuse with a different request body.
- [ ] Add concurrent request tests for both routes.
- [ ] Add a test for a failed creation followed by a retry with the same key.
- [ ] Document key scope, retention and expiry policy.
- [ ] Ensure idempotency records are tenant-scoped using Person 1's authenticated retailer context.

**Acceptance:** Retry/double-submit/concurrent calls cannot create duplicate experiments on either API path, and errors are stable and documented.

---

# Phase 2 — Persist commercial settings and finish financial/experiment measurement

## P1-10 + P1-26 — One persistent retailer settings system

**Status: Not implemented as a persisted settings feature.** Current constraints/ranking/strategy settings are largely code defaults; the agent constraint tool still uses `DEFAULT_CONSTRAINTS`.

- [ ] Define a retailer settings model/table and Pydantic input/output schemas.
- [ ] Persist minimum gross margin.
- [ ] Persist maximum discount.
- [ ] Persist campaign budget.
- [ ] Persist restricted product SKUs/IDs.
- [ ] Persist no-sales/aged-stock/low-velocity thresholds.
- [ ] Persist minimum stock and planned test units.
- [ ] Persist test duration/baseline duration.
- [ ] Persist strategy costs (bundle, reposition, promotion) and identify placeholder estimates.
- [ ] Persist recommendation ranking weights and `discount_last` policy.
- [ ] Validate numeric ranges, weight totals, duplicate/restricted identifiers and unknown fields.
- [ ] Define explicit defaults for a new retailer and document they are team defaults, not industry facts.
- [ ] Add a single `EffectiveRetailerSettings` loader/contract.
- [ ] Pass the same settings through rescue generation, candidate generation, hard constraints, ranking, agent tools, experiment create/edit/approve/start and dashboard thresholds.
- [ ] Remove helper-tool paths that silently use `DEFAULT_CONSTRAINTS` when retailer settings are available.
- [ ] Save the effective settings snapshot with every rescue plan.
- [ ] Save the effective settings snapshot with every experiment.
- [ ] Revalidate a saved plan using its saved rules plus current live inventory, according to a documented policy.
- [ ] Add tests proving API and agent tool paths make identical decisions for identical inputs/settings.
- [ ] Add Alembic migration and rollback/upgrade tests for settings storage.

**Acceptance:** Each retailer has persisted, validated settings, and every entry point uses the same effective settings contract and records the snapshot used.

## P1-34 — Complete historical price/cost accounting

**Status: Mostly implemented.** Experiment snapshots already contain product IDs, SKUs, cost, selling price and stock, and are refreshed at start. Outcome calculations use saved snapshot costs. Remaining work is about the lifecycle/adjustment policy and tests.

- [x] Save target and bundle product accounting snapshot.
- [x] Refresh snapshot at experiment start.
- [x] Use saved unit cost when calculating outcomes.
- [x] Store actual paid selling price separately in outcome inputs.
- [ ] Ensure plan/experiment snapshots also preserve the exact approved price and cost basis used for constraints.
- [ ] Define an audited correction mechanism if an experiment's actual cost basis changed after start; do not silently accept client cost.
- [ ] Record whether any cost correction was applied, by whom and why.
- [ ] Ensure price/cost changes through later CSV import do not rewrite historical plan/outcome records.
- [ ] Add regression test: change the product table after experiment completion and prove historical outcome totals remain unchanged.
- [ ] Document the accounting basis and operating-cost exclusions in API, UI and README.

**Acceptance:** Every historical experiment profit can be reproduced from its stored cost/price/stock snapshot and recorded actual sales.

## P1-35 — Establish currency and rounding policy end to end

**Status: Partial.** Hard constraint calculations use high precision/Decimal-derived values, but product/experiment database money fields are still Float and there is no first-class persisted currency field.

- [ ] Declare INR as the current supported currency for the demo.
- [ ] Add currency code to retailer settings or explicitly freeze it as a deployment-wide contract.
- [ ] Reject mixed-currency data.
- [ ] Decide whether database storage moves to integer paise or SQL `Numeric/Decimal`; document migration strategy.
- [ ] Migrate Product costs/prices and experiment monetary fields away from Float if the production accounting contract requires exact persistence.
- [ ] Keep Decimal/minor-unit arithmetic for margin, discount, budget, bundle price and gross profit.
- [ ] Define rounding policy for normal prices, bundle prices, discounts, gross profit and display values.
- [ ] Declare taxes/fees excluded or add the agreed accounting fields.
- [ ] Add paise-level boundary tests and serialization tests.
- [ ] Verify displayed values reconcile with stored integer/decimal values.

**Acceptance:** Stored monetary values and all commercial decisions follow one documented currency and rounding contract.

## P1-12 — Finish experiment time windows, baseline and control identity

**Status: Partial.** Date order and `actual_days` equality are validated. The control payload contains measurements only, without control identity/period metadata; early-stop handling is absent.

- [x] Validate `end_date >= start_date`.
- [x] Require outcome `actual_days` to equal the saved inclusive experiment date range.
- [x] Preserve baseline units/days as paired inputs.
- [ ] Decide whether future-dated starts are allowed; the current start action sets status to running immediately even with a future start date.
- [ ] Add a deliberate early-stop action/workflow.
- [ ] Require and persist early-stop reason and actual stop date.
- [ ] Persist baseline start/end dates.
- [ ] Persist actual intervention start/end dates.
- [ ] Extend control metadata with control SKU/product or control-period identity.
- [ ] Persist control baseline dates and comparison dates.
- [ ] Record why the control is considered comparable and whether it received no intervention.
- [ ] Calculate per-day rates when periods have different lengths.
- [ ] Prevent price changes and discounts from being double-subtracted.
- [ ] Show that before/after and control comparisons are not automatic causal proof.
- [ ] Add tests for date boundaries, future dates, early completion, mismatched control periods and different period lengths.

**Acceptance:** Every outcome identifies what was measured, over which dates, against which control (if any), and what conclusions are not justified.

## P1-36 — Add dated sales-history snapshots

**Status: Not implemented.** Current 30/60/90-day sales values are latest fields on `Product` and imports replace them; there is no dated snapshot history model.

- [ ] Add a `sales_snapshots` table or equivalent append-only model.
- [ ] Record retailer, product/SKU, import timestamp, source and the reported cumulative window values.
- [ ] Keep current inventory values separate from historical import snapshots.
- [ ] Preserve overlapping cumulative 30/60/90-day windows as overlapping windows.
- [ ] Do not subtract or sum overlapping cumulative values as independent sales.
- [ ] Define stale snapshot rules.
- [ ] Define what happens when a product first appears or is too new for a window.
- [ ] Keep manual experiment outcomes separate from inventory sales snapshots.
- [ ] Add migrations and tests for repeated imports and stale/missing records.
- [ ] Add an API/dashboard data contract that states the represented period.

**Acceptance:** The app can explain the date and period basis of each sales metric without inventing daily transactions.

## P1-41 — Finish CSV/API/experiment schema reconciliation

**Status: Partial.** CSV parsing/import is structured and transactional; identifier mapping, null semantics and sales-snapshot field grouping exist. CRUD and historical snapshots are still missing.

- [x] Validate required CSV fields and supported optional fields.
- [x] Reject duplicate SKU rows according to the documented import policy.
- [x] Import in one database transaction.
- [x] Preserve optional blank cells or replace sales-snapshot group with NULL according to the documented rules.
- [ ] Add a consistent validation service shared by CSV and manual product API.
- [ ] Implement explicit optional-field clearing for product PATCH.
- [ ] Keep `product_pk` (database PK) and `sku` (retailer ID) unambiguous everywhere.
- [ ] Add date, numeric, NaN/infinity and maximum-length validation at all public boundaries.
- [ ] Align API, CSV, tools, recommendation plans, experiments and outcomes to one product contract.
- [ ] Add the missing `suggested_correction` field if the frontend/test-plan contract still requires it, or formally revise the contract with Person 3.
- [ ] Add contract tests for null, blank, omitted and explicit-clear values.

**Acceptance:** CSV import, manual product APIs, agent tools and experiment records use identical validation and null/identifier semantics.

---

# Phase 3 — Complete inventory APIs and dashboard

## P1-08 — Product list/detail/create/edit APIs

**Status: Not implemented.** Current `/inventory` routes are CSV preview/import/dashboard only; Qloo mapping subroutes are not general product CRUD.

- [ ] `GET /products` with retailer scoping, search, filters and pagination.
- [ ] `GET /products/{product_pk}`.
- [ ] `POST /products`.
- [ ] `PATCH /products/{product_pk}`.
- [ ] Return both internal `product_pk` and retailer `sku` explicitly.
- [ ] Use Person 1's authenticated tenant context; do not accept caller-selected retailer IDs.
- [ ] Reuse CSV/manual validation for costs, prices, quantities, duplicate SKUs and optional fields.
- [ ] Keep missing sales as NULL/unknown.
- [ ] Define stable 4xx errors and examples.
- [ ] Add tests for create/read/update, duplicate SKU, invalid values, clearing optional values and cross-tenant IDs.
- [ ] Add API contract coverage for the future frontend.

**Acceptance:** The frontend can manage products through stable public APIs without direct DB access.

## P1-09 — Complete inventory dashboard aggregates

**Status: Partial.** Product counts, attention/insufficient-data counts, tied-up inventory cost, flagged cost, rule counts and descriptions exist. Total units and potential retail value are missing.

- [ ] Add total units in stock (`sum(quantity_in_stock)`).
- [ ] Add potential retail value (`sum(quantity_in_stock * selling_price)`).
- [ ] Keep total inventory cost tied up.
- [ ] Keep flagged inventory cost tied up.
- [ ] Add explicit formula and period descriptions for every metric.
- [ ] Feed thresholds from the persisted retailer settings (P1-10), not only dataclass defaults.
- [ ] Preserve statuses: known zero sales, aged stock, low velocity and insufficient data.
- [ ] Never convert missing sales into zero.
- [ ] Test every aggregate against hand-calculated fixtures.
- [ ] Update dashboard response types and frontend cards.

**Acceptance:** Dashboard metrics are deterministic, explainable and consistent with current retailer settings.

---

# Phase 4 — Qloo reliability and signal integration

## P1-14 — Finish Qloo cache/retry/observability hardening

**Status: Mostly implemented.** The cache is an `OrderedDict` capped at 512 entries with expiry cleanup; retries and typed errors exist.

- [x] Bound cache entry count.
- [x] Remove expired cache entries during writes/access.
- [x] Bound retry attempts.
- [x] Handle auth, timeout, rate-limit, upstream and malformed-response categories.
- [ ] Test concurrent access to the process-local cache or document the intended threading model.
- [ ] Decide whether a shared cache is needed for the actual deployment; avoid adding infrastructure without a requirement.
- [ ] Add explicit cache hit/miss/eviction counters.
- [ ] Add endpoint, latency, status and retry-count instrumentation without logging credentials or unnecessary raw content.
- [ ] Check `Retry-After` behaviour and retryable versus non-retryable failures against the approved event limits.
- [ ] Keep empty successful results distinct from provider failures.
- [ ] Verify real response shapes through the approved live access method (P0-25).

**Acceptance:** Cache memory is bounded; logs/metrics make provider failures diagnosable without exposing keys.

## P1-25 — Fix force/refresh semantics for unverified entity mappings

**Status: Bug remains in current service.** `resolve_product()` short-circuits confirmed/rejected mappings, but re-resolves an existing unverified mapping regardless of `force=False`.

- [ ] No existing mapping → resolve and save.
- [ ] Existing unverified mapping + `force=False` → return the saved mapping without a new Qloo call or evidence row.
- [ ] Existing unverified mapping + `force=True` → refresh and save new evidence/mapping.
- [ ] Confirmed mapping → preserve final human decision even on force.
- [ ] Rejected mapping → preserve final human decision even on force.
- [ ] Do not let refresh silently change Person 1's human decisions.
- [ ] Add tests for repeated default resolve, forced refresh, confirmed refresh and rejected refresh.
- [ ] Verify `DbQlooGateway` and direct `/products/{pk}/qloo/resolve` route share the same semantics.
- [ ] Update API docs.

**Acceptance:** The `force` flag has one consistent and tested meaning across API and pipeline calls.

## P1-29 — Preserve Qloo affinity end to end

**Status: Implemented in source.** The parser, `QlooRelatedEntity`, adapter, strategy evidence and tool output carry nullable affinity and distinguish it from internal matching/ranking scores.

- [x] Nullable `InsightEntity.affinity` parsing.
- [x] Affinity carried through the adapter and tool outputs.
- [x] Affinity included in evidence/strategy explanation when present.
- [x] Missing affinity remains null; no inferred value is fabricated.
- [ ] Add/keep a complete contract test from raw Insights fixture → parser → adapter → plan JSON → frontend response.
- [ ] Verify all cross-category types preserve their own entity type and actual affinity field.
- [ ] Ensure UI labels it explicitly as Qloo-reported affinity and not demand probability or sales forecast.

**Acceptance:** Each displayed affinity can be traced to the actual Qloo response; absence remains absence.

## P1-39 — Add a per-run provider request and time budget

**Status: Partial.** Attempts per HTTP request, a maximum category list and API rate limits exist; there is no central per-rescue time/call budget with a recorded per-run summary.

- [ ] Define maximum Qloo requests per rescue run.
- [ ] Define maximum Insights categories per run and per-category result count.
- [ ] Define maximum agent iterations and total wall-clock time.
- [ ] Add a shared request-budget object passed through the gateway/workflow.
- [ ] Respect event quota and `Retry-After` policy.
- [ ] Record actual calls, retries, cache hits, latency and category failures per run.
- [ ] Return useful partial plans when a budget is exhausted.
- [ ] Keep rate-limit semantics correct if deployment later uses multiple workers (the current limiter is process-local).
- [ ] Test that a single rescue run cannot exceed the configured budget.

**Acceptance:** External calls and end-to-end provider latency have explicit, tested upper bounds.

## P1-40 — Preserve correct provider failure semantics

**Status: Mostly implemented but integration coverage is incomplete.** Qloo exceptions are typed and workflow stages can fail without fabricating evidence.

- [x] Typed Qloo error categories exist.
- [x] API error mapping exists.
- [x] Pipeline records failed stages and supports partial plans.
- [ ] Verify missing key, invalid key, timeout, 429, 5xx, malformed JSON, 404/no results and successful empty Insights separately.
- [ ] Verify partial category success remains usable and all-category failure is surfaced as failure.
- [ ] Verify an LLM-offline case does not imply Qloo failure or success.
- [ ] Ensure `/qloo/status` diagnostic HTTP status/body contract cannot be misread as a successful provider check when `ok=false`.
- [ ] Ensure no Qloo-backed explanations are generated from failed or empty evidence.
- [ ] Add route-level integration tests for all error categories.

**Acceptance:** Empty result, provider failure, missing configuration and fallback-only recommendation are visibly and programmatically distinct.

---

# Phase 5 — Agent validation, prompt safety and real tool use

## P1-27 — Strict semantic validation for tool arguments

**Status: Partial.** Custom validator rejects unknown/required/type/enum errors and some array shape errors, but does not provide full strict field constraints and business semantics.

- [ ] Define strict Pydantic argument models per tool.
- [ ] Reject unknown arguments and extra nested fields.
- [ ] Enforce numeric bounds, positive prices, positive planned units and array length limits.
- [ ] Reject NaN and infinity with `math.isfinite`/strict validators.
- [ ] Enforce string length and non-empty requirements.
- [ ] Reject duplicate product IDs.
- [ ] Verify all product IDs belong to the authenticated retailer and selected product set (use Person 1 tenant context).
- [ ] Validate tool outputs before feeding them to another step.
- [ ] Re-run deterministic commercial rules after all model-proposed arguments.
- [ ] Add malformed, adversarial and cross-tenant argument tests.

**Acceptance:** No malformed, non-finite, out-of-range or out-of-scope tool input can reach business logic.

## P1-38 — Prompt-injection and model-output protection

**Status: Partial.** Explanation prompts already restrict numeric/guarantee claims, but do not constitute a complete retrieved-content/tool authorization boundary.

- [ ] Delimit product text, Qloo names/tags/descriptions and retailer notes as untrusted data.
- [ ] Add explicit instructions to ignore instructions embedded inside retrieved content.
- [ ] Never place keys, private configuration or unrelated retailer records in prompts.
- [ ] Validate every structured model response against strict Pydantic schemas.
- [ ] Escape/sanitize untrusted content when rendering it in the frontend.
- [ ] Keep tool authorization, tenant scope, price/stock calculations, hard constraints and approvals outside LLM authority.
- [ ] Test hostile product titles/descriptions and Qloo metadata containing instruction-like text, fake numbers and links.
- [ ] Verify invalid model output falls back safely without inventing evidence.

**Acceptance:** Retrieved content cannot override system policy, tool permissions or commercial validation.

## P1-11 — Decide and implement the agent capability honestly

**Status: Not implemented as an autonomous/tool-selecting agent.** `agent/tools.py` is a registry; `agent/workflow.py` runs a predetermined pipeline; `agent/llm.py` provides text completion, not a bounded tool-call loop.

- [ ] Decide between implementing real model-directed tool calling or accurately scoping the product as deterministic orchestration with LLM-assisted explanations.
- [ ] If implementing: define strict tool allowlist and per-tool Pydantic schema.
- [ ] Implement provider-supported tool calling and a bounded execution loop.
- [ ] Let the model inspect actual tool results before choosing a next allowed action.
- [ ] Cap tool calls, iterations and total wall-clock time.
- [ ] Record a trace of model plan, selected tool, validated arguments, result and next action.
- [ ] Add prompt-injection protections before activating tool calls.
- [ ] Keep margin/discount/budget/stock checks deterministic and authoritative.
- [ ] Keep approval and publishing actions outside LLM authority.
- [ ] Add tool-error, empty-Qloo, timeout, invalid-output and fallback tests.
- [ ] Record which tool/evidence outputs informed a saved plan.
- [ ] Update README, pitch and judge demo so claims match actual implementation.

**Acceptance:** Demonstrate at least one genuine bounded LLM-selected tool call with a trace, or explicitly describe the current deterministic pipeline accurately.

---

# Phase 6 — Complete and securely integrate the frontend

**Current status:** A Next.js app exists with `/`, `/upload`, `/rescue/[pk]` and `/experiments`. Do not scaffold a second app; extend this one. Authentication integration is a dependency on Person 1's secure token/session design.

## F0 — Secure API connection and frontend quality foundation

- [ ] Agree with Person 1 on the server-side session/proxy/token contract.
- [ ] Implement a Next.js server-side API proxy/session or equivalent secure server-side fetch path.
- [ ] Never put raw retailer bearer tokens in `NEXT_PUBLIC_*` variables or browser JavaScript.
- [ ] Update `frontend/lib/api.ts` to use the secure authenticated path.
- [ ] Configure production backend origin and exact CORS origins.
- [ ] Add typed response/error handling for 401, 403, 409, 422, 429, 500 and 503.
- [ ] Add frontend `.env.example` with non-secret public origin only.
- [ ] Add `typecheck` and `test` scripts to `frontend/package.json`.
- [ ] Install via `npm ci` and verify lockfile reproducibility.
- [ ] Run ESLint, TypeScript type-check and Next build.
- [ ] Add a frontend component/unit test framework.
- [ ] Add loading, empty, partial and failure states for every API-driven page.

## F1 — Inventory management

- [ ] Add product list/table page backed by `GET /products`.
- [ ] Add product detail page backed by `GET /products/{product_pk}`.
- [ ] Add manual product creation after P1-08 is ready.
- [ ] Add manual product editing and explicit clear-optional-field behaviour.
- [ ] Add search, filters, pagination and sorting.
- [x] Keep CSV preview and import UI.
- [ ] Display row-level validation details and suggested correction if that contract is retained.
- [ ] Display import created/updated/skipped totals.
- [ ] Display the new dashboard total units and potential retail value after P1-09.
- [ ] Display missing sales as unknown, not zero.

## F2 — Rescue Lab and cultural evidence

- [x] Basic rescue-plan page and ranked strategy cards exist.
- [x] Basic rejected-option reasons are displayed.
- [ ] Display actual Qloo source/target type, evidence ID/reference and provider affinity where returned.
- [ ] Provide access to the exact stored Qloo evidence payload through the protected evidence API, with a safe UI presentation.
- [ ] Add/verify human confirm/reject controls for ambiguous entity matches (coordinate ownership with Person 1).
- [ ] Display category coverage and per-category failures for cross-category Insights.
- [ ] Display data-quality warnings and clearly distinguish fact, provider signal, internal match score and hypothesis.
- [ ] Add editable strategy workspace for price, bundle partner, discount and planned units.
- [ ] Call backend `/rescue/evaluate` after edits; do not calculate authoritative margin in browser.
- [ ] Prevent creating an experiment if the plan was not saved or its plan ID is missing.
- [ ] Display assumptions, operational risks and causal limitations.
- [ ] Add refresh-Qloo action only through the documented force/refresh semantics.

## F3 — Experiments and settings

- [x] Basic experiment list and lifecycle actions exist.
- [x] Basic outcome form/view exists.
- [ ] Display snapshot price/cost/stock basis in experiment details.
- [ ] Display baseline dates and control identity once P1-12 is complete.
- [ ] Add deliberate early-stop flow and reason.
- [ ] Display actual units/revenue/COGS/gross profit/margin and excluded costs.
- [ ] Keep simulated and observed outcomes visibly separate.
- [ ] Add retailer settings screen once P1-10 is complete.
- [ ] Add minimum margin, discount cap, budget, restricted products, thresholds, test units/days, campaign costs and ranking weights.
- [ ] Add structured strategy feedback UI when P2-21/P2-29 are implemented.
- [ ] Add data completeness panel when P2-23/P2-27 are implemented.

## F4 — Interaction/accessibility/browser testing

- [ ] Test desktop, tablet and mobile layouts.
- [ ] Verify keyboard navigation and focus states.
- [ ] Add accessible labels and error messaging.
- [ ] Ensure no buttons are inert.
- [ ] Escape untrusted product/Qloo content before rendering.
- [ ] Test authentication/session expiry and unauthorized requests.
- [ ] Test all API-driven loading, empty, error and partial states.
- [ ] Add browser E2E flows for upload → dashboard → rescue → experiment → outcome.

**Acceptance:** An authenticated retailer can complete the full workflow from the browser without exposing a bearer token or making frontend calculations authoritative.

---

# Phase 7 — Demo fixtures, end-to-end proof, API docs and deployment

## P1-17 — Reproducible demo dataset

**Status: Partial.** A 40-row synthetic CSV and data notes exist, but `seed_dev.py` seeds only three products when the entire Product table is empty; there is no complete demo-mode reset path.

- [x] Keep synthetic demo CSV clearly labelled.
- [x] Include missing sales, low stock, aged stock, margin warnings and ambiguous Qloo example.
- [ ] Create a single deterministic seed command for the complete sample scenario.
- [ ] Define expected dashboard totals and known feasible/infeasible strategies.
- [ ] Include explicit exact-match, ambiguous, no-match and cross-category fixtures; mark provider-verified rows only when genuinely checked.
- [ ] Keep observed outcomes separate from simulated outcomes.
- [ ] Make repeated seed runs idempotent.
- [ ] Add a demo-only reset operation with a hard demo-mode guard (do not delete real retailer data).
- [ ] Test reset/seed idempotency and tenant isolation.

**Acceptance:** A documented command creates the same repeatable scenario and expected results every time.

## P1-15 — Execute T01–T10 end to end

**Status: Not complete.** Current `docs/test_plan.md` explicitly says T01–T10 have not all been individually run. The 486 passing tests are automated tests, not a substitute for this manual/integrated acceptance run.

- [ ] T01 — Valid Qloo entity match; record selected entity and evidence.
- [ ] T02 — Ambiguous match; verify no blind selection and human review path.
- [ ] T03 — No Qloo match; verify no fabricated entity/evidence.
- [ ] T04 — Successful empty Insights; verify no invented links/affinity.
- [ ] T05 — Bundle failing margin; verify deterministic rejection.
- [ ] T06 — Bundle stock shortage; verify infeasible option rejection.
- [ ] T07 — Missing sales, zero sales, aged stock, low velocity and insufficient-data handling.
- [ ] T08 — Qloo timeout/provider failure; verify partial/failure semantics.
- [ ] T09 — CSV preview/import, duplicate SKU, row/file errors and rollback; resolve whether `suggested_correction` is required.
- [ ] T10 — Create/approve/start experiment, record outcome and verify saved accounting.
- [ ] For each test, record setup, fixture, expected result, actual result, Pass/Fail/Not Run and evidence.
- [ ] Run the full backend suite after final merge.
- [ ] Run frontend lint/type-check/build/test.
- [ ] Run PostgreSQL migration/transaction/stock reservation tests.
- [ ] Test security/tenant boundaries with two distinct retailer tokens (Person 1's implementation).
- [ ] Test concurrent idempotency and stock reservation on PostgreSQL.
- [ ] Run live Qloo harness tests separately from mocks.

**Acceptance:** T01–T10 each have a recorded result and supporting evidence; all critical failures are fixed.

## P1-42 — Versioned API contract and frontend route coverage

- [ ] Reconcile generated OpenAPI with current FastAPI routes and schemas.
- [ ] Document each request and response field with correct PK/SKU semantics.
- [ ] Document idempotency behaviour on both experiment-creation paths.
- [ ] Document auth requirements and the frontend's secure session/proxy boundary.
- [ ] Document plan persistence success/failure response and header behaviour.
- [ ] Document provider partial-result/error contracts.
- [ ] Document outcome snapshot/accounting semantics.
- [ ] Add contract tests for all routes used by frontend.
- [ ] Add stable error examples for 401/403/404/409/422/429/500/503.
- [ ] Version breaking changes and retain example JSON fixtures.

## P1-18 — Synchronize README and handoff docs

**Status: Partial.** Several supporting docs exist, but root README is only a short summary and currently links to a missing `docs/merge_resolution_2026-10-30.md`; frontend README is generic starter text.

- [ ] Fix or remove the broken merge-resolution link.
- [ ] Write clean-clone backend setup instructions.
- [ ] Write frontend setup instructions.
- [ ] Document all environment variables without secrets.
- [ ] Document retailer token generation/configuration (coordinate with Person 1; never document raw tokens).
- [ ] Document Alembic migration/upgrade/bootstrap procedure.
- [ ] Document database seed/reset procedure.
- [ ] Document CSV field semantics and product ID/SKU contract.
- [ ] Document all commercial formulas, constraints and rounding/currency policy.
- [ ] Document Qloo approved access path, category allowlist, quota and fallback semantics.
- [ ] Document agent capability honestly (deterministic vs tool-selecting).
- [ ] Document simulated vs observed outcomes and control limitations.
- [ ] Update test plan with current suite count and manual T01–T10 status.
- [ ] Add judge-facing demo script and known limitations.
- [ ] Ensure every README link resolves in the repository.

## P1-16 — Deploy and validate release

**Status: Not verified from this archive.**

- [ ] Choose the hosting environment and supported Python/Node runtime versions.
- [ ] Configure PostgreSQL and persistent storage.
- [ ] Back up existing database before migration.
- [ ] Apply Alembic migrations explicitly.
- [ ] Configure exact `CORS_ORIGINS`.
- [ ] Configure retailer token hashes securely with Person 1's process.
- [ ] Configure approved Qloo credential/access method and optional LLM credential.
- [ ] Deploy backend and frontend.
- [ ] Verify `/health` and authenticated/internal `/ready` according to deployment policy.
- [ ] Verify frontend proxy/session reaches protected backend APIs.
- [ ] Verify Qloo direct runtime transport is event-authorized or migrated.
- [ ] Verify PostgreSQL data persists across restart/redeploy.
- [ ] Verify provider failure gives useful partial results without secrets/stack traces.
- [ ] Verify one-worker limitation for process-local limiter or implement shared limiter before scaling.
- [ ] Record public demo URL, reset process and known limitations.

**Acceptance:** A clean hosted deployment is externally verified, persistent and reproducible. Do not call the project deployed until this passes.

---

# Phase 8 — P2 differentiators and product hardening

These are not release blockers. Several have partial foundations; implement only after the P0/P1 release path is correct.

## P2-19 — Full strategy acceptance/rejection audit (partial)

- [x] Current plan displays ranking dimensions, weights, explanations and some rejected reasons.
- [ ] Persist every candidate considered, not only the final top strategies.
- [ ] Preserve generation/filter/check/rank state for each candidate.
- [ ] Preserve hard-constraint violations and per-dimension scores.
- [ ] Explain why one strategy outranked another.
- [ ] Separate provider evidence, internal match type, commercial feasibility and operational effort.
- [ ] Make a deterministic strategy decision reproducible from saved inputs.

## P2-20 — Rules-only vs LLM-only vs Qloo-informed comparison (not implemented)

- [ ] Build deterministic comparison fixture with same inventory and constraints.
- [ ] Run rules-only candidate generation.
- [ ] Run LLM-only ideation without allowing it to approve/calculate.
- [ ] Run Qloo-informed constrained workflow.
- [ ] Compare evidence quality, candidate diversity, feasibility, cost and explanation trace.
- [ ] Do not claim performance/sales uplift without measured outcomes.

## P2-21 and P2-29 — Retailer feedback and bounded effect (not implemented)

- [ ] Capture useful/not useful.
- [ ] Capture feasible/not feasible.
- [ ] Add reason codes and optional note.
- [ ] Store feedback separately from actual sales outcomes.
- [ ] Add a minimum-data policy before feedback affects ranking.
- [ ] Use feedback only through documented filtering/de-prioritization rules.
- [ ] Keep audit trail of how feedback affects future suggestions.

## P2-22 and P2-25 — Reproducible snapshots, audit log and replay (partial)

- [x] Rescue plan JSON, constraints snapshot, ranking rationale and evidence IDs are saved.
- [x] Experiment product/cost/price/stock snapshot exists.
- [ ] Save exact inventory snapshot used at recommendation time.
- [ ] Save effective retailer settings snapshot and ranking weights.
- [ ] Save matching/ranking/generator version and agent/LLM prompt version.
- [ ] Save excluded candidates and reasons.
- [ ] Add deterministic replay from the saved inputs, not today's inventory.
- [ ] Verify historical plans remain explainable after inventory/settings changes.

## P2-23 and P2-27 — Data completeness and evidence coverage (partial)

- [x] Basic missing-sales history and Qloo unavailable/ambiguous/partial status are disclosed.
- [ ] Report cost/price/stock/creator/brand/genre/age/sales completeness.
- [ ] Report Qloo resolution status and category coverage.
- [ ] Explain what each missing field prevents the engine from concluding.
- [ ] Add a user-visible readiness/data-completeness assessment before recommendation generation.
- [ ] Never score missing data as zero or imply missing evidence is negative evidence.

## P2-24 and P2-34 — Operational observability (partial)

- [x] Safe exception responses and some sanitized logs exist.
- [x] Qloo cache hit metadata and provider error types exist.
- [ ] Add request/correlation ID creation and propagation across API, workflow and logs.
- [ ] Track per-run Qloo/LLM calls, cache hits, retries, latency and failures.
- [ ] Add private operator view/metrics for external calls and cost where measurable.
- [ ] Add database readiness/failure diagnostics and safe alerting.
- [ ] Keep credentials and raw sensitive payloads out of logs.

## P2-26 — Per-candidate rejection reasons (partial)

- [x] Current plan includes some rejected/skipped candidates and hard-constraint reasons.
- [ ] Preserve every generated candidate's lifecycle state.
- [ ] Include precise reason codes for missing/ambiguous evidence, not stocked, no stock, restricted, low margin, discount cap, budget and low operational feasibility.
- [ ] Keep rejected items separate from recommendations.

## P2-28 — Safe demo mode and reset (partial)

- [x] Synthetic sample inventory and dev seed script exist.
- [ ] Add explicit demo-mode configuration.
- [ ] Add a visible demo-data label.
- [ ] Add deterministic full seed/reset.
- [ ] Restrict reset to demo mode and a dedicated demo tenant.
- [ ] Prove reset cannot delete real retailer data.
- [ ] Keep sample outcomes simulated.

## P2-30 — Counterfactual mode comparison

- [ ] Use same inventory/constraints for each mode.
- [ ] Compare rules-only, LLM ideation and Qloo-informed approaches.
- [ ] Compare evidence, candidate variety, feasibility, costs and transparency.
- [ ] Avoid sales-performance claims without validated experiments.

## P2-31 — Control-group identity and comparability (partial)

- [x] Numeric baseline/control measurement fields exist.
- [ ] Add control product or period identity.
- [ ] Add baseline and experiment dates for control and target.
- [ ] Record why the comparison is valid and whether the control avoided intervention.
- [ ] Calculate per-day rates for different periods.
- [ ] Display confounders and causal limitations.

## P2-32 — Seasonality context (schema-only/partial)

- [x] Product includes an optional seasonality field.
- [ ] Accept documented retailer-entered seasonality/calendar events.
- [ ] Use dated sales data before asserting a seasonal pattern.
- [ ] Label unsupported seasonal patterns as hypotheses.

## P2-33 — Privacy and retention policy

- [ ] Document why raw Qloo responses are stored.
- [ ] Define retention duration and deletion/export process.
- [ ] Restrict access through Person 1's tenant/evidence controls.
- [ ] Avoid unnecessary personal/customer-level data.
- [ ] Document backup and deletion interaction.

## P2-35 — Backup and restore

- [ ] Add automated DB backup process for hosted DB.
- [ ] Document retention and recovery point policy.
- [ ] Test restore into a separate database.
- [ ] Validate row counts and foreign keys after restore.
- [ ] Document recovery for interrupted experiment state transitions.

## P2-36 — Discount-last preference (implemented; retain regression tests)

- [x] `discount_last` is represented in ranking configuration and ranking logic sorts feasible non-markdown strategies before promotions when enabled.
- [ ] Keep tests proving hard constraints always outrank this preference.
- [ ] Verify a promotion is still returned if it is the only feasible option.
- [ ] Explain it as a retailer/team preference, not a universal retail law.

## P2-37 — Outcome-quality review before claiming a learning loop

- [ ] Track count/diversity of observed experiments.
- [ ] Track missing outcomes and data completeness.
- [ ] Track experiment durations and control availability.
- [ ] Track known confounders.
- [ ] Define minimum sample/quality requirements before predictive learning.
- [ ] Keep current output descriptive until a model is evaluated out of sample.

---

# Phase 9 — P3 future ideas (after MVP acceptance)

These are future product ideas, not required for the current MVP release.

- [ ] POS/e-commerce integration for dated transactions and live stock with explicit source-of-truth rules.
- [ ] Real stock reservation/sale/promotion integrations behind explicit retailer approval and rollback.
- [ ] Broader multi-category retail support after the bookstore cross-category workflow is proven.
- [ ] Retailer collaboration and staff roles after multi-tenant security is fully deployed.
- [ ] Notifications for experiment end dates, stock-outs and missing outcomes.
- [ ] Multi-store analytics after store identifiers and access controls are robust.
- [ ] Randomized/matched-product experiment design helpers where store operations support them.
- [ ] Predictive sales models only after enough representative dated outcomes and out-of-sample evaluation.

---

# 4. Final release gate

Do not mark StockRescue complete until the following are all true:

- [ ] P0-25 live Qloo verification is successful using the event-authorized method.
- [ ] P0-26 persistence failure response and documentation are consistent.
- [ ] Alembic owns all production schema evolution; application startup does not call `create_all()` or run ad-hoc DDL.
- [ ] PostgreSQL migration and transaction tests pass.
- [ ] Person 1's auth, tenant, stock reservation, matching and provenance changes pass two-retailer and concurrent-request tests.
- [ ] Person 2 settings, product CRUD, dashboard, experiment measurement and accounting contracts are complete.
- [ ] Qloo `force` semantics and provider request budgets are correct.
- [ ] The LLM/agent capability is either genuinely tool-selecting with bounded traces or accurately described as deterministic workflow + explanation.
- [ ] Frontend uses a secure server-side auth/session integration and never exposes retailer tokens.
- [ ] Frontend lint, type-check, tests and production build pass.
- [ ] T01–T10 end-to-end scenarios have individually recorded evidence.
- [ ] Demo data and reset are deterministic and safely scoped.
- [ ] README, API contract, test plan and handoff docs match the actual code.
- [ ] Hosted API/frontend, CORS, readiness, persistence and restart/redeploy have been externally verified.
- [ ] Release ZIP excludes `.env`, local DB, `.venv`, `.git`, node_modules, build outputs and caches.

## 5. Recommended execution order

1. **Phase 0:** complete approved live Qloo access verification and reconcile P0-26 documentation.
2. **Phase 1:** remove startup schema mutation, complete transaction boundaries, readiness and all-path idempotency.
3. **Phase 2:** implement persistent retailer settings; then historical accounting/currency; then date/control metadata and sales snapshots.
4. **Phase 3:** product CRUD and complete dashboard aggregates.
5. **Phase 4:** fix refresh semantics, implement request budgets and finish provider error/affinity integration tests.
6. **Phase 5:** strict tool schemas and prompt protection before any LLM tool-calling loop.
7. **Phase 6:** securely connect the existing frontend, then finish inventory, rescue and experiment/settings screens.
8. **Phase 7:** demo fixtures, T01–T10, contract docs and hosted deployment.
9. **Phase 8–9:** P2 improvements, then P3 product ideas.

**Immediate next task:** P1-13 migration startup correction. The migration files/tests exist, but current `main.py` still mutates the database at application startup. Fix that before adding more persistent models in Phase 2.
