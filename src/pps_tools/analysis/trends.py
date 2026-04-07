"""Trend detection over historical pricing data."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pps_tools.storage.models import TrendPoint


@dataclass
class TrendSummary:
    competitor: str
    product: str
    quantity: int
    direction: str  # "increasing", "decreasing", "stable"
    change_pct: float
    first_price: float
    last_price: float
    first_date: str
    last_date: str
    data_points: int
    notable_changes: list[dict]  # [{date, old_price, new_price, pct_change}]


def analyze_trends(
    history: list[TrendPoint],
    change_threshold_pct: float = 10.0,
) -> list[TrendSummary]:
    """Analyze price trends from historical data.

    Groups data by (competitor, product, quantity) and detects:
    - Overall direction (increasing/decreasing/stable)
    - Percentage change over the period
    - Notable jumps (>threshold% between consecutive scrapes)
    """
    # Group by (competitor, product, quantity)
    grouped: dict[tuple, list[TrendPoint]] = defaultdict(list)
    for point in history:
        key = (point.competitor, point.product, point.quantity)
        grouped[key].append(point)

    summaries = []
    for (comp, prod, qty), points in sorted(grouped.items()):
        # Sort by date
        points.sort(key=lambda p: p.date)

        if len(points) < 2:
            summaries.append(TrendSummary(
                competitor=comp,
                product=prod,
                quantity=qty,
                direction="stable",
                change_pct=0.0,
                first_price=points[0].price,
                last_price=points[0].price,
                first_date=points[0].date,
                last_date=points[0].date,
                data_points=1,
                notable_changes=[],
            ))
            continue

        first_price = points[0].price
        last_price = points[-1].price

        if first_price > 0:
            change_pct = round((last_price - first_price) / first_price * 100, 1)
        else:
            change_pct = 0.0

        if change_pct > 2:
            direction = "increasing"
        elif change_pct < -2:
            direction = "decreasing"
        else:
            direction = "stable"

        # Find notable changes
        notable = []
        for i in range(1, len(points)):
            old_price = points[i - 1].price
            new_price = points[i].price
            if old_price > 0:
                pct = abs((new_price - old_price) / old_price * 100)
                if pct >= change_threshold_pct:
                    notable.append({
                        "date": points[i].date,
                        "old_price": old_price,
                        "new_price": new_price,
                        "pct_change": round(
                            (new_price - old_price) / old_price * 100, 1
                        ),
                    })

        summaries.append(TrendSummary(
            competitor=comp,
            product=prod,
            quantity=qty,
            direction=direction,
            change_pct=change_pct,
            first_price=first_price,
            last_price=last_price,
            first_date=points[0].date,
            last_date=points[-1].date,
            data_points=len(points),
            notable_changes=notable,
        ))

    return summaries
