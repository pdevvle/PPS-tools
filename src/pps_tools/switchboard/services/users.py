"""People and teams lookups used across modules."""

from __future__ import annotations

from pps_tools.switchboard import db
from pps_tools.switchboard.web import PERMISSIONS


def get(user_id: int | None) -> dict | None:
    if not user_id:
        return None
    return db.one("SELECT * FROM users WHERE id = ?", user_id)


def name_of(user_id: int | None, default: str = "Someone") -> str:
    row = db.one("SELECT name FROM users WHERE id = ?", user_id) if user_id else None
    return row["name"] if row else default


def active_ids() -> list[int]:
    return db.column("SELECT id FROM users WHERE is_active = 1 ORDER BY id")


def inbox_user_ids() -> list[int]:
    roles = sorted(PERMISSIONS["inbox"])
    return db.column(
        f"SELECT id FROM users WHERE is_active = 1 AND role IN ({db.placeholders(roles)}) ORDER BY id", roles
    )


def ids_with_perm(perm: str) -> list[int]:
    roles = sorted(PERMISSIONS[perm])
    return db.column(
        f"SELECT id FROM users WHERE is_active = 1 AND role IN ({db.placeholders(roles)}) ORDER BY id", roles
    )


def team_member_ids(team_id: int | None) -> list[int]:
    if not team_id:
        return []
    return db.column(
        "SELECT tm.user_id FROM team_members tm JOIN users u ON u.id = tm.user_id "
        "WHERE tm.team_id = ? AND u.is_active = 1 ORDER BY tm.user_id",
        team_id,
    )


def team_ids_of(user_id: int) -> list[int]:
    return db.column("SELECT team_id FROM team_members WHERE user_id = ?", user_id)


def teams_with_members() -> list[dict]:
    teams = db.query("SELECT * FROM teams ORDER BY name COLLATE NOCASE")
    members = db.query("SELECT team_id, user_id FROM team_members")
    by_team: dict[int, list[int]] = {}
    for m in members:
        by_team.setdefault(m["team_id"], []).append(m["user_id"])
    for t in teams:
        t["member_ids"] = sorted(by_team.get(t["id"], []))
        t["deliver_to_members"] = bool(t["deliver_to_members"])
    return teams
