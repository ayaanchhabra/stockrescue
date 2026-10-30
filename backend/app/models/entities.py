"""All database tables. Money is stored as Float rounded to 2 dp (hackathon scope)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Float,
                        ForeignKey, Index, Integer, String, Text, UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("quantity_in_stock >= 0", name="ck_qty_nonneg"),
        CheckConstraint("unit_cost >= 0", name="ck_cost_nonneg"),
        CheckConstraint("selling_price > 0", name="ck_price_pos"),
        UniqueConstraint("retailer_id", "sku", name="uq_retailer_sku"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_id: Mapped[str] = mapped_column(String(64), default="demo", index=True)
    sku: Mapped[str] = mapped_column(String(64), index=True)  # CSV column "product_id"
    product_name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(100), default="Books")
    creator_or_brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    isbn13: Mapped[str | None] = mapped_column(String(13), nullable=True)
    quantity_in_stock: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[float] = mapped_column(Float)
    selling_price: Mapped[float] = mapped_column(Float)
    # Optional; NULL means "not provided", never 0
    units_sold_30d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    units_sold_60d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    units_sold_90d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_in_stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    genre_or_subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True)
    publication_or_release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    seasonality: Mapped[str | None] = mapped_column(String(100), nullable=True)
    minimum_acceptable_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    maximum_discount_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RetailerSettings(Base):
    """Persisted decision-engine configuration for one authenticated retailer."""
    __tablename__ = "retailer_settings"
    __table_args__ = (UniqueConstraint("retailer_id", name="uq_retailer_settings_retailer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class InventorySalesSnapshot(Base):
    """One dated 30/60/90-day sales snapshot per product import."""
    __tablename__ = "inventory_sales_snapshots"
    __table_args__ = (Index("ix_sales_snapshot_retailer_product_time", "retailer_id", "product_pk", "imported_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    product_pk: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="inventory_csv", nullable=False)
    units_sold_30d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    units_sold_60d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    units_sold_90d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_in_stock: Mapped[int | None] = mapped_column(Integer, nullable=True)


class QlooEvidence(Base):
    """Raw Qloo response, stored verbatim so the UI can show real provenance."""
    __tablename__ = "qloo_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_pk: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20))  # "resolve" | "insights"
    request_path: Mapped[str] = mapped_column(String(100))
    request_params: Mapped[dict[str, Any]] = mapped_column(JSON)
    response_json: Mapped[Any] = mapped_column(JSON)
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QlooEntityMapping(Base):
    __tablename__ = "qloo_entity_mappings"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_pk: Mapped[int] = mapped_column(ForeignKey("products.id"), unique=True, index=True)
    qloo_entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    qloo_entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    matched_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    match_status: Mapped[str] = mapped_column(String(20))  # strong | ambiguous | none (OUR classification)
    match_reason: Mapped[str] = mapped_column(String(300), default="")
    verification_status: Mapped[str] = mapped_column(String(20), default="unverified")  # unverified|confirmed|rejected
    candidates: Mapped[list[Any]] = mapped_column(JSON, default=list)
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("qloo_evidence.id"), nullable=True)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RescuePlan(Base):
    __tablename__ = "rescue_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_id: Mapped[str] = mapped_column(String(64), default="demo")
    product_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)  # internal product ids
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|rejected
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    evidence_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    constraints_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ranking_rationale: Mapped[Any] = mapped_column(JSON, default=dict)
    plan_json: Mapped[Any] = mapped_column(JSON, default=dict)  # full RescuePlan from Person 2
    experiments: Mapped[list["RescueExperiment"]] = relationship(back_populates="plan")


class RescueExperiment(Base):
    __tablename__ = "rescue_experiments"
    __table_args__ = (
        Index(
            "uq_plan_strategy_live", "plan_id", "product_pk", "title", "strategy_type",
            unique=True,
            sqlite_where=text("status NOT IN ('rejected', 'cancelled')"),
            postgresql_where=text("status NOT IN ('rejected', 'cancelled')"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("rescue_plans.id"), nullable=True, index=True)
    product_pk: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)  # target slow mover
    strategy_type: Mapped[str] = mapped_column(String(30))  # bundle | reposition | promotion (unsupported values rejected at the API/service boundary)
    title: Mapped[str] = mapped_column(String(200))
    proposed_action: Mapped[str] = mapped_column(Text)
    bundle_product_pks: Mapped[list[Any]] = mapped_column(JSON, default=list)
    # Target + partner SKU/cost/stock snapshot (refreshed when the experiment starts).
    product_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Exact retailer decision configuration used when this experiment was created.
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    proposed_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    calculated_margin_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    qloo_evidence_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    plan: Mapped["RescuePlan | None"] = relationship(back_populates="experiments")
    outcome: Mapped["ExperimentOutcome | None"] = relationship(back_populates="experiment", uselist=False)


class ExperimentStockReservation(Base):
    """Exclusive commitment of a SKU to one active approved/running test."""
    __tablename__ = "experiment_stock_reservations"
    __table_args__ = (
        UniqueConstraint("product_pk", name="uq_active_experiment_product_reservation"),
        UniqueConstraint("experiment_id", "product_pk", name="uq_experiment_product_reservation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("rescue_experiments.id", ondelete="CASCADE"), index=True
    )
    product_pk: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    retailer_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRecord(Base):
    """Tenant-scoped record preventing duplicate experiment creation on retries."""
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("retailer_id", "idempotency_key", name="uq_idempotency_retailer_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExperimentOutcome(Base):
    __tablename__ = "experiment_outcomes"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("rescue_experiments.id"), unique=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON)       # exactly what the retailer entered
    calculated: Mapped[dict[str, Any]] = mapped_column(JSON)   # deterministic results
    limitations: Mapped[list[Any]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    experiment: Mapped["RescueExperiment"] = relationship(back_populates="outcome")
