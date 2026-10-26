# Person 1 API contracts (backend)

Errors always look like `{"error": "<code>", "message": "<human text>"}`.
Qloo failures: `qloo_not_configured` 503, `qloo_auth` 502, `qloo_timeout` 504, `qloo_rate_limited` 429,
`qloo_upstream` / `qloo_bad_response` 502. Other: `not_found` 404, `invalid_state` 409,
`needs_resolution` 409, `invalid_calculation_input` 422.

## Python functions (for Person 2, import directly - no HTTP needed)
```python
from app.services import qloo_service, entity_resolution_service as ers
from app.services.qloo_service import QlooError

mapping = ers.resolve_product(db, product_pk)             # QlooEntityMapping (stores raw evidence)
evidence_id, result = ers.insights_for_product(db, product_pk, take=10)   # InsightsResult
# result.entities -> [InsightEntity(entity_id, name, types, affinity|None, properties, raw)]
# Raises NeedsResolution if the match is ambiguous/none and not human-confirmed.
# Catch QlooError (e.kind) and continue with retailer metadata + label the coverage gap.
```
Save `evidence_id` values in `RescuePlan.evidence_ids` / `RescueExperiment.qloo_evidence_ids`.

## HTTP (for Person 3)
| Method | Path | Purpose |
|---|---|---|
| GET | /health | liveness + whether a Qloo key is configured |
| GET | /qloo/status | real connectivity test (one Qloo search) |
| GET | /qloo/search?query=&type=urn:entity:book | entity search |
| POST | /products/{pk}/qloo/resolve?force= | resolve product -> mapping (strong/ambiguous/none) |
| GET | /products/{pk}/qloo/mapping | current mapping (+ `coverage_gap`) |
| POST | /products/{pk}/qloo/confirm `{entity_id}` | human picks a candidate |
| POST | /products/{pk}/qloo/reject | human rejects the match |
| POST | /products/{pk}/qloo/insights `{take}` | real insights + `evidence_id` |
| GET | /experiments?status= | list |
| GET | /experiments/summary | counts and totals, observed vs simulated kept separate |
| POST | /experiments | create (status `proposed`) |
| PATCH | /experiments/{id} | edit while `proposed` |
| POST | /experiments/{id}/approve `{approved_by}` | proposed -> approved |
| POST | /experiments/{id}/reject | proposed -> rejected |
| POST | /experiments/{id}/start `{start_date,end_date}` | approved -> running |
| POST | /experiments/{id}/cancel | approved/running -> cancelled |
| POST | /experiments/{id}/outcome | running -> completed, returns calculated results |
| GET | /experiments/{id}/outcome | stored outcome |

Status flow: proposed -> approved -> running -> completed (or rejected / cancelled).
Product ids in these APIs are the internal integer `Product.id` ("product_pk"), not the CSV SKU.
