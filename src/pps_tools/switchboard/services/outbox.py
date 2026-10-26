"""Composing and sending.

Drafts are shared by default: teammates see them in the conversation and can co-edit
(every save bumps ``version`` and is broadcast live). Sending turns the draft into a
``scheduled`` message: due after the undo window, or at the chosen send-later time.
The worker's ``process_outbox`` hands due messages to the channel adapter.
"""

from __future__ import annotations

import html as htmllib
from datetime import timedelta

from pps_tools.switchboard import channels as channel_registry
from pps_tools.switchboard import config, db, realtime
from pps_tools.switchboard.channels import SendError
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import files, hooks, inbox, notify, search, settings
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.services.sanitize import is_blank, sanitize
from pps_tools.switchboard.util import (
    html_to_text, iso, norm_email, norm_phone, normalize_subject, now, now_iso, parse_address_list,
    parse_iso, render_template, snippet, token,
)
from pps_tools.switchboard.web import bad_request, forbidden, not_found

RETRY_MINUTES = (1, 5, 15)


# -- channels -----------------------------------------------------------------------


def channel(cid: int | None) -> dict | None:
    return db.one("SELECT * FROM channels WHERE id = ?", cid) if cid else None


def can_send_from(user: dict, ch: dict | None) -> bool:
    if not ch or not ch["is_active"]:
        return False
    if ch["visibility"] == "personal":
        return ch["owner_user_id"] == user["id"]
    return ch["id"] in inbox.visible_channel_ids(user)


def sendable_channels(user: dict) -> list[dict]:
    return [c for c in db.query("SELECT * FROM channels WHERE is_active = 1 ORDER BY type, name") if can_send_from(user, c)]


def own_addresses() -> set[str]:
    return {(c["address"] or "").lower() for c in db.query("SELECT address FROM channels WHERE type = 'email'") if c["address"]}


# -- signatures ---------------------------------------------------------------------


def signature_for(user: dict, ch: dict | None) -> str:
    """The user's own signature, else the channel's (with {{user.*}} filled in)."""
    prefs = db.jload(user.get("prefs_json"), {}) or {}
    mine = prefs.get("signature_html")
    if mine:
        return sanitize(mine, "basic")
    if ch and ch.get("signature_html"):
        ctx = {
            "__html__": True,
            "user": {"name": user["name"], "first_name": user["name"].split(" ")[0], "title": user.get("title") or "",
                     "email": user["email"], "phone": user.get("phone") or ""},
            "org": {"name": settings.get("org.name")},
            "channel": {"name": ch["name"], "address": ch.get("address") or ""},
        }
        return sanitize(render_template(ch["signature_html"], ctx), "basic")
    return ""


# -- drafts -------------------------------------------------------------------------


def serialize_draft(d: dict) -> dict:
    return {
        "id": d["id"],
        "conversation_id": d["conversation_id"],
        "channel_id": d["channel_id"],
        "mode": d["mode"],
        "reply_to_message_id": d["reply_to_message_id"],
        "to": db.jload(d["to_json"], []),
        "cc": db.jload(d["cc_json"], []),
        "bcc": db.jload(d["bcc_json"], []),
        "subject": d["subject"],
        "body_html": d["body_html"],
        "include_signature": bool(d["include_signature"]),
        "is_shared": bool(d["is_shared"]),
        "version": d["version"],
        "created_by": d["created_by"],
        "updated_by": d["updated_by"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "attachments": [files.serialize(a) for a in files.for_owner("draft", d["id"])],
    }


def _recipients_for_reply(conv: dict, msg: dict | None, mode: str, ch: dict | None) -> tuple[list, list]:
    if ch and ch["type"] in ("sms", "whatsapp", "chat"):
        handle = conv.get("thread_key")
        if not handle and conv.get("contact_id"):
            c = contacts_svc.get(conv["contact_id"])
            handle = c and c.get("phone")
        return ([{"name": None, "handle": handle}] if handle else []), []
    if not msg:
        c = contacts_svc.get(conv.get("contact_id"))
        return ([{"name": c.get("name"), "handle": c["email"]}] if c and c.get("email") else []), []
    mine = own_addresses()
    if msg["direction"] == "in":
        primary = parse_address_list(msg["reply_to"]) or [{"name": msg["from_name"], "handle": msg["from_handle"]}]
    else:
        primary = db.jload(msg["to_json"], [])
    to = [p for p in primary if p.get("handle")]
    cc: list = []
    if mode == "reply_all":
        seen = {p["handle"].lower() for p in to} | mine
        for p in db.jload(msg["to_json"], []) + db.jload(msg["cc_json"], []):
            h = (p.get("handle") or "").lower()
            if h and h not in seen and (ch is None or h != (ch.get("address") or "").lower()):
                seen.add(h)
                cc.append(p)
        if msg["direction"] == "in":
            cc = [p for p in cc if p not in to]
    return to, cc


def _forward_body(msg: dict) -> str:
    header = (
        "<p>---------- Forwarded message ----------<br>"
        f"From: {htmllib.escape(msg['from_name'] or '')} &lt;{htmllib.escape(msg['from_handle'] or '')}&gt;<br>"
        f"Date: {htmllib.escape(msg['date'])}<br>"
        f"Subject: {htmllib.escape(msg['subject'] or '')}</p>"
    )
    return "<p></p>" + header + (msg["body_html"] or "")


def _can_edit_draft(user: dict, d: dict) -> bool:
    if d["created_by"] == user["id"]:
        return True
    if not d["is_shared"] or not d["conversation_id"]:
        return False
    return inbox.can_view(user, d["conversation_id"])


def get_draft_for(user: dict, draft_id: int) -> dict:
    d = db.one("SELECT * FROM drafts WHERE id = ?", draft_id)
    if not d or not _can_edit_draft(user, d):
        not_found("Draft not found")
    return d


def _broadcast_draft(d: dict, by: int) -> None:
    if not d["conversation_id"] or not d["is_shared"]:
        realtime.emit("draft.changed", {"id": d["id"], "conversation_id": d["conversation_id"], "by": by,
                                        "version": d["version"]}, users=[d["created_by"]])
        return
    payload = {"id": d["id"], "conversation_id": d["conversation_id"], "by": by, "version": d["version"],
               "draft": serialize_draft(d)}
    realtime.emit("draft.changed", payload, users=inbox.audience(d["conversation_id"]))


def create_draft(user: dict, data: dict) -> dict:
    mode = data.get("mode") or ("reply" if data.get("conversation_id") else "new")
    if mode not in ("new", "reply", "reply_all", "forward"):
        bad_request("Unknown draft mode")
    conv = None
    reply_msg = None
    if data.get("conversation_id"):
        conv = inbox.get_for(user, int(data["conversation_id"]))
        if data.get("reply_to_message_id"):
            reply_msg = db.one("SELECT * FROM messages WHERE id = ? AND conversation_id = ?",
                               int(data["reply_to_message_id"]), conv["id"])
        if not reply_msg:
            reply_msg = db.one(
                "SELECT * FROM messages WHERE conversation_id = ? AND status NOT IN ('scheduled', 'failed') "
                "ORDER BY date DESC, id DESC LIMIT 1", conv["id"],
            )
    ch = channel(data.get("channel_id")) if data.get("channel_id") else None
    if not ch and reply_msg:
        ch = channel(reply_msg["channel_id"])
    if not ch and conv:
        ch = channel(conv["channel_id"])
    if not ch and not conv:
        options = [c for c in sendable_channels(user) if c["type"] == "email"] or sendable_channels(user)
        ch = options[0] if options else None
    if ch and not can_send_from(user, ch):
        forbidden("You can't send from that account")
    to = parse_address_list(data["to"]) if "to" in data else None
    cc = parse_address_list(data["cc"]) if "cc" in data else None
    subject = data.get("subject")
    body = sanitize(data.get("body_html") or "", "basic")
    if conv and mode != "forward" and (to is None or cc is None):
        auto_to, auto_cc = _recipients_for_reply(conv, reply_msg, mode, ch)
        to = auto_to if to is None else to
        cc = auto_cc if cc is None else cc
    if conv and subject is None:
        base = normalize_subject((reply_msg or {}).get("subject") or conv["subject"])
        subject = (("Fwd: " if mode == "forward" else "Re: ") + base) if base else None
    if mode == "forward" and reply_msg and not body:
        body = sanitize(_forward_body(reply_msg), "email")
    stamp = now_iso()
    with db.transaction():
        did = db.insert("drafts", {
            "conversation_id": conv["id"] if conv else None,
            "channel_id": ch["id"] if ch else None,
            "mode": mode,
            "reply_to_message_id": reply_msg["id"] if reply_msg else None,
            "to_json": db.jdump(to or []),
            "cc_json": db.jdump(cc or []),
            "bcc_json": db.jdump(parse_address_list(data.get("bcc")) if data.get("bcc") else []),
            "subject": subject,
            "body_html": body,
            "include_signature": 0 if data.get("include_signature") is False else 1,
            "is_shared": 0 if data.get("is_shared") is False else 1,
            "version": 1,
            "created_by": user["id"],
            "updated_by": user["id"],
            "created_at": stamp,
            "updated_at": stamp,
        })
        if mode == "forward" and reply_msg:
            for att in files.for_owner("message", reply_msg["id"]):
                if not att["is_inline"]:
                    files.copy_to(att, "draft", did, user["id"])
        files.claim(data.get("attachment_ids"), "draft", did, user["id"])
        d = db.one("SELECT * FROM drafts WHERE id = ?", did)
        if conv:
            inbox.follow(conv["id"], user["id"])
            inbox.touch(conv["id"], "draft")
        _broadcast_draft(d, user["id"])
    return d


def update_draft(user: dict, draft_id: int, data: dict) -> dict:
    d = get_draft_for(user, draft_id)
    changes: dict = {}
    for field in ("to", "cc", "bcc"):
        if field in data:
            changes[f"{field}_json"] = db.jdump(parse_address_list(data[field]))
    if "subject" in data:
        changes["subject"] = (data["subject"] or "")[:500]
    if "body_html" in data:
        changes["body_html"] = sanitize(data["body_html"] or "", "basic")
    if "include_signature" in data:
        changes["include_signature"] = 1 if data["include_signature"] else 0
    if "is_shared" in data and d["created_by"] == user["id"]:
        changes["is_shared"] = 1 if data["is_shared"] else 0
    if "channel_id" in data:
        ch = channel(data["channel_id"])
        if not can_send_from(user, ch):
            forbidden("You can't send from that account")
        changes["channel_id"] = ch["id"]
    if "attachment_ids" in data:
        files.claim(data["attachment_ids"], "draft", draft_id, user["id"])
    with db.transaction():
        if changes:
            changes.update({"version": d["version"] + 1, "updated_by": user["id"], "updated_at": now_iso()})
            db.update("drafts", draft_id, changes)
        d = db.one("SELECT * FROM drafts WHERE id = ?", draft_id)
        _broadcast_draft(d, user["id"])
    return d


def delete_draft(user: dict, draft_id: int) -> None:
    d = get_draft_for(user, draft_id)
    with db.transaction():
        files.delete_for_owner("draft", draft_id)
        db.delete("drafts", draft_id)
        if d["conversation_id"]:
            inbox.touch(d["conversation_id"], "draft")
        realtime.emit("draft.changed", {"id": draft_id, "conversation_id": d["conversation_id"], "deleted": True,
                                        "by": user["id"]},
                      users=inbox.audience(d["conversation_id"]) if d["conversation_id"] else [user["id"]])


# -- sending ------------------------------------------------------------------------


def _message_id(ch: dict, mid: int) -> str:
    domain = (ch.get("address") or "switchboard.local").rsplit("@", 1)[-1]
    return f"<sb.{mid}.{token(9)}@{domain}>"


def _validate_recipients(ch: dict, to: list, cc: list, bcc: list) -> tuple[list, list, list]:
    if ch["type"] == "email":
        def clean(lst):
            out = []
            for p in lst:
                e = norm_email(p.get("handle"))
                if not e:
                    bad_request(f"'{p.get('handle')}' isn't a valid email address", code="invalid_recipient")
                out.append({"name": p.get("name"), "handle": e})
            return out
        to, cc, bcc = clean(to), clean(cc), clean(bcc)
        if not (to or cc or bcc):
            bad_request("Add at least one recipient", code="no_recipients")
        return to, cc, bcc
    if ch["type"] in ("sms", "whatsapp"):
        phones = [norm_phone(p.get("handle")) for p in to]
        phones = [p for p in phones if p]
        if not phones:
            bad_request("Add a phone number to text", code="no_recipients")
        return [{"name": to[0].get("name") if to else None, "handle": phones[0]}], [], []
    return to, [], []


def send_draft(user: dict, draft_id: int, send_at=None, close: bool = False) -> dict:
    d = get_draft_for(user, draft_id)
    ch = channel(d["channel_id"])
    if not can_send_from(user, ch):
        bad_request("Choose an account to send from", code="no_channel")
    attachments = files.for_owner("draft", draft_id)
    if is_blank(d["body_html"]) and not attachments:
        bad_request("The message is empty", code="empty")
    to, cc, bcc = _validate_recipients(ch, db.jload(d["to_json"], []), db.jload(d["cc_json"], []),
                                       db.jload(d["bcc_json"], []))
    when = None
    if send_at:
        when = parse_iso(send_at)
        if not when or when <= now():
            bad_request("Pick a time in the future to send")
    else:
        when = now() + timedelta(seconds=int(settings.get("inbox.undo_send_seconds") or 0))
    body = d["body_html"] or ""
    if ch["type"] == "email" and d["include_signature"]:
        sig = signature_for(user, ch)
        if sig:
            body = f'{body}<div class="sb-signature"><br>{sig}</div>'
    body = sanitize(body, "basic")
    text = html_to_text(body)
    if ch["type"] in ("sms", "whatsapp", "chat"):
        body_html_out = None if ch["type"] != "chat" else body
    else:
        body_html_out = body
    conv = inbox.get(d["conversation_id"]) if d["conversation_id"] else None
    reply_msg = db.one("SELECT * FROM messages WHERE id = ?", d["reply_to_message_id"]) if d["reply_to_message_id"] else None
    stamp = now_iso()
    with db.transaction():
        contact_ids = []
        for p in to + cc:
            c = contacts_svc.resolve(contacts_svc.kind_for(p["handle"]), p["handle"], p.get("name"), created_by=user["id"])
            if c:
                contact_ids.append(c["id"])
        created_conversation = False
        if not conv:
            thread_key = to[0]["handle"] if ch["type"] in ("sms", "whatsapp") and to else None
            conv = inbox.create_conversation(d["subject"], ch, contact_ids[0] if contact_ids else None, thread_key,
                                             created_by=user["id"])
            created_conversation = True
        cid = conv["id"]
        refs = []
        if reply_msg:
            refs = db.jload(reply_msg["references_json"], []) + ([reply_msg["external_id"]] if reply_msg["external_id"] else [])
        mid = db.insert("messages", {
            "conversation_id": cid,
            "channel_id": ch["id"],
            "direction": "out",
            "kind": ch["type"] if ch["type"] != "api" else "api",
            "from_name": user["name"],
            "from_handle": ch.get("address"),
            "to_json": db.jdump(to),
            "cc_json": db.jdump(cc),
            "bcc_json": db.jdump(bcc),
            "subject": d["subject"] if ch["type"] == "email" else None,
            "body_text": text,
            "body_html": body_html_out,
            "snippet": snippet(text, 200),
            "in_reply_to": reply_msg["external_id"] if reply_msg else None,
            "references_json": db.jdump(refs[-20:]),
            "author_id": user["id"],
            "status": "scheduled",
            "scheduled_at": iso(when),
            "track_token": token(12) if ch["type"] == "email" else None,
            "draft_json": db.jdump({**serialize_draft(d), "attachments": None, "created_conversation": created_conversation}),
            "date": iso(when),
            "created_at": stamp,
        })
        if ch["type"] == "email":
            db.update("messages", mid, {"external_id": _message_id(ch, mid)})
        files.move("draft", draft_id, "message", mid)
        db.delete("drafts", draft_id)
        db.execute(
            "UPDATE conversations SET message_count = message_count + 1, last_message_at = ?, last_activity_at = ?, "
            "preview = ?, contact_id = COALESCE(contact_id, ?) WHERE id = ?",
            iso(when), stamp, snippet(text, 200), contact_ids[0] if contact_ids else None, cid,
        )
        inbox.set_user_state(cid, user["id"], following=1, last_read_at=stamp)
        if close:
            inbox._apply_one(user, inbox.get(cid), "close", {})
        search.index("message", mid, d["subject"], text, parent_id=cid)
        inbox.touch(cid, "message")
        realtime.emit("draft.changed", {"id": draft_id, "conversation_id": cid, "deleted": True, "sent": True,
                                        "by": user["id"]}, users=inbox.audience(cid))
        hooks.fire("message.queued", {"message_id": mid, "conversation_id": cid, "user_id": user["id"],
                                      "is_new_conversation": created_conversation})
    return db.one("SELECT * FROM messages WHERE id = ?", mid)


def send_new(user: dict, channel_id: int, to, subject: str | None, body_html: str, send_at=None,
             conversation_id: int | None = None, attachment_ids=None, is_auto: bool = False) -> dict:
    """Send without a visible draft (API, rules, auto-replies)."""
    d = create_draft(user, {
        "conversation_id": conversation_id, "mode": "reply" if conversation_id else "new",
        "channel_id": channel_id, "to": to, "cc": [], "subject": subject, "body_html": body_html,
        "attachment_ids": attachment_ids, "is_shared": False,
    })
    msg = send_draft(user, d["id"], send_at=send_at)
    if is_auto:
        db.update("messages", msg["id"], {"is_auto": 1})
    return msg


def cancel_scheduled(user: dict, message_id: int) -> dict:
    """Undo send / cancel send-later: the message goes back to being a draft."""
    msg = db.one("SELECT * FROM messages WHERE id = ?", message_id)
    if not msg or not inbox.can_view(user, msg["conversation_id"]):
        not_found("Message not found")
    if msg["status"] != "scheduled":
        bad_request("It's already on its way", code="already_sent")
    if msg["author_id"] != user["id"] and user["role"] not in inbox.ADMIN_ROLES:
        forbidden("Only the author can cancel this message")
    saved = db.jload(msg["draft_json"], {}) or {}
    cid = msg["conversation_id"]
    stamp = now_iso()
    with db.transaction():
        claimed = db.execute("UPDATE messages SET status = 'cancelled' WHERE id = ? AND status = 'scheduled'", message_id)
        if not claimed.rowcount:
            bad_request("It's already on its way", code="already_sent")
        conv = inbox.get(cid)
        alone = conv["message_count"] <= 1 and conv["comment_count"] == 0
        keep_conversation = not (saved.get("created_conversation") and alone)
        did = db.insert("drafts", {
            "conversation_id": cid if keep_conversation else None,
            "channel_id": msg["channel_id"],
            "mode": saved.get("mode") or "reply",
            "reply_to_message_id": saved.get("reply_to_message_id"),
            "to_json": db.jdump(saved.get("to") or db.jload(msg["to_json"], [])),
            "cc_json": db.jdump(saved.get("cc") or []),
            "bcc_json": db.jdump(saved.get("bcc") or []),
            "subject": saved.get("subject"),
            "body_html": saved.get("body_html") or msg["body_html"] or "",
            "include_signature": 1 if saved.get("include_signature", True) else 0,
            "is_shared": 1 if saved.get("is_shared", True) else 0,
            "version": 1,
            "created_by": user["id"],
            "updated_by": user["id"],
            "created_at": stamp,
            "updated_at": stamp,
        })
        files.move("message", message_id, "draft", did)
        search.unindex("message", message_id)
        db.delete("messages", message_id)
        if keep_conversation:
            inbox.recompute(cid)
            inbox.touch(cid, "message")
        else:
            inbox.delete_forever(cid)
    return db.one("SELECT * FROM drafts WHERE id = ?", did)


def retry(user: dict, message_id: int) -> dict:
    msg = db.one("SELECT * FROM messages WHERE id = ?", message_id)
    if not msg or not inbox.can_view(user, msg["conversation_id"]):
        not_found("Message not found")
    if msg["status"] != "failed":
        bad_request("Only failed messages can be retried")
    with db.transaction():
        db.update("messages", message_id, {"status": "scheduled", "scheduled_at": now_iso(), "error": None, "attempts": 0})
        inbox.touch(msg["conversation_id"], "message")
    return db.one("SELECT * FROM messages WHERE id = ?", message_id)


def process_outbox(limit: int = 25) -> int:
    """Send every scheduled message that's due. Safe to call concurrently: each message
    is claimed with a conditional UPDATE before sending."""
    due = db.query(
        "SELECT id FROM messages WHERE status = 'scheduled' AND scheduled_at <= ? ORDER BY scheduled_at LIMIT ?",
        now_iso(), limit,
    )
    sent = 0
    for row in due:
        if db.execute("UPDATE messages SET status = 'sending' WHERE id = ? AND status = 'scheduled'", row["id"]).rowcount:
            if deliver(row["id"]):
                sent += 1
    return sent


def deliver(message_id: int) -> bool:
    msg = db.one("SELECT * FROM messages WHERE id = ?", message_id)
    conv = inbox.get(msg["conversation_id"])
    ch = channel(msg["channel_id"])
    author = users_svc.get(msg["author_id"])
    reply_to = db.one("SELECT * FROM messages WHERE external_id = ? AND conversation_id = ?", msg["in_reply_to"], conv["id"]) \
        if msg["in_reply_to"] else None
    attachments = files.for_owner("message", message_id)
    ctx = {"conversation": conv, "reply_to": reply_to, "user": author, "base_url": config.current().base_url}
    try:
        if not ch or not ch["is_active"]:
            raise SendError("The account this was sent from is disconnected")
        result = channel_registry.adapter_for(ch).send(ch, msg, attachments, ctx)
    except Exception as exc:  # adapters raise SendError; anything else is a bug but must not stall the queue
        transient = isinstance(exc, SendError) and exc.transient
        attempts = msg["attempts"] + 1
        with db.transaction():
            if transient and attempts <= len(RETRY_MINUTES):
                retry_at = iso(now() + timedelta(minutes=RETRY_MINUTES[attempts - 1]))
                db.update("messages", message_id, {"status": "scheduled", "scheduled_at": retry_at,
                                                    "attempts": attempts, "error": str(exc)})
            else:
                db.update("messages", message_id, {"status": "failed", "attempts": attempts, "error": str(exc)[:1000]})
                if author:
                    notify.notify([author["id"]], "system", f"Couldn't send: {inbox.title_of(conv)}", body=str(exc)[:300],
                                  link=inbox.link(conv["id"]), entity_type="conversation", entity_id=conv["id"],
                                  include_actor=True)
                hooks.fire("message.failed", {"message_id": message_id, "conversation_id": conv["id"], "error": str(exc)})
            inbox.touch(conv["id"], "message")
        return False
    stamp = now_iso()
    with db.transaction():
        changes = {"status": result.status or "sent", "sent_at": stamp, "date": stamp, "attempts": msg["attempts"] + 1,
                   "error": None}
        if result.external_id and not msg["external_id"]:
            changes["external_id"] = result.external_id
        if result.headers:
            changes["headers_json"] = db.jdump(result.headers)
        db.update("messages", message_id, changes)
        conv_changes = {"last_outbound_at": stamp, "last_message_at": stamp}
        if conv["last_inbound_at"] and not conv["first_response_at"]:
            conv_changes["first_response_at"] = stamp
        db.update("conversations", conv["id"], conv_changes)
        inbox.touch(conv["id"], "message")
        hooks.fire("message.sent", {"message_id": message_id, "conversation_id": conv["id"],
                                    "user_id": msg["author_id"], "is_auto": bool(msg["is_auto"])})
    return True
