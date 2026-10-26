"""Flask application factory."""

from __future__ import annotations

import logging
from datetime import timedelta
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
