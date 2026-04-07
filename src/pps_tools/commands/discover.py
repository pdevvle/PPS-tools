"""Discover competitor pricing URLs via web search."""

import click
from rich.console import Console
from rich.table import Table

from pps_tools.scraping.discovery import discover_pricing_urls
from pps_tools.storage.database import get_connection, get_db_path

console = Console()


@click.command()
@click.option("-c", "--competitor", help="Filter to one competitor")
@click.option("-p", "--product", help="Filter to one product")
@click.option("--max-results", default=5, help="Max URLs per competitor/product")
@click.option("--dry-run", is_flag=True, help="Show results without saving to DB")
def discover(competitor, product, max_results, dry_run):
    """Search the web for competitor pricing URLs."""
    console.print("[cyan]Searching for competitor pricing URLs...[/cyan]")

    results = discover_pricing_urls(
        competitor=competitor,
        product=product,
        max_results=max_results,
    )

    if not results:
        console.print("[yellow]No pricing URLs found.[/yellow]")
        return

    table = Table(title=f"Discovered Pricing URLs ({len(results)} found)")
    table.add_column("Competitor", style="cyan")
    table.add_column("Product", style="green")
    table.add_column("URL", style="blue")
    table.add_column("Source", style="yellow")

    for r in results:
        table.add_row(r["competitor"], r["product"], r["url"], r["source"])

    console.print(table)

    if dry_run:
        console.print("[yellow]Dry run - nothing saved.[/yellow]")
        return

    # Save discovered URLs to database
    saved = 0
    try:
        with get_connection() as conn:
            for r in results:
                comp_row = conn.execute(
                    "SELECT id FROM competitors WHERE name = ?", (r["competitor"],)
                ).fetchone()
                prod_row = conn.execute(
                    "SELECT id FROM products WHERE name = ?", (r["product"],)
                ).fetchone()

                if comp_row and prod_row:
                    conn.execute(
                        """INSERT OR IGNORE INTO pricing_urls
                           (competitor_id, product_id, url, discovery_method)
                           VALUES (?, ?, ?, ?)""",
                        (comp_row["id"], prod_row["id"], r["url"], r["source"]),
                    )
                    saved += 1

        console.print(f"[green]Saved {saved} URLs to database.[/green]")
    except Exception as e:
        console.print(f"[red]Error saving to database: {e}[/red]")
        console.print("[yellow]Run 'pps db init' first if database doesn't exist.[/yellow]")
