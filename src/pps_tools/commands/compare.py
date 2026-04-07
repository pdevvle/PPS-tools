"""Price comparison command."""

import click
from rich.console import Console
from rich.table import Table

from pps_tools.analysis.comparator import build_comparison, summarize_position
from pps_tools.storage.queries import get_latest_prices, get_own_pricing

console = Console()


@click.command()
@click.option("-p", "--product", required=True, help="Product to compare")
@click.option("--quantity", type=int, multiple=True, help="Filter to specific quantities")
@click.option("--competitors", help="Comma-separated competitor list")
@click.option("--include-own/--no-own", default=True, help="Include PPS pricing")
@click.option("--sort", type=click.Choice(["price", "competitor", "quantity"]),
              default="quantity", help="Sort order")
def compare(product, quantity, competitors, include_own, sort):
    """Compare pricing across competitors for a product."""
    # Fetch latest prices
    prices = get_latest_prices(product=product)

    if competitors:
        comp_list = [c.strip() for c in competitors.split(",")]
        prices = [p for p in prices if p.competitor in comp_list]

    if not prices:
        console.print("[yellow]No competitor pricing data found.[/yellow]")
        console.print("Run 'pps fetch' first to scrape pricing data.")
        return

    # Fetch own pricing
    own_prices = get_own_pricing(product=product) if include_own else []

    # Build comparison
    quantities_filter = list(quantity) if quantity else None
    rows = build_comparison(prices, own_prices, quantities_filter)

    if not rows:
        console.print("[yellow]No comparison data available for the given filters.[/yellow]")
        return

    # Get all competitor names
    all_competitors = sorted(set(
        comp for row in rows for comp in row.competitor_prices.keys()
    ))

    # Build table
    table = Table(title=f"Price Comparison: {product}")
    table.add_column("Qty", justify="right", style="cyan")

    if include_own and own_prices:
        table.add_column("PPS", justify="right", style="bold white")

    for comp in all_competitors:
        table.add_column(comp, justify="right")

    # Sort rows
    if sort == "quantity":
        rows.sort(key=lambda r: r.quantity)
    elif sort == "price":
        rows.sort(key=lambda r: r.own_price or 0)

    for row in rows:
        values = [f"{row.quantity:,}"]

        if include_own and own_prices:
            if row.own_price is not None:
                values.append(f"${row.own_price:.2f}")
            else:
                values.append("-")

        for comp in all_competitors:
            price = row.competitor_prices.get(comp)
            if price is not None:
                # Color code: green if more expensive than PPS, red if cheaper
                if row.own_price is not None:
                    diff_pct = row.price_diff_pct(comp)
                    if diff_pct is not None:
                        if diff_pct > 5:
                            values.append(f"[green]${price:.2f} (+{diff_pct}%)[/green]")
                        elif diff_pct < -5:
                            values.append(f"[red]${price:.2f} ({diff_pct}%)[/red]")
                        else:
                            values.append(f"${price:.2f} ({diff_pct:+.1f}%)")
                    else:
                        values.append(f"${price:.2f}")
                else:
                    values.append(f"${price:.2f}")
            else:
                values.append("-")

        table.add_row(*values)

    console.print(table)

    # Show position summary if own pricing available
    if include_own and own_prices:
        summary = summarize_position(rows)
        console.print()
        console.print("[bold]Competitive Position Summary:[/bold]")

        for comp, count in summary["cheaper_than"].items():
            console.print(f"  [green]Cheaper than {comp} at {count} quantity tier(s)[/green]")
        for comp, count in summary["more_expensive_than"].items():
            console.print(f"  [red]More expensive than {comp} at {count} quantity tier(s)[/red]")

        if summary["cheapest_at"]:
            console.print(f"  [bold green]PPS is cheapest overall at: "
                         f"{', '.join(f'{q:,}' for _, q in summary['cheapest_at'])}[/bold green]")
        if summary["most_expensive_at"]:
            console.print(f"  [bold red]PPS is most expensive at: "
                         f"{', '.join(f'{q:,}' for _, q in summary['most_expensive_at'])}[/bold red]")
