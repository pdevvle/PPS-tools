"""`pps qb-categorize` — launch the QuickBooks categorizer web dashboard."""

import click


@click.command("qb-categorize")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind.")
@click.option("--port", default=5000, show_default=True, help="Port to listen on.")
@click.option("--debug", is_flag=True, help="Enable Flask debug mode.")
def qb_categorize(host: str, port: int, debug: bool) -> None:
    """Run the QuickBooks transaction categorizer web UI.

    The dashboard walks you through connecting to QuickBooks Online via OAuth,
    fetching uncategorized transactions, getting Claude-suggested categories,
    and writing approved categorizations back to QBO.

    Configuration (via .env or environment):

    \b
      QBO_CLIENT_ID          Intuit app client id
      QBO_CLIENT_SECRET      Intuit app client secret
      QBO_REDIRECT_URI       OAuth redirect (default http://localhost:5000/oauth/callback)
      QBO_ENVIRONMENT        "production" (default) or "sandbox"
      ANTHROPIC_API_KEY      Claude API key
      QBO_BUSINESS_CONTEXT   Optional one-line description of your business
    """
    from pps_tools.quickbooks.app import create_app

    app = create_app()
    click.echo(f"Starting QuickBooks categorizer on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
