"""The production schedule: job operations placed on equipment and people.

``board()`` feeds the timeline (rows, blocks, the unscheduled queue, shifts and time
off for shading). ``conflicts()`` explains what's wrong with a block. ``auto_schedule()``
places unscheduled operations greedily, earliest due date first, inside work hours, on
free equipment, with a qualified person who's on shift.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from pps_tools.switchboard import db
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import jobs as jobs_svc
from pps_tools.switchboard.services import settings
from pps_tools.switchboard.util import UTC, iso, now, now_iso, parse_iso
from pps_tools.switchboard.web import bad_request

SNAP_MINUTES = 15
HORIZON_DAYS = 60
DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# -- work hours & availability ------------------------------------------------------


def work_hours() -> dict:
    """{'start': 'HH:MM', 'end': 'HH:MM', 'days': [weekday...]}, from jobs.work_hours or,
    failing that, the earliest/latest org business hours."""
    wh = settings.get("jobs.work_hours") or {}
    if wh.get("start") and wh.get("end") and wh.get("days") is not None:
        return {"start": wh["start"], "end": wh["end"], "days": [int(d) for d in wh["days"]]}
    hours = settings.get("org.business_hours") or {}
    days, starts, ends = [], [], []
    for i, key in enumerate(DAY_KEYS):
        ranges = hours.get(key) or []
        if ranges:
            days.append(i)
            starts.append(min(r[0] for r in ranges))
            ends.append(max(r[1] for r in ranges))
    return {"start": min(starts) if starts else "08:00", "end": max(ends) if ends else "17:00",
            "days": days or [0, 1, 2, 3, 4]}


def _at(day: date, hhmm: str, tz) -> datetime:
    h, m = (int(x) for x in hhmm.split(":")[:2])
    if h >= 24:
        return datetime.combine(day + timedelta(days=1), time(0, m), tzinfo=tz).astimezone(UTC)
    return datetime.combine(day, time(h, m), tzinfo=tz).astimezone(UTC)


def work_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Working intervals (UTC) overlapping [start, end)."""
    tz = settings.timezone()
    wh = work_hours()
    holidays = set(settings.get("org.holidays") or [])
    out = []
    day = start.astimezone(tz).date()
    last = end.astimezone(tz).date()
    while day <= last:
        if day.weekday() in wh["days"] and day.isoformat() not in holidays:
            ws, we = _at(day, wh["start"], tz), _at(day, wh["end"], tz)
            if we > start and ws < end:
                out.append((max(ws, start), min(we, end)))
        day += timedelta(days=1)
    return out


def published_shifts(start: str, end: str) -> dict[int, list[tuple[datetime, datetime]]]:
    out: dict[int, list] = {}
    for s in db.query(
        "SELECT user_id, start_at, end_at FROM shifts WHERE user_id IS NOT NULL AND status = 'published' "
        "AND start_at < ? AND end_at > ? ORDER BY start_at", end, start,
    ):
        out.setdefault(s["user_id"], []).append((parse_iso(s["start_at"]), parse_iso(s["end_at"])))
    return out


def approved_time_off(start: str, end: str) -> dict[int, list[tuple[datetime, datetime, str]]]:
    tz = settings.timezone()
    start_day = (parse_iso(start).astimezone(tz).date() - timedelta(days=1)).isoformat()
    end_day = (parse_iso(end).astimezone(tz).date() + timedelta(days=1)).isoformat()
    out: dict[int, list] = {}
    for r in db.query(
        "SELECT user_id, kind, start_date, end_date, start_time, end_time FROM time_off_requests "
        "WHERE status = 'approved' AND start_date <= ? AND end_date >= ?", end_day, start_day,
    ):
        d0, d1 = date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"])
        if r["start_time"] and r["end_time"]:
            span = (_at(d0, r["start_time"], tz), _at(d1, r["end_time"], tz))
        else:
            span = (_at(d0, "00:00", tz), _at(d1 + timedelta(days=1), "00:00", tz))
        out.setdefault(r["user_id"], []).append((span[0], span[1], r["kind"]))
    return out


def _overlaps(a0, a1, b0, b1) -> bool:
    return a0 < b1 and b0 < a1


def _covered(start: datetime, end: datetime, intervals: list[tuple[datetime, datetime]]) -> bool:
    """Is [start, end) inside the union of intervals?"""
    cursor = start
    for s, e in sorted(intervals):
        if s > cursor:
            break
        if e > cursor:
            cursor = e
        if cursor >= end:
            return True
    return cursor >= end


# -- conflicts ----------------------------------------------------------------------


def _names(table: str, ids) -> dict[int, str]:
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    col = "name"
    return {r["id"]: r[col] for r in db.query(f"SELECT id, {col} FROM {table} WHERE id IN ({db.placeholders(ids)})", ids)}


def conflicts(blocks: list[dict]) -> dict[int, list[dict]]:
    """{operation_id: [{code, message}]} for scheduled, unfinished operations."""
    live = [b for b in blocks if b.get("start_at") and b.get("end_at") and b.get("status") != "done"]
    out: dict[int, list[dict]] = {b["id"]: [] for b in live}
    if not live:
        return out
    lo = min(b["start_at"] for b in live)
    hi = max(b["end_at"] for b in live)
    others = db.query(
        "SELECT o.*, j.number AS job_number FROM job_operations o JOIN jobs j ON j.id = o.job_id "
        "WHERE o.start_at IS NOT NULL AND o.end_at IS NOT NULL AND o.status != 'done' AND j.archived_at IS NULL "
        "AND o.start_at < ? AND o.end_at > ?", hi, lo,
    )
    resources = _names("resources", [o["resource_id"] for o in others])
    people = _names("users", [o["user_id"] for o in others])
    shifts = published_shifts(lo, hi)
    has_shift_data = bool(shifts) or bool(db.one(
        "SELECT 1 AS any_shift FROM shifts WHERE status = 'published' AND start_at < ? AND end_at > ? LIMIT 1", hi, lo))
    time_off = approved_time_off(lo, hi)
    job_ids = sorted({b["job_id"] for b in live})
    siblings = db.query(
        f"SELECT id, job_id, name, sequence, start_at, end_at, status FROM job_operations "
        f"WHERE job_id IN ({db.placeholders(job_ids)}) ORDER BY sequence, id", job_ids,
    )
    dues = {j["id"]: j["due_at"] for j in db.query(
        f"SELECT id, due_at FROM jobs WHERE id IN ({db.placeholders(job_ids)})", job_ids)}
    tz = settings.timezone()

    for b in live:
        s, e = parse_iso(b["start_at"]), parse_iso(b["end_at"])
        problems = out[b["id"]]
        for o in others:
            if o["id"] == b["id"] or not _overlaps(s, e, parse_iso(o["start_at"]), parse_iso(o["end_at"])):
                continue
            if b.get("resource_id") and o["resource_id"] == b["resource_id"]:
                problems.append({"code": "resource_busy",
                                 "message": f"{resources.get(o['resource_id'], 'Equipment')} is also booked for "
                                            f"{o['job_number']} {o['name']}", "other_id": o["id"]})
            if b.get("user_id") and o["user_id"] == b["user_id"]:
                problems.append({"code": "person_busy",
                                 "message": f"{people.get(o['user_id'], 'They')} is also on {o['job_number']} {o['name']}",
                                 "other_id": o["id"]})
        uid = b.get("user_id")
        if uid:
            name = people.get(uid) or _names("users", [uid]).get(uid, "This person")
            for t0, t1, kind in time_off.get(uid, []):
                if _overlaps(s, e, t0, t1):
                    problems.append({"code": "time_off", "message": f"{name} is off ({kind.replace('_', ' ')})"})
                    break
            if has_shift_data and not _covered(s, e, shifts.get(uid, [])):
                problems.append({"code": "off_shift", "message": f"{name} isn't scheduled to work then"})
        due = dues.get(b["job_id"])
        if due and e > parse_iso(due):
            local = parse_iso(due).astimezone(tz)
            problems.append({"code": "after_due",
                             "message": f"Finishes after the job is due ({local.strftime('%a %b %-d, %-I:%M %p')})"})
        prev = [o for o in siblings if o["job_id"] == b["job_id"] and o["sequence"] < b.get("sequence", 0)
                and o["start_at"] and o["end_at"] and o["status"] != "done"]
        if prev:
            p = max(prev, key=lambda o: (o["sequence"], o["id"]))
            if s < parse_iso(p["end_at"]):
                problems.append({"code": "sequence", "message": f"Starts before “{p['name']}” finishes"})
    return out


# -- board --------------------------------------------------------------------------


def _schedulable_people(start: str, end: str) -> list[dict]:
    profiled = db.query(
        "SELECT u.id, u.name, u.color, u.title, u.role FROM users u JOIN staff_profiles p ON p.user_id = u.id "
        "WHERE u.is_active = 1 AND p.is_schedulable = 1 ORDER BY u.name COLLATE NOCASE"
    )
    if profiled:
        people = profiled
    else:
        people = db.query(
            "SELECT id, name, color, title, role FROM users WHERE is_active = 1 AND role IN ('staff', 'manager', 'agent') "
            "ORDER BY name COLLATE NOCASE"
        )
    have = {p["id"] for p in people}
    extra = db.query(
        "SELECT DISTINCT u.id, u.name, u.color, u.title, u.role FROM job_operations o JOIN users u ON u.id = o.user_id "
        "WHERE o.start_at < ? AND o.end_at > ?", end, start,
    )
    return people + [p for p in extra if p["id"] not in have]


def _op_rows(where: str, params: list) -> list[dict]:
    return db.query(
        "SELECT o.*, j.number AS job_number, j.title AS job_title, j.priority AS job_priority, j.due_at AS job_due_at, "
        "j.stage_id AS job_stage_id, j.contact_id AS job_contact_id, j.organization_id AS job_organization_id "
        f"FROM job_operations o JOIN jobs j ON j.id = o.job_id WHERE j.archived_at IS NULL AND {where}",
        params,
    )


def _block(o: dict, stages: dict, customers: dict) -> dict:
    st = stages.get(o["job_stage_id"]) or {}
    return {
        **jobs_svc.serialize_operation(o),
        "job_number": o["job_number"], "job_title": o["job_title"], "job_priority": o["job_priority"],
        "job_due_at": o["job_due_at"], "stage_id": o["job_stage_id"], "stage_name": st.get("name"),
        "stage_color": st.get("color"), "customer": customers.get(o["job_id"]),
    }


def _customers(rows: list[dict]) -> dict[int, str]:
    contact_ids = {r["job_contact_id"] for r in rows if r.get("job_contact_id")}
    org_ids = {r["job_organization_id"] for r in rows if r.get("job_organization_id")}
    contacts = {c["id"]: c for c in db.query(
        f"SELECT * FROM contacts WHERE id IN ({db.placeholders(contact_ids)})", sorted(contact_ids))} if contact_ids else {}
    orgs = _names("organizations", org_ids)
    out = {}
    for r in rows:
        out[r["job_id"]] = orgs.get(r.get("job_organization_id")) or (
            contacts_svc.display_name(contacts[r["job_contact_id"]], None) if r.get("job_contact_id") in contacts else None)
    return out


def board(start: str, end: str, group: str = "resource") -> dict:
    s, e = parse_iso(start), parse_iso(end)
    if not s or not e or e <= s:
        bad_request("Give a start and an end for the schedule")
    if (e - s).days > 62:
        bad_request("Show at most two months at a time")
    start, end = iso(s), iso(e)
    stages = {st["id"]: st for st in jobs_svc.stages()}
    done = [sid for sid, st in stages.items() if st["is_done"]]
    rows_sched = _op_rows("o.start_at IS NOT NULL AND o.start_at < ? AND o.end_at > ?", [end, start])
    rows_queue = _op_rows(
        f"o.start_at IS NULL AND o.status != 'done' AND (j.stage_id IS NULL OR j.stage_id NOT IN ({db.placeholders(done)}))",
        done,
    )
    customers = _customers(rows_sched + rows_queue)
    blocks = [_block(o, stages, customers) for o in rows_sched]
    found = conflicts(blocks)
    for b in blocks:
        b["conflicts"] = found.get(b["id"], [])
    queue = [_block(o, stages, customers) for o in rows_queue]
    queue.sort(key=lambda b: (b["job_due_at"] is None, b["job_due_at"] or "", jobs_svc.PRIORITY_RANK.get(b["job_priority"], 2),
                              b["job_number"], b["sequence"]))
    if group == "user":
        people = _schedulable_people(start, end)
        rows = [{"id": p["id"], "name": p["name"], "color": p["color"], "subtitle": p["title"], "kind": "user"} for p in people]
        if any(not b["user_id"] for b in blocks):
            rows.append({"id": None, "name": "Unassigned", "kind": "user"})
    else:
        res = jobs_svc.resources(active_only=True)
        rows = [{"id": r["id"], "name": r["name"], "color": r["color"], "subtitle": r["kind"], "kind": "resource"} for r in res]
        used = {r["id"] for r in res}
        missing = {b["resource_id"] for b in blocks if b["resource_id"] and b["resource_id"] not in used}
        for rid, name in _names("resources", missing).items():
            rows.append({"id": rid, "name": f"{name} (inactive)", "kind": "resource"})
        if any(not b["resource_id"] for b in blocks):
            rows.append({"id": None, "name": "No equipment", "kind": "resource"})
    shifts = [{"user_id": s_["user_id"], "start_at": s_["start_at"], "end_at": s_["end_at"],
               "position": s_["position"]} for s_ in db.query(
        "SELECT s.user_id, s.start_at, s.end_at, p.name AS position FROM shifts s LEFT JOIN positions p ON p.id = s.position_id "
        "WHERE s.user_id IS NOT NULL AND s.status = 'published' AND s.start_at < ? AND s.end_at > ? ORDER BY s.start_at",
        end, start)]
    time_off = [{"user_id": uid, "start_at": iso(a), "end_at": iso(b), "kind": kind}
                for uid, spans in approved_time_off(start, end).items() for a, b, kind in spans]
    return {
        "start": start, "end": end, "group": group, "rows": rows, "blocks": blocks, "queue": queue,
        "shifts": shifts, "time_off": time_off, "work_hours": work_hours(),
        "windows": [{"start_at": iso(a), "end_at": iso(b)} for a, b in work_windows(s, e)],
    }


# -- auto-scheduler -----------------------------------------------------------------


class _Calendar:
    """Busy intervals per resource / person, plus availability rules."""

    def __init__(self, start: datetime, end: datetime):
        lo, hi = iso(start), iso(end)
        self.busy_resource: dict[int, list] = {}
        self.busy_user: dict[int, list] = {}
        for o in db.query(
            "SELECT o.resource_id, o.user_id, o.start_at, o.end_at FROM job_operations o JOIN jobs j ON j.id = o.job_id "
            "WHERE o.start_at IS NOT NULL AND o.status != 'done' AND j.archived_at IS NULL AND o.start_at < ? AND o.end_at > ?",
            hi, lo,
        ):
            span = (parse_iso(o["start_at"]), parse_iso(o["end_at"]))
            if o["resource_id"]:
                self.busy_resource.setdefault(o["resource_id"], []).append(span)
            if o["user_id"]:
                self.busy_user.setdefault(o["user_id"], []).append(span)
        self.shifts = published_shifts(lo, hi)
        self.use_shifts = bool(self.shifts)
        self.time_off = {u: [(a, b) for a, b, _k in v] for u, v in approved_time_off(lo, hi).items()}
        self.skill_people: dict[int, list[int]] = {}
        for r in db.query("SELECT ss.skill_id, ss.user_id FROM staff_skills ss JOIN users u ON u.id = ss.user_id "
                          "WHERE u.is_active = 1 ORDER BY ss.level DESC, ss.user_id"):
            self.skill_people.setdefault(r["skill_id"], []).append(r["user_id"])

    def resource_free(self, rid, s, e) -> bool:
        return not any(_overlaps(s, e, a, b) for a, b in self.busy_resource.get(rid, []))

    def person_free(self, uid, s, e) -> bool:
        if any(_overlaps(s, e, a, b) for a, b in self.busy_user.get(uid, [])):
            return False
        if any(_overlaps(s, e, a, b) for a, b in self.time_off.get(uid, [])):
            return False
        if self.use_shifts and not _covered(s, e, self.shifts.get(uid, [])):
            return False
        return True

    def book(self, rid, uid, s, e) -> None:
        if rid:
            self.busy_resource.setdefault(rid, []).append((s, e))
        if uid:
            self.busy_user.setdefault(uid, []).append((s, e))

    def candidate_starts(self, rid, people, window_start, window_end) -> list[datetime]:
        """Times worth trying in a window: its start and the end of every busy span."""
        points = {window_start}
        for a, b in self.busy_resource.get(rid, []) if rid else []:
            if window_start <= b < window_end:
                points.add(b)
        for uid in people:
            for a, b in self.busy_user.get(uid, []):
                if window_start <= b < window_end:
                    points.add(b)
            for a, b in self.shifts.get(uid, []):
                if window_start <= a < window_end:
                    points.add(a)
            for a, b in self.time_off.get(uid, []):
                if window_start <= b < window_end:
                    points.add(b)
        return sorted({_snap_up(p) for p in points})


def _snap_up(dt: datetime) -> datetime:
    minutes = dt.minute % SNAP_MINUTES
    if minutes == 0 and dt.second == 0 and dt.microsecond == 0:
        return dt
    return (dt + timedelta(minutes=SNAP_MINUTES - minutes)).replace(second=0, microsecond=0)


def _place(cal: _Calendar, op: dict, earliest: datetime, horizon_end: datetime) -> tuple[datetime, datetime, int | None] | None:
    duration = timedelta(minutes=max(5, op["duration_minutes"] or 60))
    rid = op["resource_id"]
    if op["user_id"]:
        people = [op["user_id"]]
        needs_person = True
    elif op["skill_id"]:
        people = cal.skill_people.get(op["skill_id"], [])
        needs_person = bool(people)
    else:
        people, needs_person = [], False
    for ws, we in work_windows(earliest, horizon_end):
        window_len = we - ws
        for start in cal.candidate_starts(rid, people, ws, we):
            if start < earliest:
                continue
            end = start + duration
            # Long steps may run past the end of the day; short ones must fit.
            if end > we and duration <= window_len:
                break
            if duration > window_len and start != ws:
                continue
            if rid and not cal.resource_free(rid, start, end):
                continue
            chosen = None
            if needs_person:
                chosen = next((u for u in people if cal.person_free(u, start, end)), None)
                if chosen is None:
                    continue
            return start, end, chosen
    return None


def auto_schedule(job_ids=None, start_from=None, apply: bool = False, user: dict | None = None) -> dict:
    """Plan every unscheduled, unfinished operation of open jobs (or just ``job_ids``)."""
    begin = parse_iso(start_from) if start_from else now()
    if not begin:
        bad_request("'from' isn't a valid time")
    begin = _snap_up(max(begin, now()))
    horizon_end = begin + timedelta(days=HORIZON_DAYS)
    done = jobs_svc.done_stage_ids()
    where = [f"j.archived_at IS NULL", f"(j.stage_id IS NULL OR j.stage_id NOT IN ({db.placeholders(done)}))"]
    params: list = list(done)
    if job_ids:
        ids = [int(i) for i in job_ids]
        where.append(f"j.id IN ({db.placeholders(ids)})")
        params += ids
    jobs = db.query(f"SELECT j.* FROM jobs j WHERE {' AND '.join(where)}", params)
    jobs.sort(key=lambda j: (j["due_at"] is None, j["due_at"] or "", jobs_svc.PRIORITY_RANK.get(j["priority"], 2),
                             j["created_at"], j["id"]))
    cal = _Calendar(begin - timedelta(days=1), horizon_end)
    placements, unplaced = [], []
    for job in jobs:
        ops = db.query("SELECT * FROM job_operations WHERE job_id = ? ORDER BY sequence, id", job["id"])
        if not any(o["start_at"] is None and o["status"] != "done" for o in ops):
            continue
        cursor = begin
        for op in ops:
            if op["status"] == "done":
                continue
            if op["start_at"]:
                cursor = max(cursor, parse_iso(op["end_at"]))
                continue
            spot = _place(cal, op, cursor, horizon_end)
            if not spot:
                unplaced.append({"operation_id": op["id"], "job_id": job["id"], "job_number": job["number"],
                                 "name": op["name"], "reason": "No free time in the next 60 days"})
                break  # later steps depend on this one
            s, e, person = spot
            uid = op["user_id"] or person
            cal.book(op["resource_id"], uid, s, e)
            cursor = e
            placements.append({
                "operation_id": op["id"], "job_id": job["id"], "job_number": job["number"], "job_title": job["title"],
                "name": op["name"], "start_at": iso(s), "end_at": iso(e), "resource_id": op["resource_id"],
                "user_id": uid, "late": bool(job["due_at"] and e > parse_iso(job["due_at"])),
            })
    if apply and placements:
        stamp = now_iso()
        with db.transaction():
            per_job: dict[int, int] = {}
            for p in placements:
                db.execute(
                    "UPDATE job_operations SET start_at = ?, end_at = ?, user_id = COALESCE(user_id, ?) "
                    "WHERE id = ? AND start_at IS NULL",
                    p["start_at"], p["end_at"], p["user_id"], p["operation_id"],
                )
                per_job[p["job_id"]] = per_job.get(p["job_id"], 0) + 1
            for job_id, n in per_job.items():
                jobs_svc.add_activity(job_id, "auto_scheduled", user["id"] if user else None, {"count": n}, at=stamp)
                jobs_svc.touch(job_id, "scheduled", schedule=True)
    return {"placements": placements, "unplaced": unplaced, "applied": bool(apply and placements),
            "from": iso(begin)}
