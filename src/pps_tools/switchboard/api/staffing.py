"""Staffing API: positions & skills, people, availability, time off, shifts and
templates, swap / drop / pickup requests, the time clock (and shop kiosk), and
timesheets."""

from __future__ import annotations

import csv
import io
import sqlite3
import threading
import time
from datetime import date, timedelta

from flask import Blueprint, Response, request
from werkzeug.security import check_password_hash

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.services import hooks, notify, settings, staff_status
from pps_tools.switchboard.services import staffing as st
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.util import iso, now, now_iso, parse_iso, pick_color
from pps_tools.switchboard.web import (
    ApiError, as_bool, as_int, audit, bad_request, body, can, conflict, current_user, forbidden, login_required,
    not_found, ok, public_user, require, require_fields,
)
from pps_tools.switchboard.worker import Task

bp = Blueprint("staffing", __name__)


def _is_manager(user: dict | None = None) -> bool:
    return can(user or current_user(), "manage_staff")


def _sees_pay(user: dict | None = None) -> bool:
    return can(user or current_user(), "view_pay")


# -- positions, locations, skills -------------------------------------------------------

REF_TABLES = {
    "positions": {"fields": ("name", "color", "default_rate", "is_active", "position"), "label": "position"},
    "locations": {"fields": ("name", "address", "color", "is_active"), "label": "location"},
    "skills": {"fields": ("name",), "label": "skill"},
}


def _ref_rows(table: str, user: dict) -> list[dict]:
    order = "position, name COLLATE NOCASE" if table == "positions" else "name COLLATE NOCASE"
    rows = db.query(f"SELECT * FROM {table} ORDER BY {order}")
    if table == "positions" and not _sees_pay(user):
        for r in rows:
            r["default_rate"] = None
    for r in rows:
        if "is_active" in r:
            r["is_active"] = bool(r["is_active"])
    return rows


def _ref_values(table: str, data: dict, partial: bool) -> dict:
    spec = REF_TABLES[table]
    out = {}
    if "name" in data or not partial:
        name = (data.get("name") or "").strip()
        if not name:
            bad_request(f"Give the {spec['label']} a name")
        out["name"] = name[:80]
    for field in spec["fields"]:
        if field == "name" or field not in data:
            continue
        value = data[field]
        if field == "default_rate":
            if value in (None, ""):
                value = None
            else:
                try:
                    value = round(float(value), 2)
                except (TypeError, ValueError):
                    bad_request("Rate must be a number")
                if value < 0:
                    bad_request("Rate can't be negative")
        elif field == "is_active":
            value = 1 if as_bool(value) else 0
        elif field == "position":
            value = as_int(value, "position") or 0
        elif isinstance(value, str):
            value = value.strip() or None
        out[field] = value
    return out


def _make_ref_routes(table: str) -> None:
    label = REF_TABLES[table]["label"]

    def list_rows():
        return ok({"items": _ref_rows(table, current_user())})

    def create_row():
        values = _ref_values(table, body(), partial=False)
        if table != "skills":
            values.setdefault("color", pick_color(values["name"]))
        values["created_at"] = now_iso()
        try:
            with db.transaction():
                rid = db.insert(table, values)
                st.emit_schedule("reference", what=table)
                realtime.emit("settings.changed", {"what": table})
        except sqlite3.IntegrityError:
            conflict(f"There's already a {label} with that name", code="duplicate")
        return ok({"item": db.one(f"SELECT * FROM {table} WHERE id = ?", rid)}, 201)

    def update_row(rid: int):
        if not db.one(f"SELECT id FROM {table} WHERE id = ?", rid):
            not_found(f"No such {label}")
        values = _ref_values(table, body(), partial=True)
        if "default_rate" in values and not _sees_pay():
            forbidden()
        try:
            with db.transaction():
                db.update(table, rid, values)
                realtime.emit("settings.changed", {"what": table})
                st.emit_schedule("reference", what=table)
        except sqlite3.IntegrityError:
            conflict(f"There's already a {label} with that name", code="duplicate")
        return ok({"item": db.one(f"SELECT * FROM {table} WHERE id = ?", rid)})

    def delete_row(rid: int):
        with db.transaction():
            db.delete(table, rid)
            realtime.emit("settings.changed", {"what": table})
            st.emit_schedule("reference", what=table)
        return ok()

    bp.add_url_rule(f"/api/{table}", f"list_{table}", login_required(list_rows), methods=["GET"])
    bp.add_url_rule(f"/api/{table}", f"create_{table}", require("manage_staff")(create_row), methods=["POST"])
    bp.add_url_rule(f"/api/{table}/<int:rid>", f"update_{table}", require("manage_staff")(update_row), methods=["PATCH"])
    bp.add_url_rule(f"/api/{table}/<int:rid>", f"delete_{table}", require("manage_staff")(delete_row), methods=["DELETE"])


for _table in REF_TABLES:
    _make_ref_routes(_table)


# -- people -----------------------------------------------------------------------------

PROFILE_FIELDS = ("employee_number", "employment_type", "hourly_rate", "hire_date", "target_hours_week",
                  "max_hours_week", "default_position_id", "default_location_id", "pto_hours_per_year",
                  "emergency_contact", "notes", "is_schedulable")


def _profile_out(p: dict, viewer: dict, uid: int) -> dict:
    manager = _is_manager(viewer)
    me = viewer["id"] == uid
    out = {k: p.get(k) for k in PROFILE_FIELDS}
    out["is_schedulable"] = bool(p.get("is_schedulable", 1))
    if not _sees_pay(viewer):
        out["hourly_rate"] = None
    if not manager:
        out["notes"] = None
        if not me:
            out["emergency_contact"] = None
            out["pto_hours_per_year"] = None
    return out


def _skills_by_user() -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for r in db.query("SELECT user_id, skill_id, level FROM staff_skills ORDER BY skill_id"):
        out.setdefault(r["user_id"], []).append({"skill_id": r["skill_id"], "level": r["level"]})
    return out


def _positions_by_user() -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for r in db.query("SELECT user_id, position_id FROM staff_positions ORDER BY position_id"):
        out.setdefault(r["user_id"], []).append(r["position_id"])
    return out


def _week_minutes(week: date) -> dict[int, float]:
    rows = db.query("SELECT * FROM shifts WHERE user_id IS NOT NULL AND start_at >= ? AND start_at < ?",
                    st.day_start(week), st.day_start(week + timedelta(days=7)))
    out: dict[int, float] = {}
    for r in rows:
        if r["status"] == "published" or _is_manager():
            out[r["user_id"]] = out.get(r["user_id"], 0.0) + st.paid_minutes(r)
    return out


@bp.get("/api/staff")
@login_required
def list_staff():
    viewer = current_user()
    week = st.week_start(st.parse_day(request.args["week"], "week")) if request.args.get("week") else st.week_start(st.today())
    include_inactive = as_bool(request.args.get("include_inactive")) and _is_manager()
    users = db.query("SELECT * FROM users " + ("" if include_inactive else "WHERE is_active = 1 ") + "ORDER BY name COLLATE NOCASE")
    profiles = {p["user_id"]: p for p in db.query("SELECT * FROM staff_profiles")}
    positions = _positions_by_user()
    skills = _skills_by_user()
    status = staff_status.status_map()
    minutes = _week_minutes(week)
    items = []
    for u in users:
        items.append({
            "user": public_user(u),
            "profile": _profile_out(profiles.get(u["id"]) or st.profile(u["id"]), viewer, u["id"]),
            "position_ids": positions.get(u["id"], []),
            "skills": skills.get(u["id"], []),
            "status": status.get(u["id"], "off"),
            "week_minutes": round(minutes.get(u["id"], 0.0), 2),
        })
    return ok({"items": items, "week": week.isoformat()})


def _can_see_private(viewer: dict, uid: int) -> bool:
    return viewer["id"] == uid or _is_manager(viewer)


@bp.get("/api/staff/<int:uid>")
@login_required
def get_staff(uid: int):
    viewer = current_user()
    u = users_svc.get(uid)
    if not u:
        not_found("No such person")
    private = _can_see_private(viewer, uid)
    today = st.today()
    shift_rows = db.query(
        "SELECT * FROM shifts WHERE user_id = ? AND end_at > ? AND start_at < ? " +
        ("" if _is_manager(viewer) else "AND status = 'published' ") + "ORDER BY start_at",
        uid, now_iso(), st.day_start(today + timedelta(days=21)),
    )
    time_off = db.query("SELECT * FROM time_off_requests WHERE user_id = ? ORDER BY start_date DESC LIMIT 25", uid) if private else []
    entries = db.query(
        "SELECT * FROM time_entries WHERE user_id = ? AND clock_in >= ? ORDER BY clock_in DESC",
        uid, st.day_start(today - timedelta(days=14)),
    ) if private else []
    return ok({
        "user": public_user(u),
        "profile": _profile_out(st.profile(uid), viewer, uid),
        "position_ids": st.position_ids_of(uid),
        "skills": _skills_by_user().get(uid, []),
        "status": staff_status.status_map().get(uid, "off"),
        "availability": db.query("SELECT * FROM availability WHERE user_id = ? ORDER BY weekday, start_time", uid),
        "upcoming_shifts": [st.serialize_shift(s) for s in shift_rows],
        "time_off": time_off,
        "time_entries": [st.serialize_entry(e) for e in entries],
        "week_minutes": round(_week_minutes(st.week_start(today)).get(uid, 0.0), 2),
        "can_edit": _is_manager(viewer),
        "is_me": viewer["id"] == uid,
    })


@bp.patch("/api/staff/<int:uid>")
@login_required
def update_staff(uid: int):
    viewer = current_user()
    if not users_svc.get(uid):
        not_found("No such person")
    data = body()
    manager = _is_manager(viewer)
    if not manager:
        if viewer["id"] != uid or set(data) - {"emergency_contact"}:
            forbidden("Only a manager can change employment details")
    changes = {}
    for field in PROFILE_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field == "hourly_rate" and not _sees_pay(viewer):
            forbidden("You can't change pay rates")
        if field in ("hourly_rate", "target_hours_week", "max_hours_week", "pto_hours_per_year"):
            if value in (None, ""):
                value = None
            else:
                try:
                    value = round(float(value), 2)
                except (TypeError, ValueError):
                    bad_request(f"'{field}' must be a number")
                if value < 0:
                    bad_request(f"'{field}' can't be negative")
        elif field == "employment_type":
            if value not in st.EMPLOYMENT_TYPES:
                bad_request("Unknown employment type")
        elif field in ("default_position_id", "default_location_id"):
            value = as_int(value, field)
            table = "positions" if field == "default_position_id" else "locations"
            if value and not db.one(f"SELECT id FROM {table} WHERE id = ?", value):
                bad_request("No such position or location")
        elif field == "is_schedulable":
            value = 1 if as_bool(value) else 0
        elif field == "hire_date":
            value = st.parse_day(value, field).isoformat() if value else None
        else:
            value = (str(value).strip() or None) if value is not None else None
        changes[field] = value
    with db.transaction():
        st.ensure_profile(uid)
        if changes:
            changes["updated_at"] = now_iso()
            db.update("staff_profiles", uid, changes, key="user_id")
            audit("staff.update", "user", uid, {k: v for k, v in changes.items() if k != "hourly_rate"})
        realtime.emit("staff.changed", {"user_id": uid}, users=st.everyone_ids())
    return get_staff(uid)


@bp.put("/api/staff/<int:uid>/positions")
@require("manage_staff")
def set_positions(uid: int):
    if not users_svc.get(uid):
        not_found("No such person")
    ids = sorted({int(p) for p in body().get("position_ids") or []})
    valid = set(db.column("SELECT id FROM positions"))
    if set(ids) - valid:
        bad_request("Unknown position")
    with db.transaction():
        db.execute("DELETE FROM staff_positions WHERE user_id = ?", uid)
        for pid in ids:
            db.insert("staff_positions", {"user_id": uid, "position_id": pid})
        realtime.emit("staff.changed", {"user_id": uid}, users=st.everyone_ids())
        st.emit_schedule("positions", user_id=uid)
    return ok({"position_ids": ids})


@bp.put("/api/staff/<int:uid>/skills")
@require("manage_staff")
def set_skills(uid: int):
    if not users_svc.get(uid):
        not_found("No such person")
    items = body().get("skills") or []
    valid = set(db.column("SELECT id FROM skills"))
    clean = {}
    for item in items:
        sid = as_int(item.get("skill_id") if isinstance(item, dict) else item, "skill_id")
        level = as_int(item.get("level") if isinstance(item, dict) else 1, "level") or 1
        if sid not in valid:
            bad_request("Unknown skill")
        if level not in (1, 2, 3):
            bad_request("Skill level is 1 (trainee), 2 (competent) or 3 (expert)")
        clean[sid] = level
    with db.transaction():
        db.execute("DELETE FROM staff_skills WHERE user_id = ?", uid)
        for sid, level in sorted(clean.items()):
            db.insert("staff_skills", {"user_id": uid, "skill_id": sid, "level": level})
        realtime.emit("staff.changed", {"user_id": uid}, users=st.everyone_ids())
    return ok({"skills": [{"skill_id": k, "level": v} for k, v in sorted(clean.items())]})


@bp.get("/api/staff/<int:uid>/availability")
@login_required
def get_availability(uid: int):
    return ok({"items": db.query("SELECT * FROM availability WHERE user_id = ? ORDER BY weekday, start_time", uid)})


@bp.put("/api/staff/<int:uid>/availability")
@login_required
def put_availability(uid: int):
    viewer = current_user()
    if viewer["id"] != uid and not _is_manager(viewer):
        forbidden("You can only change your own availability")
    if not users_svc.get(uid):
        not_found("No such person")
    rows = []
    for item in body().get("items") or []:
        weekday = as_int(item.get("weekday"), "weekday")
        kind = item.get("kind") or "available"
        start, end = item.get("start_time"), item.get("end_time")
        if weekday is None or not 0 <= weekday <= 6:
            bad_request("weekday is 0 (Monday) to 6 (Sunday)")
        if kind not in ("available", "preferred", "unavailable"):
            bad_request("kind is available, preferred or unavailable")
        if not st.valid_hhmm(start) or not st.valid_hhmm(end) or st.hhmm_to_minutes(end) <= st.hhmm_to_minutes(start):
            bad_request("Each window needs a start time before its end time")
        rows.append({"user_id": uid, "weekday": weekday, "start_time": start[:5], "end_time": end[:5], "kind": kind,
                     "note": (item.get("note") or "").strip()[:200] or None})
    with db.transaction():
        db.execute("DELETE FROM availability WHERE user_id = ?", uid)
        for r in rows:
            db.insert("availability", r)
        st.emit_schedule("availability", user_id=uid)
    return get_availability(uid)


# -- time off ---------------------------------------------------------------------------


def _serialize_time_off(r: dict, viewer: dict) -> dict:
    out = dict(r)
    if not _can_see_private(viewer, r["user_id"]):
        out["reason"] = None
        out["review_note"] = None
    out["days"] = (date.fromisoformat(r["end_date"]) - date.fromisoformat(r["start_date"])).days + 1
    return out


@bp.get("/api/time-off")
@login_required
def list_time_off():
    viewer = current_user()
    where, params = [], []
    uid = as_int(request.args.get("user_id"), "user_id")
    if not _is_manager(viewer) or as_bool(request.args.get("mine")):
        if uid and uid != viewer["id"] and not _is_manager(viewer):
            forbidden()
        uid = uid or viewer["id"]
    if uid:
        where.append("user_id = ?")
        params.append(uid)
    status = request.args.get("status")
    if status == "upcoming":
        where.append("status IN ('approved', 'pending') AND end_date >= ?")
        params.append(st.today().isoformat())
    elif status == "past":
        where.append("end_date < ?")
        params.append(st.today().isoformat())
    elif status:
        where.append("status = ?")
        params.append(status)
    if request.args.get("start"):
        where.append("end_date >= ?")
        params.append(st.parse_day(request.args["start"], "start").isoformat())
    if request.args.get("end"):
        where.append("start_date < ?")
        params.append(st.parse_day(request.args["end"], "end").isoformat())
    sql = "SELECT * FROM time_off_requests" + (" WHERE " + " AND ".join(where) if where else "")
    order = " ORDER BY start_date DESC" if status == "past" else " ORDER BY start_date, id"
    rows = db.query(sql + order + " LIMIT 500", params)
    return ok({"items": [_serialize_time_off(r, viewer) for r in rows]})


def _time_off_hours(start: date, end: date, start_time, end_time) -> float:
    if start_time and end_time:
        return round((st.hhmm_to_minutes(end_time) - st.hhmm_to_minutes(start_time)) / 60, 2)
    workdays = sum(1 for d in st.days_between(start, end + timedelta(days=1)) if d.weekday() < 5)
    return float(workdays * 8)


@bp.post("/api/time-off")
@login_required
def create_time_off():
    viewer = current_user()
    data = body()
    require_fields(data, "start_date", "end_date")
    uid = as_int(data.get("user_id"), "user_id") or viewer["id"]
    if uid != viewer["id"] and not _is_manager(viewer):
        forbidden("You can only request time off for yourself")
    if not users_svc.get(uid):
        not_found("No such person")
    kind = data.get("kind") or "vacation"
    if kind not in st.TIME_OFF_KINDS:
        bad_request("Unknown kind of time off")
    start, end = st.parse_day(data["start_date"], "start_date"), st.parse_day(data["end_date"], "end_date")
    if end < start:
        bad_request("The last day can't be before the first day")
    start_time, end_time = data.get("start_time") or None, data.get("end_time") or None
    if start_time or end_time:
        if start != end:
            bad_request("Partial days are for a single date")
        if not st.valid_hhmm(start_time) or not st.valid_hhmm(end_time) or st.hhmm_to_minutes(end_time) <= st.hhmm_to_minutes(start_time):
            bad_request("Give a start time before the end time")
    overlap = db.one(
        "SELECT id FROM time_off_requests WHERE user_id = ? AND status IN ('pending', 'approved') "
        "AND start_date <= ? AND end_date >= ?", uid, end.isoformat(), start.isoformat(),
    )
    if overlap:
        conflict("There's already a time-off request covering those days", code="duplicate")
    by_manager = uid != viewer["id"] and _is_manager(viewer)
    status = "approved" if by_manager and as_bool(data.get("approve", True)) else "pending"
    stamp = now_iso()
    with db.transaction():
        rid = db.insert("time_off_requests", {
            "user_id": uid, "kind": kind, "start_date": start.isoformat(), "end_date": end.isoformat(),
            "start_time": start_time, "end_time": end_time, "hours": _time_off_hours(start, end, start_time, end_time),
            "reason": (data.get("reason") or "").strip()[:1000] or None, "status": status,
            "reviewed_by": viewer["id"] if status == "approved" else None,
            "reviewed_at": stamp if status == "approved" else None, "created_at": stamp,
        })
        who = users_svc.name_of(uid)
        span = st.fmt_day(start) + ("" if start == end else f" – {st.fmt_day(end)}")
        if status == "pending":
            notify.notify([m for m in st.manager_ids() if m != uid], "timeoff", f"{who} requested {kind} time off: {span}",
                          body=data.get("reason"), link="/schedule/timeoff", actor_id=viewer["id"],
                          entity_type="time_off", entity_id=rid)
            hooks.fire("timeoff.requested", {"request_id": rid, "user_id": uid})
        else:
            notify.notify([uid], "timeoff", f"{viewer['name']} added {kind} time off for you: {span}",
                          link="/schedule/timeoff", actor_id=viewer["id"], entity_type="time_off", entity_id=rid)
        st.emit_schedule("time_off", request_id=rid)
        st.emit_badges([uid])
    return ok({"item": _serialize_time_off(db.one("SELECT * FROM time_off_requests WHERE id = ?", rid), viewer)}, 201)


def _decide_time_off(rid: int, approve: bool):
    viewer = current_user()
    r = db.one("SELECT * FROM time_off_requests WHERE id = ?", rid)
    if not r:
        not_found("Request not found")
    if r["status"] != "pending" and not (r["status"] == "approved" and not approve):
        bad_request("This request was already decided")
    note = (body().get("note") or "").strip()[:500] or None
    status = "approved" if approve else "denied"
    with db.transaction():
        db.update("time_off_requests", rid, {"status": status, "reviewed_by": viewer["id"], "reviewed_at": now_iso(),
                                             "review_note": note})
        span = st.fmt_day(date.fromisoformat(r["start_date"]))
        if r["end_date"] != r["start_date"]:
            span += f" – {st.fmt_day(date.fromisoformat(r['end_date']))}"
        notify.notify([r["user_id"]], "timeoff", f"Time off {status}: {span}", body=note, link="/schedule/timeoff",
                      actor_id=viewer["id"], entity_type="time_off", entity_id=rid)
        hooks.fire("timeoff.decided", {"request_id": rid, "user_id": r["user_id"], "status": status, "by": viewer["id"]})
        st.emit_schedule("time_off", request_id=rid)
        st.emit_badges([r["user_id"]])
    clashes = []
    if approve:
        first, last = date.fromisoformat(r["start_date"]), date.fromisoformat(r["end_date"])
        rows = db.query("SELECT * FROM shifts WHERE user_id = ? AND start_at < ? AND end_at > ?", r["user_id"],
                        st.day_start(last + timedelta(days=1)), st.day_start(first))
        clashes = [st.serialize_shift(s) for s in rows if st.time_off_hits(s, [db.one("SELECT * FROM time_off_requests WHERE id = ?", rid)])]
    item = _serialize_time_off(db.one("SELECT * FROM time_off_requests WHERE id = ?", rid), viewer)
    return ok({"item": item, "conflicting_shifts": clashes})


@bp.post("/api/time-off/<int:rid>/approve")
@require("manage_staff")
def approve_time_off(rid: int):
    return _decide_time_off(rid, True)


@bp.post("/api/time-off/<int:rid>/deny")
@require("manage_staff")
def deny_time_off(rid: int):
    return _decide_time_off(rid, False)


@bp.post("/api/time-off/<int:rid>/cancel")
@login_required
def cancel_time_off(rid: int):
    viewer = current_user()
    r = db.one("SELECT * FROM time_off_requests WHERE id = ?", rid)
    if not r:
        not_found("Request not found")
    if _is_manager(viewer):
        if r["status"] not in ("pending", "approved"):
            bad_request("This request is already closed")
    elif r["user_id"] != viewer["id"] or r["status"] != "pending":
        forbidden("You can cancel your own request while it's pending")
    with db.transaction():
        db.update("time_off_requests", rid, {"status": "cancelled", "reviewed_by": viewer["id"], "reviewed_at": now_iso()})
        if r["user_id"] != viewer["id"]:
            notify.notify([r["user_id"]], "timeoff", f"{viewer['name']} cancelled your time off starting "
                          f"{st.fmt_day(date.fromisoformat(r['start_date']))}", link="/schedule/timeoff",
                          actor_id=viewer["id"], entity_type="time_off", entity_id=rid)
        st.emit_schedule("time_off", request_id=rid)
        st.emit_badges([r["user_id"]])
    return ok({"item": _serialize_time_off(db.one("SELECT * FROM time_off_requests WHERE id = ?", rid), viewer)})


# -- shifts -----------------------------------------------------------------------------


def _shift_values(data: dict, existing: dict | None = None) -> dict:
    out: dict = {}
    if "user_id" in data:
        uid = as_int(data["user_id"], "user_id")
        if uid:
            u = users_svc.get(uid)
            if not u or not u["is_active"]:
                bad_request("That person isn't active")
        out["user_id"] = uid
    for field, table in (("position_id", "positions"), ("location_id", "locations")):
        if field in data:
            value = as_int(data[field], field)
            if value and not db.one(f"SELECT id FROM {table} WHERE id = ?", value):
                bad_request(f"Unknown {field.replace('_id', '')}")
            out[field] = value
    if "job_id" in data:
        job_id = as_int(data["job_id"], "job_id")
        if job_id and not db.one("SELECT id FROM jobs WHERE id = ?", job_id):
            bad_request("No such job")
        out["job_id"] = job_id
    if "notes" in data:
        out["notes"] = (data["notes"] or "").strip()[:1000] or None
    if "break_minutes" in data:
        out["break_minutes"] = max(0, as_int(data["break_minutes"], "break_minutes") or 0)
    if "status" in data:
        if data["status"] not in ("draft", "published"):
            bad_request("status is draft or published")
        out["status"] = data["status"]
    # time: either date + start_time + end_time (local), or start_at + end_at
    if any(k in data for k in ("date", "start_time", "end_time")):
        cur = st.serialize_shift(existing) if existing else {}
        day = data.get("date") or cur.get("date")
        start_t = data.get("start_time") or cur.get("start_time")
        end_t = data.get("end_time") or cur.get("end_time")
        if not (day and start_t and end_t):
            bad_request("A shift needs a date, a start time and an end time")
        out["start_at"], out["end_at"] = st.instants_for(day, start_t, end_t)
    elif "start_at" in data or "end_at" in data:
        start = parse_iso(data.get("start_at") or (existing or {}).get("start_at"))
        end = parse_iso(data.get("end_at") or (existing or {}).get("end_at"))
        if not start or not end:
            bad_request("A shift needs a start and an end")
        out["start_at"], out["end_at"] = iso(start), iso(end)
    start = out.get("start_at") or (existing or {}).get("start_at")
    end = out.get("end_at") or (existing or {}).get("end_at")
    if not start or not end:
        bad_request("A shift needs a start and an end")
    length = st.minutes_between(start, end)
    if length <= 0:
        bad_request("A shift has to end after it starts")
    if length > 24 * 60:
        bad_request("A shift can't be longer than 24 hours")
    brk = out.get("break_minutes", (existing or {}).get("break_minutes") or 0)
    if brk >= length:
        bad_request("The break is longer than the shift")
    return out


def _get_shift(sid: int) -> dict:
    row = db.one("SELECT * FROM shifts WHERE id = ?", sid)
    if not row:
        not_found("Shift not found")
    return row


def _shift_out(row: dict, with_conflicts: bool = True) -> dict:
    s = st.serialize_shift(row)
    if with_conflicts:
        st.annotate_conflicts([s])
    return s


@bp.get("/api/shifts")
@login_required
def list_shifts():
    viewer = current_user()
    manager = _is_manager(viewer)
    first, last = st.range_from_args(request.args.get("start"), request.args.get("end"))
    where = ["start_at >= ?", "start_at < ?"]
    params: list = [st.day_start(first), st.day_start(last)]
    if not manager or request.args.get("status") == "published":
        where.append("status = 'published'")
    for field in ("user_id", "position_id", "location_id"):
        value = as_int(request.args.get(field), field)
        if value:
            where.append(f"{field} = ?")
            params.append(value)
    rows = db.query(f"SELECT * FROM shifts WHERE {' AND '.join(where)} ORDER BY start_at, id", params)
    items = [st.serialize_shift(r) for r in rows]
    if manager:
        st.annotate_conflicts(items)
    people_totals, day_totals = st.totals(items, include_cost=_sees_pay(viewer))
    statuses = ("approved", "pending") if manager else ("approved",)
    all_ids = st.everyone_ids()
    time_off = [_serialize_time_off(r, viewer) for r in st.time_off_rows(all_ids, first, last - timedelta(days=1), statuses)]
    if not manager:
        mine = [_serialize_time_off(r, viewer) for r in st.time_off_rows([viewer["id"]], first, last - timedelta(days=1), ("pending",))]
        time_off += mine
    availability: dict = {}
    if manager:
        for a in db.query("SELECT * FROM availability ORDER BY weekday, start_time"):
            availability.setdefault(str(a["user_id"]), []).append(a)
    ids = [s["id"] for s in items]
    requests_open = db.query(
        f"SELECT id, kind, shift_id, requester_id, target_user_id, target_shift_id, status FROM shift_requests "
        f"WHERE status IN ('pending', 'accepted') AND (shift_id IN ({db.placeholders(ids)}) OR target_shift_id IN ({db.placeholders(ids)}))",
        [*ids, *ids],
    ) if ids else []
    drafts = db.scalar("SELECT COUNT(*) FROM shifts WHERE status = 'draft' AND start_at >= ? AND start_at < ?",
                       st.day_start(first), st.day_start(last)) if manager else 0
    return ok({
        "start": first.isoformat(),
        "end": last.isoformat(),
        "days": [d.isoformat() for d in st.days_between(first, last)],
        "today": st.today().isoformat(),
        "items": items,
        "totals": {str(k): v for k, v in people_totals.items()},
        "day_totals": day_totals,
        "time_off": time_off,
        "availability": availability,
        "requests": requests_open,
        "drafts": drafts,
        "can_manage": manager,
        "can_view_pay": _sees_pay(viewer),
        "overtime_weekly_hours": settings.get("staffing.overtime_weekly_hours"),
    })


@bp.post("/api/shifts")
@require("manage_staff")
def create_shifts():
    viewer = current_user()
    data = body()
    batch = data.get("shifts") if isinstance(data.get("shifts"), list) else [data]
    if not batch:
        bad_request("Nothing to create")
    if len(batch) > 500:
        bad_request("Create at most 500 shifts at a time")
    stamp = now_iso()
    created = []
    with db.transaction():
        for item in batch:
            values = _shift_values({"break_minutes": 0, **item})
            values.setdefault("status", "draft")
            values.update({"created_by": viewer["id"], "created_at": stamp, "updated_at": stamp,
                           "published_at": stamp if values["status"] == "published" else None})
            sid = db.insert("shifts", values)
            row = _get_shift(sid)
            st.notify_shift_change(None, row, viewer["id"])
            created.append(row)
        st.emit_schedule("created", ids=[r["id"] for r in created])
    items = [st.serialize_shift(r) for r in created]
    st.annotate_conflicts(items)
    return ok({"items": items, "item": items[0] if len(items) == 1 else None}, 201)


@bp.patch("/api/shifts/<int:sid>")
@require("manage_staff")
def update_shift(sid: int):
    viewer = current_user()
    before = _get_shift(sid)
    values = _shift_values(body(), existing=before)
    if values.get("status") == "draft" and before["status"] == "published":
        values["published_at"] = None
    if values.get("status") == "published" and before["status"] != "published":
        values["published_at"] = now_iso()
    if "start_at" in values and values["start_at"] != before["start_at"]:
        values["reminded_at"] = None
    with db.transaction():
        values["updated_at"] = now_iso()
        db.update("shifts", sid, values)
        after = _get_shift(sid)
        st.notify_shift_change(before, after, viewer["id"])
        st.emit_schedule("updated", ids=[sid])
    return ok({"item": _shift_out(after)})


@bp.delete("/api/shifts/<int:sid>")
@require("manage_staff")
def delete_shift(sid: int):
    viewer = current_user()
    before = _get_shift(sid)
    with db.transaction():
        db.delete("shifts", sid)
        st.notify_shift_change(before, None, viewer["id"])
        st.emit_schedule("deleted", ids=[sid])
    return ok()


@bp.post("/api/shifts/copy-week")
@require("manage_staff")
def copy_week():
    data = body()
    require_fields(data, "from_week", "to_week")
    res = st.copy_week(st.parse_day(data["from_week"], "from_week"), st.parse_day(data["to_week"], "to_week"),
                       current_user())
    return ok(res)


@bp.post("/api/shifts/publish")
@require("manage_staff")
def publish_shifts():
    data = body()
    first, last = st.range_from_args(data.get("start"), data.get("end"))
    return ok(st.publish(first, last, current_user()))


@bp.get("/api/shifts/open")
@login_required
def open_shifts():
    viewer = current_user()
    rows = db.query("SELECT * FROM shifts WHERE user_id IS NULL AND status = 'published' AND start_at > ? "
                    "ORDER BY start_at LIMIT 100", now_iso())
    held = set(st.position_ids_of(viewer["id"]))
    mine = {r["shift_id"] for r in db.query(
        "SELECT shift_id FROM shift_requests WHERE requester_id = ? AND kind = 'pickup' AND status = 'pending'", viewer["id"])}
    items = []
    for r in rows:
        s = st.serialize_shift(r)
        s["eligible"] = not r["position_id"] or r["position_id"] in held
        s["requested"] = r["id"] in mine
        items.append(s)
    return ok({"items": items, "requires_approval": bool(settings.get("staffing.pickup_requires_approval"))})


@bp.post("/api/shifts/<int:sid>/pickup")
@login_required
def pickup_shift(sid: int):
    req = st.create_request(current_user(), {"kind": "pickup", "shift_id": sid, "note": body().get("note")})
    return ok({"request": _request_out(req, current_user())}, 201)


# -- templates --------------------------------------------------------------------------


def _template_values(data: dict, partial: bool) -> dict:
    out = {}
    if "name" in data or not partial:
        name = (data.get("name") or "").strip()
        if not name:
            bad_request("Give the template a name")
        out["name"] = name[:80]
    for field in ("start_time", "end_time"):
        if field in data or not partial:
            if not st.valid_hhmm(data.get(field)):
                bad_request("Times must look like 08:30")
            out[field] = data[field][:5]
    for field, table in (("position_id", "positions"), ("location_id", "locations")):
        if field in data:
            value = as_int(data[field], field)
            if value and not db.one(f"SELECT id FROM {table} WHERE id = ?", value):
                bad_request(f"Unknown {field.replace('_id', '')}")
            out[field] = value
    if "break_minutes" in data:
        out["break_minutes"] = max(0, as_int(data["break_minutes"], "break_minutes") or 0)
    return out


@bp.get("/api/shift-templates")
@login_required
def list_templates():
    return ok({"items": db.query("SELECT * FROM shift_templates ORDER BY start_time, name")})


@bp.post("/api/shift-templates")
@require("manage_staff")
def create_template():
    values = _template_values(body(), partial=False)
    values["created_at"] = now_iso()
    with db.transaction():
        tid = db.insert("shift_templates", values)
    return ok({"item": db.one("SELECT * FROM shift_templates WHERE id = ?", tid)}, 201)


@bp.patch("/api/shift-templates/<int:tid>")
@require("manage_staff")
def update_template(tid: int):
    if not db.one("SELECT id FROM shift_templates WHERE id = ?", tid):
        not_found("Template not found")
    with db.transaction():
        db.update("shift_templates", tid, _template_values(body(), partial=True))
    return ok({"item": db.one("SELECT * FROM shift_templates WHERE id = ?", tid)})


@bp.delete("/api/shift-templates/<int:tid>")
@require("manage_staff")
def delete_template(tid: int):
    with db.transaction():
        db.delete("shift_templates", tid)
    return ok()


# -- swap / drop / pickup requests --------------------------------------------------------


def _request_out(r: dict, viewer: dict) -> dict:
    shift = db.one("SELECT * FROM shifts WHERE id = ?", r["shift_id"])
    target = db.one("SELECT * FROM shifts WHERE id = ?", r["target_shift_id"]) if r["target_shift_id"] else None
    manager = _is_manager(viewer)
    open_ = r["status"] in ("pending", "accepted")
    return {
        **r,
        "shift": st.serialize_shift(shift) if shift else None,
        "target_shift": st.serialize_shift(target) if target else None,
        "can_accept": open_ and r["kind"] == "swap" and r["status"] == "pending" and r["target_user_id"] == viewer["id"],
        "can_approve": open_ and manager and (r["kind"] != "swap" or r["status"] == "accepted"),
        "can_deny": open_ and (manager or (r["kind"] == "swap" and r["status"] == "pending" and r["target_user_id"] == viewer["id"])),
        "can_cancel": open_ and (r["requester_id"] == viewer["id"] or manager),
    }


@bp.get("/api/shift-requests")
@login_required
def list_requests():
    viewer = current_user()
    where, params = [], []
    if not _is_manager(viewer):
        where.append("(requester_id = ? OR target_user_id = ?)")
        params += [viewer["id"], viewer["id"]]
    status = request.args.get("status") or "open"
    if status == "open":
        where.append("status IN ('pending', 'accepted')")
    elif status != "all":
        where.append("status = ?")
        params.append(status)
    sql = "SELECT * FROM shift_requests" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at DESC LIMIT 200"
    return ok({"items": [_request_out(r, viewer) for r in db.query(sql, params)]})


@bp.post("/api/shift-requests")
@login_required
def create_request():
    req = st.create_request(current_user(), body())
    return ok({"request": _request_out(req, current_user())}, 201)


@bp.post("/api/shift-requests/<int:rid>/accept")
@login_required
def accept_request(rid: int):
    return ok({"request": _request_out(st.accept_request(current_user(), rid), current_user())})


@bp.post("/api/shift-requests/<int:rid>/approve")
@login_required
def approve_request(rid: int):
    note = (body().get("note") or "").strip()[:500] or None
    return ok({"request": _request_out(st.decide_request(current_user(), rid, True, note), current_user())})


@bp.post("/api/shift-requests/<int:rid>/deny")
@login_required
def deny_request(rid: int):
    note = (body().get("note") or "").strip()[:500] or None
    return ok({"request": _request_out(st.decide_request(current_user(), rid, False, note), current_user())})


@bp.post("/api/shift-requests/<int:rid>/cancel")
@login_required
def cancel_request(rid: int):
    return ok({"request": _request_out(st.cancel_request(current_user(), rid), current_user())})


# -- time clock -------------------------------------------------------------------------


def _clock_state(uid: int) -> dict:
    at = now()
    entry = st.open_entry(uid)
    day = st.today()
    todays = db.query("SELECT * FROM time_entries WHERE user_id = ? AND clock_in >= ? AND clock_in < ?",
                      uid, st.day_start(day), st.day_start(day + timedelta(days=1)))
    current = st.shift_covering(uid, at)
    upcoming = db.one("SELECT * FROM shifts WHERE user_id = ? AND status = 'published' AND start_at > ? "
                      "ORDER BY start_at LIMIT 1", uid, iso(at))
    return {
        "entry": st.serialize_entry(entry, at) if entry else None,
        "today_minutes": round(sum(st.worked_minutes(e, at) for e in todays), 2),
        "shift": st.serialize_shift(current) if current else None,
        "next_shift": st.serialize_shift(upcoming) if upcoming else None,
        "server_time": iso(at),
    }


@bp.get("/api/timeclock")
@login_required
def get_timeclock():
    return ok(_clock_state(current_user()["id"]))


@bp.post("/api/timeclock/in")
@login_required
def clock_in():
    data = body()
    st.punch(current_user()["id"], "in", job_id=as_int(data.get("job_id"), "job_id"), note=data.get("note"))
    return ok(_clock_state(current_user()["id"]))


@bp.post("/api/timeclock/out")
@login_required
def clock_out():
    st.punch(current_user()["id"], "out", note=body().get("note"))
    return ok(_clock_state(current_user()["id"]))


@bp.post("/api/timeclock/break/start")
@login_required
def break_start():
    st.punch(current_user()["id"], "break_start")
    return ok(_clock_state(current_user()["id"]))


@bp.post("/api/timeclock/break/end")
@login_required
def break_end():
    st.punch(current_user()["id"], "break_end")
    return ok(_clock_state(current_user()["id"]))


@bp.get("/api/timeclock/live")
@require("manage_staff")
def live():
    at = now()
    rows = db.query("SELECT * FROM time_entries WHERE clock_out IS NULL ORDER BY clock_in")
    items = []
    for e in rows:
        shift = db.one("SELECT * FROM shifts WHERE id = ?", e["shift_id"]) if e["shift_id"] else None
        items.append({**st.serialize_entry(e, at), "shift": st.serialize_shift(shift) if shift else None})
    return ok({"items": items})


def _entry_values(data: dict, existing: dict | None = None) -> dict:
    out = {}
    for field in ("clock_in", "clock_out"):
        if field in data:
            value = parse_iso(data[field]) if data[field] else None
            if field == "clock_in" and not value:
                bad_request("Clock-in time is required")
            out[field] = iso(value) if value else None
    clock_in = out.get("clock_in") or (existing or {}).get("clock_in")
    clock_out = out["clock_out"] if "clock_out" in out else (existing or {}).get("clock_out")
    if not clock_in:
        bad_request("Clock-in time is required")
    if clock_out and st.minutes_between(clock_in, clock_out) <= 0:
        bad_request("Clock-out has to be after clock-in")
    if clock_out and st.minutes_between(clock_in, clock_out) > 24 * 60:
        bad_request("An entry can't be longer than 24 hours")
    if "break_minutes" in data:
        out["break_minutes"] = max(0, as_int(data["break_minutes"], "break_minutes") or 0)
        out["breaks_json"] = "[]"
    if "job_id" in data:
        job_id = as_int(data["job_id"], "job_id")
        if job_id and not db.one("SELECT id FROM jobs WHERE id = ?", job_id):
            bad_request("No such job")
        out["job_id"] = job_id
    if "notes" in data:
        out["notes"] = (data["notes"] or "").strip()[:1000] or None
    return out


@bp.post("/api/time-entries")
@require("manage_staff")
def create_entry():
    viewer = current_user()
    data = body()
    uid = as_int(data.get("user_id"), "user_id")
    if not uid or not users_svc.get(uid):
        bad_request("Pick a person")
    values = _entry_values(data)
    if not values.get("clock_out"):
        bad_request("A manual entry needs a clock-out time")
    stamp = now_iso()
    values.update({"user_id": uid, "source": "manual", "created_by": viewer["id"], "created_at": stamp,
                   "updated_at": stamp})
    with db.transaction():
        eid = db.insert("time_entries", values)
        audit("time_entry.create", "time_entry", eid, {"user_id": uid, "clock_in": values["clock_in"],
                                                        "clock_out": values["clock_out"]})
        realtime.emit("timeclock.changed", {"user_id": uid}, users=sorted(set(st.manager_ids()) | {uid}))
    return ok({"item": st.serialize_entry(db.one("SELECT * FROM time_entries WHERE id = ?", eid))}, 201)


@bp.patch("/api/time-entries/<int:eid>")
@require("manage_staff")
def update_entry(eid: int):
    before = db.one("SELECT * FROM time_entries WHERE id = ?", eid)
    if not before:
        not_found("Time entry not found")
    values = _entry_values(body(), existing=before)
    if body().get("clear_flag") or "clock_out" in values:
        values["flag"] = None
    with db.transaction():
        values["updated_at"] = now_iso()
        db.update("time_entries", eid, values)
        audit("time_entry.update", "time_entry", eid, {
            "before": {k: before[k] for k in ("clock_in", "clock_out", "break_minutes", "job_id")},
            "after": {k: v for k, v in values.items() if k in ("clock_in", "clock_out", "break_minutes", "job_id")},
        })
        realtime.emit("timeclock.changed", {"user_id": before["user_id"]},
                      users=sorted(set(st.manager_ids()) | {before["user_id"]}))
    return ok({"item": st.serialize_entry(db.one("SELECT * FROM time_entries WHERE id = ?", eid))})


@bp.delete("/api/time-entries/<int:eid>")
@require("manage_staff")
def delete_entry(eid: int):
    before = db.one("SELECT * FROM time_entries WHERE id = ?", eid)
    if not before:
        not_found("Time entry not found")
    with db.transaction():
        db.delete("time_entries", eid)
        audit("time_entry.delete", "time_entry", eid, {"user_id": before["user_id"], "clock_in": before["clock_in"],
                                                        "clock_out": before["clock_out"]})
        realtime.emit("timeclock.changed", {"user_id": before["user_id"]},
                      users=sorted(set(st.manager_ids()) | {before["user_id"]}))
    return ok()


_kiosk_failures: dict[str, list[float]] = {}
_kiosk_lock = threading.Lock()
KIOSK_WINDOW = 300
KIOSK_MAX_FAILURES = 8


@bp.post("/api/kiosk/punch")
@require("manage_staff")
def kiosk_punch():
    """Shop tablet: a PIN identifies the person; punches toggle in / out."""
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
    cutoff = time.time() - KIOSK_WINDOW
    with _kiosk_lock:
        recent = [t for t in _kiosk_failures.get(ip, []) if t > cutoff]
        _kiosk_failures[ip] = recent
        if len(recent) >= KIOSK_MAX_FAILURES:
            raise ApiError(429, "too_many_attempts", "Too many wrong PINs. Wait a few minutes and try again.")
    pin = str(body().get("pin") or "").strip()
    match = None
    if pin.isdigit() and 4 <= len(pin) <= 8:
        for u in db.query("SELECT * FROM users WHERE is_active = 1 AND pin_hash IS NOT NULL ORDER BY id"):
            if check_password_hash(u["pin_hash"], pin):
                match = u
                break
    if not match:
        with _kiosk_lock:
            _kiosk_failures.setdefault(ip, []).append(time.time())
        raise ApiError(401, "wrong_pin", "That PIN doesn't match anyone")
    action = "out" if st.open_entry(match["id"]) else "in"
    entry = st.punch(match["id"], action, source="kiosk")
    at = entry["clock_out"] if action == "out" else entry["clock_in"]
    return ok({
        "user_id": match["id"], "name": match["name"], "color": match["color"], "action": action, "at": at,
        "worked_minutes": round(st.worked_minutes(entry), 2) if action == "out" else None,
        "shift": _clock_state(match["id"])["shift"],
    })


# -- timesheets -------------------------------------------------------------------------


def _timesheet_range() -> tuple[date, date]:
    if request.args.get("start"):
        return st.range_from_args(request.args.get("start"), request.args.get("end"))
    anchor = st.parse_day(request.args["date"], "date") if request.args.get("date") else st.today()
    return st.pay_period(anchor)


def _timesheet_people(viewer: dict) -> list[int]:
    uid = as_int(request.args.get("user_id"), "user_id")
    if not _is_manager(viewer):
        if uid and uid != viewer["id"]:
            forbidden("You can only see your own timesheet")
        return [viewer["id"]]
    if uid:
        return [uid]
    with_entries = set(db.column("SELECT DISTINCT user_id FROM time_entries"))
    schedulable = {u for u in st.everyone_ids() if st.profile(u).get("is_schedulable", 1)}
    return sorted(with_entries | schedulable)


@bp.get("/api/timesheets")
@login_required
def get_timesheets():
    viewer = current_user()
    first, last = _timesheet_range()
    people = _timesheet_people(viewer)
    rows = st.timesheets(first, last, people)
    length = (last - first).days
    return ok({
        "start": first.isoformat(),
        "end": last.isoformat(),
        "days": [d.isoformat() for d in st.days_between(first, last)],
        "prev": {"start": (first - timedelta(days=length)).isoformat(), "end": first.isoformat()},
        "next": {"start": last.isoformat(), "end": (last + timedelta(days=length)).isoformat()},
        "pay_period": settings.get("staffing.pay_period"),
        "people": rows,
        "can_manage": _is_manager(viewer),
    })


@bp.post("/api/timesheets/approve")
@require("manage_staff")
def approve_timesheets():
    viewer = current_user()
    data = body()
    require_fields(data, "start", "end")
    first, last = st.range_from_args(data["start"], data["end"])
    ids = [int(u) for u in data.get("user_ids") or []]
    if not ids:
        bad_request("Pick at least one person")
    stamp = now_iso()
    with db.transaction():
        cur = db.execute(
            f"UPDATE time_entries SET status = 'approved', approved_by = ?, approved_at = ?, updated_at = ? "
            f"WHERE user_id IN ({db.placeholders(ids)}) AND clock_out IS NOT NULL AND clock_in >= ? AND clock_in < ?",
            [viewer["id"], stamp, stamp, *ids, st.day_start(first), st.day_start(last)],
        )
        audit("timesheets.approve", data={"user_ids": ids, "start": first.isoformat(), "end": last.isoformat()})
        realtime.emit("timeclock.changed", {"approved": ids}, users=sorted(set(st.manager_ids()) | set(ids)))
    return ok({"approved_entries": cur.rowcount})


@bp.get("/api/timesheets/export.csv")
@login_required
def export_timesheets():
    viewer = current_user()
    first, last = _timesheet_range()
    people = _timesheet_people(viewer)
    rows = st.timesheets(first, last, people)
    profiles = {p["user_id"]: p for p in db.query("SELECT user_id, employee_number FROM staff_profiles")}
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Employee", "Employee number", "Date", "In", "Out", "Break minutes", "Regular hours",
                     "Overtime hours", "Job ID", "Status", "Notes"])
    for person in rows:
        name = users_svc.name_of(person["user_id"])
        number = (profiles.get(person["user_id"]) or {}).get("employee_number") or ""
        for e in person["entries"]:
            clock_in = st.local_dt(e["clock_in"])
            clock_out = st.local_dt(e["clock_out"]) if e["clock_out"] else None
            writer.writerow([
                name, number, clock_in.date().isoformat(), clock_in.strftime("%H:%M"),
                clock_out.strftime("%H:%M") if clock_out else "", int(round(e["break_minutes"])),
                f"{e['regular_minutes'] / 60:.2f}", f"{e['overtime_minutes'] / 60:.2f}", e["job_id"] or "",
                e["status"], (e["notes"] or "").replace("\n", " "),
            ])
    filename = f"timesheets-{first.isoformat()}-to-{(last - timedelta(days=1)).isoformat()}.csv"
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@bp.get("/api/staffing/counts")
@login_required
def counts():
    viewer = current_user()
    out = st.pending_counts(viewer)
    if _is_manager(viewer):
        today = st.today()
        out["drafts"] = db.scalar("SELECT COUNT(*) FROM shifts WHERE status = 'draft' AND start_at >= ? AND start_at < ?",
                                  st.day_start(st.week_start(today)), st.day_start(st.week_start(today) + timedelta(days=35)))
        out["clocked_in"] = len(staff_status.clocked_in_user_ids())
        out["flagged"] = db.scalar("SELECT COUNT(*) FROM time_entries WHERE flag IS NOT NULL")
    return ok(out)


# -- background -------------------------------------------------------------------------


def send_shift_reminders() -> int:
    lead = int(settings.get("staffing.shift_reminder_minutes") or 0)
    if lead <= 0:
        return 0
    at = now()
    rows = db.query(
        "SELECT * FROM shifts WHERE status = 'published' AND user_id IS NOT NULL AND reminded_at IS NULL "
        "AND start_at > ? AND start_at <= ?", iso(at), iso(at + timedelta(minutes=lead)),
    )
    for s in rows:
        with db.transaction():
            if not db.execute("UPDATE shifts SET reminded_at = ? WHERE id = ? AND reminded_at IS NULL",
                              now_iso(), s["id"]).rowcount:
                continue
            where = db.one("SELECT name FROM locations WHERE id = ?", s["location_id"]) if s["location_id"] else None
            notify.notify([s["user_id"]], "shift", f"Your shift starts at {st.fmt_time(s['start_at'])}",
                          body=f"{st.describe_shift(s)}" + (f" · {where['name']}" if where else ""),
                          link="/me", entity_type="shift", entity_id=s["id"])
    return len(rows)


def auto_clock_out() -> int:
    hours = float(settings.get("staffing.auto_clock_out_hours") or 0)
    if hours <= 0:
        return 0
    at = now()
    rows = db.query("SELECT * FROM time_entries WHERE clock_out IS NULL AND clock_in < ?",
                    iso(at - timedelta(hours=hours)))
    for e in rows:
        limit = parse_iso(e["clock_in"]) + timedelta(hours=hours)
        shift = db.one("SELECT * FROM shifts WHERE id = ?", e["shift_id"]) if e["shift_id"] else None
        out_at = limit
        if shift and parse_iso(e["clock_in"]) < parse_iso(shift["end_at"]) < limit:
            out_at = parse_iso(shift["end_at"])
        breaks = st.breaks_of(e)
        if breaks and not breaks[-1].get("end"):
            breaks[-1]["end"] = iso(max(out_at, parse_iso(breaks[-1]["start"])))
        with db.transaction():
            total = st.break_minutes({"breaks_json": db.jdump(breaks), "break_minutes": e["break_minutes"]})
            db.update("time_entries", e["id"], {
                "clock_out": iso(out_at), "breaks_json": db.jdump(breaks), "break_minutes": int(round(total)),
                "flag": "auto_clock_out", "updated_at": now_iso(),
            })
            name = users_svc.name_of(e["user_id"])
            notify.notify([e["user_id"]], "shift", "You were clocked out automatically",
                          body=f"Clocked out at {st.fmt_time(iso(out_at))}. Tell a manager if the time is wrong.",
                          link="/schedule/timesheets", entity_type="time_entry", entity_id=e["id"], include_actor=True)
            notify.notify([m for m in st.manager_ids() if m != e["user_id"]], "shift",
                          f"{name} forgot to clock out — please review", link="/schedule/timesheets",
                          entity_type="time_entry", entity_id=e["id"])
            realtime.emit("timeclock.changed", {"user_id": e["user_id"]},
                          users=sorted(set(st.manager_ids()) | {e["user_id"]}))
    return len(rows)


def worker_tasks():
    return [
        Task("staffing.shift_reminders", 60, send_shift_reminders),
        Task("staffing.auto_clock_out", 300, auto_clock_out),
    ]


# -- module hooks -----------------------------------------------------------------------


def bootstrap(user: dict) -> dict:
    return {
        "positions": _ref_rows("positions", user),
        "locations": _ref_rows("locations", user),
        "skills": _ref_rows("skills", user),
    }


def badges(user: dict) -> dict:
    counts = st.pending_counts(user)
    return {"schedule": counts["timeoff"] + counts["requests"] + counts["mine"]}


def search(user: dict, q: str, limit: int) -> list[dict]:
    like = f"%{q}%"
    rows = db.query("SELECT id, name, title FROM users WHERE is_active = 1 AND name LIKE ? ORDER BY name LIMIT ?", like, limit)
    names = {p["id"]: p["name"] for p in db.query("SELECT id, name FROM positions")}
    held = _positions_by_user()
    out = []
    for r in rows:
        roles = ", ".join(names[p] for p in held.get(r["id"], []) if p in names)
        out.append({"type": "staff", "id": r["id"], "title": r["name"],
                    "subtitle": "Schedule & profile" + (f" · {roles}" if roles else ""),
                    "url": f"/schedule/people/{r['id']}", "icon": "calendar-clock", "group": "People"})
    return out


DEFAULT_POSITIONS = [
    ("Front Desk", "#0c8599", 20.0), ("Designer", "#c2255c", 26.0), ("Press Operator", "#e8590c", 23.0),
    ("Bindery", "#2f9e44", 19.0), ("Driver", "#f08c00", 18.0),
]


def on_setup(ctx: dict) -> None:
    stamp = now_iso()
    for i, (name, color, rate) in enumerate(DEFAULT_POSITIONS):
        if not db.one("SELECT id FROM positions WHERE name = ?", name):
            db.insert("positions", {"name": name, "color": color, "default_rate": rate, "position": i, "created_at": stamp})
    if not db.one("SELECT id FROM locations LIMIT 1"):
        db.insert("locations", {"name": "Main shop", "color": "#3b5bdb", "created_at": stamp})
    if not db.one("SELECT id FROM shift_templates LIMIT 1"):
        for name, start, end, brk in (("Opening (6:30–3)", "06:30", "15:00", 30), ("Day (8–5)", "08:00", "17:00", 60),
                                      ("Mid (9–5:30)", "09:00", "17:30", 30), ("Evening (4–9)", "16:00", "21:00", 0),
                                      ("Saturday half day (8–12)", "08:00", "12:00", 0)):
            db.insert("shift_templates", {"name": name, "start_time": start, "end_time": end, "break_minutes": brk,
                                          "created_at": stamp})


def seed(ctx) -> None:
    from pps_tools.switchboard.demo.staffing import seed_staffing

    seed_staffing(ctx)
