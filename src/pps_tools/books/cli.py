"""`pps books`: run PPS Books and its scheduled jobs from the command line."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _config(data_dir: Optional[str] = None):
    from pps_tools.books.config import Config

    cfg = Config()
    if data_dir:
        cfg.data_dir = Path(data_dir)
        cfg.database_url = None
        cfg.secret_key = None
    return cfg.resolve()


def _session(cfg):
    from pps_tools.books.db import create_schema, make_engine, make_session_factory

    engine = make_engine(cfg.database_url)
    create_schema(engine)
    return make_session_factory(engine)(), engine


data_dir_option = click.option("--data-dir", envvar="BOOKS_DATA_DIR", default=None,
                               help="Folder for the database, attachments and keys (BOOKS_DATA_DIR, default ./books-data).")


@click.group("books")
def books_group():
    """PPS Books: double-entry bookkeeping with Stripe payments.

    \b
      pps books serve             # open the web app (http://127.0.0.1:5080)
      pps books demo              # a demo company with six months of activity
      pps books run-scheduled     # recurring transactions, reminders, late fees (for cron)
      pps books stripe-sync       # pull Stripe charges, fees, payouts and refunds
      pps books check             # verify the ledger balances

    Settings come from the environment or .env: BOOKS_DATA_DIR, BOOKS_BASE_URL,
    STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, SMTP_*, ANTHROPIC_API_KEY.
    """


@books_group.command("serve")
@data_dir_option
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=5080, show_default=True)
@click.option("--debug", is_flag=True, help="Flask debug mode (never on a shared server).")
def serve(data_dir: Optional[str], host: str, port: int, debug: bool) -> None:
    """Run the web app. For production, put it behind HTTPS (see the README)."""
    from pps_tools.books.web.app import create_app

    cfg = _config(data_dir)
    app = create_app(cfg)
    if host not in ("127.0.0.1", "localhost") and not (cfg.base_url or "").startswith("https://"):
        console.print("[yellow]Warning:[/yellow] reachable from other machines without HTTPS. Set BOOKS_BASE_URL to "
                      "your https:// address and run behind a TLS proxy.")
    console.print(f"PPS Books on [bold]http://{host}:{port}[/bold]  (data in {cfg.data_dir.resolve()})")
    app.run(host=host, port=port, debug=debug, use_reloader=debug)


@books_group.command("setup")
@data_dir_option
@click.option("--company", prompt="Company name")
@click.option("--email", prompt="Your email")
@click.option("--name", prompt="Your name")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--industry", type=click.Choice(["print_shop", "general"]), default="print_shop", show_default=True)
def setup_cmd(data_dir, company, email, name, password, industry) -> None:
    """Create the company and its first admin without the web page."""
    from pps_tools.books.services import setup
    from pps_tools.books.services.errors import BooksError

    cfg = _config(data_dir)
    s, _ = _session(cfg)
    try:
        setup.create_company(s, company, email, name, password, industry=industry)
        s.commit()
    except BooksError as exc:
        raise click.ClickException(str(exc)) from None
    console.print(f"[green]Ready.[/green] Sign in as {email} with [bold]pps books serve[/bold].")


@books_group.command("demo")
@data_dir_option
@click.option("--password", default="demo-books-123", show_default=True, help="Password for demo@example.com.")
def demo_cmd(data_dir: Optional[str], password: str) -> None:
    """Build a demo company (a print shop) in an empty data folder."""
    from pps_tools.books.services import demo, setup

    cfg = _config(data_dir or "books-demo")
    s, _ = _session(cfg)
    if setup.is_set_up(s):
        raise click.ClickException(f"{cfg.data_dir} already has a company. Use another --data-dir.")
    started = time.monotonic()
    demo.build(s, password, today=date.today())
    s.commit()
    console.print(f"[green]Demo company built[/green] in {time.monotonic() - started:.1f}s at {cfg.data_dir.resolve()}.")
    console.print(f"  pps books serve --data-dir {cfg.data_dir}   then sign in as {demo.DEMO_EMAIL} / {password}")


@books_group.command("run-scheduled")
@data_dir_option
def run_scheduled(data_dir: Optional[str]) -> None:
    """Create due recurring transactions, send reminders, add late fees, email scheduled reports."""
    from pps_tools.books.services import recurring, setup

    cfg = _config(data_dir)
    s, _ = _session(cfg)
    if not setup.is_set_up(s):
        raise click.ClickException("No company yet. Run `pps books setup` or open the web app.")
    report = recurring.run_scheduled(s, cfg, date.today(), base_url=(cfg.base_url or "").rstrip("/"))
    s.commit()
    console.print(f"Created {len(report.created)}, sent {report.sent}, autopaid {report.autopaid}, "
                  f"reminders {report.reminders}, late fees {report.late_fees}, reports {report.reports_emailed}.")
    for err in report.errors:
        console.print(f"[red]•[/red] {err}")
    if report.errors:
        raise SystemExit(1)


@books_group.command("stripe-sync")
@data_dir_option
@click.option("--days", default=30, show_default=True, help="How far back to look.")
def stripe_sync(data_dir: Optional[str], days: int) -> None:
    """Record Stripe activity the webhook may have missed (safe to repeat)."""
    from pps_tools.books.services import stripe_service
    from pps_tools.books.services.errors import BooksError

    cfg = _config(data_dir)
    s, _ = _session(cfg)
    try:
        result = stripe_service.sync(s, cfg, since=int(time.time()) - days * 86400)
        s.commit()
    except BooksError as exc:
        raise click.ClickException(str(exc)) from None
    console.print(", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in result.items()))


@books_group.command("reset-password")
@data_dir_option
@click.argument("email")
@click.option("--password", prompt="New password", hide_input=True, confirmation_prompt=True)
def reset_password(data_dir: Optional[str], email: str, password: str) -> None:
    """Set a user's password (and unlock the account)."""
    from sqlalchemy import func, select

    from pps_tools.books.models import User
    from pps_tools.books.services import users
    from pps_tools.books.services.errors import BooksError

    cfg = _config(data_dir)
    s, _ = _session(cfg)
    user = s.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if user is None:
        raise click.ClickException(f"No user with email {email}.")
    try:
        users.set_password(user, password)
    except BooksError as exc:
        raise click.ClickException(str(exc)) from None
    user.failed_logins = 0
    user.locked_until = None
    user.active = True
    s.commit()
    console.print(f"Password changed for {user.name}.")


@books_group.command("recompute-inventory")
@data_dir_option
def recompute_inventory(data_dir: Optional[str]) -> None:
    """Replay every inventory item's history (FIFO) and rebuild cost of goods sold."""
    from pps_tools.books.services import inventory

    cfg = _config(data_dir)
    s, _ = _session(cfg)
    n = inventory.recompute_all(s)
    s.commit()
    console.print(f"Recomputed {n} inventory item{'s' if n != 1 else ''}.")


@books_group.command("check")
@data_dir_option
def check(data_dir: Optional[str]) -> None:
    """Verify the books: every transaction balances, the trial balance is zero, A/R and A/P tie out."""
    from sqlalchemy import func, select

    from pps_tools.books.models import Account, LedgerEntry, Transaction

    cfg = _config(data_dir)
    s, _ = _session(cfg)
    problems = []
    unbalanced = s.execute(select(LedgerEntry.txn_id, func.sum(LedgerEntry.amount_cents))
                           .group_by(LedgerEntry.txn_id).having(func.sum(LedgerEntry.amount_cents) != 0)).all()
    for txn_id, diff in unbalanced:
        problems.append(f"Transaction {txn_id} is off by {diff / 100:.2f}")
    total = s.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0))) or 0
    if total:
        problems.append(f"Trial balance is off by {total / 100:.2f}")
    table = Table("Check", "Books", "Open documents", "Result")
    for kind, ttype, sign in (("ar", "invoice", 1), ("ap", "bill", -1)):
        ids = select(Account.id).where(Account.type == kind)
        ledger = sign * int(s.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0))
                                     .where(LedgerEntry.account_id.in_(ids))) or 0)
        types = ("invoice",) if kind == "ar" else ("bill",)
        credits = ("credit_memo", "payment") if kind == "ar" else ("vendor_credit", "bill_payment")
        open_docs = int(s.scalar(select(func.coalesce(func.sum(Transaction.balance_cents), 0))
                                 .where(Transaction.type.in_(types), Transaction.voided.is_(False))) or 0)
        open_credits = int(s.scalar(select(func.coalesce(func.sum(Transaction.balance_cents), 0))
                                    .where(Transaction.type.in_(credits), Transaction.voided.is_(False))) or 0)
        expected = open_docs - open_credits
        ok = ledger == expected
        table.add_row("A/R" if kind == "ar" else "A/P", f"{ledger / 100:,.2f}", f"{expected / 100:,.2f}",
                      "[green]ok[/green]" if ok else "[red]differs[/red]")
        if not ok:
            problems.append(f"{'A/R' if kind == 'ar' else 'A/P'} ledger {ledger / 100:,.2f} vs open items {expected / 100:,.2f}")
    console.print(table)
    count = s.scalar(select(func.count(Transaction.id))) or 0
    if problems:
        for p in problems:
            console.print(f"[red]•[/red] {p}")
        raise SystemExit(1)
    console.print(f"[green]All {count} transactions balance.[/green]")


@books_group.command("backup")
@data_dir_option
@click.argument("target", type=click.Path(dir_okay=False, writable=True))
def backup(data_dir: Optional[str], target: str) -> None:
    """Write a consistent copy of the SQLite database to TARGET (without stored API credentials)."""
    from pps_tools.books.services import exporter

    cfg = _config(data_dir)
    _, engine = _session(cfg)
    try:
        Path(target).write_bytes(exporter.sqlite_backup(engine))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    console.print(f"Backed up to {target}. Copy {cfg.attachments_dir} too, for attachments.")
