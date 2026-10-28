from app.models.entities import Product
from app.services.inventory_metrics import (
    DEFAULT_SLOW_MOVING_SETTINGS,
    SlowMovingSettings,
    assess_product,
    build_inventory_dashboard,
)


def make_product(
    *,
    sku="B001",
    name="Test Book",
    quantity=10,
    unit_cost=20.0,
    sold_30=None,
    sold_60=None,
    sold_90=None,
    days_in_stock=None,
):
    return Product(
        sku=sku,
        product_name=name,
        category="Books",
        quantity_in_stock=quantity,
        unit_cost=unit_cost,
        selling_price=40.0,
        units_sold_30d=sold_30,
        units_sold_60d=sold_60,
        units_sold_90d=sold_90,
        days_in_stock=days_in_stock,
    )


def test_no_recent_sales_triggers_at_30_days():
    result = assess_product(
        make_product(sold_30=0, days_in_stock=30)
    )

    assert result.status == "needs_attention"
    assert "no_recent_sales" in result.rules_triggered


def test_no_recent_sales_also_triggers_when_stock_age_is_unknown():
    result = assess_product(make_product(sold_30=0, days_in_stock=None))

    assert "no_recent_sales" in result.rules_triggered


def test_zero_sales_with_stock_age_below_30_days_does_not_trigger_that_rule():
    result = assess_product(make_product(sold_30=0, days_in_stock=29))

    assert "no_recent_sales" not in result.rules_triggered


def test_aged_stock_triggers_at_90_days():
    result = assess_product(make_product(days_in_stock=90))

    assert result.status == "needs_attention"
    assert "aged_stock" in result.rules_triggered


def test_low_sales_velocity_triggers_above_180_days_stock_cover():
    # 61 units at 10 units per 30 days = 183 days of stock cover.
    result = assess_product(
        make_product(quantity=61, sold_30=10, days_in_stock=30)
    )

    assert result.stock_cover_days == 183.0
    assert "low_sales_velocity" in result.rules_triggered


def test_exactly_180_days_stock_cover_does_not_trigger():
    # 60 units at 10 units per 30 days = exactly 180 days.
    result = assess_product(
        make_product(quantity=60, sold_30=10, days_in_stock=30)
    )

    assert result.stock_cover_days == 180.0
    assert "low_sales_velocity" not in result.rules_triggered


def test_product_too_new_for_sales_window_is_not_flagged_for_velocity():
    result = assess_product(
        make_product(quantity=100, sold_30=1, days_in_stock=20)
    )

    assert "low_sales_velocity" not in result.rules_triggered


def test_missing_sales_and_stock_age_means_insufficient_data():
    result = assess_product(
        make_product(
            sold_30=None,
            sold_60=None,
            sold_90=None,
            days_in_stock=None,
        )
    )

    assert result.status == "not_enough_data_to_assess"
    assert result.rules_triggered == ()


def test_multiple_rules_can_trigger_for_one_product():
    result = assess_product(make_product(sold_30=0, days_in_stock=120))

    assert result.status == "needs_attention"
    assert "no_recent_sales" in result.rules_triggered
    assert "aged_stock" in result.rules_triggered


def test_inventory_cost_tied_up_is_quantity_times_unit_cost():
    result = assess_product(
        make_product(quantity=12, unit_cost=27.25)
    )

    assert result.inventory_cost_tied_up == 327.0


def test_dashboard_ranks_flagged_products_by_inventory_cost():
    low_cost = make_product(
        sku="LOW",
        name="Low Cost Book",
        quantity=10,
        unit_cost=5,
        sold_30=0,
        days_in_stock=40,
    )
    high_cost = make_product(
        sku="HIGH",
        name="High Cost Book",
        quantity=20,
        unit_cost=50,
        sold_30=0,
        days_in_stock=40,
    )
    unknown = make_product(
        sku="UNKNOWN",
        name="Unknown History Book",
        quantity=7,
        unit_cost=10,
    )

    dashboard = build_inventory_dashboard([low_cost, high_cost, unknown])

    assert dashboard.total_products == 3
    assert dashboard.needs_attention_count == 2
    assert dashboard.not_enough_data_count == 1

    assert [
        item.sku for item in dashboard.products_needing_attention
    ] == ["HIGH", "LOW"]

    assert dashboard.total_inventory_cost_tied_up == 1_120.0
    assert dashboard.flagged_inventory_cost_tied_up == 1_050.0


def test_dashboard_reports_rule_counts_and_thresholds():
    products = [
        make_product(sku="A", sold_30=0, days_in_stock=30),
        make_product(sku="B", sold_30=10, days_in_stock=90),
    ]

    dashboard = build_inventory_dashboard(products)

    assert dashboard.rule_counts["no_recent_sales"] == 1
    assert dashboard.rule_counts["aged_stock"] == 1
    assert dashboard.thresholds["sales_window_days"] == 30
    assert dashboard.thresholds["aged_stock_days"] == 90
    assert "low_sales_velocity" in dashboard.rule_descriptions


def test_custom_thresholds_are_applied():
    settings = SlowMovingSettings(
        no_recent_sales_min_stock_days=20,
        aged_stock_days=60,
        low_sales_cover_days=120,
    )
    result = assess_product(
        make_product(sold_30=0, days_in_stock=20),
        settings,
    )

    assert "no_recent_sales" in result.rules_triggered
    assert settings != DEFAULT_SLOW_MOVING_SETTINGS


def test_dashboard_metrics_include_calculations_and_periods():
    dashboard = build_inventory_dashboard([
        make_product(sold_30=0, days_in_stock=30)
    ])

    descriptions = dashboard.metric_descriptions

    assert "current inventory snapshot" in descriptions["total_products"]
    assert "30-day period" in descriptions["needs_attention_count"]
    assert "quantity_in_stock" in descriptions["total_inventory_cost_tied_up"]
    assert "unit_cost" in descriptions["total_inventory_cost_tied_up"]
    assert "at least one slow-moving rule" in descriptions[
        "flagged_inventory_cost_tied_up"
    ]
