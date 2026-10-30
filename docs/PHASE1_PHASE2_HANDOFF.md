# StockRescue — Phase 1 and Phase 2 implementation handoff

Date: 30 October 2026

## Phase 1 — P0

### P0-26 — Rescue plan persistence is now mandatory

- `POST /rescue/{product_pk}` no longer returns a successful-looking plan after `save_plan()` fails.
- Persistence failure returns HTTP 503 `plan_persistence_failed` with a safe message.
- The response omits `X-Rescue-Plan-Id` and does not return the unsaved plan.
- Added/updated regression test for forced plan-save failure.

### P0-25 — Qloo event-access check prepared; live result remains outstanding

- Replaced the direct-HTTP smoke-test script with a harness-based script using the documented `qloo api` CLI surface.
- The script checks the local CLI version, a book entity search, and movie/artist Insights calls, while emitting only sanitized metadata.
- It does not print API keys, request headers, or raw provider responses.
- The current event access guide documents `@qloo/qloo-harness` 0.1.26+ and supported surfaces. This repository's runtime Qloo client still uses Python direct HTTP; that runtime path must be confirmed with the organizers or migrated to the harness before it is represented as event-approved.
- This execution environment has no `qloo` executable, no event credential, and does not have outbound Qloo access configured. Live connectivity was not verified.

## Phase 2 — P1

### P1-13 — Alembic migrations

- Added `backend/alembic.ini`, migration environment and script template.
- Added an initial migration for all current application tables, including idempotency records and a partial unique index for live plan strategies.
- Removed production schema creation from FastAPI startup.
- Added safe bootstrap logic for a complete legacy `create_all()` database: preserves existing tables/rows, adds the new idempotency table/index, and adds `product_snapshot` if missing.
- `seed_dev.py` no longer creates schema implicitly and requires `alembic upgrade head` first.

Commands (from `backend/`):

```bash
python -m alembic upgrade head
python -m alembic current
python -m alembic check
```

### P1-30 — Transaction boundaries and rollback handling

- Added shared `commit_or_rollback()` helper.
- Applied it to plan persistence, Qloo resolve/confirm/reject/Insights writes, and experiment create/edit/approve/reject/cancel/start/outcome writes.
- Resolve evidence + mapping are flushed and committed as one unit.
- Plan data + its evidence-reference list are committed as one unit.
- Outcome row + experiment completed status are committed as one unit.
- Experiment row + optional idempotency record are committed as one unit.
- Failure rolls back the active unit of work and propagates to the safe API error handler.

### P1-33 — Idempotency and database uniqueness

- Added `idempotency_records` table with unique `(retailer_id, idempotency_key)`.
- `POST /experiments` and create-from-saved-strategy accept optional `Idempotency-Key` header.
- Repeating the same key with the same body returns the original experiment (HTTP 200).
- Reusing the key for a different body returns HTTP 409 `idempotency_conflict`.
- Key and experiment are written in the same transaction.
- Added partial unique index `(plan_id, product_pk, title, strategy_type)` for records whose status is not rejected/cancelled, preventing races that bypass the service-level duplicate check.

### P1-31 — Liveness/readiness separation

- `/health` remains a lightweight process liveness endpoint.
- Added `/ready`, which checks database connectivity, required tables and current Alembic head.
- `/ready` returns HTTP 503 when the database is unreachable, the schema is incomplete, or migrations are missing/out of date.
- Routine readiness checks do not consume Qloo quota.

## Verification

The backend suite result and Alembic migration integration result are recorded in the release notes accompanying this archive. Live Qloo access is explicitly not marked complete because no authenticated live harness response was obtained in this environment.
