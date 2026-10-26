"""Calendars and events.

* Recurrence: an RFC 5545 subset (FREQ=DAILY|WEEKLY|MONTHLY|YEARLY with INTERVAL,
  BYDAY (incl. "2TU"/"-1FR" for monthly), BYMONTHDAY, COUNT, UNTIL) plus EXDATE.
  Occurrences are generated on the wall clock of the org timezone, so a weekly 8am
  meeting stays at 8am when daylight saving changes.
* Overlays: read-only items from other modules (published shifts, job due dates,
  scheduled job work, approved time off) shown alongside events.
* ICS: per-calendar export, a private per-person feed (/feeds/<token>.ics) and
  read-only subscriptions to outside calendars. Exports expand recurring events into
  single VEVENTs, which every calendar app understands without VTIMEZONE data.
* Reminders: one notification per occurrence, reminder_minutes before it starts.
"""

from __future__ import annotations

import calendar as pycal
import ipaddress
import re
import socket
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from urllib.parse import urljoin, urlparse

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.services import notify, settings
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.util import UTC, get_zone, iso, now, now_iso, parse_date, parse_iso
from pps_tools.switchboard.web import bad_request, forbidden, not_found

WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
FREQS = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
MAX_ITERATIONS = 20000
MAX_REMINDER_MINUTES = 28 * 24 * 60


# -- recurrence ---------------------------------------------------------------------


@dataclass
class Rule:
    freq: str
    interval: int = 1
    count: int | None = None
    until: datetime | None = None          # aware UTC
    byday: list[tuple[int | None, int]] = field(default_factory=list)  # (ordinal, weekday 0=Mon)
    bymonthday: list[int] = field(default_factory=list)


def _parse_until(value: str, tz) -> datetime:
    value = value.strip()
    if re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value, "%Y%m%d").date()
        # inclusive date: through the end of that local day
        return datetime.combine(d, time(23, 59, 59), tzinfo=tz).astimezone(UTC)
    m = re.fullmatch(r"(\d{8}T\d{6})(Z?)", value)
    if not m:
        raise ValueError(f"bad UNTIL {value!r}")
    naive = datetime.strptime(m.group(1), "%Y%m%dT%H%M%S")
    return naive.replace(tzinfo=UTC if m.group(2) else tz).astimezone(UTC)


def parse_rrule(rule: str, tz=UTC) -> Rule:
    parts: dict[str, str] = {}
    text = rule.strip()
    if text.upper().startswith("RRULE:"):
        text = text[6:]
    for piece in text.split(";"):
        if "=" in piece:
            k, v = piece.split("=", 1)
            parts[k.strip().upper()] = v.strip()
    freq = parts.get("FREQ", "").upper()
    if freq not in FREQS:
        raise ValueError("FREQ must be DAILY, WEEKLY, MONTHLY or YEARLY")
    interval = int(parts.get("INTERVAL", "1") or 1)
    if interval < 1 or interval > 999:
        raise ValueError("INTERVAL must be between 1 and 999")
    count = int(parts["COUNT"]) if parts.get("COUNT") else None
    if count is not None and (count < 1 or count > 5000):
        raise ValueError("COUNT must be between 1 and 5000")
    until = _parse_until(parts["UNTIL"], tz) if parts.get("UNTIL") else None
    byday = []
    for item in [x for x in parts.get("BYDAY", "").upper().split(",") if x]:
        m = re.fullmatch(r"([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)", item)
        if not m:
            raise ValueError(f"bad BYDAY {item!r}")
        ordinal = int(m.group(1)) if m.group(1) else None
        if ordinal is not None and (ordinal == 0 or abs(ordinal) > 5):
            raise ValueError(f"bad BYDAY {item!r}")
        byday.append((ordinal, WEEKDAYS.index(m.group(2))))
    bymonthday = []
    for item in [x for x in parts.get("BYMONTHDAY", "").split(",") if x]:
        d = int(item)
        if d == 0 or abs(d) > 31:
            raise ValueError(f"bad BYMONTHDAY {item!r}")
        bymonthday.append(d)
    return Rule(freq, interval, count, until, byday, bymonthday)


def normalize_rrule(rule: str | None, tz=UTC) -> str | None:
    """Validate and canonicalize; raises a 400 for anything we can't expand."""
    if not rule or not str(rule).strip():
        return None
    try:
        r = parse_rrule(str(rule), tz)
    except (ValueError, TypeError) as exc:
        bad_request(f"Can't use that repeat rule: {exc}", code="bad_rrule")
    out = [f"FREQ={r.freq}"]
    if r.interval != 1:
        out.append(f"INTERVAL={r.interval}")
    if r.byday:
        out.append("BYDAY=" + ",".join(f"{o if o else ''}{WEEKDAYS[d]}" for o, d in r.byday))
    if r.bymonthday:
        out.append("BYMONTHDAY=" + ",".join(str(d) for d in r.bymonthday))
    if r.count:
        out.append(f"COUNT={r.count}")
    if r.until:
        out.append("UNTIL=" + r.until.strftime("%Y%m%dT%H%M%SZ"))
    return ";".join(out)


def _add_months(year: int, month: int, n: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + n
    return idx // 12, idx % 12 + 1


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> int | None:
    last = pycal.monthrange(year, month)[1]
    days = [d for d in range(1, last + 1) if date(year, month, d).weekday() == weekday]
    if ordinal > 0:
        return days[ordinal - 1] if ordinal <= len(days) else None
    return days[ordinal] if -ordinal <= len(days) else None


def _iterate(rule: Rule, start: datetime, skip: int = 0):
    """Naive local datetimes of the series in order (DTSTART first, per RFC 5545).
    ``skip`` jumps ahead that many periods (only valid without COUNT)."""
    if skip == 0:
        yield start
    t = start.time()
    if rule.freq == "DAILY":
        days = {d for _, d in rule.byday}
        k = max(1, skip)
        while True:
            cand = start + timedelta(days=k * rule.interval)
            if not days or cand.weekday() in days:
                yield cand
            k += 1
    elif rule.freq == "WEEKLY":
        weekdays = sorted({d for _, d in rule.byday}) or [start.weekday()]
        week0 = datetime.combine(start.date() - timedelta(days=start.weekday()), t)
        k = skip
        while True:
            base = week0 + timedelta(weeks=k * rule.interval)
            for wd in weekdays:
                cand = base + timedelta(days=wd)
                if cand > start:
                    yield cand
            k += 1
    elif rule.freq == "MONTHLY":
        k = skip
        while True:
            y, m = _add_months(start.year, start.month, k * rule.interval)
            last = pycal.monthrange(y, m)[1]
            days: set[int] = set()
            if rule.bymonthday:
                for d in rule.bymonthday:
                    day = d if d > 0 else last + d + 1
                    if 1 <= day <= last:
                        days.add(day)
            elif rule.byday:
                for ordinal, wd in rule.byday:
                    if ordinal:
                        day = _nth_weekday(y, m, wd, ordinal)
                        if day:
                            days.add(day)
                    else:
                        days.update(d for d in range(1, last + 1) if date(y, m, d).weekday() == wd)
            elif start.day <= last:
                days.add(start.day)
            for day in sorted(days):
                cand = datetime.combine(date(y, m, day), t)
                if cand > start:
                    yield cand
            k += 1
    else:  # YEARLY
        k = max(1, skip)
        while True:
            y = start.year + k * rule.interval
            try:
                cand = datetime.combine(date(y, start.month, start.day), t)
            except ValueError:  # Feb 29
                k += 1
                continue
            yield cand
            k += 1


def _skip_periods(rule: Rule, start: datetime, range_start: datetime) -> int:
    if rule.count:
        return 0
    if range_start <= start:
        return 0
    if rule.freq == "DAILY":
        return max(0, (range_start - start).days // rule.interval - 1)
    if rule.freq == "WEEKLY":
        week0 = start.date() - timedelta(days=start.weekday())
        return max(0, ((range_start.date() - week0).days // 7) // rule.interval - 1)
    if rule.freq == "MONTHLY":
        months = (range_start.year - start.year) * 12 + (range_start.month - start.month)
        return max(0, months // rule.interval - 1)
    return max(0, (range_start.year - start.year) // rule.interval - 1)


def occurrences(start_at: str, end_at: str, rrule: str | None, exdates: list[str] | None,
                range_start: datetime, range_end: datetime, tz) -> list[tuple[datetime, datetime]]:
    """[(start, end)] aware-UTC occurrences overlapping [range_start, range_end)."""
    start = parse_iso(start_at)
    end = parse_iso(end_at)
    if not rrule:
        return [(start, end)] if start < range_end and end > range_start else []
    rule = parse_rrule(rrule, tz)
    local_start = start.astimezone(tz).replace(tzinfo=None)
    wall = end.astimezone(tz).replace(tzinfo=None) - local_start
    skipped = set(exdates or [])
    rs_local = range_start.astimezone(tz).replace(tzinfo=None) - wall
    out = []
    n = 0
    for i, naive in enumerate(_iterate(rule, local_start, _skip_periods(rule, local_start, rs_local))):
        if i > MAX_ITERATIONS:
            break
        occ_start = naive.replace(tzinfo=tz).astimezone(UTC)
        if rule.until and occ_start > rule.until:
            break
        n += 1
        if rule.count and n > rule.count:
            break
        if occ_start >= range_end:
            break
        occ_end = (naive + wall).replace(tzinfo=tz).astimezone(UTC)
        if occ_end <= range_start and not (occ_end == occ_start == range_start):
            continue
        if iso(occ_start) in skipped:
            continue
        out.append((occ_start, occ_end))
    return out


def rrule_until_before(rrule: str, cutoff: datetime, tz) -> str:
    """The same rule, ending just before ``cutoff`` (COUNT becomes UNTIL)."""
    r = parse_rrule(rrule, tz)
    r.count = None
    r.until = cutoff - timedelta(seconds=1)
    out = [f"FREQ={r.freq}"]
    if r.interval != 1:
        out.append(f"INTERVAL={r.interval}")
    if r.byday:
        out.append("BYDAY=" + ",".join(f"{o if o else ''}{WEEKDAYS[d]}" for o, d in r.byday))
    if r.bymonthday:
        out.append("BYMONTHDAY=" + ",".join(str(d) for d in r.bymonthday))
    out.append("UNTIL=" + r.until.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ"))
    return ";".join(out)


def remaining_rule(ev: dict, tz) -> str:
    """The rule for the rest of a series split off with "this and following": a COUNT
    becomes an UNTIL at the original series' last occurrence."""
    rule = parse_rrule(ev["rrule"], tz)
    parts = [p for p in ev["rrule"].split(";") if not p.upper().startswith(("COUNT=", "UNTIL="))]
    if rule.count:
        occ = occurrences(ev["start_at"], ev["end_at"], ev["rrule"], [], parse_iso(ev["start_at"]),
                          parse_iso(ev["start_at"]) + timedelta(days=366 * 50), tz)
        if occ:
            parts.append("UNTIL=" + occ[-1][0].strftime("%Y%m%dT%H%M%SZ"))
    elif rule.until:
        parts.append("UNTIL=" + rule.until.strftime("%Y%m%dT%H%M%SZ"))
    return ";".join(parts)


# -- calendars ----------------------------------------------------------------------


def org_tz():
    return settings.timezone()


def personal_calendar(user: dict) -> dict:
    cal = db.one("SELECT * FROM calendars WHERE kind = 'personal' AND owner_user_id = ? ORDER BY id LIMIT 1", user["id"])
    if cal:
        return cal
    with db.transaction():
        cid = db.insert("calendars", {"name": user["name"], "color": user.get("color") or "#3b5bdb", "kind": "personal",
                                      "owner_user_id": user["id"], "created_by": user["id"], "created_at": now_iso()})
    return db.one("SELECT * FROM calendars WHERE id = ?", cid)


def visible_calendars(user: dict) -> list[dict]:
    return db.query(
        "SELECT * FROM calendars WHERE kind = 'shared' OR owner_user_id = ? OR (kind = 'subscription' AND owner_user_id IS NULL) "
        "ORDER BY CASE kind WHEN 'personal' THEN 0 WHEN 'shared' THEN 1 ELSE 2 END, name COLLATE NOCASE",
        user["id"],
    )


def can_see_calendar(user: dict, cal: dict) -> bool:
    if cal["kind"] == "shared":
        return True
    if cal["kind"] == "subscription" and cal["owner_user_id"] is None:
        return True
    return cal["owner_user_id"] == user["id"]


def can_write_calendar(user: dict, cal: dict) -> bool:
    if cal["kind"] == "subscription":
        return False
    if cal["kind"] == "personal":
        return cal["owner_user_id"] == user["id"]
    return True


def can_manage_calendar(user: dict, cal: dict) -> bool:
    if cal["kind"] == "personal" or (cal["kind"] == "subscription" and cal["owner_user_id"]):
        return cal["owner_user_id"] == user["id"]
    return user["role"] in ("owner", "admin", "manager") or cal["created_by"] == user["id"]


def get_calendar_for(user: dict, calendar_id: int) -> dict:
    cal = db.one("SELECT * FROM calendars WHERE id = ?", calendar_id)
    if not cal or not can_see_calendar(user, cal):
        not_found("Calendar not found")
    return cal


def serialize_calendar(user: dict, cal: dict) -> dict:
    return {
        "id": cal["id"], "name": cal["name"], "color": cal["color"], "kind": cal["kind"],
        "owner_user_id": cal["owner_user_id"], "is_mine": cal["owner_user_id"] == user["id"],
        "ics_url": cal["ics_url"] if can_manage_calendar(user, cal) else None,
        "last_sync_at": cal["last_sync_at"], "sync_error": cal["sync_error"],
        "can_write": can_write_calendar(user, cal), "can_manage": can_manage_calendar(user, cal),
    }


# -- events -------------------------------------------------------------------------


def attendee_ids(ev: dict) -> list[int]:
    out = []
    for a in db.jload(ev["attendees_json"], []) or []:
        if isinstance(a, dict) and a.get("user_id"):
            out.append(int(a["user_id"]))
    return out


def can_see_event(user: dict, ev: dict, cal: dict | None = None) -> bool:
    cal = cal or db.one("SELECT * FROM calendars WHERE id = ?", ev["calendar_id"])
    return bool(cal) and (can_see_calendar(user, cal) or user["id"] in attendee_ids(ev) or ev["created_by"] == user["id"])


def can_edit_event(user: dict, ev: dict, cal: dict | None = None) -> bool:
    cal = cal or db.one("SELECT * FROM calendars WHERE id = ?", ev["calendar_id"])
    if not cal or not can_write_calendar(user, cal):
        return False
    if cal["kind"] == "personal":
        return True
    return ev["created_by"] == user["id"] or user["role"] != "staff"


def get_event_for(user: dict, event_id: int) -> tuple[dict, dict]:
    ev = db.one("SELECT * FROM calendar_events WHERE id = ?", event_id)
    if not ev:
        not_found("Event not found")
    cal = db.one("SELECT * FROM calendars WHERE id = ?", ev["calendar_id"])
    if not can_see_event(user, ev, cal):
        not_found("Event not found")
    return ev, cal


def _local_dates(start: datetime, end: datetime, tz) -> tuple[str, str]:
    s = start.astimezone(tz).date()
    e = (end.astimezone(tz) - timedelta(seconds=1)).date()
    return s.isoformat(), max(s, e).isoformat()


def serialize_occurrence(user: dict, ev: dict, cal: dict, start: datetime, end: datetime, tz) -> dict:
    recurring = bool(ev["rrule"])
    item = {
        "id": f"{ev['id']}:{iso(start)}" if recurring else str(ev["id"]),
        "kind": "event",
        "event_id": ev["id"],
        "calendar_id": ev["calendar_id"],
        "title": ev["title"],
        "description": ev["description"],
        "location": ev["location"],
        "start": iso(start),
        "end": iso(end),
        "all_day": bool(ev["all_day"]),
        "recurring": recurring,
        "rrule": ev["rrule"],
        "original_start": iso(start) if recurring else ev["original_start"],
        "parent_id": ev["parent_id"],
        "attendees": db.jload(ev["attendees_json"], []),
        "reminder_minutes": ev["reminder_minutes"],
        "color": ev["color"] or cal["color"],
        "created_by": ev["created_by"],
        "conversation_id": ev["conversation_id"],
        "job_id": ev["job_id"],
        "can_edit": can_edit_event(user, ev, cal),
        "read_only": not can_edit_event(user, ev, cal),
    }
    if ev["all_day"]:
        item["start_date"], item["end_date"] = _local_dates(start, end, tz)
    return item


def list_occurrences(user: dict, range_start: datetime, range_end: datetime,
                     calendar_ids: list[int] | None = None, only_mine: bool = False) -> list[dict]:
    tz = org_tz()
    cals = {c["id"]: c for c in db.query("SELECT * FROM calendars")}
    rows = db.query(
        "SELECT * FROM calendar_events WHERE (rrule IS NULL AND start_at < ? AND end_at > ?) "
        "OR (rrule IS NOT NULL AND start_at < ?) ORDER BY start_at",
        iso(range_end), iso(range_start), iso(range_end),
    )
    out = []
    for ev in rows:
        cal = cals.get(ev["calendar_id"])
        if not cal:
            continue
        mine = ev["created_by"] == user["id"] or user["id"] in attendee_ids(ev)
        if only_mine and not mine:
            continue
        if not (can_see_calendar(user, cal) or mine):
            continue
        if calendar_ids is not None and ev["calendar_id"] not in calendar_ids and not (mine and cal["kind"] == "personal"
                                                                                       and cal["owner_user_id"] != user["id"]):
            continue
        try:
            occ = occurrences(ev["start_at"], ev["end_at"], ev["rrule"], db.jload(ev["exdates_json"], []),
                              range_start, range_end, tz)
        except ValueError:
            occ = []
        out.extend(serialize_occurrence(user, ev, cal, s, e, tz) for s, e in occ)
    out.sort(key=lambda o: (o["start"], not o["all_day"], o["title"]))
    return out


def _times_from(data: dict, tz, existing: dict | None = None) -> tuple[str, str, int]:
    all_day = bool(data["all_day"]) if "all_day" in data else bool(existing and existing["all_day"])
    if all_day:
        sd = parse_date(data.get("start_date")) or (parse_iso(data.get("start_at")).astimezone(tz).date()
                                                    if data.get("start_at") else None)
        if not sd and existing:
            sd = parse_iso(existing["start_at"]).astimezone(tz).date()
        if not sd:
            bad_request("Pick a date for the event", code="validation")
        ed = parse_date(data.get("end_date")) or sd
        if ed < sd:
            bad_request("The event can't end before it starts", code="validation")
        start = datetime.combine(sd, time(0, 0), tzinfo=tz)
        end = datetime.combine(ed + timedelta(days=1), time(0, 0), tzinfo=tz)
        return iso(start), iso(end), 1
    start = parse_iso(data.get("start_at")) if data.get("start_at") else (parse_iso(existing["start_at"]) if existing else None)
    if not start:
        bad_request("Pick a start time for the event", code="validation")
    if data.get("end_at"):
        end = parse_iso(data["end_at"])
    elif existing and "start_at" not in data:
        end = parse_iso(existing["end_at"])
    elif existing:
        end = start + (parse_iso(existing["end_at"]) - parse_iso(existing["start_at"]))
    else:
        end = start + timedelta(hours=1)
    if not end or end <= start:
        bad_request("The event must end after it starts", code="validation")
    return iso(start), iso(end), 0


def _clean_attendees(raw) -> list[dict]:
    out, seen = [], set()
    for a in raw or []:
        if isinstance(a, (int, str)) and str(a).isdigit():
            a = {"user_id": int(a)}
        if not isinstance(a, dict):
            continue
        if a.get("user_id"):
            uid = int(a["user_id"])
            if uid in seen or not users_svc.get(uid):
                continue
            seen.add(uid)
            out.append({"user_id": uid})
        elif a.get("email"):
            key = str(a["email"]).strip().lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"email": key, "name": (a.get("name") or "").strip() or None})
    return out


def _event_values(user: dict, data: dict, existing: dict | None = None) -> dict:
    tz = org_tz()
    values: dict = {}
    if "title" in data or not existing:
        title = (data.get("title") or "").strip()
        if not title:
            bad_request("Give the event a title", code="validation")
        values["title"] = title[:300]
    for f in ("description", "location", "color"):
        if f in data:
            values[f] = (data.get(f) or "").strip() or None
    if not existing or any(k in data for k in ("start_at", "end_at", "start_date", "end_date", "all_day")):
        values["start_at"], values["end_at"], values["all_day"] = _times_from(data, tz, existing)
    if "rrule" in data:
        values["rrule"] = normalize_rrule(data.get("rrule"), tz)
    if "attendees" in data:
        values["attendees_json"] = db.jdump(_clean_attendees(data.get("attendees")))
    if "reminder_minutes" in data:
        rm = data.get("reminder_minutes")
        if rm in (None, ""):
            values["reminder_minutes"] = None
        else:
            rm = int(rm)
            if rm < 0 or rm > MAX_REMINDER_MINUTES:
                bad_request("Reminder must be between 0 minutes and 4 weeks before")
            values["reminder_minutes"] = rm
    if "calendar_id" in data:
        cal = get_calendar_for(user, int(data["calendar_id"]))
        if not can_write_calendar(user, cal):
            forbidden("You can't add events to that calendar")
        values["calendar_id"] = cal["id"]
    for f in ("conversation_id", "job_id"):
        if f in data:
            values[f] = int(data[f]) if data.get(f) not in (None, "") else None
    return values


def _notify_attendees(user: dict, ev: dict, user_ids, verb: str) -> None:
    ids = [u for u in user_ids if u != user["id"]]
    if not ids:
        return
    tz = org_tz()
    start = parse_iso(ev["start_at"]).astimezone(tz)
    when = f"{start:%a %b} {start.day}" + ("" if ev["all_day"] else f", {start.hour % 12 or 12}:{start:%M} {'AM' if start.hour < 12 else 'PM'}")
    notify.notify(ids, "reminder", f"{user['name']} {verb}: {ev['title']}", body=when + (f" · {ev['location']}" if ev["location"] else ""),
                  link=f"/calendar?event={ev['id']}&date={start.date().isoformat()}", actor_id=user["id"],
                  entity_type="event", entity_id=ev["id"])


def _emit(ev: dict) -> None:
    realtime.emit("calendar.changed", {"event_id": ev["id"], "calendar_id": ev["calendar_id"]})


def create_event(user: dict, data: dict) -> dict:
    if not data.get("calendar_id"):
        data = {**data, "calendar_id": personal_calendar(user)["id"]}
    values = _event_values(user, data)
    stamp = now_iso()
    values.update({"created_by": user["id"], "created_at": stamp, "updated_at": stamp})
    values.setdefault("attendees_json", "[]")
    with db.transaction():
        eid = db.insert("calendar_events", values)
        ev = db.one("SELECT * FROM calendar_events WHERE id = ?", eid)
        _notify_attendees(user, ev, attendee_ids(ev), "invited you")
        _emit(ev)
    return ev


def _override_from(series: dict, original_start: str, values: dict, user: dict) -> int:
    """A standalone copy of one occurrence, with ``values`` applied."""
    occ_start = parse_iso(original_start)
    duration = parse_iso(series["end_at"]) - parse_iso(series["start_at"])
    row = {k: series[k] for k in ("calendar_id", "title", "description", "location", "all_day", "attendees_json",
                                  "reminder_minutes", "color", "conversation_id", "job_id")}
    row.update({"start_at": iso(occ_start), "end_at": iso(occ_start + duration)})
    row.update({k: v for k, v in values.items() if k != "rrule"})
    stamp = now_iso()
    row.update({"rrule": None, "exdates_json": "[]", "parent_id": series["id"], "original_start": iso(occ_start),
                "created_by": series["created_by"] or user["id"], "created_at": stamp, "updated_at": stamp})
    return db.insert("calendar_events", row)


def _add_exdate(ev: dict, original_start: str) -> None:
    ex = db.jload(ev["exdates_json"], []) or []
    key = iso(parse_iso(original_start))
    if key not in ex:
        ex.append(key)
        db.update("calendar_events", ev["id"], {"exdates_json": db.jdump(sorted(ex)), "updated_at": now_iso()})


def update_event(user: dict, event_id: int, data: dict, scope: str = "all", original_start: str | None = None) -> dict:
    ev, cal = get_event_for(user, event_id)
    if not can_edit_event(user, ev, cal):
        forbidden("You can't change this event")
    tz = org_tz()
    if scope not in ("all", "one", "following"):
        bad_request("scope must be all, one or following")
    if scope != "all" and not ev["rrule"]:
        scope = "all"
    if scope != "all" and not parse_iso(original_start):
        bad_request("original_start is required to change one occurrence")
    before = set(attendee_ids(ev))
    with db.transaction():
        if scope == "all":
            shifted = dict(data)
            # Moving one occurrence of a series with scope=all shifts the whole series by
            # the same amount (instead of re-anchoring the series on that occurrence).
            if ev["rrule"] and original_start and parse_iso(original_start):
                if data.get("start_at") and not data.get("all_day") and not ev["all_day"]:
                    delta = parse_iso(data["start_at"]) - parse_iso(original_start)
                    new_len = (parse_iso(data["end_at"]) - parse_iso(data["start_at"])) if data.get("end_at") else \
                        (parse_iso(ev["end_at"]) - parse_iso(ev["start_at"]))
                    shifted["start_at"] = iso(parse_iso(ev["start_at"]) + delta)
                    shifted["end_at"] = iso(parse_iso(shifted["start_at"]) + new_len)
                elif data.get("start_date") and ev["all_day"] and data.get("all_day", True):
                    occ_day = parse_iso(original_start).astimezone(tz).date()
                    new_start = parse_date(data["start_date"])
                    new_end = parse_date(data.get("end_date")) or new_start
                    series_start = parse_iso(ev["start_at"]).astimezone(tz).date()
                    shifted["start_date"] = (series_start + (new_start - occ_day)).isoformat()
                    shifted["end_date"] = (series_start + (new_start - occ_day) + (new_end - new_start)).isoformat()
            values = _event_values(user, shifted, ev)
            if values:
                values["updated_at"] = now_iso()
                db.update("calendar_events", event_id, values)
            result_id = event_id
        elif scope == "one":
            values = _event_values(user, data, ev)
            _add_exdate(ev, original_start)
            result_id = _override_from(ev, original_start, values, user)
        else:  # following
            cutoff = parse_iso(original_start)
            values = _event_values(user, data, ev)
            first_start = parse_iso(ev["start_at"])
            if cutoff <= first_start:
                values["updated_at"] = now_iso()
                db.update("calendar_events", event_id, values)
                result_id = event_id
            else:
                rest_rule = remaining_rule(ev, tz)
                db.update("calendar_events", event_id, {"rrule": rrule_until_before(ev["rrule"], cutoff, tz),
                                                        "updated_at": now_iso()})
                duration = parse_iso(ev["end_at"]) - first_start
                row = {k: ev[k] for k in ("calendar_id", "title", "description", "location", "all_day", "attendees_json",
                                          "reminder_minutes", "color", "conversation_id", "job_id", "created_by")}
                row.update({"start_at": iso(cutoff), "end_at": iso(cutoff + duration),
                            "rrule": rest_rule, "exdates_json": db.jdump(
                                [x for x in db.jload(ev["exdates_json"], []) if x >= iso(cutoff)])})
                row.update(values)
                stamp = now_iso()
                row.update({"created_at": stamp, "updated_at": stamp})
                result_id = db.insert("calendar_events", row)
                db.execute("DELETE FROM calendar_events WHERE parent_id = ? AND original_start >= ?", event_id, iso(cutoff))
        new = db.one("SELECT * FROM calendar_events WHERE id = ?", result_id)
        added = set(attendee_ids(new)) - before
        if added:
            _notify_attendees(user, new, added, "invited you")
        time_changed = any(k in data for k in ("start_at", "end_at", "start_date", "end_date", "all_day"))
        if time_changed and before & set(attendee_ids(new)):
            _notify_attendees(user, new, before & set(attendee_ids(new)), "moved")
        _emit(new)
    return new


def delete_event(user: dict, event_id: int, scope: str = "all", original_start: str | None = None) -> None:
    ev, cal = get_event_for(user, event_id)
    if not can_edit_event(user, ev, cal):
        forbidden("You can't delete this event")
    tz = org_tz()
    with db.transaction():
        if scope == "one" and ev["rrule"]:
            if not parse_iso(original_start):
                bad_request("original_start is required to delete one occurrence")
            _add_exdate(ev, original_start)
        elif scope == "following" and ev["rrule"] and parse_iso(original_start) and parse_iso(original_start) > parse_iso(ev["start_at"]):
            cutoff = parse_iso(original_start)
            db.update("calendar_events", event_id, {"rrule": rrule_until_before(ev["rrule"], cutoff, tz), "updated_at": now_iso()})
            db.execute("DELETE FROM calendar_events WHERE parent_id = ? AND original_start >= ?", event_id, iso(cutoff))
        else:
            db.delete("calendar_events", event_id)
        _emit(ev)


# -- overlays from other modules ------------------------------------------------------

OVERLAYS = ("shifts", "all_shifts", "jobs", "operations", "timeoff")


def _safe(sql: str, params: list) -> list[dict]:
    try:
        return db.query(sql, params)
    except sqlite3.OperationalError:
        return []


def overlay_items(user: dict, range_start: datetime, range_end: datetime, kinds) -> list[dict]:
    tz = org_tz()
    rs, re_ = iso(range_start), iso(range_end)
    out: list[dict] = []
    kinds = set(kinds or [])
    if kinds & {"shifts", "all_shifts"}:
        mine_only = "all_shifts" not in kinds
        rows = _safe(
            "SELECT s.*, p.name AS position_name, p.color AS position_color, l.name AS location_name "
            "FROM shifts s LEFT JOIN positions p ON p.id = s.position_id LEFT JOIN locations l ON l.id = s.location_id "
            "WHERE s.status = 'published' AND s.user_id IS NOT NULL AND s.start_at < ? AND s.end_at > ?"
            + (" AND s.user_id = ?" if mine_only else "") + " ORDER BY s.start_at",
            [re_, rs] + ([user["id"]] if mine_only else []),
        )
        for s in rows:
            who = users_svc.get(s["user_id"])
            mine = s["user_id"] == user["id"]
            label = s["position_name"] or "Shift"
            out.append({
                "id": f"shift:{s['id']}", "kind": "shift", "read_only": True,
                "title": (f"Shift · {label}" if mine else f"{who['name'] if who else 'Someone'} · {label}"),
                "subtitle": s["location_name"], "start": s["start_at"], "end": s["end_at"], "all_day": False,
                "color": s["position_color"] or (who or {}).get("color") or "#868e96",
                "user_id": s["user_id"], "url": "/schedule",
            })
    if "jobs" in kinds:
        for j in _safe(
            "SELECT j.id, j.number, j.title, j.due_at, j.completed_at, s.name AS stage_name, s.color AS stage_color "
            "FROM jobs j LEFT JOIN job_stages s ON s.id = j.stage_id WHERE j.archived_at IS NULL AND j.due_at >= ? AND j.due_at < ? "
            "ORDER BY j.due_at", [rs, re_],
        ):
            due = parse_iso(j["due_at"])
            out.append({
                "id": f"job:{j['id']}", "kind": "job_due", "read_only": True,
                "title": f"Due: {j['number']} {j['title']}", "subtitle": j["stage_name"],
                "start": j["due_at"], "end": iso(due + timedelta(minutes=30)), "all_day": False,
                "done": bool(j["completed_at"]), "color": j["stage_color"] or "#e8590c", "url": f"/jobs/{j['id']}",
            })
    if "operations" in kinds:
        for o in _safe(
            "SELECT o.id, o.name, o.start_at, o.end_at, o.status, o.user_id, j.id AS job_id, j.number, j.title, "
            "r.name AS resource_name FROM job_operations o JOIN jobs j ON j.id = o.job_id "
            "LEFT JOIN resources r ON r.id = o.resource_id "
            "WHERE o.user_id = ? AND o.start_at IS NOT NULL AND o.start_at < ? AND o.end_at > ? ORDER BY o.start_at",
            [user["id"], re_, rs],
        ):
            out.append({
                "id": f"op:{o['id']}", "kind": "operation", "read_only": True,
                "title": f"{o['number']} · {o['name']}", "subtitle": o["resource_name"] or o["title"],
                "start": o["start_at"], "end": o["end_at"], "all_day": False, "done": o["status"] == "done",
                "color": "#7048e8", "url": f"/jobs/{o['job_id']}",
            })
    if "timeoff" in kinds:
        d0 = range_start.astimezone(tz).date().isoformat()
        d1 = range_end.astimezone(tz).date().isoformat()
        for t in _safe(
            "SELECT * FROM time_off_requests WHERE status = 'approved' AND start_date <= ? AND end_date >= ? ORDER BY start_date",
            [d1, d0],
        ):
            who = users_svc.get(t["user_id"])
            sd, ed = parse_date(t["start_date"]), parse_date(t["end_date"])
            partial = bool(t["start_time"] and t["end_time"] and sd == ed)
            if partial:
                start = datetime.combine(sd, time.fromisoformat(t["start_time"]), tzinfo=tz)
                end = datetime.combine(sd, time.fromisoformat(t["end_time"]), tzinfo=tz)
            else:
                start = datetime.combine(sd, time(0, 0), tzinfo=tz)
                end = datetime.combine(ed + timedelta(days=1), time(0, 0), tzinfo=tz)
            item = {
                "id": f"timeoff:{t['id']}", "kind": "timeoff", "read_only": True,
                "title": f"{who['name'] if who else 'Someone'} · {t['kind'].replace('_', ' ')}",
                "start": iso(start), "end": iso(end), "all_day": not partial, "color": "#868e96",
                "user_id": t["user_id"], "url": "/schedule/timeoff",
            }
            if not partial:
                item["start_date"], item["end_date"] = sd.isoformat(), ed.isoformat()
            out.append(item)
    for item in out:
        if item.get("all_day") and "start_date" not in item:
            item["start_date"], item["end_date"] = _local_dates(parse_iso(item["start"]), parse_iso(item["end"]), tz)
    return out


# -- ICS ----------------------------------------------------------------------------


def ics_escape(text: str | None) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def _ics_dt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def vevent(uid: str, summary: str, start: datetime, end: datetime, all_day: bool = False, description: str | None = None,
           location: str | None = None, url: str | None = None, tz=UTC, stamp: datetime | None = None) -> list[str]:
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{_ics_dt(stamp or now())}"]
    if all_day:
        sd = start.astimezone(tz).date()
        ed = end.astimezone(tz).date()
        if ed <= sd:
            ed = sd + timedelta(days=1)
        lines += [f"DTSTART;VALUE=DATE:{sd:%Y%m%d}", f"DTEND;VALUE=DATE:{ed:%Y%m%d}"]
    else:
        lines += [f"DTSTART:{_ics_dt(start)}", f"DTEND:{_ics_dt(end)}"]
    lines.append(f"SUMMARY:{ics_escape(summary)}")
    if description:
        lines.append(f"DESCRIPTION:{ics_escape(description)}")
    if location:
        lines.append(f"LOCATION:{ics_escape(location)}")
    if url:
        lines.append(f"URL:{url}")
    lines.append("END:VEVENT")
    return lines


def calendar_ics(name: str, events: list[list[str]]) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Switchboard//Calendar//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{ics_escape(name)}", "X-PUBLISHED-TTL:PT30M"]
    for ev in events:
        lines += ev
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _strip_html(text: str | None) -> str | None:
    from pps_tools.switchboard.util import html_to_text

    return html_to_text(text) if text and "<" in text else text


def event_vevents(ev: dict, range_start: datetime, range_end: datetime, tz, base_url: str = "") -> list[list[str]]:
    out = []
    try:
        occ = occurrences(ev["start_at"], ev["end_at"], ev["rrule"], db.jload(ev["exdates_json"], []), range_start, range_end, tz)
    except ValueError:
        occ = []
    for s, e in occ:
        uid = f"event-{ev['id']}" + (f"-{_ics_dt(s)}" if ev["rrule"] else "") + "@switchboard"
        out.append(vevent(uid, ev["title"], s, e, bool(ev["all_day"]), _strip_html(ev["description"]), ev["location"],
                          f"{base_url}/calendar?event={ev['id']}" if base_url else None, tz))
    return out


def export_calendar(cal: dict, base_url: str = "") -> str:
    tz = org_tz()
    start, end = now() - timedelta(days=90), now() + timedelta(days=400)
    events = []
    for ev in db.query("SELECT * FROM calendar_events WHERE calendar_id = ? ORDER BY start_at", cal["id"]):
        events += event_vevents(ev, start, end, tz, base_url)
    return calendar_ics(cal["name"], events)


def personal_feed(user: dict, base_url: str = "") -> str:
    """My published shifts, my scheduled job work, my approved time off and events I
    created or was invited to."""
    tz = org_tz()
    start, end = now() - timedelta(days=30), now() + timedelta(days=365)
    events: list[list[str]] = []
    for item in overlay_items(user, start, end, ["shifts", "operations"]):
        uid = item["id"].replace(":", "-") + "@switchboard"
        events.append(vevent(uid, item["title"], parse_iso(item["start"]), parse_iso(item["end"]), False,
                             item.get("subtitle"), item.get("subtitle") if item["kind"] == "shift" else None,
                             f"{base_url}{item['url']}" if base_url else None, tz))
    for item in overlay_items(user, start, end, ["timeoff"]):
        if item.get("user_id") != user["id"]:
            continue
        events.append(vevent(item["id"].replace(":", "-") + "@switchboard", "Time off", parse_iso(item["start"]),
                             parse_iso(item["end"]), item["all_day"], None, None, None, tz))
    for ev in db.query("SELECT * FROM calendar_events ORDER BY start_at"):
        if ev["created_by"] == user["id"] or user["id"] in attendee_ids(ev):
            events += event_vevents(ev, start, end, tz, base_url)
    return calendar_ics(f"{user['name']} — Switchboard", events)


# -- ICS import (subscriptions) -------------------------------------------------------

_PROP_RE = re.compile(r"^([A-Za-z0-9-]+)((?:;[^:]*)?):(.*)$")


def _unescape(text: str) -> str:
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), text)


def _params(raw: str) -> dict:
    out = {}
    for piece in [p for p in raw.split(";") if p]:
        if "=" in piece:
            k, v = piece.split("=", 1)
            out[k.upper()] = v.strip('"')
    return out


def _parse_ics_dt(value: str, params: dict, default_tz) -> tuple[datetime, bool]:
    value = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value[:8], "%Y%m%d").date()
        return datetime.combine(d, time(0, 0), tzinfo=default_tz), True
    if value.endswith("Z"):
        return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC), False
    zone = get_zone(params.get("TZID")) if params.get("TZID") else default_tz
    if params.get("TZID") and zone is UTC and params["TZID"] not in ("UTC", "Etc/UTC", "GMT"):
        zone = default_tz  # Windows zone names etc.
    return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=zone), False


def _parse_duration(value: str) -> timedelta:
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value.strip())
    if not m:
        return timedelta(0)
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x) if x else 0 for x in m.groups()[1:])
    return sign * timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def parse_ics(text: str, default_tz=UTC) -> list[dict]:
    """VEVENTs as dicts: uid, title, description, location, start, end (aware UTC),
    all_day, rrule (only if we can expand it), exdates (iso), recurrence_id (iso)."""
    unfolded = re.sub(r"\r?\n[ \t]", "", text)
    events, cur = [], None
    for line in unfolded.splitlines():
        if line.strip().upper() == "BEGIN:VEVENT":
            cur = {"exdates": []}
            continue
        if line.strip().upper() == "END:VEVENT":
            if cur is not None and cur.get("start"):
                events.append(cur)
            cur = None
            continue
        if cur is None:
            continue
        m = _PROP_RE.match(line)
        if not m:
            continue
        name, params, value = m.group(1).upper(), _params(m.group(2)), m.group(3)
        try:
            if name == "UID":
                cur["uid"] = value.strip()
            elif name == "SUMMARY":
                cur["title"] = _unescape(value)
            elif name == "DESCRIPTION":
                cur["description"] = _unescape(value)
            elif name == "LOCATION":
                cur["location"] = _unescape(value)
            elif name == "STATUS":
                cur["status"] = value.strip().upper()
            elif name == "DTSTART":
                cur["start"], cur["all_day"] = _parse_ics_dt(value, params, default_tz)
            elif name == "DTEND":
                cur["end"], _ = _parse_ics_dt(value, params, default_tz)
            elif name == "DURATION":
                cur["duration"] = _parse_duration(value)
            elif name == "RRULE":
                cur["rrule_raw"] = value.strip()
            elif name == "EXDATE":
                for v in value.split(","):
                    dt, _ = _parse_ics_dt(v, params, default_tz)
                    cur["exdates"].append(iso(dt.astimezone(UTC)))
            elif name == "RECURRENCE-ID":
                dt, _ = _parse_ics_dt(value, params, default_tz)
                cur["recurrence_id"] = iso(dt.astimezone(UTC))
        except ValueError:
            continue
    out = []
    for ev in events:
        if ev.get("status") == "CANCELLED" and not ev.get("recurrence_id"):
            continue
        start = ev["start"]
        if ev.get("end"):
            end = ev["end"]
        elif ev.get("duration"):
            end = start + ev["duration"]
        else:
            end = start + (timedelta(days=1) if ev.get("all_day") else timedelta(0))
        if end < start:
            end = start
        rrule = None
        if ev.get("rrule_raw"):
            try:
                rrule = normalize_rrule(ev["rrule_raw"], default_tz)
            except Exception:  # unsupported (e.g. FREQ=HOURLY): keep the first occurrence only
                rrule = None
        out.append({
            "uid": ev.get("uid") or f"noid-{iso(start)}-{ev.get('title', '')}",
            "title": (ev.get("title") or "(no title)")[:300],
            "description": ev.get("description"),
            "location": ev.get("location"),
            "start": start.astimezone(UTC), "end": end.astimezone(UTC), "all_day": bool(ev.get("all_day")),
            "rrule": rrule, "exdates": ev["exdates"], "recurrence_id": ev.get("recurrence_id"),
            "cancelled": ev.get("status") == "CANCELLED",
        })
    return out


def import_events(cal: dict, items: list[dict]) -> int:
    """Replace a subscription calendar's events with ``items`` (from parse_ics)."""
    stamp = now_iso()
    with db.transaction():
        db.execute("DELETE FROM calendar_events WHERE calendar_id = ?", cal["id"])
        masters: dict[str, int] = {}
        for it in [i for i in items if not i["recurrence_id"]]:
            masters[it["uid"]] = db.insert("calendar_events", {
                "calendar_id": cal["id"], "title": it["title"], "description": it["description"], "location": it["location"],
                "start_at": iso(it["start"]), "end_at": iso(it["end"]), "all_day": 1 if it["all_day"] else 0,
                "rrule": it["rrule"], "exdates_json": db.jdump(sorted(set(it["exdates"]))),
                "external_uid": it["uid"], "created_at": stamp, "updated_at": stamp,
            })
        for it in [i for i in items if i["recurrence_id"]]:
            master_id = masters.get(it["uid"])
            if master_id:
                master = db.one("SELECT * FROM calendar_events WHERE id = ?", master_id)
                _add_exdate(master, it["recurrence_id"])
            if it["cancelled"]:
                continue
            db.insert("calendar_events", {
                "calendar_id": cal["id"], "title": it["title"], "description": it["description"], "location": it["location"],
                "start_at": iso(it["start"]), "end_at": iso(it["end"]), "all_day": 1 if it["all_day"] else 0,
                "parent_id": master_id, "original_start": it["recurrence_id"],
                "external_uid": f"{it['uid']}#{it['recurrence_id']}", "created_at": stamp, "updated_at": stamp,
            })
        db.update("calendars", cal["id"], {"last_sync_at": stamp, "sync_error": None})
        realtime.emit("calendar.changed", {"calendar_id": cal["id"]})
    return len(items)


MAX_ICS_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 3


def _addresses(host: str, port: int) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def _check_public(url: str) -> None:
    """Any teammate can add a subscription, so never let one make the server fetch from
    its own network (localhost, the LAN, cloud metadata endpoints)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("that isn't a web link to an iCalendar (.ics) file")
    try:
        addresses = _addresses(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError:
        raise ValueError(f"couldn't find {parsed.hostname}") from None
    if not addresses or not all(ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("that link points to a private network address")


def fetch_ics(url: str) -> str:
    """Download a subscription feed: public addresses only (checked again on every
    redirect) and at most MAX_ICS_BYTES, read in chunks so a huge file can't fill memory."""
    import requests

    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[9:]
    for _ in range(MAX_REDIRECTS + 1):
        _check_public(url)
        with requests.get(url, timeout=20, headers={"User-Agent": "Switchboard calendar sync"},
                          stream=True, allow_redirects=False) as resp:
            if resp.is_redirect:
                url = urljoin(url, resp.headers.get("Location", ""))
                continue
            resp.raise_for_status()
            chunks, size = [], 0
            for chunk in resp.iter_content(64 * 1024):
                size += len(chunk)
                if size > MAX_ICS_BYTES:
                    raise ValueError("calendar file is larger than 10 MB")
                chunks.append(chunk)
            return b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
    raise ValueError("that link redirects too many times")


def sync_subscription(cal: dict) -> int:
    try:
        text = fetch_ics(cal["ics_url"] or "")
        if "BEGIN:VCALENDAR" not in text.upper():
            raise ValueError("that link didn't return an iCalendar (.ics) file")
        return import_events(cal, parse_ics(text, org_tz()))
    except Exception as exc:
        with db.transaction():
            db.update("calendars", cal["id"], {"sync_error": str(exc)[:300], "last_sync_at": now_iso()})
        return 0


def sync_all_subscriptions() -> int:
    n = 0
    for cal in db.query("SELECT * FROM calendars WHERE kind = 'subscription' AND ics_url IS NOT NULL"):
        n += sync_subscription(cal)
    return n


# -- reminders ----------------------------------------------------------------------


def process_reminders() -> int:
    current = now()
    tz = org_tz()
    horizon = current + timedelta(minutes=MAX_REMINDER_MINUTES + 1)
    rows = db.query(
        "SELECT * FROM calendar_events WHERE reminder_minutes IS NOT NULL AND "
        "((rrule IS NULL AND start_at > ? AND start_at <= ?) OR (rrule IS NOT NULL AND start_at <= ?))",
        iso(current - timedelta(minutes=5)), iso(horizon), iso(horizon),
    )
    sent = 0
    for ev in rows:
        lead = timedelta(minutes=ev["reminder_minutes"])
        try:
            occ = occurrences(ev["start_at"], ev["end_at"], ev["rrule"], db.jload(ev["exdates_json"], []),
                              current, current + lead + timedelta(minutes=1), tz)
        except ValueError:
            continue
        for start, _end in occ:
            if not (start - lead <= current < start):
                continue
            key = iso(start)
            if db.one("SELECT 1 AS x FROM calendar_reminders_sent WHERE event_id = ? AND occurrence_start = ?", ev["id"], key):
                continue
            with db.transaction():
                db.insert("calendar_reminders_sent", {"event_id": ev["id"], "occurrence_start": key, "sent_at": now_iso()})
                people = {u for u in [ev["created_by"], *attendee_ids(ev)] if u}
                local = start.astimezone(tz)
                when = "now" if ev["reminder_minutes"] == 0 else f"at {local.hour % 12 or 12}:{local:%M} {'AM' if local.hour < 12 else 'PM'}"
                notify.notify(people, "reminder", f"{ev['title']} starts {when}", body=ev["location"],
                              link=f"/calendar?event={ev['id']}&date={local.date().isoformat()}",
                              entity_type="event", entity_id=ev["id"], include_actor=True)
                sent += 1
    return sent
