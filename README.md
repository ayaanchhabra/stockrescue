# StockRescue

StockRescue helps independent retailers identify slow-moving inventory, discover Qloo-supported cultural associations, generate commercially constrained rescue strategies, and measure controlled experiments. Cultural associations are hypotheses, not proof of demand or guaranteed sales uplift.

## Project structure

- `backend/` — FastAPI API, business rules, Qloo integration, SQLAlchemy models and Alembic migrations.
- `frontend/` — Next.js application for inventory upload, dashboard, rescue workflows, experiments, retailer settings and API access.
- `docs/` — business rules, data contracts, testing plan, security and Person 2 handoff notes.

## Backend setup

Use Python 3.11+ (the requirements use FastAPI, Pydantic 2 and SQLAlchemy 2). From `backend/`:

```bash
python -m venv .venv
# Activate the environment, then:
pip install -r requirements.txt
cp .env.example .env
```

Set the required values in `backend/.env` or the deployment environment. At minimum, configure:

- `DATABASE_URL` — SQLite for local development or PostgreSQL for a hosted deployment.
- `RETAILER_API_TOKEN_HASHES` — JSON mapping SHA-256 token hashes to retailer IDs; raw tokens are issued out-of-band and must not be committed.
- `CORS_ORIGINS` — exact frontend origin(s).
- `QLOO_API_KEY` — only through the access path approved for the current Qloo event.

Apply schema migrations before starting the API. Production startup does not create or mutate tables automatically:

```bash
cd backend
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`. `/health` checks process liveness; `/ready` checks database connectivity and current Alembic revision. All application routes except documented public health/docs paths require a retailer bearer token.

## Frontend setup

From `frontend/`:

```bash
npm ci
# Create frontend/.env.local and set NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Open `http://localhost:3000`, then visit **API access** and paste the retailer token issued out-of-band. The demo UI stores it only in the current browser session. Use HTTPS outside localhost. This is a lightweight hackathon access flow, not a production OAuth/session replacement.

The **Settings** page updates persisted retailer constraints and strategy defaults. Existing experiments retain the settings snapshot captured when they were created.

## Tests and checks

```bash
cd backend
python -m compileall -q app
python -m pytest -q
python -m pytest tests/test_migrations.py -q
```

Frontend checks (after `npm ci`):

```bash
cd frontend
npm run typecheck
npm run lint
npm run build
```

The backend automated tests use mocked Qloo responses for isolated tests. They do **not** prove live Qloo connectivity. Run `python qloo_smoke_test.py` from `backend/` in an environment with the current event-approved Qloo harness installed and configured, then record the sanitized result. Run a PostgreSQL migration/transaction test and externally verify deployment before claiming production readiness.

## Accounting notes

- Currency for this MVP is INR.
- Experiment outcomes use saved product cost snapshots and actual customer-paid prices.
- Actual selling prices are net of discounts; discounts are not subtracted a second time.
- Gross profit = revenue − cost of goods sold − additional direct campaign costs. Labour, rent, packaging and platform fees are excluded unless entered as campaign costs.
- Simulated outcomes remain separate from observed outcomes.
- Before/after changes are descriptive and are not proof that the intervention caused the change.

## Important documentation

- `docs/business_rules.md` — commercial and inventory rules.
- `docs/inventory_data_contract.md` — CSV and product data contract.
- `docs/test_plan.md` — manual end-to-end test cases.
- `docs/security_and_stock_commitments.md` — authentication, tenant and stock reservation design.
- `docs/URGENT_MVP_IMPLEMENTATION_HANDOFF.md` — this implementation's verified changes and remaining manual work.

## Demo limitations

The live Qloo event flow, PostgreSQL environment, hosted deployment, and complete manual T01–T10 run must be verified with the team's real credentials and target infrastructure. Do not present mocked provider tests as live API evidence or simulated outcomes as observed retail results.
