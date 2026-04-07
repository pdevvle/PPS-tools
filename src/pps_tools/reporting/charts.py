"""Chart generation for pricing reports."""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pps_tools.storage.models import ComparisonRow
from pps_tools.analysis.trends import TrendSummary
from pps_tools.utils.config import get_settings


def _get_chart_settings() -> dict:
    settings = get_settings().get("reporting", {})
    return {
        "dpi": settings.get("chart_dpi", 150),
        "style": settings.get("chart_style", "seaborn-v0_8-whitegrid"),
    }


def generate_comparison_chart(
    rows: list[ComparisonRow],
    output_path: Path,
    title: str = "Price Comparison",
) -> Path:
    """Generate a grouped bar chart comparing prices across competitors."""
    settings = _get_chart_settings()

    try:
        plt.style.use(settings["style"])
    except OSError:
        pass

    # Group by quantity, showing each competitor as a bar
    quantities = sorted(set(r.quantity for r in rows))
    all_competitors = sorted(set(
        comp for row in rows for comp in row.competitor_prices.keys()
    ))

    fig, ax = plt.subplots(figsize=(max(10, len(quantities) * 1.5), 6))

    bar_width = 0.8 / (len(all_competitors) + 1)  # +1 for PPS
    x_positions = range(len(quantities))

    # Plot PPS bars
    pps_prices = []
    for qty in quantities:
        matching = [r for r in rows if r.quantity == qty]
        pps_prices.append(matching[0].own_price if matching and matching[0].own_price else 0)

    if any(p > 0 for p in pps_prices):
        ax.bar(
            [x - bar_width * len(all_competitors) / 2 for x in x_positions],
            pps_prices, bar_width, label="PPS", color="#2196F3", edgecolor="white",
        )

    # Plot competitor bars
    colors = ["#FF5722", "#4CAF50", "#FF9800", "#9C27B0", "#00BCD4", "#795548", "#607D8B"]
    for i, comp in enumerate(all_competitors):
        prices = []
        for qty in quantities:
            matching = [r for r in rows if r.quantity == qty]
            price = matching[0].competitor_prices.get(comp, 0) if matching else 0
            prices.append(price)

        offset = (i + 1 - len(all_competitors) / 2) * bar_width
        ax.bar(
            [x + offset for x in x_positions],
            prices, bar_width, label=comp,
            color=colors[i % len(colors)], edgecolor="white",
        )

    ax.set_xlabel("Quantity")
    ax.set_ylabel("Total Price ($)")
    ax.set_title(title)
    ax.set_xticks(list(x_positions))
    ax.set_xticklabels([f"{q:,}" for q in quantities])
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=settings["dpi"], bbox_inches="tight")
    plt.close()

    return output_path


def generate_trend_chart(
    trend_data: list[dict],
    output_path: Path,
    title: str = "Price Trends",
) -> Path:
    """Generate a line chart showing price trends over time.

    trend_data: list of {date, price, competitor, quantity} dicts.
    """
    settings = _get_chart_settings()

    try:
        plt.style.use(settings["style"])
    except OSError:
        pass

    fig, ax = plt.subplots(figsize=(12, 6))

    # Group by competitor
    from collections import defaultdict
    by_competitor: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for point in trend_data:
        by_competitor[point["competitor"]].append((point["date"], point["price"]))

    colors = ["#2196F3", "#FF5722", "#4CAF50", "#FF9800", "#9C27B0", "#00BCD4", "#795548"]
    for i, (comp, data) in enumerate(sorted(by_competitor.items())):
        data.sort(key=lambda x: x[0])
        dates = [d[0][:10] for d in data]
        prices = [d[1] for d in data]
        ax.plot(dates, prices, marker="o", label=comp,
                color=colors[i % len(colors)], linewidth=2, markersize=4)

    ax.set_xlabel("Date")
    ax.set_ylabel("Total Price ($)")
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # Rotate x labels for readability
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(output_path, dpi=settings["dpi"], bbox_inches="tight")
    plt.close()

    return output_path


def generate_heatmap(
    rows: list[ComparisonRow],
    output_path: Path,
    title: str = "Price Difference Heatmap (% vs PPS)",
) -> Path:
    """Generate a heatmap showing price differences from PPS."""
    settings = _get_chart_settings()

    quantities = sorted(set(r.quantity for r in rows if r.own_price is not None))
    all_competitors = sorted(set(
        comp for row in rows for comp in row.competitor_prices.keys()
    ))

    if not quantities or not all_competitors:
        # Create empty chart if no data
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No comparison data available", ha="center", va="center")
        plt.savefig(output_path, dpi=settings["dpi"])
        plt.close()
        return output_path

    # Build matrix
    data = []
    for comp in all_competitors:
        row_data = []
        for qty in quantities:
            matching = [r for r in rows if r.quantity == qty]
            if matching:
                diff = matching[0].price_diff_pct(comp)
                row_data.append(diff if diff is not None else 0)
            else:
                row_data.append(0)
        data.append(row_data)

    fig, ax = plt.subplots(figsize=(max(8, len(quantities) * 1.2), max(4, len(all_competitors) * 0.6)))

    im = ax.imshow(data, cmap="RdYlGn", aspect="auto")

    ax.set_xticks(range(len(quantities)))
    ax.set_xticklabels([f"{q:,}" for q in quantities])
    ax.set_yticks(range(len(all_competitors)))
    ax.set_yticklabels(all_competitors)

    # Add text annotations
    for i in range(len(all_competitors)):
        for j in range(len(quantities)):
            val = data[i][j]
            ax.text(j, i, f"{val:+.1f}%", ha="center", va="center",
                    fontsize=8, color="black" if abs(val) < 30 else "white")

    ax.set_title(title)
    ax.set_xlabel("Quantity")
    fig.colorbar(im, label="% Difference (positive = competitor more expensive)")

    plt.tight_layout()
    plt.savefig(output_path, dpi=settings["dpi"], bbox_inches="tight")
    plt.close()

    return output_path
