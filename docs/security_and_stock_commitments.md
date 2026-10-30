# StockRescue security, tenant boundaries, stock commitments and Qloo provenance

**Scope:** Tasks 01, 02, 03, 08, 09 and 12 from the 30 October 2026 roadmap.

## 01 — API keys, secrets and release artifacts

- Keep Qloo/LLM credentials in the backend host's secret environment, never in source control, a frontend `NEXT_PUBLIC_*` variable, a browser bundle, an exported ZIP, or logs.
- Generate a retailer bearer token once with `python scripts/generate_retailer_token.py <retailer-id>`. Save the raw token in an approved secret manager; the terminal shows it only once. The backend receives only `RETAILER_API_TOKEN_HASHES`, a JSON object mapping SHA-256 token hashes to retailer IDs.
- `python scripts/package_release.py --root . --output dist/stockrescue-release.zip` builds a sanitized archive, omitting `.env` files other than `.env.example`, local databases, virtual environments, bytecode, build outputs and common secret patterns. It inspects the ZIP after writing.
- From a Git checkout, run `python scripts/scan_git_history.py` after `git fetch --all`. It searches patches reachable from local refs for common credentials/private-key patterns. It intentionally reports only file/commit metadata, not secret values. Binary history and credentials not matching known patterns still need a manual/secret-scanner review.
- If a real credential was included in an archive or commit that left the trusted team boundary, revoke/rotate that credential at the provider. Removing it from the latest tree does not invalidate an exposed key.

## 02 — Authentication, authorization and request limits

All application API routes require `Authorization: Bearer <retailer-token>`. Only `/health`, API documentation (`/docs`, `/openapi.json`, `/redoc`) and CORS preflight are public. A missing/invalid token gets 401. If no token-hash map is configured, API traffic fails closed with 503 (`auth_not_configured`).

Example host configuration (hash only; do not paste the raw token here):

```text
RETAILER_API_TOKEN_HASHES={"<sha256-token-hash>":"demo"}
QLOO_REQUESTS_PER_MINUTE=15
RESCUE_RUNS_PER_MINUTE=5
CORS_ORIGINS=https://<your-vercel-host>
```

To revoke a retailer token, remove its hash from `RETAILER_API_TOKEN_HASHES` and restart/redeploy the API. Issue a replacement token and hash through the generator; never ask a retailer to send a token through chat or commit it to a file.

The current rate limiter is in-process and intended for a **single API worker**. It applies per retailer to Qloo status/search/resolve/Insights calls and rescue runs. Before using multiple workers or multiple instances, replace it with a shared limiter (for example Redis); otherwise quotas are per process.

**Frontend deployment boundary:** never place a shared backend bearer token in browser JavaScript, local storage, or `NEXT_PUBLIC_*`. A Vercel server-side route/proxy (or a real login/session system) must hold the raw token server-side and attach it to API requests. A static browser-only client cannot safely hold a shared retailer token. The current code does not implement a user login screen or Vercel proxy, so do not claim end-user authentication is complete until that client-side boundary is implemented and tested.

## 03 — Retailer/tenant isolation

The authenticated token determines `request.state.retailer_id`; the client cannot select a tenant in a request body or URL. `get_db()` transfers that authenticated value to the SQLAlchemy session. Product, inventory import/preview/dashboard, Qloo mapping/evidence, rescue plans, experiments, outcomes and agent inventory lookups are scoped through this session identity. Guessed IDs belonging to another retailer return not-found rather than revealing record existence.

The `demo` fallback in `retailer_id_for()` exists only for direct service/unit-test sessions that have no HTTP request context. HTTP requests reach database dependencies only after successful auth middleware and receive the token-derived tenant. Do not use this helper as a substitute for the middleware in a new HTTP entry point.

## 08 — Competing experiments and scarce stock

The current ExperimentCreate contract has no per-SKU planned-unit quantity. Rather than invent an amount to reserve, StockRescue uses a conservative exclusive policy: **a SKU can appear in at most one approved or running experiment at a time**, whether as the target or a bundle component. Proposed experiments do not reserve stock.

Approval and start both recheck all target/bundle SKUs under product-row locks, and create unique reservation rows. The reservation table's unique constraint is a second concurrency guard. A conflict returns HTTP 409 (`stock_commitment_conflict`) and the conflicting SKU list. Cancelling or completing an experiment releases its reservations. Actual on-hand quantity is never silently decremented by a reservation.

This is intentionally stricter than a quantity-based reservation and may block two experiments that could safely share stock. Implement quantity-aware commitments only after the API persists planned units per SKU and defines the approval/start accounting rule. There is no override path in this implementation.

## 09 — Qloo identity matching

Title equality, popularity and Goodreads rating-count dominance are not identity proof. Strong automatic matching now needs corroboration from a supplied ISBN-13, publication year (and creator corroboration where supplied), or creator text found in Qloo descriptive/disambiguation metadata. Exact-title, subtitle and close-spelling matches without corroboration remain ambiguous and require a human decision before Insights can run. A contradictory ISBN/year does not become a strong match.

The inventory contract accepts optional `isbn13`; it validates and normalizes the 13-digit ISBN check digit. Existing CSVs without the new column remain valid. If the retailer has no ISBN/year/creator and Qloo does not provide corroborating metadata, the correct state is review/coverage gap—not a fabricated certainty. Confirmed/rejected decisions remain final through forced refresh.

## 12 — Evidence/provenance integrity

A plan item labelled `source=qloo` must preserve the returned destination entity ID, source entity ID, destination/source entity types when available, nullable Qloo affinity, request parameters, fetch timestamp, evidence row ID and exact `qloo_evidence:<id>` reference. `qloo_affinity` remains separate from internal title similarity and strategy ranking. Missing affinity stays null; it is never inferred from popularity or internal similarity.

Before saving a plan, the backend verifies that its products belong to the authenticated retailer and that each Qloo claim's evidence row belongs to the target product, is an Insights record, has matching request parameters/source entity/timestamp, and contains the claimed destination entity in the stored provider response. Invalid/mismatched evidence aborts plan persistence. A rescue response is returned as usable only if the plan was saved; persistence failure returns 500 (`plan_persistence_failed`) without returning an apparently usable plan.

Qloo affinity indicates a provider relationship, not purchase intent or guaranteed sales uplift. Suggestions remain hypotheses to test.

## Existing PostgreSQL migration

For an existing PostgreSQL database, apply `backend/db/migrations/20261030_tasks_01_02_03_08_09_12.sql` **before** deploying the new application code. It adds the nullable ISBN-13 column and the stock-reservation table/indexes. `Base.metadata.create_all()` creates missing tables but does not add columns to an existing table; the SQL migration is necessary for the `isbn13` column. Back up the DB first and verify the resulting schema.

## Verification commands

```bash
cd backend
python -m compileall -q app
python -m pytest -q
cd ..
python scripts/scan_git_history.py       # run from a real Git checkout
python scripts/package_release.py --root . --output dist/stockrescue-release.zip
```

The package script checks the files being shipped; the Git history scanner checks local reachable commit patches. Neither proves that already published provider credentials have been rotated or that a remote deployment is configured correctly.
