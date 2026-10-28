# Person 2 handoff: Decision Engine

Branch: `feat/decision-engine` (not merged yet). Full design: `docs/decision-engine.md`.

## Status

Test suite: **338 passed** (306 Person 2 + 32 Person 1) with `python -m pytest -q` from `backend/`. `pytest -q tests` and `pytest -q app/tests` also pass on their own.

| File | Status | Tests |
|---|---|---|
| `app/services/economics_service.py` | done | 32 |
| `app/services/constraints_service.py` | done | 25 |
| `app/services/ranking_service.py` | done | 18 |
| `app/services/matcher_service.py` | done | 29 |
| `app/services/strategy_generator.py` | done | 45 |
| `app/services/plan_builder.py` | done | 27 |
| `app/services/rescue_config.py` | done (+ `ExplanationSettings`) | covered |
| `app/schemas/rescue.py` | done (contract, unchanged) | covered |
| `app/agent/workflow.py` | done (pipeline) | 27 |
| `app/agent/prompts.py`, `app/agent/explanation.py` | **new**: LLM prompt and numeric guard | 26 |
| `app/agent/llm.py` | **new**: OpenAI-compatible / Anthropic client via httpx | 11 |
| `app/agent/adapters.py` | **new**: Product → engine inputs, `DbQlooGateway` over P1's entity resolution, plan save/load, strategy → experiment | 27 |
| `app/schemas/rescue_api.py`, `app/api/rescue.py` | **new**: rescue API (4 routes) | 22 |
| `app/agent/tools.py` | **new**: named tool registry (master plan names) | 8 |
| `tests/test_evaluation_cases.py` | **new**: 9 named feasible/infeasible scenarios | 9 |
| `tests/conftest.py`, `tests/p2_helpers.py` | **new**: in-memory DB, fake key, network blocked, row helpers | |

Also verified by a scratch smoke test (not in the repo): Person 1's real `app.main` with this router mounted, and Person 1's real `qloo_service`/`entity_resolution_service` fed test-double HTTP replies. Resolve → insights → plan → saved evidence → `X-Rescue-Plan-Id` → experiment created → approved by P1's route. With no Qloo key, the route returns 200 with `qloo_status="error"`.

## Person 1: two changes in `app/main.py` (I did not edit your file)

```python
from app.api import experiments, health, qloo, rescue   # add rescue
...
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list,
                   allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Rescue-Plan-Id"])          # add this argument
...
app.include_router(rescue.router)                               # add this line
```

## Person 3: what the frontend needs

- `POST /rescue/{product_pk}` (optional body `{"constraints": {...}, "refresh_qloo": false}`) returns the `RescuePlan` (contract in `app/schemas/rescue.py`, example in `docs/decision-engine.md`). Read the plan id from the response header `X-Rescue-Plan-Id`.
- **All `product_id` values in a plan are the integer pk as a string**, so `int(product_id)` works directly with `/products/{pk}/qloo/...` and `/experiments`.
- Qloo evidence `raw_ref` = `"qloo_evidence:{id}"`. Show the raw response with `GET /qloo/evidence/{id}`.
- `qloo_status = ambiguous`: show `qloo_note` (it lists the alternatives). After the retailer confirms an entity (`POST /products/{pk}/qloo/confirm`), call `POST /rescue/{pk}` again to get Qloo-backed strategies.
- `stages_failed` non-empty means the plan is partial; show `limitations`.
- Workspace edits (price, partner, discount): call `POST /rescue/evaluate` to get recalculated economics and violations. Never calculate margins in the browser. Then `PATCH /experiments/{id}` with the new `proposed_price` and `calculated_margin_pct`.
- "Create experiment" button: `POST /rescue/plans/{plan_id}/strategies/{rank}/experiment` (201, P1's `ExperimentOut`, status `proposed`). Then use P1's approve/start/outcome routes.
- `llm_explanation` is LLM-written (it may be `null`). Style it as "AI explanation", visually distinct from calculated values and Qloo evidence.

## Person 4: deploy and data

- The rescue route needs products in the `products` table (your CSV importer, or `seed_dev.py` locally).
- Render env vars for LLM text (optional; the app works without them): `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, and `LLM_BASE_URL` if needed. They are listed in `backend/.env.example`.
- No new Python dependencies were added.

## Decisions I made (tell the team)

1. **Decision-engine `product_id` = `str(Product.id)`, not the SKU.** Every P1 route and `ExperimentCreate` use the pk. This differs from the naming map in `docs/business_rules.md` §8 (SKU → product_id). The mapping lives only in `app/agent/adapters.py`.
2. **Stored Qloo mapping is reused** on each rescue run (so a person's confirm/reject is respected and Qloo is not re-queried). `refresh_qloo: true` forces a fresh resolve.
3. **A rejected mapping** (a person said "wrong book") is treated as `no_match`. **A confirmed mapping** is `strong_match`.
4. **LLM guard allow-list** is slightly wider than "names, rank and test days": any number already present in the strategy's code-written text is allowed. It is still safe, because those numbers were all computed by the system.
5. **Plan saving is best-effort.** If the DB write fails, the plan is still returned, without the header.
6. Per-request constraint overrides merge over the defaults. Restricted ids are added to the defaults, never removed.
7. `tools.py` is a registry only. The workflow stays the bounded pipeline, and no LLM chooses tools.

## Open items (not built around)

- P4's CSV sales-snapshot question is still open. Intended answer: the four snapshot fields are replaced together, and an all-blank row changes nothing. The engine only reads what is recorded (`has_sales_history`).
- Default weights rank the themed display above the bundle. Weights are unchanged on purpose.
- Out of scope: CSV import, the dashboard, outcome maths (P1 has it), frontend, migrations, the counterfactual comparison, the feedback loop.

## Manual steps for me (Person 2)

1. Copy these files into my repo, then run `cd backend && python -m pytest -q` on my own machine (expect 338 passed).
2. Review, then commit and push on `feat/decision-engine`. Send P1 the `main.py` snippet above.
