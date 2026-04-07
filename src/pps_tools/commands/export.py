"""Raw data export command."""

from pathlib import Path

import click
from rich.console import Console

from pps_tools.storage.queries import get_all_price_points, get_latest_prices, get_own_pricing
from pps_tools.analysis.comparator import build_comparison
from pps_tools.reporting.csv_export import export_price_points_csv, export_comparison_csv
from pps_tools.reporting.json_export import export_price_points_json, export_comparison_json

console = Console()


@click.command()
@click.option("--format", "fmt", required=True,
              type=click.Choice(["json", "csv"]), help="Export format")
@click.option("--type", "export_type",
              type=click.Choice(["raw", "comparison"]), default="raw",
              help="Export raw data or comparison matrix")
@click.option("-p", "--product", help="Filter to product")
@click.option("-c", "--competitor", help="Filter to competitor")
@click.option("--since", help="Only data after this date (YYYY-MM-DD)")
@click.option("-o", "--output", "output_path", type=click.Path(), help="Output file path")
def export(fmt, export_type, product, competitor, since, output_path):
    """Export pricing data to JSON or CSV."""
    if export_type == "raw":
        _export_raw(fmt, product, competitor, since, output_path)
    elif export_type == "comparison":
        _export_comparison(fmt, product, competitor, output_path)


def _export_raw(fmt, product, competitor, since, output_path):
    points = get_all_price_points(product=product, competitor=competitor, since=since)

    if not points:
        console.print("[yellow]No data to export.[/yellow]")
        return

    if not output_path:
        output_path = f"pricing_data.{fmt}"

    path = Path(output_path)

    if fmt == "csv":
        export_price_points_csv(points, path)
    else:
        export_price_points_json(points, path)

    console.print(f"[green]Exported {len(points)} records to: {path}[/green]")


def _export_comparison(fmt, product, competitor, output_path):
    prices = get_latest_prices(product=product, competitor=competitor)
    own_prices = get_own_pricing(product=product)

    if not prices:
        console.print("[yellow]No data to export.[/yellow]")
        return

    rows = build_comparison(prices, own_prices)

    if not output_path:
        output_path = f"comparison.{fmt}"

    path = Path(output_path)

    if fmt == "csv":
        export_comparison_csv(rows, path)
    else:
        export_comparison_json(rows, path)

    console.print(f"[green]Exported {len(rows)} comparison rows to: {path}[/green]")
