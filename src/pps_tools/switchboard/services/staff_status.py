"""Who is working right now — used by "assign to whoever is on shift" (team setting and
rule action) and by availability badges."""

from __future__ import annotations

from pps_tools.switchboard import db
from pps_tools.switchboard.util import now_iso


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
