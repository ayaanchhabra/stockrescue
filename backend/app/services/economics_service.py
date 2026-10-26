"""Deterministic economics for StockRescue.

Every financial number shown in the app comes from this module.
The LLM never calculates or overrides these values.

Accounting assumptions (state these in the UI):
- Money is in a single currency (INR in the demo).
- "Gross profit" = selling price - unit cost, before rent, labour, packaging,
  platform fees, or any other operating cost.
- Direct campaign costs (e.g. printed signage) are subtracted only where a
  function says so explicitly.
- Revenue is never profit.
"""

from __future__ import annotations

from typing import Iterable, Sequence


class EconomicsError(ValueError):
    """Raised when an input would make a calculation meaningless or unsafe."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _require_non_negative(value: float, name: str) -> None:
    if value is None or value < 0:
        raise EconomicsError(f"{name} must be >= 0 (got {value!r})")


def _require_positive_price(price: float) -> None:
    if price is None or price <= 0:
        raise EconomicsError(f"selling price must be > 0 (got {price!r})")


def _require_pct(pct: float, name: str) -> None:
    if pct is None or pct < 0 or pct > 100:
        raise EconomicsError(f"{name} must be between 0 and 100 (got {pct!r})")


def _r(value: float, places: int = 2) -> float:
    """Round a money/percentage value for display. Keep raw values for checks."""
    return round(value, places)


# ---------------------------------------------------------------------------
# Single product
# ---------------------------------------------------------------------------

def inventory_cost_tied_up(quantity: int, unit_cost: float) -> float:
    """quantity x unit_cost"""
    _require_non_negative(quantity, "quantity")
    _require_non_negative(unit_cost, "unit_cost")
    return _r(quantity * unit_cost)


def potential_retail_value(quantity: int, selling_price: float) -> float:
    """quantity x selling_price (value if everything sold at full price)."""
    _require_non_negative(quantity, "quantity")
    _require_non_negative(selling_price, "selling_price")
    return _r(quantity * selling_price)


def gross_profit_per_unit(selling_price: float, unit_cost: float) -> float:
    """selling_price - unit_cost. May be negative (a loss) and that is allowed."""
    _require_positive_price(selling_price)
    _require_non_negative(unit_cost, "unit_cost")
    return _r(selling_price - unit_cost)


def gross_margin_pct(selling_price: float, unit_cost: float) -> float:
    """((selling_price - unit_cost) / selling_price) x 100"""
    _require_positive_price(selling_price)
    _require_non_negative(unit_cost, "unit_cost")
    return _r((selling_price - unit_cost) / selling_price * 100)


def discounted_price(selling_price: float, discount_pct: float) -> float:
    """Price after a percentage discount."""
    _require_positive_price(selling_price)
    _require_pct(discount_pct, "discount_pct")
    return _r(selling_price * (1 - discount_pct / 100))


def discount_pct_between(original_price: float, new_price: float) -> float:
    """Discount % implied by moving from original_price to new_price.

    Returns 0 if new_price >= original_price (that is a markup, not a discount).
    """
    _require_positive_price(original_price)
    _require_non_negative(new_price, "new_price")
    if new_price >= original_price:
        return 0.0
    return _r((original_price - new_price) / original_price * 100)


def min_price_for_margin(unit_cost: float, min_margin_pct: float) -> float:
    """Lowest selling price that still meets min_margin_pct.

    margin = (p - c) / p  =>  p = c / (1 - margin)
    """
    _require_non_negative(unit_cost, "unit_cost")
    if min_margin_pct is None or min_margin_pct < 0 or min_margin_pct >= 100:
        raise EconomicsError(
            f"min_margin_pct must be >= 0 and < 100 (got {min_margin_pct!r})"
        )
    return _r(unit_cost / (1 - min_margin_pct / 100))


def max_discount_for_margin(
    selling_price: float, unit_cost: float, min_margin_pct: float
) -> float:
    """Largest discount % that keeps margin >= min_margin_pct.

    Returns 0.0 if even the full price does not meet the minimum margin.
    """
    floor_price = min_price_for_margin(unit_cost, min_margin_pct)
    _require_positive_price(selling_price)
    if floor_price >= selling_price:
        return 0.0
    return discount_pct_between(selling_price, floor_price)


# ---------------------------------------------------------------------------
# Bundles
# ---------------------------------------------------------------------------

def bundle_unit_cost(unit_costs: Sequence[float]) -> float:
    """Sum of the unit costs of the items in ONE bundle."""
    if not unit_costs:
        raise EconomicsError("a bundle needs at least one item")
    for c in unit_costs:
        _require_non_negative(c, "unit_cost")
    return _r(sum(unit_costs))


def bundle_gross_profit(bundle_price: float, unit_costs: Sequence[float]) -> float:
    """bundle_price - sum(unit costs)."""
    _require_positive_price(bundle_price)
    return _r(bundle_price - bundle_unit_cost(unit_costs))


def bundle_margin_pct(bundle_price: float, unit_costs: Sequence[float]) -> float:
    """((bundle_price - bundle_cost) / bundle_price) x 100"""
    _require_positive_price(bundle_price)
    cost = bundle_unit_cost(unit_costs)
    return _r((bundle_price - cost) / bundle_price * 100)


def bundle_discount_vs_separate_pct(
    bundle_price: float, separate_prices: Sequence[float]
) -> float:
    """How much cheaper the bundle is than buying the items separately.

    This is the 'effective discount' a customer sees. Returns 0 if the bundle
    costs the same or more than the separate prices.
    """
    if not separate_prices:
        raise EconomicsError("a bundle needs at least one item")
    for p in separate_prices:
        _require_positive_price(p)
    return discount_pct_between(sum(separate_prices), bundle_price)


def max_complete_bundles(stock_levels: Iterable[int]) -> int:
    """How many complete bundles can be assembled (limited by the scarcest item).

    Assumes one unit of each item per bundle. Raises if an item has negative stock.
    """
    levels = list(stock_levels)
    if not levels:
        raise EconomicsError("a bundle needs at least one item")
    for q in levels:
        _require_non_negative(q, "stock level")
    return int(min(levels))


# ---------------------------------------------------------------------------
# Experiment outcomes
# ---------------------------------------------------------------------------

def experiment_revenue(
    units_sold: Sequence[int], actual_prices: Sequence[float]
) -> float:
    """sum(units_sold_i x actual_price_i). Prices are what customers really paid
    (after any discount), so discounts are NOT subtracted a second time."""
    if len(units_sold) != len(actual_prices):
        raise EconomicsError("units_sold and actual_prices must have the same length")
    total = 0.0
    for u, p in zip(units_sold, actual_prices):
        _require_non_negative(u, "units_sold")
        _require_non_negative(p, "actual price")
        total += u * p
    return _r(total)


def experiment_gross_profit(
    units_sold: Sequence[int],
    actual_prices: Sequence[float],
    unit_costs: Sequence[float],
    direct_campaign_costs: float = 0.0,
) -> float:
    """sum(units_i x (price_i - cost_i)) - direct_campaign_costs.

    direct_campaign_costs covers only costs caused by the experiment (signage,
    printing, ads). It does not include rent, labour, or platform fees.
    """
    if not (len(units_sold) == len(actual_prices) == len(unit_costs)):
        raise EconomicsError("units, prices and costs must have the same length")
    _require_non_negative(direct_campaign_costs, "direct_campaign_costs")
    total = 0.0
    for u, p, c in zip(units_sold, actual_prices, unit_costs):
        _require_non_negative(u, "units_sold")
        _require_non_negative(p, "actual price")
        _require_non_negative(c, "unit_cost")
        total += u * (p - c)
    return _r(total - direct_campaign_costs)


def experiment_margin_pct(revenue: float, gross_profit: float) -> float | None:
    """gross_profit / revenue x 100, or None when revenue is zero."""
    _require_non_negative(revenue, "revenue")
    if revenue == 0:
        return None
    return _r(gross_profit / revenue * 100)


def sales_change_pct(
    baseline_units: float,
    baseline_days: int,
    experiment_units: float,
    experiment_days: int,
    min_days: int = 7,
) -> float | None:
    """% change in daily sales rate versus the baseline period.

    Returns None (not a misleading number) when the comparison is not valid:
    - baseline is zero (cannot divide by it),
    - either period is shorter than min_days.

    This is a before/after difference, NOT proof the experiment caused it.
    """
    _require_non_negative(baseline_units, "baseline_units")
    _require_non_negative(experiment_units, "experiment_units")
    if baseline_days <= 0 or experiment_days <= 0:
        raise EconomicsError("period lengths must be > 0 days")
    if baseline_days < min_days or experiment_days < min_days:
        return None
    if baseline_units <= 0:
        return None
    baseline_rate = baseline_units / baseline_days
    experiment_rate = experiment_units / experiment_days
    return _r((experiment_rate - baseline_rate) / baseline_rate * 100)