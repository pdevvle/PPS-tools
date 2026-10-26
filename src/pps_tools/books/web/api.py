"""REST API (JSON), authenticated with ``Authorization: Bearer <token>``.

A token acts as the user who created it, with that user's role. Transactions
take the same fields as the forms (see ``services.transactions.save``).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, or_, select
from werkzeug.exceptions import HTTPException

from pps_tools.books import __version__
from pps_tools.books.db import utcnow
from pps_tools.books.models import Account, ApiToken, Customer, Item, LedgerEntry, Transaction, Vendor
from pps_tools.books.services import audit
from pps_tools.books.services import transactions as tx
from pps_tools.books.services import users as user_service
from pps_tools.books.services.dates import parse_date
from pps_tools.books.services.errors import BooksError, ClosedPeriodError
from pps_tools.books.txn_types import TXN_TYPES
from pps_tools.books.web import core

bp = Blueprint("api", __name__, url_prefix="/api/v1")

MAX_LIMIT = 500


class ApiError(Exception):
    def __init__(self, status: int, message: str, field: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.field = field


@bp.errorhandler(ApiError)
def _api_error(exc: ApiError):
    body = {"error": exc.message}
    if exc.field:
        body["field"] = exc.field
    return jsonify(body), exc.status


@bp.errorhandler(BooksError)
def _books_error(exc: BooksError):
    core.db().rollback()
    body = {"error": str(exc)}
    if getattr(exc, "field", None):
        body["field"] = exc.field
    return jsonify(body), 409 if isinstance(exc, ClosedPeriodError) else 422


@bp.errorhandler(HTTPException)
def _http_error(exc: HTTPException):
    return jsonify({"error": exc.description or exc.name}), exc.code


@bp.before_request
def _authenticate():
    header = request.headers.get("Authorization", "")
    scheme, _, raw = header.partition(" ")
    if scheme.lower() != "bearer" or not raw.strip():
        raise ApiError(401, "Send your API token as 'Authorization: Bearer <token>'.")
    digest = hashlib.sha256(raw.strip().encode()).hexdigest()
    s = core.db()
    tok = s.scalar(select(ApiToken).where(ApiToken.token_hash == digest))
    if tok is None or tok.revoked or not tok.user.active:
        raise ApiError(401, "That API token isn't valid.")
    g.user = tok.user
    g.api_token = tok
    now = utcnow()
    if tok.last_used_at is None or now - tok.last_used_at > timedelta(minutes=1):
        tok.last_used_at = now
        s.commit()


def _need(permission: str) -> None:
    if not core.can(permission):
        raise ApiError(403, f"This token's user doesn't have the '{permission}' permission.")


def _json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "Send a JSON object in the request body.")
    return data


def _page() -> tuple[int, int]:
    try:
        limit = min(MAX_LIMIT, max(1, int(request.args.get("limit", 100))))
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        raise ApiError(400, "limit and offset are numbers.") from None
    return limit, offset


def _plain(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return format(v, "f")
    return v


def _row(obj, fields: list[str]) -> dict:
    return {f: _plain(getattr(obj, f)) for f in fields}


# -- company ------------------------------------------------------------------------------------------


@bp.route("/company")
def company():
    c = core.company()
    return jsonify({"name": c.name, "legal_name": c.legal_name, "email": c.email, "phone": c.phone,
                    "home_currency": c.home_currency, "fiscal_year_start_month": c.fiscal_year_start_month,
                    "accounting_method": c.accounting_method, "closing_date": _plain(c.closing_date),
                    "version": __version__, "user": {"id": g.user.id, "name": g.user.name, "role": g.user.role}})


# -- names and lists -----------------------------------------------------------------------------------

CUSTOMER_FIELDS = ["id", "display_name", "company_name", "title", "first_name", "last_name", "email", "cc_email",
                   "phone", "mobile", "website", "bill_line1", "bill_line2", "bill_city", "bill_state", "bill_postal",
                   "bill_country", "ship_same_as_bill", "ship_line1", "ship_line2", "ship_city", "ship_state",
                   "ship_postal", "ship_country", "terms_id", "taxable", "tax_exemption_reason", "resale_number",
                   "default_tax_rate_id", "parent_id", "is_project", "notes", "active", "created_at", "updated_at"]
VENDOR_FIELDS = ["id", "display_name", "company_name", "first_name", "last_name", "email", "phone", "website",
                 "bill_line1", "bill_line2", "bill_city", "bill_state", "bill_postal", "bill_country", "terms_id",
                 "account_number", "track_1099", "default_expense_account_id", "notes", "active", "created_at"]
ITEM_FIELDS = ["id", "name", "sku", "type", "category_id", "unit", "description", "sales_price", "income_account_id",
               "taxable", "purchase_description", "cost", "expense_account_id", "asset_account_id",
               "preferred_vendor_id", "qty_on_hand", "reorder_point", "active"]
ACCOUNT_FIELDS = ["id", "number", "name", "type", "detail_type", "parent_id", "description", "active", "system_key"]

# What a client may set when creating or updating.
WRITABLE = {
    "customer": [f for f in CUSTOMER_FIELDS if f not in ("id", "is_project", "created_at", "updated_at")],
    "vendor": [f for f in VENDOR_FIELDS if f not in ("id", "created_at")],
    "item": [f for f in ITEM_FIELDS if f not in ("id", "qty_on_hand")],
}
MODELS = {"customers": (Customer, "customer", CUSTOMER_FIELDS, "sales.view"),
          "vendors": (Vendor, "vendor", VENDOR_FIELDS, "purchases.view"),
          "items": (Item, "item", ITEM_FIELDS, "sales.view")}


def _model(kind: str):
    if kind not in MODELS:
        raise ApiError(404, f"Unknown list '{kind}'.")
    return MODELS[kind]


@bp.route("/<kind>", methods=["GET"])
def list_names(kind: str):
    if kind == "accounts":
        _need("accounting.view")
        rows = core.db().scalars(select(Account).order_by(Account.number, Account.name)).all()
        return jsonify({"data": [dict(_row(a, ACCOUNT_FIELDS), balance_cents=None) for a in rows]})
    model, _, fields, perm = _model(kind)
    _need(perm)
    q = select(model)
    if request.args.get("active", "true").lower() != "all":
        q = q.where(model.active.is_(request.args.get("active", "true").lower() != "false"))
    needle = (request.args.get("q") or "").strip()
    name_col = model.name if model is Item else model.display_name
    if needle:
        q = q.where(or_(name_col.ilike(f"%{needle}%"), *([model.email.ilike(f"%{needle}%")] if model is not Item else [])))
    since = request.args.get("updated_since")
    if since and hasattr(model, "updated_at"):
        try:
            q = q.where(model.updated_at >= datetime.fromisoformat(since))
        except ValueError:
            raise ApiError(400, "updated_since is an ISO date or datetime.") from None
    limit, offset = _page()
    s = core.db()
    total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = s.scalars(q.order_by(name_col).offset(offset).limit(limit)).all()
    return jsonify({"data": [_row(r, fields) for r in rows], "total": total, "limit": limit, "offset": offset})


@bp.route("/<kind>/<int:obj_id>", methods=["GET"])
def get_name(kind: str, obj_id: int):
    model, _, fields, perm = _model(kind)
    _need(perm)
    obj = core.db().get(model, obj_id)
    if obj is None:
        raise ApiError(404, "Not found.")
    out = _row(obj, fields)
    if model in (Customer, Vendor):
        # What they owe (or are owed): their side of A/R or A/P, credits netted.
        s = core.db()
        kind, col, sign = ("ar", LedgerEntry.customer_id, 1) if model is Customer else ("ap", LedgerEntry.vendor_id, -1)
        ids = select(Account.id).where(Account.type == kind)
        out["balance_cents"] = sign * int(s.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0))
                                                   .where(LedgerEntry.account_id.in_(ids), col == obj.id)) or 0)
    return jsonify(out)


@bp.route("/<kind>", methods=["POST"])
def create_name(kind: str):
    model, label, fields, _ = _model(kind)
    _need("lists.edit")
    obj = model(active=True)
    if model is Item:
        obj.type = "service"
        obj.taxable = True
    _apply(obj, label, _json_body())
    s = core.db()
    s.add(obj)
    s.flush()
    audit.record(s, g.user, "create", label, obj.id, name=getattr(obj, "display_name", None) or obj.name,
                 summary=f"Added {label} via API")
    s.commit()
    return jsonify(_row(obj, fields)), 201


@bp.route("/<kind>/<int:obj_id>", methods=["PATCH", "PUT"])
def update_name(kind: str, obj_id: int):
    model, label, fields, _ = _model(kind)
    _need("lists.edit")
    s = core.db()
    obj = s.get(model, obj_id)
    if obj is None:
        raise ApiError(404, "Not found.")
    _apply(obj, label, _json_body())
    audit.record(s, g.user, "update", label, obj.id, name=getattr(obj, "display_name", None) or obj.name,
                 summary=f"Updated {label} via API")
    s.commit()
    return jsonify(_row(obj, fields))


def _apply(obj, label: str, data: dict) -> None:
    s = core.db()
    unknown = sorted(set(data) - set(WRITABLE[label]))
    if unknown:
        raise ApiError(400, f"Fields that can't be set: {', '.join(unknown)}.")
    for key, value in data.items():
        col = obj.__table__.columns[key]
        py = getattr(col.type, "python_type", str) if not hasattr(col.type, "impl") else Decimal
        try:
            if value is None or value == "":
                if not col.nullable:
                    raise ApiError(422, f"{key} can't be empty.", key)
                value = None
            elif py is bool:
                value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
            elif py is int:
                value = int(value)
            elif py is Decimal:
                value = Decimal(str(value))
            elif py is date:
                value = parse_date(value)
            else:
                value = str(value).strip()
        except (ValueError, ArithmeticError):
            raise ApiError(422, f"{key} has the wrong type.", key) from None
        setattr(obj, key, value)
    name_attr = "name" if isinstance(obj, Item) else "display_name"
    name = getattr(obj, name_attr)
    if not name:
        raise ApiError(422, f"{name_attr} is required.", name_attr)
    model = type(obj)
    dup = s.scalar(select(model.id).where(func.lower(getattr(model, name_attr)) == name.lower(),
                                          model.id != (obj.id or 0)))
    if dup:
        raise ApiError(409, f"Another {label} is already named '{name}'.", name_attr)
    if isinstance(obj, Item) and obj.type not in ("service", "non_inventory", "inventory", "bundle"):
        raise ApiError(422, "type is service, non_inventory, inventory or bundle.", "type")


# -- transactions ----------------------------------------------------------------------------------------


def _txn_json(t: Transaction, full: bool = False) -> dict:
    out = {"id": t.id, "type": t.type, "number": t.number, "date": _plain(t.date), "due_date": _plain(t.due_date),
           "customer_id": t.customer_id, "vendor_id": t.vendor_id, "name": t.entity_name,
           "total_cents": t.total_cents, "balance_cents": t.balance_cents, "status": tx.status(t)[1] or t.status,
           "voided": t.voided, "memo": t.memo, "created_at": _plain(t.created_at), "updated_at": _plain(t.updated_at)}
    if full:
        payload = tx.to_payload(t)
        out.update({k: _plain(v) for k, v in payload.items() if k not in out})
        out["subtotal_cents"] = t.subtotal_cents
        out["tax_cents"] = t.tax_cents
        out["entries"] = [{"account_id": e.account_id, "amount_cents": e.amount_cents, "date": _plain(e.date)}
                          for e in t.entries]
    return out


def _load(txn_id: int) -> Transaction:
    t = core.db().get(Transaction, txn_id)
    if t is None:
        raise ApiError(404, "Transaction not found.")
    if not user_service.can_view_type(g.user, t.type):
        raise ApiError(403, "This token's user can't see that kind of transaction.")
    return t


@bp.route("/transactions", methods=["GET"])
def list_transactions():
    s = core.db()
    q = select(Transaction)
    types = [t for t in (request.args.get("type") or "").split(",") if t]
    for t in types:
        if t not in TXN_TYPES:
            raise ApiError(400, f"Unknown transaction type '{t}'.")
    visible = [t for t in TXN_TYPES if user_service.can_view_type(g.user, t)]
    q = q.where(Transaction.type.in_([t for t in (types or visible) if t in visible]))
    try:
        if request.args.get("since"):
            q = q.where(Transaction.date >= parse_date(request.args["since"]))
        if request.args.get("until"):
            q = q.where(Transaction.date <= parse_date(request.args["until"]))
        if request.args.get("updated_since"):
            q = q.where(Transaction.updated_at >= datetime.fromisoformat(request.args["updated_since"]))
    except ValueError:
        raise ApiError(400, "Dates are YYYY-MM-DD.") from None
    for key in ("customer_id", "vendor_id"):
        if request.args.get(key, type=int):
            q = q.where(getattr(Transaction, key) == request.args.get(key, type=int))
    if request.args.get("open") == "true":
        q = q.where(Transaction.balance_cents != 0, Transaction.voided.is_(False))
    limit, offset = _page()
    total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = s.scalars(q.order_by(Transaction.date.desc(), Transaction.id.desc()).offset(offset).limit(limit)).all()
    return jsonify({"data": [_txn_json(t) for t in rows], "total": total, "limit": limit, "offset": offset})


@bp.route("/transactions/<int:txn_id>", methods=["GET"])
def get_transaction(txn_id: int):
    return jsonify(_txn_json(_load(txn_id), full=True))


@bp.route("/transactions", methods=["POST"])
def create_transaction():
    data = _json_body()
    ttype = data.get("type")
    if ttype not in TXN_TYPES:
        raise ApiError(422, "Set 'type' to a transaction type, like invoice or expense.", "type")
    if not user_service.can_edit_type(g.user, ttype):
        raise ApiError(403, "This token's user can't create that kind of transaction.")
    s = core.db()
    txn = tx.save(s, data, user=g.user, closing_password=data.pop("closing_password", None), source="api")
    s.commit()
    return jsonify(_txn_json(txn, full=True)), 201


@bp.route("/transactions/<int:txn_id>", methods=["PUT", "PATCH"])
def update_transaction(txn_id: int):
    txn = _load(txn_id)
    if not user_service.can_edit_type(g.user, txn.type):
        raise ApiError(403, "This token's user can't change that kind of transaction.")
    data = _json_body()
    if request.method == "PATCH":
        merged = tx.to_payload(txn)
        merged.update(data)
        data = merged
    data["type"] = txn.type
    s = core.db()
    txn = tx.save(s, data, txn=txn, user=g.user, closing_password=data.pop("closing_password", None))
    s.commit()
    return jsonify(_txn_json(txn, full=True))


@bp.route("/transactions/<int:txn_id>", methods=["DELETE"])
def delete_transaction(txn_id: int):
    txn = _load(txn_id)
    if not user_service.can_edit_type(g.user, txn.type):
        raise ApiError(403, "This token's user can't delete that kind of transaction.")
    s = core.db()
    tx.delete(s, txn, user=g.user, closing_password=request.args.get("closing_password"))
    s.commit()
    return "", 204


@bp.route("/transactions/<int:txn_id>/void", methods=["POST"])
def void_transaction(txn_id: int):
    txn = _load(txn_id)
    if not user_service.can_edit_type(g.user, txn.type):
        raise ApiError(403, "This token's user can't void that kind of transaction.")
    s = core.db()
    body = request.get_json(silent=True) or {}
    tx.void(s, txn, user=g.user, closing_password=body.get("closing_password"))
    s.commit()
    return jsonify(_txn_json(txn, full=True))


# -- reports --------------------------------------------------------------------------------------------


@bp.route("/reports", methods=["GET"])
def list_reports():
    _need("reports.view")
    from pps_tools.books.services import reports

    return jsonify({"data": [{"key": k, "title": r.title, "category": r.category, "description": r.description}
                             for k, r in reports.REGISTRY.items()]})


@bp.route("/reports/<key>", methods=["GET"])
def run_report(key: str):
    _need("reports.view")
    from pps_tools.books.services import reports

    if key not in reports.REGISTRY:
        raise ApiError(404, f"Unknown report '{key}'. GET /api/v1/reports lists them.")
    r = reports.run(core.db(), key, reports.Params.from_args(request.args.to_dict()))
    return jsonify({"key": key, "title": r.title, "subtitle": r.subtitle, "basis": r.basis,
                    "columns": [{"key": c.key, "label": c.label, "kind": c.kind} for c in r.columns],
                    "rows": [{"kind": row.kind, "level": row.level,
                              "cells": {k: _plain(v) for k, v in row.cells.items()}} for row in r.rows],
                    "notes": r.notes, "amounts_in": "cents"})
