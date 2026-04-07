"""Tests for the comparator module."""

from pps_tools.analysis.comparator import build_comparison, summarize_position
from pps_tools.storage.models import PricePoint, OwnPricing


def test_build_comparison_basic():
    """Test building a basic comparison matrix."""
    prices = [
        PricePoint(competitor="vistaprint", product="business_cards",
                   quantity=100, total_price=29.99),
        PricePoint(competitor="gotprint", product="business_cards",
                   quantity=100, total_price=24.99),
        PricePoint(competitor="vistaprint", product="business_cards",
                   quantity=500, total_price=79.99),
        PricePoint(competitor="gotprint", product="business_cards",
                   quantity=500, total_price=69.99),
    ]

    own = [
        OwnPricing(product="business_cards", quantity=100, total_price=27.00),
        OwnPricing(product="business_cards", quantity=500, total_price=75.00),
    ]

    rows = build_comparison(prices, own)
    assert len(rows) == 2

    row_100 = [r for r in rows if r.quantity == 100][0]
    assert row_100.own_price == 27.00
    assert row_100.competitor_prices["vistaprint"] == 29.99
    assert row_100.competitor_prices["gotprint"] == 24.99


def test_build_comparison_no_own():
    """Test comparison without own pricing."""
    prices = [
        PricePoint(competitor="vistaprint", product="flyers",
                   quantity=500, total_price=49.99),
    ]

    rows = build_comparison(prices)
    assert len(rows) == 1
    assert rows[0].own_price is None


def test_build_comparison_quantity_filter():
    """Test filtering by quantity."""
    prices = [
        PricePoint(competitor="gotprint", product="flyers",
                   quantity=100, total_price=19.99),
        PricePoint(competitor="gotprint", product="flyers",
                   quantity=500, total_price=49.99),
    ]

    rows = build_comparison(prices, quantities=[500])
    assert len(rows) == 1
    assert rows[0].quantity == 500


def test_comparison_row_cheapest():
    """Test cheapest/most expensive detection."""
    prices = [
        PricePoint(competitor="vistaprint", product="cards",
                   quantity=100, total_price=30.00),
        PricePoint(competitor="gotprint", product="cards",
                   quantity=100, total_price=20.00),
        PricePoint(competitor="moo", product="cards",
                   quantity=100, total_price=40.00),
    ]

    rows = build_comparison(prices)
    assert rows[0].cheapest_competitor == "gotprint"
    assert rows[0].most_expensive_competitor == "moo"


def test_price_diff_pct():
    """Test percentage difference calculation."""
    prices = [
        PricePoint(competitor="vistaprint", product="cards",
                   quantity=100, total_price=30.00),
    ]
    own = [
        OwnPricing(product="cards", quantity=100, total_price=25.00),
    ]

    rows = build_comparison(prices, own)
    diff = rows[0].price_diff_pct("vistaprint")
    assert diff == 20.0  # vistaprint is 20% more expensive


def test_summarize_position():
    """Test position summary."""
    prices = [
        PricePoint(competitor="vistaprint", product="cards",
                   quantity=100, total_price=30.00),
        PricePoint(competitor="gotprint", product="cards",
                   quantity=100, total_price=20.00),
    ]
    own = [
        OwnPricing(product="cards", quantity=100, total_price=25.00),
    ]

    rows = build_comparison(prices, own)
    summary = summarize_position(rows)

    assert "vistaprint" in summary["cheaper_than"]
    assert "gotprint" in summary["more_expensive_than"]
