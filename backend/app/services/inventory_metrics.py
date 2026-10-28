"""Transparent slow-moving inventory rules and dashboard calculations.

This module contains no database writes and no HTTP routes. It consumes
Product objects and returns assessments that the API layer can serialize
after the frontend contract is agreed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from app.models.entities import Product

RuleName = Literal[
    "no_recent_sales",
    "aged_stock",
    "low_sales_velocity",
]

ProductStatus = Literal[
    "needs_attention",
    "not_enough_data_to_assess",
    "no_attention_rule_triggered",
]


@dataclass(frozen=True)
class SlowMovingSettings:
    """Configurable team defaults, not industry facts."""

    no_recent_sales_min_stock_days: int = 30
    aged_stock_days: int = 90
    low_sales_cover_days: int = 180

    def __post_init__(self) -> None:
        if self.no_recent_sales_min_stock_days < 1:
            raise ValueError("no_recent_sales_min_stock_days must be >= 1")
        if self.aged_stock_days < 1:
            raise ValueError("aged_stock_days must be >= 1")
        if self.low_sales_cover_days < 1:
            raise ValueError("low_sales_cover_days must be >= 1")


DEFAULT_SLOW_MOVING_SETTINGS = SlowMovingSettings()

SALES_WINDOW_DAYS = 30

SALES_COLUMNS = (
    "units_sold_30d",
    "units_sold_60d",
    "units_sold_90d",
)


@dataclass(frozen=True)
class ProductAssessment:
    product_pk: int | None
    sku: str
    product_name: str
    category: str
    quantity_in_stock: int
    unit_cost: float
    inventory_cost_tied_up: float
    status: ProductStatus
    rules_triggered: tuple[RuleName, ...]
    explanations: tuple[str, ...]
    stock_cover_days: float | None


@dataclass(frozen=True)
class InventoryDashboard:
    total_products: int
    needs_attention_count: int
    not_enough_data_count: int
    total_inventory_cost_tied_up: float
    flagged_inventory_cost_tied_up: float
    rule_counts: dict[str, int]
    thresholds: dict[str, int]
    rule_descriptions: dict[str, str]
    metric_descriptions: dict[str, str]
    products_needing_attention: tuple[ProductAssessment, ...]
    products_not_enough_data: tuple[ProductAssessment, ...]


def _money(value: float) -> float:
    """Return monetary figures rounded to two decimal places."""
    return round(float(value), 2)


def assess_product(
    product: Product,
    settings: SlowMovingSettings = DEFAULT_SLOW_MOVING_SETTINGS,
) -> ProductAssessment:
    """Apply the documented slow-moving rules to one inventory product."""

    quantity = product.quantity_in_stock
    unit_cost = float(product.unit_cost)
    days_in_stock = product.days_in_stock
    sold_30 = product.units_sold_30d

    stock_cover_days: float | None = None
    if sold_30 is not None and sold_30 > 0:
        stock_cover_days = quantity * SALES_WINDOW_DAYS / sold_30

    rules: list[RuleName] = []
    explanations: list[str] = []

    # A known age shorter than the sales window means the product is too new
    # to assess from that window. Unknown age does not automatically disqualify it.
    old_enough_for_sales_window = (
        days_in_stock is None or days_in_stock >= SALES_WINDOW_DAYS
    )

    # Rule 1: a recorded zero is different from missing sales data.
    if (
        sold_30 == 0
        and (
            days_in_stock is None
            or days_in_stock >= settings.no_recent_sales_min_stock_days
        )
    ):
        rules.append("no_recent_sales")
        explanations.append(
            f"Recorded zero sales in the last {SALES_WINDOW_DAYS} days; "
            f"stock age is at least {settings.no_recent_sales_min_stock_days} "
            "days or is unknown."
        )

    # Rule 2: age alone is sufficient to flag aged stock.
    if (
        days_in_stock is not None
        and days_in_stock >= settings.aged_stock_days
    ):
        rules.append("aged_stock")
        explanations.append(
            f"Stock has been held for at least {settings.aged_stock_days} days."
        )

    # Rule 3: only apply the 30-day velocity window if the product is old
    # enough for that window, or its age is unknown.
    if (
        sold_30 is not None
        and sold_30 > 0
        and old_enough_for_sales_window
        and stock_cover_days is not None
        and stock_cover_days > settings.low_sales_cover_days
    ):
        rules.append("low_sales_velocity")
        explanations.append(
            f"Current stock covers more than {settings.low_sales_cover_days} "
            f"days at the recorded {SALES_WINDOW_DAYS}-day sales rate "
            f"(estimated cover: {stock_cover_days:.2f} days)."
        )

    has_any_sales_data = any(
        getattr(product, column) is not None for column in SALES_COLUMNS
    )

    if rules:
        status: ProductStatus = "needs_attention"
    elif not has_any_sales_data and days_in_stock is None:
        status = "not_enough_data_to_assess"
        explanations.append(
            "Sales history and stock age are both missing; there is not "
            "enough data to assess this product."
        )
    else:
        status = "no_attention_rule_triggered"
        explanations.append(
            "None of the configured slow-moving rules triggered on the "
            "available data. This does not imply that every business risk "
            "has been ruled out."
        )

    return ProductAssessment(
        product_pk=product.id,
        sku=product.sku,
        product_name=product.product_name,
        category=product.category,
        quantity_in_stock=quantity,
        unit_cost=unit_cost,
        inventory_cost_tied_up=_money(quantity * unit_cost),
        status=status,
        rules_triggered=tuple(rules),
        explanations=tuple(explanations),
        stock_cover_days=(
            round(stock_cover_days, 2)
            if stock_cover_days is not None
            else None
        ),
    )


def build_inventory_dashboard(
    products: Sequence[Product],
    settings: SlowMovingSettings = DEFAULT_SLOW_MOVING_SETTINGS,
) -> InventoryDashboard:
    """Calculate summary metrics and rank flagged products by tied-up cost."""

    assessments = [assess_product(product, settings) for product in products]

    flagged = [
        item for item in assessments if item.status == "needs_attention"
    ]
    insufficient = [
        item
        for item in assessments
        if item.status == "not_enough_data_to_assess"
    ]

    # Most inventory cost tied up appears first; use stable tie-breakers.
    flagged.sort(
        key=lambda item: (
            -item.inventory_cost_tied_up,
            item.product_name.casefold(),
            item.sku,
        )
    )

    rule_names = (
        "no_recent_sales",
        "aged_stock",
        "low_sales_velocity",
    )
    rule_counts = {
        rule: sum(rule in item.rules_triggered for item in assessments)
        for rule in rule_names
    }

    thresholds = {
        "sales_window_days": SALES_WINDOW_DAYS,
        "no_recent_sales_min_stock_days": settings.no_recent_sales_min_stock_days,
        "aged_stock_days": settings.aged_stock_days,
        "low_sales_cover_days": settings.low_sales_cover_days,
    }

    rule_descriptions = {
        "no_recent_sales": (
            f"Recorded zero sales over {SALES_WINDOW_DAYS} days "
            f"and stock age of at least {settings.no_recent_sales_min_stock_days} "
            "days or unknown."
        ),
        "aged_stock": (
            f"Current stock has been held for at least "
            f"{settings.aged_stock_days} days."
        ),
        "low_sales_velocity": (
            f"Positive sales in the recorded {SALES_WINDOW_DAYS}-day period "
            f"and stock cover greater than {settings.low_sales_cover_days} days."
        ),
    }

    metric_descriptions = {
        "total_products": (
            "Count of products in the current inventory snapshot when "
            "the dashboard is requested."
        ),
        "needs_attention_count": (
            "Count of products with at least one slow-moving rule triggered, "
            "using the currently stored units_sold_30d and days_in_stock values. "
            "Sales history represents the last recorded 30-day period."
        ),
        "not_enough_data_count": (
            "Count of products with all three sales-history fields and "
            "days_in_stock missing in the current inventory snapshot."
        ),
        "total_inventory_cost_tied_up": (
            "Sum of quantity_in_stock multiplied by unit_cost across all "
            "products in the current inventory snapshot."
        ),
        "flagged_inventory_cost_tied_up": (
            "Sum of quantity_in_stock multiplied by unit_cost for products "
            "where at least one slow-moving rule fires, using the current "
            "inventory snapshot."
        ),
    }

    return InventoryDashboard(
        total_products=len(assessments),
        needs_attention_count=len(flagged),
        not_enough_data_count=len(insufficient),
        total_inventory_cost_tied_up=_money(
            sum(item.inventory_cost_tied_up for item in assessments)
        ),
        flagged_inventory_cost_tied_up=_money(
            sum(item.inventory_cost_tied_up for item in flagged)
        ),
        rule_counts=rule_counts,
        thresholds=thresholds,
        rule_descriptions=rule_descriptions,
        metric_descriptions=metric_descriptions,
        products_needing_attention=tuple(flagged),
        products_not_enough_data=tuple(insufficient),
    )
