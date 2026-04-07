"""JSON export for pricing data."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from pps_tools.storage.models import PricePoint, ComparisonRow


def export_price_points_json(points: list[PricePoint], output_path: Path) -> Path:
    """Export raw price points to JSON."""
    data = []
    for p in points:
        data.append({
            "competitor": p.competitor,
            "product": p.product,
            "quantity": p.quantity,
            "total_price": p.total_price,
            "unit_price": p.unit_price,
            "paper_type": p.paper_type,
            "size": p.size,
            "color_mode": p.color_mode,
            "sides": p.sides,
            "turnaround_days": p.turnaround_days,
            "finish": p.finish,
            "currency": p.currency,
            "scraped_at": p.scraped_at,
        })

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    return output_path


def export_comparison_json(rows: list[ComparisonRow], output_path: Path) -> Path:
    """Export comparison data to JSON."""
    data = []
    for row in sorted(rows, key=lambda r: (r.product, r.quantity)):
        entry = {
            "product": row.product,
            "quantity": row.quantity,
            "pps_price": row.own_price,
            "pps_unit_price": row.own_unit_price,
            "competitors": {},
        }
        for comp, price in row.competitor_prices.items():
            entry["competitors"][comp] = {
                "total_price": price,
                "unit_price": row.competitor_unit_prices.get(comp),
                "diff_pct": row.price_diff_pct(comp),
            }
        data.append(entry)

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    return output_path
