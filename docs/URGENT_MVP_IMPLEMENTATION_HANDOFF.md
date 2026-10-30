# StockRescue — Urgent MVP implementation handoff

**Date:** 30 October 2026  
**Based on:** `stockrescue(2).zip` (latest archive supplied in this conversation)  
**Scope:** Complete locally verifiable portions of the six urgent MVP milestones. Do not interpret mocked tests as live Qloo or deployment proof.

## Implemented in this update

### Retailer settings and constraints
- Added authenticated `GET /settings` and `PUT /settings` for a validated INR settings document.
- Settings include hard constraints, strategy defaults/campaign cost assumptions, ranking weights and slow-moving thresholds.
- Rescue API and agent helper tools use the persisted settings instead of silently using unrelated defaults.
- Rescue plans retain a full `settings_snapshot` inside their constraint snapshot.
- New experiments capture the validated settings snapshot at creation. Edit, approval and start revalidation use that saved snapshot, so changing today's retailer settings does not silently rewrite the rules under which an existing experiment was proposed.
- Added rollback handling when settings persistence fails.
- CORS now permits `PUT`, required by the settings endpoint.

### Historical data and dashboard
- Each successful CSV import creates dated inventory sales snapshot rows with source metadata.
- Added retailer-scoped `GET /inventory/products/{product_pk}/sales-history`.
- Null sales values remain null; no sales history is fabricated.
- Dashboard aggregates include total inventory units and potential full-price retail value.
- Dashboard uses saved retailer slow-moving thresholds.
- Frontend dashboard now displays units in stock, potential retail value and inventory cost.

### Frontend access and settings
- Frontend API client attaches the bearer token entered by the retailer.
- Added `/access` to enter and verify the out-of-band retailer token via `GET /settings`.
- Token is stored in tab-scoped `sessionStorage`; this is a lightweight hackathon demo integration, not a production OAuth/session architecture.
- Added `/settings` for minimum margin, maximum discount, budget, restricted SKUs, test units/days and direct campaign cost assumptions. Other settings fields are retained when saving.

### Documentation
- Replaced the starter root README with backend/frontend setup, migration, test and accounting instructions.
- Updated frontend README.
- Added `typecheck` npm script.
- Updated `WORK_LOG_PERSON2.md`.

## Verification performed here

- `python -m compileall -q app` — passed.
- `python -m pytest -q` — **494 passed**.
- `python -m pytest tests/test_migrations.py -q` — **2 passed**.
- Fresh SQLite database: `alembic upgrade head` — passed.
- Fresh SQLite database: `alembic check` — `No new upgrade operations detected.`
- Regression tests added for direct-experiment settings enforcement, settings snapshot preservation through approval, and CORS `PUT` preflight.
- ZIP integrity and release-artifact filtering must be checked on the final archive.

## Work still requiring the project owner / team environment

1. **Live Qloo verification:** install the current event-approved Qloo harness, configure the team's individually attributable event key out of band, and run `cd backend && python qloo_smoke_test.py`. The current script expects Node.js 22.19.0+ and `@qloo/qloo-harness` 0.1.26+. The backend's existing `qloo_service.py` transport still makes direct HTTP requests; confirm with event instructions whether that transport is accepted, or migrate the backend request path to the approved CLI/MCP surface. Do not claim success from mocked tests.
2. **Frontend install/build:** `npm ci` timed out in this environment. `tsc --noEmit` could not run because installed Node/React type packages were unavailable. Run `npm ci`, `npm run typecheck`, `npm run lint` and `npm run build` in a network-enabled environment and fix any errors.
3. **PostgreSQL:** run migrations, transaction tests, unique/idempotency tests and a restart-persistence test against the actual PostgreSQL version selected for deployment. SQLite success is not PostgreSQL proof.
4. **Authentication handoff:** Person 1 must issue retailer tokens out of band and confirm `RETAILER_API_TOKEN_HASHES` is configured on the backend. The frontend's sessionStorage token entry is demo-only; replace it with a proper short-lived server-side session/OAuth flow before production.
5. **Full end-to-end run:** execute and record T01–T10 with actual inventory fixtures and live Qloo. Check CSV upload → dashboard → Qloo resolution/confirmation → cross-category Insights → recommendation generation → plan persistence → experiment creation/approval/start → observed outcome → summary.
6. **Deployment:** configure secrets, database, exact CORS origins, migrations and hosting; test `/health`, `/ready`, API token access, frontend access, restart/redeploy persistence and provider failure messages from outside the host.
7. **Product scope intentionally not completed in this urgent pass:** full product CRUD (CSV-first flow remains), early-stop experiment outcome workflow, full event-level sales ledger, autonomous LLM tool selection, richer control-group identity metadata, and the deferred P2/P3 features.

## Important interpretation

This update improves the existing code and completes locally testable portions. It does not establish a live Qloo success, a PostgreSQL production deployment, a frontend production build, or the full manual acceptance run. Record those as pending until they are actually completed.
