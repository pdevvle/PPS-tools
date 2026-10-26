"""Emoji reactions on comments, chat messages and job activity."""

from __future__ import annotations

from pps_tools.switchboard import db
from pps_tools.switchboard.realtime import emit
from pps_tools.switchboard.util import now_iso

TARGET_TYPES = ("comment", "chat_message", "job_activity", "message")


def toggle(target_type: str, target_id: int, user_id: int, emoji: str) -> bool:
    """Add the reaction, or remove it if this user already reacted. Returns True if added."""
    existing = db.one(
        "SELECT id FROM reactions WHERE target_type = ? AND target_id = ? AND user_id = ? AND emoji = ?",
        target_type, target_id, user_id, emoji,
    )
    if existing:
        db.delete("reactions", existing["id"])
        added = False
    else:
        db.insert("reactions", {
            "target_type": target_type, "target_id": target_id, "user_id": user_id,
            "emoji": emoji, "created_at": now_iso(),
        })
        added = True
    emit("reaction.changed", {"target_type": target_type, "target_id": target_id,
                              "reactions": for_target(target_type, target_id)})
    return added


def for_target(target_type: str, target_id: int) -> list[dict]:
    return for_targets(target_type, [target_id]).get(target_id, [])


def for_targets(target_type: str, ids: list[int]) -> dict[int, list[dict]]:
    """{target_id: [{"emoji": "👍", "user_ids": [1, 2]}]} in first-reacted order."""
    out: dict[int, list[dict]] = {}
    if not ids:
        return out
    rows = db.query(
        f"SELECT target_id, emoji, user_id FROM reactions WHERE target_type = ? "
        f"AND target_id IN ({db.placeholders(ids)}) ORDER BY id",
        [target_type, *ids],
    )
    for r in rows:
        groups = out.setdefault(r["target_id"], [])
        for g in groups:
            if g["emoji"] == r["emoji"]:
                g["user_ids"].append(r["user_id"])
                break
        else:
            groups.append({"emoji": r["emoji"], "user_ids": [r["user_id"]]})
    return out
