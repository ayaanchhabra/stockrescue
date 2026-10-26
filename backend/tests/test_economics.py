import pytest

from app.services import economics_service as eco
from app.services.economics_service import EconomicsError


# --- single product -------------------------------------------------------

def test_inventory_cost_tied_up_matches_example():
    # Example from the idea doc: 24 copies at Rs 350
    assert eco.inventory_cost_tied_up(24, 350) == 8400


def test_potential_retail_value():
    assert eco.potential_retail_value(24, 500) == 12000


def test_gross_profit_and_margin():
    assert eco.gross_profit_per_unit(500, 350) == 150
    assert eco.gross_margin_pct(500, 350) == 30.0


def test_negative_profit_is_allowed_but_visible():
    assert eco.gross_profit_per_unit(300, 350) == -50
    assert eco.gross_margin_pct(300, 350) < 0


@pytest.mark.parametrize("bad_price", [0, -10, None])
def test_zero_or_invalid_price_is_rejected(bad_price):
    with pytest.raises(EconomicsError):
        eco.gross_margin_pct(bad_price, 100)
    with pytest.raises(EconomicsError):
        eco.gross_profit_per_unit(bad_price, 100)


def test_negative_cost_or_quantity_rejected():
    with pytest.raises(EconomicsError):
        eco.gross_margin_pct(500, -1)
    with pytest.raises(EconomicsError):
        eco.inventory_cost_tied_up(-1, 100)


# --- discounts ------------------------------------------------------------

def test_discounted_price_and_resulting_margin():
    price = eco.discounted_price(500, 30)
    assert price == 350
    # 30% off a Rs 500 book with Rs 350 cost leaves zero margin
    assert eco.gross_margin_pct(price, 350) == 0


def test_discount_pct_out_of_range_rejected():
    with pytest.raises(EconomicsError):
        eco.discounted_price(500, 101)
    with pytest.raises(EconomicsError):
        eco.discounted_price(500, -5)


def test_discount_pct_between_prices():
    assert eco.discount_pct_between(500, 400) == 20.0
    assert eco.discount_pct_between(500, 500) == 0.0
    assert eco.discount_pct_between(500, 600) == 0.0  # markup is not a discount


def test_min_price_for_margin():
    # cost 350, want 30% margin -> price 500
    assert eco.min_price_for_margin(350, 30) == 500


def test_min_price_for_margin_rejects_100_percent():
    with pytest.raises(EconomicsError):
        eco.min_price_for_margin(350, 100)


def test_max_discount_for_margin():
    # price 500, cost 350, floor margin 15% -> floor price 411.76 -> ~17.65% off
    d = eco.max_discount_for_margin(500, 350, 15)
    assert 17.5 < d < 17.8


def test_max_discount_is_zero_when_full_price_already_below_minimum_margin():
    assert eco.max_discount_for_margin(400, 380, 20) == 0.0


# --- bundles --------------------------------------------------------------

def test_bundle_economics():
    costs = [350, 200]
    assert eco.bundle_unit_cost(costs) == 550
    assert eco.bundle_gross_profit(800, costs) == 250
    assert eco.bundle_margin_pct(800, costs) == 31.25


def test_bundle_below_cost_gives_negative_margin():
    assert eco.bundle_margin_pct(500, [350, 200]) < 0


def test_empty_bundle_rejected():
    with pytest.raises(EconomicsError):
        eco.bundle_unit_cost([])


def test_bundle_zero_price_rejected():
    with pytest.raises(EconomicsError):
        eco.bundle_margin_pct(0, [100, 100])


def test_bundle_effective_discount_vs_separate():
    # items sold separately for 500 + 400 = 900; bundle at 800 -> 11.11% off
    assert eco.bundle_discount_vs_separate_pct(800, [500, 400]) == 11.11


def test_max_complete_bundles_limited_by_scarcest_item():
    assert eco.max_complete_bundles([24, 5, 12]) == 5
    assert eco.max_complete_bundles([0, 10]) == 0


def test_max_complete_bundles_rejects_negative_or_empty():
    with pytest.raises(EconomicsError):
        eco.max_complete_bundles([5, -1])
    with pytest.raises(EconomicsError):
        eco.max_complete_bundles([])


# --- experiment outcomes --------------------------------------------------

def test_experiment_revenue_uses_actual_prices():
    assert eco.experiment_revenue([10, 5], [500, 400]) == 7000


def test_experiment_gross_profit_subtracts_campaign_costs_once():
    # 10 x (500-350) + 5 x (400-200) = 1500 + 1000 = 2500, minus 300 signage
    gp = eco.experiment_gross_profit([10, 5], [500, 400], [350, 200], 300)
    assert gp == 2200


def test_revenue_is_not_profit():
    rev = eco.experiment_revenue([10], [500])
    gp = eco.experiment_gross_profit([10], [500], [350])
    assert rev == 5000 and gp == 1500 and rev != gp


def test_experiment_length_mismatch_rejected():
    with pytest.raises(EconomicsError):
        eco.experiment_revenue([1, 2], [100])
    with pytest.raises(EconomicsError):
        eco.experiment_gross_profit([1], [100, 200], [50])


def test_experiment_margin_none_when_no_revenue():
    assert eco.experiment_margin_pct(0, 0) is None
    assert eco.experiment_margin_pct(5000, 1500) == 30.0


# --- sales change vs baseline --------------------------------------------

def test_sales_change_is_normalised_by_days():
    # baseline: 14 units / 14 days = 1/day; experiment: 21 units / 7 days = 3/day
    assert eco.sales_change_pct(14, 14, 21, 7) == 200.0


def test_sales_change_none_when_baseline_is_zero():
    assert eco.sales_change_pct(0, 14, 5, 14) is None


def test_sales_change_none_when_period_too_short():
    assert eco.sales_change_pct(10, 3, 12, 14) is None
    assert eco.sales_change_pct(10, 14, 12, 3) is None


def test_sales_change_negative_when_sales_fall():
    assert eco.sales_change_pct(14, 14, 7, 14) == -50.0


def test_sales_change_rejects_zero_length_period():
    with pytest.raises(EconomicsError):
        eco.sales_change_pct(10, 0, 10, 14)