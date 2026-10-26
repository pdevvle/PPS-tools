"""Sign-in: first-run setup, login/logout, invitations, password changes and resets."""

from __future__ import annotations

import threading
import time
from datetime import timedelta

from flask import Blueprint, current_app, session
from werkzeug.security import check_password_hash, generate_password_hash

from pps_tools.switchboard import config, db
from pps_tools.switchboard.api.core import me_payload
from pps_tools.switchboard.services import mailer, settings
from pps_tools.switchboard.util import iso, now, now_iso, parse_iso, pick_color, token
from pps_tools.switchboard.web import (
    ApiError, audit, bad_request, body, client_ip, conflict, current_user, login_required, ok,
)

bp = Blueprint("auth", __name__)

MIN_PASSWORD = 8
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()
WINDOW_SECONDS = 15 * 60
MAX_FAILURES = 10


def _throttle_keys(email: str) -> list[str]:
    return [f"ip:{client_ip()}", f"email:{email}"]


def _check_throttle(email: str) -> None:
    cutoff = time.time() - WINDOW_SECONDS
    with _failures_lock:
        for key in _throttle_keys(email):
            recent = [t for t in _failures.get(key, []) if t > cutoff]
            _failures[key] = recent
            if len(recent) >= MAX_FAILURES:
                raise ApiError(429, "too_many_attempts", "Too many failed sign-in attempts. Try again in a few minutes.")


def _record_failure(email: str) -> None:
    with _failures_lock:
        for key in _throttle_keys(email):
            _failures.setdefault(key, []).append(time.time())


def _validate_password(password: str | None) -> str:
    if not password or len(password) < MIN_PASSWORD:
        bad_request(f"Use at least {MIN_PASSWORD} characters for the password", code="weak_password")
    return password


def _start_session(user: dict, remember: bool = True) -> None:
    session.clear()
    session["uid"] = user["id"]
    session["sv"] = user["session_version"]
    session.permanent = remember


@bp.get("/api/auth/state")
def auth_state():
    user = current_user()
    return ok({
        "setup_required": db.scalar("SELECT COUNT(*) FROM users") == 0,
        "user": me_payload(user) if user else None,
        "org_name": settings.get("org.name"),
        "can_email": mailer.can_send(),
    })


@bp.post("/api/auth/setup")
def setup():
    """Create the workspace and its first owner. Only allowed while there are no users."""
    data = body()
    if db.scalar("SELECT COUNT(*) FROM users"):
        conflict("This workspace is already set up", code="already_setup")
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    if not name or "@" not in email:
        bad_request("Your name and a valid email are required")
    password = _validate_password(data.get("password"))
    org_name = (data.get("org_name") or "").strip() or settings.get("org.name")
    stamp = now_iso()
    with db.transaction():
        uid = db.insert("users", {
            "email": email,
            "name": name,
            "password_hash": generate_password_hash(password),
            "role": "owner",
            "color": pick_color(email),
            "timezone": data.get("timezone"),
            "feed_token": token(),
            "created_at": stamp,
            "updated_at": stamp,
        })
        settings.set("org.name", org_name)
        if data.get("timezone"):
            settings.set("org.timezone", data["timezone"])
        ctx = {"owner_id": uid}
        for module in current_app.extensions["switchboard_modules"]:
            if hasattr(module, "on_setup"):
                module.on_setup(ctx)
    user = db.one("SELECT * FROM users WHERE id = ?", uid)
    _start_session(user)
    return ok({"me": me_payload(user)}, 201)


@bp.post("/api/auth/login")
def login():
    data = body()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    _check_throttle(email)
    user = db.one("SELECT * FROM users WHERE email = ?", email)
    valid = bool(user and user["password_hash"] and check_password_hash(user["password_hash"], password))
    if not valid or not user["is_active"]:
        _record_failure(email)
        if valid and not user["is_active"]:
            raise ApiError(403, "deactivated", "This account has been deactivated")
        raise ApiError(401, "invalid_credentials", "That email and password don't match")
    _start_session(user, remember=data.get("remember", True) is not False)
    db.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", now_iso(), user["id"])
    return ok({"me": me_payload(user)})


@bp.post("/api/auth/logout")
def logout():
    session.clear()
    return ok()


@bp.post("/api/auth/password")
@login_required
def change_password():
    data = body()
    user = current_user()
    if user["password_hash"] and not check_password_hash(user["password_hash"], data.get("current") or ""):
        raise ApiError(400, "wrong_password", "Your current password is incorrect")
    new = _validate_password(data.get("new"))
    version = user["session_version"] + 1
    db.update("users", user["id"], {
        "password_hash": generate_password_hash(new),
        "session_version": version,  # signs out every other session
        "updated_at": now_iso(),
    })
    session["sv"] = version
    audit("user.password_changed", "user", user["id"])
    return ok()


def _user_by_token(column: str, tok: str) -> dict:
    user = db.one(f"SELECT * FROM users WHERE {column} = ?", tok)
    expires = parse_iso(user[column.replace("_token", "_expires_at")]) if user else None
    if not user or not user["is_active"] or (expires and expires < now()):
        raise ApiError(404, "invalid_token", "This link is invalid or has expired")
    return user


@bp.get("/api/auth/invite/<tok>")
def invite_info(tok: str):
    user = _user_by_token("invite_token", tok)
    return ok({"email": user["email"], "name": user["name"], "org_name": settings.get("org.name")})


@bp.post("/api/auth/invite/<tok>")
def accept_invite(tok: str):
    user = _user_by_token("invite_token", tok)
    data = body()
    password = _validate_password(data.get("password"))
    changes = {
        "password_hash": generate_password_hash(password),
        "invite_token": None,
        "invite_expires_at": None,
        "updated_at": now_iso(),
    }
    if (data.get("name") or "").strip():
        changes["name"] = data["name"].strip()
    if data.get("timezone"):
        changes["timezone"] = data["timezone"]
    db.update("users", user["id"], changes)
    user = db.one("SELECT * FROM users WHERE id = ?", user["id"])
    _start_session(user)
    return ok({"me": me_payload(user)})


@bp.post("/api/auth/forgot")
def forgot_password():
    """Email a reset link. Always answers the same way so it can't reveal who has an
    account."""
    email = (body().get("email") or "").strip().lower()
    user = db.one("SELECT * FROM users WHERE email = ? AND is_active = 1", email)
    if user:
        tok = token()
        db.update("users", user["id"], {"reset_token": tok, "reset_expires_at": iso(now() + timedelta(hours=2))})
        link = f"{config.current().base_url}/reset/{tok}"
        mailer.send_system_email(
            user["email"],
            "Reset your Switchboard password",
            f"<p>Someone asked to reset the password for {user['email']}.</p>"
            f"<p><a href=\"{link}\">Choose a new password</a> (valid for 2 hours).</p>"
            "<p style=\"color:#888\">If that wasn't you, ignore this email.</p>",
        )
    return ok({"ok": True, "can_email": mailer.can_send()})


@bp.post("/api/auth/reset/<tok>")
def reset_password(tok: str):
    user = _user_by_token("reset_token", tok)
    password = _validate_password(body().get("password"))
    db.update("users", user["id"], {
        "password_hash": generate_password_hash(password),
        "reset_token": None,
        "reset_expires_at": None,
        "invite_token": None,
        "session_version": user["session_version"] + 1,
        "updated_at": now_iso(),
    })
    user = db.one("SELECT * FROM users WHERE id = ?", user["id"])
    _start_session(user)
    return ok({"me": me_payload(user)})
