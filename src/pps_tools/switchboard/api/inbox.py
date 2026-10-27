"""Inbox API: conversations, comments, drafts & sending, labels, canned responses."""

from __future__ import annotations

from flask import Blueprint, Response, request

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import files, inbox, inbox_query, notify, outbox, search, settings
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.services.sanitize import sanitize
from pps_tools.switchboard.util import first_name, now_iso, pick_color, render_template
from pps_tools.switchboard.web import (
    as_bool, as_int, bad_request, body, can, current_user, forbidden, login_required, not_found, ok, require,
    require_fields,
)
from pps_tools.switchboard.worker import Task

bp = Blueprint("inbox", __name__)


# -- conversations ------------------------------------------------------------------


@bp.get("/api/counts")
@login_required
def get_counts():
    return ok(inbox_query.counts(current_user()))


@bp.get("/api/conversations")
@login_required
def list_conversations():
    args = request.args
    limit = min(as_int(args.get("limit"), "limit") or 50, 200)
    return ok(inbox_query.list_conversations(
        current_user(), mailbox=args.get("mailbox") or "inbox", q=(args.get("q") or "").strip() or None,
        cursor=args.get("cursor"), limit=limit, include_closed=as_bool(args.get("include_closed")),
    ))


@bp.post("/api/conversations")
@login_required
def create_discussion():
    """Start an internal discussion (comments only, no external channel)."""
    data = body()
    require_fields(data, "subject")
    user = current_user()
    with db.transaction():
        conv = inbox.create_conversation(data["subject"], None, created_by=user["id"],
                                         team_id=as_int(data.get("team_id"), "team_id"))
        cid = conv["id"]
        inbox.set_user_state(cid, user["id"], following=1, in_inbox=1, last_read_at=now_iso())
        for uid in data.get("user_ids") or []:
            if users_svc.get(int(uid)):
                inbox.set_user_state(cid, int(uid), following=1, in_inbox=1)
        inbox.add_event(cid, "discussion_started", user["id"])
    if (data.get("body") or "").strip():
        inbox.add_comment(user, cid, data["body"], data.get("attachment_ids"))
    with db.transaction():
        inbox.touch(cid, "created")
    return ok({"conversation": inbox_query.detail(user, cid)["conversation"]}, 201)


@bp.get("/api/conversations/<int:cid>")
@login_required
def get_conversation(cid: int):
    return ok(inbox_query.detail(current_user(), cid))


@bp.post("/api/conversations/<int:cid>/read")
@login_required
def read_conversation(cid: int):
    user = current_user()
    inbox.get_for(user, cid)
    with db.transaction():
        inbox.mark_read(cid, user["id"])
        notify.mark_entity_read(user["id"], "conversation", cid)
        realtime.emit("badges.changed", {}, users=[user["id"]])
    return ok()


@bp.get("/api/conversations/<int:cid>/history")
@login_required
def contact_history(cid: int):
    user = current_user()
    conv = inbox.get_for(user, cid)
    if not conv["contact_id"]:
        return ok({"items": []})
    return ok({"items": inbox_query.contact_history(user, conv["contact_id"], exclude=cid)})


@bp.post("/api/conversations/actions")
@login_required
def conversation_actions():
    data = body()
    require_fields(data, "ids", "action")
    ids = data["ids"] if isinstance(data["ids"], list) else [data["ids"]]
    params = {k: v for k, v in data.items() if k not in ("ids", "action")}
    done = inbox.apply_action(current_user(), ids, data["action"], params)
    return ok({"ids": done})


@bp.post("/api/conversations/<int:cid>/comments")
@login_required
def add_comment(cid: int):
    data = body()
    comment = inbox.add_comment(current_user(), cid, data.get("body") or "", data.get("attachment_ids"))
    return ok({"comment": comment}, 201)


@bp.patch("/api/comments/<int:comment_id>")
@login_required
def edit_comment(comment_id: int):
    return ok({"comment": inbox.edit_comment(current_user(), comment_id, body().get("body") or "")})


@bp.delete("/api/comments/<int:comment_id>")
@login_required
def delete_comment(comment_id: int):
    inbox.delete_comment(current_user(), comment_id)
    return ok()


@bp.post("/api/conversations/<int:cid>/reminders")
@login_required
def add_reminder(cid: int):
    data = body()
    reminder = inbox.add_reminder(current_user(), cid, data.get("remind_at"), data.get("condition") or "always",
                                  data.get("note"))
    return ok({"reminder": reminder}, 201)


@bp.delete("/api/reminders/<int:rid>")
@login_required
def delete_reminder(rid: int):
    r = db.one("SELECT * FROM reminders WHERE id = ? AND user_id = ?", rid, current_user()["id"])
    if not r:
        not_found("Reminder not found")
    with db.transaction():
        db.delete("reminders", rid)
        inbox.touch(r["conversation_id"], "reminder")
    return ok()


# -- drafts & sending ---------------------------------------------------------------


@bp.get("/api/drafts")
@login_required
def list_new_drafts():
    return ok({"items": inbox_query.new_drafts(current_user())})


@bp.post("/api/drafts")
@login_required
def create_draft():
    d = outbox.create_draft(current_user(), body())
    return ok({"draft": outbox.serialize_draft(d)}, 201)


@bp.get("/api/drafts/<int:did>")
@login_required
def get_draft(did: int):
    return ok({"draft": outbox.serialize_draft(outbox.get_draft_for(current_user(), did))})


@bp.patch("/api/drafts/<int:did>")
@login_required
def update_draft(did: int):
    d = outbox.update_draft(current_user(), did, body())
    return ok({"draft": outbox.serialize_draft(d)})


@bp.delete("/api/drafts/<int:did>")
@login_required
def delete_draft(did: int):
    outbox.delete_draft(current_user(), did)
    return ok()


@bp.post("/api/drafts/<int:did>/send")
@login_required
def send_draft(did: int):
    data = body()
    msg = outbox.send_draft(current_user(), did, send_at=data.get("send_at"), close=as_bool(data.get("close")))
    return ok({"message_id": msg["id"], "conversation_id": msg["conversation_id"], "status": msg["status"],
               "scheduled_at": msg["scheduled_at"]}, 201)


@bp.post("/api/messages/<int:mid>/cancel")
@login_required
def cancel_message(mid: int):
    d = outbox.cancel_scheduled(current_user(), mid)
    return ok({"draft": outbox.serialize_draft(d)})


@bp.post("/api/messages/<int:mid>/retry")
@login_required
def retry_message(mid: int):
    msg = outbox.retry(current_user(), mid)
    return ok({"status": msg["status"]})


@bp.get("/api/messages/<int:mid>/raw")
@login_required
def raw_message(mid: int):
    msg = db.one("SELECT * FROM messages WHERE id = ?", mid)
    if not msg or not inbox.can_view(current_user(), msg["conversation_id"]) or not msg["raw_key"]:
        not_found("Original not available")
    data = files.read_blob(msg["raw_key"])
    if data is None:
        not_found("Original not available")
    return Response(data, mimetype="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="message-{mid}.eml"',
                             "Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff"})


@bp.get("/api/compose/channels")
@login_required
def compose_channels():
    user = current_user()
    return ok({"items": [{"id": c["id"], "type": c["type"], "name": c["name"], "address": c["address"],
                          "visibility": c["visibility"]} for c in outbox.sendable_channels(user)]})


@bp.get("/api/compose/recipients")
@login_required
def recipient_suggestions():
    q = (request.args.get("q") or "").strip()
    kind = request.args.get("kind") or "email"
    if len(q) < 1:
        return ok({"items": []})
    like = f"%{q}%"
    rows = db.query(
        "SELECT c.id, c.name, h.value, h.kind FROM contact_handles h JOIN contacts c ON c.id = h.contact_id "
        "WHERE h.kind = ? AND (h.value LIKE ? OR c.name LIKE ?) "
        "ORDER BY (SELECT MAX(last_activity_at) FROM conversations WHERE contact_id = c.id) DESC LIMIT 8",
        "email" if kind == "email" else "phone", like, like,
    )
    return ok({"items": [{"contact_id": r["id"], "name": r["name"], "handle": r["value"]} for r in rows]})


@bp.get("/api/me/signature")
@login_required
def my_signature():
    user = current_user()
    channel_id = as_int(request.args.get("channel_id"), "channel_id")
    ch = outbox.channel(channel_id) if channel_id else None
    prefs = db.jload(user["prefs_json"], {}) or {}
    return ok({"signature_html": prefs.get("signature_html") or "", "effective_html": outbox.signature_for(user, ch)})


# -- labels -------------------------------------------------------------------------


def visible_labels(user: dict) -> list[dict]:
    return db.query(
        "SELECT id, name, color, parent_id, visibility, owner_user_id, position FROM labels "
        "WHERE visibility = 'shared' OR owner_user_id = ? ORDER BY position, name COLLATE NOCASE",
        user["id"],
    )


@bp.get("/api/labels")
@login_required
def list_labels():
    return ok({"items": visible_labels(current_user())})


def _label_payload(data: dict, partial: bool) -> dict:
    out = {}
    if "name" in data or not partial:
        name = (data.get("name") or "").strip()
        if not name:
            bad_request("Label name is required")
        out["name"] = name[:80]
    if "color" in data:
        out["color"] = data["color"]
    if "parent_id" in data:
        out["parent_id"] = as_int(data["parent_id"], "parent_id")
    if "position" in data:
        out["position"] = as_int(data["position"], "position") or 0
    return out


@bp.post("/api/labels")
@login_required
def create_label():
    data = body()
    user = current_user()
    values = _label_payload(data, partial=False)
    visibility = data.get("visibility") or "shared"
    if visibility not in ("shared", "personal"):
        bad_request("visibility must be shared or personal")
    if visibility == "shared" and not can(user, "inbox"):
        forbidden()
    values.update({"visibility": visibility, "owner_user_id": user["id"] if visibility == "personal" else None,
                   "color": values.get("color") or pick_color(values["name"]), "created_at": now_iso()})
    with db.transaction():
        lid = db.insert("labels", values)
        realtime.emit("settings.changed", {"what": "labels"})
    return ok({"label": db.one("SELECT * FROM labels WHERE id = ?", lid)}, 201)


def _own_label(lid: int) -> dict:
    label = db.one("SELECT * FROM labels WHERE id = ?", lid)
    user = current_user()
    if not label:
        not_found("Label not found")
    if label["visibility"] == "personal" and label["owner_user_id"] != user["id"]:
        not_found("Label not found")
    if label["visibility"] == "shared" and user["role"] not in ("owner", "admin", "manager", "agent"):
        forbidden()
    return label


@bp.patch("/api/labels/<int:lid>")
@login_required
def update_label(lid: int):
    _own_label(lid)
    with db.transaction():
        db.update("labels", lid, _label_payload(body(), partial=True))
        realtime.emit("settings.changed", {"what": "labels"})
    return ok({"label": db.one("SELECT * FROM labels WHERE id = ?", lid)})


@bp.delete("/api/labels/<int:lid>")
@login_required
def delete_label(lid: int):
    _own_label(lid)
    with db.transaction():
        db.delete("labels", lid)
        realtime.emit("settings.changed", {"what": "labels"})
    return ok()


# -- canned responses ---------------------------------------------------------------


def _visible_responses(user: dict, q: str | None = None) -> list[dict]:
    team_ids = users_svc.team_ids_of(user["id"]) or [0]
    params: list = [user["id"], *team_ids]
    where = (f"(visibility = 'shared' OR (visibility = 'personal' AND owner_user_id = ?) "
             f"OR (visibility = 'team' AND team_id IN ({db.placeholders(team_ids)})))")
    if q:
        where += " AND (title LIKE ? OR shortcut LIKE ? OR body_html LIKE ?)"
        params += [f"%{q}%", f"{q}%", f"%{q}%"]
    return db.query(f"SELECT * FROM canned_responses WHERE {where} ORDER BY usage_count DESC, title COLLATE NOCASE", params)


@bp.get("/api/responses")
@require("inbox")
def list_responses():
    return ok({"items": _visible_responses(current_user(), (request.args.get("q") or "").strip() or None)})


def _response_payload(data: dict, partial: bool) -> dict:
    out = {}
    if "title" in data or not partial:
        title = (data.get("title") or "").strip()
        if not title:
            bad_request("Give the response a name")
        out["title"] = title[:120]
    for field in ("subject", "folder"):
        if field in data:
            out[field] = (data[field] or "").strip() or None
    if "shortcut" in data:
        out["shortcut"] = (data["shortcut"] or "").strip().lstrip("/").lower() or None
    if "body_html" in data:
        out["body_html"] = sanitize(data["body_html"] or "", "basic")
    if "visibility" in data:
        if data["visibility"] not in ("shared", "personal", "team"):
            bad_request("visibility must be shared, personal or team")
        out["visibility"] = data["visibility"]
    if "team_id" in data:
        out["team_id"] = as_int(data["team_id"], "team_id")
    return out


@bp.post("/api/responses")
@require("inbox")
def create_response():
    user = current_user()
    values = _response_payload(body(), partial=False)
    values.setdefault("visibility", "shared")
    values["owner_user_id"] = user["id"]
    values["created_at"] = values["updated_at"] = now_iso()
    with db.transaction():
        rid = db.insert("canned_responses", values)
    return ok({"response": db.one("SELECT * FROM canned_responses WHERE id = ?", rid)}, 201)


def _editable_response(rid: int) -> dict:
    row = db.one("SELECT * FROM canned_responses WHERE id = ?", rid)
    user = current_user()
    if not row or row["id"] not in {r["id"] for r in _visible_responses(user)}:
        not_found("Response not found")
    if row["visibility"] == "personal" and row["owner_user_id"] != user["id"]:
        forbidden()
    return row


@bp.patch("/api/responses/<int:rid>")
@require("inbox")
def update_response(rid: int):
    _editable_response(rid)
    values = _response_payload(body(), partial=True)
    values["updated_at"] = now_iso()
    with db.transaction():
        db.update("canned_responses", rid, values)
    return ok({"response": db.one("SELECT * FROM canned_responses WHERE id = ?", rid)})


@bp.delete("/api/responses/<int:rid>")
@require("inbox")
def delete_response(rid: int):
    _editable_response(rid)
    with db.transaction():
        db.delete("canned_responses", rid)
    return ok()


def render_response(row: dict, user: dict, conversation: dict | None) -> dict:
    contact = contacts_svc.get(conversation["contact_id"]) if conversation and conversation.get("contact_id") else None
    ctx = {
        "__html__": True,
        "contact": {
            "name": (contact or {}).get("name") or "", "first_name": first_name((contact or {}).get("name")) or "there",
            "email": (contact or {}).get("email") or "", "phone": (contact or {}).get("phone") or "",
        },
        "user": {"name": user["name"], "first_name": first_name(user["name"]), "email": user["email"],
                 "title": user.get("title") or "", "phone": user.get("phone") or ""},
        "org": {"name": settings.get("org.name")},
        "conversation": {"subject": (conversation or {}).get("subject") or "", "id": (conversation or {}).get("id") or ""},
    }
    return {
        "subject": render_template(row["subject"], {**ctx, "__html__": False}) if row["subject"] else None,
        "body_html": sanitize(render_template(row["body_html"], ctx), "basic"),
    }


@bp.post("/api/responses/<int:rid>/render")
@require("inbox")
def use_response(rid: int):
    user = current_user()
    row = next((r for r in _visible_responses(user) if r["id"] == rid), None)
    if not row:
        not_found("Response not found")
    cid = as_int(body().get("conversation_id"), "conversation_id")
    conv = inbox.get_for(user, cid) if cid else None
    db.execute("UPDATE canned_responses SET usage_count = usage_count + 1 WHERE id = ?", rid)
    return ok(render_response(row, user, conv))


# -- module hooks -------------------------------------------------------------------


def _can_read_message_file(user: dict, mid: int) -> bool:
    row = db.one("SELECT conversation_id FROM messages WHERE id = ?", mid)
    return bool(row) and inbox.can_view(user, row["conversation_id"])


def _can_read_comment_file(user: dict, comment_id: int) -> bool:
    row = db.one("SELECT conversation_id FROM comments WHERE id = ?", comment_id)
    return bool(row) and inbox.can_view(user, row["conversation_id"])


def _can_read_draft_file(user: dict, did: int) -> bool:
    d = db.one("SELECT * FROM drafts WHERE id = ?", did)
    if not d:
        return False
    return d["created_by"] == user["id"] or bool(d["is_shared"] and d["conversation_id"] and inbox.can_view(user, d["conversation_id"]))


files.register_access("message", _can_read_message_file)
files.register_access("comment", _can_read_comment_file)
files.register_access("draft", _can_read_draft_file)


def bootstrap(user: dict) -> dict:
    channel_ids = set(inbox.visible_channel_ids(user))
    channels = [
        {"id": c["id"], "type": c["type"], "name": c["name"], "address": c["address"], "visibility": c["visibility"],
         "team_id": c["team_id"], "is_active": bool(c["is_active"]), "owner_user_id": c["owner_user_id"]}
        for c in db.query("SELECT * FROM channels ORDER BY type, name") if c["id"] in channel_ids
    ]
    return {"labels": visible_labels(user), "channels": channels}


def badges(user: dict) -> dict:
    if not can(user, "inbox"):
        return {}
    counts = inbox_query.counts(user)
    return {"inbox": counts["inbox_unread"]}


def search(user: dict, q: str, limit: int) -> list[dict]:
    if not can(user, "inbox"):
        return []
    res = inbox_query.list_conversations(user, mailbox="all", q=q, limit=limit)
    return [{
        "type": "conversation", "id": c["id"],
        "title": c["subject"] or (c["contact"] or {}).get("display_name") or "Conversation",
        "subtitle": ((c["contact"] or {}).get("display_name") or "") + (" · " if c["contact"] else "") + (c["preview"] or ""),
        "url": inbox.link(c["id"]), "icon": {"sms": "smartphone", "whatsapp": "message-circle", "chat": "message-square"}.get(
            (c["channel"] or {}).get("type"), "mail"),
        "group": "Conversations",
    } for c in res["items"]]


def worker_tasks():
    return [
        Task("inbox.outbox", 2, outbox.process_outbox),
        Task("inbox.snooze", 15, inbox.wake_snoozed),
        Task("inbox.reminders", 30, inbox.process_reminders),
    ]


DEFAULT_LABELS = [
    ("Quote request", "#1971c2"), ("Order", "#2f9e44"), ("Proof", "#7048e8"), ("Rush", "#e03131"),
    ("Billing", "#f08c00"), ("Vendor", "#868e96"),
]


def on_setup(ctx: dict) -> None:
    stamp = now_iso()
    for i, (name, color) in enumerate(DEFAULT_LABELS):
        db.insert("labels", {"name": name, "color": color, "visibility": "shared", "position": i, "created_at": stamp})
    if not ctx.get("demo"):
        tid = db.insert("teams", {"name": "Front Office", "color": "#0c8599", "created_at": stamp})
        db.insert("team_members", {"team_id": tid, "user_id": ctx["owner_id"]})


def seed(ctx) -> None:
    from pps_tools.switchboard.demo.inbox import seed_inbox

    seed_inbox(ctx)
