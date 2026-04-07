"""Scrape ALL competitors and products in one run.

Designed for unattended cron execution:
    0 6 * * 1  cd /path/to/PPS-tools && pps scrape-all --quiet
"""

from __future__ import annotations

import logging
from datetime import datetime

import click
from rich.console import Console
from rich.table import Table

from pps_tools.scraping.fetcher import Fetcher
from pps_tools.scraping.parsers import get_parser_for_url
from pps_tools.storage.database import get_connection
from pps_tools.storage.queries import save_price_points

console = Console()
logger = logging.getLogger("pps_tools.commands.scrape_all")


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


@click.command("scrape-all")
@click.option("--js/--no-js", default=False,
              help="Use playwright for JS-rendered sites (requires playwright)")
@click.option("--skip-dynamic/--no-skip-dynamic", default=True,
              help="Skip JS-rendered sites when --no-js (default: skip)")
@click.option("--delay", type=float, help="Override delay between requests (seconds)")
@click.option("--quiet", is_flag=True, help="Minimal output (for cron)")
@click.option("--save/--no-save", default=True, help="Persist results to DB")
@click.option("-v", "--verbose", is_flag=True, help="Show raw parsed data")
def scrape_all(js, skip_dynamic, delay, quiet, save, verbose):
    """Scrape ALL competitors and ALL products in one run.

    Fetches pricing from every active URL in the database, parses it,
    and saves the results. Ideal for weekly cron jobs.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    fetcher = Fetcher(delay=delay)

    # Get ALL active pricing URLs
    try:
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT pu.url, pu.id as url_id, pu.is_dynamic,
                       c.name as competitor_name, c.id as competitor_id,
                       p.name as product_name, p.id as product_id
                FROM pricing_urls pu
                JOIN competitors c ON pu.competitor_id = c.id
                JOIN products p ON pu.product_id = p.id
                WHERE pu.is_active = 1
                ORDER BY c.name, p.name
            """).fetchall()
    except Exception as e:
        if quiet:
            print(f"ERROR: Database error: {e}")
        else:
            console.print(f"[red]Database error: {e}[/red]")
            console.print("[yellow]Run 'pps db init' first.[/yellow]")
        raise SystemExit(1)

    if not rows:
        if quiet:
            print("No pricing URLs found. Run 'pps discover' first.")
        else:
            console.print("[yellow]No pricing URLs found. Run 'pps discover' first.[/yellow]")
        return

    if not quiet:
        console.print(f"[cyan]Scraping {len(rows)} URLs across all competitors...[/cyan]\n")

    # Track results per competitor/product
    stats: dict[str, dict[str, dict]] = {}
    total_points = 0
    total_errors = 0
    total_skipped = 0

    for row in rows:
        url = row["url"]
        comp = row["competitor_name"]
        prod = row["product_name"]

        # Initialize stats tracking
        stats.setdefault(comp, {})
        stats[comp].setdefault(prod, {"points": 0, "status": "pending"})

        # Skip dynamic sites unless --js
        if row["is_dynamic"] and not js:
            if skip_dynamic:
                stats[comp][prod]["status"] = "skipped"
                total_skipped += 1
                if not quiet:
                    console.print(f"  [dim]Skipping {comp}/{prod} (JS required)[/dim]")
                continue

        if not quiet:
            console.print(f"  Fetching [cyan]{comp}[/cyan] / [green]{prod}[/green]...")

        # Fetch (with optional playwright for JS sites)
        result = None
        if row["is_dynamic"] and js:
            html = _fetch_with_playwright(url)
            if html:
                from pps_tools.scraping.fetcher import FetchResult
                result = FetchResult(
                    url=url, final_url=url, status_code=200,
                    html=html, headers={}, success=True,
                )
            else:
                if not quiet:
                    console.print(f"    [yellow]Playwright unavailable, skipping[/yellow]")
                stats[comp][prod]["status"] = "skipped"
                total_skipped += 1
                continue

        if result is None:
            result = fetcher.fetch(url)

        if not result.success:
            stats[comp][prod]["status"] = "failed"
            total_errors += 1
            if not quiet:
                console.print(f"    [red]Failed: {result.error}[/red]")
            _log_scrape_run(row, "failed", 0, result.error)
            continue

        # Parse
        parser = get_parser_for_url(url, result.html)
        if not parser:
            stats[comp][prod]["status"] = "failed"
            total_errors += 1
            _log_scrape_run(row, "failed", 0, "No parser found")
            continue

        points = parser.parse(url, result.html, prod)

        if verbose and points:
            for p in sorted(points, key=lambda x: x.quantity):
                console.print(f"    qty={p.quantity:>6,}  ${p.total_price:.2f}")

        if save and points:
            saved = save_price_points(points)
            stats[comp][prod] = {"points": saved, "status": "success"}
            total_points += saved
            _log_scrape_run(row, "success", saved)
        elif points:
            stats[comp][prod] = {"points": len(points), "status": "success"}
            total_points += len(points)
        else:
            stats[comp][prod]["status"] = "empty"
            _log_scrape_run(row, "partial", 0, "No pricing data extracted")

        # Update last_checked
        try:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE pricing_urls SET last_checked = datetime('now') WHERE id = ?",
                    (row["url_id"],),
                )
        except Exception:
            pass

    # ── Summary ──
    if quiet:
        print(f"Scraped {total_points} prices, {total_errors} errors, {total_skipped} skipped")
    else:
        console.print()
        table = Table(title="Scrape Summary")
        table.add_column("Competitor", style="cyan")
        table.add_column("Product", style="green")
        table.add_column("Prices", justify="right")
        table.add_column("Status")

        for comp in sorted(stats):
            for prod in sorted(stats[comp]):
                s = stats[comp][prod]
                status_style = {
                    "success": "[green]OK[/green]",
                    "failed": "[red]FAILED[/red]",
                    "empty": "[yellow]No data[/yellow]",
                    "skipped": "[dim]Skipped[/dim]",
                    "pending": "[dim]—[/dim]",
                }.get(s["status"], s["status"])
                table.add_row(comp, prod, str(s["points"]), status_style)

        console.print(table)
        console.print(f"\n[green]Total: {total_points} price points[/green]", end="")
        if total_errors:
            console.print(f" | [red]{total_errors} errors[/red]", end="")
        if total_skipped:
            console.print(f" | [dim]{total_skipped} skipped (JS)[/dim]", end="")
        console.print()

    if total_errors > 0:
        raise SystemExit(1)


def _fetch_with_playwright(url: str, timeout: int = 30000) -> str | None:
    """Attempt to fetch a JS-rendered page. Returns HTML or None."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=timeout)
            page.wait_for_load_state("networkidle")
            html = page.content()
            browser.close()
            return html
    except Exception:
        return None
