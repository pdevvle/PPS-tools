"""Report generation commands."""

from pathlib import Path

import click
from rich.console import Console

from pps_tools.analysis.comparator import build_comparison, summarize_position
from pps_tools.analysis.trends import analyze_trends
from pps_tools.reporting.terminal import render_comparison_table, render_trend_table, render_dashboard
from pps_tools.reporting.html import generate_comparison_report, generate_dashboard_report
from pps_tools.storage.queries import get_latest_prices, get_own_pricing, get_price_history
from pps_tools.utils.config import get_settings

console = Console()


@click.command()
@click.option("--type", "report_type", required=True,
              type=click.Choice(["comparison", "trend", "dashboard"]),
              help="Report type")
@click.option("-p", "--product", help="Filter to product")
@click.option("-c", "--competitor", help="Filter to competitor (for trend)")
@click.option("--days", default=90, help="Lookback period for trends")
@click.option("--format", "fmt", type=click.Choice(["terminal", "html"]),
              default="terminal", help="Output format")
@click.option("--output-dir", type=click.Path(), help="Output directory for HTML reports")
def report(report_type, product, competitor, days, fmt, output_dir):
    """Generate formatted reports."""
    if output_dir:
        out_dir = Path(output_dir)
    else:
        settings = get_settings().get("reporting", {})
        out_dir = Path(settings.get("output_dir", "reports"))

    out_dir.mkdir(parents=True, exist_ok=True)

    if report_type == "comparison":
        _comparison_report(product, competitor, fmt, out_dir)
    elif report_type == "trend":
        _trend_report(product, competitor, days, fmt, out_dir)
    elif report_type == "dashboard":
        _dashboard_report(product, days, fmt, out_dir)


def _comparison_report(product, competitor, fmt, out_dir):
    prices = get_latest_prices(product=product, competitor=competitor)
    own_prices = get_own_pricing(product=product)

    if not prices:
        console.print("[yellow]No pricing data found. Run 'pps fetch' first.[/yellow]")
        return

    rows = build_comparison(prices, own_prices)
    position = summarize_position(rows) if own_prices else {}

    if fmt == "terminal":
        title = f"Price Comparison"
        if product:
            title += f": {product}"
        render_comparison_table(rows, title)
    elif fmt == "html":
        output_path = out_dir / "comparison_report.html"
        generate_comparison_report(rows, position, output_path)
        console.print(f"[green]Report saved to: {output_path}[/green]")


def _trend_report(product, competitor, days, fmt, out_dir):
    if not product:
        console.print("[red]Product is required for trend reports. Use -p/--product.[/red]")
        return

    history = get_price_history(product, competitor, days)
    if not history:
        console.print("[yellow]No historical data found for trend analysis.[/yellow]")
        return

    summaries = analyze_trends(history)

    if fmt == "terminal":
        title = f"Price Trends: {product}"
        if competitor:
            title += f" ({competitor})"
        title += f" (last {days} days)"
        render_trend_table(summaries, title)
    elif fmt == "html":
        # For HTML, generate as part of a comparison report with trends
        prices = get_latest_prices(product=product, competitor=competitor)
        own_prices = get_own_pricing(product=product)
        rows = build_comparison(prices, own_prices)
        position = summarize_position(rows) if own_prices else {}

        output_path = out_dir / "trend_report.html"
        generate_dashboard_report(rows, summaries, position, output_path)
        console.print(f"[green]Trend report saved to: {output_path}[/green]")


def _dashboard_report(product, days, fmt, out_dir):
    prices = get_latest_prices(product=product)
    own_prices = get_own_pricing(product=product)

    if not prices:
        console.print("[yellow]No pricing data found. Run 'pps fetch' first.[/yellow]")
        return

    rows = build_comparison(prices, own_prices)
    position = summarize_position(rows) if own_prices else {}

    # Get trends for all products
    products_with_data = set(p.product for p in prices)
    all_summaries = []
    for prod in products_with_data:
        history = get_price_history(prod, days=days)
        if history:
            all_summaries.extend(analyze_trends(history))

    if fmt == "terminal":
        render_dashboard(rows, all_summaries, position)
    elif fmt == "html":
        output_path = out_dir / "dashboard.html"
        generate_dashboard_report(rows, all_summaries, position, output_path)
        console.print(f"[green]Dashboard saved to: {output_path}[/green]")
