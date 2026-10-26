"""Flask application factory."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from pps_tools.switchboard import config as config_mod
from pps_tools.switchboard import db
from pps_tools.switchboard.config import Config
from pps_tools.switchboard.modules import load_modules
from pps_tools.switchboard.web import ApiError, csrf_ok, resolve_user
from pps_tools.switchboard.worker import Task, Worker

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Path prefixes that are never the single-page app.
_NON_SPA_PREFIXES = ("/api/", "/static/", "/public/", "/hooks/", "/widget/", "/feeds/", "/t/")

_worker: Worker | None = None


def create_app(config: Config | None = None, **overrides) -> Flask:
    config = config or Config.from_env(**overrides)
    config_mod.set_current(config)
    config.files_dir.mkdir(parents=True, exist_ok=True)
    db.configure(config.db_path)
    db.migrate()
    from pps_tools.switchboard.services import settings

    settings.invalidate()

    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    app.config.update(
        SECRET_KEY=config.secret_key,
        SESSION_COOKIE_NAME="switchboard_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.base_url.startswith("https://"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        MAX_CONTENT_LENGTH=60 * 1024 * 1024,
        TESTING=config.testing,
    )
    app.json.sort_keys = False
    app.extensions["switchboard"] = config

    modules = load_modules()
    app.extensions["switchboard_modules"] = modules
    for module in modules:
        app.register_blueprint(module.bp)
        if hasattr(module, "on_app"):
            module.on_app(app)

    @app.before_request
    def _identify():
        resolve_user()
        if request.path.startswith("/api/") and not csrf_ok():
            raise ApiError(403, "csrf", "Missing X-Requested-With header")

    @app.teardown_appcontext
    def _close_db(exc):
        db.close()

    @app.errorhandler(ApiError)
    def _api_error(err: ApiError):
        return err.to_response()

    @app.errorhandler(HTTPException)
    def _http_error(err: HTTPException):
        if request.path.startswith(("/api/", "/public/", "/hooks/")):
            code = (err.name or "error").lower().replace(" ", "_")
            return jsonify({"error": {"code": code, "message": err.description}}), err.code
        return err

    @app.errorhandler(Exception)
    def _unhandled(err: Exception):  # pragma: no cover - last resort
        logger.exception("Unhandled error on %s %s", request.method, request.path)
        if request.path.startswith(("/api/", "/public/", "/hooks/")):
            return jsonify({"error": {"code": "server_error", "message": str(err) or "Server error"}}), 500
        return "Server error", 500

    @app.get("/")
    @app.get("/<path:path>")
    def _spa(path: str = ""):
        if ("/" + path).startswith(_NON_SPA_PREFIXES):
            return jsonify({"error": {"code": "not_found", "message": "Not found"}}), 404
        response = send_from_directory(STATIC_DIR, "index.html")
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/manifest.webmanifest")
    def _manifest():
        return send_from_directory(STATIC_DIR, "manifest.webmanifest", mimetype="application/manifest+json")

    if config.start_worker and not config.testing:
        start_worker(modules)
    return app


def collect_tasks(modules) -> list[Task]:
    tasks: list[Task] = []
    for module in modules:
        if hasattr(module, "worker_tasks"):
            tasks.extend(module.worker_tasks())
    return tasks


def start_worker(modules) -> Worker:
    global _worker
    if _worker is not None and _worker.is_alive():
        return _worker
    _worker = Worker(collect_tasks(modules))
    _worker.start()
    return _worker
