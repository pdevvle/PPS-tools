"""HTTP plumbing shared by every API blueprint: who is calling, what they may do, JSON
in and out, and uniform errors.

Errors are JSON: ``{"error": {"code": "not_found", "message": "..."}}``.
Raise ``ApiError`` (or the helpers below) anywhere inside a request.

Authentication: a signed session cookie for the web app, or ``Authorization: Bearer``
with an API token. Cookie-authenticated writes must carry ``X-Requested-With`` (browsers
won't send custom headers cross-site without CORS, which we never grant) — that is the
CSRF defence, together with SameSite=Lax cookies.
"""

from __future__ import annotations

import functools
from typing import Any, Callable

from flask import g, jsonify, request, session

from pps_tools.switchboard import db
from pps_tools.switchboard.util import now_iso, sha256

ROLES = ("owner", "admin", "manager", "agent", "staff")

# permission -> roles that have it
PERMISSIONS: dict[str, set[str]] = {
    "inbox": {"owner", "admin", "manager", "agent"},
    "admin": {"owner", "admin"},
    "manage_staff": {"owner", "admin", "manager"},
    "view_pay": {"owner", "admin", "manager"},
    "manage_jobs": {"owner", "admin", "manager", "agent"},
    "analytics": {"owner", "admin", "manager"},
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **details):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details

    def to_response(self):
        payload = {"error": {"code": self.code, "message": self.message}}
        if self.details:
            payload["error"]["details"] = self.details
        return jsonify(payload), self.status


def bad_request(message: str, code: str = "bad_request", **details):
    raise ApiError(400, code, message, **details)


def not_found(message: str = "Not found"):
    raise ApiError(404, "not_found", message)


def forbidden(message: str = "You don't have permission to do that"):
    raise ApiError(403, "forbidden", message)


def conflict(message: str, code: str = "conflict", **details):
    raise ApiError(409, code, message, **details)


def ok(data: Any = None, status: int = 200):
    if data is None:
        data = {"ok": True}
    return jsonify(data), status


def body() -> dict:
    """JSON body (or form fields) as a dict; never None."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    if request.form:
        return request.form.to_dict()
    return {}


def require_fields(data: dict, *names: str) -> None:
    missing = [n for n in names if data.get(n) in (None, "", [])]
    if missing:
        bad_request(f"Missing required field{'s' if len(missing) > 1 else ''}: {', '.join(missing)}",
                    code="validation", fields=missing)


def arg_int(name: str, default: int | None = None) -> int | None:
    value = request.args.get(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        bad_request(f"'{name}' must be a number")


def as_int(value, name: str = "value", allow_none: bool = True) -> int | None:
    if value in (None, ""):
        if allow_none:
            return None
        bad_request(f"'{name}' is required")
    try:
        return int(value)
    except (TypeError, ValueError):
        bad_request(f"'{name}' must be a number")


def as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


# -- identity -----------------------------------------------------------------------


def current_user() -> dict | None:
    return getattr(g, "user", None)


def user_id() -> int:
    return g.user["id"]


def can(user: dict | None, perm: str) -> bool:
    if not user:
        return False
    return user["role"] in PERMISSIONS.get(perm, set())


def resolve_user() -> None:
    """before_request hook: populate g.user from the bearer token or session."""
    g.user = None
    g.via_token = False
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        raw = auth[7:].strip()
        row = db.one(
            "SELECT u.*, t.id AS token_id FROM api_tokens t JOIN users u ON u.id = t.user_id "
            "WHERE t.token_hash = ? AND t.revoked_at IS NULL AND u.is_active = 1",
            sha256(raw),
        )
        if row:
            db.execute("UPDATE api_tokens SET last_used_at = ? WHERE id = ?", now_iso(), row.pop("token_id"))
            g.user = row
            g.via_token = True
        return
    uid = session.get("uid")
    if not uid:
        return
    row = db.one("SELECT * FROM users WHERE id = ? AND is_active = 1", uid)
    if row and row["session_version"] == session.get("sv"):
        g.user = row


def csrf_ok() -> bool:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    if getattr(g, "via_token", False):
        return True
    return bool(request.headers.get("X-Requested-With"))


def login_required(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            raise ApiError(401, "unauthorized", "Please sign in")
        return fn(*args, **kwargs)

    return wrapper


def require(*perms: str) -> Callable:
    """Decorator: signed in and holding every listed permission."""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                raise ApiError(401, "unauthorized", "Please sign in")
            for perm in perms:
                if not can(user, perm):
                    forbidden()
            return fn(*args, **kwargs)

        return wrapper

    return deco


def audit(action: str, entity_type: str | None = None, entity_id: int | None = None, data: dict | None = None) -> None:
    user = current_user()
    db.insert("audit_log", {
        "user_id": user["id"] if user else None,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "data_json": db.jdump(data) if data else None,
        "ip": request.headers.get("X-Forwarded-For", request.remote_addr) if request else None,
        "created_at": now_iso(),
    })


def public_user(u: dict | None, include_private: bool = False) -> dict | None:
    """User fields safe to show any signed-in teammate."""
    if not u:
        return None
    out = {
        "id": u["id"],
        "name": u["name"],
        "email": u["email"],
        "role": u["role"],
        "title": u.get("title"),
        "phone": u.get("phone"),
        "color": u.get("color"),
        "timezone": u.get("timezone"),
        "is_active": bool(u.get("is_active", 1)),
        "last_seen_at": u.get("last_seen_at"),
    }
    if include_private:
        out["prefs"] = db.jload(u.get("prefs_json"), {})
        out["has_pin"] = bool(u.get("pin_hash"))
        out["created_at"] = u.get("created_at")
    return out
