"""Endpoints the outside world calls, without a Switchboard login:

* /hooks/twilio/<key>           inbound SMS / WhatsApp (Twilio-signed)
* /hooks/twilio/<key>/status    delivery receipts
* /hooks/email/<key>?secret=    raw MIME from a forwarding service (Mailgun, SendGrid, ...)
* /hooks/form/<key>             website contact & quote forms (CORS)
* /widget/<key>.js + /public/chat/<key>/...   the website chat widget (CORS, visitor token)
* /t/o/<token>.gif              email open tracking pixel

Each URL carries the channel's unguessable public key; rotate it in Settings to
invalidate old URLs.
"""

from __future__ import annotations

import base64
import hmac
import html as htmllib
import json
import mimetypes
import threading
import time
from collections import deque
from pathlib import Path

from flask import Blueprint, Response, redirect, request

from pps_tools.switchboard import config as config_mod
from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.channels import chat as chat_channel
from pps_tools.switchboard.channels import mime, twilio
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import files, inbox, notify, settings
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.services.inbox import Inbound, deliver_inbound
from pps_tools.switchboard.services.rules import in_business_hours
from pps_tools.switchboard.util import html_to_text, initials, norm_email, norm_phone, now_iso, text_to_html, token
from pps_tools.switchboard.web import ApiError, bad_request, not_found, ok

bp = Blueprint("public", __name__)

WIDGET_JS = Path(__file__).resolve().parent.parent / "static" / "widget" / "chat-widget.js"
GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
TWIML_EMPTY = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
MAX_FORM_FILES = 5
MAX_FORM_FILE_BYTES = 10 * 1024 * 1024
CHAT_MAX_CHARS = 4000


# -- helpers --------------------------------------------------------------------------


class RateLimiter:
    """At most ``limit`` hits per ``window`` seconds per key (in memory, per process)."""

    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque] = {}
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        cutoff = time.monotonic() - self.window
        with self.lock:
            q = self.hits.setdefault(key, deque())
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(time.monotonic())
            return True

    def reset(self) -> None:
        with self.lock:
            self.hits.clear()


session_limiter = RateLimiter(10, 60)
chat_limiter = RateLimiter(30, 60)
form_limiter = RateLimiter(10, 60)


def client_ip() -> str:
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()


def _limit(limiter: RateLimiter, scope: str) -> None:
    if not limiter.allow(f"{scope}:{client_ip()}"):
        raise ApiError(429, "rate_limited", "Too many requests — please slow down")


def _channel(key: str, types: tuple[str, ...], active: bool = True) -> dict:
    ch = db.one(f"SELECT * FROM channels WHERE public_key = ? AND type IN ({db.placeholders(types)})", [key, *types])
    if not ch or (active and not ch["is_active"]):
        not_found("Unknown channel")
    return ch


def _cfg(ch: dict) -> dict:
    return db.jload(ch.get("config_json"), {}) or {}


@bp.after_request
def _cors(response):
    if request.path.startswith(("/public/chat/", "/hooks/form/", "/widget/")):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Max-Age"] = "600"
    return response


# -- Twilio ---------------------------------------------------------------------------


def _twilio_verified(ch: dict) -> bool:
    cfg = _cfg(ch)
    if cfg.get("demo") or cfg.get("validate_signature") is False:
        return True
    url = config_mod.current().base_url + request.full_path
    if url.endswith("?"):
        url = url[:-1]
    params = list(request.form.items(multi=True))
    return twilio.valid_signature(url, params, cfg.get("auth_token") or "", request.headers.get("X-Twilio-Signature"))


@bp.post("/hooks/twilio/<key>")
def twilio_inbound(key: str):
    ch = _channel(key, ("sms", "whatsapp"), active=False)
    if not _twilio_verified(ch):
        raise ApiError(403, "bad_signature", "Twilio signature didn't match")
    if not ch["is_active"]:
        return Response(TWIML_EMPTY, mimetype="text/xml")
    form = request.form
    sender = norm_phone(form.get("From"))
    if not sender:
        bad_request("Missing From")
    cfg = _cfg(ch)
    attachments = []
    for i in range(min(int(form.get("NumMedia") or 0), 10)):
        url = form.get(f"MediaUrl{i}")
        ctype = form.get(f"MediaContentType{i}") or "application/octet-stream"
        if not url or cfg.get("demo"):
            continue
        data = twilio.download_media(cfg, url)
        if data is not None:
            ext = mimetypes.guess_extension(ctype) or ""
            attachments.append({"filename": f"media-{i + 1}{ext}", "content_type": ctype, "data": data})
    deliver_inbound(Inbound(
        channel=ch, kind=ch["type"], from_handle=sender, from_name=(form.get("ProfileName") or "").strip() or None,
        to=[{"name": None, "handle": norm_phone(form.get("To")) or ch["address"]}],
        body_text=form.get("Body") or ("(media)" if attachments else ""), external_id=form.get("MessageSid"),
        thread_key=sender, attachments=attachments,
    ))
    return Response(TWIML_EMPTY, mimetype="text/xml")


STATUS_RANK = {"received": 0, "scheduled": 0, "sending": 0, "sent": 1, "delivered": 2, "read": 3, "failed": 4}


@bp.post("/hooks/twilio/<key>/status")
def twilio_status(key: str):
    ch = _channel(key, ("sms", "whatsapp"), active=False)
    if not _twilio_verified(ch):
        raise ApiError(403, "bad_signature", "Twilio signature didn't match")
    sid = request.form.get("MessageSid")
    new = twilio.STATUS_MAP.get((request.form.get("MessageStatus") or "").lower())
    msg = db.one("SELECT * FROM messages WHERE external_id = ? AND channel_id = ?", sid, ch["id"]) if sid else None
    if not msg or not new or STATUS_RANK.get(new, 0) <= STATUS_RANK.get(msg["status"], 0):
        return Response(status=204)
    changes = {"status": new}
    if new == "failed":
        code = request.form.get("ErrorCode")
        changes["error"] = f"Not delivered (Twilio error {code})" if code else "Not delivered"
    with db.transaction():
        db.update("messages", msg["id"], changes)
        if new == "failed" and msg["author_id"]:
            conv = inbox.get(msg["conversation_id"])
            notify.notify([msg["author_id"]], "system", f"Text not delivered: {inbox.title_of(conv)}",
                          body=changes["error"], link=inbox.link(conv["id"]), entity_type="conversation",
                          entity_id=conv["id"], include_actor=True)
        inbox.touch(msg["conversation_id"], "status")
    return Response(status=204)


# -- raw email ------------------------------------------------------------------------


@bp.post("/hooks/email/<key>")
def email_hook(key: str):
    ch = _channel(key, ("email",))
    secret = request.args.get("secret") or request.headers.get("X-Switchboard-Secret") or ""
    expected = _cfg(ch).get("inbound_secret") or ""
    if not expected or not hmac.compare_digest(secret, expected):
        raise ApiError(403, "bad_secret", "Wrong or missing secret")
    raw = None
    if request.mimetype in ("message/rfc822", "text/plain", "application/octet-stream"):
        raw = request.get_data()
    else:
        upload = request.files.get("email") or request.files.get("body-mime")
        if upload:
            raw = upload.read()
        else:
            text = request.form.get("email") or request.form.get("body-mime")
            raw = text.encode("utf-8") if text else None
    if not raw:
        bad_request("Send the raw message (message/rfc822) or a form field named 'email'")
    msg = deliver_inbound(mime.to_inbound(ch, raw, fallback_id=f"<hook-{token(10)}@switchboard>"))
    if msg is None:
        return ok({"ok": True, "duplicate": True})
    return ok({"ok": True, "conversation_id": msg["conversation_id"]})


# -- website forms --------------------------------------------------------------------

FORM_ALIASES = {
    "name": ("name", "your-name", "full_name", "fullname", "your_name", "contact_name"),
    "email": ("email", "your-email", "e-mail", "mail", "your_email", "email_address"),
    "phone": ("phone", "tel", "your-phone", "telephone", "mobile", "phone_number"),
    "subject": ("subject", "your-subject", "topic"),
    "message": ("message", "your-message", "comments", "comment", "body", "msg", "details", "description"),
}


def _pick(data: dict, field: str) -> tuple[str | None, str | None]:
    for key in FORM_ALIASES[field]:
        for k, v in data.items():
            if k.lower() == key and str(v).strip():
                return str(v).strip(), k
    return None, None


def _escape(value) -> str:
    return htmllib.escape(str(value))


def _label(key: str) -> str:
    return key.replace("_", " ").replace("-", " ").strip().capitalize()


@bp.route("/hooks/form/<key>", methods=["POST", "OPTIONS"])
def form_hook(key: str):
    if request.method == "OPTIONS":
        return Response(status=204)
    ch = _channel(key, ("api",))
    _limit(form_limiter, f"form:{key}")
    data = {k: v for k, v in request.form.items()} or (request.get_json(silent=True) or {})
    if not isinstance(data, dict):
        bad_request("Send form fields")
    target = str(data.get("_redirect") or "")
    if str(data.get("_gotcha") or "").strip():
        return _form_done(target)  # a bot filled the hidden field: pretend it worked
    used = set()
    values = {}
    for field in FORM_ALIASES:
        values[field], k = _pick(data, field)
        if k:
            used.add(k)
    email = norm_email(values["email"]) if values["email"] else None
    if values["email"] and not email:
        bad_request("Please enter a valid email address", code="validation")
    phone = norm_phone(values["phone"]) if values["phone"] else None
    if not (email or phone or values["message"]):
        bad_request("Please include an email address, phone number or message", code="validation")
    rows = [("Name", values["name"]), ("Email", email), ("Phone", values["phone"])]
    rows += [(_label(k), str(v)) for k, v in data.items()
             if not k.startswith("_") and k not in used and str(v).strip()]
    table = "".join(
        f"<tr><th align=\"left\" style=\"padding:2px 12px 2px 0\">{_escape(k)}</th><td>{_escape(v)}</td></tr>"
        for k, v in rows if v
    )
    html = (text_to_html(values["message"]) if values["message"] else "") + (f"<table>{table}</table>" if table else "")
    attachments = []
    for upload in list(request.files.values())[:MAX_FORM_FILES]:
        content = upload.read(MAX_FORM_FILE_BYTES + 1)
        if upload.filename and len(content) <= MAX_FORM_FILE_BYTES:
            attachments.append({"filename": upload.filename, "content_type": upload.mimetype, "data": content})
    subject = values["subject"] or f"Website form: {values['name'] or email or phone or 'new submission'}"
    deliver_inbound(Inbound(
        channel=ch, kind="api", from_handle=email or phone, from_name=values["name"], subject=subject,
        body_html=html, body_text=html_to_text(html), external_id=f"form-{token(10)}", attachments=attachments,
        headers={"Origin": request.headers.get("Origin") or "", "Referer": request.headers.get("Referer") or ""},
    ))
    return _form_done(target)


def _form_done(target: str):
    if target.startswith(("http://", "https://")):
        return redirect(target, code=303)
    if "text/html" in (request.headers.get("Accept") or "") and not request.is_json:
        org = settings.get("org.name")
        return Response(
            f"<!doctype html><meta charset=utf-8><title>Thanks!</title><body style=\"font-family:system-ui;padding:48px;"
            f"text-align:center\"><h1>Thanks!</h1><p>{_escape(org)} got your message and will be in touch soon.</p></body>",
            mimetype="text/html",
        )
    return ok({"ok": True})


# -- website chat ---------------------------------------------------------------------


def _online_agents(ch: dict) -> list[dict]:
    online = set(realtime.broker.online_user_ids())
    pool = users_svc.team_member_ids(ch["team_id"]) if ch["team_id"] else users_svc.inbox_user_ids()
    people = [users_svc.get(u) for u in pool if u in online]
    return [{"name": p["name"].split(" ")[0], "initials": initials(p["name"]), "color": p["color"]} for p in people if p][:3]


def chat_public_config(ch: dict) -> dict:
    cfg = chat_channel.chat_config(ch)
    agents = _online_agents(ch)
    return {
        "key": ch["public_key"],
        "name": ch["name"],
        "org_name": settings.get("org.name"),
        "greeting": cfg["greeting"],
        "color": cfg["color"],
        "require_email": bool(cfg["require_email"]),
        "offline_message": cfg["offline_message"],
        "online": bool(agents) or in_business_hours(),
        "agents": agents,
    }


@bp.get("/widget/<key>.js")
def widget_js(key: str):
    ch = db.one("SELECT * FROM channels WHERE public_key = ? AND type = 'chat'", key)
    if not ch or not ch["is_active"]:
        return Response("/* Switchboard chat is turned off for this site. */", mimetype="application/javascript")
    source = WIDGET_JS.read_text(encoding="utf-8")
    payload = json.dumps(chat_public_config(ch)).replace("</", "<\\/")
    return Response(source.replace("__SB_CONFIG__", payload), mimetype="application/javascript",
                    headers={"Cache-Control": "public, max-age=300"})


@bp.route("/public/chat/<key>/config", methods=["GET", "OPTIONS"])
def chat_config(key: str):
    if request.method == "OPTIONS":
        return Response(status=204)
    return ok(chat_public_config(_channel(key, ("chat",))))


def _visitor(ch: dict, tok: str | None) -> dict:
    v = db.one("SELECT * FROM chat_visitors WHERE token = ? AND channel_id = ?", tok or "", ch["id"]) if tok else None
    if not v:
        raise ApiError(404, "unknown_visitor", "Chat session not found — start a new one")
    return v


@bp.route("/public/chat/<key>/session", methods=["POST", "OPTIONS"])
def chat_session(key: str):
    if request.method == "OPTIONS":
        return Response(status=204)
    ch = _channel(key, ("chat",))
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    name = (str(data.get("name") or "")).strip()[:80] or None
    raw_email = (str(data.get("email") or "")).strip()
    email = norm_email(raw_email) if raw_email else None
    if raw_email and not email:
        bad_request("That email address doesn't look right", code="validation")
    page = (str(data.get("page_url") or "")).strip()[:500] or None
    if data.get("token"):
        existing = db.one("SELECT * FROM chat_visitors WHERE token = ? AND channel_id = ?", str(data["token"]), ch["id"])
        if existing:
            changes = {"last_seen_at": now_iso()}
            if name and not existing["name"]:
                changes["name"] = name
            if email and not existing["email"]:
                changes["email"] = email
                contact = contacts_svc.resolve("email", email, name or existing["name"])
                if contact:
                    changes["contact_id"] = existing["contact_id"] or contact["id"]
            with db.transaction():
                db.update("chat_visitors", existing["id"], changes)
            return ok({"token": existing["token"], "name": changes.get("name", existing["name"]),
                       "email": changes.get("email", existing["email"])})
    _limit(session_limiter, f"chat-session:{key}")
    if chat_channel.chat_config(ch)["require_email"] and not email:
        bad_request("Please enter your email so we can reply", code="email_required")
    tok = token(24)
    with db.transaction():
        contact = contacts_svc.resolve("email", email, name) if email else contacts_svc.resolve("chat", tok, name or "Website visitor")
        db.insert("chat_visitors", {
            "channel_id": ch["id"], "token": tok, "name": name, "email": email, "contact_id": contact["id"] if contact else None,
            "page_url": page, "user_agent": (request.headers.get("User-Agent") or "")[:300], "ip": client_ip(),
            "created_at": now_iso(), "last_seen_at": now_iso(),
        })
    return ok({"token": tok, "name": name, "email": email}, 201)


def _visible_message(m: dict, ch: dict) -> dict:
    out = {"id": m["id"], "direction": m["direction"], "text": m["body_text"] or "", "at": m["date"], "author": None}
    if m["direction"] == "out":
        out["html"] = m["body_html"] or text_to_html(m["body_text"])
        author = users_svc.get(m["author_id"])
        out["author"] = {"name": (author["name"].split(" ")[0] if author else ch["name"]),
                         "initials": initials(author["name"] if author else ch["name"]),
                         "color": (author or {}).get("color") or "#3b5bdb"}
    out["attachments"] = [{"filename": a["filename"], "url": files.public_url(a, absolute=True), "is_image": files.is_image(a)}
                          for a in files.for_owner("message", m["id"]) if not a["is_inline"]]
    return out


_seen_writes: dict[int, float] = {}


@bp.route("/public/chat/<key>/messages", methods=["GET", "POST", "OPTIONS"])
def chat_messages(key: str):
    if request.method == "OPTIONS":
        return Response(status=204)
    ch = _channel(key, ("chat",))
    if request.method == "POST":
        return _chat_post(ch)
    v = _visitor(ch, request.args.get("token"))
    if time.monotonic() - _seen_writes.get(v["id"], 0) > 20:
        _seen_writes[v["id"]] = time.monotonic()
        db.update("chat_visitors", v["id"], {"last_seen_at": now_iso()})
    if not v["conversation_id"]:
        return ok({"messages": [], "agent_typing": False, "online": chat_public_config(ch)["online"]})
    try:
        after = int(request.args.get("after") or 0)
    except ValueError:
        after = 0
    rows = db.query(
        "SELECT * FROM messages WHERE conversation_id = ? AND channel_id = ? AND id > ? AND kind = 'chat' "
        "AND (direction = 'in' OR status IN ('sent', 'delivered', 'read')) ORDER BY id LIMIT 200",
        v["conversation_id"], ch["id"], after,
    )
    typing = any(x["state"] == "composing" for x in realtime.presence.viewers(f"conversation:{v['conversation_id']}"))
    return ok({"messages": [_visible_message(m, ch) for m in rows], "agent_typing": typing,
               "online": chat_public_config(ch)["online"]})


def _chat_post(ch: dict):
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    v = _visitor(ch, data.get("token"))
    _limit(chat_limiter, f"chat:{v['token']}")
    text = (str(data.get("body") or "")).strip()
    if not text:
        bad_request("Type a message first", code="validation")
    text = text[:CHAT_MAX_CHARS]
    page = (str(data.get("page_url") or "")).strip()[:500] or v["page_url"]
    msg = deliver_inbound(Inbound(
        channel=ch, kind="chat", from_handle=v["email"], from_name=v["name"] or "Website visitor", body_text=text,
        thread_key=v["token"], conversation_id=v["conversation_id"], contact_id=v["contact_id"],
        external_id=f"chat-{token(10)}", headers={"page_url": page or ""},
    ))
    if msg is None:
        bad_request("That message was already received", code="duplicate")
    with db.transaction():
        db.update("chat_visitors", v["id"], {"conversation_id": msg["conversation_id"], "last_seen_at": now_iso(),
                                             "page_url": page})
    return ok({"message": _visible_message(msg, ch)}, 201)


# -- open tracking --------------------------------------------------------------------


@bp.get("/t/o/<tok>.gif")
def open_pixel(tok: str):
    msg = db.one("SELECT id, conversation_id, opened_at, direction FROM messages WHERE track_token = ?", tok)
    if msg and msg["direction"] == "out" and not msg["opened_at"]:
        with db.transaction():
            db.update("messages", msg["id"], {"opened_at": now_iso()})
            inbox.touch(msg["conversation_id"], "opened")
    return Response(GIF, mimetype="image/gif",
                    headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"})
