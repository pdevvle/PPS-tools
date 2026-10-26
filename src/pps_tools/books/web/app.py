"""Flask application factory."""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from flask import Flask, g, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from pps_tools.books import __version__
from pps_tools.books.config import Config
from pps_tools.books.db import create_schema, make_engine, make_session_factory
from pps_tools.books.services import prefs as prefs_service
from pps_tools.books.services import setup as setup_service
from pps_tools.books.services import transactions as txn_service
from pps_tools.books.txn_types import TXN_TYPES
from pps_tools.books.web import core, filters

PKG = Path(__file__).resolve().parent.parent
log = logging.getLogger(__name__)

# Endpoints reachable without signing in.
PUBLIC_BLUEPRINTS = {"public", "stripe_hooks", "api", "static"}
PUBLIC_ENDPOINTS = {"auth.login", "auth.setup", "static", "health"}


def create_app(config: Optional[Config] = None) -> Flask:
    cfg = (config or Config()).resolve()
    app = Flask(__name__, template_folder=str(PKG / "templates"), static_folder=str(PKG / "static"),
                static_url_path="/static")
    app.secret_key = cfg.secret_key
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(cfg.base_url and cfg.base_url.startswith("https://")),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=cfg.max_upload_mb * 1024 * 1024,
        TESTING=cfg.testing,
    )
    engine = make_engine(cfg.database_url)
    create_schema(engine)
    app.extensions["books"] = {"config": cfg, "engine": engine, "session_factory": make_session_factory(engine)}

    filters.register(app)
    # Globals (not just context values) so macros imported without context can use them.
    app.jinja_env.globals.update(csrf_token=core.csrf_token, txn_status=txn_service.status, can=core.can)
    _register_blueprints(app)

    @app.before_request
    def _gate():
        endpoint = request.endpoint or ""
        blueprint = endpoint.split(".", 1)[0] if "." in endpoint else endpoint
        core.check_csrf()
        if blueprint in PUBLIC_BLUEPRINTS or endpoint in PUBLIC_ENDPOINTS:
            return None
        if not setup_service.is_set_up(core.db()):
            return redirect(url_for("auth.setup"))
        if core.current_user() is None:
            return redirect(url_for("auth.login", next=request.full_path if request.method == "GET" else None))
        return None

    @app.before_request
    def _scheduled_work():
        # Without cron, run recurring transactions, reminders and late fees at most hourly while
        # people use the app, on a background thread so no request waits for it.
        if cfg.testing or not app.config.get("BOOKS_IN_APP_SCHEDULER", True):
            return None
        state = app.extensions["books"]
        now = time.monotonic()
        if now - state.get("scheduled_at", float("-inf")) < 3600:
            return None
        state["scheduled_at"] = now
        base_url = (cfg.base_url or request.host_url).rstrip("/")
        threading.Thread(target=_run_scheduled, args=(app, base_url), daemon=True, name="books-scheduler").start()
        return None

    @app.teardown_appcontext
    def _close_db(exc):
        s = g.pop("db", None)
        if s is not None:
            if exc is not None:
                s.rollback()
            s.close()

    @app.context_processor
    def _globals():
        s = core.db()
        try:
            prefs = prefs_service.get_all(s) if setup_service.is_set_up(s) else dict(prefs_service.DEFAULTS)
        except Exception:  # pragma: no cover - before tables exist
            prefs = dict(prefs_service.DEFAULTS)
        return {
            "user": core.current_user(),
            "company": core.company(),
            "can": core.can,
            "csrf_token": core.csrf_token,
            "prefs": _AttrDict(prefs),
            "txn_types": TXN_TYPES,
            "txn_status": txn_service.status,
            "today": core.today(),
            "version": __version__,
            "public_base": (cfg.base_url or request.host_url).rstrip("/"),
        }

    @app.route("/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.errorhandler(403)
    def _forbidden(e):
        return render_template("errors/error.html", code=403, title="You don't have access to that",
                               message="Ask your company admin to change your role if you need it."), 403

    @app.errorhandler(404)
    def _not_found(e):
        return render_template("errors/error.html", code=404, title="Page not found",
                               message="It may have been deleted, or the link is wrong."), 404

    @app.errorhandler(400)
    def _bad_request(e):
        message = e.description if isinstance(e, HTTPException) else "Bad request."
        return render_template("errors/error.html", code=400, title="That didn't work", message=message), 400

    @app.errorhandler(500)
    def _server_error(e):  # pragma: no cover
        log.exception("server error")
        return render_template("errors/error.html", code=500, title="Something went wrong",
                               message="The error was logged. Nothing you entered was saved."), 500

    return app


def _run_scheduled(app: Flask, base_url: str) -> None:
    from pps_tools.books.services import recurring

    books = app.extensions["books"]
    s = books["session_factory"]()
    try:
        if not setup_service.is_set_up(s):
            return
        # Another worker process may have run within the hour; a stamp file in the data folder
        # decides (kept out of company prefs so it can't race a settings save).
        stamp = books["config"].data_dir / ".scheduler_last_run"
        try:
            if time.time() - stamp.stat().st_mtime < 3300:
                return
        except FileNotFoundError:
            pass
        stamp.touch()
        report = recurring.run_scheduled(s, books["config"], date.today(), base_url=base_url)
        s.commit()
        if report.created or report.errors:
            log.info("scheduled work: %d created, %d errors", len(report.created), len(report.errors))
        for err in report.errors:
            log.warning("scheduled work: %s", err)
    except Exception:  # pragma: no cover - never let the background thread take the app down
        s.rollback()
        log.exception("scheduled work failed")
    finally:
        s.close()


class _AttrDict(dict):
    def __getattr__(self, key):
        return self.get(key)


def _register_blueprints(app: Flask) -> None:
    from pps_tools.books.web import (accounting, api, attachments, audit, auth, banking, budgets, dashboard,
                                     expenses, items, lists, names, payments, projects, public, recurring,
                                     reports, sales, search, settings, stripe_hooks, tax, time, txn)

    for module in (auth, dashboard, txn, sales, expenses, names, items, accounting, banking, reports, tax,
                   settings, lists, recurring, budgets, time, projects, payments, audit, search, attachments,
                   public, stripe_hooks, api):
        app.register_blueprint(module.bp)
