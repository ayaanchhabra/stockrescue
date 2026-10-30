"""Hard-constraint engine for StockRescue.

Takes a candidate strategy and the retailer's constraints and answers:
"may this be proposed at all, and if not, exactly why?"

Deterministic code only. The LLM cannot override a failed check.
Every failure carries a short code (for tests/UI) and a human-readable reason
(shown to the retailer as a rejected option).

Conventions
- One "unit" of a strategy = one sale of that strategy: one bundle, one
  discounted book, or one book sold in a new display.
- proposed_price is the price a customer pays for ONE unit of the strategy.
- Discount is measured against the sum of the items' normal selling prices.
- The margin floor applies to every strategy that changes the price or forms a
  bundle (promotion, bundle). A reposition at the normal price does not change
  the margin, so a product that is already below its floor is not blocked from
  a display; the result carries a WARNING instead (see ConstraintResult.warnings).
- Every strategy needs `planned_units` complete units in stock, because a test
  that can sell fewer cannot show a measurable change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Dict, List, Optional, Tuple

from . import economics_service as eco
from .economics_service import EconomicsError
from .rescue_config import Constraints

# Strategy type names. These match StrategyType values in schemas/rescue.py.
BUNDLE = "bundle"
REPOSITION = "reposition"
PROMOTION = "promotion"

# Violation codes
EMPTY_STRATEGY = "EMPTY_STRATEGY"
INVALID_PLAN = "INVALID_PLAN"
INVALID_PRICE = "INVALID_PRICE"
INVALID_PRODUCT_DATA = "INVALID_PRODUCT_DATA"
DUPLICATE_PRODUCT = "DUPLICATE_PRODUCT"
RESTRICTED_PRODUCT = "RESTRICTED_PRODUCT"
INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
BELOW_MIN_MARGIN = "BELOW_MIN_MARGIN"
DISCOUNT_TOO_HIGH = "DISCOUNT_TOO_HIGH"
OVER_BUDGET = "OVER_BUDGET"

# Warning codes (do not reject a strategy)
MARGIN_ALREADY_BELOW_FLOOR = "MARGIN_ALREADY_BELOW_FLOOR"


@dataclass(frozen=True)
class ProductRef:
    """The product facts the constraint engine needs (from the inventory)."""

    product_id: str
    name: str
    quantity: int
    unit_cost: float
    selling_price: float
    # Optional per-product limits from the CSV. Stricter of (global, product) wins.
    min_margin_pct: Optional[float] = None
    max_discount_pct: Optional[float] = None


@dataclass(frozen=True)
class CandidateStrategy:
    strategy_type: str
    name: str
    products: Tuple[ProductRef, ...]
    proposed_price: float
    estimated_experiment_cost: float = 0.0
    planned_units: int = 1  # how many units the test needs to be able to sell


@dataclass(frozen=True)
class Violation:
    code: str
    message: str


@dataclass(frozen=True)
class ConstraintResult:
    passed: bool
    violations: Tuple[Violation, ...] = ()
    # Calculated values (empty if the candidate was too invalid to calculate).
    metrics: Dict[str, float] = field(default_factory=dict)
    # Things the retailer should know that do NOT reject the strategy.
    warnings: Tuple[Violation, ...] = ()

    @property
    def reasons(self) -> List[str]:
        return [v.message for v in self.violations]

    @property
    def warning_messages(self) -> List[str]:
        return [w.message for w in self.warnings]

    @property
    def codes(self) -> List[str]:
        return [v.code for v in self.violations]


# ---------------------------------------------------------------------------
# Effective limits (global rule + optional per-product rule)
# ---------------------------------------------------------------------------

def effective_min_margin(products, constraints: Constraints) -> float:
    values = [constraints.min_margin_pct]
    values += [p.min_margin_pct for p in products if p.min_margin_pct is not None]
    return max(values)


def effective_max_discount(products, constraints: Constraints) -> float:
    values = [constraints.max_discount_pct]
    values += [p.max_discount_pct for p in products if p.max_discount_pct is not None]
    return min(values)


def _decimal(value, name: str) -> Decimal:
    """Convert user/database numbers without introducing binary-float rounding."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{name} must be a finite number")
    if not result.is_finite():
        raise ValueError(f"{name} must be a finite number")
    return result


def max_allowed_discount_pct(product: ProductRef, constraints: Constraints) -> float:
    """Largest safe two-decimal discount; round DOWN so it cannot breach margin."""
    price = _decimal(product.selling_price, "selling_price")
    cost = _decimal(product.unit_cost, "unit_cost")
    min_margin = _decimal(effective_min_margin([product], constraints), "min_margin_pct")
    cap = _decimal(effective_max_discount([product], constraints), "max_discount_pct")
    if min_margin >= Decimal("100"):
        return 0.0
    floor_price = cost / (Decimal("1") - min_margin / Decimal("100"))
    margin_cap = max(Decimal("0"), (price - floor_price) / price * Decimal("100"))
    safe = min(cap, margin_cap).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
    return float(safe)


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------

def check_candidate(
    candidate: CandidateStrategy, constraints: Constraints
) -> ConstraintResult:
    violations: List[Violation] = []

    def add(code: str, message: str) -> None:
        violations.append(Violation(code, message))

    products = candidate.products

    # Unknown strategy types fail closed. They must never receive an implicit exemption.
    if candidate.strategy_type not in (BUNDLE, REPOSITION, PROMOTION):
        add(INVALID_PLAN, f"Unsupported strategy type: {candidate.strategy_type!r}.")
        return ConstraintResult(False, tuple(violations))

    if not products:
        add(EMPTY_STRATEGY, "The strategy contains no products.")
        return ConstraintResult(False, tuple(violations))

    if candidate.proposed_price is None:
        add(INVALID_PRICE, "Proposed price must be greater than zero.")
        return ConstraintResult(False, tuple(violations))

    try:
        proposed_price = _decimal(candidate.proposed_price, "proposed_price")
        estimated_cost = _decimal(candidate.estimated_experiment_cost, "estimated_experiment_cost")
        product_costs = [_decimal(p.unit_cost, f"unit_cost for {p.name}") for p in products]
        product_prices = [_decimal(p.selling_price, f"selling_price for {p.name}") for p in products]
        min_margin = _decimal(effective_min_margin(products, constraints), "min_margin_pct")
        max_discount = _decimal(effective_max_discount(products, constraints), "max_discount_pct")
        budget = _decimal(constraints.max_campaign_budget, "max_campaign_budget")
    except (ValueError, TypeError) as exc:
        add(INVALID_PRODUCT_DATA, str(exc))
        return ConstraintResult(False, tuple(violations))

    if candidate.planned_units < 1:
        add(INVALID_PLAN, "Planned units must be at least 1.")
    if estimated_cost < 0:
        add(INVALID_PLAN, "Estimated experiment cost cannot be negative.")

    ids = [p.product_id for p in products]
    if len(set(ids)) != len(ids):
        add(DUPLICATE_PRODUCT, "The same product appears more than once in the strategy.")

    bad = []
    for p, price, cost in zip(products, product_prices, product_costs):
        try:
            quantity = _decimal(p.quantity, f"quantity for {p.name}")
        except ValueError:
            bad.append(p.name)
            continue
        if price <= 0 or cost < 0 or quantity < 0:
            bad.append(p.name)
    if bad:
        add(INVALID_PRODUCT_DATA,
            "Invalid price, cost or stock data for: " + ", ".join(bad) + ".")

    if proposed_price <= 0:
        add(INVALID_PRICE, "Proposed price must be greater than zero.")

    restricted = [p.name for p in products if p.product_id in constraints.restricted_product_ids]
    if restricted:
        add(RESTRICTED_PRODUCT, "Restricted by the retailer: " + ", ".join(restricted) + ".")

    if any(v.code in (INVALID_PRODUCT_DATA, INVALID_PRICE, INVALID_PLAN, DUPLICATE_PRODUCT)
           for v in violations):
        return ConstraintResult(False, tuple(violations))

    # --- stock -------------------------------------------------------------
    quantities = [int(p.quantity) for p in products]
    units_available = min(quantities)
    if units_available < candidate.planned_units:
        scarcest = min(products, key=lambda p: p.quantity)
        add(
            INSUFFICIENT_STOCK,
            f"Not enough stock to run a meaningful test: it needs "
            f"{candidate.planned_units} complete unit(s) but only {units_available} can be "
            f"supplied ('{scarcest.name}' has {scarcest.quantity} in stock).",
        )

    # --- economics: compare full-precision Decimal values; round only for display.
    unit_cost = sum(product_costs, Decimal("0"))
    separate_total = sum(product_prices, Decimal("0"))
    margin = (proposed_price - unit_cost) / proposed_price * Decimal("100")
    discount = (max(Decimal("0"), (separate_total - proposed_price) / separate_total * Decimal("100"))
                if separate_total > 0 else Decimal("0"))
    profit = proposed_price - unit_cost

    warnings: List[Violation] = []
    price_unchanged = candidate.strategy_type == REPOSITION and proposed_price == separate_total
    still_profitable = margin > 0
    if margin < min_margin:
        if price_unchanged and still_profitable:
            warnings.append(Violation(
                MARGIN_ALREADY_BELOW_FLOOR,
                f"This product's margin ({margin:.2f}%) is already below your "
                f"{min_margin:.2f}% minimum. The display does not change that.",
            ))
        else:
            floor_price = unit_cost / (Decimal("1") - min_margin / Decimal("100"))
            add(BELOW_MIN_MARGIN,
                f"Gross margin {margin:.2f}% is below the {min_margin:.2f}% minimum "
                f"(price would need to be at least Rs {floor_price:.2f}).")

    if discount > max_discount:
        add(DISCOUNT_TOO_HIGH,
            f"Discount of {discount:.2f}% exceeds the {max_discount:.2f}% maximum.")

    if estimated_cost > budget:
        add(OVER_BUDGET,
            f"Estimated cost Rs {estimated_cost:.2f} exceeds the Rs {budget:.2f} campaign budget.")

    metrics = {
        "unit_cost": round(float(unit_cost), 2),
        "proposed_price": round(float(proposed_price), 2),
        "profit_per_unit": round(float(profit), 2),
        "margin_pct": round(float(margin), 2),
        "discount_pct": round(float(discount), 2),
        "units_available": float(units_available),
        "planned_units": float(candidate.planned_units),
        "effective_min_margin": float(min_margin),
        "effective_max_discount": float(max_discount),
        "estimated_experiment_cost": float(estimated_cost),
    }
    return ConstraintResult(not violations, tuple(violations), metrics, tuple(warnings))
