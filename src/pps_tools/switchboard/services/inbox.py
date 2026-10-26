"""Conversations: who can see them, where they sit for each person, delivery of
inbound messages, comments, and every action (assign, label, close, snooze, merge...).

Shared vs. personal state
-------------------------
``conversations`` holds what everyone shares: open/closed, team, assignees, labels,
snooze, spam/trash. ``conversation_users`` holds each person's own view: whether it's
in their Inbox, starred, read position, and whether they follow it. Following people
get the conversation back in their Inbox when a new message arrives; you follow what
you've written in, been assigned or been mentioned in.

A team's inbox is computed: open, unsnoozed conversations with that team_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import files, hooks, notify, search, staff_status
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.services.sanitize import is_blank, mention_ids, sanitize
from pps_tools.switchboard.util import (
    html_to_text, iso, norm_iso, normalize_subject, now, now_iso, parse_iso, snippet, text_to_html,
)
from pps_tools.switchboard.web import ApiError, bad_request, can, forbidden, not_found

ADMIN_ROLES = ("owner", "admin")

# Acting user for automation (rules, timers). Actions taken as SYSTEM_USER record no
# person and skip personal state (inbox placement, stars).
SYSTEM_USER = {"id": None, "role": "owner", "name": "Switchboard", "email": "", "prefs_json": "{}"}


# -- visibility ---------------------------------------------------------------------


def visible_channel_ids(user: dict) -> list[int]:
    if not can(user, "inbox"):
        return []
    team_ids = set(users_svc.team_ids_of(user["id"]))
    out = []
    for ch in db.query("SELECT id, visibility, owner_user_id, team_id FROM channels"):
        if ch["visibility"] == "personal":
            if ch["owner_user_id"] == user["id"]:
                out.append(ch["id"])
        elif user["role"] in ADMIN_ROLES or ch["team_id"] is None or ch["team_id"] in team_ids:
            out.append(ch["id"])
    return out


def visibility_clause(user: dict, alias: str = "c") -> tuple[str, list]:
    """SQL condition (and params) for conversations ``user`` may see."""
    parts = [f"EXISTS (SELECT 1 FROM conversation_users vu WHERE vu.conversation_id = {alias}.id AND vu.user_id = ?)"]
    params: list = [user["id"]]
    if can(user, "inbox"):
        if user["role"] in ADMIN_ROLES:
            parts.append(f"{alias}.team_id IS NOT NULL")
        else:
            team_ids = users_svc.team_ids_of(user["id"])
            if team_ids:
                parts.append(f"{alias}.team_id IN ({db.placeholders(team_ids)})")
                params.extend(team_ids)
        channel_ids = visible_channel_ids(user)
        if channel_ids:
            parts.append(f"{alias}.channel_id IN ({db.placeholders(channel_ids)})")
            params.extend(channel_ids)
    return "(" + " OR ".join(parts) + ")", params


def can_view(user: dict, cid: int) -> bool:
    clause, params = visibility_clause(user)
    return db.one(f"SELECT 1 AS ok FROM conversations c WHERE c.id = ? AND {clause}", [cid, *params]) is not None


def get(cid: int) -> dict | None:
    return db.one("SELECT * FROM conversations WHERE id = ?", cid)


def get_for(user: dict, cid: int) -> dict:
    conv = get(cid)
    if not conv or not can_view(user, cid):
        not_found("Conversation not found")
    return conv


def resolve_merged(conv: dict | None) -> dict | None:
    seen = set()
    while conv and conv["merged_into_id"] and conv["id"] not in seen:
        seen.add(conv["id"])
        conv = get(conv["merged_into_id"])
    return conv


def audience(cid: int) -> list[int]:
    """Active users who can see this conversation (who should hear about changes)."""
    conv = get(cid)
    if not conv:
        return []
    ids = set(db.column("SELECT user_id FROM conversation_users WHERE conversation_id = ?", cid))
    inbox_users = set(users_svc.inbox_user_ids())
    admins = set(db.column(
        f"SELECT id FROM users WHERE is_active = 1 AND role IN ({db.placeholders(ADMIN_ROLES)})", list(ADMIN_ROLES)
    ))
    if conv["team_id"]:
        ids |= set(users_svc.team_member_ids(conv["team_id"])) | admins
    channel = db.one("SELECT * FROM channels WHERE id = ?", conv["channel_id"]) if conv["channel_id"] else None
    if channel:
        if channel["visibility"] == "personal":
            ids.add(channel["owner_user_id"])
        elif channel["team_id"]:
            ids |= set(users_svc.team_member_ids(channel["team_id"])) | admins
        else:
            ids |= inbox_users
    active = set(users_svc.active_ids())
    return sorted(ids & active)


def touch(cid: int, reason: str = "updated") -> None:
    """Tell everyone who can see the conversation that it changed."""
    people = audience(cid)
    realtime.emit("conversation.changed", {"id": cid, "reason": reason}, users=people)
    realtime.emit("badges.changed", {}, users=people)


# -- per-person state ---------------------------------------------------------------


def set_user_state(cid: int, uid: int, **fields) -> None:
    db.execute(
        "INSERT INTO conversation_users (conversation_id, user_id, following, in_inbox, starred) "
        "VALUES (?, ?, 0, 0, 0) ON CONFLICT DO NOTHING",
        cid, uid,
    )
    if fields:
        cols = ", ".join(f"{k} = ?" for k in fields)
        db.execute(f"UPDATE conversation_users SET {cols} WHERE conversation_id = ? AND user_id = ?",
                   [*fields.values(), cid, uid])


def user_state(cid: int, uid: int) -> dict:
    row = db.one("SELECT * FROM conversation_users WHERE conversation_id = ? AND user_id = ?", cid, uid)
    return row or {"following": 0, "in_inbox": 0, "starred": 0, "last_read_at": None}


def follow(cid: int, uid: int) -> None:
    set_user_state(cid, uid, following=1)


def mark_read(cid: int, uid: int) -> None:
    set_user_state(cid, uid, last_read_at=now_iso())


def followers(cid: int) -> list[int]:
    return db.column(
        "SELECT cu.user_id FROM conversation_users cu JOIN users u ON u.id = cu.user_id "
        "WHERE cu.conversation_id = ? AND cu.following = 1 AND u.is_active = 1",
        cid,
    )


def assignees(cid: int) -> list[int]:
    return db.column("SELECT user_id FROM conversation_assignees WHERE conversation_id = ? ORDER BY assigned_at", cid)


def add_event(cid: int, type_: str, user_id: int | None = None, data: dict | None = None) -> int:
    return db.insert("conversation_events", {
        "conversation_id": cid, "user_id": user_id, "type": type_,
        "data_json": db.jdump(data or {}), "created_at": now_iso(),
    })


def link(cid: int) -> str:
    return f"/inbox/c/{cid}"


def title_of(conv: dict) -> str:
    if conv.get("subject"):
        return conv["subject"]
    contact = contacts_svc.get(conv.get("contact_id"))
    return contacts_svc.display_name(contact, "Conversation")


# -- delivery -----------------------------------------------------------------------


@dataclass
class Inbound:
    """A message arriving from any channel, already parsed by its adapter."""

    channel: dict
    kind: str                                   # email | sms | whatsapp | chat | api
    from_handle: str | None = None              # email address / phone number
    from_name: str | None = None
    to: list = field(default_factory=list)      # [{"name", "handle"}]
    cc: list = field(default_factory=list)
    reply_to: str | None = None
    subject: str | None = None
    body_text: str | None = None
    body_html: str | None = None                # raw; sanitized here
    external_id: str | None = None
    in_reply_to: str | None = None
    references: list = field(default_factory=list)
    date: str | None = None
    attachments: list = field(default_factory=list)  # [{"filename", "content_type", "data", "content_id", "inline"}]
    thread_key: str | None = None               # sms/whatsapp number, chat visitor token
    headers: dict = field(default_factory=dict)
    is_auto: bool = False                       # auto-replies, bulk mail: never auto-answer these
    is_spam: bool = False
    raw: bytes | None = None                    # original MIME
    contact_id: int | None = None               # known sender (chat visitors)
    conversation_id: int | None = None          # explicit thread (chat visitors)


def _thread_for(msg: Inbound, contact: dict | None) -> dict | None:
    channel = msg.channel
    if msg.conversation_id:
        conv = resolve_merged(get(msg.conversation_id))
        if conv and not conv["deleted_at"]:
            return conv
    if msg.kind == "email":
        refs = [r for r in [msg.in_reply_to, *(msg.references or [])] if r]
        if refs:
            row = db.one(
                f"SELECT conversation_id FROM messages WHERE external_id IN ({db.placeholders(refs)}) "
                f"ORDER BY id DESC LIMIT 1",
                refs,
            )
            if row:
                conv = resolve_merged(get(row["conversation_id"]))
                if conv:
                    return conv
        subject = normalize_subject(msg.subject).lower()
        if contact and len(subject) >= 4:
            recent = db.query(
                "SELECT * FROM conversations WHERE channel_id = ? AND contact_id = ? AND deleted_at IS NULL "
                "AND merged_into_id IS NULL AND last_activity_at >= ? ORDER BY last_activity_at DESC LIMIT 10",
                channel["id"], contact["id"], iso(now() - timedelta(days=7)),
            )
            for conv in recent:
                if normalize_subject(conv["subject"]).lower() == subject:
                    return conv
        return None
    if msg.thread_key:
        conv = db.one(
            "SELECT * FROM conversations WHERE channel_id = ? AND thread_key = ? AND deleted_at IS NULL "
            "AND merged_into_id IS NULL ORDER BY last_activity_at DESC LIMIT 1",
            channel["id"], msg.thread_key,
        )
        if conv and (conv["status"] == "open" or conv["last_activity_at"] >= iso(now() - timedelta(days=30))):
            return conv
    return None


def create_conversation(subject: str | None, channel: dict | None, contact_id: int | None = None,
                        thread_key: str | None = None, created_by: int | None = None,
                        team_id: int | None = None) -> dict:
    stamp = now_iso()
    cid = db.insert("conversations", {
        "subject": (subject or "").strip()[:500] or None,
        "channel_id": channel["id"] if channel else None,
        "team_id": team_id if team_id is not None else (channel["team_id"] if channel else None),
        "contact_id": contact_id,
        "thread_key": thread_key,
        "status": "open",
        "last_activity_at": stamp,
        "created_by": created_by,
        "created_at": stamp,
    })
    hooks.fire("conversation.created", {"conversation_id": cid, "created_by": created_by})
    return get(cid)


def _place_inbound(conv: dict, channel: dict | None) -> None:
    cid = conv["id"]
    if channel and channel["visibility"] == "personal" and channel["owner_user_id"]:
        set_user_state(cid, channel["owner_user_id"], following=1, in_inbox=1)
    db.execute("UPDATE conversation_users SET in_inbox = 1 WHERE conversation_id = ? AND following = 1", cid)
    for uid in assignees(cid):
        set_user_state(cid, uid, in_inbox=1)
    if conv["team_id"]:
        team = db.one("SELECT deliver_to_members FROM teams WHERE id = ?", conv["team_id"])
        if team and team["deliver_to_members"]:
            for uid in users_svc.team_member_ids(conv["team_id"]):
                set_user_state(cid, uid, in_inbox=1)
    elif channel and channel["visibility"] == "shared":
        for uid in users_svc.inbox_user_ids():
            set_user_state(cid, uid, in_inbox=1)


def deliver_inbound(msg: Inbound) -> dict | None:
    """Store an inbound message: dedupe, find or start its conversation, file it into
    the right inboxes, auto-assign, notify. Returns the message row, or None if this
    exact message was already delivered."""
    channel = msg.channel
    with db.transaction():
        if msg.external_id and db.one(
            "SELECT 1 AS dup FROM messages WHERE external_id = ? AND channel_id = ?", msg.external_id, channel["id"]
        ):
            return None
        contact = contacts_svc.get(msg.contact_id) if msg.contact_id else None
        if not contact and msg.from_handle:
            kind = "email" if msg.kind == "email" or "@" in msg.from_handle else "phone"
            contact = contacts_svc.resolve(kind, msg.from_handle, msg.from_name)
        if not contact and msg.kind == "chat" and msg.thread_key:
            # Anonymous website visitor: a contact keyed by their chat session.
            contact = contacts_svc.resolve("chat", msg.thread_key, msg.from_name or "Website visitor")
        conv = _thread_for(msg, contact)
        is_new = conv is None
        if is_new:
            subject = msg.subject if msg.kind in ("email", "api") else None
            conv = create_conversation(subject, channel, contact["id"] if contact else None, msg.thread_key)
        cid = conv["id"]
        stamp = now_iso()
        body_html = sanitize(msg.body_html, "email") if msg.body_html else text_to_html(msg.body_text)
        body_text = msg.body_text if msg.body_text else html_to_text(body_html)
        mid = db.insert("messages", {
            "conversation_id": cid,
            "channel_id": channel["id"],
            "direction": "in",
            "kind": msg.kind,
            "from_name": (msg.from_name or (contact or {}).get("name") or None),
            "from_handle": msg.from_handle,
            "to_json": db.jdump(msg.to or []),
            "cc_json": db.jdump(msg.cc or []),
            "reply_to": msg.reply_to,
            "subject": msg.subject,
            "body_text": body_text,
            "body_html": body_html,
            "snippet": snippet(body_text, 200),
            "external_id": msg.external_id,
            "in_reply_to": msg.in_reply_to,
            "references_json": db.jdump(msg.references or []),
            "contact_id": contact["id"] if contact else None,
            "status": "received",
            "is_auto": 1 if msg.is_auto else 0,
            "headers_json": db.jdump(msg.headers or {}),
            "date": norm_iso(msg.date) or stamp,
            "created_at": stamp,
        })
        for att in msg.attachments or []:
            files.save_bytes(att["data"], att.get("filename") or "attachment", att.get("content_type"),
                             owner_type="message", owner_id=mid, content_id=att.get("content_id"),
                             is_inline=bool(att.get("inline")))
        if msg.raw:
            db.update("messages", mid, {"raw_key": files.store_blob(msg.raw, ".eml")})
        spam = bool(msg.is_spam or (contact and contact["is_blocked"]))
        db.execute(
            "UPDATE conversations SET message_count = message_count + 1, last_message_at = ?, "
            "last_inbound_at = ?, last_activity_at = ?, preview = ?, contact_id = COALESCE(contact_id, ?), "
            "status = 'open', closed_at = NULL, closed_by = NULL, snoozed_until = NULL, snoozed_by = NULL, "
            "deleted_at = NULL, is_spam = CASE WHEN ? THEN 1 ELSE is_spam END WHERE id = ?",
            stamp, stamp, stamp, snippet(body_text, 200), contact["id"] if contact else None, 1 if spam else 0, cid,
        )
        conv = get(cid)
        if not conv["is_spam"]:
            _place_inbound(conv, channel)
            if is_new:
                auto_assign(conv)
            _notify_inbound(conv, mid, contact, msg)
        search.index("message", mid, msg.subject or conv["subject"], body_text, parent_id=cid)
        touch(cid, "message")
        hooks.fire("message.received", {
            "message_id": mid, "conversation_id": cid, "channel_id": channel["id"],
            "is_new_conversation": is_new, "is_auto": bool(msg.is_auto),
        })
        return db.one("SELECT * FROM messages WHERE id = ?", mid)


def _notify_inbound(conv: dict, mid: int, contact: dict | None, msg: Inbound) -> None:
    cid = conv["id"]
    people = set(followers(cid)) | set(assignees(cid))
    channel = msg.channel
    if channel["visibility"] == "personal" and channel["owner_user_id"]:
        people.add(channel["owner_user_id"])
    watching = {v["user_id"] for v in realtime.presence.viewers(f"conversation:{cid}")}
    who = msg.from_name or contacts_svc.display_name(contact, msg.from_handle or "Someone")
    notify.notify(
        people - watching, "message", f"{who}: {conv['subject'] or 'New message'}",
        body=snippet(msg.body_text or html_to_text(msg.body_html), 140),
        link=link(cid), entity_type="conversation", entity_id=cid,
    )


# -- assignment ---------------------------------------------------------------------


def assign(cid: int, user_ids, by: int | None = None, mode: str = "add") -> tuple[list[int], list[int]]:
    """mode: add | set | remove. Returns (added, removed)."""
    current = set(assignees(cid))
    wanted = {int(u) for u in user_ids or []}
    valid = set(users_svc.active_ids())
    wanted &= valid
    if mode == "set":
        target = wanted
    elif mode == "remove":
        target = current - wanted
    else:
        target = current | wanted
    added = sorted(target - current)
    removed = sorted(current - target)
    stamp = now_iso()
    for uid in added:
        db.insert("conversation_assignees", {"conversation_id": cid, "user_id": uid, "assigned_by": by, "assigned_at": stamp})
        set_user_state(cid, uid, following=1, in_inbox=1)
    for uid in removed:
        db.execute("DELETE FROM conversation_assignees WHERE conversation_id = ? AND user_id = ?", cid, uid)
    if added:
        add_event(cid, "assigned", by, {"user_ids": added})
        conv = get(cid)
        actor = users_svc.name_of(by, "Switchboard") if by else "Switchboard"
        notify.notify(added, "assigned", f"{actor} assigned you: {title_of(conv)}",
                      body=conv["preview"], link=link(cid), actor_id=by,
                      entity_type="conversation", entity_id=cid)
        hooks.fire("conversation.assigned", {"conversation_id": cid, "user_ids": added, "by": by})
    if removed:
        add_event(cid, "unassigned", by, {"user_ids": removed})
        hooks.fire("conversation.unassigned", {"conversation_id": cid, "user_ids": removed, "by": by})
    return added, removed


def open_assigned_count(uid: int) -> int:
    return db.scalar(
        "SELECT COUNT(*) FROM conversation_assignees a JOIN conversations c ON c.id = a.conversation_id "
        "WHERE a.user_id = ? AND c.status = 'open' AND c.deleted_at IS NULL AND c.is_spam = 0",
        uid,
    )


def pick_assignee(team_id: int, mode: str, candidates: list[int] | None = None) -> int | None:
    """Choose an owner for a new conversation in this team (or among ``candidates``)."""
    members = [u for u in users_svc.team_member_ids(team_id) if can(users_svc.get(u), "inbox")]
    pool = [u for u in (candidates if candidates is not None else members)]
    if mode == "on_shift":
        working = set(staff_status.on_shift_user_ids())
        pool = [u for u in pool if u in working]
        mode = "round_robin"
    if not pool:
        return None
    if mode == "load_balanced":
        return min(pool, key=lambda u: (open_assigned_count(u), u))
    team = db.one("SELECT rr_last_user_id FROM teams WHERE id = ?", team_id) or {}
    last = team.get("rr_last_user_id")
    ordered = sorted(pool)
    nxt = next((u for u in ordered if last is None or u > last), ordered[0])
    db.execute("UPDATE teams SET rr_last_user_id = ? WHERE id = ?", nxt, team_id)
    return nxt


def auto_assign(conv: dict) -> int | None:
    if not conv["team_id"] or assignees(conv["id"]):
        return None
    team = db.one("SELECT * FROM teams WHERE id = ?", conv["team_id"])
    if not team or team["assignment_mode"] == "manual":
        return None
    uid = pick_assignee(team["id"], team["assignment_mode"])
    if uid:
        assign(conv["id"], [uid], by=None)
    return uid


# -- comments -----------------------------------------------------------------------


def add_comment(user: dict, cid: int, body_html: str, attachment_ids=None) -> dict:
    conv = get_for(user, cid)
    body = sanitize(body_html, "basic")
    if is_blank(body) and not attachment_ids:
        bad_request("Write something first")
    active = set(users_svc.active_ids())
    mentioned = [u for u in mention_ids(body) if u in active and u != user["id"]]
    stamp = now_iso()
    with db.transaction():
        comment_id = db.insert("comments", {
            "conversation_id": cid, "user_id": user["id"], "body": body,
            "mentions_json": db.jdump(mentioned), "created_at": stamp,
        })
        files.claim(attachment_ids, "comment", comment_id, user["id"])
        db.execute("UPDATE conversations SET comment_count = comment_count + 1, last_activity_at = ? WHERE id = ?",
                   stamp, cid)
        set_user_state(cid, user["id"], following=1, last_read_at=stamp)
        text = html_to_text(body)
        for uid in mentioned:
            set_user_state(cid, uid, following=1, in_inbox=1)
        notify.notify(mentioned, "mention", f"{user['name']} mentioned you: {title_of(conv)}",
                      body=snippet(text, 140), link=link(cid), actor_id=user["id"],
                      entity_type="conversation", entity_id=cid)
        others = set(followers(cid)) - set(mentioned) - {user["id"]}
        notify.notify(others, "comment", f"{user['name']} commented: {title_of(conv)}",
                      body=snippet(text, 140), link=link(cid), actor_id=user["id"],
                      entity_type="conversation", entity_id=cid)
        search.index("comment", comment_id, None, text, parent_id=cid)
        touch(cid, "comment")
        hooks.fire("comment.created", {"comment_id": comment_id, "conversation_id": cid, "user_id": user["id"],
                                       "mentions": mentioned})
    return db.one("SELECT * FROM comments WHERE id = ?", comment_id)


def edit_comment(user: dict, comment_id: int, body_html: str) -> dict:
    comment = db.one("SELECT * FROM comments WHERE id = ? AND deleted_at IS NULL", comment_id)
    if not comment:
        not_found("Comment not found")
    if comment["user_id"] != user["id"]:
        forbidden("You can only edit your own comments")
    body = sanitize(body_html, "basic")
    if is_blank(body):
        bad_request("A comment can't be empty")
    with db.transaction():
        db.update("comments", comment_id, {"body": body, "edited_at": now_iso()})
        search.index("comment", comment_id, None, html_to_text(body), parent_id=comment["conversation_id"])
        touch(comment["conversation_id"], "comment")
    return db.one("SELECT * FROM comments WHERE id = ?", comment_id)


def delete_comment(user: dict, comment_id: int) -> None:
    comment = db.one("SELECT * FROM comments WHERE id = ? AND deleted_at IS NULL", comment_id)
    if not comment:
        not_found("Comment not found")
    if comment["user_id"] != user["id"] and user["role"] not in ADMIN_ROLES:
        forbidden("You can only delete your own comments")
    with db.transaction():
        db.update("comments", comment_id, {"deleted_at": now_iso()})
        db.execute("UPDATE conversations SET comment_count = MAX(0, comment_count - 1) WHERE id = ?",
                   comment["conversation_id"])
        search.unindex("comment", comment_id)
        files.delete_for_owner("comment", comment_id)
        touch(comment["conversation_id"], "comment")


# -- actions ------------------------------------------------------------------------

ACTIONS = (
    "close", "reopen", "archive", "move_to_inbox", "star", "unstar", "read", "unread", "snooze", "unsnooze",
    "spam", "not_spam", "trash", "restore", "delete_forever", "assign", "label", "team", "priority",
    "follow", "unfollow", "subject", "merge",
)


def apply_action(user: dict, ids: list[int], action: str, params: dict | None = None) -> list[int]:
    if action not in ACTIONS:
        bad_request(f"Unknown action '{action}'")
    params = params or {}
    ids = [int(i) for i in ids or []]
    if not ids:
        bad_request("Choose at least one conversation")
    if action == "merge":
        if len(ids) < 1 or not params.get("target_id"):
            bad_request("Pick the conversation to merge into")
        target = int(params["target_id"])
        for cid in ids:
            if cid != target:
                merge(user, cid, target)
        return [target]
    done = []
    with db.transaction():
        for cid in ids:
            conv = get_for(user, cid)
            _apply_one(user, conv, action, params)
            done.append(cid)
    return done


def system_action(cid: int, action: str, params: dict | None = None) -> None:
    """Apply an action as automation (rules, timers): no visibility check, no actor."""
    if action in ("merge", "delete_forever"):
        bad_request(f"'{action}' can't be automated")
    conv = get(cid)
    if not conv:
        return
    with db.transaction():
        _apply_one(SYSTEM_USER, conv, action, params or {})


def _apply_one(user: dict, conv: dict, action: str, params: dict) -> None:
    cid = conv["id"]
    uid = user["id"]
    stamp = now_iso()
    reason = action
    if action == "close":
        if conv["status"] != "closed":
            db.update("conversations", cid, {"status": "closed", "closed_at": stamp, "closed_by": uid})
            db.execute("UPDATE conversation_users SET in_inbox = 0 WHERE conversation_id = ?", cid)
            add_event(cid, "closed", uid)
            hooks.fire("conversation.closed", {"conversation_id": cid, "by": uid})
    elif action == "reopen":
        if conv["status"] != "open":
            db.update("conversations", cid, {"status": "open", "closed_at": None, "closed_by": None})
            if uid:
                set_user_state(cid, uid, in_inbox=1, following=1)
            add_event(cid, "reopened", uid)
            hooks.fire("conversation.reopened", {"conversation_id": cid, "by": uid})
    elif action == "archive":
        if uid:
            set_user_state(cid, uid, in_inbox=0)
    elif action == "move_to_inbox":
        if uid:
            set_user_state(cid, uid, in_inbox=1, following=1)
        if conv["status"] == "closed":
            db.update("conversations", cid, {"status": "open", "closed_at": None, "closed_by": None})
            add_event(cid, "reopened", uid)
    elif action in ("star", "unstar"):
        if uid:
            set_user_state(cid, uid, starred=1 if action == "star" else 0)
    elif action == "read":
        if uid:
            mark_read(cid, uid)
    elif action == "unread":
        if uid:
            set_user_state(cid, uid, last_read_at=None)
    elif action == "snooze":
        until = parse_iso(params.get("until"))
        if not until or until <= now():
            bad_request("Snooze until a time in the future")
        db.update("conversations", cid, {"snoozed_until": iso(until), "snoozed_by": uid})
        add_event(cid, "snoozed", uid, {"until": iso(until)})
    elif action == "unsnooze":
        if conv["snoozed_until"]:
            db.update("conversations", cid, {"snoozed_until": None, "snoozed_by": None})
            if uid:
                set_user_state(cid, uid, in_inbox=1)
            add_event(cid, "unsnoozed", uid)
    elif action == "spam":
        db.update("conversations", cid, {"is_spam": 1})
        db.execute("UPDATE conversation_users SET in_inbox = 0 WHERE conversation_id = ?", cid)
        if params.get("block") and conv["contact_id"]:
            db.update("contacts", conv["contact_id"], {"is_blocked": 1})
        add_event(cid, "spam", uid, {"blocked": bool(params.get("block"))})
    elif action == "not_spam":
        db.update("conversations", cid, {"is_spam": 0})
        if uid:
            set_user_state(cid, uid, in_inbox=1)
        if conv["contact_id"]:
            db.update("contacts", conv["contact_id"], {"is_blocked": 0})
        add_event(cid, "not_spam", uid)
    elif action == "trash":
        db.update("conversations", cid, {"deleted_at": stamp})
        db.execute("UPDATE conversation_users SET in_inbox = 0 WHERE conversation_id = ?", cid)
        add_event(cid, "trashed", uid)
    elif action == "restore":
        db.update("conversations", cid, {"deleted_at": None})
        if uid:
            set_user_state(cid, uid, in_inbox=1)
        add_event(cid, "restored", uid)
    elif action == "delete_forever":
        if user["role"] not in ADMIN_ROLES:
            forbidden("Only admins can permanently delete")
        if not conv["deleted_at"]:
            bad_request("Move it to Trash first")
        delete_forever(cid)
        return
    elif action == "assign":
        mode = params.get("mode", "add")
        if mode not in ("add", "set", "remove"):
            bad_request("mode must be add, set or remove")
        assign(cid, params.get("user_ids") or [], by=uid, mode=mode)
    elif action == "label":
        set_labels(user, cid, params.get("add") or [], params.get("remove") or [])
    elif action == "team":
        team_id = params.get("team_id")
        if team_id is not None and not db.one("SELECT id FROM teams WHERE id = ?", team_id):
            bad_request("No such team")
        if team_id != conv["team_id"]:
            db.update("conversations", cid, {"team_id": team_id})
            add_event(cid, "moved_team", uid, {"from": conv["team_id"], "to": team_id})
    elif action == "priority":
        value = params.get("value")
        if value not in ("low", "normal", "high", "urgent"):
            bad_request("Priority must be low, normal, high or urgent")
        db.update("conversations", cid, {"priority": value})
        add_event(cid, "priority", uid, {"value": value})
    elif action == "follow":
        if uid:
            set_user_state(cid, uid, following=1)
    elif action == "unfollow":
        if uid:
            set_user_state(cid, uid, following=0, in_inbox=0)
    elif action == "subject":
        value = (params.get("value") or "").strip()[:500]
        if not value:
            bad_request("Subject can't be empty")
        db.update("conversations", cid, {"subject": value})
        add_event(cid, "renamed", uid, {"from": conv["subject"], "to": value})
        search.index("conversation", cid, value, "", parent_id=cid)
    touch(cid, reason)


def set_labels(user: dict | None, cid: int, add_ids, remove_ids) -> None:
    """Add/remove labels. ``user`` None (or SYSTEM_USER) may only use shared labels."""
    uid = (user or {}).get("id")
    add_ids = [int(i) for i in add_ids]
    remove_ids = [int(i) for i in remove_ids]
    stamp = now_iso()
    added = []
    for lid in add_ids:
        label = db.one("SELECT * FROM labels WHERE id = ?", lid)
        if not label or (label["visibility"] == "personal" and (not uid or label["owner_user_id"] != uid)):
            continue
        cur = db.execute(
            "INSERT OR IGNORE INTO conversation_labels (conversation_id, label_id, added_by, added_at) VALUES (?, ?, ?, ?)",
            cid, lid, uid, stamp,
        )
        if cur.rowcount:
            added.append(lid)
    removed = []
    for lid in remove_ids:
        cur = db.execute("DELETE FROM conversation_labels WHERE conversation_id = ? AND label_id = ?", cid, lid)
        if cur.rowcount:
            removed.append(lid)
    if added:
        add_event(cid, "labeled", uid, {"label_ids": added})
        hooks.fire("conversation.labeled", {"conversation_id": cid, "label_ids": added, "by": uid})
    if removed:
        add_event(cid, "unlabeled", uid, {"label_ids": removed})


def delete_forever(cid: int) -> None:
    for mid in db.column("SELECT id FROM messages WHERE conversation_id = ?", cid):
        files.delete_for_owner("message", mid)
        search.unindex("message", mid)
    for comment_id in db.column("SELECT id FROM comments WHERE conversation_id = ?", cid):
        files.delete_for_owner("comment", comment_id)
        search.unindex("comment", comment_id)
    people = audience(cid)
    db.delete("conversations", cid)
    realtime.emit("conversation.changed", {"id": cid, "reason": "deleted"}, users=people)
    realtime.emit("badges.changed", {}, users=people)


def recompute(cid: int) -> None:
    """Rebuild counters and preview from the conversation's messages and comments."""
    # Scheduled (send-later) messages count, but don't move "last activity" into the future.
    stats = db.one(
        "SELECT COUNT(*) AS n, MAX(CASE WHEN status != 'scheduled' THEN date END) AS last_date, "
        "MAX(CASE WHEN direction = 'in' THEN date END) AS last_in, "
        "MAX(CASE WHEN direction = 'out' AND status NOT IN ('scheduled', 'failed') THEN date END) AS last_out "
        "FROM messages WHERE conversation_id = ? AND status != 'cancelled'",
        cid,
    )
    comments = db.one("SELECT COUNT(*) AS n, MAX(created_at) AS last FROM comments WHERE conversation_id = ? AND deleted_at IS NULL", cid)
    last = db.one("SELECT snippet FROM messages WHERE conversation_id = ? AND status NOT IN ('scheduled', 'cancelled') "
                  "ORDER BY date DESC, id DESC LIMIT 1", cid)
    conv = get(cid)
    activity = max([x for x in (stats["last_date"], comments["last"], conv["created_at"]) if x])
    db.update("conversations", cid, {
        "message_count": stats["n"], "comment_count": comments["n"], "last_message_at": stats["last_date"],
        "last_inbound_at": stats["last_in"], "last_outbound_at": stats["last_out"],
        "last_activity_at": activity, "preview": last["snippet"] if last else conv["preview"],
    })


def merge(user: dict, source_id: int, target_id: int) -> dict:
    if source_id == target_id:
        bad_request("Can't merge a conversation into itself")
    get_for(user, source_id)
    get_for(user, target_id)
    source = get(source_id)
    with db.transaction():
        for table in ("messages", "comments", "conversation_events", "drafts", "reminders", "tasks"):
            db.execute(f"UPDATE {table} SET conversation_id = ? WHERE conversation_id = ?", target_id, source_id)
        db.execute("UPDATE chat_messages SET conversation_id = ? WHERE conversation_id = ?", target_id, source_id)
        db.execute(
            "INSERT OR IGNORE INTO job_conversations (job_id, conversation_id, created_at) "
            "SELECT job_id, ?, created_at FROM job_conversations WHERE conversation_id = ?", target_id, source_id,
        )
        db.execute(
            "INSERT OR IGNORE INTO conversation_labels (conversation_id, label_id, added_by, added_at) "
            "SELECT ?, label_id, added_by, added_at FROM conversation_labels WHERE conversation_id = ?", target_id, source_id,
        )
        db.execute(
            "INSERT OR IGNORE INTO conversation_assignees (conversation_id, user_id, assigned_by, assigned_at) "
            "SELECT ?, user_id, assigned_by, assigned_at FROM conversation_assignees WHERE conversation_id = ?",
            target_id, source_id,
        )
        for row in db.query("SELECT * FROM conversation_users WHERE conversation_id = ?", source_id):
            mine = user_state(target_id, row["user_id"])
            set_user_state(target_id, row["user_id"],
                           following=max(row["following"], mine["following"]),
                           in_inbox=max(row["in_inbox"], mine["in_inbox"]),
                           starred=max(row["starred"], mine["starred"]))
        db.execute(
            "UPDATE search_index SET parent_id = ? WHERE parent_id = ? AND kind IN ('message', 'comment')",
            target_id, source_id,
        )
        recompute(target_id)
        stamp = now_iso()
        db.update("conversations", source_id, {
            "merged_into_id": target_id, "deleted_at": stamp, "message_count": 0, "comment_count": 0,
        })
        db.execute("UPDATE conversation_users SET in_inbox = 0 WHERE conversation_id = ?", source_id)
        add_event(target_id, "merged", user["id"], {"from_id": source_id, "subject": source["subject"]})
        touch(target_id, "merged")
        touch(source_id, "merged")
        hooks.fire("conversation.merged", {"source_id": source_id, "target_id": target_id, "by": user["id"]})
    return get(target_id)


# -- snooze & reminders (worker) ------------------------------------------------------


def wake_snoozed() -> int:
    stamp = now_iso()
    due = db.query("SELECT * FROM conversations WHERE snoozed_until IS NOT NULL AND snoozed_until <= ?", stamp)
    for conv in due:
        with db.transaction():
            cid = conv["id"]
            db.update("conversations", cid, {"snoozed_until": None, "snoozed_by": None, "status": "open",
                                              "closed_at": None, "closed_by": None})
            people = set(assignees(cid))
            if conv["snoozed_by"]:
                people.add(conv["snoozed_by"])
            for uid in people:
                set_user_state(cid, uid, in_inbox=1, following=1)
            add_event(cid, "unsnoozed", None, {"by_timer": True})
            if conv["snoozed_by"]:
                notify.notify([conv["snoozed_by"]], "snooze", f"Back in your inbox: {title_of(conv)}",
                              body=conv["preview"], link=link(cid), entity_type="conversation", entity_id=cid)
            touch(cid, "unsnoozed")
    return len(due)


def add_reminder(user: dict, cid: int, remind_at, condition: str = "always", note: str | None = None) -> dict:
    get_for(user, cid)
    at = parse_iso(remind_at)
    if not at or at <= now():
        bad_request("Pick a time in the future")
    if condition not in ("always", "no_reply"):
        bad_request("condition must be 'always' or 'no_reply'")
    with db.transaction():
        rid = db.insert("reminders", {
            "conversation_id": cid, "user_id": user["id"], "remind_at": iso(at), "condition": condition,
            "note": note, "created_at": now_iso(),
        })
        add_event(cid, "reminder_set", user["id"], {"at": iso(at), "condition": condition})
        touch(cid, "reminder")
    return db.one("SELECT * FROM reminders WHERE id = ?", rid)


def process_reminders() -> int:
    stamp = now_iso()
    due = db.query("SELECT * FROM reminders WHERE done_at IS NULL AND remind_at <= ?", stamp)
    fired = 0
    for r in due:
        with db.transaction():
            db.update("reminders", r["id"], {"done_at": stamp})
            conv = get(r["conversation_id"])
            if not conv or conv["deleted_at"]:
                continue
            if r["condition"] == "no_reply" and conv["last_inbound_at"] and conv["last_inbound_at"] > r["created_at"]:
                continue
            cid = conv["id"]
            set_user_state(cid, r["user_id"], in_inbox=1, following=1)
            if conv["status"] == "closed":
                db.update("conversations", cid, {"status": "open", "closed_at": None, "closed_by": None})
            title = "No reply yet" if r["condition"] == "no_reply" else "Reminder"
            notify.notify([r["user_id"]], "reminder", f"{title}: {title_of(conv)}", body=r["note"] or conv["preview"],
                          link=link(cid), entity_type="conversation", entity_id=cid, include_actor=True)
            add_event(cid, "reminder", r["user_id"], {"condition": r["condition"], "note": r["note"]})
            touch(cid, "reminder")
            fired += 1
    return fired


__all__ = ["Inbound", "deliver_inbound", "apply_action", "add_comment", "ApiError"]
