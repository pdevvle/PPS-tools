"""Price comparison logic."""

from __future__ import annotations

from collections import defaultdict

from pps_tools.storage.models import ComparisonRow, PricePoint, OwnPricing


def build_comparison(
    price_points: list[PricePoint],
    own_prices: list[OwnPricing] | None = None,
    quantities: list[int] | None = None,
) -> list[ComparisonRow]:
    """Build a comparison matrix from price points and own pricing.

    Groups by product and quantity, creating a row for each combination
    with competitor prices and own price side by side.
    """
    # Group competitor prices by (product, quantity)
    grouped: dict[tuple[str, int], dict[str, float]] = defaultdict(dict)
    for pp in price_points:
        key = (pp.product, pp.quantity)
        # Keep the lowest price per competitor per quantity
        existing = grouped[key].get(pp.competitor)
        if existing is None or pp.total_price < existing:
            grouped[key][pp.competitor] = pp.total_price

    # Build own pricing lookup: (product, quantity) -> price
    own_lookup: dict[tuple[str, int], float] = {}
    if own_prices:
        for op in own_prices:
            own_lookup[(op.product, op.quantity)] = op.total_price

    # Build comparison rows
    rows = []
    for (product, quantity), comp_prices in sorted(grouped.items()):
        if quantities and quantity not in quantities:
            continue

        own_price = own_lookup.get((product, quantity))

        comp_unit_prices = {}
        for comp, price in comp_prices.items():
            if quantity > 0:
                comp_unit_prices[comp] = round(price / quantity, 4)

        row = ComparisonRow(
            product=product,
            quantity=quantity,
            own_price=own_price,
            competitor_prices=comp_prices,
            own_unit_price=round(own_price / quantity, 4) if own_price and quantity > 0 else None,
            competitor_unit_prices=comp_unit_prices,
        )
        rows.append(row)

    return rows


def summarize_position(rows: list[ComparisonRow]) -> dict:
    """Summarize PPS's competitive position across all comparison rows.

    Returns dict with:
        - cheaper_than: dict of competitor -> count of quantities where PPS is cheaper
        - more_expensive_than: dict of competitor -> count
        - avg_diff_pct: dict of competitor -> average percentage difference
        - cheapest_at: list of (product, quantity) where PPS is cheapest overall
        - most_expensive_at: list of (product, quantity) where PPS is most expensive
    """
    cheaper_than: dict[str, int] = defaultdict(int)
    more_expensive_than: dict[str, int] = defaultdict(int)
    diff_pcts: dict[str, list[float]] = defaultdict(list)
    cheapest_at = []
    most_expensive_at = []

    for row in rows:
        if row.own_price is None:
            continue

        all_prices = dict(row.competitor_prices)
        all_prices["PPS"] = row.own_price

        sorted_by_price = sorted(all_prices.items(), key=lambda x: x[1])
        if sorted_by_price[0][0] == "PPS":
            cheapest_at.append((row.product, row.quantity))
        if sorted_by_price[-1][0] == "PPS":
            most_expensive_at.append((row.product, row.quantity))

        for comp, price in row.competitor_prices.items():
            diff = row.price_diff_pct(comp)
            if diff is not None:
                diff_pcts[comp].append(diff)
                if diff > 0:
                    cheaper_than[comp] += 1
                elif diff < 0:
                    more_expensive_than[comp] += 1

    avg_diff_pct = {}
    for comp, diffs in diff_pcts.items():
        avg_diff_pct[comp] = round(sum(diffs) / len(diffs), 1) if diffs else 0

    return {
        "cheaper_than": dict(cheaper_than),
        "more_expensive_than": dict(more_expensive_than),
        "avg_diff_pct": avg_diff_pct,
        "cheapest_at": cheapest_at,
        "most_expensive_at": most_expensive_at,
    }
