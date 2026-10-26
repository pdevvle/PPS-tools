"""Calendar API: calendars, events (with recurrence), overlays, ICS export and feeds."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, Response, request

from pps_tools.switchboard import config, db, realtime
from pps_tools.switchboard.services import calendars as cal_svc
from pps_tools.switchboard.util import iso, now, now_iso, parse_date, parse_iso, pick_color
from pps_tools.switchboard.web import (
    as_bool, as_int, bad_request, body, current_user, forbidden, login_required, not_found, ok, require_fields,
)
from pps_tools.switchboard.worker import Task

bp = Blueprint("calendar", __name__)

MAX_RANGE_DAYS = 400


def _range() -> tuple:
    start = parse_iso(request.args.get("start"))
    end = parse_iso(request.args.get("end"))
    if not start or not end:
        bad_request("start and end are required (ISO date-times)")
    if end <= start:
        bad_request("end must be after start")
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        bad_request(f"Ask for at most {MAX_RANGE_DAYS} days at a time")
    return start, end


def _base_url() -> str:
    return config.current().base_url


# -- calendars ----------------------------------------------------------------------


@bp.get("/api/calendars")
@login_required
def list_calendars():
    user = current_user()
    cal_svc.personal_calendar(user)
    return ok({"items": [cal_svc.serialize_calendar(user, c) for c in cal_svc.visible_calendars(user)]})


@bp.post("/api/calendars")
@login_required
def create_calendar():
    user = current_user()
    data = body()
    require_fields(data, "name")
    kind = data.get("kind") or "shared"
    if kind not in ("shared", "personal", "subscription"):
        bad_request("kind must be shared, personal or subscription")
    private = as_bool(data.get("private")) or kind == "personal"
    if kind == "shared" and user["role"] == "staff":
        forbidden("Ask a manager to add shared calendars")
    if kind == "subscription":
        url = (data.get("ics_url") or "").strip()
        if not url.lower().startswith(("http://", "https://", "webcal://")):
            bad_request("Paste the calendar's iCal (.ics) link")
        if not private and user["role"] == "staff":
            private = True
    values = {
        "name": data["name"].strip()[:120], "color": data.get("color") or pick_color(data["name"]), "kind": kind,
        "owner_user_id": user["id"] if private else None, "ics_url": (data.get("ics_url") or "").strip() or None,
        "created_by": user["id"], "created_at": now_iso(),
    }
    with db.transaction():
        cid = db.insert("calendars", values)
        realtime.emit("calendar.changed", {"calendar_id": cid})
    cal = db.one("SELECT * FROM calendars WHERE id = ?", cid)
    if kind == "subscription":
        cal_svc.sync_subscription(cal)
        cal = db.one("SELECT * FROM calendars WHERE id = ?", cid)
    return ok({"calendar": cal_svc.serialize_calendar(user, cal)}, 201)


@bp.patch("/api/calendars/<int:calendar_id>")
@login_required
def update_calendar(calendar_id: int):
    user = current_user()
    cal = cal_svc.get_calendar_for(user, calendar_id)
    if not cal_svc.can_manage_calendar(user, cal):
        forbidden("You can't change this calendar")
    data = body()
    values = {}
    if "name" in data:
        if not (data["name"] or "").strip():
            bad_request("Name can't be empty")
        values["name"] = data["name"].strip()[:120]
    if "color" in data:
        values["color"] = data["color"]
    if "ics_url" in data and cal["kind"] == "subscription":
        values["ics_url"] = (data["ics_url"] or "").strip() or None
    with db.transaction():
        db.update("calendars", calendar_id, values)
        realtime.emit("calendar.changed", {"calendar_id": calendar_id})
    return ok({"calendar": cal_svc.serialize_calendar(user, db.one("SELECT * FROM calendars WHERE id = ?", calendar_id))})


@bp.delete("/api/calendars/<int:calendar_id>")
@login_required
def delete_calendar(calendar_id: int):
    user = current_user()
    cal = cal_svc.get_calendar_for(user, calendar_id)
    if not cal_svc.can_manage_calendar(user, cal):
        forbidden("You can't delete this calendar")
    with db.transaction():
        db.delete("calendars", calendar_id)
        realtime.emit("calendar.changed", {"calendar_id": calendar_id})
    return ok()


@bp.post("/api/calendars/<int:calendar_id>/sync")
@login_required
def sync_calendar(calendar_id: int):
    user = current_user()
    cal = cal_svc.get_calendar_for(user, calendar_id)
    if cal["kind"] != "subscription":
        bad_request("Only subscribed calendars can be refreshed")
    count = cal_svc.sync_subscription(cal)
    cal = db.one("SELECT * FROM calendars WHERE id = ?", calendar_id)
    return ok({"imported": count, "calendar": cal_svc.serialize_calendar(user, cal)})


@bp.get("/api/calendars/<int:calendar_id>/export.ics")
@login_required
def export_calendar(calendar_id: int):
    cal = cal_svc.get_calendar_for(current_user(), calendar_id)
    text = cal_svc.export_calendar(cal, _base_url())
    return Response(text, mimetype="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="calendar-{calendar_id}.ics"'})


# -- events -------------------------------------------------------------------------


@bp.get("/api/calendar/events")
@login_required
def list_events():
    user = current_user()
    start, end = _range()
    ids = request.args.get("calendar_ids")
    calendar_ids = [int(x) for x in ids.split(",") if x.strip().isdigit()] if ids else None
    overlays = [x for x in (request.args.get("overlays") or "").split(",") if x in cal_svc.OVERLAYS]
    items = cal_svc.list_occurrences(user, start, end, calendar_ids)
    items += cal_svc.overlay_items(user, start, end, overlays)
    items.sort(key=lambda o: (o["start"], not o.get("all_day"), o["title"]))
    return ok({"items": items})


@bp.get("/api/calendar/agenda")
@login_required
def my_agenda():
    """Today and tomorrow for My Day: my events, shifts and scheduled job work."""
    user = current_user()
    tz = cal_svc.org_tz()
    from datetime import datetime, time

    # ?date=YYYY-MM-DD lets the browser say which day "today" is for it.
    today = parse_date(request.args.get("date")) or now().astimezone(tz).date()
    days = min(max(as_int(request.args.get("days"), "days") or 2, 1), 14)
    start = datetime.combine(today, time(0, 0), tzinfo=tz)
    end = start + timedelta(days=days)
    items = cal_svc.list_occurrences(user, start, end, None)
    items += cal_svc.overlay_items(user, start, end, ["shifts", "operations"])
    items.sort(key=lambda o: (o["start"], not o.get("all_day"), o["title"]))
    return ok({"items": items, "today": today.isoformat()})


@bp.post("/api/calendar/events")
@login_required
def create_event():
    ev = cal_svc.create_event(current_user(), body())
    return ok({"event": _event_payload(ev)}, 201)


def _event_payload(ev: dict) -> dict:
    user = current_user()
    cal = db.one("SELECT * FROM calendars WHERE id = ?", ev["calendar_id"])
    tz = cal_svc.org_tz()
    item = cal_svc.serialize_occurrence(user, ev, cal, parse_iso(ev["start_at"]), parse_iso(ev["end_at"]), tz)
    item["id"] = str(ev["id"])
    item["exdates"] = db.jload(ev["exdates_json"], [])
    item["calendar"] = {"id": cal["id"], "name": cal["name"], "color": cal["color"], "kind": cal["kind"]}
    return item


@bp.get("/api/calendar/events/<int:event_id>")
@login_required
def get_event(event_id: int):
    ev, _cal = cal_svc.get_event_for(current_user(), event_id)
    return ok({"event": _event_payload(ev)})


@bp.patch("/api/calendar/events/<int:event_id>")
@login_required
def update_event(event_id: int):
    data = body()
    scope = request.args.get("scope") or data.pop("scope", None) or "all"
    original = request.args.get("original_start") or data.pop("original_start", None)
    ev = cal_svc.update_event(current_user(), event_id, data, scope=scope, original_start=original)
    return ok({"event": _event_payload(ev)})


@bp.delete("/api/calendar/events/<int:event_id>")
@login_required
def delete_event(event_id: int):
    data = body()
    scope = request.args.get("scope") or data.get("scope") or "all"
    original = request.args.get("original_start") or data.get("original_start")
    cal_svc.delete_event(current_user(), event_id, scope=scope, original_start=original)
    return ok()


# -- private feed -------------------------------------------------------------------


@bp.get("/feeds/<tok>.ics")
def personal_feed(tok: str):
    user = db.one("SELECT * FROM users WHERE feed_token = ? AND is_active = 1", tok)
    if not user:
        not_found("Unknown calendar link")
    return Response(cal_svc.personal_feed(user, _base_url()), mimetype="text/calendar",
                    headers={"Cache-Control": "private, max-age=300",
                             "Content-Disposition": 'inline; filename="switchboard.ics"'})


# -- module hooks -------------------------------------------------------------------


def on_setup(ctx: dict) -> None:
    db.insert("calendars", {"name": "Shop calendar", "color": "#0c8599", "kind": "shared",
                            "created_by": ctx.get("owner_id"), "created_at": now_iso()})


def search(user: dict, q: str, limit: int) -> list[dict]:
    like = f"%{q}%"
    rows = db.query(
        "SELECT * FROM calendar_events WHERE (title LIKE ? OR location LIKE ?) AND (end_at >= ? OR rrule IS NOT NULL) "
        "ORDER BY start_at LIMIT ?", like, like, iso(now() - timedelta(days=30)), limit * 3,
    )
    out = []
    tz = cal_svc.org_tz()
    for ev in rows:
        if not cal_svc.can_see_event(user, ev):
            continue
        start = parse_iso(ev["start_at"]).astimezone(tz)
        out.append({"type": "event", "id": ev["id"], "title": ev["title"],
                    "subtitle": f"{start:%a %b} {start.day}" + (" · repeats" if ev["rrule"] else "") + (f" · {ev['location']}" if ev["location"] else ""),
                    "url": f"/calendar?event={ev['id']}&date={start.date().isoformat()}", "icon": "calendar", "group": "Calendar"})
        if len(out) >= limit:
            break
    return out


def worker_tasks():
    return [
        Task("calendar.reminders", 60, cal_svc.process_reminders),
        Task("calendar.subscriptions", 1800, cal_svc.sync_all_subscriptions),
    ]


def seed(ctx) -> None:
    from pps_tools.switchboard.demo.calendar import seed_calendar

    seed_calendar(ctx)
