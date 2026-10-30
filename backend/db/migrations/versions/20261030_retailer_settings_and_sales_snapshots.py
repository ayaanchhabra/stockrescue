"""add retailer decision settings and dated inventory sales snapshots

Revision ID: 20261030_settings_sales
Revises: 27c4190e336d
Create Date: 2026-10-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261030_settings_sales"
down_revision: Union[str, None] = "27c4190e336d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rescue_experiments", sa.Column("settings_snapshot", sa.JSON(), nullable=True))
    op.execute("UPDATE rescue_experiments SET settings_snapshot = '{}' WHERE settings_snapshot IS NULL")
    with op.batch_alter_table("rescue_experiments") as batch_op:
        batch_op.alter_column("settings_snapshot", existing_type=sa.JSON(), nullable=False)

    op.create_table(
        "retailer_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("retailer_id", sa.String(length=64), nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("retailer_id", name="uq_retailer_settings_retailer"),
    )
    op.create_index("ix_retailer_settings_retailer_id", "retailer_settings", ["retailer_id"], unique=False)

    op.create_table(
        "inventory_sales_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("retailer_id", sa.String(length=64), nullable=False),
        sa.Column("product_pk", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("units_sold_30d", sa.Integer(), nullable=True),
        sa.Column("units_sold_60d", sa.Integer(), nullable=True),
        sa.Column("units_sold_90d", sa.Integer(), nullable=True),
        sa.Column("days_in_stock", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["product_pk"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_sales_snapshots_retailer_id", "inventory_sales_snapshots", ["retailer_id"], unique=False)
    op.create_index("ix_inventory_sales_snapshots_product_pk", "inventory_sales_snapshots", ["product_pk"], unique=False)
    op.create_index(
        "ix_sales_snapshot_retailer_product_time", "inventory_sales_snapshots",
        ["retailer_id", "product_pk", "imported_at"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sales_snapshot_retailer_product_time", table_name="inventory_sales_snapshots")
    op.drop_index("ix_inventory_sales_snapshots_product_pk", table_name="inventory_sales_snapshots")
    op.drop_index("ix_inventory_sales_snapshots_retailer_id", table_name="inventory_sales_snapshots")
    op.drop_table("inventory_sales_snapshots")
    op.drop_index("ix_retailer_settings_retailer_id", table_name="retailer_settings")
    op.drop_table("retailer_settings")
    with op.batch_alter_table("rescue_experiments") as batch_op:
        batch_op.drop_column("settings_snapshot")
