"""PPS-Tools CLI entry point."""

import click

from pps_tools.commands.db import db_group
from pps_tools.commands.discover import discover
from pps_tools.commands.fetch import fetch
from pps_tools.commands.compare import compare
from pps_tools.commands.report import report
from pps_tools.commands.export import export
from pps_tools.commands.import_data import import_group


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
    """


main.add_command(db_group, "db")
main.add_command(discover)
main.add_command(fetch)
main.add_command(compare)
main.add_command(report)
main.add_command(export)
main.add_command(import_group, "import")


if __name__ == "__main__":
    main()
