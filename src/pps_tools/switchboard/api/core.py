"""Core API: bootstrap, people, teams, notifications, files, reactions, presence and the
live event stream."""

from __future__ import annotations

import time

from flask import Blueprint, Response, current_app, request, send_file
from werkzeug.security import generate_password_hash

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.services import files, notify, reactions, settings, users
from pps_tools.switchboard.util import now_iso, pick_color, token
from pps_tools.switchboard.web import (
    PERMISSIONS, ROLES, as_bool, as_int, audit, bad_request, body, can, current_user,
    forbidden, login_required, not_found, ok, public_user, require, require_fields,
)
from pps_tools.switchboard.worker import Task

bp = Blueprint("core", __name__)

APP_VERSION = "1.0.0"
INVITE_DAYS = 14


def me_payload(user: dict) -> dict:
    out = public_user(user, include_private=True)
    out["permissions"] = sorted(p for p, roles in PERMISSIONS.items() if user["role"] in roles)
    out["team_ids"] = users.team_ids_of(user["id"])
    return out


def bootstrap(user: dict) -> dict:
    all_users = db.query("SELECT * FROM users ORDER BY name COLLATE NOCASE")
    return {
        "me": me_payload(user),
        "settings": settings.public(),
        "users": [public_user(u) for u in all_users],
        "teams": users.teams_with_members(),
        "online": realtime.broker.online_user_ids(),
        "presence": realtime.presence.snapshot(),
        "unread_notifications": notify.unread_count(user["id"]),
        "server_time": now_iso(),
        "version": APP_VERSION,
    }


@bp.get("/api/bootstrap")
@login_required
def get_bootstrap():
    user = current_user()
    data: dict = {}
    for module in current_app.extensions["switchboard_modules"]:
        if hasattr(module, "bootstrap"):
            data.update(module.bootstrap(user) or {})
    return ok(data)


@bp.get("/api/health")
def health():
    return ok({"ok": True, "version": APP_VERSION, "time": now_iso()})


@bp.get("/api/badges")
@login_required
def get_badges():
    """Counts on the left rail: {"inbox": 4, "chat": 2, ...} from each module's badges(user)."""
    user = current_user()
    out: dict = {}
    for module in current_app.extensions["switchboard_modules"]:
        if hasattr(module, "badges"):
            out.update(module.badges(user) or {})
    return ok({"badges": out})


@bp.get("/api/search")
@login_required
def global_search():
    """Command-palette search. Each module's search(user, q, limit) returns
    [{"type", "id", "title", "subtitle", "url", "icon", "group"}]."""
    q = (request.args.get("q") or "").strip()
    limit = min(as_int(request.args.get("limit"), "limit") or 10, 50)
    if len(q) < 2:
        return ok({"items": []})
    user = current_user()
    items: list = []
    for module in current_app.extensions["switchboard_modules"]:
        if hasattr(module, "search"):
            items.extend(module.search(user, q, limit) or [])
    return ok({"items": items})


def search(user: dict, q: str, limit: int) -> list[dict]:
    like = f"%{q}%"
    rows = db.query(
        "SELECT id, name, title, email FROM users WHERE is_active = 1 AND (name LIKE ? OR email LIKE ?) "
        "ORDER BY name LIMIT ?", like, like, limit,
    )
    return [{"type": "user", "id": r["id"], "title": r["name"], "subtitle": r["title"] or r["email"],
             "url": f"/chat/dm/{r['id']}", "icon": "user", "group": "People"} for r in rows if r["id"] != user["id"]]


# -- people -------------------------------------------------------------------------


def _invite_url(tok: str) -> str:
    from pps_tools.switchboard import config

    return f"{config.current().base_url}/invite/{tok}"


def _send_invite(user: dict, invited_by: dict) -> bool:
    from pps_tools.switchboard.services import mailer

    org = settings.get("org.name")
    link = _invite_url(user["invite_token"])
    html = (
        f"<p>Hi {user['name'].split(' ')[0]},</p>"
        f"<p>{invited_by['name']} invited you to join <b>{org}</b> on Switchboard.</p>"
        f"<p><a href=\"{link}\">Accept the invitation</a> to set your password.</p>"
        f"<p style=\"color:#888\">This link expires in {INVITE_DAYS} days.</p>"
    )
    return mailer.send_system_email(user["email"], f"You're invited to {org}", html)


def _set_teams(user_id: int, team_ids) -> None:
    db.execute("DELETE FROM team_members WHERE user_id = ?", user_id)
    for tid in {int(t) for t in team_ids or []}:
        if db.one("SELECT id FROM teams WHERE id = ?", tid):
            db.insert("team_members", {"team_id": tid, "user_id": user_id})


@bp.get("/api/users")
@login_required
def list_users():
    rows = db.query("SELECT * FROM users ORDER BY name COLLATE NOCASE")
    admin = can(current_user(), "admin")
    out = []
    for u in rows:
        item = public_user(u)
        item["team_ids"] = users.team_ids_of(u["id"])
        if admin:
            item["invite_pending"] = bool(u["invite_token"]) and not u["password_hash"]
            item["has_pin"] = bool(u["pin_hash"])
        out.append(item)
    return ok({"items": out})


@bp.post("/api/users")
@require("admin")
def create_user():
    data = body()
    require_fields(data, "email", "name")
    email = data["email"].strip().lower()
    role = data.get("role") or "agent"
    if role not in ROLES:
        bad_request("Unknown role")
    if role == "owner" and current_user()["role"] != "owner":
        forbidden("Only an owner can add another owner")
    if db.one("SELECT id FROM users WHERE email = ?", email):
        bad_request("Someone with that email is already on the team", code="duplicate")
    now = now_iso()
    with db.transaction():
        uid = db.insert("users", {
            "email": email,
            "name": data["name"].strip(),
            "role": role,
            "title": data.get("title"),
            "phone": data.get("phone"),
            "color": data.get("color") or pick_color(email),
            "timezone": data.get("timezone"),
            "invite_token": token(),
            "invite_expires_at": _days_from_now(INVITE_DAYS),
            "feed_token": token(),
            "created_at": now,
            "updated_at": now,
        })
        if data.get("password"):
            db.update("users", uid, {"password_hash": generate_password_hash(data["password"]), "invite_token": None})
        _set_teams(uid, data.get("team_ids"))
        audit("user.create", "user", uid, {"email": email, "role": role})
        realtime.emit("settings.changed", {"what": "users"})
    user = users.get(uid)
    emailed = False
    if user["invite_token"] and as_bool(data.get("send_invite", True)):
        emailed = _send_invite(user, current_user())
    return ok({
        "user": public_user(user),
        "invite_url": _invite_url(user["invite_token"]) if user["invite_token"] else None,
        "emailed": emailed,
    }, 201)


def _days_from_now(days: int) -> str:
    from datetime import timedelta

    from pps_tools.switchboard.util import iso, now

    return iso(now() + timedelta(days=days))


@bp.patch("/api/users/<int:uid>")
@login_required
def update_user(uid: int):
    me = current_user()
    target = users.get(uid)
    if not target:
        not_found("No such person")
    is_admin = can(me, "admin")
    if uid != me["id"] and not is_admin:
        forbidden()
    data = body()
    changes = {}
    for field in ("name", "title", "phone", "color", "timezone"):
        if field in data:
            value = data[field]
            changes[field] = (value.strip() or None) if isinstance(value, str) else value
    if "name" in changes and not changes["name"]:
        bad_request("Name can't be empty")
    if is_admin:
        if "email" in data:
            email = (data["email"] or "").strip().lower()
            other = db.one("SELECT id FROM users WHERE email = ? AND id != ?", email, uid)
            if not email or other:
                bad_request("That email is empty or already in use")
            changes["email"] = email
        if "role" in data and data["role"] != target["role"]:
            if data["role"] not in ROLES:
                bad_request("Unknown role")
            if "owner" in (data["role"], target["role"]) and me["role"] != "owner":
                forbidden("Only an owner can change owners")
            if target["role"] == "owner" and _owner_count() <= 1:
                bad_request("The workspace needs at least one owner")
            changes["role"] = data["role"]
            changes["session_version"] = target["session_version"] + 1
        if "is_active" in data:
            active = 1 if as_bool(data["is_active"]) else 0
            if not active and target["role"] == "owner" and _owner_count() <= 1:
                bad_request("You can't deactivate the only owner")
            if not active and uid == me["id"]:
                bad_request("You can't deactivate yourself")
            changes["is_active"] = active
            if not active:
                changes["session_version"] = target["session_version"] + 1
    with db.transaction():
        if changes:
            changes["updated_at"] = now_iso()
            db.update("users", uid, changes)
        if is_admin and "team_ids" in data:
            _set_teams(uid, data["team_ids"])
        audit("user.update", "user", uid, {k: v for k, v in changes.items() if k != "session_version"})
        realtime.emit("settings.changed", {"what": "users"})
    return ok({"user": public_user(users.get(uid))})


def _owner_count() -> int:
    return db.scalar("SELECT COUNT(*) FROM users WHERE role = 'owner' AND is_active = 1")


@bp.post("/api/users/<int:uid>/invite")
@require("admin")
def reinvite(uid: int):
    """New invite (no password yet) or password-reset link (existing account)."""
    user = users.get(uid)
    if not user:
        not_found("No such person")
    from pps_tools.switchboard import config

    tok = token()
    if user["password_hash"]:
        db.update("users", uid, {"reset_token": tok, "reset_expires_at": _days_from_now(2)})
        link = f"{config.current().base_url}/reset/{tok}"
        return ok({"url": link, "kind": "reset", "emailed": False})
    db.update("users", uid, {"invite_token": tok, "invite_expires_at": _days_from_now(INVITE_DAYS)})
    emailed = _send_invite(users.get(uid), current_user()) if as_bool(body().get("send", True)) else False
    return ok({"url": _invite_url(tok), "kind": "invite", "emailed": emailed})


@bp.get("/api/me")
@login_required
def get_me():
    return ok({"me": me_payload(current_user())})


@bp.patch("/api/me/prefs")
@login_required
def update_prefs():
    """Shallow-merge into prefs; nested 'notify' map is merged too."""
    data = body()
    prefs = db.jload(current_user()["prefs_json"], {}) or {}
    for key, value in data.items():
        if key == "notify" and isinstance(value, dict):
            prefs.setdefault("notify", {}).update(value)
        elif value is None:
            prefs.pop(key, None)
        else:
            prefs[key] = value
    db.update("users", current_user()["id"], {"prefs_json": db.jdump(prefs), "updated_at": now_iso()})
    return ok({"prefs": prefs})


@bp.post("/api/me/pin")
@login_required
def set_pin():
    pin = str(body().get("pin") or "").strip()
    if not (pin.isdigit() and 4 <= len(pin) <= 8):
        bad_request("PIN must be 4–8 digits")
    db.update("users", current_user()["id"], {"pin_hash": generate_password_hash(pin)})
    return ok()


@bp.post("/api/me/feed-token")
@login_required
def rotate_feed_token():
    tok = token()
    db.update("users", current_user()["id"], {"feed_token": tok})
    return ok({"feed_token": tok})


# -- teams --------------------------------------------------------------------------


def _team_payload(data: dict, partial: bool) -> dict:
    out = {}
    if "name" in data or not partial:
        name = (data.get("name") or "").strip()
        if not name:
            bad_request("Team name is required")
        out["name"] = name
    for field in ("color", "description"):
        if field in data:
            out[field] = data[field] or None
    if "deliver_to_members" in data:
        out["deliver_to_members"] = 1 if as_bool(data["deliver_to_members"]) else 0
    if "assignment_mode" in data:
        if data["assignment_mode"] not in ("manual", "round_robin", "load_balanced", "on_shift"):
            bad_request("Unknown assignment mode")
        out["assignment_mode"] = data["assignment_mode"]
    return out


def _set_members(team_id: int, member_ids) -> None:
    db.execute("DELETE FROM team_members WHERE team_id = ?", team_id)
    for uid in {int(u) for u in member_ids or []}:
        if users.get(uid):
            db.insert("team_members", {"team_id": team_id, "user_id": uid})


@bp.get("/api/teams")
@login_required
def list_teams():
    return ok({"items": users.teams_with_members()})


@bp.post("/api/teams")
@require("admin")
def create_team():
    data = body()
    values = _team_payload(data, partial=False)
    if db.one("SELECT id FROM teams WHERE name = ?", values["name"]):
        bad_request("A team with that name already exists", code="duplicate")
    with db.transaction():
        values.setdefault("color", pick_color(values["name"]))
        values["created_at"] = now_iso()
        tid = db.insert("teams", values)
        _set_members(tid, data.get("member_ids"))
        realtime.emit("settings.changed", {"what": "teams"})
    return ok({"team": next(t for t in users.teams_with_members() if t["id"] == tid)}, 201)


@bp.patch("/api/teams/<int:tid>")
@require("admin")
def update_team(tid: int):
    if not db.one("SELECT id FROM teams WHERE id = ?", tid):
        not_found("No such team")
    data = body()
    with db.transaction():
        db.update("teams", tid, _team_payload(data, partial=True))
        if "member_ids" in data:
            _set_members(tid, data["member_ids"])
        realtime.emit("settings.changed", {"what": "teams"})
    return ok({"team": next(t for t in users.teams_with_members() if t["id"] == tid)})


@bp.delete("/api/teams/<int:tid>")
@require("admin")
def delete_team(tid: int):
    with db.transaction():
        db.delete("teams", tid)
        realtime.emit("settings.changed", {"what": "teams"})
    return ok()


# -- organization settings ----------------------------------------------------------


@bp.get("/api/settings")
@login_required
def get_settings():
    return ok({"settings": settings.public()})


@bp.patch("/api/settings")
@require("admin")
def patch_settings():
    """Update known settings keys: {"org.name": "...", "inbox.undo_send_seconds": 10}."""
    data = body()
    unknown = [k for k in data if k not in settings.DEFAULTS]
    if unknown:
        bad_request(f"Unknown setting: {', '.join(unknown)}", code="unknown_setting")
    if "org.timezone" in data:
        from pps_tools.switchboard.util import get_zone, UTC

        if get_zone(data["org.timezone"]) is UTC and data["org.timezone"] not in ("UTC", "Etc/UTC"):
            bad_request("Unknown timezone")
    with db.transaction():
        for key, value in data.items():
            settings.set(key, value)
        audit("settings.update", data={k: ("***" if settings.is_private(k) else v) for k, v in data.items()})
        realtime.emit("settings.changed", {"what": "settings", "keys": list(data)})
    return ok({"settings": settings.public()})


# -- notifications ------------------------------------------------------------------


@bp.get("/api/notifications")
@login_required
def list_notifications():
    uid = current_user()["id"]
    limit = min(as_int(request.args.get("limit"), "limit") or 50, 200)
    where, params = ["user_id = ?"], [uid]
    if as_bool(request.args.get("unread")):
        where.append("read_at IS NULL")
    before = as_int(request.args.get("before"), "before")
    if before:
        where.append("id < ?")
        params.append(before)
    rows = db.query(
        f"SELECT * FROM notifications WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?", [*params, limit]
    )
    return ok({"items": rows, "unread_count": notify.unread_count(uid)})


@bp.post("/api/notifications/read")
@login_required
def read_notifications():
    ids = body().get("ids")
    if ids is not None and not isinstance(ids, list):
        bad_request("ids must be a list")
    with db.transaction():
        notify.mark_read(current_user()["id"], [int(i) for i in ids] if ids is not None else None)
    return ok({"unread_count": notify.unread_count(current_user()["id"])})


# -- presence & live events ---------------------------------------------------------

_last_seen_write: dict[int, float] = {}


@bp.post("/api/presence")
@login_required
def post_presence():
    data = body()
    target = data.get("target")
    if target is not None and (not isinstance(target, str) or len(target) > 80):
        bad_request("Bad presence target")
    state = data.get("state") or "viewing"
    if state not in ("viewing", "composing", "typing"):
        bad_request("Bad presence state")
    uid = current_user()["id"]
    realtime.presence.update(uid, target, state, as_int(data.get("draft_id"), "draft_id"))
    # last_seen_at at most once a minute per user
    if time.time() - _last_seen_write.get(uid, 0) > 60:
        _last_seen_write[uid] = time.time()
        db.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", now_iso(), uid)
    return ok()


@bp.get("/api/events")
@login_required
def events():
    uid = current_user()["id"]
    db.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", now_iso(), uid)
    db.close()  # long-lived response: don't hold a connection
    return Response(
        realtime.stream(uid),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# -- files --------------------------------------------------------------------------

# Served inline; everything else downloads. All file responses also get a sandbox CSP so
# an uploaded HTML/SVG file can never run script on our origin.
_INLINE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "application/pdf",
                 "text/plain", "audio/", "video/")


def _send_attachment(att: dict, force_download: bool = False):
    inline = not force_download and att["content_type"].startswith(_INLINE_TYPES)
    path = files.path_for(att)
    if not path.is_file():
        not_found("File is missing from storage")
    response = send_file(
        path,
        mimetype=att["content_type"] if inline else "application/octet-stream",
        as_attachment=not inline,
        download_name=att["filename"],
        max_age=3600,
        conditional=True,
    )
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@bp.post("/api/files")
@login_required
def upload_files():
    uploads = request.files.getlist("files") or request.files.getlist("file")
    if not uploads:
        bad_request("No file uploaded")
    inline = as_bool(request.form.get("inline"))
    saved = []
    with db.transaction():
        for f in uploads:
            att = files.save_upload(f, current_user()["id"], is_inline=inline,
                                    content_id=token(8) + "@switchboard" if inline else None)
            saved.append(files.serialize(att))
    return ok({"items": saved}, 201)


@bp.get("/api/files/<int:att_id>/<path:filename>")
@login_required
def download_file(att_id: int, filename: str):
    att = files.get(att_id)
    if not att or not files.can_read(current_user(), att):
        not_found("File not found")
    return _send_attachment(att, force_download=as_bool(request.args.get("download")))


@bp.get("/public/files/<tok>/<path:filename>")
def public_file(tok: str, filename: str):
    att = db.one("SELECT * FROM attachments WHERE token = ?", tok)
    if not att:
        not_found("File not found")
    return _send_attachment(att, force_download=as_bool(request.args.get("download")))


@bp.delete("/api/files/<int:att_id>")
@login_required
def delete_file(att_id: int):
    att = files.get(att_id)
    if not att:
        not_found("File not found")
    mine = att["uploaded_by"] == current_user()["id"]
    if (att["owner_type"] in (None, "draft") and mine) or can(current_user(), "admin"):
        with db.transaction():
            files.delete(att)
        return ok()
    forbidden("You can only remove your own uploads")


# -- reactions ----------------------------------------------------------------------


@bp.post("/api/reactions")
@login_required
def toggle_reaction():
    data = body()
    require_fields(data, "target_type", "target_id", "emoji")
    if data["target_type"] not in reactions.TARGET_TYPES:
        bad_request("Can't react to that")
    emoji = str(data["emoji"])[:16]
    with db.transaction():
        added = reactions.toggle(data["target_type"], int(data["target_id"]), current_user()["id"], emoji)
    return ok({"added": added, "reactions": reactions.for_target(data["target_type"], int(data["target_id"]))})


# -- background ---------------------------------------------------------------------


def _prune_presence():
    realtime.presence.prune()


def _cleanup_files():
    with db.transaction():
        files.cleanup_orphans()


def worker_tasks():
    return [
        Task("presence.prune", 15, _prune_presence),
        Task("files.cleanup", 3600, _cleanup_files),
    ]
