"""Staffing logic: the shop's local days and weeks, shift conflicts, weekly totals,
time-clock math, overtime splitting for timesheets, pay periods, and the workflows
for publishing schedules and handling swap / drop / pickup requests.

All "day" and "week" math happens in the organization's timezone (org.timezone) and
weeks start on org.week_start (0 = Sunday, 1 = Monday). Instants stay UTC in the
database; shift times shown and entered in the app are local wall-clock times.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.services import hooks, notify, settings
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.util import first_name, iso, local_to_utc_iso, now, now_iso, parse_date, parse_iso
from pps_tools.switchboard.web import bad_request, can, conflict, forbidden, not_found

settings.register_defaults({
    "staffing.overtime_weekly_hours": 40,
    "staffing.overtime_daily_hours": None,
    "staffing.min_rest_hours": 10,
    "staffing.max_shift_hours": 12,
    "staffing.pickup_requires_approval": True,
    "staffing.swap_requires_approval": True,
    "staffing.pay_period": "weekly",            # weekly | biweekly
    "staffing.pay_period_anchor": "2026-01-04",  # first day of any biweekly period
    "staffing.shift_reminder_minutes": 60,
    "staffing.clock_rounding_minutes": 0,
    "staffing.early_clock_in_minutes": 15,
    "staffing.auto_clock_out_hours": 14,
})

WEEKDAY_NAMES = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]
TIME_OFF_KINDS = ("vacation", "sick", "personal", "unpaid", "other")
EMPLOYMENT_TYPES = ("full_time", "part_time", "contractor", "seasonal")


# -- local time -----------------------------------------------------------------------


def tz():
    return settings.timezone()


def week_start(d: date) -> date:
    """First day of the org week containing ``d``."""
    if int(settings.get("org.week_start") or 0) == 1:
        offset = d.weekday()               # Monday start
    else:
        offset = (d.weekday() + 1) % 7     # Sunday start
    return d - timedelta(days=offset)


def local_dt(value) -> datetime:
    return parse_iso(value).astimezone(tz())


def local_date(value) -> date:
    return local_dt(value).date()


def today() -> date:
    return now().astimezone(tz()).date()


def day_start(d: date) -> str:
    """Instant of local midnight starting ``d``."""
    return local_to_utc_iso(d, "00:00", tz())


def hhmm_to_minutes(value: str | None) -> int:
    if not value:
        return 0
    h, m = (int(x) for x in str(value).split(":")[:2])
    return h * 60 + m


def valid_hhmm(value) -> bool:
    try:
        h, m = (int(x) for x in str(value).split(":")[:2])
    except (TypeError, ValueError):
        return False
    return 0 <= m < 60 and (0 <= h < 24 or (h == 24 and m == 0))


def fmt_time(value: str | datetime) -> str:
    """'9:30 AM' / '9 AM' in local time, for notification text."""
    dt = local_dt(value) if not isinstance(value, datetime) else value
    hour = dt.hour % 12 or 12
    suffix = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{dt.minute:02d} {suffix}" if dt.minute else f"{hour} {suffix}"


def fmt_hhmm(value: str) -> str:
    minutes = hhmm_to_minutes(value)
    h, m = divmod(minutes % 1440, 60)
    hour = h % 12 or 12
    suffix = "AM" if h < 12 else "PM"
    return f"{hour}:{m:02d} {suffix}" if m else f"{hour} {suffix}"


def fmt_day(d: date) -> str:
    return f"{d.strftime('%a')} {d.strftime('%b')} {d.day}"


def fmt_hours(minutes: float) -> str:
    h = minutes / 60
    return f"{h:.0f}h" if abs(h - round(h)) < 0.05 else f"{h:.1f}h"


def parse_day(value, name: str = "date") -> date:
    """A local date from 'YYYY-MM-DD' or an ISO instant."""
    if value in (None, ""):
        bad_request(f"'{name}' is required")
    text = str(value)
    if len(text) > 10 and parse_iso(text):
        return local_date(text)
    d = parse_date(text)
    if not d:
        bad_request(f"'{name}' must be a date like 2026-10-26")
    return d


def instants_for(day, start_time: str, end_time: str) -> tuple[str, str]:
    """Local date + 'HH:MM' times -> (start, end) instants. An end at or before the
    start means the shift runs past midnight."""
    d = parse_day(day)
    if not valid_hhmm(start_time) or not valid_hhmm(end_time):
        bad_request("Times must look like 08:30")
    start = local_to_utc_iso(d, start_time, tz())
    end_day = d if hhmm_to_minutes(end_time) > hhmm_to_minutes(start_time) else d + timedelta(days=1)
    end = local_to_utc_iso(end_day, end_time, tz())
    return start, end


def minutes_between(a, b) -> float:
    return (parse_iso(b) - parse_iso(a)).total_seconds() / 60.0


def range_from_args(start, end, default_days: int = 7) -> tuple[date, date]:
    """(first day, day after the last) from request args; defaults to this week."""
    s = parse_day(start, "start") if start else week_start(today())
    e = parse_day(end, "end") if end else s + timedelta(days=default_days)
    if e <= s:
        bad_request("'end' must be after 'start'")
    if (e - s).days > 62:
        bad_request("Ask for at most two months at a time")
    return s, e


def days_between(s: date, e: date) -> list[date]:
    return [s + timedelta(days=i) for i in range((e - s).days)]


# -- people ---------------------------------------------------------------------------


def manager_ids() -> list[int]:
    return users_svc.ids_with_perm("manage_staff")


def everyone_ids() -> list[int]:
    return users_svc.active_ids()


def profile(uid: int) -> dict:
    row = db.one("SELECT * FROM staff_profiles WHERE user_id = ?", uid)
    if row:
        return row
    return {"user_id": uid, "employee_number": None, "employment_type": "full_time", "hourly_rate": None,
            "hire_date": None, "target_hours_week": None, "max_hours_week": None, "default_position_id": None,
            "default_location_id": None, "pto_hours_per_year": None, "emergency_contact": None, "notes": None,
            "is_schedulable": 1, "updated_at": None}


def ensure_profile(uid: int) -> None:
    db.execute("INSERT OR IGNORE INTO staff_profiles (user_id) VALUES (?)", uid)


def position_ids_of(uid: int) -> list[int]:
    return db.column("SELECT position_id FROM staff_positions WHERE user_id = ? ORDER BY position_id", uid)


def rate_for(uid: int | None, position_id: int | None, rates: dict | None = None, position_rates: dict | None = None) -> float:
    if rates is None:
        rates = {r["user_id"]: r["hourly_rate"] for r in db.query("SELECT user_id, hourly_rate FROM staff_profiles")}
    if position_rates is None:
        position_rates = {p["id"]: p["default_rate"] for p in db.query("SELECT id, default_rate FROM positions")}
    rate = rates.get(uid) if uid else None
    if rate is None and position_id:
        rate = position_rates.get(position_id)
    return float(rate or 0)


# -- shifts ---------------------------------------------------------------------------


def paid_minutes(shift: dict) -> float:
    return max(0.0, minutes_between(shift["start_at"], shift["end_at"]) - (shift.get("break_minutes") or 0))


def serialize_shift(s: dict) -> dict:
    st, en = local_dt(s["start_at"]), local_dt(s["end_at"])
    return {
        "id": s["id"],
        "user_id": s["user_id"],
        "position_id": s["position_id"],
        "location_id": s["location_id"],
        "start_at": s["start_at"],
        "end_at": s["end_at"],
        "date": st.date().isoformat(),
        "start_time": st.strftime("%H:%M"),
        "end_time": en.strftime("%H:%M"),
        "overnight": en.date() > st.date(),
        "break_minutes": s["break_minutes"] or 0,
        "minutes": round(paid_minutes(s), 2),
        "notes": s["notes"],
        "status": s["status"],
        "job_id": s["job_id"],
        "published_at": s["published_at"],
        "created_by": s["created_by"],
        "updated_at": s["updated_at"],
    }


def split_overtime(items: list[dict], weekly_hours=None, daily_hours=None) -> None:
    """Split each item's minutes into regular and overtime, in time order: daily
    overtime first (if a daily threshold is set), then weekly overtime on what's left.
    items: [{"start": iso, "minutes": n}] — adds "regular", "overtime", "day", "week"."""
    weekly = float(weekly_hours if weekly_hours is not None else settings.get("staffing.overtime_weekly_hours") or 0) * 60
    daily_setting = daily_hours if daily_hours is not None else settings.get("staffing.overtime_daily_hours")
    daily = float(daily_setting) * 60 if daily_setting else None
    week_regular: dict = defaultdict(float)
    day_total: dict = defaultdict(float)
    for item in sorted(items, key=lambda i: i["start"]):
        d = local_date(item["start"])
        wk = week_start(d)
        worked = max(0.0, float(item["minutes"]))
        if daily is not None:
            reg_daily = min(worked, max(0.0, daily - day_total[d]))
        else:
            reg_daily = worked
        overtime = worked - reg_daily
        if weekly:
            regular = min(reg_daily, max(0.0, weekly - week_regular[wk]))
        else:
            regular = reg_daily
        overtime += reg_daily - regular
        week_regular[wk] += regular
        day_total[d] += worked
        item.update({"regular": regular, "overtime": overtime, "day": d, "week": wk})


def _window_shifts(user_ids: list[int], start: str, end: str) -> list[dict]:
    if not user_ids:
        return []
    return db.query(
        f"SELECT * FROM shifts WHERE user_id IN ({db.placeholders(user_ids)}) AND start_at < ? AND end_at > ? "
        f"ORDER BY start_at",
        [*user_ids, end, start],
    )


def time_off_rows(user_ids: list[int], first: date, last: date, statuses=("approved", "pending")) -> list[dict]:
    if not user_ids:
        return []
    return db.query(
        f"SELECT * FROM time_off_requests WHERE user_id IN ({db.placeholders(user_ids)}) "
        f"AND status IN ({db.placeholders(statuses)}) AND start_date <= ? AND end_date >= ?",
        [*user_ids, *statuses, last.isoformat(), first.isoformat()],
    )


def time_off_hits(shift: dict, rows: list[dict]) -> list[dict]:
    """Time-off requests that overlap a shift (dates, plus times for partial days)."""
    st, en = local_dt(shift["start_at"]), local_dt(shift["end_at"])
    last_day = (en - timedelta(minutes=1)).date()
    hits = []
    for r in rows:
        if r["user_id"] != shift["user_id"]:
            continue
        rs, re_ = date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"])
        if rs > last_day or re_ < st.date():
            continue
        if r["start_time"] and r["end_time"]:
            # partial day: compare clock times on each overlapping day
            overlap = False
            d = max(rs, st.date())
            while d <= min(re_, last_day):
                off_start = parse_iso(local_to_utc_iso(d, r["start_time"], tz()))
                off_end = parse_iso(local_to_utc_iso(d, r["end_time"], tz()))
                if parse_iso(shift["start_at"]) < off_end and off_start < parse_iso(shift["end_at"]):
                    overlap = True
                    break
                d += timedelta(days=1)
            if not overlap:
                continue
        hits.append(r)
    return hits


def annotate_conflicts(shifts: list[dict]) -> None:
    """Add ``conflicts`` ([{type, severity, message}]) to serialized shifts. Looks at
    each person's other shifts (drafts too), time off, availability, positions and
    the overtime / rest / length rules."""
    for s in shifts:
        s["conflicts"] = []
    assigned = [s for s in shifts if s["user_id"]]
    if not assigned:
        return
    user_ids = sorted({s["user_id"] for s in assigned})
    win_start = iso(min(parse_iso(s["start_at"]) for s in assigned) - timedelta(days=8))
    win_end = iso(max(parse_iso(s["end_at"]) for s in assigned) + timedelta(days=8))
    others = [serialize_shift(r) for r in _window_shifts(user_ids, win_start, win_end)]
    by_user: dict[int, list[dict]] = defaultdict(list)
    for o in others:
        by_user[o["user_id"]].append(o)
    time_off = time_off_rows(user_ids, local_date(win_start), local_date(win_end))
    availability: dict[int, list[dict]] = defaultdict(list)
    for a in db.query(f"SELECT * FROM availability WHERE user_id IN ({db.placeholders(user_ids)})", user_ids):
        availability[a["user_id"]].append(a)
    held: dict[int, set] = defaultdict(set)
    for p in db.query(f"SELECT * FROM staff_positions WHERE user_id IN ({db.placeholders(user_ids)})", user_ids):
        held[p["user_id"]].add(p["position_id"])
    position_names = {p["id"]: p["name"] for p in db.query("SELECT id, name FROM positions")}
    names = {u: first_name(users_svc.name_of(u, "They")) for u in user_ids}
    weekly_h = float(settings.get("staffing.overtime_weekly_hours") or 0)
    daily_h = settings.get("staffing.overtime_daily_hours")
    min_rest = float(settings.get("staffing.min_rest_hours") or 0)
    max_len = float(settings.get("staffing.max_shift_hours") or 0)

    # cumulative weekly/daily minutes per shift, in time order (drafts count too)
    cumulative: dict[int, tuple[float, float]] = {}
    for uid, lst in by_user.items():
        week_sum: dict = defaultdict(float)
        day_sum: dict = defaultdict(float)
        for o in sorted(lst, key=lambda x: x["start_at"]):
            d = date.fromisoformat(o["date"])
            week_sum[week_start(d)] += o["minutes"]
            day_sum[d] += o["minutes"]
            cumulative[o["id"]] = (week_sum[week_start(d)], day_sum[d])

    for s in assigned:
        uid = s["user_id"]
        name = names.get(uid, "They")
        mine = [o for o in by_user[uid] if o["id"] != s["id"]]
        start, end = parse_iso(s["start_at"]), parse_iso(s["end_at"])
        conflicts = s["conflicts"]
        for o in mine:
            if parse_iso(o["start_at"]) < end and start < parse_iso(o["end_at"]):
                conflicts.append({"type": "overlap", "severity": "error",
                                  "message": f"Overlaps {name}'s shift {fmt_hhmm(o['start_time'])}–{fmt_hhmm(o['end_time'])} on {fmt_day(date.fromisoformat(o['date']))}"})
                break
        for r in time_off_hits(s, time_off):
            if r["status"] == "approved":
                conflicts.append({"type": "time_off", "severity": "error",
                                  "message": f"{name} has approved {r['kind']} time off"})
            else:
                conflicts.append({"type": "time_off_pending", "severity": "warning",
                                  "message": f"{name} has asked for {r['kind']} time off"})
        rows = availability.get(uid) or []
        if rows:
            st_local = local_dt(s["start_at"])
            wd = st_local.weekday()
            st_min = st_local.hour * 60 + st_local.minute
            en_min = st_min + int(round(minutes_between(s["start_at"], s["end_at"])))
            for r in rows:
                if r["weekday"] == wd and r["kind"] == "unavailable":
                    rs, re_ = hhmm_to_minutes(r["start_time"]), hhmm_to_minutes(r["end_time"]) or 1440
                    if st_min < re_ and rs < en_min:
                        conflicts.append({"type": "unavailable", "severity": "warning",
                                          "message": f"{name} is unavailable {fmt_hhmm(r['start_time'])}–{fmt_hhmm(r['end_time'])} on {WEEKDAY_NAMES[wd]}"})
                        break
            if any(r["kind"] in ("available", "preferred") for r in rows):
                covered = any(
                    r["weekday"] == wd and r["kind"] in ("available", "preferred")
                    and hhmm_to_minutes(r["start_time"]) <= st_min and en_min <= (hhmm_to_minutes(r["end_time"]) or 1440)
                    for r in rows
                )
                if not covered:
                    conflicts.append({"type": "availability", "severity": "warning",
                                      "message": f"Outside {name}'s availability on {WEEKDAY_NAMES[wd]}"})
        week_total, day_total = cumulative.get(s["id"], (0.0, 0.0))
        if weekly_h and week_total > weekly_h * 60 + 0.01:
            conflicts.append({"type": "overtime", "severity": "warning",
                              "message": f"Puts {name} at {fmt_hours(week_total)} this week (overtime after {weekly_h:g}h)"})
        if daily_h and day_total > float(daily_h) * 60 + 0.01:
            conflicts.append({"type": "overtime_daily", "severity": "warning",
                              "message": f"{fmt_hours(day_total)} in one day (overtime after {float(daily_h):g}h)"})
        if min_rest:
            earlier = [o for o in mine if parse_iso(o["end_at"]) <= start]
            if earlier:
                prev_end = max(parse_iso(o["end_at"]) for o in earlier)
                rest = (start - prev_end).total_seconds() / 3600
                if 0 < rest < min_rest:
                    conflicts.append({"type": "rest", "severity": "warning",
                                      "message": f"Only {rest:.1f}h rest since {name}'s last shift (minimum {min_rest:g}h)"})
        span = minutes_between(s["start_at"], s["end_at"]) / 60
        if max_len and span > max_len + 0.001:
            conflicts.append({"type": "long", "severity": "warning",
                              "message": f"{span:.1f}h shift (longest allowed is {max_len:g}h)"})
        if s["position_id"] and held.get(uid) and s["position_id"] not in held[uid]:
            conflicts.append({"type": "position", "severity": "warning",
                              "message": f"{name} isn't set up as {position_names.get(s['position_id'], 'this position')}"})


def totals(shifts: list[dict], include_cost: bool) -> tuple[dict, dict]:
    """Per-person and per-day totals for serialized shifts:
    ({uid: {minutes, shifts, overtime_minutes, cost}}, {date: {minutes, shifts, cost, open}})."""
    rates = {r["user_id"]: r["hourly_rate"] for r in db.query("SELECT user_id, hourly_rate FROM staff_profiles")}
    position_rates = {p["id"]: p["default_rate"] for p in db.query("SELECT id, default_rate FROM positions")}
    people: dict = {}
    days: dict = {}
    by_user: dict[int, list[dict]] = defaultdict(list)
    for s in shifts:
        day = days.setdefault(s["date"], {"minutes": 0.0, "shifts": 0, "cost": 0.0, "open": 0})
        day["shifts"] += 1
        day["minutes"] += s["minutes"]
        if not s["user_id"]:
            day["open"] += 1
        cost = s["minutes"] / 60 * rate_for(s["user_id"], s["position_id"], rates, position_rates)
        day["cost"] += cost
        if s["user_id"]:
            by_user[s["user_id"]].append(s)
            p = people.setdefault(s["user_id"], {"minutes": 0.0, "shifts": 0, "overtime_minutes": 0.0, "cost": 0.0})
            p["minutes"] += s["minutes"]
            p["shifts"] += 1
            p["cost"] += cost
    for uid, lst in by_user.items():
        items = [{"start": s["start_at"], "minutes": s["minutes"]} for s in lst]
        split_overtime(items)
        people[uid]["overtime_minutes"] = sum(i["overtime"] for i in items)
    for collection in (people.values(), days.values()):
        for t in collection:
            t["minutes"] = round(t["minutes"], 2)
            t["cost"] = round(t["cost"], 2) if include_cost else None
            if "overtime_minutes" in t:
                t["overtime_minutes"] = round(t["overtime_minutes"], 2)
    return people, days


# -- notifications & events -------------------------------------------------------------


def emit_schedule(reason: str, **data) -> None:
    realtime.emit("schedule.changed", {"reason": reason, **data}, users=everyone_ids())


def emit_badges(user_ids=None) -> None:
    people = {u for u in (user_ids or []) if u} | set(manager_ids())
    realtime.emit("badges.changed", {}, users=sorted(people))


def describe_shift(s: dict) -> str:
    st, en = local_dt(s["start_at"]), local_dt(s["end_at"])
    return f"{fmt_day(st.date())}, {fmt_time(st)}–{fmt_time(en)}"


def week_link(d: date) -> str:
    return f"/schedule?week={week_start(d).isoformat()}"


def notify_shift_change(before: dict | None, after: dict | None, actor_id: int | None) -> None:
    """Tell people when a published shift of theirs is added, changed or removed."""
    published = (before and before["status"] == "published") or (after and after["status"] == "published")
    if not published:
        return
    old_uid = before["user_id"] if before and before["status"] == "published" else None
    new_uid = after["user_id"] if after and after["status"] == "published" else None
    actor = users_svc.name_of(actor_id, "A manager") if actor_id else "A manager"
    if old_uid and old_uid != new_uid:
        notify.notify([old_uid], "shift", f"{actor} removed you from {describe_shift(before)}",
                      link=week_link(local_date(before["start_at"])), actor_id=actor_id, entity_type="shift",
                      entity_id=before["id"])
    if new_uid and new_uid != old_uid:
        notify.notify([new_uid], "shift", f"New shift: {describe_shift(after)}",
                      link=week_link(local_date(after["start_at"])), actor_id=actor_id, entity_type="shift",
                      entity_id=after["id"])
    elif new_uid and before and (before["start_at"], before["end_at"], before["position_id"], before["location_id"]) != (
            after["start_at"], after["end_at"], after["position_id"], after["location_id"]):
        notify.notify([new_uid], "shift", f"Your shift changed: {describe_shift(after)}",
                      body=f"Was {describe_shift(before)}", link=week_link(local_date(after["start_at"])),
                      actor_id=actor_id, entity_type="shift", entity_id=after["id"])


def publish(start: date, end: date, by: dict) -> dict:
    """Publish draft shifts starting in [start, end) and tell each person once."""
    rows = db.query(
        "SELECT * FROM shifts WHERE status = 'draft' AND start_at >= ? AND start_at < ? ORDER BY start_at",
        day_start(start), day_start(end),
    )
    if not rows:
        return {"published": 0, "people": 0}
    stamp = now_iso()
    with db.transaction():
        ids = [r["id"] for r in rows]
        db.execute(f"UPDATE shifts SET status = 'published', published_at = ?, updated_at = ? "
                   f"WHERE id IN ({db.placeholders(ids)})", [stamp, stamp, *ids])
        people = sorted({r["user_id"] for r in rows if r["user_id"]})
        label = fmt_day(week_start(start)).split(" ", 1)[1]
        for uid in people:
            count = sum(1 for r in rows if r["user_id"] == uid)
            notify.notify([uid], "shift", f"Your schedule for the week of {label} is published",
                          body=f"{count} shift{'s' if count != 1 else ''} — check your hours and times.",
                          link=week_link(start), actor_id=by["id"], entity_type="schedule")
        open_positions = {r["position_id"] for r in rows if not r["user_id"]}
        if open_positions:
            if None in open_positions:
                eligible = set(everyone_ids())
            else:
                eligible = set(db.column(
                    f"SELECT user_id FROM staff_positions WHERE position_id IN ({db.placeholders(open_positions)})",
                    sorted(open_positions),
                ))
            notify.notify(sorted(eligible & set(everyone_ids())), "shift", "Open shifts are available to pick up",
                          link="/schedule/requests", actor_id=by["id"], entity_type="schedule")
        hooks.fire("shift.published", {"shift_ids": ids, "user_ids": people, "start": start.isoformat(),
                                       "end": end.isoformat(), "by": by["id"]})
        emit_schedule("published", start=start.isoformat(), end=end.isoformat())
    return {"published": len(rows), "people": len(people)}


def copy_week(from_week: date, to_week: date, by: dict) -> dict:
    """Copy every shift of one week into another as drafts, at the same local times.
    Skips shifts that would overlap something the person already has."""
    src_start, dst_start = week_start(from_week), week_start(to_week)
    if src_start == dst_start:
        bad_request("Pick two different weeks")
    rows = db.query("SELECT * FROM shifts WHERE start_at >= ? AND start_at < ? ORDER BY start_at",
                    day_start(src_start), day_start(src_start + timedelta(days=7)))
    created, skipped = [], 0
    stamp = now_iso()
    with db.transaction():
        for r in rows:
            s = serialize_shift(r)
            d = date.fromisoformat(s["date"]) + (dst_start - src_start)
            start, end = instants_for(d, s["start_time"], s["end_time"])
            if r["user_id"] and db.one(
                "SELECT 1 AS x FROM shifts WHERE user_id = ? AND start_at < ? AND end_at > ?", r["user_id"], end, start
            ):
                skipped += 1
                continue
            created.append(db.insert("shifts", {
                "user_id": r["user_id"], "position_id": r["position_id"], "location_id": r["location_id"],
                "start_at": start, "end_at": end, "break_minutes": r["break_minutes"], "notes": r["notes"],
                "status": "draft", "job_id": r["job_id"], "created_by": by["id"], "created_at": stamp,
                "updated_at": stamp,
            }))
        emit_schedule("copied", start=dst_start.isoformat())
    return {"created": len(created), "skipped": skipped}


# -- requests: swap / drop / pickup ------------------------------------------------------


def get_request(rid: int) -> dict:
    row = db.one("SELECT * FROM shift_requests WHERE id = ?", rid)
    if not row:
        not_found("Request not found")
    return row


def _future_published(shift: dict) -> None:
    if shift["status"] != "published":
        bad_request("Only published shifts can be swapped, dropped or picked up")
    if parse_iso(shift["start_at"]) <= now():
        bad_request("That shift has already started")


def _awaiting_manager(rid: int, title: str, actor_id: int) -> None:
    notify.notify(manager_ids(), "swap", title, link="/schedule/requests", actor_id=actor_id,
                  entity_type="shift_request", entity_id=rid)


def create_request(user: dict, data: dict) -> dict:
    kind = data.get("kind")
    if kind not in ("drop", "pickup", "swap"):
        bad_request("kind must be drop, pickup or swap")
    shift = db.one("SELECT * FROM shifts WHERE id = ?", data.get("shift_id"))
    if not shift:
        not_found("Shift not found")
    _future_published(shift)
    pending = db.one(
        "SELECT id FROM shift_requests WHERE shift_id = ? AND requester_id = ? AND status IN ('pending', 'accepted')",
        shift["id"], user["id"],
    )
    if pending:
        conflict("You already have a request open for this shift")
    target_user_id = target_shift_id = None
    if kind in ("drop", "swap") and shift["user_id"] != user["id"]:
        forbidden("You can only give away your own shifts")
    if kind == "pickup":
        if shift["user_id"]:
            bad_request("That shift isn't open")
        held = position_ids_of(user["id"])
        if shift["position_id"] and shift["position_id"] not in held:
            forbidden("You aren't set up for that position")
        if db.one("SELECT 1 AS x FROM shifts WHERE user_id = ? AND start_at < ? AND end_at > ?",
                  user["id"], shift["end_at"], shift["start_at"]):
            conflict("You're already working then")
    if kind == "swap":
        target_user_id = int(data.get("target_user_id") or 0)
        target = users_svc.get(target_user_id)
        if not target or not target["is_active"] or target_user_id == user["id"]:
            bad_request("Pick a coworker to swap with")
        if data.get("target_shift_id"):
            other = db.one("SELECT * FROM shifts WHERE id = ?", data["target_shift_id"])
            if not other or other["user_id"] != target_user_id:
                bad_request("That shift isn't theirs")
            _future_published(other)
            target_shift_id = other["id"]
    note = (data.get("note") or "").strip()[:500] or None
    stamp = now_iso()
    with db.transaction():
        rid = db.insert("shift_requests", {
            "kind": kind, "shift_id": shift["id"], "requester_id": user["id"], "target_user_id": target_user_id,
            "target_shift_id": target_shift_id, "status": "pending", "note": note, "created_at": stamp,
        })
        when = describe_shift(shift)
        if kind == "swap":
            what = f"swap shifts ({when})" if target_shift_id else f"take their shift ({when})"
            notify.notify([target_user_id], "swap", f"{user['name']} asked you to {what}", body=note,
                          link="/schedule/requests", actor_id=user["id"], entity_type="shift_request", entity_id=rid)
        elif kind == "drop":
            _awaiting_manager(rid, f"{user['name']} wants to drop {when}", user["id"])
        else:
            if not settings.get("staffing.pickup_requires_approval"):
                _execute(rid, None)
            else:
                _awaiting_manager(rid, f"{user['name']} wants to pick up {when}", user["id"])
        emit_schedule("request", request_id=rid)
        emit_badges([user["id"], target_user_id] if target_user_id else [user["id"]])
    return get_request(rid)


def _execute(rid: int, decider: dict | None, note: str | None = None) -> None:
    """Carry out an approved request (inside a transaction)."""
    req = get_request(rid)
    shift = db.one("SELECT * FROM shifts WHERE id = ?", req["shift_id"])
    stamp = now_iso()
    by = decider["id"] if decider else None
    if req["kind"] == "drop":
        if shift["user_id"] != req["requester_id"]:
            conflict("That shift has changed hands since the request")
        db.update("shifts", shift["id"], {"user_id": None, "updated_at": stamp})
    elif req["kind"] == "pickup":
        if shift["user_id"]:
            conflict("Someone already picked up that shift")
        db.update("shifts", shift["id"], {"user_id": req["requester_id"], "updated_at": stamp})
        for other in db.query("SELECT id, requester_id FROM shift_requests WHERE shift_id = ? AND kind = 'pickup' "
                              "AND status = 'pending' AND id != ?", shift["id"], rid):
            db.update("shift_requests", other["id"], {"status": "denied", "decided_by": by, "decided_at": stamp,
                                                      "decision_note": "Someone else picked it up"})
            notify.notify([other["requester_id"]], "swap", f"The open shift {describe_shift(shift)} was filled",
                          link="/schedule/requests", entity_type="shift_request", entity_id=other["id"])
    else:  # swap
        if shift["user_id"] != req["requester_id"]:
            conflict("That shift has changed hands since the request")
        if req["target_shift_id"]:
            other = db.one("SELECT * FROM shifts WHERE id = ?", req["target_shift_id"])
            if not other or other["user_id"] != req["target_user_id"]:
                conflict("Their shift has changed hands since the request")
            db.update("shifts", other["id"], {"user_id": req["requester_id"], "updated_at": stamp})
        db.update("shifts", shift["id"], {"user_id": req["target_user_id"], "updated_at": stamp})
    db.update("shift_requests", rid, {"status": "approved", "decided_by": by, "decided_at": stamp,
                                      "decision_note": note})
    people = [u for u in (req["requester_id"], req["target_user_id"]) if u]
    verb = {"drop": "drop", "pickup": "pick up", "swap": "swap"}[req["kind"]]
    notify.notify(people, "swap", f"Approved: {verb} {describe_shift(shift)}", body=note,
                  link=week_link(local_date(shift["start_at"])), actor_id=by, entity_type="shift_request",
                  entity_id=rid)
    hooks.fire("shift.request_approved", {"request_id": rid, "kind": req["kind"], "shift_id": shift["id"]})


def accept_request(user: dict, rid: int) -> dict:
    req = get_request(rid)
    if req["kind"] != "swap" or req["target_user_id"] != user["id"]:
        forbidden("Only the coworker asked can accept this")
    if req["status"] != "pending":
        bad_request("This request is no longer waiting on you")
    with db.transaction():
        db.update("shift_requests", rid, {"status": "accepted"})
        shift = db.one("SELECT * FROM shifts WHERE id = ?", req["shift_id"])
        if settings.get("staffing.swap_requires_approval"):
            notify.notify([req["requester_id"]], "swap", f"{user['name']} accepted your swap — waiting on a manager",
                          link="/schedule/requests", actor_id=user["id"], entity_type="shift_request", entity_id=rid)
            requester = users_svc.name_of(req["requester_id"])
            _awaiting_manager(rid, f"Swap to approve: {requester} ↔ {user['name']} ({describe_shift(shift)})", user["id"])
        else:
            _execute(rid, None)
        emit_schedule("request", request_id=rid)
        emit_badges([req["requester_id"], user["id"]])
    return get_request(rid)


def decide_request(user: dict, rid: int, approve: bool, note: str | None = None) -> dict:
    req = get_request(rid)
    is_manager = can(user, "manage_staff")
    is_target = req["kind"] == "swap" and req["target_user_id"] == user["id"]
    if approve:
        if not is_manager:
            forbidden("Only a manager can approve")
        if req["status"] not in ("pending", "accepted"):
            bad_request("This request was already decided")
        if req["kind"] == "swap" and req["status"] != "accepted":
            bad_request(f"{users_svc.name_of(req['target_user_id'])} hasn't accepted the swap yet")
        with db.transaction():
            _execute(rid, user, note)
            emit_schedule("request", request_id=rid)
            emit_badges([req["requester_id"], req["target_user_id"]])
        return get_request(rid)
    if not (is_manager or (is_target and req["status"] == "pending")):
        forbidden("You can't decline this request")
    if req["status"] not in ("pending", "accepted"):
        bad_request("This request was already decided")
    with db.transaction():
        db.update("shift_requests", rid, {"status": "denied", "decided_by": user["id"], "decided_at": now_iso(),
                                          "decision_note": note})
        shift = db.one("SELECT * FROM shifts WHERE id = ?", req["shift_id"])
        notify.notify([req["requester_id"]], "swap", f"{user['name']} declined your request for {describe_shift(shift)}",
                      body=note, link="/schedule/requests", actor_id=user["id"], entity_type="shift_request",
                      entity_id=rid)
        emit_schedule("request", request_id=rid)
        emit_badges([req["requester_id"], req["target_user_id"]])
    return get_request(rid)


def cancel_request(user: dict, rid: int) -> dict:
    req = get_request(rid)
    if req["requester_id"] != user["id"] and not can(user, "manage_staff"):
        forbidden("Only the person who asked can cancel")
    if req["status"] not in ("pending", "accepted"):
        bad_request("This request was already decided")
    with db.transaction():
        db.update("shift_requests", rid, {"status": "cancelled", "decided_by": user["id"], "decided_at": now_iso()})
        emit_schedule("request", request_id=rid)
        emit_badges([req["requester_id"], req["target_user_id"]])
    return get_request(rid)


def pending_counts(user: dict) -> dict:
    """What's waiting: for managers, approvals; for everyone, swaps asked of them."""
    out = {"timeoff": 0, "requests": 0, "mine": 0}
    if can(user, "manage_staff"):
        out["timeoff"] = db.scalar("SELECT COUNT(*) FROM time_off_requests WHERE status = 'pending'")
        out["requests"] = db.scalar(
            "SELECT COUNT(*) FROM shift_requests WHERE (kind IN ('drop', 'pickup') AND status = 'pending') "
            "OR (kind = 'swap' AND status = 'accepted')"
        )
    out["mine"] = db.scalar(
        "SELECT COUNT(*) FROM shift_requests WHERE kind = 'swap' AND status = 'pending' AND target_user_id = ?",
        user["id"],
    )
    return out


# -- time clock ---------------------------------------------------------------------------


def breaks_of(entry: dict) -> list[dict]:
    return db.jload(entry.get("breaks_json"), []) or []


def break_minutes(entry: dict, at: datetime | None = None) -> float:
    """Finished breaks (plus a running one, up to ``at``). Manual entries keep a plain
    break_minutes number instead of a break list."""
    breaks = breaks_of(entry)
    if not breaks:
        return float(entry.get("break_minutes") or 0)
    total = 0.0
    for b in breaks:
        end = parse_iso(b.get("end")) or at
        if end:
            total += max(0.0, (end - parse_iso(b["start"])).total_seconds() / 60)
    return total


def on_break(entry: dict) -> bool:
    breaks = breaks_of(entry)
    return bool(breaks) and not breaks[-1].get("end")


def _round(dt: datetime, minutes: int) -> datetime:
    if not minutes:
        return dt
    step = minutes * 60
    ts = dt.timestamp()
    return datetime.fromtimestamp(round(ts / step) * step, dt.tzinfo)


def worked_minutes(entry: dict, at: datetime | None = None) -> float:
    """Paid minutes of a time entry (open entries count up to ``at``/now), after the
    clock rounding setting."""
    at = at or now()
    rounding = int(settings.get("staffing.clock_rounding_minutes") or 0)
    start = _round(parse_iso(entry["clock_in"]), rounding)
    end = _round(parse_iso(entry["clock_out"]), rounding) if entry.get("clock_out") else at
    return max(0.0, (end - start).total_seconds() / 60 - break_minutes(entry, at))


def open_entry(uid: int) -> dict | None:
    return db.one("SELECT * FROM time_entries WHERE user_id = ? AND clock_out IS NULL ORDER BY clock_in DESC LIMIT 1", uid)


def shift_covering(uid: int, at: datetime | None = None) -> dict | None:
    """The published shift ``uid`` is working at ``at`` (with the early clock-in window)."""
    at = at or now()
    early = int(settings.get("staffing.early_clock_in_minutes") or 0)
    return db.one(
        "SELECT * FROM shifts WHERE user_id = ? AND status = 'published' AND start_at <= ? AND end_at > ? "
        "ORDER BY start_at LIMIT 1",
        uid, iso(at + timedelta(minutes=early)), iso(at),
    )


def serialize_entry(e: dict, at: datetime | None = None) -> dict:
    return {
        "id": e["id"],
        "user_id": e["user_id"],
        "shift_id": e["shift_id"],
        "job_id": e["job_id"],
        "clock_in": e["clock_in"],
        "clock_out": e["clock_out"],
        "breaks": breaks_of(e),
        "break_minutes": round(break_minutes(e, at or now()), 2),
        "worked_minutes": round(worked_minutes(e, at), 2),
        "on_break": on_break(e),
        "notes": e["notes"],
        "source": e["source"],
        "status": e["status"],
        "flag": e.get("flag"),
        "approved_by": e["approved_by"],
        "approved_at": e["approved_at"],
        "date": local_date(e["clock_in"]).isoformat(),
    }


def punch(uid: int, action: str, source: str = "clock", job_id: int | None = None, note: str | None = None) -> dict:
    """Clock in/out or start/end a break for ``uid``. Returns the time entry."""
    stamp = now_iso()
    entry = open_entry(uid)
    with db.transaction():
        if action == "in":
            if entry:
                conflict("You're already clocked in", code="already_in")
            if job_id and not db.one("SELECT id FROM jobs WHERE id = ?", job_id):
                bad_request("No such job")
            shift = shift_covering(uid)
            eid = db.insert("time_entries", {
                "user_id": uid, "shift_id": shift["id"] if shift else None, "job_id": job_id, "clock_in": stamp,
                "notes": (note or "").strip()[:500] or None, "source": source, "created_by": uid, "created_at": stamp,
                "updated_at": stamp,
            })
        else:
            if not entry:
                conflict("You're not clocked in", code="not_in")
            eid = entry["id"]
            breaks = breaks_of(entry)
            if action == "break_start":
                if on_break(entry):
                    conflict("You're already on a break")
                breaks.append({"start": stamp, "end": None})
                db.update("time_entries", eid, {"breaks_json": db.jdump(breaks), "updated_at": stamp})
            elif action == "break_end":
                if not on_break(entry):
                    conflict("You're not on a break")
                breaks[-1]["end"] = stamp
                total = break_minutes({"breaks_json": db.jdump(breaks)})
                db.update("time_entries", eid, {"breaks_json": db.jdump(breaks), "break_minutes": int(round(total)),
                                                "updated_at": stamp})
            elif action == "out":
                if on_break(entry):
                    breaks[-1]["end"] = stamp
                total = break_minutes({"breaks_json": db.jdump(breaks), "break_minutes": entry["break_minutes"]})
                changes = {"clock_out": stamp, "breaks_json": db.jdump(breaks), "break_minutes": int(round(total)),
                           "updated_at": stamp}
                if note:
                    changes["notes"] = "\n".join(x for x in (entry["notes"], note.strip()[:500]) if x)
                db.update("time_entries", eid, changes)
            else:
                bad_request("Unknown time clock action")
        hooks.fire("timeclock.punch", {"user_id": uid, "action": action, "entry_id": eid, "source": source})
        realtime.emit("timeclock.changed", {"user_id": uid, "action": action}, users=sorted(set(manager_ids()) | {uid}))
    return db.one("SELECT * FROM time_entries WHERE id = ?", eid)


# -- timesheets & pay periods --------------------------------------------------------------


def pay_period(d: date) -> tuple[date, date]:
    ws = week_start(d)
    if settings.get("staffing.pay_period") == "biweekly":
        anchor = week_start(parse_date(settings.get("staffing.pay_period_anchor")) or ws)
        weeks = (ws - anchor).days // 7
        start = ws - timedelta(days=7 * (weeks % 2))
        return start, start + timedelta(days=14)
    return ws, ws + timedelta(days=7)


def timesheets(start: date, end: date, user_ids: list[int]) -> list[dict]:
    """Per person, per local day: worked / break / regular / overtime / scheduled
    minutes, plus entries. Overtime looks at whole weeks so a partial range is right."""
    if not user_ids:
        return []
    at = now()
    wk_start = week_start(start)
    wk_end = week_start(end - timedelta(days=1)) + timedelta(days=7)
    ph = db.placeholders(user_ids)
    entries = db.query(
        f"SELECT * FROM time_entries WHERE user_id IN ({ph}) AND clock_in >= ? AND clock_in < ? ORDER BY clock_in",
        [*user_ids, day_start(wk_start), day_start(wk_end)],
    )
    shifts = db.query(
        f"SELECT * FROM shifts WHERE user_id IN ({ph}) AND status = 'published' AND start_at >= ? AND start_at < ?",
        [*user_ids, day_start(start), day_start(end)],
    )
    by_user: dict[int, list[dict]] = defaultdict(list)
    for e in entries:
        by_user[e["user_id"]].append(e)
    scheduled: dict = defaultdict(float)
    for s in shifts:
        scheduled[(s["user_id"], local_date(s["start_at"]))] += paid_minutes(s)
    days = days_between(start, end)
    out = []
    for uid in user_ids:
        items = [{"start": e["clock_in"], "minutes": worked_minutes(e, at), "entry": e} for e in by_user.get(uid, [])]
        split_overtime(items)
        in_range = [i for i in items if start <= i["day"] < end]
        day_rows = []
        for d in days:
            mine = [i for i in in_range if i["day"] == d]
            worked = sum(i["minutes"] for i in mine)
            sched = scheduled.get((uid, d), 0.0)
            day_rows.append({
                "date": d.isoformat(),
                "worked": round(worked, 2),
                "breaks": round(sum(break_minutes(i["entry"], at) for i in mine), 2),
                "regular": round(sum(i["regular"] for i in mine), 2),
                "overtime": round(sum(i["overtime"] for i in mine), 2),
                "scheduled": round(sched, 2),
                "variance": round(worked - sched, 2),
            })
        closed = [i["entry"] for i in in_range if i["entry"]["clock_out"]]
        serialized = []
        for i in in_range:
            row = serialize_entry(i["entry"], at)
            row["regular_minutes"] = round(i["regular"], 2)
            row["overtime_minutes"] = round(i["overtime"], 2)
            serialized.append(row)
        out.append({
            "user_id": uid,
            "days": day_rows,
            "totals": {k: round(sum(r[k] for r in day_rows), 2)
                       for k in ("worked", "breaks", "regular", "overtime", "scheduled", "variance")},
            "entries": serialized,
            "open_entries": sum(1 for i in in_range if not i["entry"]["clock_out"]),
            "flagged": sum(1 for i in in_range if i["entry"].get("flag")),
            "approved": bool(closed) and all(e["status"] == "approved" for e in closed),
        })
    return out
