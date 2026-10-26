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
- The margin floor applies to every strategy (including repositioning at full
  price): it is the retailer's "minimum acceptable margin" rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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

    @property
    def reasons(self) -> List[str]:
        return [v.message for v in self.violations]

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


def max_allowed_discount_pct(product: ProductRef, constraints: Constraints) -> float:
    """Largest discount % on ONE product that satisfies BOTH the discount cap
    and the margin floor. Use this to size a controlled-promotion strategy."""
    eff_min = effective_min_margin([product], constraints)
    eff_cap = effective_max_discount([product], constraints)
    margin_cap = eco.max_discount_for_margin(
        product.selling_price, product.unit_cost, eff_min
    )
    return round(min(eff_cap, margin_cap), 2)


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

    # --- structural problems: cannot calculate anything --------------------
    if not products:
        add(EMPTY_STRATEGY, "The strategy contains no products.")
        return ConstraintResult(False, tuple(violations))

    if candidate.planned_units < 1:
        add(INVALID_PLAN, "Planned units must be at least 1.")
    if candidate.estimated_experiment_cost < 0:
        add(INVALID_PLAN, "Estimated experiment cost cannot be negative.")

    ids = [p.product_id for p in products]
    if len(set(ids)) != len(ids):
        add(DUPLICATE_PRODUCT, "The same product appears more than once in the strategy.")

    bad = [
        p.name
        for p in products
        if p.selling_price is None or p.selling_price <= 0
        or p.unit_cost is None or p.unit_cost < 0
        or p.quantity is None or p.quantity < 0
    ]
    if bad:
        add(
            INVALID_PRODUCT_DATA,
            "Invalid price, cost or stock data for: " + ", ".join(bad) + ".",
        )

    if candidate.proposed_price is None or candidate.proposed_price <= 0:
        add(INVALID_PRICE, "Proposed price must be greater than zero.")

    restricted = [p.name for p in products if p.product_id in constraints.restricted_product_ids]
    if restricted:
        add(RESTRICTED_PRODUCT, "Restricted by the retailer: " + ", ".join(restricted) + ".")

    if any(v.code in (INVALID_PRODUCT_DATA, INVALID_PRICE, INVALID_PLAN, DUPLICATE_PRODUCT)
           for v in violations):
        # Do not calculate on bad inputs.
        return ConstraintResult(False, tuple(violations))

    # --- stock -------------------------------------------------------------
    units_available = eco.max_complete_bundles([p.quantity for p in products])
    if units_available < candidate.planned_units:
        scarcest = min(products, key=lambda p: p.quantity)
        add(
            INSUFFICIENT_STOCK,
            f"Only {units_available} complete unit(s) can be supplied but the test "
            f"needs {candidate.planned_units}; '{scarcest.name}' has {scarcest.quantity} in stock.",
        )

    # --- economics ---------------------------------------------------------
    costs = [p.unit_cost for p in products]
    separate_prices = [p.selling_price for p in products]
    unit_cost = eco.bundle_unit_cost(costs)
    margin = eco.bundle_margin_pct(candidate.proposed_price, costs)
    profit = eco.bundle_gross_profit(candidate.proposed_price, costs)
    discount = eco.bundle_discount_vs_separate_pct(candidate.proposed_price, separate_prices)

    eff_min = effective_min_margin(products, constraints)
    eff_cap = effective_max_discount(products, constraints)

    if margin < eff_min - 1e-9:
        floor_price = eco.min_price_for_margin(unit_cost, eff_min)
        add(
            BELOW_MIN_MARGIN,
            f"Gross margin {margin:.2f}% is below the {eff_min:.2f}% minimum "
            f"(price would need to be at least Rs {floor_price:.2f}).",
        )

    if discount > eff_cap + 1e-9:
        add(
            DISCOUNT_TOO_HIGH,
            f"Discount of {discount:.2f}% exceeds the {eff_cap:.2f}% maximum.",
        )

    if candidate.estimated_experiment_cost > constraints.max_campaign_budget + 1e-9:
        add(
            OVER_BUDGET,
            f"Estimated cost Rs {candidate.estimated_experiment_cost:.2f} exceeds the "
            f"Rs {constraints.max_campaign_budget:.2f} campaign budget.",
        )

    metrics = {
        "unit_cost": unit_cost,
        "proposed_price": candidate.proposed_price,
        "profit_per_unit": profit,
        "margin_pct": margin,
        "discount_pct": discount,
        "units_available": float(units_available),
        "planned_units": float(candidate.planned_units),
        "effective_min_margin": eff_min,
        "effective_max_discount": eff_cap,
        "estimated_experiment_cost": candidate.estimated_experiment_cost,
    }
    return ConstraintResult(not violations, tuple(violations), metrics)
