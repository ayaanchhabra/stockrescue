"""Ensure stock reservations and ISBN schema exists.

Revision ID: b52f3103668d
Revises: 20261030_settings_sales
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b52f3103668d"
down_revision: Union[str, None] = "20261030_settings_sales"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "experiment_stock_reservations" not in tables:
        op.create_table(
            "experiment_stock_reservations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("experiment_id", sa.Integer(), nullable=False),
            sa.Column("product_pk", sa.Integer(), nullable=False),
            sa.Column("retailer_id", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["experiment_id"], ["rescue_experiments.id"],
                ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["product_pk"], ["products.id"],
                ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "experiment_id", "product_pk",
                name="uq_experiment_product_reservation"
            ),
            sa.UniqueConstraint(
                "product_pk",
                name="uq_active_experiment_product_reservation"
            ),
        )

    inspector = sa.inspect(op.get_bind())
    existing_indexes = {
        index["name"]
        for index in inspector.get_indexes("experiment_stock_reservations")
    }

    expected_indexes = {
        "ix_experiment_stock_reservations_experiment_id": ["experiment_id"],
        "ix_experiment_stock_reservations_product_pk": ["product_pk"],
        "ix_experiment_stock_reservations_retailer_id": ["retailer_id"],
    }

    for name, columns in expected_indexes.items():
        if name not in existing_indexes:
            op.create_index(
                name,
                "experiment_stock_reservations",
                columns,
                unique=False,
            )

    inspector = sa.inspect(op.get_bind())
    product_columns = {
        column["name"] for column in inspector.get_columns("products")
    }

    if "isbn13" not in product_columns:
        with op.batch_alter_table("products") as batch_op:
            batch_op.add_column(
                sa.Column("isbn13", sa.String(13), nullable=True)
            )


def downgrade() -> None:
    # Preserve baseline objects already defined by the initial migration.
    pass