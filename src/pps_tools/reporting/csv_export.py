"""CSV export for pricing data."""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

from pps_tools.storage.models import PricePoint, ComparisonRow


def export_price_points_csv(points: list[PricePoint], output_path: Path) -> Path:
    """Export raw price points to CSV."""
    fieldnames = [
        "competitor", "product", "quantity", "total_price", "unit_price",
        "paper_type", "size", "color_mode", "sides", "turnaround_days",
        "finish", "currency", "scraped_at",
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in points:
            writer.writerow({
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

    return output_path


def export_comparison_csv(rows: list[ComparisonRow], output_path: Path) -> Path:
    """Export comparison data to CSV."""
    all_competitors = sorted(set(
        comp for row in rows for comp in row.competitor_prices.keys()
    ))

    fieldnames = ["product", "quantity", "pps_price"] + all_competitors

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: (r.product, r.quantity)):
            data = {
                "product": row.product,
                "quantity": row.quantity,
                "pps_price": row.own_price or "",
            }
            for comp in all_competitors:
                data[comp] = row.competitor_prices.get(comp, "")
            writer.writerow(data)

    return output_path
