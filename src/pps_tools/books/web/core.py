"""Shared web plumbing: the request's DB session, the signed-in user,
permission decorators, CSRF, and form parsing helpers."""

from __future__ import annotations

import hmac
import re
import secrets
from datetime import date
from functools import wraps
from typing import Any, Callable, Optional

from flask import abort, current_app, flash, g, redirect, request, session, url_for
from sqlalchemy.orm import Session

from pps_tools.books.models import Company, User
from pps_tools.books.services import users as user_service
from pps_tools.books.services.errors import BooksError

CSRF_EXEMPT_PREFIXES = ("/stripe/webhook", "/api/")


def db() -> Session:
    if "db" not in g:
        g.db = current_app.extensions["books"]["session_factory"]()
    return g.db


def config():
    return current_app.extensions["books"]["config"]


def company() -> Optional[Company]:
    if "company" not in g:
        g.company = db().get(Company, 1)
    return g.company


def current_user() -> Optional[User]:
    if "user" not in g:
        uid = session.get("uid")
        user = db().get(User, uid) if uid else None
        if user is not None and (not user.active or session.get("pwv") != _password_version(user)):
            user = None
        g.user = user
    return g.user


def _password_version(user: User) -> str:
    # Changing the password signs out every other session.
    return user.password_hash[-12:]


def login(user: User) -> None:
    session.clear()
    session["uid"] = user.id
    session["pwv"] = _password_version(user)
    session.permanent = True
    g.user = user


def logout() -> None:
    session.clear()
    g.pop("user", None)


def can(permission: str) -> bool:
    return user_service.can(current_user(), permission)


def requires(permission: str) -> Callable:
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if current_user() is None:
                return redirect(url_for("auth.login", next=request.full_path))
            if not can(permission):
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return deco


# -- CSRF -----------------------------------------------------------------------------


def csrf_token() -> str:
    tok = session.get("_csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["_csrf"] = tok
    return tok


def check_csrf() -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if any(request.path.startswith(p) for p in CSRF_EXEMPT_PREFIXES):
        return
    sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
    expected = session.get("_csrf") or ""
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, "Your session expired or the form was stale. Go back, refresh the page and try again.")


# -- forms ----------------------------------------------------------------------------------


def f(name: str, default: Any = None) -> Any:
    value = request.form.get(name)
    if value is None:
        return default
    return value.strip() if isinstance(value, str) else value


def f_int(name: str) -> Optional[int]:
    value = request.form.get(name, "").strip()
    try:
        return int(value) if value else None
    except ValueError:
        return None


def f_bool(name: str) -> bool:
    return request.form.get(name, "").lower() in ("1", "on", "true", "yes")


_ROW = re.compile(r"^(?P<prefix>[a-z]+)-(?P<idx>\d+)-(?P<field>[a-z_0-9]+)$")


def indexed_rows(prefix: str, bools: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Rows posted as ``<prefix>-<n>-<field>``, in the order of their ``pos`` field."""
    rows: dict[int, dict[str, Any]] = {}
    for key in request.form:
        m = _ROW.match(key)
        if not m or m.group("prefix") != prefix:
            continue
        idx = int(m.group("idx"))
        rows.setdefault(idx, {})[m.group("field")] = request.form.get(key, "").strip()
    out = []
    for idx, row in rows.items():
        for b in bools:
            row[b] = row.get(b, "") in ("1", "on", "true", "yes")
        row.setdefault("pos", str(idx))
        out.append(row)
    out.sort(key=lambda r: (int(r.get("pos") or 0)))
    return out


def flash_error(exc: Exception) -> None:
    if isinstance(exc, BooksError):
        flash(str(exc), "error")
    else:  # pragma: no cover - defensive
        current_app.logger.exception("unexpected error")
        flash("Something went wrong saving that. Nothing was changed.", "error")


def safe_next(default: str) -> str:
    target = request.args.get("next") or request.form.get("next") or ""
    if target.startswith("/") and not target.startswith("//"):
        return target
    return default


def today() -> date:
    return date.today()


def client_ip() -> str:
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()


def paginate(query_count: int, per_page: int = 50) -> tuple[int, int, int]:
    """(page, offset, pages) from ?page=."""
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    pages = max(1, (query_count + per_page - 1) // per_page)
    page = min(page, pages)
    return page, (page - 1) * per_page, pages
