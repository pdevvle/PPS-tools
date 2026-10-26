"""`pps marketing` — the cross-platform ads & social Marketing Hub."""

import json
import sys

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _hub():
    from pps_tools.marketing.config import MarketingSettings
    from pps_tools.marketing.hub import MarketingHub
    from pps_tools.marketing.store import Store

    settings = MarketingSettings.from_env()
    return MarketingHub(Store(settings.db_path), settings)


@click.group("marketing")
def marketing_group():
    """Marketing Hub: Google Ads, Meta (Facebook + Instagram), Pinterest, X, LinkedIn and TikTok in one place.

    \b
      pps marketing serve        # open the web app (http://127.0.0.1:5050)
      pps marketing status       # what's connected
      pps marketing report       # spend & results by channel
      pps marketing publish-due  # send scheduled posts (for cron)
      pps marketing run-rules    # run automation rules (for cron)

    Configure platforms in .env — see .env.example for every setting.
    """


@marketing_group.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind.")
@click.option("--port", default=5050, show_default=True, help="Port to listen on.")
@click.option("--debug", is_flag=True, help="Enable Flask debug mode.")
@click.option("--no-scheduler", is_flag=True, help="Don't publish scheduled posts from this process.")
def serve(host: str, port: int, debug: bool, no_scheduler: bool) -> None:
    """Run the Marketing Hub web app."""
    from pps_tools.marketing.app import create_app

    app = create_app(start_scheduler=not no_scheduler)
    hub = app.extensions["marketing_hub"]
    if host not in ("127.0.0.1", "localhost") and not hub.settings.app_password:
        console.print("[yellow]Warning:[/yellow] the hub is reachable from other machines but MARKETING_APP_PASSWORD is not set.")
    mode = "demo data" if hub.demo_active() else "live data"
    console.print(f"Marketing Hub on [bold]http://{host}:{port}[/bold] ({mode})")
    # The reloader would start a second scheduler thread, so it stays off.
    app.run(host=host, port=port, debug=debug, use_reloader=False)


@marketing_group.command("status")
def status() -> None:
    """Show which platforms are configured and connected."""
    from pps_tools.marketing.ai import ai_configured

    hub = _hub()
    table = Table(title="Marketing Hub connections")
    table.add_column("Platform")
    table.add_column("Configured")
    table.add_column("Connected")
    table.add_column("Ad accounts", justify="right")
    table.add_column("Publish targets", justify="right")
    for key, p in hub.platforms.items():
        conn = hub.store.get_connection(key)
        missing = p.missing_env()
        table.add_row(
            p.name,
            "[green]yes[/green]" if p.configured else f"[red]missing {', '.join(missing)}[/red]",
            "[green]yes[/green]" if conn else "no",
            str(len(hub.store.list_accounts(key, enabled_only=True))) if conn else "-",
            str(len(hub.store.list_targets(key, enabled_only=True))) if conn else "-",
        )
    console.print(table)
    console.print(f"Demo mode: [bold]{hub.demo_setting()}[/bold] ({'showing demo data' if hub.demo_active() else 'showing live data'})")
    console.print(f"Claude AI features: {'[green]ready[/green]' if ai_configured() else '[yellow]set ANTHROPIC_API_KEY[/yellow]'}")


@marketing_group.command("report")
@click.option("--range", "preset", default="30d", show_default=True,
              type=click.Choice(["7d", "14d", "30d", "90d", "mtd", "last_month"]), help="Date range.")
@click.option("--format", "fmt", default="table", type=click.Choice(["table", "csv", "json"]), show_default=True)
@click.option("--refresh", is_flag=True, help="Ignore cached numbers and ask every platform again.")
def report(preset: str, fmt: str, refresh: bool) -> None:
    """Spend and results by channel for a date range."""
    from pps_tools.marketing import analytics as an
    from pps_tools.marketing.models import network_for

    hub = _hub()
    period = an.resolve_period(preset)
    rows, errors = hub.metrics(period.start, period.end, refresh=refresh)
    for name, msg in errors.items():
        console.print(f"[red]{name}:[/red] {msg}", highlight=False)
    networks = an.by_network(rows)
    total = an.totals(rows)

    if fmt == "json":
        click.echo(json.dumps({
            "period": {"start": period.start.isoformat(), "end": period.end.isoformat()},
            "channels": {k: t.to_dict() for k, t in networks},
            "total": total.to_dict(),
            "demo": hub.demo_active(),
        }, indent=2))
        return
    if fmt == "csv":
        import csv

        writer = csv.writer(sys.stdout)
        writer.writerow(["channel", "spend", "impressions", "clicks", "conversions", "revenue", "cpa", "roas"])
        for key, t in networks + [("total", total)]:
            writer.writerow([key, f"{t.spend:.2f}", t.impressions, t.clicks, f"{t.conversions:.2f}",
                             f"{t.conversion_value:.2f}", f"{t.cpa:.2f}" if t.cpa else "", f"{t.roas:.2f}" if t.roas else ""])
        return

    title = f"{period.label}: {period.start} → {period.end}" + (" (demo data)" if hub.demo_active() else "")
    table = Table(title=title)
    for col, justify in (("Channel", "left"), ("Spend", "right"), ("Clicks", "right"), ("CTR", "right"),
                         ("Conv.", "right"), ("Cost/conv.", "right"), ("Revenue", "right"), ("ROAS", "right")):
        table.add_column(col, justify=justify)

    def add(label: str, t, style: str = "") -> None:
        table.add_row(
            label,
            f"{t.spend:,.2f}",
            f"{t.clicks:,}",
            f"{t.ctr * 100:.2f}%" if t.ctr is not None else "-",
            f"{t.conversions:,.0f}",
            f"{t.cpa:,.2f}" if t.cpa else "-",
            f"{t.conversion_value:,.2f}",
            f"{t.roas:.2f}x" if t.roas and t.conversion_value else "-",
            style=style,
        )

    for key, t in networks:
        add(network_for(key).label, t)
    add("All channels", total, "bold")
    console.print(table)


@marketing_group.command("publish-due")
def publish_due_cmd() -> None:
    """Publish every scheduled post whose time has come (run every few minutes from cron)."""
    from pps_tools.marketing.publisher import publish_due

    hub = _hub()
    done = publish_due(hub)
    for post_id in done:
        post = hub.store.get_post(post_id)
        ok = sum(1 for r in post["results"].values() if r.get("ok"))
        console.print(f"Post {post_id}: {post['status']} ({ok}/{len(post['results'])} destinations)")
    if not done:
        console.print("No posts due.")


@marketing_group.command("run-rules")
@click.option("--dry-run", is_flag=True, help="Show what would happen without changing anything.")
def run_rules(dry_run: bool) -> None:
    """Evaluate the enabled automation rules (run hourly from cron)."""
    from pps_tools.marketing.rules import evaluate

    hub = _hub()
    rules = hub.store.list_rules(enabled_only=True)
    if not rules:
        console.print("No enabled rules. Create them on the Automation page.")
        return
    problems: dict = {}
    outcomes = evaluate(hub, rules, dry_run=dry_run, problems=problems)
    for name, msg in problems.items():
        console.print(f"[yellow]Skipped {name}[/yellow] (couldn't read its numbers): {msg}", highlight=False)
    if not outcomes:
        console.print(f"{len(rules)} rule(s) checked; no campaign matched.")
        return
    table = Table(title=("Dry run — " if dry_run else "") + f"{len(outcomes)} match(es)")
    for col in ("Rule", "Campaign", "Platform", "Result"):
        table.add_column(col)
    for o in outcomes:
        table.add_row(o.rule_name, o.campaign_name, hub.platform(o.platform).name, f"{o.status}: {o.message}")
    console.print(table)
    if not dry_run:
        hub.store.log("rule.run", f"Ran {len(rules)} rule(s) from the command line: {len(outcomes)} match(es)")
