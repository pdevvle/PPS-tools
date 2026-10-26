"""Team chat: channels (public or private), direct messages, threads, mentions,
reactions, attachments, unread counts, and sharing inbox conversations into a room.

Live updates are hints: 'chat.message' {room_id, id, parent_id, user_id} tells members
to fetch new messages; 'chat.room' {room_id} to refresh room lists; 'chat.typing'.
"""

from __future__ import annotations

import re

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import files, inbox, notify, reactions, search
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.services.sanitize import is_blank, mention_ids, sanitize
from pps_tools.switchboard.util import html_to_text, now_iso, snippet
from pps_tools.switchboard.web import bad_request, conflict, forbidden, not_found

MANAGER_ROLES = ("owner", "admin", "manager")
DELETED_BODY = ""


# -- rooms --------------------------------------------------------------------------


def room(room_id: int) -> dict | None:
    return db.one("SELECT * FROM chat_rooms WHERE id = ?", room_id)


def member_row(room_id: int, uid: int) -> dict | None:
    return db.one("SELECT * FROM chat_members WHERE room_id = ? AND user_id = ? AND left_at IS NULL", room_id, uid)


def member_ids(room_id: int) -> list[int]:
    return db.column(
        "SELECT cm.user_id FROM chat_members cm JOIN users u ON u.id = cm.user_id "
        "WHERE cm.room_id = ? AND cm.left_at IS NULL AND u.is_active = 1 ORDER BY cm.user_id", room_id,
    )


def can_read(user: dict, r: dict) -> bool:
    if member_row(r["id"], user["id"]):
        return True
    return r["kind"] == "channel" and not r["is_private"]


def room_for(user: dict, room_id: int) -> dict:
    r = room(room_id)
    if not r or not can_read(user, r):
        not_found("Room not found")
    return r


def normalize_name(name: str | None) -> str:
    name = (name or "").strip().lstrip("#").lower()
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"[^a-z0-9\-]", "", name).strip("-")
    return name[:60]


def ensure_defaults(user: dict) -> None:
    """Join default rooms (#general) the first time this person opens chat."""
    rows = db.query(
        "SELECT r.id FROM chat_rooms r WHERE r.is_default = 1 AND r.archived_at IS NULL AND NOT EXISTS "
        "(SELECT 1 FROM chat_members m WHERE m.room_id = r.id AND m.user_id = ?)", user["id"],
    )
    if not rows:
        return
    stamp = now_iso()
    with db.transaction():
        for r in rows:
            db.insert("chat_members", {"room_id": r["id"], "user_id": user["id"], "joined_at": stamp, "last_read_at": stamp})


def _add_member(room_id: int, uid: int, read_now: bool = False) -> bool:
    existing = db.one("SELECT * FROM chat_members WHERE room_id = ? AND user_id = ?", room_id, uid)
    stamp = now_iso()
    if existing:
        if existing["left_at"] is None:
            return False
        db.execute("UPDATE chat_members SET left_at = NULL, joined_at = ?, last_read_at = ? WHERE room_id = ? AND user_id = ?",
                   stamp, stamp, room_id, uid)
        return True
    db.insert("chat_members", {"room_id": room_id, "user_id": uid, "joined_at": stamp,
                               "last_read_at": stamp if read_now else None})
    return True


def _emit_room(room_id: int, users=None) -> None:
    people = sorted(set(users or []) | set(member_ids(room_id)))
    realtime.emit("chat.room", {"room_id": room_id}, users=people)
    realtime.emit("badges.changed", {}, users=people)


def create_room(user: dict, name: str, topic: str | None = None, is_private: bool = False,
                member_ids_: list | None = None) -> dict:
    slug = normalize_name(name)
    if not slug:
        bad_request("Give the channel a name (letters, numbers and dashes)", code="validation")
    if db.one("SELECT id FROM chat_rooms WHERE kind = 'channel' AND name = ? COLLATE NOCASE", slug):
        conflict(f"#{slug} already exists", code="duplicate")
    stamp = now_iso()
    with db.transaction():
        rid = db.insert("chat_rooms", {"kind": "channel", "name": slug, "topic": (topic or "").strip()[:250] or None,
                                       "is_private": 1 if is_private else 0, "created_by": user["id"], "created_at": stamp})
        _add_member(rid, user["id"], read_now=True)
        active = set(users_svc.active_ids())
        for uid in member_ids_ or []:
            if int(uid) in active:
                _add_member(rid, int(uid), read_now=True)
        _emit_room(rid)
    return room(rid)


def update_room(user: dict, room_id: int, data: dict) -> dict:
    r = room_for(user, room_id)
    if r["kind"] == "dm":
        bad_request("Direct messages can't be renamed")
    is_owner = r["created_by"] == user["id"] or user["role"] in MANAGER_ROLES
    if not member_row(room_id, user["id"]):
        forbidden("Join the channel first")
    values = {}
    if "topic" in data:
        values["topic"] = (data["topic"] or "").strip()[:250] or None
    if any(k in data for k in ("name", "is_private", "archived")) and not is_owner:
        forbidden("Only the channel's creator or a manager can do that")
    if "name" in data:
        slug = normalize_name(data["name"])
        if not slug:
            bad_request("Channel names use letters, numbers and dashes")
        if db.one("SELECT id FROM chat_rooms WHERE kind = 'channel' AND name = ? COLLATE NOCASE AND id != ?", slug, room_id):
            conflict(f"#{slug} already exists", code="duplicate")
        values["name"] = slug
    if "is_private" in data:
        if r["is_default"] and data["is_private"]:
            bad_request("The default channel stays public")
        values["is_private"] = 1 if data["is_private"] else 0
    if "archived" in data:
        values["archived_at"] = now_iso() if data["archived"] else None
    with db.transaction():
        if values:
            db.update("chat_rooms", room_id, values)
        _emit_room(room_id)
    return room(room_id)


def join(user: dict, room_id: int) -> dict:
    r = room_for(user, room_id)
    if r["kind"] == "dm":
        forbidden()
    with db.transaction():
        _add_member(room_id, user["id"], read_now=False)
        _emit_room(room_id)
    return r


def leave(user: dict, room_id: int) -> None:
    r = room_for(user, room_id)
    if r["kind"] == "dm":
        bad_request("You can mute a direct message, but not leave it")
    with db.transaction():
        db.execute("UPDATE chat_members SET left_at = ? WHERE room_id = ? AND user_id = ?", now_iso(), room_id, user["id"])
        _emit_room(room_id, users=[user["id"]])


def add_members(user: dict, room_id: int, ids: list) -> None:
    r = room_for(user, room_id)
    if not member_row(room_id, user["id"]):
        forbidden("Join the channel first")
    if r["kind"] == "dm":
        bad_request("Start a new group message instead")
    active = set(users_svc.active_ids())
    with db.transaction():
        added = [int(u) for u in ids if int(u) in active and _add_member(room_id, int(u), read_now=True)]
        if added:
            notify.notify(added, "chat", f"{user['name']} added you to #{r['name']}", link=f"/chat/{room_id}",
                          actor_id=user["id"], entity_type="chat_room", entity_id=room_id)
        _emit_room(room_id, users=added)


def remove_member(user: dict, room_id: int, uid: int) -> None:
    r = room_for(user, room_id)
    if uid != user["id"] and not (r["created_by"] == user["id"] or user["role"] in MANAGER_ROLES):
        forbidden("Only the channel's creator or a manager can remove people")
    if r["kind"] == "dm":
        bad_request("People can't be removed from a direct message")
    with db.transaction():
        db.execute("UPDATE chat_members SET left_at = ? WHERE room_id = ? AND user_id = ?", now_iso(), room_id, uid)
        _emit_room(room_id, users=[uid])


def set_muted(user: dict, room_id: int, muted: bool) -> None:
    if not member_row(room_id, user["id"]):
        not_found("Room not found")
    with db.transaction():
        db.execute("UPDATE chat_members SET muted = ? WHERE room_id = ? AND user_id = ?", 1 if muted else 0, room_id, user["id"])
        realtime.emit("chat.room", {"room_id": room_id}, users=[user["id"]])
        realtime.emit("badges.changed", {}, users=[user["id"]])


def mark_read(user: dict, room_id: int) -> None:
    if not member_row(room_id, user["id"]):
        return
    with db.transaction():
        db.execute("UPDATE chat_members SET last_read_at = ? WHERE room_id = ? AND user_id = ?", now_iso(), room_id, user["id"])
        notify.mark_entity_read(user["id"], "chat_room", room_id)
        realtime.emit("chat.read", {"room_id": room_id}, users=[user["id"]])
        realtime.emit("badges.changed", {}, users=[user["id"]])


def get_or_create_dm(user: dict, other_ids: list) -> dict:
    others = sorted({int(u) for u in other_ids})
    active = set(users_svc.active_ids())
    if any(u not in active for u in others):
        bad_request("Can't message that person")
    if len(others) > 8:
        bad_request("Group messages are limited to 9 people; make a channel instead")
    ids = sorted(set(others) | {user["id"]})
    key = ",".join(str(i) for i in ids)
    existing = db.one("SELECT * FROM chat_rooms WHERE dm_key = ?", key)
    if existing:
        return existing
    stamp = now_iso()
    with db.transaction():
        rid = db.insert("chat_rooms", {"kind": "dm", "dm_key": key, "is_private": 1, "created_by": user["id"],
                                       "created_at": stamp})
        for uid in ids:
            db.insert("chat_members", {"room_id": rid, "user_id": uid, "joined_at": stamp, "last_read_at": stamp})
        _emit_room(rid)
    return room(rid)


# -- listing ------------------------------------------------------------------------


def _unread(user: dict) -> dict[int, dict]:
    uid = user["id"]
    rows = db.query(
        "SELECT m.room_id, COUNT(*) AS n, "
        "SUM(CASE WHEN (',' || substr(m.mentions_json, 2, length(m.mentions_json) - 2) || ',') LIKE ? THEN 1 ELSE 0 END) AS mentions "
        "FROM chat_messages m JOIN chat_members cm ON cm.room_id = m.room_id AND cm.user_id = ? AND cm.left_at IS NULL "
        "WHERE m.parent_id IS NULL AND m.deleted_at IS NULL AND (m.user_id IS NULL OR m.user_id != ?) "
        "AND (cm.last_read_at IS NULL OR m.created_at > cm.last_read_at) GROUP BY m.room_id",
        f"%,{uid},%", uid, uid,
    )
    return {r["room_id"]: {"unread": r["n"], "mentions": r["mentions"] or 0} for r in rows}


def unread_total(user: dict) -> int:
    counts = _unread(user)
    muted = set(db.column("SELECT room_id FROM chat_members WHERE user_id = ? AND muted = 1 AND left_at IS NULL", user["id"]))
    return sum(c["unread"] for rid, c in counts.items() if rid not in muted)


def _last_messages(room_ids: list[int]) -> dict[int, dict]:
    if not room_ids:
        return {}
    rows = db.query(
        f"SELECT m.* FROM chat_messages m JOIN (SELECT room_id, MAX(id) AS mid FROM chat_messages "
        f"WHERE parent_id IS NULL AND deleted_at IS NULL AND room_id IN ({db.placeholders(room_ids)}) GROUP BY room_id) x "
        f"ON x.mid = m.id", room_ids,
    )
    out = {}
    for m in rows:
        text = html_to_text(m["body"]) or ("📎 Attachment" if files.for_owner("chat_message", m["id"]) else
                                            ("Shared a conversation" if m["conversation_id"] else ""))
        out[m["room_id"]] = {"id": m["id"], "user_id": m["user_id"], "preview": snippet(text, 90), "created_at": m["created_at"]}
    return out


def serialize_rooms(user: dict, rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    unread = _unread(user)
    last = _last_messages(ids)
    members: dict[int, list[int]] = {}
    for m in db.query(
        f"SELECT cm.room_id, cm.user_id FROM chat_members cm JOIN users u ON u.id = cm.user_id "
        f"WHERE cm.left_at IS NULL AND u.is_active = 1 AND cm.room_id IN ({db.placeholders(ids)}) ORDER BY cm.user_id", ids,
    ):
        members.setdefault(m["room_id"], []).append(m["user_id"])
    mine = {m["room_id"]: m for m in db.query(
        f"SELECT * FROM chat_members WHERE user_id = ? AND left_at IS NULL AND room_id IN ({db.placeholders(ids)})",
        [user["id"], *ids])}
    out = []
    for r in rows:
        mids = members.get(r["id"], [])
        me = mine.get(r["id"])
        if r["kind"] == "dm":
            others = [u for u in mids if u != user["id"]] or [user["id"]]
            title = ", ".join(users_svc.name_of(u) for u in others)
            if others == [user["id"]]:
                title += " (you)"
        else:
            others = []
            title = r["name"]
        u = unread.get(r["id"], {})
        out.append({
            "id": r["id"], "kind": r["kind"], "name": r["name"], "title": title, "topic": r["topic"],
            "is_private": bool(r["is_private"]), "is_default": bool(r["is_default"]), "archived_at": r["archived_at"],
            "created_by": r["created_by"], "created_at": r["created_at"], "last_message_at": r["last_message_at"],
            "member_ids": mids, "member_count": len(mids), "other_ids": others,
            "is_member": bool(me), "muted": bool(me and me["muted"]), "last_read_at": me["last_read_at"] if me else None,
            "unread": u.get("unread", 0) if me else 0, "mentions": u.get("mentions", 0) if me else 0,
            "last_message": last.get(r["id"]),
        })
    return out


def list_rooms(user: dict) -> list[dict]:
    ensure_defaults(user)
    rows = db.query(
        "SELECT r.* FROM chat_rooms r JOIN chat_members cm ON cm.room_id = r.id AND cm.user_id = ? AND cm.left_at IS NULL "
        "WHERE r.archived_at IS NULL ORDER BY r.kind, COALESCE(r.last_message_at, r.created_at) DESC", user["id"],
    )
    return serialize_rooms(user, rows)


def browse_rooms(user: dict) -> list[dict]:
    rows = db.query(
        "SELECT r.* FROM chat_rooms r WHERE r.kind = 'channel' AND r.is_private = 0 AND r.archived_at IS NULL "
        "ORDER BY r.name COLLATE NOCASE"
    )
    return serialize_rooms(user, rows)


# -- messages -----------------------------------------------------------------------


def _conversation_card(user: dict, cid: int | None) -> dict | None:
    if not cid:
        return None
    conv = inbox.get(cid)
    if not conv or not inbox.can_view(user, cid):
        return {"id": cid, "restricted": True}
    contact = contacts_svc.get(conv["contact_id"]) if conv["contact_id"] else None
    return {
        "id": cid, "subject": inbox.title_of(conv), "status": conv["status"], "preview": conv["preview"],
        "contact": contacts_svc.display_name(contact, "") if contact else None,
        "message_count": conv["message_count"], "url": inbox.link(cid),
    }


def serialize_messages(user: dict, rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    ids = [m["id"] for m in rows]
    atts = files.for_owners("chat_message", ids)
    reacts = reactions.for_targets("chat_message", ids)
    out = []
    for m in rows:
        deleted = bool(m["deleted_at"])
        out.append({
            "id": m["id"], "room_id": m["room_id"], "user_id": m["user_id"],
            "body": DELETED_BODY if deleted else m["body"], "deleted": deleted,
            "mentions": db.jload(m["mentions_json"], []), "parent_id": m["parent_id"],
            "reply_count": m["reply_count"], "last_reply_at": m["last_reply_at"],
            "created_at": m["created_at"], "edited_at": m["edited_at"],
            "attachments": [] if deleted else [files.serialize(a) for a in atts.get(m["id"], [])],
            "reactions": [] if deleted else reacts.get(m["id"], []),
            "conversation": None if deleted else _conversation_card(user, m["conversation_id"]),
            "reply_user_ids": [],
        })
    parents = [o for o in out if o["reply_count"]]
    if parents:
        pids = [o["id"] for o in parents]
        repliers: dict[int, list[int]] = {}
        for r in db.query(
            f"SELECT parent_id, user_id, MAX(id) AS last FROM chat_messages WHERE parent_id IN ({db.placeholders(pids)}) "
            f"AND deleted_at IS NULL GROUP BY parent_id, user_id ORDER BY last DESC", pids,
        ):
            repliers.setdefault(r["parent_id"], []).append(r["user_id"])
        for o in parents:
            o["reply_user_ids"] = repliers.get(o["id"], [])[:5]
    return out


def list_messages(user: dict, room_id: int, before: int | None = None, after: int | None = None,
                  around: int | None = None, limit: int = 50) -> dict:
    room_for(user, room_id)
    limit = max(1, min(limit, 200))
    base = "SELECT * FROM chat_messages WHERE room_id = ? AND parent_id IS NULL"
    if around:
        older = db.query(base + " AND id <= ? ORDER BY id DESC LIMIT ?", room_id, around, limit // 2 + 1)
        newer = db.query(base + " AND id > ? ORDER BY id ASC LIMIT ?", room_id, around, limit // 2)
        rows = list(reversed(older)) + newer
        more_before = bool(older) and db.one(base + " AND id < ? LIMIT 1", room_id, older[-1]["id"]) is not None
        more_after = bool(newer) and db.one(base + " AND id > ? LIMIT 1", room_id, newer[-1]["id"]) is not None
    elif after:
        rows = db.query(base + " AND id > ? ORDER BY id ASC LIMIT ?", room_id, after, limit + 1)
        more_after = len(rows) > limit
        rows = rows[:limit]
        more_before = True
    else:
        params: list = [room_id]
        sql = base
        if before:
            sql += " AND id < ?"
            params.append(before)
        rows = db.query(sql + " ORDER BY id DESC LIMIT ?", [*params, limit + 1])
        more_before = len(rows) > limit
        rows = list(reversed(rows[:limit]))
        more_after = False
    return {"items": serialize_messages(user, rows), "has_more_before": more_before, "has_more_after": more_after}


def thread(user: dict, message_id: int) -> dict:
    parent = db.one("SELECT * FROM chat_messages WHERE id = ?", message_id)
    if not parent:
        not_found("Message not found")
    room_for(user, parent["room_id"])
    if parent["parent_id"]:
        parent = db.one("SELECT * FROM chat_messages WHERE id = ?", parent["parent_id"])
    replies = db.query("SELECT * FROM chat_messages WHERE parent_id = ? ORDER BY id", parent["id"])
    return {"parent": serialize_messages(user, [parent])[0], "replies": serialize_messages(user, replies)}


def get_message_for(user: dict, message_id: int) -> dict:
    m = db.one("SELECT * FROM chat_messages WHERE id = ?", message_id)
    if not m:
        not_found("Message not found")
    room_for(user, m["room_id"])
    return m


def _index(m: dict) -> None:
    search.index("chat", m["id"], None, html_to_text(m["body"]), parent_id=m["room_id"])


def post_message(user: dict, room_id: int, body_html: str, parent_id: int | None = None, attachment_ids=None,
                 conversation_id: int | None = None) -> dict:
    r = room_for(user, room_id)
    if r["archived_at"]:
        bad_request("This channel is archived")
    if not member_row(room_id, user["id"]):
        if r["kind"] == "channel" and not r["is_private"]:
            with db.transaction():
                _add_member(room_id, user["id"])
        else:
            forbidden("You're not in this conversation")
    body = sanitize(body_html or "", "basic")
    if conversation_id:
        if not inbox.get(int(conversation_id)) or not inbox.can_view(user, int(conversation_id)):
            not_found("Conversation not found")
        conversation_id = int(conversation_id)
    if is_blank(body) and not attachment_ids and not conversation_id:
        bad_request("Write something first", code="empty")
    parent = None
    if parent_id:
        parent = db.one("SELECT * FROM chat_messages WHERE id = ? AND room_id = ?", int(parent_id), room_id)
        if not parent:
            bad_request("That thread isn't in this room")
        if parent["parent_id"]:
            parent = db.one("SELECT * FROM chat_messages WHERE id = ?", parent["parent_id"])
    active = set(users_svc.active_ids())
    mentioned = [u for u in mention_ids(body) if u in active and u != user["id"]]
    stamp = now_iso()
    with db.transaction():
        mid = db.insert("chat_messages", {
            "room_id": room_id, "user_id": user["id"], "body": body, "mentions_json": db.jdump(mentioned),
            "parent_id": parent["id"] if parent else None, "conversation_id": conversation_id, "created_at": stamp,
        })
        files.claim(attachment_ids, "chat_message", mid, user["id"])
        if parent:
            db.execute("UPDATE chat_messages SET reply_count = reply_count + 1, last_reply_at = ? WHERE id = ?", stamp, parent["id"])
        else:
            db.execute("UPDATE chat_rooms SET last_message_at = ? WHERE id = ?", stamp, room_id)
        db.execute("UPDATE chat_members SET last_read_at = ? WHERE room_id = ? AND user_id = ?", stamp, room_id, user["id"])
        message = db.one("SELECT * FROM chat_messages WHERE id = ?", mid)
        _index(message)
        _notify(user, r, message, mentioned, parent)
        members = member_ids(room_id)
        realtime.emit("chat.message", {"room_id": room_id, "id": mid, "parent_id": message["parent_id"],
                                       "user_id": user["id"]}, users=members)
        realtime.emit("badges.changed", {}, users=members)
    return message


def _notify(user: dict, r: dict, message: dict, mentioned: list[int], parent: dict | None) -> None:
    room_id = r["id"]
    text = snippet(html_to_text(message["body"]) or ("Sent an attachment" if not message["conversation_id"] else "Shared a conversation"), 140)
    viewing = {v["user_id"] for v in realtime.presence.viewers(f"chat:{room_id}")}
    link = f"/chat/{room_id}?m={message['id']}" + (f"&thread={parent['id']}" if parent else "")
    where = "a direct message" if r["kind"] == "dm" else f"#{r['name']}"
    members = set(member_ids(room_id))
    can_see = members if (r["kind"] == "dm" or r["is_private"]) else set(users_svc.active_ids())
    notified = set()
    targets = [u for u in mentioned if u in can_see]
    if targets:
        notify.notify(targets, "mention", f"{user['name']} mentioned you in {where}", body=text, link=link,
                      actor_id=user["id"], entity_type="chat_room", entity_id=room_id)
        notified |= set(targets)
    muted = set(db.column("SELECT user_id FROM chat_members WHERE room_id = ? AND muted = 1 AND left_at IS NULL", room_id))
    if r["kind"] == "dm":
        others = members - {user["id"]} - notified - viewing - muted
        notify.notify(others, "chat", f"{user['name']}" + ("" if len(members) <= 2 else f" in {where}"), body=text, link=link,
                      actor_id=user["id"], entity_type="chat_room", entity_id=room_id)
    elif parent and parent["user_id"] and parent["user_id"] != user["id"]:
        pid = parent["user_id"]
        if pid not in notified and pid not in viewing and pid not in muted and pid in can_see:
            notify.notify([pid], "chat", f"{user['name']} replied to your message in {where}", body=text, link=link,
                          actor_id=user["id"], entity_type="chat_room", entity_id=room_id)


def edit_message(user: dict, message_id: int, body_html: str) -> dict:
    m = get_message_for(user, message_id)
    if m["user_id"] != user["id"]:
        forbidden("You can only edit your own messages")
    if m["deleted_at"]:
        bad_request("That message was deleted")
    body = sanitize(body_html or "", "basic")
    if is_blank(body) and not files.for_owner("chat_message", message_id) and not m["conversation_id"]:
        bad_request("A message can't be empty", code="empty")
    with db.transaction():
        db.update("chat_messages", message_id, {"body": body, "edited_at": now_iso()})
        m = db.one("SELECT * FROM chat_messages WHERE id = ?", message_id)
        _index(m)
        realtime.emit("chat.message", {"room_id": m["room_id"], "id": message_id, "parent_id": m["parent_id"],
                                       "user_id": user["id"], "edited": True}, users=member_ids(m["room_id"]))
    return m


def delete_message(user: dict, message_id: int) -> None:
    m = get_message_for(user, message_id)
    if m["user_id"] != user["id"] and user["role"] not in ("owner", "admin"):
        forbidden("You can only delete your own messages")
    with db.transaction():
        db.update("chat_messages", message_id, {"deleted_at": now_iso(), "body": DELETED_BODY})
        files.delete_for_owner("chat_message", message_id)
        search.unindex("chat", message_id)
        if m["parent_id"]:
            db.execute("UPDATE chat_messages SET reply_count = MAX(0, reply_count - 1) WHERE id = ?", m["parent_id"])
        realtime.emit("chat.message", {"room_id": m["room_id"], "id": message_id, "parent_id": m["parent_id"],
                                       "user_id": user["id"], "deleted": True}, users=member_ids(m["room_id"]))


def typing(user: dict, room_id: int) -> None:
    room_for(user, room_id)
    others = [u for u in member_ids(room_id) if u != user["id"]]
    realtime.broker.publish("chat.typing", {"room_id": room_id, "user_id": user["id"]}, others)
