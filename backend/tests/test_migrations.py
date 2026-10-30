"""Alembic integration test against a fresh, isolated SQLite database."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def test_fresh_database_migrates_to_head_without_schema_drift(tmp_path):
    backend_dir = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "fresh-stockrescue.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database_path}"
    env["PYTHONPATH"] = str(backend_dir)

    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir, env=env, capture_output=True, text=True, timeout=60,
    )
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr

    engine = create_engine(env["DATABASE_URL"])
    try:
        tables = set(inspect(engine).get_table_names())
        expected = {
            "products", "qloo_evidence", "qloo_entity_mappings", "rescue_plans",
            "rescue_experiments", "experiment_outcomes", "idempotency_records",
            "retailer_settings", "inventory_sales_snapshots", "alembic_version",
        }
        assert expected.issubset(tables)
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "20261030_settings_sales"
    finally:
        engine.dispose()

    check = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=backend_dir, env=env, capture_output=True, text=True, timeout=60,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert "No new upgrade operations detected" in check.stdout + check.stderr


def test_legacy_create_all_database_is_adopted_without_data_loss(tmp_path):
    """An existing pre-Alembic DB should be stamped forward, not rebuilt."""
    from app import models  # noqa: F401
    from app.db.session import Base
    from app.models import Product

    backend_dir = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "legacy-stockrescue.db"
    database_url = f"sqlite:///{database_path}"
    legacy_engine = create_engine(database_url)
    try:
        Base.metadata.create_all(legacy_engine)
        with legacy_engine.begin() as connection:
            connection.execute(text("""INSERT INTO products
                (retailer_id, sku, product_name, category, quantity_in_stock, unit_cost,
                 selling_price, created_at, updated_at)
                VALUES ('demo', 'LEGACY-1', 'Legacy record', 'Books', 7, 10, 20,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""))
            # Match an older version where the compatibility snapshot column
            # had not yet been introduced, and where no Alembic version table
            # or idempotency table exists.
            connection.execute(text("DROP TABLE idempotency_records"))
            connection.execute(text("DROP TABLE inventory_sales_snapshots"))
            connection.execute(text("DROP TABLE retailer_settings"))
            connection.execute(text("ALTER TABLE rescue_experiments DROP COLUMN product_snapshot"))
            connection.execute(text("ALTER TABLE rescue_experiments DROP COLUMN settings_snapshot"))
    finally:
        legacy_engine.dispose()

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["PYTHONPATH"] = str(backend_dir)
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir, env=env, capture_output=True, text=True, timeout=60,
    )
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            sku = connection.execute(text("SELECT sku FROM products WHERE sku='LEGACY-1'")).scalar_one()
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            columns = {row["name"] for row in inspect(connection).get_columns("rescue_experiments")}
        assert sku == "LEGACY-1"
        assert revision == "20261030_settings_sales"
        assert "product_snapshot" in columns
        assert "idempotency_records" in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    check = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=backend_dir, env=env, capture_output=True, text=True, timeout=60,
    )
    assert check.returncode == 0, check.stdout + check.stderr
