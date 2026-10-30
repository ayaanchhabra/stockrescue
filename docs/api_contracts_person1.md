# Backend API contract: Qloo and Experiments (Person 1)

Source of truth is the running app: `/openapi.json` and `/docs` on the backend. This file summarises it.
Code: `backend/app/api/qloo.py`, `backend/app/api/experiments.py`, `backend/app/schemas/`.
Product ids in all paths are the internal integer `Product.id` (`product_pk`), not the CSV SKU.
There is no authentication in the MVP. `retailer_id` defaults to `"demo"`.

## Error format

Our errors: `{"error": "<code>", "message": "<human text>"}`

| HTTP | error | Meaning |
|---|---|---|
| 503 | qloo_not_configured | QLOO_API_KEY missing |
| 502 | qloo_auth | Qloo rejected the key |
| 504 | qloo_timeout | Qloo timed out after retries |
| 429 | qloo_rate_limited | Qloo rate limit after retries |
| 502 | qloo_upstream / qloo_bad_response | Qloo error or non-JSON response |
| 404 | not_found | Product, experiment, evidence or outcome does not exist |
| 409 | invalid_state | Status change not allowed |
| 409 | needs_resolution | Insights requested without a strong or confirmed Qloo match |
| 422 | invalid_calculation_input | e.g. units sold exceed stock at start |
| 500 | internal_error | Unexpected; details only in server logs |
| 503 | plan_persistence_failed | Rescue plan could not be saved; the route returns no plan body and no plan-id header. |
| 409 | idempotency_conflict | An `Idempotency-Key` was reused with a different request body or unavailable resource. |

Request validation errors (wrong types, negatives) use FastAPI's default 422 body: `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`.

## Python functions (for the decision engine; no HTTP needed)

```python
from app.services import entity_resolution_service as ers
from app.services.qloo_service import QlooError
from app.errors import NeedsResolution

mapping = ers.resolve_product(db, product_pk)  # QlooEntityMapping; stores raw evidence
evidence_id, result = ers.insights_for_product(
    db, product_pk, take=10, target_type="urn:entity:movie"
)  # InsightsResult for one target category
```
Catch `QlooError` (`e.kind`) and `NeedsResolution`; continue with retailer data and label the Qloo coverage gap. The rescue gateway makes a bounded set of cross-category Insights requests (book, movie, artist, TV show and video game). These categories are allowlisted against Qloo's current Insights `filter.type` enum. Qloo's `query.affinity` is carried separately from internal product-match/ranking scores and remains null when the provider omits it. A result can inspire a display theme, but it is only eligible as a bundle partner when it matches a real stocked product.

## Qloo endpoints

| Method | Path | Notes |
|---|---|---|
| GET | /health | Liveness only: `{"status":"ok","qloo_key_configured":bool}`; does not probe the DB or Qloo. |
| GET | /ready | HTTP 200 only when DB is reachable, required tables exist, and Alembic is at head; otherwise HTTP 503 with `checks` and safe `details`. |
| GET | /qloo/status | Real connectivity test. Always HTTP 200: `{"ok":true,"sample_results":n,"from_cache":bool,"base_url":...}` or `{"ok":false,"error":kind,"message":...,"status_code":...}` |
| GET | /qloo/search?query=&type=urn:entity:book&take=5 | `{"query","candidates":[Candidate],"request_params","from_cache"}` |
| POST | /products/{pk}/qloo/resolve?force=false | Returns Mapping. A human-confirmed mapping is kept unless `force=true`. |
| GET | /products/{pk}/qloo/mapping | Mapping, or 404 if never resolved |
| POST | /products/{pk}/qloo/confirm | Body `{"entity_id"}` must be one of the stored candidates (else 404) |
| POST | /products/{pk}/qloo/reject | Marks the match rejected (coverage gap) |
| POST | /products/{pk}/qloo/insights | Optional body `{"take": 1..30}` (default 10). Returns `{"evidence_id", "result": Insights}`. 409 `needs_resolution` if no usable match. |
| GET | /qloo/evidence/{id} | The exact Qloo request and raw response: `{id, product_pk, kind, request_path, request_params, response_json, from_cache, fetched_at}` |

**Mapping:** `product_pk, qloo_entity_id, qloo_entity_type, matched_name, match_status ("strong"|"ambiguous"|"none"), match_reason, verification_status ("unverified"|"confirmed"|"rejected"), candidates[], evidence_id, last_checked_at, coverage_gap`.
`match_status` is OUR classification, not a Qloo score.

**Candidate:** `entity_id, name, types[], publication_year, isbn13, image_url, short_description, qloo_popularity, goodreads_ratings_count, creator_in_description, internal_name_similarity`.
`qloo_popularity` is Qloo's field; `goodreads_ratings_count` is Goodreads data relayed by Qloo; `internal_name_similarity` is ours.

**Insights:** `source_entity_id, target_type, endpoint, request_params, entities[], filtered_same_title_count, fetched_at, from_cache, raw (always null here; use the evidence endpoint)`.
**Insight entity:** `entity_id, name, types[], affinity (Qloo's query.affinity, may be null), popularity, tags[{id,name,type}], publication_year, image_url, short_description`.
Use only `urn:tag:genre:*` tags as cultural evidence. Tags like `urn:tag:age_ranges:*` are audience data and are not a reason for a recommendation.
An empty `entities` list means Qloo had no useful results.

Matching behaviour: one same-name entity is `strong`. Several same-name entities are `strong` only if one has at least 1000 Goodreads ratings and 10x more than the runner-up (the reason says so; please verify); otherwise `ambiguous`. Titles with a subtitle ("Sapiens" matches "Sapiens: A Brief History...") are handled. No candidates, or only loosely related titles (fewer than 60% of the query's words, ignoring words like "the" and "of", appear in the best candidate), gives `none`. Verified against real Qloo with invented titles; `none` means `qloo_entity_id` is null, `coverage_gap` is true, and insights return 409 `needs_resolution`.

## Experiments endpoints

Status flow: `proposed -> approved -> running -> completed`. Also `proposed -> rejected`, and `approved|running -> cancelled`. Completed, rejected and cancelled are final.

| Method | Path | Body | Result |
|---|---|---|---|
| GET | /experiments?status= | | list |
| POST | /experiments | create; accepts optional `Idempotency-Key` header (1–128 chars) | 201 for a new experiment; 200 when replaying the same key/body; 409 if the key is reused with a different body |
| GET | /experiments/{id} | | |
| PATCH | /experiments/{id} | any of `proposed_action, bundle_product_pks, proposed_price, estimated_cost, calculated_margin_pct` | only while `proposed`, else 409 |
| POST | /experiments/{id}/approve | optional `{"approved_by"}` | `approved` |
| POST | /experiments/{id}/reject | | `rejected` |
| POST | /experiments/{id}/cancel | | `cancelled` |
| POST | /experiments/{id}/start | `{"start_date","end_date"}` (end >= start) | `running` |
| POST | /experiments/{id}/outcome | see below | 201, `completed`. Only allowed while `running`. |
| GET | /experiments/{id}/outcome | | stored outcome, 404 if none |
| GET | /experiments/summary | | counts and totals |

**Create body:** `plan_id?, product_pk, strategy_type ("bundle"|"reposition"|"promotion"), title, proposed_action, bundle_product_pks[], proposed_price (>0), estimated_cost (>=0), calculated_margin_pct?, qloo_evidence_ids[]`.
`other` is intentionally unsupported and returns request validation 422; the service-level guard also fails closed for unknown strategy types. `calculated_margin_pct` is ignored and recomputed by the backend. Hard margin, discount and budget checks use unrounded Decimal values; rounding is only for response/display metrics. When `plan_id` is supplied, the backend verifies that target product, retailer, exact strategy, bundle partners and Qloo evidence all belong to that saved plan/strategy. Evidence rows must exist and belong to the target product.

**Outcome body:** `is_simulated, items[{sku, units_sold, actual_selling_price (net of discount), unit_cost?}], additional_costs, target_units_sold?, actual_days, baseline_units?, baseline_days? (both or neither), stock_at_start?, control?{baseline_units, baseline_days, experiment_units, experiment_days}, notes?`. `product_id` remains accepted as a backwards-compatible alias for `sku`; it always means the retailer SKU, not a database PK. `unit_cost` is deprecated/untrusted and ignored. The backend requires the outcome SKUs to exactly match the experiment's saved product snapshot, uses snapshot costs and starting stock, derives target units from the target SKU row, and rejects duplicate/unrelated/missing SKUs, mismatched target quantities, over-stock sales and unequal component quantities for bundles. `target_units_sold` and `stock_at_start` are optional consistency assertions, not sources of truth. `actual_days` must match the saved inclusive start/end date range.

**Outcome result:** `id, experiment_id, is_simulated, inputs, calculated, limitations[], notes, recorded_at`.
`calculated`: `revenue, cost_of_goods_sold, additional_direct_campaign_costs, gross_profit_before_campaign_costs, gross_profit, gross_margin_pct (null if no revenue), target_units_sold, inventory_remaining, baseline_comparison{available, baseline_units_per_day, experiment_units_per_day, expected_units_at_baseline_rate, units_above_baseline_rate, sales_change_pct (null if baseline rate is 0), note?}, control_comparison{available, control_sales_change_pct?, difference_vs_control_pct_points?}, accounting_basis, limitations`.
Gross profit = sum(units x (actual price - unit cost)) - additional direct campaign costs. Actual price is already net of discounts. Revenue is never reported as profit.
When `is_simulated` is true, the first limitation starts with "SIMULATED".

**Summary:** `plans_generated, experiments_by_status{}, experiments_total, observed{completed_experiments, units_sold, revenue, gross_profit, campaign_costs}, simulated{same fields}, note`. Observed and simulated totals are never combined.

## Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| QLOO_API_KEY | yes (for real Qloo) | empty | Without it Qloo endpoints return 503 `qloo_not_configured`; /health still works |
| DATABASE_URL | yes in production | `sqlite:///./stockrescue.db` | Use the PostgreSQL URL; `postgres://` and `postgresql://` are converted to `postgresql+psycopg2://` |
| CORS_ORIGINS | yes in production | `http://localhost:3000` | Comma-separated frontend URLs |
| QLOO_BASE_URL | no | `https://hackathon.api.qloo.com` | |
| QLOO_TIMEOUT_SECONDS | no | 15 | |
| QLOO_CACHE_TTL_SECONDS | no | 3600 | in-memory cache, per process |

Start command (from `backend/`): `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

Apply schema changes before starting the application: `alembic upgrade head` (from `backend/`). Use `/health` for process liveness and `/ready` for database/schema/migration readiness. Production startup does not mutate the schema; schema evolution is managed by Alembic. Use `alembic current` to inspect the installed revision and `alembic check` to detect model/schema drift.
## Person 2 urgent MVP additions — 30 October 2026

### Retailer settings

- `GET /settings` — authenticated; returns the retailer's persisted decision settings or documented MVP defaults.
- `PUT /settings` — authenticated full-document replacement; validates `currency=INR`, constraints, strategy defaults, ranking weights and slow-moving thresholds. A successful response returns the normalized saved document.
- New experiments store the validated settings document in `settings_snapshot`. Edit, approve and start rechecks use the saved experiment snapshot. Older saved plans with only a legacy constraints snapshot preserve those hard constraints.

### Inventory aggregates and sales snapshots

`GET /inventory/dashboard` also returns:
- `total_inventory_units`: sum of current on-hand quantity across retailer products.
- `potential_retail_value`: sum of quantity multiplied by current selling price; theoretical full-price value, not a sales forecast.

Each valid row imported by `POST /inventory/import` adds a dated `inventory_sales_snapshots` row. Missing sales values remain `null`.

- `GET /inventory/products/{product_pk}/sales-history` — authenticated and retailer-scoped; returns dated imported 30/60/90-day sales windows, source and days-in-stock values.

### Browser access flow

The frontend `/access` page accepts a retailer bearer token issued out-of-band and validates it via `GET /settings`. The current demo client stores that token in tab-scoped `sessionStorage` and attaches it to API requests. This is not a production OAuth/session design; use a short-lived server-side session before production deployment.

The CORS allow-method list includes `PUT` for the settings endpoint. Exact deployed frontend origin(s) must still be configured in `CORS_ORIGINS`.
