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
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.services import economics_service as eco

ACCOUNTING_BASIS = (
    "Gross profit = sum(units sold x (actual selling price - unit cost)) - additional direct campaign costs. "
    "Actual selling price is net of discounts (discounts are not subtracted twice). "
    "Labour, rent, packaging and platform fees are excluded unless entered as campaign costs."
)
MIN_COMPARABLE_DAYS = 7


class CalcError(ValueError):
    """Invalid input for an experiment calculation."""


def _r(x: float | Decimal | None, nd: int = 2) -> float | None:
    if x is None:
        return None
    value = Decimal(str(x)).quantize(Decimal("1").scaleb(-nd), rounding=ROUND_HALF_UP)
    return float(value)


def _decimal(value: float | int | Decimal, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CalcError(f"{field} must be a finite number") from exc
    if not result.is_finite():
        raise CalcError(f"{field} must be a finite number")
    return result


def _rate_change(units: float, days: float, b_units: float, b_days: float) -> tuple[float | None, float | None, float | None]:
    """(baseline_rate, actual_rate, change_pct).

    change_pct comes from economics_service.sales_change_pct, the single rule for
    this number: it is None when either period is shorter than MIN_COMPARABLE_DAYS
    or the baseline rate is 0 (a misleading percentage is never shown).
    """
    b_rate = b_units / b_days
    a_rate = units / days
    try:
        change = eco.sales_change_pct(b_units, b_days, units, days, MIN_COMPARABLE_DAYS)
    except eco.EconomicsError as e:
        raise CalcError(str(e)) from e
    return b_rate, a_rate, change


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
    """Calculate totals using the already validated, server-bound product rows.

    Each item contains `sku`, `units_sold`, `actual_selling_price` and the
    server-sourced `unit_cost`. Quantities are reconciled by experiment_service.
    """
    if not items:
        raise CalcError("At least one item (product sold) is required")
    if actual_days < 1:
        raise CalcError("actual_days must be at least 1")
    campaign_cost = _decimal(additional_costs, "additional_costs")
    if campaign_cost < 0:
        raise CalcError("additional_costs cannot be negative")
    if target_units_sold < 0:
        raise CalcError("target_units_sold cannot be negative")

    seen_skus: set[str] = set()
    revenue = Decimal("0")
    cogs = Decimal("0")
    for it in items:
        sku = str(it.get("sku", it.get("product_id", ""))).strip()
        if not sku:
            raise CalcError("Every outcome item must identify a SKU")
        if sku in seen_skus:
            raise CalcError(f"Duplicate SKU in outcome: {sku}")
        seen_skus.add(sku)
        units = it["units_sold"]
        if isinstance(units, bool) or not isinstance(units, int) or units < 0:
            raise CalcError(f"Invalid units_sold for SKU {sku}")
        price = _decimal(it["actual_selling_price"], f"actual_selling_price for {sku}")
        cost = _decimal(it["unit_cost"], f"unit_cost for {sku}")
        if price < 0 or cost < 0:
            raise CalcError(f"Negative value in item {sku}")
        if units > 0 and price <= 0:
            raise CalcError(f"Actual selling price must be greater than zero when SKU {sku} has sales")
        revenue += Decimal(units) * price
        cogs += Decimal(units) * cost

    gross_profit_before_campaign = revenue - cogs
    gross_profit = gross_profit_before_campaign - campaign_cost
    margin = (gross_profit / revenue * Decimal("100")) if revenue > 0 else None

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
        too_short = actual_days < MIN_COMPARABLE_DAYS or baseline_days < MIN_COMPARABLE_DAYS
        expected = b_rate * actual_days
        baseline = {
            "available": True,
            "baseline_units_per_day": _r(b_rate, 4),
            "experiment_units_per_day": _r(a_rate, 4),
            "expected_units_at_baseline_rate": None if too_short else _r(expected),
            "units_above_baseline_rate": None if too_short else _r(target_units_sold - expected),
            "sales_change_pct": _r(change),
        }
        if too_short:
            baseline["note"] = (
                f"A period is shorter than {MIN_COMPARABLE_DAYS} days, so no percentage change "
                "or comparison was calculated."
            )
            limitations.append(
                f"One of the periods is shorter than {MIN_COMPARABLE_DAYS} days; no percentage "
                "change was calculated because it would be misleading."
            )
        elif change is None:
            baseline["note"] = "Baseline sales rate is zero, so a percentage change is undefined."
            limitations.append("Baseline period had no sales; percentage change cannot be calculated.")
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
            limitations.append("Control comparison undefined (a zero baseline rate, or a period shorter than "
                f"{MIN_COMPARABLE_DAYS} days).")
    else:
        limitations.append("No comparable product or control period provided.")

    return {
        "revenue": _r(revenue),
        "cost_of_goods_sold": _r(cogs),
        "additional_direct_campaign_costs": _r(campaign_cost),
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
