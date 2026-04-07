"""Fetch and parse competitor pricing data."""

from __future__ import annotations

import logging
from datetime import datetime

import click
from rich.console import Console
from rich.table import Table

from pps_tools.scraping.fetcher import Fetcher
from pps_tools.scraping.parsers import get_parser_for_url
from pps_tools.storage.database import get_connection, get_db_path
from pps_tools.storage.models import PricePoint, ScrapeRun
from pps_tools.storage.queries import save_price_points

console = Console()
logger = logging.getLogger("pps_tools.commands.fetch")


@click.command()
@click.option("-c", "--competitor", help="Filter to one competitor")
@click.option("-p", "--product", help="Filter to one product")
@click.option("--url", "single_url", help="Fetch a single specific URL")
@click.option("--delay", type=float, help="Override delay between requests (seconds)")
@click.option("--js/--no-js", default=False, help="Attempt JS rendering (requires playwright)")
@click.option("--save/--no-save", default=True, help="Persist results to DB")
@click.option("-v", "--verbose", is_flag=True, help="Show raw parsed data")
def fetch(competitor, product, single_url, delay, js, save, verbose):
    """Scrape pricing data from competitor websites."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    fetcher = Fetcher(delay=delay)

    if single_url:
        _fetch_single_url(fetcher, single_url, product or "unknown", save, verbose)
        return

    # Get URLs from database
    try:
        with get_connection() as conn:
            query = """
                SELECT pu.url, pu.id as url_id, pu.is_dynamic,
                       c.name as competitor_name, c.id as competitor_id,
                       p.name as product_name, p.id as product_id
                FROM pricing_urls pu
                JOIN competitors c ON pu.competitor_id = c.id
                JOIN products p ON pu.product_id = p.id
                WHERE pu.is_active = 1
            """
            params: list = []

            if competitor:
                query += " AND c.name = ?"
                params.append(competitor)
            if product:
                query += " AND p.name = ?"
                params.append(product)

            rows = conn.execute(query, params).fetchall()
    except Exception as e:
        console.print(f"[red]Database error: {e}[/red]")
        console.print("[yellow]Run 'pps db init' first.[/yellow]")
        return

    if not rows:
        console.print("[yellow]No pricing URLs found in database.[/yellow]")
        console.print("Run 'pps discover' first to find pricing URLs.")
        return

    console.print(f"[cyan]Fetching pricing from {len(rows)} URLs...[/cyan]")
    total_points = 0
    errors = 0

    for row in rows:
        url = row["url"]
        comp_name = row["competitor_name"]
        prod_name = row["product_name"]

        if row["is_dynamic"] and not js:
            console.print(
                f"  [yellow]Skipping {comp_name}/{prod_name} (JS required, use --js)[/yellow]"
            )
            continue

        console.print(f"  Fetching [cyan]{comp_name}[/cyan] / [green]{prod_name}[/green]...")

        result = fetcher.fetch(url)
        if not result.success:
            console.print(f"    [red]Failed: {result.error}[/red]")
            errors += 1
            _log_scrape_run(row, "failed", 0, result.error)
            continue

        # Parse the HTML
        parser = get_parser_for_url(url, result.html)
        if not parser:
            console.print(f"    [yellow]No parser found for URL[/yellow]")
            _log_scrape_run(row, "failed", 0, "No parser found")
            continue

        points = parser.parse(url, result.html, prod_name)

        if verbose:
            _display_points(points, comp_name, prod_name)

        if save and points:
            saved = save_price_points(points)
            console.print(f"    [green]Saved {saved} price points[/green]")
            _log_scrape_run(row, "success", saved)
        elif points:
            console.print(f"    Found {len(points)} price points (not saved)")
            _log_scrape_run(row, "success", len(points))
        else:
            console.print(f"    [yellow]No pricing data found[/yellow]")
            _log_scrape_run(row, "partial", 0, "No pricing data extracted")

        total_points += len(points)

        # Update last_checked
        try:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE pricing_urls SET last_checked = datetime('now') WHERE id = ?",
                    (row["url_id"],),
                )
        except Exception:
            pass

    console.print()
    console.print(f"[green]Done! {total_points} total price points from {len(rows)} URLs[/green]")
    if errors:
        console.print(f"[red]{errors} URLs failed[/red]")


def _fetch_single_url(fetcher: Fetcher, url: str, product: str, save: bool, verbose: bool):
    """Fetch and parse a single URL."""
    console.print(f"[cyan]Fetching:[/cyan] {url}")

    result = fetcher.fetch(url)
    if not result.success:
        console.print(f"[red]Failed: {result.error}[/red]")
        return

    parser = get_parser_for_url(url, result.html)
    if not parser:
        console.print("[yellow]No parser found, using generic parser[/yellow]")
        from pps_tools.scraping.parsers.generic import GenericParser
        parser = GenericParser()

    points = parser.parse(url, result.html, product)

    if verbose or not save:
        _display_points(points, parser.competitor_name, product)

    if save and points:
        saved = save_price_points(points)
        console.print(f"[green]Saved {saved} price points[/green]")
    elif not points:
        console.print("[yellow]No pricing data found on this page.[/yellow]")


def _display_points(points: list[PricePoint], competitor: str, product: str):
    """Display parsed price points in a table."""
    if not points:
        return

    table = Table(title=f"{competitor} - {product}")
    table.add_column("Qty", justify="right", style="cyan")
    table.add_column("Total", justify="right", style="green")
    table.add_column("Unit Price", justify="right", style="yellow")
    table.add_column("Paper", style="dim")
    table.add_column("Source", style="dim", max_width=40)

    for p in sorted(points, key=lambda x: x.quantity):
        table.add_row(
            f"{p.quantity:,}",
            f"${p.total_price:.2f}",
            f"${p.unit_price:.4f}" if p.unit_price else "-",
            p.paper_type or "-",
            (p.raw_text or "")[:40],
        )

    console.print(table)


def _log_scrape_run(row, status: str, records: int, error: str | None = None):
    """Log a scrape run to the database."""
    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO scrape_runs
                   (competitor_id, product_id, url, status, records_found,
                    error_message, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                (row["competitor_id"], row["product_id"], row["url"],
                 status, records, error),
            )
    except Exception:
        pass
