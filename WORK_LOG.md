# StockRescue work log — roadmap tasks 01, 02, 03, 08, 09 and 12

**Date:** 30 October 2026  
**Implementation base:** Uploaded `stockrescue-feat-data-qa-deployment.zip` reference snapshot (29 October 2026), not the user's latest local Git branch.  
**Working rule:** No commit, push, deploy, credential rotation or live database migration was performed.

## Task 01 — Secure API keys and secrets

- Added a sanitized release packager (`scripts/package_release.py`) that omits `.env` except `.env.example`, local DB files, `.git`, virtual environments, build caches and common runtime artifacts; scans current text files for common token/private-key patterns and inspects the generated ZIP.
- Added a targeted Git-history scanner (`scripts/scan_git_history.py`). It must be run from the actual Git checkout after `git fetch --all`.
- Added a cryptographically random retailer bearer-token generator (`scripts/generate_retailer_token.py`); only SHA-256 token hashes are configured in the API.
- Updated `.env.example` with fail-closed auth configuration and rate limits.
- Verification: sanitized ZIP created and checked (112 files; no excluded runtime/secrets paths found).
- Not verified: Git history scan could not run because the uploaded source archive has no `.git` directory. Credential rotation cannot be performed from this environment; rotate any real Qloo/LLM key that was exposed outside the trusted team boundary.

## Task 02 — Secure API endpoints and authorization

- Added fail-closed bearer-token authentication middleware; `/health` and API docs/preflight are public, other API routes require a valid token.
- Tenant identity is derived from the SHA-256 token-hash map; missing auth returns 401; missing token configuration returns 503.
- Added per-retailer per-minute limits for Qloo status/search/resolve/Insights and rescue runs. This is in-process and requires one API worker until replaced with a shared limiter.
- CORS uses the configured origin list. Deployment must set the exact Vercel origin.
- Verification: authentication required/invalid-token/config-fails-closed tests and Qloo rate-limit test pass.
- Not complete for browser release: this snapshot has placeholder frontend files only. Add a Vercel server-side proxy/session that holds the raw token server-side; never expose a shared token in browser JS or `NEXT_PUBLIC_*`.

## Task 03 — Retailer/tenant isolation

- Threaded authenticated retailer identity into the SQLAlchemy request session.
- Scoped inventory preview/import/dashboard, product lookups, Qloo mapping/evidence, plans, experiments, outcomes and agent inventory tools to that identity.
- Removed caller-selectable `retailer_id` from the `get_inventory` agent tool.
- Verification: two-retailer API isolation tests, guessed-ID 404 tests and agent-tool scope regression test pass.

## Task 08 — Competing experiment stock commitments

- Added exclusive reservation rows for each SKU included as target or bundle partner in an approved/running experiment.
- Rechecks stock and conflicts during approval and start, locking product rows in stable order and relying on a unique reservation constraint as an additional race guard.
- Conflict returns 409 `stock_commitment_conflict`; cancellation and completed outcomes release reservations. Physical stock is not silently decremented.
- Because the current contract has no planned units per SKU, the implementation conservatively allows at most one active approved/running experiment per SKU. This can over-block cases where separate unit allocations might safely coexist.
- Added PostgreSQL SQL migration at `backend/db/migrations/20261030_tasks_01_02_03_08_09_12.sql` for the reservation table and optional ISBN column.
- Verification: active overlap, bundle component, conflict and release regression tests pass.
- Not verified: migration has not been applied to the user's Render PostgreSQL database.

## Task 09 — Qloo entity matching accuracy

- Removed popularity/rating-count as identity proof.
- Exact title, subtitle and near-spelling candidates remain ambiguous unless corroborated by ISBN-13, matching publication year (with creator corroboration when supplied), or creator text in Qloo descriptive/disambiguation metadata.
- Added optional ISBN-13 to Product and CSV import/template with normalization/check-digit validation; existing CSVs without the column remain valid.
- Forced refresh cannot override a confirmed/rejected human decision.
- Verification: added matching tests for title-only ambiguity, creator/year/ISBN corroboration and conflicts; full suite passes.

## Task 12 — Evidence and provenance integrity

- Qloo evidence in a plan must preserve destination/source IDs, types when provided, nullable provider affinity, request parameters, fetch time, evidence row ID and exact `qloo_evidence:<id>` reference.
- Kept provider affinity distinct from internal similarity and ranking score; missing affinity remains null.
- Plan persistence verifies tenant/product ownership, Insights evidence kind, source entity, request parameters, timestamp and that the destination entity exists in the stored raw provider response.
- Rescue now fails closed with `plan_persistence_failed` rather than returning a seemingly usable plan when saving failed.
- Verification: regression tests for missing/forged provenance and failed plan persistence pass.

## Verification run

From `backend/`:

- `python -m pytest -q` → **399 passed**.
- `python -m compileall -q app` → **passed**.

Archive check:

- `scripts/package_release.py` → produced 112-file ZIP.
- ZIP inspection found no `.env` (except `.env.example`), DB, venv, `.git`, `node_modules`, Python bytecode or cache directories.
- History scan not performed on this extracted archive because it contains no `.git` metadata.

## Required before applying to the actual current branch / public demo

1. Reconcile this patch against the actual `feat/data-qa-deployment` branch; this implementation was generated from the older uploaded ZIP snapshot and is not a drop-in replacement for later branch changes.
2. Run `python scripts/scan_git_history.py` in the real clone after fetching all refs; review results and rotate any exposed provider credentials.
3. Generate a separate retailer token for each retailer; configure only its hash in the backend host.
4. Build a Vercel server-side proxy/session so browser requests never contain the raw shared token.
5. Back up Render PostgreSQL, apply the supplied SQL migration, and verify the new column/table and reservation uniqueness before deploying the application code.
6. Set exact `CORS_ORIGINS`, provider keys and token hashes in Render; deploy with one API worker or replace the in-process limiter with shared storage.
7. Run the full suite on the reconciled current branch and repeat PostgreSQL and hosted auth/tenant/overlap/provenance tests. No deployment or live secret changes are claimed by this work log.
