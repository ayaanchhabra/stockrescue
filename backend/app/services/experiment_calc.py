"""Pure, dependency-free experiment maths. No DB, no FastAPI: easy to test.

Accounting basis (shown in the UI):
  * actual_selling_price is the price the customer really paid (already net of any
    discount), so discounts are NOT subtracted a second time.
  * additional_direct_campaign_costs = printing, signage, ads, etc. Labour, rent,
    packaging and platform fees are EXCLUDED unless the retailer includes them there.
  * gross_profit = sum(units * (price - unit_cost)) - additional_direct_campaign_costs
Revenue is never reported as profit.
"""
from __future__ import annotations

from typing import Any

ACCOUNTING_BASIS = (
    "Gross profit = sum(units sold x (actual selling price - unit cost)) - additional direct campaign costs. "
    "Actual selling price is net of discounts (discounts are not subtracted twice). "
    "Labour, rent, packaging and platform fees are excluded unless entered as campaign costs."
)
MIN_COMPARABLE_DAYS = 7


class CalcError(ValueError):
    """Invalid input for an experiment calculation."""


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(x + 0.0, nd)


def _rate_change(units: float, days: float, b_units: float, b_days: float) -> tuple[float | None, float | None, float | None]:
    """(baseline_rate, actual_rate, change_pct). change_pct is None if baseline rate is 0."""
    b_rate = b_units / b_days
    a_rate = units / days
    if b_rate <= 0:
        return b_rate, a_rate, None
    return b_rate, a_rate, (a_rate - b_rate) / b_rate * 100


def compute_outcome(
    *,
    items: list[dict],
    additional_costs: float,
    target_units_sold: int,
    actual_days: int,
    baseline_units: int | None = None,
    baseline_days: int | None = None,
    stock_at_start: int | None = None,
    control: dict | None = None,
    is_simulated: bool = False,
) -> dict[str, Any]:
    """items: [{product_id, units_sold, actual_selling_price, unit_cost}, ...]"""
    if not items:
        raise CalcError("At least one item (product sold) is required")
    if actual_days < 1:
        raise CalcError("actual_days must be at least 1")
    if additional_costs < 0:
        raise CalcError("additional_costs cannot be negative")
    if target_units_sold < 0:
        raise CalcError("target_units_sold cannot be negative")

    revenue = cogs = 0.0
    for it in items:
        u, p, c = it["units_sold"], it["actual_selling_price"], it["unit_cost"]
        if u < 0 or p < 0 or c < 0:
            raise CalcError(f"Negative value in item {it.get('product_id')}")
        revenue += u * p
        cogs += u * c

    gross_profit_before_campaign = revenue - cogs
    gross_profit = gross_profit_before_campaign - additional_costs
    margin = (gross_profit / revenue * 100) if revenue > 0 else None

    inventory_remaining = None
    if stock_at_start is not None:
        if target_units_sold > stock_at_start:
            raise CalcError("Units sold of the target product exceed stock at the start of the experiment")
        inventory_remaining = stock_at_start - target_units_sold

    limitations: list[str] = [
        "A before/after difference is not proof that the intervention caused the change "
        "(seasonality, foot traffic, placement, price and other factors may contribute).",
    ]
    if is_simulated:
        limitations.insert(0, "SIMULATED outcome: entered for demonstration, not observed retail data.")

    baseline: dict[str, Any] = {"available": False}
    have_baseline = baseline_units is not None and baseline_days is not None
    if have_baseline:
        if baseline_units < 0 or baseline_days < 1:
            raise CalcError("baseline_units must be >= 0 and baseline_days >= 1")
        b_rate, a_rate, change = _rate_change(target_units_sold, actual_days, baseline_units, baseline_days)
        expected = b_rate * actual_days
        baseline = {
            "available": True,
            "baseline_units_per_day": _r(b_rate, 4),
            "experiment_units_per_day": _r(a_rate, 4),
            "expected_units_at_baseline_rate": _r(expected),
            "units_above_baseline_rate": _r(target_units_sold - expected),
            "sales_change_pct": _r(change),
        }
        if change is None:
            baseline["note"] = "Baseline sales rate is zero, so a percentage change is undefined."
            limitations.append("Baseline period had no sales; percentage change cannot be calculated.")
        if actual_days < MIN_COMPARABLE_DAYS or baseline_days < MIN_COMPARABLE_DAYS:
            limitations.append(f"One of the periods is shorter than {MIN_COMPARABLE_DAYS} days; results are noisy.")
        if abs(actual_days - baseline_days) > max(actual_days, baseline_days) * 0.5:
            limitations.append("Baseline and experiment periods differ a lot in length; compared per day only.")
    else:
        limitations.append("No baseline provided; no comparison was calculated.")

    control_out: dict[str, Any] = {"available": False}
    if control:
        try:
            cb_u, cb_d = control["baseline_units"], control["baseline_days"]
            ce_u, ce_d = control["experiment_units"], control["experiment_days"]
        except KeyError as e:
            raise CalcError(f"control is missing field {e}")
        if cb_u < 0 or ce_u < 0 or cb_d < 1 or ce_d < 1:
            raise CalcError("control units must be >= 0 and control days >= 1")
        _, _, c_change = _rate_change(ce_u, ce_d, cb_u, cb_d)
        control_out = {"available": True, "control_sales_change_pct": _r(c_change)}
        if c_change is not None and baseline.get("sales_change_pct") is not None:
            control_out["difference_vs_control_pct_points"] = _r(baseline["sales_change_pct"] - c_change)
        else:
            limitations.append("Control comparison undefined (control or target baseline rate is zero).")
    else:
        limitations.append("No comparable product or control period provided.")

    return {
        "revenue": _r(revenue),
        "cost_of_goods_sold": _r(cogs),
        "additional_direct_campaign_costs": _r(additional_costs),
        "gross_profit_before_campaign_costs": _r(gross_profit_before_campaign),
        "gross_profit": _r(gross_profit),
        "gross_margin_pct": _r(margin),
        "target_units_sold": target_units_sold,
        "inventory_remaining": inventory_remaining,
        "baseline_comparison": baseline,
        "control_comparison": control_out,
        "accounting_basis": ACCOUNTING_BASIS,
        "limitations": limitations,
    }
