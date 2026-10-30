"""Process liveness and database/schema readiness diagnostics."""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text

from app.config import settings
from app.db.session import engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """Liveness only: does not probe the DB or spend external-provider quota."""
    return {"status": "ok", "qloo_key_configured": bool(settings.qloo_api_key)}


def _alembic_config() -> Config:
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", settings.sqlalchemy_url.replace("%", "%%"))
    return config


@router.get("/ready")
def ready():
    """Readiness: DB reachable, expected schema present, and migrations at head."""
    checks = {"database": False, "schema": False, "migrations": False}
    details: dict[str, str] = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            checks["database"] = True
            table_names = set(inspect(connection).get_table_names())
            required = {
                "products", "qloo_evidence", "qloo_entity_mappings", "rescue_plans",
                "rescue_experiments", "experiment_outcomes", "idempotency_records",
                "retailer_settings", "inventory_sales_snapshots",
            }
            missing = sorted(required - table_names)
            checks["schema"] = not missing
            if missing:
                details["schema"] = "Missing tables: " + ", ".join(missing)
            current = MigrationContext.configure(connection).get_current_revision()
            head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
            checks["migrations"] = bool(current and head and current == head)
            if not checks["migrations"]:
                details["migrations"] = f"Database revision is {current or 'unversioned'}; expected {head or 'a migration head'}."
    except Exception as exc:  # noqa: BLE001 - readiness should report a safe, typed result
        details["database"] = f"Readiness check failed ({type(exc).__name__})."

    is_ready = all(checks.values())
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"status": "ready" if is_ready else "not_ready", "checks": checks, "details": details},
    )
