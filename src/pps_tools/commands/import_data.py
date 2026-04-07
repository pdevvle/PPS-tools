"""Import command for loading pricing data from CSV/JSON files."""

import csv
import json
from pathlib import Path

import click
from rich.console import Console

from pps_tools.storage.database import get_connection
from pps_tools.storage.models import PricePoint, OwnPricing
from pps_tools.storage.queries import save_price_points, save_own_pricing

console = Console()


@click.group("import")
def import_group():
    """Import pricing data from files."""


@import_group.command("competitors")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--format", "fmt", type=click.Choice(["csv", "json"]), help="File format (auto-detected from extension)")
def import_competitors(file_path, fmt):
    """Import competitor pricing data from a CSV or JSON file.

    CSV format: competitor,product,quantity,total_price[,paper_type,size,...]
    JSON format: [{competitor, product, quantity, total_price, ...}, ...]
    """
    path = Path(file_path)
    if fmt is None:
        fmt = path.suffix.lstrip(".")

    if fmt == "csv":
        points = _load_csv(path)
    elif fmt == "json":
        points = _load_json(path)
    else:
        console.print(f"[red]Unsupported format: {fmt}[/red]")
        return

    if not points:
        console.print("[yellow]No data found in file.[/yellow]")
        return

    saved = save_price_points(points)
    console.print(f"[green]Imported {saved} competitor price points from {path.name}[/green]")


@import_group.command("own")
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--format", "fmt", type=click.Choice(["csv", "json"]), help="File format (auto-detected)")
def import_own(file_path, fmt):
    """Import PPS's own pricing data from a CSV or JSON file.

    CSV format: product,quantity,total_price[,paper_type,size,...]
    JSON format: [{product, quantity, total_price, ...}, ...]
    """
    path = Path(file_path)
    if fmt is None:
        fmt = path.suffix.lstrip(".")

    if fmt == "csv":
        prices = _load_own_csv(path)
    elif fmt == "json":
        prices = _load_own_json(path)
    else:
        console.print(f"[red]Unsupported format: {fmt}[/red]")
        return

    if not prices:
        console.print("[yellow]No data found in file.[/yellow]")
        return

    saved = save_own_pricing(prices)
    console.print(f"[green]Imported {saved} PPS price points from {path.name}[/green]")


def _load_csv(path: Path) -> list[PricePoint]:
    points = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                points.append(PricePoint(
                    competitor=row["competitor"],
                    product=row["product"],
                    quantity=int(row["quantity"]),
                    total_price=float(row["total_price"]),
                    paper_type=row.get("paper_type") or None,
                    size=row.get("size") or None,
                    color_mode=row.get("color_mode") or None,
                    sides=row.get("sides") or None,
                    turnaround_days=int(row["turnaround_days"]) if row.get("turnaround_days") else None,
                    finish=row.get("finish") or None,
                    raw_text=row.get("raw_text") or f"imported from {path.name}",
                ))
            except (KeyError, ValueError) as e:
                console.print(f"[yellow]Skipping row: {e}[/yellow]")
    return points


def _load_json(path: Path) -> list[PricePoint]:
    with open(path) as f:
        data = json.load(f)
    points = []
    for item in data:
        try:
            points.append(PricePoint(
                competitor=item["competitor"],
                product=item["product"],
                quantity=int(item["quantity"]),
                total_price=float(item["total_price"]),
                paper_type=item.get("paper_type"),
                size=item.get("size"),
                color_mode=item.get("color_mode"),
                sides=item.get("sides"),
                turnaround_days=item.get("turnaround_days"),
                finish=item.get("finish"),
                raw_text=item.get("raw_text", f"imported from {path.name}"),
            ))
        except (KeyError, ValueError) as e:
            console.print(f"[yellow]Skipping item: {e}[/yellow]")
    return points


def _load_own_csv(path: Path) -> list[OwnPricing]:
    prices = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                prices.append(OwnPricing(
                    product=row["product"],
                    quantity=int(row["quantity"]),
                    total_price=float(row["total_price"]),
                    paper_type=row.get("paper_type") or None,
                    size=row.get("size") or None,
                    color_mode=row.get("color_mode") or None,
                    sides=row.get("sides") or None,
                    turnaround_days=int(row["turnaround_days"]) if row.get("turnaround_days") else None,
                    finish=row.get("finish") or None,
                    effective_date=row.get("effective_date") or None,
                ))
            except (KeyError, ValueError) as e:
                console.print(f"[yellow]Skipping row: {e}[/yellow]")
    return prices


def _load_own_json(path: Path) -> list[OwnPricing]:
    with open(path) as f:
        data = json.load(f)
    prices = []
    for item in data:
        try:
            prices.append(OwnPricing(
                product=item["product"],
                quantity=int(item["quantity"]),
                total_price=float(item["total_price"]),
                paper_type=item.get("paper_type"),
                size=item.get("size"),
                color_mode=item.get("color_mode"),
                sides=item.get("sides"),
                turnaround_days=item.get("turnaround_days"),
                finish=item.get("finish"),
                effective_date=item.get("effective_date"),
            ))
        except (KeyError, ValueError) as e:
            console.print(f"[yellow]Skipping item: {e}[/yellow]")
    return prices
