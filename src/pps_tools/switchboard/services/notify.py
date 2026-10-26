"""In-app notifications (the bell), pushed live to the recipient's open tabs; the web
app also raises a desktop notification for them.

Users can mute a type in their preferences: ``prefs.notify[<type>] = false``.
Types: mention, assigned, message, comment, reminder, snooze, task, job, shift,
timeoff, swap, chat, system.
"""

from __future__ import annotations

from typing import Iterable

from pps_tools.switchboard import db
from pps_tools.switchboard.realtime import emit
from pps_tools.switchboard.util import now_iso

TYPES = ("mention", "assigned", "message", "comment", "reminder", "snooze", "task",
         "job", "shift", "timeoff", "swap", "chat", "system")


def notify(
    user_ids: Iterable[int],
    type_: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    actor_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    include_actor: bool = False,
) -> list[int]:
    created = []
    for uid in sorted({u for u in user_ids if u}):
        if uid == actor_id and not include_actor:
            continue
        user = db.one("SELECT is_active, prefs_json FROM users WHERE id = ?", uid)
        if not user or not user["is_active"]:
            continue
        prefs = db.jload(user["prefs_json"], {}) or {}
        if (prefs.get("notify") or {}).get(type_) is False:
            continue
        row = {
            "user_id": uid,
            "type": type_,
            "title": title[:300],
            "body": (body or "")[:500] or None,
            "link": link,
            "actor_id": actor_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "created_at": now_iso(),
            "read_at": None,
        }
        row["id"] = db.insert("notifications", row)
        created.append(row["id"])
        emit("notification", row, users=[uid])
    return created


def mark_read(user_id: int, ids: list[int] | None = None) -> int:
    now = now_iso()
    if ids is None:
        count = db.execute(
            "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL", now, user_id
        ).rowcount
    else:
        count = db.execute(
            f"UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL "
            f"AND id IN ({db.placeholders(ids)})",
            [now, user_id, *ids],
        ).rowcount
    emit("notifications.read", {"ids": ids}, users=[user_id])
    return count


def mark_entity_read(user_id: int, entity_type: str, entity_id: int) -> None:
    """Opening a conversation/job clears its notifications."""
    count = db.execute(
        "UPDATE notifications SET read_at = ? WHERE user_id = ? AND entity_type = ? AND entity_id = ? "
        "AND read_at IS NULL",
        now_iso(), user_id, entity_type, entity_id,
    ).rowcount
    if count:
        emit("notifications.read", {"entity_type": entity_type, "entity_id": entity_id}, users=[user_id])


def unread_count(user_id: int) -> int:
    return db.scalar("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL", user_id)
