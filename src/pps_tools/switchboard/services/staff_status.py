"""Who is working right now — used by "assign to whoever is on shift" (team setting and
rule action), the People list and availability badges."""

from __future__ import annotations

from pps_tools.switchboard import db
from pps_tools.switchboard.util import now, now_iso


def on_shift_user_ids(at: str | None = None) -> list[int]:
    """People with a published shift covering ``at`` or who are clocked in now."""
    at = at or now_iso()
    rows = db.column(
        "SELECT DISTINCT user_id FROM shifts WHERE user_id IS NOT NULL AND status = 'published' "
        "AND start_at <= ? AND end_at > ?",
        at, at,
    )
    clocked = db.column("SELECT DISTINCT user_id FROM time_entries WHERE clock_out IS NULL")
    active = set(db.column("SELECT id FROM users WHERE is_active = 1"))
    return sorted((set(rows) | set(clocked)) & active)


def clocked_in_user_ids() -> list[int]:
    return db.column("SELECT DISTINCT user_id FROM time_entries WHERE clock_out IS NULL ORDER BY user_id")


def status_map() -> dict[int, str]:
    """{user_id: 'on_break' | 'clocked_in' | 'on_shift' | 'on_leave'} for everyone who
    isn't simply off right now (absent ids are 'off')."""
    from pps_tools.switchboard.services import settings

    stamp = now_iso()
    today = now().astimezone(settings.timezone()).date().isoformat()
    out: dict[int, str] = {}
    for uid in db.column(
        "SELECT DISTINCT user_id FROM time_off_requests WHERE status = 'approved' AND start_date <= ? AND end_date >= ? "
        "AND (start_time IS NULL OR end_time IS NULL)", today, today,
    ):
        out[uid] = "on_leave"
    for uid in db.column(
        "SELECT DISTINCT user_id FROM shifts WHERE user_id IS NOT NULL AND status = 'published' AND start_at <= ? AND end_at > ?",
        stamp, stamp,
    ):
        out[uid] = "on_shift"
    for e in db.query("SELECT user_id, breaks_json FROM time_entries WHERE clock_out IS NULL"):
        breaks = db.jload(e["breaks_json"], []) or []
        out[e["user_id"]] = "on_break" if breaks and not breaks[-1].get("end") else "clocked_in"
    return out
