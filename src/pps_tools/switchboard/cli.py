"""``pps switchboard ...`` commands: run the server, seed a demo, manage users, back up."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import click

from pps_tools.switchboard.config import DEFAULT_PORT


def _make_app(data_dir: str | None, **kwargs):
    from pps_tools.switchboard.app import create_app
    from pps_tools.switchboard.config import Config

    overrides = {"data_dir": data_dir} if data_dir else {}
    return create_app(Config.from_env(**overrides, **kwargs))


@click.group("switchboard")
def switchboard_group():
    """Switchboard: team inbox, staffing and job scheduling.

    \b
      pps switchboard seed       # optional: a demo workspace to explore
      pps switchboard run        # then open http://localhost:5050
    """


@switchboard_group.command("run")
@click.option("--host", default="127.0.0.1", show_default=True, help="Use 0.0.0.0 to serve your network.")
@click.option("--port", default=DEFAULT_PORT, show_default=True, type=int)
@click.option("--data-dir", envvar="SWITCHBOARD_DATA_DIR", help="Where the database and files live.")
@click.option("--no-worker", is_flag=True, help="Don't run background jobs (mail sync, send later, ...).")
@click.option("--debug", is_flag=True, help="Flask debug mode (auto-reload; never on a shared network).")
@click.option("--open-browser", is_flag=True, help="Open the app in your browser once it starts.")
def run(host, port, data_dir, no_worker, debug, open_browser):
    """Start the web server."""
    from werkzeug.serving import run_simple

    app = _make_app(data_dir, start_worker=not no_worker)
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}"
    click.echo(f"Switchboard running at {url}  (data: {app.extensions['switchboard'].data_dir})")
    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    # One process, many threads: live updates are broadcast in-process.
    run_simple(host, port, app, threaded=True, use_reloader=debug, use_debugger=debug)


@switchboard_group.command("init")
@click.option("--data-dir", envvar="SWITCHBOARD_DATA_DIR")
def init(data_dir):
    """Create or upgrade the database."""
    app = _make_app(data_dir, start_worker=False)
    click.echo(f"Database ready at {app.extensions['switchboard'].db_path}")


@switchboard_group.command("seed")
@click.option("--data-dir", envvar="SWITCHBOARD_DATA_DIR")
@click.option("--reset", is_flag=True, help="Delete the existing database and files first.")
def seed(data_dir, reset):
    """Build a demo print-shop workspace (people, inbox, schedule, jobs)."""
    from pps_tools.switchboard.config import Config
    from pps_tools.switchboard.seed import DEMO_DOMAIN, DEMO_PASSWORD, PEOPLE, seed_demo

    if reset:
        cfg = Config.from_env(**({"data_dir": data_dir} if data_dir else {}))
        if cfg.db_path.exists() and not click.confirm(f"Delete everything in {cfg.data_dir}?"):
            raise click.Abort()
        for suffix in ("", "-wal", "-shm"):
            Path(str(cfg.db_path) + suffix).unlink(missing_ok=True)
        shutil.rmtree(cfg.files_dir, ignore_errors=True)
    _make_app(data_dir, start_worker=False)
    try:
        seed_demo()
    except RuntimeError as exc:
        raise click.ClickException(str(exc))
    click.echo("Demo workspace ready. Sign in as any of:")
    for _key, name, role, title, _color in PEOPLE:
        email = f"{name.split()[0].lower()}@{DEMO_DOMAIN}"
        click.echo(f"  {email:<20} {role:<8} {title}")
    click.echo(f"Password for every demo account: {DEMO_PASSWORD}")


@switchboard_group.command("create-user")
@click.option("--data-dir", envvar="SWITCHBOARD_DATA_DIR")
@click.option("--email", required=True)
@click.option("--name", required=True)
@click.option("--role", type=click.Choice(["owner", "admin", "manager", "agent", "staff"]), default="agent")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def create_user(data_dir, email, name, role, password):
    """Add a person who can sign in (handy if you're locked out)."""
    from werkzeug.security import generate_password_hash

    from pps_tools.switchboard import db
    from pps_tools.switchboard.util import now_iso, pick_color, token

    _make_app(data_dir, start_worker=False)
    email = email.strip().lower()
    with db.transaction():
        existing = db.one("SELECT id FROM users WHERE email = ?", email)
        if existing:
            db.update("users", existing["id"], {"password_hash": generate_password_hash(password), "role": role,
                                                 "is_active": 1})
            click.echo(f"Updated {email}")
            return
        db.insert("users", {
            "email": email, "name": name, "role": role, "password_hash": generate_password_hash(password),
            "color": pick_color(email), "feed_token": token(), "created_at": now_iso(), "updated_at": now_iso(),
        })
    click.echo(f"Created {email} ({role})")


@switchboard_group.command("backup")
@click.argument("destination", type=click.Path(dir_okay=False, writable=True))
@click.option("--data-dir", envvar="SWITCHBOARD_DATA_DIR")
def backup(destination, data_dir):
    """Write a consistent copy of the database (safe while the server runs)."""
    app = _make_app(data_dir, start_worker=False)
    src = sqlite3.connect(str(app.extensions["switchboard"].db_path))
    dst = sqlite3.connect(destination)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    click.echo(f"Backed up to {destination}. Attachments live in {app.extensions['switchboard'].files_dir}")
