"""Rich terminal output for reports."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from pps_tools.analysis.comparator import build_comparison, summarize_position
from pps_tools.analysis.trends import TrendSummary
from pps_tools.storage.models import ComparisonRow

console = Console()

TREND_ARROWS = {
    "increasing": "[red]\u2191[/red]",
    "decreasing": "[green]\u2193[/green]",
    "stable": "[yellow]\u2192[/yellow]",
}


def render_comparison_table(rows: list[ComparisonRow], title: str = "Price Comparison"):
    """Render a comparison table to the terminal."""
    if not rows:
        console.print("[yellow]No data to display.[/yellow]")
        return

    all_competitors = sorted(set(
        comp for row in rows for comp in row.competitor_prices.keys()
    ))

    table = Table(title=title, show_lines=True)
    table.add_column("Product", style="bold")
    table.add_column("Qty", justify="right", style="cyan")
    table.add_column("PPS", justify="right", style="bold white")

    for comp in all_competitors:
        table.add_column(comp, justify="right")

    for row in sorted(rows, key=lambda r: (r.product, r.quantity)):
        values = [
            row.product,
            f"{row.quantity:,}",
            f"${row.own_price:.2f}" if row.own_price else "-",
        ]

        for comp in all_competitors:
            price = row.competitor_prices.get(comp)
            if price is not None:
                diff_pct = row.price_diff_pct(comp)
                if diff_pct is not None:
                    if diff_pct > 5:
                        values.append(f"[green]${price:.2f}[/green]")
                    elif diff_pct < -5:
                        values.append(f"[red]${price:.2f}[/red]")
                    else:
                        values.append(f"${price:.2f}")
                else:
                    values.append(f"${price:.2f}")
            else:
                values.append("-")

        table.add_row(*values)

    console.print(table)


def render_trend_table(summaries: list[TrendSummary], title: str = "Price Trends"):
    """Render a trend summary table."""
    if not summaries:
        console.print("[yellow]No trend data available.[/yellow]")
        return

    table = Table(title=title, show_lines=True)
    table.add_column("Competitor", style="cyan")
    table.add_column("Product")
    table.add_column("Qty", justify="right")
    table.add_column("Direction")
    table.add_column("Change", justify="right")
    table.add_column("First Price", justify="right")
    table.add_column("Last Price", justify="right")
    table.add_column("Period")
    table.add_column("Points", justify="right")

    for s in summaries:
        arrow = TREND_ARROWS.get(s.direction, "")
        change_style = "red" if s.change_pct > 0 else "green" if s.change_pct < 0 else "yellow"

        table.add_row(
            s.competitor,
            s.product,
            f"{s.quantity:,}",
            f"{arrow} {s.direction}",
            f"[{change_style}]{s.change_pct:+.1f}%[/{change_style}]",
            f"${s.first_price:.2f}",
            f"${s.last_price:.2f}",
            f"{s.first_date[:10]} to {s.last_date[:10]}",
            str(s.data_points),
        )

    console.print(table)

    # Show notable changes
    notable = [c for s in summaries for c in s.notable_changes]
    if notable:
        console.print()
        console.print("[bold]Notable Price Changes:[/bold]")
        for change in sorted(notable, key=lambda c: abs(c["pct_change"]), reverse=True)[:10]:
            direction = "[red]\u2191" if change["pct_change"] > 0 else "[green]\u2193"
            console.print(
                f"  {direction} {change['pct_change']:+.1f}%[/] "
                f"${change['old_price']:.2f} \u2192 ${change['new_price']:.2f} "
                f"on {change['date'][:10]}"
            )


def render_dashboard(
    comparison_rows: list[ComparisonRow],
    trend_summaries: list[TrendSummary],
    position_summary: dict,
):
    """Render a summary dashboard to the terminal."""
    console.print(Panel("[bold]PPS Competitor Pricing Dashboard[/bold]", expand=False))
    console.print()

    # Position summary
    if position_summary:
        console.print("[bold]Competitive Position:[/bold]")
        cheaper = position_summary.get("cheaper_than", {})
        expensive = position_summary.get("more_expensive_than", {})

        for comp in sorted(set(list(cheaper.keys()) + list(expensive.keys()))):
            c_count = cheaper.get(comp, 0)
            e_count = expensive.get(comp, 0)
            total = c_count + e_count
            if total > 0:
                pct = round(c_count / total * 100)
                bar = "\u2588" * (pct // 5) + "\u2591" * ((100 - pct) // 5)
                console.print(f"  vs {comp}: [green]{bar}[/green] {pct}% cheaper")

        console.print()

    # Latest comparison snapshot
    if comparison_rows:
        render_comparison_table(comparison_rows[:20], "Latest Prices (Top 20)")
        console.print()

    # Trend highlights
    if trend_summaries:
        changing = [s for s in trend_summaries if s.direction != "stable"]
        if changing:
            console.print("[bold]Active Trends:[/bold]")
            for s in changing[:10]:
                arrow = TREND_ARROWS.get(s.direction, "")
                console.print(
                    f"  {arrow} {s.competitor}/{s.product} (qty {s.quantity:,}): "
                    f"{s.change_pct:+.1f}% over {s.data_points} data points"
                )
