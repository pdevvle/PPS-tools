"""Connected accounts ("channels"): add/edit/remove, test the connection, sync mail
now, and inject messages into API channels.

Secrets in a channel's config are never sent back to the browser: they come back as
MASK, and saving MASK (or leaving the field empty) keeps the stored value.
"""

from __future__ import annotations

import html as htmllib
import logging
import threading
import time

from flask import Blueprint

from pps_tools.switchboard import config as config_mod
from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.channels import ADAPTERS, api_channel, chat as chat_channel, twilio  # noqa: F401  (registers adapters)
from pps_tools.switchboard.channels import email as email_channel
from pps_tools.switchboard.services.inbox import Inbound, deliver_inbound
from pps_tools.switchboard.util import norm_email, norm_phone, now_iso, token
from pps_tools.switchboard.web import (
    as_bool, as_int, audit, bad_request, body, current_user, not_found, ok, require,
)
from pps_tools.switchboard.worker import Task

logger = logging.getLogger(__name__)

bp = Blueprint("channels", __name__)

TYPES = ("email", "sms", "whatsapp", "chat", "api")
MASK = "••••••"
SECRET_KEYS = {"imap_password", "smtp_password", "auth_token", "secret", "inbound_secret"}
_TWILIO_KEYS = {"account_sid", "auth_token", "from_number", "messaging_service_sid", "validate_signature", "demo"}
CONFIG_KEYS = {
    "email": {"preset", "imap_host", "imap_port", "imap_ssl", "imap_user", "imap_password", "imap_folder", "smtp_host",
              "smtp_port", "smtp_security", "smtp_user", "smtp_password", "from_name_mode", "initial_days", "poll_seconds",
              "track_opens", "append_sent", "sent_folder", "inbound_secret", "demo"},
    "sms": _TWILIO_KEYS,
    "whatsapp": _TWILIO_KEYS,
    "chat": {"greeting", "color", "require_email", "offline_message", "email_fallback", "demo"},
    "api": {"outbound_url", "secret", "demo"},
}
DEFAULT_CONFIG = {
    "email": {"imap_port": 993, "imap_ssl": True, "imap_folder": "INBOX", "smtp_port": 587, "smtp_security": "starttls",
              "from_name_mode": "user", "initial_days": 7, "poll_seconds": 60, "track_opens": False, "append_sent": False},
    "sms": {"validate_signature": True},
    "whatsapp": {"validate_signature": True},
    "chat": dict(chat_channel.DEFAULTS),
    "api": {},
}
TYPE_NAMES = {"email": "Email", "sms": "Text messages", "whatsapp": "WhatsApp", "chat": "Website chat", "api": "API & forms"}
INT_KEYS = {"imap_port", "smtp_port", "initial_days", "poll_seconds"}
BOOL_KEYS = {"imap_ssl", "track_opens", "append_sent", "validate_signature", "require_email", "email_fallback", "demo"}


def _cfg(ch: dict) -> dict:
    return db.jload(ch.get("config_json"), {}) or {}


def base_url() -> str:
    return config_mod.current().base_url


def connect_info(ch: dict) -> dict:
    """URLs and snippets an admin pastes into Twilio, a website, a form..."""
    cfg = _cfg(ch)
    base, key = base_url(), ch["public_key"]
    info: dict = {"base_url": base, "base_is_public": email_channel.is_public_base(base)}
    if ch["type"] == "email":
        info["inbound_hook"] = f"{base}/hooks/email/{key}?secret={cfg.get('inbound_secret') or ''}"
    elif ch["type"] in ("sms", "whatsapp"):
        info["twilio_inbound"] = f"{base}/hooks/twilio/{key}"
        info["twilio_status"] = f"{base}/hooks/twilio/{key}/status"
    elif ch["type"] == "chat":
        info["widget_url"] = f"{base}/widget/{key}.js"
        info["snippet"] = f'<script src="{base}/widget/{key}.js" async></script>'
    elif ch["type"] == "api":
        form = f"{base}/hooks/form/{key}"
        info["form_endpoint"] = form
        info["api_endpoint"] = f"{base}/api/channels/{ch['id']}/messages"
        info["secret"] = cfg.get("secret")
        info["form_snippet"] = (
            f'<form action="{htmllib.escape(form)}" method="post">\n'
            '  <input name="name" placeholder="Your name" required>\n'
            '  <input name="email" type="email" placeholder="Email" required>\n'
            '  <input name="phone" placeholder="Phone">\n'
            '  <textarea name="message" placeholder="What can we print for you?" required></textarea>\n'
            '  <input name="_gotcha" style="display:none" tabindex="-1" autocomplete="off">\n'
            '  <input type="hidden" name="_redirect" value="https://your-site.example/thanks">\n'
            '  <button>Send</button>\n'
            "</form>"
        )
        info["curl"] = (
            f"curl -X POST {base}/api/channels/{ch['id']}/messages \\\n"
            "  -H 'Authorization: Bearer <API token>' -H 'Content-Type: application/json' \\\n"
            "  -d '{\"from\": {\"name\": \"Ann Lee\", \"handle\": \"ann@example.com\"}, "
            "\"subject\": \"Quote request\", \"body_text\": \"500 flyers please\"}'"
        )
    return info


def serialize(ch: dict) -> dict:
    cfg = _cfg(ch)
    allowed = CONFIG_KEYS.get(ch["type"], set())
    public_cfg = {k: (MASK if k in SECRET_KEYS and v else v) for k, v in cfg.items() if k in allowed and k != "inbound_secret"}
    adapter = ADAPTERS.get(ch["type"])
    stats = db.one(
        "SELECT COUNT(*) AS conversations, SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open "
        "FROM conversations WHERE channel_id = ? AND deleted_at IS NULL", ch["id"],
    )
    return {
        "id": ch["id"],
        "type": ch["type"],
        "type_name": TYPE_NAMES.get(ch["type"], ch["type"]),
        "name": ch["name"],
        "address": ch["address"],
        "is_active": bool(ch["is_active"]),
        "visibility": ch["visibility"],
        "owner_user_id": ch["owner_user_id"],
        "team_id": ch["team_id"],
        "signature_html": ch["signature_html"],
        "public_key": ch["public_key"],
        "last_sync_at": ch["last_sync_at"],
        "sync_error": ch["sync_error"],
        "created_at": ch["created_at"],
        "updated_at": ch["updated_at"],
        "demo": bool(cfg.get("demo")),
        "config": public_cfg,
        "capabilities": adapter.public_config(ch) if adapter else {},
        "connect": connect_info(ch),
        "stats": {"conversations": stats["conversations"] or 0, "open": stats["open"] or 0},
    }


def _get(cid: int) -> dict:
    ch = db.one("SELECT * FROM channels WHERE id = ?", cid)
    if not ch:
        not_found("Channel not found")
    return ch


def _clean_config(type_: str, incoming: dict, stored: dict | None = None) -> dict:
    """Merge submitted config onto the stored one, keeping secrets sent back masked."""
    if incoming is None:
        incoming = {}
    if not isinstance(incoming, dict):
        bad_request("config must be an object")
    allowed = CONFIG_KEYS[type_]
    merged = dict(DEFAULT_CONFIG.get(type_, {}))
    merged.update(stored or {})
    for key, value in incoming.items():
        if key not in allowed:
            continue
        if key in SECRET_KEYS and (value in (None, "", MASK)):
            continue
        if key in INT_KEYS:
            if value in (None, ""):
                merged.pop(key, None)
                continue
            try:
                value = int(value)
            except (TypeError, ValueError):
                bad_request(f"'{key}' must be a number", code="validation")
        elif key in BOOL_KEYS:
            value = as_bool(value)
        elif isinstance(value, str):
            value = value.strip()
        merged[key] = value
    if type_ == "email":
        merged.setdefault("inbound_secret", token(16))
        if merged.get("smtp_security") not in ("starttls", "ssl", "none"):
            merged["smtp_security"] = "starttls"
        if merged.get("from_name_mode") not in ("user", "channel", "user_at_org"):
            merged["from_name_mode"] = "user"
        merged["poll_seconds"] = max(30, int(merged.get("poll_seconds") or 60))
    if type_ == "api":
        merged.setdefault("secret", token(24))
        url = merged.get("outbound_url")
        if url and not url.startswith(("http://", "https://")):
            bad_request("The reply URL must start with http:// or https://", code="validation")
    if type_ == "chat":
        color = merged.get("color") or "#3b5bdb"
        if not (isinstance(color, str) and color.startswith("#") and len(color) in (4, 7)):
            bad_request("Color must look like #3b5bdb", code="validation")
    return merged


def _clean_address(type_: str, address) -> str | None:
    address = (address or "").strip()
    if type_ == "email":
        clean = norm_email(address)
        if not clean:
            bad_request("Enter the email address of this account", code="validation")
        return clean
    if type_ in ("sms", "whatsapp"):
        clean = norm_phone(address)
        if not clean or len(clean) < 8:
            bad_request("Enter the phone number in international format, e.g. +16025550142", code="validation")
        return clean
    return address or None


def _ownership(data: dict, current: dict | None = None) -> dict:
    out = {}
    visibility = data.get("visibility", (current or {}).get("visibility") or "shared")
    if visibility not in ("shared", "personal"):
        bad_request("visibility must be shared or personal", code="validation")
    out["visibility"] = visibility
    if visibility == "personal":
        owner = as_int(data.get("owner_user_id"), "owner_user_id") or (current or {}).get("owner_user_id") or current_user()["id"]
        if not db.one("SELECT id FROM users WHERE id = ? AND is_active = 1", owner):
            bad_request("Unknown owner", code="validation")
        out["owner_user_id"] = owner
        out["team_id"] = None
    else:
        out["owner_user_id"] = None
        if "team_id" in data or current is None:
            team_id = as_int(data.get("team_id"), "team_id")
            if team_id and not db.one("SELECT id FROM teams WHERE id = ?", team_id):
                bad_request("Unknown team", code="validation")
            out["team_id"] = team_id
    return out


def _changed():
    realtime.emit("settings.changed", {"what": "channels"})


@bp.get("/api/channels")
@require("admin")
def list_channels():
    rows = db.query("SELECT * FROM channels ORDER BY type, name COLLATE NOCASE")
    return ok({"items": [serialize(c) for c in rows]})


@bp.get("/api/channels/presets")
@require("admin")
def presets():
    return ok({"email": email_channel.PRESETS, "chat_defaults": chat_channel.DEFAULTS})


@bp.get("/api/channels/<int:cid>")
@require("admin")
def get_channel(cid: int):
    return ok({"channel": serialize(_get(cid))})


@bp.post("/api/channels")
@require("admin")
def create_channel():
    data = body()
    type_ = data.get("type")
    if type_ not in TYPES:
        bad_request("Choose a channel type", code="validation")
    address = _clean_address(type_, data.get("address"))
    name = (data.get("name") or "").strip() or address or TYPE_NAMES[type_]
    cfg = _clean_config(type_, data.get("config") or {})
    if type_ in ("sms", "whatsapp") and not cfg.get("demo") and not (cfg.get("account_sid") and cfg.get("auth_token")):
        bad_request("Enter your Twilio Account SID and Auth Token", code="validation")
    values = {
        "type": type_, "name": name[:120], "address": address, "is_active": 0 if data.get("is_active") is False else 1,
        "config_json": db.jdump(cfg), "signature_html": _signature(data.get("signature_html")),
        "public_key": token(16), "created_at": now_iso(), "updated_at": now_iso(),
        **_ownership(data),
    }
    with db.transaction():
        cid = db.insert("channels", values)
        audit("channel.create", "channel", cid, {"type": type_, "name": name})
        _changed()
    return ok({"channel": serialize(_get(cid))}, 201)


def _signature(value) -> str | None:
    from pps_tools.switchboard.services.sanitize import is_blank, sanitize

    if value is None:
        return None
    clean = sanitize(value, "basic")
    return None if is_blank(clean) else clean


@bp.patch("/api/channels/<int:cid>")
@require("admin")
def update_channel(cid: int):
    ch = _get(cid)
    data = body()
    changes: dict = {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            bad_request("Name can't be empty", code="validation")
        changes["name"] = name[:120]
    if "address" in data:
        changes["address"] = _clean_address(ch["type"], data.get("address"))
    if "config" in data:
        changes["config_json"] = db.jdump(_clean_config(ch["type"], data["config"], _cfg(ch)))
    if "signature_html" in data:
        changes["signature_html"] = _signature(data.get("signature_html"))
    if "is_active" in data:
        changes["is_active"] = 1 if as_bool(data["is_active"]) else 0
    if any(k in data for k in ("visibility", "team_id", "owner_user_id")):
        changes.update(_ownership(data, ch))
    if not changes:
        return ok({"channel": serialize(ch)})
    changes["updated_at"] = now_iso()
    with db.transaction():
        db.update("channels", cid, changes)
        audit("channel.update", "channel", cid, {k: v for k, v in changes.items() if k != "config_json"})
        _changed()
    return ok({"channel": serialize(_get(cid))})


@bp.delete("/api/channels/<int:cid>")
@require("admin")
def delete_channel(cid: int):
    ch = _get(cid)
    with db.transaction():
        db.delete("channels", cid)
        audit("channel.delete", "channel", cid, {"name": ch["name"], "type": ch["type"]})
        _changed()
    return ok()


@bp.post("/api/channels/<int:cid>/rotate-key")
@require("admin")
def rotate_key(cid: int):
    """New public key: old webhook / widget / form URLs stop working."""
    _get(cid)
    with db.transaction():
        db.update("channels", cid, {"public_key": token(16), "updated_at": now_iso()})
        audit("channel.rotate_key", "channel", cid)
        _changed()
    return ok({"channel": serialize(_get(cid))})


def _test_config(type_: str, cfg: dict) -> tuple[bool, str]:
    if cfg.get("demo"):
        return True, "Demo channel — nothing to connect to"
    adapter = ADAPTERS.get(type_)
    if not adapter:
        return True, "Nothing to test for this channel type"
    try:
        return adapter.test(cfg)
    except Exception as exc:  # a test must always answer
        logger.warning("Channel test failed: %s", exc)
        return False, str(exc) or exc.__class__.__name__


@bp.post("/api/channels/test")
@require("admin")
def test_new():
    data = body()
    type_ = data.get("type")
    if type_ not in TYPES:
        bad_request("Choose a channel type", code="validation")
    good, message = _test_config(type_, _clean_config(type_, data.get("config") or {}))
    return ok({"ok": good, "message": message})


@bp.post("/api/channels/<int:cid>/test")
@require("admin")
def test_existing(cid: int):
    ch = _get(cid)
    cfg = _clean_config(ch["type"], body().get("config") or {}, _cfg(ch))
    good, message = _test_config(ch["type"], cfg)
    return ok({"ok": good, "message": message})


@bp.post("/api/channels/<int:cid>/sync")
@require("admin")
def sync_now(cid: int):
    ch = _get(cid)
    cfg = _cfg(ch)
    if ch["type"] != "email":
        bad_request("Only email accounts are synced")
    if cfg.get("demo"):
        return ok({"fetched": 0, "error": None, "message": "Demo channel — nothing to fetch"})
    if not cfg.get("imap_host"):
        bad_request("Add an incoming (IMAP) server first")
    fetched, error = email_channel.sync_and_record(cid)
    realtime.emit("settings.changed", {"what": "channels"}, users=[current_user()["id"]])
    return ok({"fetched": fetched, "error": error,
               "message": error or (f"Fetched {fetched} new message{'s' if fetched != 1 else ''}" if fetched else "No new mail")})


@bp.post("/api/channels/<int:cid>/messages")
@require("inbox")
def inject_message(cid: int):
    """Post an inbound message into an API channel (website, Zapier, POS...)."""
    ch = _get(cid)
    if ch["type"] != "api":
        bad_request("Messages can only be posted to API channels", code="wrong_channel")
    if not ch["is_active"]:
        bad_request("This channel is paused", code="inactive")
    data = body()
    sender = data.get("from") if isinstance(data.get("from"), dict) else {}
    handle = (sender.get("handle") or sender.get("email") or sender.get("phone") or data.get("from_email")
              or data.get("from_phone") or "").strip() or None
    name = (sender.get("name") or data.get("from_name") or "").strip() or None
    text = data.get("body_text")
    html = data.get("body_html")
    if not (text or html):
        bad_request("Send body_text or body_html", code="validation")
    if handle and "@" in handle and not norm_email(handle):
        bad_request("from.handle isn't a valid email address", code="validation")
    msg = deliver_inbound(Inbound(
        channel=ch, kind="api", from_handle=(norm_email(handle) if handle and "@" in handle else norm_phone(handle) or handle),
        from_name=name, subject=(data.get("subject") or "").strip() or None, body_text=text, body_html=html,
        thread_key=(str(data["thread_key"]) if data.get("thread_key") else None),
        external_id=(str(data["external_id"]) if data.get("external_id") else f"api-{token(10)}"),
    ))
    if msg is None:
        return ok({"duplicate": True})
    return ok({"message_id": msg["id"], "conversation_id": msg["conversation_id"]}, 201)


# -- background ---------------------------------------------------------------------

_last_kick: dict[int, float] = {}


def _sync_in_thread(channel_id: int) -> None:
    try:
        email_channel.sync_and_record(channel_id)
    finally:
        db.close()


def kick_mail_sync() -> int:
    """Start a background sync for every IMAP account that's due (one at a time per account)."""
    started = 0
    for ch in db.query("SELECT * FROM channels WHERE type = 'email' AND is_active = 1"):
        cfg = _cfg(ch)
        if cfg.get("demo") or not cfg.get("imap_host"):
            continue
        interval = max(30, int(cfg.get("poll_seconds") or 60))
        if time.monotonic() - _last_kick.get(ch["id"], -1e9) < interval:
            continue
        if email_channel.sync_lock(ch["id"]).locked():
            continue
        _last_kick[ch["id"]] = time.monotonic()
        threading.Thread(target=_sync_in_thread, args=(ch["id"],), name=f"imap-{ch['id']}", daemon=True).start()
        started += 1
    return started


def worker_tasks():
    return [
        Task("channels.mail_sync", 15, kick_mail_sync),
        Task("channels.chat_fallback", 60, chat_channel.email_missed_replies),
    ]


def seed(ctx) -> None:
    """Give the demo channels realistic settings (they stay offline: demo=true)."""
    channels = ctx.data.get("channels") or {}
    for key, extra in (
        ("orders", {"preset": "gmail", "imap_host": "imap.gmail.com", "imap_user": "orders@pps.demo",
                    "smtp_host": "smtp.gmail.com", "smtp_user": "orders@pps.demo", "from_name_mode": "user",
                    "track_opens": True}),
        ("personal", {"preset": "outlook", "imap_host": "outlook.office365.com", "smtp_host": "smtp.office365.com",
                      "imap_user": "morgan@pps.demo"}),
        ("sms", {"account_sid": "ACdemo0000000000000000000000000000", "from_number": "+16025550142"}),
        ("chat", {"greeting": "Hi! 👋 Need a quote or checking on an order? Ask away — we're in the shop 8–5.",
                  "color": "#3b5bdb", "require_email": False}),
    ):
        cid = channels.get(key)
        if not cid:
            continue
        row = db.one("SELECT * FROM channels WHERE id = ?", cid)
        cfg = _clean_config(row["type"], extra, _cfg(row))
        cfg["demo"] = True
        db.update("channels", cid, {"config_json": db.jdump(cfg)})
    wa = db.one("SELECT * FROM channels WHERE type = 'whatsapp' ORDER BY id LIMIT 1")
    if wa:
        cfg = _clean_config("whatsapp", {"account_sid": "ACdemo0000000000000000000000000000"}, _cfg(wa))
        cfg["demo"] = True
        db.update("channels", wa["id"], {"config_json": db.jdump(cfg)})
    stamp = now_iso()
    team = ctx.teams.get("office")
    api_id = db.insert("channels", {
        "type": "api", "name": "Website quote form", "address": "priorityprint.example/quote", "visibility": "shared",
        "team_id": team, "config_json": db.jdump({"demo": True, "secret": token(24)}), "public_key": token(16),
        "created_at": stamp, "updated_at": stamp,
    })
    channels["form"] = api_id
    ctx.data["channels"] = channels
    from pps_tools.switchboard.services import inbox

    msg = inbox.deliver_inbound(Inbound(
        channel=db.one("SELECT * FROM channels WHERE id = ?", api_id), kind="api",
        from_handle="ops@sunvalleydental.example", from_name="Renee Alvarez", subject="Quote request: appointment cards",
        body_html=(
            "<p>We need 2,500 appointment reminder cards for our three offices. Same design as last year if you still have it.</p>"
            "<table><tr><th align=\"left\">Product</th><td>Appointment cards</td></tr>"
            "<tr><th align=\"left\">Quantity</th><td>2,500</td></tr>"
            "<tr><th align=\"left\">Needed by</th><td>End of the month</td></tr>"
            "<tr><th align=\"left\">Phone</th><td>(602) 555-0177</td></tr></table>"
        ),
        external_id=f"form-{token(8)}",
    ))
    if msg:
        at = ctx.ago(hours=5, minutes=12)
        db.execute("UPDATE messages SET date = ?, created_at = ? WHERE id = ?", at, at, msg["id"])
        db.execute("UPDATE conversations SET created_at = ? WHERE id = ?", at, msg["conversation_id"])
        db.execute("UPDATE notifications SET created_at = ? WHERE entity_type = 'conversation' AND entity_id = ?",
                   at, msg["conversation_id"])
        inbox.recompute(msg["conversation_id"])
