"""Tests for the trends module."""

from pps_tools.analysis.trends import analyze_trends
from pps_tools.storage.models import TrendPoint


def test_analyze_increasing_trend():
    """Test detection of increasing price trend."""
    history = [
        TrendPoint(date="2024-01-01", price=20.00, quantity=100,
                   competitor="vistaprint", product="cards"),
        TrendPoint(date="2024-02-01", price=22.00, quantity=100,
                   competitor="vistaprint", product="cards"),
        TrendPoint(date="2024-03-01", price=25.00, quantity=100,
                   competitor="vistaprint", product="cards"),
    ]

    summaries = analyze_trends(history)
    assert len(summaries) == 1
    assert summaries[0].direction == "increasing"
    assert summaries[0].change_pct == 25.0
    assert summaries[0].data_points == 3


def test_analyze_decreasing_trend():
    """Test detection of decreasing price trend."""
    history = [
        TrendPoint(date="2024-01-01", price=30.00, quantity=100,
                   competitor="gotprint", product="cards"),
        TrendPoint(date="2024-02-01", price=25.00, quantity=100,
                   competitor="gotprint", product="cards"),
        TrendPoint(date="2024-03-01", price=20.00, quantity=100,
                   competitor="gotprint", product="cards"),
    ]

    summaries = analyze_trends(history)
    assert len(summaries) == 1
    assert summaries[0].direction == "decreasing"


def test_analyze_stable_trend():
    """Test detection of stable pricing."""
    history = [
        TrendPoint(date="2024-01-01", price=25.00, quantity=100,
                   competitor="moo", product="cards"),
        TrendPoint(date="2024-02-01", price=25.10, quantity=100,
                   competitor="moo", product="cards"),
        TrendPoint(date="2024-03-01", price=24.90, quantity=100,
                   competitor="moo", product="cards"),
    ]

    summaries = analyze_trends(history)
    assert len(summaries) == 1
    assert summaries[0].direction == "stable"


def test_notable_changes():
    """Test detection of notable price jumps."""
    history = [
        TrendPoint(date="2024-01-01", price=20.00, quantity=100,
                   competitor="vistaprint", product="cards"),
        TrendPoint(date="2024-02-01", price=20.00, quantity=100,
                   competitor="vistaprint", product="cards"),
        TrendPoint(date="2024-03-01", price=25.00, quantity=100,
                   competitor="vistaprint", product="cards"),
    ]

    summaries = analyze_trends(history, change_threshold_pct=10.0)
    assert len(summaries[0].notable_changes) == 1
    assert summaries[0].notable_changes[0]["pct_change"] == 25.0


def test_multiple_competitors():
    """Test analysis with multiple competitors."""
    history = [
        TrendPoint(date="2024-01-01", price=20.00, quantity=100,
                   competitor="vistaprint", product="cards"),
        TrendPoint(date="2024-02-01", price=22.00, quantity=100,
                   competitor="vistaprint", product="cards"),
        TrendPoint(date="2024-01-01", price=18.00, quantity=100,
                   competitor="gotprint", product="cards"),
        TrendPoint(date="2024-02-01", price=17.00, quantity=100,
                   competitor="gotprint", product="cards"),
    ]

    summaries = analyze_trends(history)
    assert len(summaries) == 2

    by_comp = {s.competitor: s for s in summaries}
    assert by_comp["vistaprint"].direction == "increasing"
    assert by_comp["gotprint"].direction == "decreasing"
