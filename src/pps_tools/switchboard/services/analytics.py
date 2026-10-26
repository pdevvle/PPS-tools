"""Reports: inbox responsiveness, team hours and labor cost, job throughput.

Each report covers a range of local dates (org timezone, both ends inclusive) and reads
the module tables directly, so it works with whatever is installed: empty tables give
zeros, never errors. Durations are minutes. Day/hour/week buckets use the org's
timezone and week start, so a message at 11:30 PM lands on the day people saw it.

Conversations from personal channels are left out of inbox reports (they're private).
"""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from pps_tools.switchboard import db
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import settings
from pps_tools.switchboard.util import csv_cell, iso, now, now_iso, parse_date, parse_iso
from pps_tools.switchboard.web import PERMISSIONS, bad_request

MAX_DAYS = 366
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
LATE_GRACE_MINUTES = 5
OT_PREMIUM = 0.5          # overtime is paid at time and a half
DEFAULT_OT_WEEKLY_HOURS = 40
SENT_STATUSES = ("sent", "delivered", "read")


# -- periods & math -----------------------------------------------------------------


@dataclass(frozen=True)
class Period:
    start: date
    end: date            # inclusive
    tz: tzinfo

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.start, time(0), tzinfo=self.tz)

    @property
    def end_dt(self) -> datetime:
        return datetime.combine(self.end + timedelta(days=1), time(0), tzinfo=self.tz)

    @property
    def start_utc(self) -> str:
        return iso(self.start_dt)

    @property
    def end_utc(self) -> str:
        return iso(self.end_dt)

    @property
    def length(self) -> int:
        return (self.end - self.start).days + 1

    def days(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.length)]

    def previous(self) -> Period:
        return Period(self.start - timedelta(days=self.length), self.start - timedelta(days=1), self.tz)

    def local(self, value) -> datetime | None:
        dt = parse_iso(value)
        return dt.astimezone(self.tz) if dt else None

    def day(self, value) -> str | None:
        dt = self.local(value)
        return dt.date().isoformat() if dt else None

    def describe(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "days": self.length,
                "timezone": settings.get("org.timezone"), "week_start": week_start_setting()}


def period_from_args(start: str | None, end: str | None) -> Period:
    """Defaults to the last 30 days ending today (org timezone)."""
    tz = settings.timezone()
    today = now().astimezone(tz).date()
    end_d = parse_date(end) or today
    start_d = parse_date(start) or (end_d - timedelta(days=29))
    if start_d > end_d:
        bad_request("The start date must be before the end date")
    if (end_d - start_d).days >= MAX_DAYS:
        bad_request("Choose a range of at most a year")
    return Period(start_d, end_d, tz)


def week_start_setting() -> int:
    try:
        return 1 if int(settings.get("org.week_start") or 0) == 1 else 0
    except (TypeError, ValueError):
        return 0


def week_start(d: date) -> date:
    """Start of d's week: Sunday (org.week_start 0) or Monday (1)."""
    offset = d.weekday() if week_start_setting() == 1 else (d.weekday() + 1) % 7
    return d - timedelta(days=offset)


def weekday_order() -> list[int]:
    """Python weekday numbers (Mon=0) in display order."""
    return [0, 1, 2, 3, 4, 5, 6] if week_start_setting() == 1 else [6, 0, 1, 2, 3, 4, 5]


def minutes_between(a: datetime | None, b: datetime | None) -> float:
    if a is None or b is None:
        return 0.0
    return (b - a).total_seconds() / 60.0


def percentile(values: list[float], pct: float) -> float | None:
    """Linear interpolation between closest ranks (numpy's default)."""
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return float(ordered[lo])
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _r(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def stats(values: list[float]) -> dict:
    return {
        "count": len(values),
        "median": _r(percentile(values, 50)),
        "average": _r(sum(values) / len(values)) if values else None,
        "p90": _r(percentile(values, 90)),
    }


def day_pieces(start: datetime, end: datetime, tz: tzinfo) -> list[tuple[date, float]]:
    """Split [start, end) at local midnights: [(local date, minutes), ...]."""
    out: list[tuple[date, float]] = []
    if end <= start:
        return out
    cur = start.astimezone(tz)
    stop = end.astimezone(tz)
    while cur < stop:
        nxt = datetime.combine(cur.date() + timedelta(days=1), time(0), tzinfo=tz)
        piece_end = min(nxt, stop)
        out.append((cur.date(), minutes_between(cur, piece_end)))
        cur = piece_end
    return out


def _user_names() -> dict[int, dict]:
    return {u["id"]: u for u in db.query("SELECT id, name, color, title, role, is_active FROM users")}


# -- inbox --------------------------------------------------------------------------


def _conv_filter(team_id: int | None, channel_id: int | None) -> tuple[str, list]:
    parts = [
        "c.is_spam = 0",
        "c.merged_into_id IS NULL",
        "(c.channel_id IS NULL OR c.channel_id NOT IN (SELECT id FROM channels WHERE visibility = 'personal'))",
    ]
    params: list = []
    if team_id:
        parts.append("c.team_id = ?")
        params.append(team_id)
    if channel_id:
        parts.append("c.channel_id = ?")
        params.append(channel_id)
    return " AND ".join(parts), params


def _inbox_core(period: Period, where: str, params: list) -> dict:
    s, e = period.start_utc, period.end_utc
    received = db.query(
        f"SELECT m.created_at, m.channel_id FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        f"WHERE m.direction = 'in' AND m.created_at >= ? AND m.created_at < ? AND {where}",
        [s, e, *params],
    )
    sent = db.query(
        f"SELECT m.sent_at, m.channel_id, m.author_id FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        f"WHERE m.direction = 'out' AND m.status IN ({db.placeholders(SENT_STATUSES)}) AND m.is_auto = 0 "
        f"AND m.sent_at >= ? AND m.sent_at < ? AND {where}",
        [*SENT_STATUSES, s, e, *params],
    )
    created = db.scalar(
        f"SELECT COUNT(*) FROM conversations c WHERE c.created_at >= ? AND c.created_at < ? AND {where}", [s, e, *params]
    )
    comments = db.query(
        f"SELECT cm.user_id FROM comments cm JOIN conversations c ON c.id = cm.conversation_id "
        f"WHERE cm.deleted_at IS NULL AND cm.created_at >= ? AND cm.created_at < ? AND {where}",
        [s, e, *params],
    )
    closed = db.query(
        f"SELECT c.id, c.created_at, c.closed_at, c.closed_by FROM conversations c "
        f"WHERE c.status = 'closed' AND c.closed_at >= ? AND c.closed_at < ? AND {where}",
        [s, e, *params],
    )
    responded = db.query(
        f"SELECT c.id, c.first_response_at, (SELECT MIN(m.created_at) FROM messages m "
        f"WHERE m.conversation_id = c.id AND m.direction = 'in') AS first_in "
        f"FROM conversations c WHERE c.first_response_at >= ? AND c.first_response_at < ? AND {where}",
        [s, e, *params],
    )
    frt: list[tuple[int, float]] = []  # (conversation id, minutes)
    for r in responded:
        if not r["first_in"]:
            continue
        mins = minutes_between(parse_iso(r["first_in"]), parse_iso(r["first_response_at"]))
        if mins >= 0:
            frt.append((r["id"], mins))
    responders: dict[int, int] = {}
    ids = [cid for cid, _ in frt]
    if ids:
        first_in = {r["id"]: r["first_in"] for r in responded}
        for m in db.query(
            f"SELECT conversation_id, author_id, sent_at FROM messages WHERE conversation_id IN ({db.placeholders(ids)}) "
            f"AND direction = 'out' AND sent_at IS NOT NULL AND author_id IS NOT NULL ORDER BY sent_at, id",
            ids,
        ):
            cid = m["conversation_id"]
            if cid not in responders and m["sent_at"] >= (first_in.get(cid) or ""):
                responders[cid] = m["author_id"]
    resolution = [
        mins for mins in (minutes_between(parse_iso(c["created_at"]), parse_iso(c["closed_at"])) for c in closed)
        if mins >= 0
    ]
    return {
        "received": received, "sent": sent, "created": created or 0, "comments": comments, "closed": closed,
        "frt": frt, "responders": responders, "resolution": resolution,
    }


def _inbox_totals(core: dict) -> dict:
    return {
        "conversations": core["created"],
        "received": len(core["received"]),
        "sent": len(core["sent"]),
        "comments": len(core["comments"]),
        "closed": len(core["closed"]),
        "median_first_response": _r(percentile([m for _, m in core["frt"]], 50)),
    }


def _waiting_now(user: dict | None, where: str, params: list, limit: int = 10) -> dict:
    from pps_tools.switchboard.services import inbox as inbox_svc

    clause, vparams = inbox_svc.visibility_clause(user) if user else ("1 = 1", [])
    stamp = now_iso()
    rows = db.query(
        "SELECT c.id, c.subject, c.contact_id, c.priority, c.team_id, c.channel_id, "
        "(SELECT MIN(m.created_at) FROM messages m WHERE m.conversation_id = c.id AND m.direction = 'in' "
        " AND (c.last_outbound_at IS NULL OR m.created_at > c.last_outbound_at)) AS waiting_since "
        "FROM conversations c WHERE c.status = 'open' AND c.deleted_at IS NULL "
        "AND (c.snoozed_until IS NULL OR c.snoozed_until <= ?) AND c.last_inbound_at IS NOT NULL "
        "AND (c.last_outbound_at IS NULL OR c.last_outbound_at < c.last_inbound_at) "
        f"AND {where} AND {clause} ORDER BY waiting_since",
        [stamp, *params, *vparams],
    )
    current = now()
    items = []
    for r in rows[:limit]:
        contact = contacts_svc.get(r["contact_id"])
        assignees = db.column("SELECT user_id FROM conversation_assignees WHERE conversation_id = ?", r["id"])
        since = parse_iso(r["waiting_since"])
        items.append({
            "id": r["id"], "subject": r["subject"], "contact": contacts_svc.display_name(contact, ""),
            "priority": r["priority"], "waiting_since": r["waiting_since"],
            "minutes": _r(minutes_between(since, current), 0) if since else None, "assignee_ids": assignees,
        })
    return {"count": len(rows), "items": items}


def _sla(period: Period, core: dict, where: str, params: list) -> dict | None:
    target = settings.get("inbox.sla_first_response_minutes") or 0
    try:
        target = int(target)
    except (TypeError, ValueError):
        target = 0
    if target <= 0:
        return None
    frt = [m for _, m in core["frt"]]
    late = sum(1 for m in frt if m > target)
    open_rows = db.query(
        "SELECT (SELECT MIN(m.created_at) FROM messages m WHERE m.conversation_id = c.id AND m.direction = 'in') AS first_in "
        "FROM conversations c WHERE c.first_response_at IS NULL AND c.status = 'open' AND c.deleted_at IS NULL "
        f"AND c.last_inbound_at IS NOT NULL AND {where}",
        params,
    )
    current = now()
    waiting_over = 0
    for r in open_rows:
        first_in = parse_iso(r["first_in"])
        if first_in and period.start_dt <= first_in < period.end_dt and minutes_between(first_in, current) > target:
            waiting_over += 1
    within = len(frt) - late
    return {
        "target_minutes": target, "responded": len(frt), "within": within, "late": late, "waiting_over": waiting_over,
        "breaches": late + waiting_over,
        "within_pct": _r(within * 100.0 / len(frt)) if frt else None,
    }


def inbox_report(period: Period, team_id: int | None = None, channel_id: int | None = None,
                 user: dict | None = None) -> dict:
    where, params = _conv_filter(team_id, channel_id)
    core = _inbox_core(period, where, params)
    prev = _inbox_core(period.previous(), where, params)

    daily = {d.isoformat(): {"date": d.isoformat(), "received": 0, "sent": 0, "closed": 0} for d in period.days()}
    for r in core["received"]:
        key = period.day(r["created_at"])
        if key in daily:
            daily[key]["received"] += 1
    for r in core["sent"]:
        key = period.day(r["sent_at"])
        if key in daily:
            daily[key]["sent"] += 1
    for r in core["closed"]:
        key = period.day(r["closed_at"])
        if key in daily:
            daily[key]["closed"] += 1

    order = weekday_order()
    grid = [[0] * 24 for _ in range(7)]
    for r in core["received"]:
        dt = period.local(r["created_at"])
        if dt:
            grid[order.index(dt.weekday())][dt.hour] += 1

    users = _user_names()
    inbox_roles = PERMISSIONS["inbox"]
    agent_ids = {u["id"] for u in users.values() if u["is_active"] and u["role"] in inbox_roles}
    sent_by: dict[int, int] = defaultdict(int)
    for r in core["sent"]:
        if r["author_id"]:
            sent_by[r["author_id"]] += 1
    closed_by: dict[int, int] = defaultdict(int)
    for r in core["closed"]:
        if r["closed_by"]:
            closed_by[r["closed_by"]] += 1
    comments_by: dict[int, int] = defaultdict(int)
    for r in core["comments"]:
        if r["user_id"]:
            comments_by[r["user_id"]] += 1
    frt_by: dict[int, list[float]] = defaultdict(list)
    for cid, mins in core["frt"]:
        uid = core["responders"].get(cid)
        if uid:
            frt_by[uid].append(mins)
    open_assigned = {r["user_id"]: r["n"] for r in db.query(
        f"SELECT a.user_id, COUNT(*) AS n FROM conversation_assignees a JOIN conversations c ON c.id = a.conversation_id "
        f"WHERE c.status = 'open' AND c.deleted_at IS NULL AND {where} GROUP BY a.user_id", params,
    )}
    agent_ids |= set(sent_by) | set(closed_by) | set(frt_by) | set(comments_by)
    agents = []
    for uid in agent_ids:
        u = users.get(uid)
        if not u:
            continue
        agents.append({
            "user_id": uid, "name": u["name"], "color": u["color"],
            "sent": sent_by.get(uid, 0), "closed": closed_by.get(uid, 0), "comments": comments_by.get(uid, 0),
            "first_responses": len(frt_by.get(uid, [])),
            "median_first_response": _r(percentile(frt_by.get(uid, []), 50)),
            "open_assigned": open_assigned.get(uid, 0),
        })
    agents.sort(key=lambda a: (-a["sent"], -a["closed"], a["name"]))

    received_by_channel: dict[int, int] = defaultdict(int)
    for r in core["received"]:
        received_by_channel[r["channel_id"]] += 1
    sent_by_channel: dict[int, int] = defaultdict(int)
    for r in core["sent"]:
        sent_by_channel[r["channel_id"]] += 1
    channel_rows = db.query("SELECT id, name, type FROM channels WHERE visibility = 'shared' ORDER BY name")
    channels = [
        {"channel_id": c["id"], "name": c["name"], "type": c["type"],
         "received": received_by_channel.get(c["id"], 0), "sent": sent_by_channel.get(c["id"], 0)}
        for c in channel_rows if not channel_id or c["id"] == channel_id
    ]
    channels.sort(key=lambda c: (-(c["received"] + c["sent"]), c["name"]))

    labels = db.query(
        "SELECT l.id AS label_id, l.name, l.color, COUNT(DISTINCT c.id) AS conversations "
        "FROM conversation_labels cl JOIN labels l ON l.id = cl.label_id JOIN conversations c ON c.id = cl.conversation_id "
        f"WHERE l.visibility = 'shared' AND c.created_at < ? AND c.last_activity_at >= ? AND {where} "
        "GROUP BY l.id ORDER BY conversations DESC, l.name LIMIT 8",
        [period.end_utc, period.start_utc, *params],
    )

    totals = _inbox_totals(core)
    waiting = _waiting_now(user, where, params)
    totals["waiting"] = waiting["count"]
    return {
        "period": period.describe(),
        "filters": {"team_id": team_id, "channel_id": channel_id},
        "totals": totals,
        "previous": _inbox_totals(prev),
        "daily": list(daily.values()),
        "first_response": stats([m for _, m in core["frt"]]),
        "resolution": stats(core["resolution"]),
        "sla": _sla(period, core, where, params),
        "agents": agents,
        "channels": channels,
        "labels": labels,
        "heatmap": {"weekdays": [WEEKDAYS[i] for i in order], "cells": grid,
                    "max": max((max(row) for row in grid), default=0)},
        "waiting": waiting,
    }


# -- team ---------------------------------------------------------------------------


def _ot_settings() -> tuple[float, float | None]:
    weekly = settings.get("staffing.overtime_weekly_hours", DEFAULT_OT_WEEKLY_HOURS)
    daily = settings.get("staffing.overtime_daily_hours", None)
    try:
        weekly = float(weekly) if weekly not in (None, "") else float(DEFAULT_OT_WEEKLY_HOURS)
    except (TypeError, ValueError):
        weekly = float(DEFAULT_OT_WEEKLY_HOURS)
    try:
        daily = float(daily) if daily not in (None, "", 0) else None
    except (TypeError, ValueError):
        daily = None
    return weekly * 60, (daily * 60 if daily else None)


def _entry_net_pieces(entry: dict, tz, until: datetime) -> list[tuple[date, float]]:
    """Worked minutes of a time entry per local day, breaks spread evenly."""
    start = parse_iso(entry["clock_in"])
    end = parse_iso(entry["clock_out"]) if entry["clock_out"] else until
    if not start or not end or end <= start:
        return []
    total = minutes_between(start, end)
    brk = min(float(entry["break_minutes"] or 0), total)
    factor = (total - brk) / total if total else 0
    return [(d, m * factor) for d, m in day_pieces(start, end, tz)]


def _shift_net_pieces(shift: dict, tz) -> list[tuple[date, float]]:
    start, end = parse_iso(shift["start_at"]), parse_iso(shift["end_at"])
    if not start or not end or end <= start:
        return []
    total = minutes_between(start, end)
    brk = min(float(shift["break_minutes"] or 0), total)
    factor = (total - brk) / total if total else 0
    return [(d, m * factor) for d, m in day_pieces(start, end, tz)]


def _team_core(period: Period) -> dict:
    tz = period.tz
    current = now()

    def in_range(d: date) -> bool:
        return period.start <= d <= period.end

    w0 = week_start(period.start)
    w1 = week_start(period.end) + timedelta(days=7)
    w0_utc = iso(datetime.combine(w0, time(0), tzinfo=tz))
    w1_utc = iso(datetime.combine(w1, time(0), tzinfo=tz))

    users = _user_names()
    profiles = {p["user_id"]: p for p in db.query("SELECT * FROM staff_profiles")}
    positions = {p["id"]: p for p in db.query("SELECT * FROM positions")}

    def rate_of(uid: int, position_id: int | None = None) -> float | None:
        prof = profiles.get(uid) or {}
        if prof.get("hourly_rate") is not None:
            return float(prof["hourly_rate"])
        for pid in (position_id, prof.get("default_position_id")):
            if pid and positions.get(pid) and positions[pid]["default_rate"] is not None:
                return float(positions[pid]["default_rate"])
        return None

    people: dict[int, dict] = {}

    def person(uid: int) -> dict:
        if uid not in people:
            u = users.get(uid) or {"name": "Unknown", "color": None, "title": None}
            people[uid] = {
                "user_id": uid, "name": u["name"], "color": u["color"], "title": u.get("title"),
                "scheduled_minutes": 0.0, "worked_minutes": 0.0, "overtime_minutes": 0.0,
                "scheduled_cost": 0.0, "labor_cost": 0.0, "late": 0, "timeoff_days": 0.0,
                "rate": rate_of(uid), "shifts": 0,
            }
        return people[uid]

    daily = {d: {"date": d.isoformat(), "scheduled_minutes": 0.0, "worked_minutes": 0.0} for d in period.days()}
    by_position: dict[int | None, dict] = {}

    def pos_row(pid: int | None) -> dict:
        if pid not in by_position:
            p = positions.get(pid) if pid else None
            by_position[pid] = {"position_id": pid, "name": p["name"] if p else "No position",
                                "color": p["color"] if p else None,
                                "scheduled_minutes": 0.0, "worked_minutes": 0.0, "labor_cost": 0.0}
        return by_position[pid]

    shifts = db.query(
        "SELECT * FROM shifts WHERE user_id IS NOT NULL AND status = 'published' AND start_at < ? AND end_at > ?",
        iso(period.end_dt), iso(period.start_dt - timedelta(days=1)),
    )
    for sh in shifts:
        mins = sum(m for d, m in _shift_net_pieces(sh, tz) if in_range(d))
        if mins <= 0:
            continue
        p = person(sh["user_id"])
        p["shifts"] += 1
        p["scheduled_minutes"] += mins
        rate = rate_of(sh["user_id"], sh["position_id"])
        if rate is not None:
            p["scheduled_cost"] += rate * mins / 60
        pos_row(sh["position_id"])["scheduled_minutes"] += mins
        for d, m in _shift_net_pieces(sh, tz):
            if in_range(d):
                daily[d]["scheduled_minutes"] += m

    entries = db.query(
        "SELECT e.*, s.position_id AS shift_position_id FROM time_entries e LEFT JOIN shifts s ON s.id = e.shift_id "
        "WHERE e.clock_in < ? AND (e.clock_out IS NULL OR e.clock_out > ?)",
        w1_utc, w0_utc,
    )
    weekly_ot, daily_ot = _ot_settings()
    week_minutes: dict[tuple[int, date], float] = defaultdict(float)
    day_minutes: dict[tuple[int, date], float] = defaultdict(float)
    for en in entries:
        pieces = _entry_net_pieces(en, tz, current)
        uid = en["user_id"]
        for d, m in pieces:
            week_minutes[(uid, week_start(d))] += m
            day_minutes[(uid, d)] += m
        mins = sum(m for d, m in pieces if in_range(d))
        if mins <= 0:
            continue
        p = person(uid)
        p["worked_minutes"] += mins
        pid = en["shift_position_id"] or (profiles.get(uid) or {}).get("default_position_id")
        row = pos_row(pid)
        row["worked_minutes"] += mins
        rate = rate_of(uid, pid)
        if rate is not None:
            p["labor_cost"] += rate * mins / 60
            row["labor_cost"] += rate * mins / 60
        for d, m in pieces:
            if in_range(d):
                daily[d]["worked_minutes"] += m

    # Overtime is a property of whole weeks: count every week that overlaps the range,
    # under the weekly rule or (when set) the daily rule, whichever pays more.
    first_wk, last_wk = week_start(period.start), week_start(period.end)
    weekly_rule: dict[int, dict[date, float]] = defaultdict(dict)
    daily_rule: dict[int, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for (uid, wk), mins in week_minutes.items():
        if first_wk <= wk <= last_wk:
            weekly_rule[uid][wk] = max(0.0, mins - weekly_ot)
    if daily_ot:
        for (uid, d), mins in day_minutes.items():
            if first_wk <= week_start(d) <= last_wk:
                daily_rule[uid][week_start(d)] += max(0.0, mins - daily_ot)
    for uid in set(weekly_rule) | set(daily_rule):
        wks = set(weekly_rule[uid]) | set(daily_rule[uid])
        ot = sum(max(weekly_rule[uid].get(wk, 0.0), daily_rule[uid].get(wk, 0.0)) for wk in wks)
        if ot > 0:
            p = person(uid)
            p["overtime_minutes"] += ot
            if p["rate"] is not None:
                p["labor_cost"] += OT_PREMIUM * p["rate"] * ot / 60

    # Late clock-ins: the first punch for each shift (the linked one, else the shift it
    # falls in) against the shift's start. Later punches that day are back-from-break or
    # job switches, not late arrivals.
    late_items = []
    nearby = defaultdict(list)
    for sh in db.query(
        "SELECT * FROM shifts WHERE user_id IS NOT NULL AND status = 'published' AND start_at < ? AND end_at > ?",
        iso(period.end_dt + timedelta(hours=2)), iso(period.start_dt - timedelta(hours=12)),
    ):
        nearby[sh["user_id"]].append(sh)
    shift_by_id = {sh["id"]: sh for lst in nearby.values() for sh in lst}
    first_punch: dict[tuple[int, int], tuple[datetime, dict, dict]] = {}
    for en in entries:
        clock_in = parse_iso(en["clock_in"])
        if not clock_in:
            continue
        shift = shift_by_id.get(en["shift_id"]) if en["shift_id"] else None
        if shift is None:
            candidates = [
                sh for sh in nearby.get(en["user_id"], [])
                if parse_iso(sh["start_at"]) - timedelta(hours=2) <= clock_in < parse_iso(sh["end_at"])
            ]
            shift = min(candidates, key=lambda sh: abs(minutes_between(parse_iso(sh["start_at"]), clock_in)), default=None)
        if not shift:
            continue
        key = (en["user_id"], shift["id"])
        if key not in first_punch or clock_in < first_punch[key][0]:
            first_punch[key] = (clock_in, en, shift)
    for clock_in, en, shift in first_punch.values():
        if not (period.start_dt <= clock_in < period.end_dt):
            continue
        late_by = minutes_between(parse_iso(shift["start_at"]), clock_in)
        if late_by > LATE_GRACE_MINUTES:
            p = person(en["user_id"])
            p["late"] += 1
            late_items.append({"user_id": en["user_id"], "name": p["name"], "shift_start": shift["start_at"],
                               "clock_in": en["clock_in"], "minutes_late": _r(late_by, 0)})
    late_items.sort(key=lambda x: x["clock_in"], reverse=True)

    for r in db.query(
        "SELECT * FROM time_off_requests WHERE status = 'approved' AND start_date <= ? AND end_date >= ?",
        period.end.isoformat(), period.start.isoformat(),
    ):
        s, e = parse_date(r["start_date"]), parse_date(r["end_date"])
        if not s or not e or e < s:
            continue
        first, last = max(s, period.start), min(e, period.end)
        overlap = (last - first).days + 1
        total = (e - s).days + 1
        if r["hours"]:
            days = float(r["hours"]) / 8 * overlap / total
        elif r["start_time"] and r["end_time"]:
            h1, m1 = (int(x) for x in r["start_time"].split(":")[:2])
            h2, m2 = (int(x) for x in r["end_time"].split(":")[:2])
            days = min(1.0, max(0.0, ((h2 * 60 + m2) - (h1 * 60 + m1)) / 480)) * overlap
        else:
            days = float(overlap)
        person(r["user_id"])["timeoff_days"] += days

    for uid, prof in profiles.items():
        u = users.get(uid)
        if u and u["is_active"] and prof.get("is_schedulable", 1):
            person(uid)

    rows = []
    for p in people.values():
        rows.append({
            **p,
            "scheduled_minutes": _r(p["scheduled_minutes"], 0),
            "worked_minutes": _r(p["worked_minutes"], 0),
            "overtime_minutes": _r(p["overtime_minutes"], 0),
            "scheduled_cost": _r(p["scheduled_cost"], 2) if p["rate"] is not None else None,
            "labor_cost": _r(p["labor_cost"], 2) if p["rate"] is not None else None,
            "timeoff_days": _r(p["timeoff_days"], 1),
            "variance_minutes": _r(p["worked_minutes"] - p["scheduled_minutes"], 0),
        })
    rows.sort(key=lambda p: (-(p["worked_minutes"] or 0), -(p["scheduled_minutes"] or 0), p["name"]))
    positions_out = sorted(
        ({**v, "scheduled_minutes": _r(v["scheduled_minutes"], 0), "worked_minutes": _r(v["worked_minutes"], 0),
          "labor_cost": _r(v["labor_cost"], 2)} for v in by_position.values()),
        key=lambda v: (-(v["worked_minutes"] or 0), -(v["scheduled_minutes"] or 0), v["name"]),
    )
    totals = {
        "people": sum(1 for p in rows if (p["worked_minutes"] or 0) > 0 or (p["scheduled_minutes"] or 0) > 0),
        "scheduled_minutes": _r(sum(p["scheduled_minutes"] or 0 for p in rows), 0),
        "worked_minutes": _r(sum(p["worked_minutes"] or 0 for p in rows), 0),
        "overtime_minutes": _r(sum(p["overtime_minutes"] or 0 for p in rows), 0),
        "labor_cost": _r(sum(p["labor_cost"] or 0 for p in rows), 2),
        "scheduled_cost": _r(sum(p["scheduled_cost"] or 0 for p in rows), 2),
        "late": sum(p["late"] for p in rows),
        "timeoff_days": _r(sum(p["timeoff_days"] or 0 for p in rows), 1),
        "missing_rates": sum(1 for p in rows if p["rate"] is None and ((p["worked_minutes"] or 0) > 0)),
    }
    return {
        "totals": totals,
        "people": rows,
        "positions": positions_out,
        "daily": [{**v, "scheduled_minutes": _r(v["scheduled_minutes"], 0), "worked_minutes": _r(v["worked_minutes"], 0)}
                  for v in daily.values()],
        "late": late_items[:25],
        "overtime_rule": {"weekly_hours": weekly_ot / 60, "daily_hours": (daily_ot / 60) if daily_ot else None},
    }


def team_report(period: Period) -> dict:
    core = _team_core(period)
    prev = _team_core(period.previous())["totals"]
    return {
        "period": period.describe(),
        **core,
        "previous": {k: prev[k] for k in ("scheduled_minutes", "worked_minutes", "overtime_minutes", "labor_cost", "late")},
    }


# -- jobs ---------------------------------------------------------------------------


def _stage_ids(data: dict) -> tuple[int | None, int | None]:
    """Stage ids from a stage_changed activity (accepts the shapes modules use)."""
    for a, b in (("from_id", "to_id"), ("from_stage_id", "to_stage_id"), ("from", "to")):
        if a in data or b in data:
            fa, fb = data.get(a), data.get(b)
            fa = fa if isinstance(fa, int) else None
            fb = fb if isinstance(fb, int) else None
            if fa is not None or fb is not None:
                return fa, fb
    return None, None


def _job_minutes(entries: list[dict], current: datetime) -> float:
    total = 0.0
    for en in entries:
        start = parse_iso(en["clock_in"])
        end = parse_iso(en["clock_out"]) if en["clock_out"] else current
        if start and end and end > start:
            total += max(0.0, minutes_between(start, end) - float(en["break_minutes"] or 0))
    return total


def _on_time(job: dict) -> bool:
    done, due = parse_iso(job["completed_at"]), parse_iso(job["due_at"])
    return bool(done and due and done <= due)


def _jobs_totals(period: Period) -> dict:
    s, e = period.start_utc, period.end_utc
    created = db.scalar("SELECT COUNT(*) FROM jobs WHERE created_at >= ? AND created_at < ?", s, e) or 0
    completed = db.query("SELECT due_at, completed_at, quote_amount FROM jobs WHERE completed_at >= ? AND completed_at < ?", s, e)
    with_due = [j for j in completed if j["due_at"]]
    on_time = sum(1 for j in with_due if _on_time(j))
    return {
        "created": created,
        "completed": len(completed),
        "revenue": _r(sum(float(j["quote_amount"] or 0) for j in completed), 2),
        "on_time_pct": _r(on_time * 100.0 / len(with_due)) if with_due else None,
    }


def jobs_report(period: Period) -> dict:
    s, e = period.start_utc, period.end_utc
    current = now()
    stamp = now_iso()
    stages = db.query("SELECT * FROM job_stages ORDER BY position, id")
    stage_by_id = {st["id"]: st for st in stages}

    created = db.query("SELECT id, created_at FROM jobs WHERE created_at >= ? AND created_at < ?", s, e)
    completed = db.query(
        "SELECT id, number, title, created_at, completed_at, due_at, quote_amount FROM jobs "
        "WHERE completed_at >= ? AND completed_at < ?", s, e,
    )

    weeks: dict[date, dict] = {}
    wk = week_start(period.start)
    while wk <= period.end:
        weeks[wk] = {"week_start": wk.isoformat(), "created": 0, "completed": 0}
        wk += timedelta(days=7)
    for j in created:
        d = period.local(j["created_at"])
        if d and week_start(d.date()) in weeks:
            weeks[week_start(d.date())]["created"] += 1
    for j in completed:
        d = period.local(j["completed_at"])
        if d and week_start(d.date()) in weeks:
            weeks[week_start(d.date())]["completed"] += 1

    with_due = [j for j in completed if j["due_at"]]
    on_time = sum(1 for j in with_due if _on_time(j))
    cycle = [m for m in (minutes_between(parse_iso(j["created_at"]), parse_iso(j["completed_at"])) for j in completed) if m >= 0]

    open_rows = db.query(
        "SELECT stage_id, COUNT(*) AS n, SUM(CASE WHEN due_at IS NOT NULL AND due_at < ? THEN 1 ELSE 0 END) AS overdue "
        "FROM jobs WHERE archived_at IS NULL GROUP BY stage_id", stamp,
    )
    counts = {r["stage_id"]: r for r in open_rows}
    wip = []
    for st in stages:
        if st["is_done"]:
            continue
        r = counts.get(st["id"]) or {"n": 0, "overdue": 0}
        wip.append({"stage_id": st["id"], "name": st["name"], "color": st["color"], "jobs": r["n"],
                    "overdue": r["overdue"] or 0, "wip_limit": st["wip_limit"]})
    if None in counts:
        wip.append({"stage_id": None, "name": "No stage", "color": None, "jobs": counts[None]["n"],
                    "overdue": counts[None]["overdue"] or 0, "wip_limit": None})
    open_total = sum(w["jobs"] for w in wip)
    overdue_total = sum(w["overdue"] for w in wip)

    # Time in stage: from each stage_changed activity back to when the job entered the stage.
    activity = db.query(
        "SELECT a.job_id, a.data_json, a.created_at, j.created_at AS job_created FROM job_activity a "
        "JOIN jobs j ON j.id = a.job_id WHERE a.type = 'stage_changed' ORDER BY a.job_id, a.created_at, a.id"
    )
    in_stage: dict[int, list[float]] = defaultdict(list)
    last_job = None
    entered = None
    for a in activity:
        if a["job_id"] != last_job:
            last_job = a["job_id"]
            entered = a["job_created"]
        from_id, _to_id = _stage_ids(db.jload(a["data_json"], {}) or {})
        if from_id is not None and entered:
            mins = minutes_between(parse_iso(entered), parse_iso(a["created_at"]))
            if mins >= 0 and s <= a["created_at"] < e:
                in_stage[from_id].append(mins)
        entered = a["created_at"]
    time_in_stage = [
        {"stage_id": st["id"], "name": st["name"], "color": st["color"], "transitions": len(in_stage[st["id"]]),
         "average_minutes": _r(sum(in_stage[st["id"]]) / len(in_stage[st["id"]]), 0) if in_stage[st["id"]] else None,
         "median_minutes": _r(percentile(in_stage[st["id"]], 50), 0)}
        for st in stages if in_stage.get(st["id"])
    ]

    # Estimated vs actual hours on jobs finished in the range or worked on in it.
    worked_ids = set(db.column(
        "SELECT DISTINCT job_id FROM time_entries WHERE job_id IS NOT NULL AND clock_in < ? "
        "AND (clock_out IS NULL OR clock_out > ?)", e, s,
    ))
    job_ids = sorted(worked_ids | {j["id"] for j in completed})
    hours = []
    if job_ids:
        ph = db.placeholders(job_ids)
        info = {j["id"]: j for j in db.query(f"SELECT id, number, title, estimated_minutes, stage_id FROM jobs WHERE id IN ({ph})", job_ids)}
        est_ops = {r["job_id"]: r["m"] for r in db.query(
            f"SELECT job_id, SUM(duration_minutes) AS m FROM job_operations WHERE job_id IN ({ph}) GROUP BY job_id", job_ids)}
        entries_by_job: dict[int, list[dict]] = defaultdict(list)
        for en in db.query(f"SELECT job_id, clock_in, clock_out, break_minutes FROM time_entries WHERE job_id IN ({ph})", job_ids):
            entries_by_job[en["job_id"]].append(en)
        for jid in job_ids:
            j = info.get(jid)
            if not j:
                continue
            estimated = est_ops.get(jid) or j["estimated_minutes"]
            actual = _job_minutes(entries_by_job.get(jid, []), current)
            hours.append({
                "job_id": jid, "number": j["number"], "title": j["title"],
                "stage": (stage_by_id.get(j["stage_id"]) or {}).get("name"),
                "estimated_minutes": _r(estimated, 0) if estimated else None,
                "actual_minutes": _r(actual, 0),
                "variance_pct": _r((actual - estimated) * 100.0 / estimated) if estimated and actual else None,
            })
        hours.sort(key=lambda h: (-(h["actual_minutes"] or 0), h["number"]))
    both = [h for h in hours if h["estimated_minutes"] and h["actual_minutes"]]

    customers: dict[tuple, dict] = {}
    for j in db.query(
        "SELECT j.id, j.quote_amount, j.completed_at, j.organization_id, j.contact_id, o.name AS org_name "
        "FROM jobs j LEFT JOIN organizations o ON o.id = j.organization_id WHERE j.created_at >= ? AND j.created_at < ?", s, e,
    ):
        if j["organization_id"]:
            key, name = ("org", j["organization_id"]), j["org_name"]
        elif j["contact_id"]:
            key, name = ("contact", j["contact_id"]), contacts_svc.display_name(contacts_svc.get(j["contact_id"]), "Unknown")
        else:
            key, name = ("none", 0), "No customer"
        row = customers.setdefault(key, {"kind": key[0], "id": key[1] or None, "name": name, "jobs": 0,
                                         "completed": 0, "quoted": 0.0})
        row["jobs"] += 1
        row["completed"] += 1 if j["completed_at"] else 0
        row["quoted"] += float(j["quote_amount"] or 0)
    top_customers = sorted(customers.values(), key=lambda c: (-c["quoted"], -c["jobs"], c["name"] or ""))[:10]
    for c in top_customers:
        c["quoted"] = _r(c["quoted"], 2)

    totals = {
        **_jobs_totals(period),
        "on_time": on_time,
        "with_due": len(with_due),
        "average_cycle_minutes": _r(sum(cycle) / len(cycle), 0) if cycle else None,
        "median_cycle_minutes": _r(percentile(cycle, 50), 0),
        "open": open_total,
        "overdue": overdue_total,
        "estimated_minutes": _r(sum(h["estimated_minutes"] for h in both), 0) if both else None,
        "actual_minutes": _r(sum(h["actual_minutes"] for h in both), 0) if both else None,
    }
    return {
        "period": period.describe(),
        "totals": totals,
        "previous": _jobs_totals(period.previous()),
        "weekly": list(weeks.values()),
        "wip": wip,
        "time_in_stage": time_in_stage,
        "hours": hours[:25],
        "customers": top_customers,
    }


# -- CSV ------------------------------------------------------------------------------


def _hours(minutes) -> float | None:
    return None if minutes is None else round(minutes / 60.0, 2)


TABLES = {
    "inbox": {
        "daily": (["Date", "Received", "Sent", "Closed"],
                  lambda d: [[r["date"], r["received"], r["sent"], r["closed"]] for r in d["daily"]]),
        "agents": (["Teammate", "Replies sent", "Closed", "Comments", "First responses", "Median first response (min)",
                    "Open assigned now"],
                   lambda d: [[a["name"], a["sent"], a["closed"], a["comments"], a["first_responses"],
                               a["median_first_response"], a["open_assigned"]] for a in d["agents"]]),
        "channels": (["Channel", "Type", "Received", "Sent"],
                     lambda d: [[c["name"], c["type"], c["received"], c["sent"]] for c in d["channels"]]),
        "labels": (["Label", "Conversations"], lambda d: [[lbl["name"], lbl["conversations"]] for lbl in d["labels"]]),
        "hours": (["Weekday", "Hour", "Messages received"],
                  lambda d: [[d["heatmap"]["weekdays"][i], h, d["heatmap"]["cells"][i][h]]
                             for i in range(7) for h in range(24)]),
        "waiting": (["Conversation", "Customer", "Waiting since", "Minutes waiting"],
                    lambda d: [[w["subject"] or "", w["contact"], w["waiting_since"], w["minutes"]] for w in d["waiting"]["items"]]),
    },
    "team": {
        "people": (["Person", "Shifts", "Scheduled hours", "Worked hours", "Overtime hours", "Labor cost",
                    "Late clock-ins", "Time off (days)"],
                   lambda d: [[p["name"], p["shifts"], _hours(p["scheduled_minutes"]), _hours(p["worked_minutes"]),
                               _hours(p["overtime_minutes"]), p["labor_cost"], p["late"], p["timeoff_days"]]
                              for p in d["people"]]),
        "daily": (["Date", "Scheduled hours", "Worked hours"],
                  lambda d: [[r["date"], _hours(r["scheduled_minutes"]), _hours(r["worked_minutes"])] for r in d["daily"]]),
        "positions": (["Position", "Scheduled hours", "Worked hours", "Labor cost"],
                      lambda d: [[p["name"], _hours(p["scheduled_minutes"]), _hours(p["worked_minutes"]), p["labor_cost"]]
                                 for p in d["positions"]]),
        "late": (["Person", "Shift start", "Clocked in", "Minutes late"],
                 lambda d: [[x["name"], x["shift_start"], x["clock_in"], x["minutes_late"]] for x in d["late"]]),
    },
    "jobs": {
        "weekly": (["Week starting", "Created", "Completed"],
                   lambda d: [[w["week_start"], w["created"], w["completed"]] for w in d["weekly"]]),
        "wip": (["Stage", "Open jobs", "Overdue", "WIP limit"],
                lambda d: [[w["name"], w["jobs"], w["overdue"], w["wip_limit"]] for w in d["wip"]]),
        "stages": (["Stage", "Moves out", "Average hours in stage", "Median hours in stage"],
                   lambda d: [[t["name"], t["transitions"], _hours(t["average_minutes"]), _hours(t["median_minutes"])]
                              for t in d["time_in_stage"]]),
        "hours": (["Job", "Title", "Stage", "Estimated hours", "Actual hours", "Variance %"],
                  lambda d: [[h["number"], h["title"], h["stage"], _hours(h["estimated_minutes"]), _hours(h["actual_minutes"]),
                              h["variance_pct"]] for h in d["hours"]]),
        "customers": (["Customer", "Jobs", "Completed", "Quoted value"],
                      lambda d: [[c["name"], c["jobs"], c["completed"], c["quoted"]] for c in d["customers"]]),
    },
}


def to_csv(report: str, table: str, data: dict) -> str:
    headers, rows = TABLES[report][table]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows(data):
        writer.writerow([csv_cell(v) for v in row])
    return buf.getvalue()
