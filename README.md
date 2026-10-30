# StockRescue

StockRescue helps independent retailers identify slow-moving inventory, explore Qloo-powered cultural associations across media categories, generate commercially constrained merchandising experiments, and measure recorded outcomes. Qloo signals are cultural hypotheses, not proof of local purchase intent or guaranteed sales uplift.

## Backend

See [`docs/api_contracts_person1.md`](docs/api_contracts_person1.md) for API contracts and setup notes.

### Database setup (required before starting the API)

Schema creation/evolution is managed by Alembic. From `backend/`, configure `DATABASE_URL`, then run:

```bash
python -m alembic upgrade head
python -m alembic current
python -m alembic check
```

Start the API only after migrations succeed:

```bash
python -m uvicorn app.main:app --reload
```

`GET /health` is a liveness check. `GET /ready` checks database connectivity, required tables, and whether the database is at the current Alembic head. It returns HTTP 503 until migrations have been applied. Application startup no longer calls `Base.metadata.create_all()`.

### Tests

```bash
cd backend
python -m pytest -q
```

The suite uses mocked Qloo responses for repeatable tests. It does not prove live connectivity.

### Qloo event smoke test

The current event access guide lists the public `@qloo/qloo-harness` surfaces (`qloo api`, `qloo exec`, `qloo explore`, `qloo mcp`) as the supported event path. Install Node.js 22.19.0+, install `@qloo/qloo-harness` 0.1.26+, and configure an individually attributable event credential with `qloo setup --qloo`. Then run `python qloo_smoke_test.py` from `backend/`. The script uses the harness CLI and emits sanitized status only. It requires the local CLI and outbound network access.

**Important integration limitation:** the StockRescue backend's current Qloo service still uses its Python HTTP transport. The harness smoke test verifies the approved CLI path but does not prove that the app's direct HTTP transport is event-authorized or live. Obtain organizer approval for that transport or move the runtime Qloo client to the harness before claiming event-compliant live integration. The current workspace has no Qloo CLI or event credential, so no successful live response is claimed here.

Do not put `.env`, database files, virtual environments, Git metadata or provider credentials in release archives. Start from `backend/.env.example` and supply secrets through environment variables.
