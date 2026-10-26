"""Team chat API: rooms, DMs, messages, threads, typing."""

from __future__ import annotations

from flask import Blueprint, request

from pps_tools.switchboard import db
from pps_tools.switchboard.services import chat as chat_svc
from pps_tools.switchboard.services import files, search as search_svc
from pps_tools.switchboard.util import now_iso
from pps_tools.switchboard.web import as_bool, as_int, bad_request, body, current_user, login_required, ok

bp = Blueprint("chat", __name__)


def _room_payload(room_id: int) -> dict:
    user = current_user()
    return chat_svc.serialize_rooms(user, [chat_svc.room(room_id)])[0]


@bp.get("/api/chat/rooms")
@login_required
def list_rooms():
    return ok({"items": chat_svc.list_rooms(current_user())})


@bp.get("/api/chat/rooms/browse")
@login_required
def browse_rooms():
    return ok({"items": chat_svc.browse_rooms(current_user())})


@bp.post("/api/chat/rooms")
@login_required
def create_room():
    data = body()
    r = chat_svc.create_room(current_user(), data.get("name"), data.get("topic"), as_bool(data.get("is_private")),
                             data.get("member_ids") or [])
    return ok({"room": _room_payload(r["id"])}, 201)


@bp.get("/api/chat/rooms/<int:room_id>")
@login_required
def get_room(room_id: int):
    chat_svc.room_for(current_user(), room_id)
    return ok({"room": _room_payload(room_id)})


@bp.patch("/api/chat/rooms/<int:room_id>")
@login_required
def update_room(room_id: int):
    chat_svc.update_room(current_user(), room_id, body())
    return ok({"room": _room_payload(room_id)})


@bp.post("/api/chat/rooms/<int:room_id>/join")
@login_required
def join_room(room_id: int):
    chat_svc.join(current_user(), room_id)
    return ok({"room": _room_payload(room_id)})


@bp.post("/api/chat/rooms/<int:room_id>/leave")
@login_required
def leave_room(room_id: int):
    chat_svc.leave(current_user(), room_id)
    return ok()


@bp.post("/api/chat/rooms/<int:room_id>/members")
@login_required
def add_members(room_id: int):
    ids = body().get("user_ids") or []
    if not isinstance(ids, list):
        bad_request("user_ids must be a list")
    chat_svc.add_members(current_user(), room_id, ids)
    return ok({"room": _room_payload(room_id)})


@bp.delete("/api/chat/rooms/<int:room_id>/members/<int:uid>")
@login_required
def remove_member(room_id: int, uid: int):
    chat_svc.remove_member(current_user(), room_id, uid)
    return ok()


@bp.post("/api/chat/rooms/<int:room_id>/mute")
@login_required
def mute_room(room_id: int):
    chat_svc.set_muted(current_user(), room_id, as_bool(body().get("muted", True)))
    return ok()


@bp.post("/api/chat/rooms/<int:room_id>/read")
@login_required
def read_room(room_id: int):
    chat_svc.mark_read(current_user(), room_id)
    return ok()


@bp.post("/api/chat/rooms/<int:room_id>/typing")
@login_required
def typing(room_id: int):
    chat_svc.typing(current_user(), room_id)
    return ok()


@bp.get("/api/chat/rooms/<int:room_id>/messages")
@login_required
def list_messages(room_id: int):
    args = request.args
    return ok(chat_svc.list_messages(
        current_user(), room_id, before=as_int(args.get("before"), "before"), after=as_int(args.get("after"), "after"),
        around=as_int(args.get("around"), "around"), limit=as_int(args.get("limit"), "limit") or 50,
    ))


@bp.post("/api/chat/rooms/<int:room_id>/messages")
@login_required
def post_message(room_id: int):
    data = body()
    m = chat_svc.post_message(current_user(), room_id, data.get("body") or "", as_int(data.get("parent_id"), "parent_id"),
                              data.get("attachment_ids"), as_int(data.get("conversation_id"), "conversation_id"))
    return ok({"message": chat_svc.serialize_messages(current_user(), [m])[0]}, 201)


@bp.get("/api/chat/messages/<int:message_id>/thread")
@login_required
def get_thread(message_id: int):
    return ok(chat_svc.thread(current_user(), message_id))


@bp.patch("/api/chat/messages/<int:message_id>")
@login_required
def edit_message(message_id: int):
    m = chat_svc.edit_message(current_user(), message_id, body().get("body") or "")
    return ok({"message": chat_svc.serialize_messages(current_user(), [m])[0]})


@bp.delete("/api/chat/messages/<int:message_id>")
@login_required
def delete_message(message_id: int):
    chat_svc.delete_message(current_user(), message_id)
    return ok()


@bp.route("/api/chat/dm/<int:user_id>", methods=["GET", "POST"])
@login_required
def direct_message(user_id: int):
    r = chat_svc.get_or_create_dm(current_user(), [user_id] if user_id != current_user()["id"] else [])
    return ok({"room": _room_payload(r["id"])})


@bp.post("/api/chat/dms")
@login_required
def group_message():
    ids = body().get("user_ids") or []
    if not isinstance(ids, list) or not ids:
        bad_request("Pick who to message")
    r = chat_svc.get_or_create_dm(current_user(), [int(i) for i in ids if int(i) != current_user()["id"]])
    return ok({"room": _room_payload(r["id"])}, 201)


# -- module hooks -------------------------------------------------------------------


def _can_read_chat_file(user: dict, message_id: int) -> bool:
    m = db.one("SELECT room_id FROM chat_messages WHERE id = ?", message_id)
    r = chat_svc.room(m["room_id"]) if m else None
    return bool(r) and chat_svc.can_read(user, r)


files.register_access("chat_message", _can_read_chat_file)


def on_setup(ctx: dict) -> None:
    stamp = now_iso()
    owner = ctx.get("owner_id")
    general = db.insert("chat_rooms", {"kind": "channel", "name": "general", "topic": "Shop-wide announcements and chatter",
                                       "is_default": 1, "created_by": owner, "created_at": stamp})
    db.insert("chat_rooms", {"kind": "channel", "name": "production", "topic": "Press schedule, maintenance, what's running",
                             "created_by": owner, "created_at": stamp})
    if owner:
        db.insert("chat_members", {"room_id": general, "user_id": owner, "joined_at": stamp, "last_read_at": stamp})


def badges(user: dict) -> dict:
    return {"chat": chat_svc.unread_total(user)}


def search(user: dict, q: str, limit: int) -> list[dict]:
    out = []
    like = f"%{chat_svc.normalize_name(q) or q}%"
    for r in db.query("SELECT * FROM chat_rooms WHERE kind = 'channel' AND archived_at IS NULL AND name LIKE ? "
                      "ORDER BY name LIMIT ?", like, limit):
        if chat_svc.can_read(user, r):
            out.append({"type": "chat_room", "id": r["id"], "title": f"#{r['name']}", "subtitle": r["topic"] or "Channel",
                        "url": f"/chat/{r['id']}", "icon": "hash", "group": "Chat"})
    seen_rooms = {}
    for hit in search_svc.search(["chat"], q, 200):
        rid = hit["parent_id"]
        if rid not in seen_rooms:
            r = chat_svc.room(rid)
            seen_rooms[rid] = r if r and chat_svc.can_read(user, r) else None
        r = seen_rooms[rid]
        if not r:
            continue
        m = db.one("SELECT * FROM chat_messages WHERE id = ? AND deleted_at IS NULL", hit["ref_id"])
        if not m:
            continue
        from pps_tools.switchboard.util import html_to_text, snippet

        where = f"#{r['name']}" if r["kind"] == "channel" else "Direct message"
        out.append({"type": "chat_message", "id": m["id"], "title": snippet(html_to_text(m["body"]), 80),
                    "subtitle": where, "url": f"/chat/{rid}?m={m['id']}" + (f"&thread={m['parent_id']}" if m["parent_id"] else ""),
                    "icon": "messages-square", "group": "Chat"})
        if len(out) >= limit * 2:
            break
    return out


def seed(ctx) -> None:
    from pps_tools.switchboard.demo.chat import seed_chat

    seed_chat(ctx)
