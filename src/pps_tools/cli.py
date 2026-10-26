"""PPS-Tools CLI entry point."""

import click

from pps_tools.commands.db import db_group
from pps_tools.commands.discover import discover
from pps_tools.commands.fetch import fetch
from pps_tools.commands.scrape_all import scrape_all
from pps_tools.commands.compare import compare
from pps_tools.commands.report import report
from pps_tools.commands.export import export
from pps_tools.commands.export_comp_js import export_comp_js
from pps_tools.commands.import_data import import_group
from pps_tools.commands.qb_categorize import qb_categorize
from pps_tools.books.cli import books_group
from pps_tools.commands.marketing import marketing_group
from pps_tools.switchboard.cli import switchboard_group


@click.group()
@click.version_option(package_name="pps-tools")
def main():
    """PPS-Tools: Competitor pricing analysis for Priority Print Service.

    Discover, scrape, compare, and report on competitor pricing data
    across the print services industry.

    Getting started:

    \b
      1. pps db init          # Initialize the database
      2. pps discover         # Find competitor pricing URLs
      3. pps fetch            # Scrape pricing data
      4. pps compare -p business_cards  # Compare prices
      5. pps report --type dashboard    # Generate reports
      6. pps export --format csv        # Export raw data

    Marketing Hub (ads + social across Google, Meta, Pinterest, X, LinkedIn, TikTok):

    \b
      pps marketing serve               # open the web app

    Switchboard (team inbox, staffing and job scheduling):

    \b
      pps switchboard run               # open the web app

    PPS Books (bookkeeping and invoicing with Stripe payments):

    \b
      pps books serve                   # open the web app
      pps books demo                    # try it with a demo company
    """


main.add_command(db_group, "db")
main.add_command(discover)
main.add_command(fetch)
main.add_command(scrape_all)
main.add_command(compare)
main.add_command(report)
main.add_command(export)
main.add_command(export_comp_js)
main.add_command(import_group, "import")
main.add_command(qb_categorize)
main.add_command(marketing_group, "marketing")
main.add_command(switchboard_group, "switchboard")
main.add_command(books_group, "books")


if __name__ == "__main__":
    main()
