"""Flask web dashboard for reviewing & approving QBO categorizations.

Flow:
    1. /            → landing page; "Connect to QuickBooks" if no tokens.
    2. /oauth/start → redirect to Intuit auth.
    3. /oauth/callback → exchange code, store tokens.
    4. /review     → pulls uncategorized transactions, fetches Claude
                     suggestions, shows a table with approve/edit controls.
    5. POST /apply → writes the approved category back to QBO.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from pps_tools.quickbooks.categorizer import Categorizer
from pps_tools.quickbooks.qbo_client import QBOAuth, QBOClient

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def create_app(auth: Optional[QBOAuth] = None) -> Flask:
    app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32).hex())
    app.config["QBO_AUTH"] = auth or QBOAuth()

    # -- helpers --------------------------------------------------------------

    def _client() -> Optional[QBOClient]:
        qbo_auth: QBOAuth = app.config["QBO_AUTH"]
        if qbo_auth.load() is None:
            return None
        return QBOClient(qbo_auth)

    # -- routes ---------------------------------------------------------------

    @app.route("/")
    def index():
        qbo_auth: QBOAuth = app.config["QBO_AUTH"]
        connected = qbo_auth.load() is not None
        configured = bool(qbo_auth.client_id and qbo_auth.client_secret)
        return render_template(
            "qb_index.html",
            connected=connected,
            configured=configured,
            environment=qbo_auth.environment,
        )

    @app.route("/oauth/start")
    def oauth_start():
        qbo_auth: QBOAuth = app.config["QBO_AUTH"]
        if not (qbo_auth.client_id and qbo_auth.client_secret):
            flash("QBO_CLIENT_ID / QBO_CLIENT_SECRET not configured.", "error")
            return redirect(url_for("index"))
        url, state = qbo_auth.authorize_url()
        session["oauth_state"] = state
        return redirect(url)

    @app.route("/oauth/callback")
    def oauth_callback():
        qbo_auth: QBOAuth = app.config["QBO_AUTH"]
        code = request.args.get("code")
        realm_id = request.args.get("realmId")
        state = request.args.get("state")
        expected = session.pop("oauth_state", None)
        if not code or not realm_id:
            flash("Missing code or realmId in callback.", "error")
            return redirect(url_for("index"))
        if expected and state != expected:
            abort(400, "OAuth state mismatch")
        qbo_auth.exchange_code(code, realm_id)
        flash(f"Connected to QuickBooks (company {realm_id}).", "success")
        return redirect(url_for("index"))

    @app.route("/disconnect", methods=["POST"])
    def disconnect():
        app.config["QBO_AUTH"].clear()
        flash("Disconnected.", "info")
        return redirect(url_for("index"))

    @app.route("/review")
    def review():
        client = _client()
        if client is None:
            flash("Connect to QuickBooks first.", "error")
            return redirect(url_for("index"))

        start = request.args.get("start") or None
        end = request.args.get("end") or None
        mode = request.args.get("mode", "uncategorized")

        accounts = client.list_accounts()
        if mode == "all":
            txns = client.list_purchases(start_date=start, end_date=end, limit=100)
        else:
            txns = client.list_uncategorized_purchases(start_date=start, end_date=end, limit=100)

        categorizer = Categorizer(accounts=accounts)
        rows = []
        for t in txns:
            try:
                suggestion = categorizer.suggest(t)
                rows.append({"txn": t, "suggestion": suggestion, "error": None})
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Suggestion failed for %s", t.id)
                rows.append({"txn": t, "suggestion": None, "error": str(exc)})

        return render_template(
            "qb_review.html",
            rows=rows,
            accounts=accounts,
            mode=mode,
            start=start or "",
            end=end or "",
        )

    @app.route("/apply", methods=["POST"])
    def apply():
        client = _client()
        if client is None:
            return jsonify({"ok": False, "error": "not connected"}), 400

        payload = request.get_json(silent=True) or request.form
        txn_id = payload.get("txn_id")
        sync_token = payload.get("sync_token")
        line_id = payload.get("line_id")
        account_id = payload.get("account_id")
        amount = float(payload.get("amount", 0))
        if not (txn_id and sync_token and line_id and account_id):
            return jsonify({"ok": False, "error": "missing fields"}), 400

        from pps_tools.quickbooks.models import Transaction
        stub = Transaction(
            id=str(txn_id),
            txn_type="Purchase",
            sync_token=str(sync_token),
            txn_date="",
            amount=amount,
            line_id=str(line_id),
        )
        updated = client.update_purchase_category(stub, str(account_id))
        return jsonify({
            "ok": True,
            "txn_id": updated.id,
            "new_sync_token": updated.sync_token,
            "account_id": account_id,
        })

    return app
