"""Database management commands."""

import click
from rich.console import Console
from rich.table import Table

from pps_tools.storage.database import init_db, get_db_stats, prune_old_records

console = Console()


@click.group("db")
def db_group():
    """Database management commands."""


@db_group.command()
def init():
    """Initialize the database with schema and seed data."""
    path = init_db()
    console.print(f"[green]Database initialized at:[/green] {path}")


@db_group.command()
def stats():
    """Show database statistics."""
    try:
        data = get_db_stats()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print("[yellow]Run 'pps db init' first to create the database.[/yellow]")
        return

    table = Table(title="Database Statistics")
    table.add_column("Table", style="cyan")
    table.add_column("Records", justify="right", style="green")

    for tbl in ["competitors", "products", "pricing_urls", "price_points",
                 "own_pricing", "scrape_runs"]:
        table.add_row(tbl, str(data.get(tbl, 0)))

    console.print(table)
    console.print()

    latest = data.get("latest_scrape")
    earliest = data.get("earliest_scrape")
    if latest:
        console.print(f"Earliest scrape: [cyan]{earliest}[/cyan]")
        console.print(f"Latest scrape:   [cyan]{latest}[/cyan]")
    else:
        console.print("[yellow]No pricing data scraped yet.[/yellow]")


@db_group.command()
@click.option("--older-than", type=int, required=True, help="Delete records older than N days")
@click.confirmation_option(prompt="Are you sure you want to delete old records?")
def prune(older_than: int):
    """Remove old price point records."""
    deleted = prune_old_records(older_than)
    console.print(f"[green]Deleted {deleted} records older than {older_than} days.[/green]")
