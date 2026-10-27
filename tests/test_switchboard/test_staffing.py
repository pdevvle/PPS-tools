"""Staffing: positions, shifts & conflicts, publishing, swaps/drops/pickups, time off,
the time clock and kiosk, timesheets and overtime, background reminders."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import pytest

from pps_tools.switchboard import db
from pps_tools.switchboard.services import settings
from pps_tools.switchboard.services import staffing as st
from pps_tools.switchboard.util import iso, now, parse_iso


def future_week(weeks: int = 2) -> date:
    """Start of an org week safely in the future."""
    return st.week_start(st.today()) + timedelta(days=7 * weeks)


def day_in(week: date, weekday: int) -> str:
    """'YYYY-MM-DD' of the given weekday (Mon=0) within the org week."""
    return next((week + timedelta(days=i)).isoformat() for i in range(7) if (week + timedelta(days=i)).weekday() == weekday)


@pytest.fixture
def positions(client):
    return {p["name"]: p["id"] for p in client.get("/api/positions")["items"]}


@pytest.fixture
def press(client, make_user, positions):
    """A staff press operator."""
    user, api = make_user("staff", name="Alex Press")
    client.put(f"/api/staff/{user['id']}/positions", {"position_ids": [positions["Press Operator"]]})
    return user, api


def add_shift(client, user_id, day, start="08:00", end="16:30", brk=30, position=None, status="draft", expect=201):
    body = {"user_id": user_id, "date": day, "start_time": start, "end_time": end, "break_minutes": brk, "status": status}
    if position:
        body["position_id"] = position
    return client.post("/api/shifts", body, expect=expect)


def conflict_types(item):
    return {c["type"] for c in item["conflicts"]}


# -- reference data & people ---------------------------------------------------------


def test_setup_creates_positions_location_and_templates(client):
    names = [p["name"] for p in client.get("/api/positions")["items"]]
    assert {"Front Desk", "Designer", "Press Operator", "Bindery", "Driver"} <= set(names)
    assert client.get("/api/locations")["items"][0]["name"] == "Main shop"
    assert len(client.get("/api/shift-templates")["items"]) >= 3
    boot = client.get("/api/bootstrap")
    assert boot["positions"] and boot["locations"] is not None and "skills" in boot


def test_position_crud_and_permissions(client, make_user):
    _, staff = make_user("staff")
    staff.post("/api/positions", {"name": "Nope"}, expect=403)
    created = client.post("/api/positions", {"name": "Laminator", "default_rate": "17.5"})["item"]
    assert created["default_rate"] == 17.5
    client.post("/api/positions", {"name": "laminator"}, expect=409)
    client.patch(f"/api/positions/{created['id']}", {"is_active": False})
    # staff don't see pay rates
    item = next(p for p in staff.get("/api/positions")["items"] if p["id"] == created["id"])
    assert item["default_rate"] is None and item["is_active"] is False
    client.delete(f"/api/positions/{created['id']}")
    skill = client.post("/api/skills", {"name": "Offset press"})["item"]
    client.post("/api/skills", {"name": "Offset press"}, expect=409)
    client.delete(f"/api/skills/{skill['id']}")


def test_staff_profiles_rates_and_permissions(client, make_user, positions):
    staff_user, staff = make_user("staff")
    manager_user, manager = make_user("manager")
    client.patch(f"/api/staff/{staff_user['id']}", {"hourly_rate": 22, "employee_number": "PPS-9",
                                                     "employment_type": "part_time", "notes": "Great on the folder"})
    mine = staff.get(f"/api/staff/{staff_user['id']}")
    assert mine["profile"]["hourly_rate"] is None and mine["profile"]["notes"] is None
    assert manager.get(f"/api/staff/{staff_user['id']}")["profile"]["hourly_rate"] == 22
    # staff can only change their own emergency contact
    staff.patch(f"/api/staff/{staff_user['id']}", {"emergency_contact": "Mom 555-0100"})
    staff.patch(f"/api/staff/{staff_user['id']}", {"hourly_rate": 99}, expect=403)
    staff.patch(f"/api/staff/{manager_user['id']}", {"emergency_contact": "x"}, expect=403)
    client.patch(f"/api/staff/{staff_user['id']}", {"employment_type": "wizard"}, expect=400)
    listing = staff.get("/api/staff")["items"]
    row = next(i for i in listing if i["user"]["id"] == staff_user["id"])
    assert row["profile"]["employee_number"] == "PPS-9" and row["status"] == "off"
    assert all(i["profile"]["hourly_rate"] is None for i in listing)


def test_skills_and_availability(client, press):
    user, api = press
    # (the jobs module seeds common skills into the same table, so use a name it doesn't)
    skill = client.post("/api/skills", {"name": "Spot UV coater"})["item"]
    client.post("/api/skills", {"name": "spot uv coater"}, expect=409)
    client.put(f"/api/staff/{user['id']}/skills", {"skills": [{"skill_id": skill["id"], "level": 3}]})
    client.put(f"/api/staff/{user['id']}/skills", {"skills": [{"skill_id": skill["id"], "level": 7}]}, expect=400)
    assert client.get(f"/api/staff/{user['id']}")["skills"] == [{"skill_id": skill["id"], "level": 3}]
    api.put(f"/api/staff/{user['id']}/availability", {"items": [
        {"weekday": 0, "start_time": "06:00", "end_time": "15:00", "kind": "available"},
        {"weekday": 4, "start_time": "14:00", "end_time": "24:00", "kind": "unavailable"},
    ]})
    api.put(f"/api/staff/{user['id']}/availability", {"items": [{"weekday": 9, "start_time": "06:00", "end_time": "07:00"}]},
            expect=400)
    api.put(f"/api/staff/{user['id']}/availability", {"items": [{"weekday": 1, "start_time": "10:00", "end_time": "09:00"}]},
            expect=400)
    assert len(api.get(f"/api/staff/{user['id']}/availability")["items"]) == 2


# -- shifts & conflicts ------------------------------------------------------------------


def test_create_shift_local_times_and_overnight(client, press, positions):
    user, _ = press
    week = future_week()
    monday = day_in(week, 0)
    item = add_shift(client, user["id"], monday, "06:30", "15:00", 30, positions["Press Operator"])["item"]
    assert item["date"] == monday and item["start_time"] == "06:30" and item["end_time"] == "15:00"
    assert item["minutes"] == 480
    # Phoenix is UTC-7 all year
    assert item["start_at"].endswith("13:30:00.000Z")
    night = add_shift(client, user["id"], day_in(week, 2), "22:00", "06:00", 0)["item"]
    assert night["overnight"] is True and night["minutes"] == 480
    add_shift(client, user["id"], monday, "08:00", "09:00", 90, expect=400)  # break longer than the shift


def test_staff_only_see_published_and_cannot_edit(client, press):
    user, api = press
    week = future_week()
    draft = add_shift(client, user["id"], day_in(week, 1))["item"]
    published = add_shift(client, user["id"], day_in(week, 2), status="published")["item"]
    mine = api.get("/api/shifts", query_string={"start": week.isoformat()})
    assert [s["id"] for s in mine["items"]] == [published["id"]]
    assert mine["can_manage"] is False
    full = client.get("/api/shifts", query_string={"start": week.isoformat()})
    assert {s["id"] for s in full["items"]} == {draft["id"], published["id"]} and full["drafts"] == 1
    api.post("/api/shifts", {"user_id": user["id"], "date": day_in(week, 3), "start_time": "08:00", "end_time": "12:00"},
             expect=403)
    api.patch(f"/api/shifts/{published['id']}", {"notes": "x"}, expect=403)
    api.delete(f"/api/shifts/{published['id']}", expect=403)


def test_conflicts(client, press, positions):
    user, api = press
    uid = user["id"]
    week = future_week()
    mon, tue, wed, fri = (day_in(week, d) for d in (0, 1, 2, 4))
    a = add_shift(client, uid, mon, "08:00", "16:30", 30, positions["Press Operator"])["item"]
    assert a["conflicts"] == []
    overlap = add_shift(client, uid, mon, "16:00", "18:00", 0)["item"]
    assert "overlap" in conflict_types(overlap)
    # less than 10h rest: Monday shift ends 16:30/18:00, Tuesday starts 02:00
    early = add_shift(client, uid, tue, "02:00", "05:00", 0)["item"]
    assert "rest" in conflict_types(early)
    long_shift = add_shift(client, uid, wed, "05:00", "18:30", 30)["item"]
    assert "long" in conflict_types(long_shift)
    wrong = add_shift(client, uid, fri, "08:00", "12:00", 0, positions["Driver"])["item"]
    assert "position" in conflict_types(wrong)
    api.put(f"/api/staff/{uid}/availability", {"items": [
        {"weekday": 4, "start_time": "10:00", "end_time": "24:00", "kind": "unavailable"}]})
    refreshed = client.get("/api/shifts", query_string={"start": week.isoformat()})["items"]
    friday_shift = next(s for s in refreshed if s["id"] == wrong["id"])
    assert "unavailable" in conflict_types(friday_shift)
    errors = [c for c in friday_shift["conflicts"] if c["severity"] == "error"]
    assert errors == []


def test_outside_availability_and_time_off_conflicts(client, press):
    user, api = press
    uid = user["id"]
    week = future_week()
    api.put(f"/api/staff/{uid}/availability", {"items": [{"weekday": 1, "start_time": "16:00", "end_time": "22:00"}]})
    morning = add_shift(client, uid, day_in(week, 1), "09:00", "13:00", 0)["item"]
    assert "availability" in conflict_types(morning)
    evening = add_shift(client, uid, day_in(week, 1), "16:00", "21:00", 0)["item"]
    assert "availability" not in conflict_types(evening)
    off = api.post("/api/time-off", {"kind": "vacation", "start_date": day_in(week, 3), "end_date": day_in(week, 3)})["item"]
    thursday = add_shift(client, uid, day_in(week, 3), "16:00", "20:00", 0)["item"]
    assert "time_off_pending" in conflict_types(thursday)
    client.post(f"/api/time-off/{off['id']}/approve")
    refreshed = client.get("/api/shifts", query_string={"start": week.isoformat()})["items"]
    assert "time_off" in conflict_types(next(s for s in refreshed if s["id"] == thursday["id"]))


def test_weekly_overtime_conflict_and_totals(client, press, positions):
    user, _ = press
    week = future_week()
    for wd in range(5):
        add_shift(client, user["id"], day_in(week, wd), "07:00", "16:00", 0, positions["Press Operator"])
    res = client.get("/api/shifts", query_string={"start": week.isoformat()})
    items = sorted(res["items"], key=lambda s: s["start_at"])
    assert ["overtime" in conflict_types(s) for s in items] == [False, False, False, False, True]
    total = res["totals"][str(user["id"])]
    assert total["minutes"] == 45 * 60 and total["overtime_minutes"] == 5 * 60
    # rate falls back to the position's default rate
    rate = next(p for p in client.get("/api/positions")["items"] if p["id"] == positions["Press Operator"])["default_rate"]
    assert total["cost"] == pytest.approx(45 * rate)
    assert sum(d["shifts"] for d in res["day_totals"].values()) == 5


def test_publish_notifies_each_person_once(client, press, make_user):
    user, api = press
    other, other_api = make_user("staff")
    week = future_week()
    for wd in (0, 1, 2):
        add_shift(client, user["id"], day_in(week, wd))
    add_shift(client, other["id"], day_in(week, 3))
    res = client.post("/api/shifts/publish", {"start": week.isoformat(), "end": (week + timedelta(days=7)).isoformat()})
    assert res == {"published": 4, "people": 2}
    notes = [n for n in api.get("/api/notifications")["items"] if n["type"] == "shift"]
    assert len(notes) == 1 and "published" in notes[0]["title"]
    assert notes[0]["link"] == f"/schedule?week={week.isoformat()}"
    assert client.post("/api/shifts/publish", {"start": week.isoformat()}) == {"published": 0, "people": 0}
    # staff see the whole team's published schedule
    assert len(api.get("/api/shifts", query_string={"start": week.isoformat()})["items"]) == 4


def test_changing_published_shift_notifies(client, press, make_user):
    user, api = press
    other, other_api = make_user("staff")
    week = future_week()
    shift = add_shift(client, user["id"], day_in(week, 0), status="published")["item"]
    client.patch(f"/api/shifts/{shift['id']}", {"start_time": "09:00"})
    titles = [n["title"] for n in api.get("/api/notifications")["items"]]
    assert any(t.startswith("Your shift changed") for t in titles)
    client.patch(f"/api/shifts/{shift['id']}", {"user_id": other["id"]})
    assert any(t.startswith("New shift") for t in [n["title"] for n in other_api.get("/api/notifications")["items"]])
    assert any("removed you" in n["title"] for n in api.get("/api/notifications")["items"])
    client.delete(f"/api/shifts/{shift['id']}")
    assert any("removed you" in n["title"] for n in other_api.get("/api/notifications")["items"])


def test_copy_week_skips_overlaps(client, press):
    user, _ = press
    src = future_week(2)
    dst = future_week(3)
    add_shift(client, user["id"], day_in(src, 0), "06:30", "15:00", status="published")
    add_shift(client, user["id"], day_in(src, 1), "06:30", "15:00", status="published")
    add_shift(client, None, day_in(src, 5), "08:00", "12:00", 0)
    add_shift(client, user["id"], day_in(dst, 1), "07:00", "12:00")  # already booked Tuesday
    res = client.post("/api/shifts/copy-week", {"from_week": src.isoformat(), "to_week": dst.isoformat()})
    assert res == {"created": 2, "skipped": 1}
    copied = client.get("/api/shifts", query_string={"start": dst.isoformat()})["items"]
    monday = next(s for s in copied if s["date"] == day_in(dst, 0))
    assert monday["start_time"] == "06:30" and monday["status"] == "draft"
    assert any(s["user_id"] is None for s in copied)


# -- swap / drop / pickup ---------------------------------------------------------------


def test_swap_flow(client, press, make_user, positions):
    user, api = press
    other, other_api = make_user("staff")
    client.put(f"/api/staff/{other['id']}/positions", {"position_ids": [positions["Press Operator"]]})
    week = future_week()
    mine = add_shift(client, user["id"], day_in(week, 0), status="published")["item"]
    theirs = add_shift(client, other["id"], day_in(week, 2), status="published")["item"]
    req = api.post("/api/shift-requests", {"kind": "swap", "shift_id": mine["id"], "target_user_id": other["id"],
                                           "target_shift_id": theirs["id"], "note": "Dentist"})["request"]
    api.post("/api/shift-requests", {"kind": "swap", "shift_id": mine["id"], "target_user_id": other["id"]}, expect=409)
    assert other_api.get("/api/badges")["badges"]["schedule"] == 1
    # requester can't accept their own swap; the manager has to wait for the coworker
    api.post(f"/api/shift-requests/{req['id']}/accept", expect=403)
    client.post(f"/api/shift-requests/{req['id']}/approve", expect=400)
    accepted = other_api.post(f"/api/shift-requests/{req['id']}/accept")["request"]
    assert accepted["status"] == "accepted"
    other_api.post(f"/api/shift-requests/{req['id']}/approve", expect=403)
    assert client.get("/api/badges")["badges"]["schedule"] == 1
    done = client.post(f"/api/shift-requests/{req['id']}/approve", {"note": "OK"})["request"]
    assert done["status"] == "approved"
    after = {s["id"]: s for s in client.get("/api/shifts", query_string={"start": week.isoformat()})["items"]}
    assert after[mine["id"]]["user_id"] == other["id"] and after[theirs["id"]]["user_id"] == user["id"]
    assert any(n["title"].startswith("Approved") for n in api.get("/api/notifications")["items"])


def test_swap_without_manager_approval(client, press, make_user):
    settings.set("staffing.swap_requires_approval", False)
    user, api = press
    other, other_api = make_user("staff")
    shift = add_shift(client, user["id"], day_in(future_week(), 0), status="published")["item"]
    req = api.post("/api/shift-requests", {"kind": "swap", "shift_id": shift["id"], "target_user_id": other["id"]})["request"]
    assert other_api.post(f"/api/shift-requests/{req['id']}/accept")["request"]["status"] == "approved"
    assert db.one("SELECT user_id FROM shifts WHERE id = ?", shift["id"])["user_id"] == other["id"]


def test_drop_then_pickup(client, press, make_user, positions):
    user, api = press
    driver, driver_api = make_user("staff")
    client.put(f"/api/staff/{driver['id']}/positions", {"position_ids": [positions["Driver"]]})
    helper, helper_api = make_user("staff")
    client.put(f"/api/staff/{helper['id']}/positions", {"position_ids": [positions["Press Operator"]]})
    shift = add_shift(client, user["id"], day_in(future_week(), 1), position=positions["Press Operator"],
                      status="published")["item"]
    drop = api.post("/api/shift-requests", {"kind": "drop", "shift_id": shift["id"]})["request"]
    helper_api.post(f"/api/shift-requests/{drop['id']}/approve", expect=403)
    client.post(f"/api/shift-requests/{drop['id']}/approve")
    assert db.one("SELECT user_id FROM shifts WHERE id = ?", shift["id"])["user_id"] is None
    open_list = helper_api.get("/api/shifts/open")["items"]
    assert open_list[0]["id"] == shift["id"] and open_list[0]["eligible"] is True
    driver_api.post(f"/api/shifts/{shift['id']}/pickup", expect=403)  # wrong position
    pickup = helper_api.post(f"/api/shifts/{shift['id']}/pickup")["request"]
    assert pickup["status"] == "pending"
    client.post(f"/api/shift-requests/{pickup['id']}/approve")
    assert db.one("SELECT user_id FROM shifts WHERE id = ?", shift["id"])["user_id"] == helper["id"]


def test_instant_pickup_when_no_approval_needed(client, press):
    settings.set("staffing.pickup_requires_approval", False)
    user, api = press
    shift = add_shift(client, None, day_in(future_week(), 5), "08:00", "12:00", 0, status="published")["item"]
    assert api.post(f"/api/shifts/{shift['id']}/pickup")["request"]["status"] == "approved"
    assert db.one("SELECT user_id FROM shifts WHERE id = ?", shift["id"])["user_id"] == user["id"]
    api.post(f"/api/shifts/{shift['id']}/pickup", expect=400)  # not open any more


def test_requests_need_future_published_shifts(client, press):
    user, api = press
    draft = add_shift(client, user["id"], day_in(future_week(), 0))["item"]
    api.post("/api/shift-requests", {"kind": "drop", "shift_id": draft["id"]}, expect=400)
    past_day = (st.today() - timedelta(days=3)).isoformat()
    past = add_shift(client, user["id"], past_day, status="published")["item"]
    api.post("/api/shift-requests", {"kind": "drop", "shift_id": past["id"]}, expect=400)


# -- time off ---------------------------------------------------------------------------


def test_time_off_request_and_decisions(client, press, make_user):
    user, api = press
    manager, manager_api = make_user("manager")
    start = (st.today() + timedelta(days=20)).isoformat()
    end = (st.today() + timedelta(days=22)).isoformat()
    req = api.post("/api/time-off", {"kind": "vacation", "start_date": start, "end_date": end, "reason": "Trip"})["item"]
    assert req["status"] == "pending" and req["days"] == 3
    api.post("/api/time-off", {"kind": "sick", "start_date": start, "end_date": start}, expect=409)
    api.post("/api/time-off", {"kind": "vacation", "start_date": end, "end_date": start}, expect=400)
    api.post("/api/time-off", {"kind": "personal", "start_date": start, "end_date": end, "start_time": "09:00",
                               "end_time": "12:00"}, expect=400)
    assert any(n["type"] == "timeoff" for n in manager_api.get("/api/notifications")["items"])
    assert manager_api.get("/api/badges")["badges"]["schedule"] == 1
    api.post(f"/api/time-off/{req['id']}/approve", expect=403)
    # coworkers can't read each other's reasons
    _, coworker = make_user("staff")
    assert coworker.get("/api/time-off")["items"] == []
    res = manager_api.post(f"/api/time-off/{req['id']}/deny", {"note": "Busy week"})
    assert res["item"]["status"] == "denied"
    assert any("denied" in n["title"] for n in api.get("/api/notifications")["items"])
    again = api.post("/api/time-off", {"kind": "vacation", "start_date": start, "end_date": start})["item"]
    api.post(f"/api/time-off/{again['id']}/cancel")
    assert api.get("/api/time-off", query_string={"status": "cancelled"})["items"][0]["id"] == again["id"]


def test_manager_adds_time_off_for_someone_and_sees_clashing_shifts(client, press):
    user, api = press
    day = day_in(future_week(), 2)
    add_shift(client, user["id"], day, status="published")
    pending = api.post("/api/time-off", {"kind": "sick", "start_date": day, "end_date": day})["item"]
    res = client.post(f"/api/time-off/{pending['id']}/approve")
    assert len(res["conflicting_shifts"]) == 1
    other_day = day_in(future_week(3), 1)
    added = client.post("/api/time-off", {"user_id": user["id"], "kind": "personal", "start_date": other_day,
                                          "end_date": other_day, "start_time": "13:00", "end_time": "17:00"})["item"]
    assert added["status"] == "approved" and added["hours"] == 4


# -- time clock -------------------------------------------------------------------------


def test_time_clock_in_break_out(client, press):
    user, api = press
    state = api.get("/api/timeclock")
    assert state["entry"] is None
    state = api.post("/api/timeclock/in", {"note": "Starting the menus"})
    assert state["entry"]["clock_out"] is None
    api.post("/api/timeclock/in", expect=409)
    api.post("/api/timeclock/break/end", expect=409)
    assert api.post("/api/timeclock/break/start")["entry"]["on_break"] is True
    api.post("/api/timeclock/break/start", expect=409)
    assert api.post("/api/timeclock/break/end")["entry"]["on_break"] is False
    live = client.get("/api/timeclock/live")["items"]
    assert [e["user_id"] for e in live] == [user["id"]]
    api.get("/api/timeclock/live", expect=403)
    assert user["id"] in [i["user"]["id"] for i in client.get("/api/staff")["items"] if i["status"] == "clocked_in"]
    out = api.post("/api/timeclock/out")
    assert out["entry"] is None
    api.post("/api/timeclock/out", expect=409)
    entry = db.one("SELECT * FROM time_entries WHERE user_id = ?", user["id"])
    assert entry["clock_out"] and len(db.jload(entry["breaks_json"])) == 1


def test_clock_in_links_current_shift(client, press):
    user, api = press
    start = now() + timedelta(minutes=10)  # inside the early clock-in window
    client.post("/api/shifts", {"user_id": user["id"], "start_at": iso(start), "end_at": iso(start + timedelta(hours=8)),
                                "status": "published"})
    state = api.post("/api/timeclock/in")
    assert state["entry"]["shift_id"] is not None and state["shift"] is not None


def test_kiosk_punch_toggles_and_throttles(client, press, make_user):
    user, api = press
    api.post("/api/me/pin", {"pin": "4321"})
    _, staff_tablet = make_user("staff")
    staff_tablet.post("/api/kiosk/punch", {"pin": "4321"}, expect=403)
    res = client.post("/api/kiosk/punch", {"pin": "4321"})
    assert res["action"] == "in" and res["name"] == "Alex Press"
    res = client.post("/api/kiosk/punch", {"pin": "4321"})
    assert res["action"] == "out"
    assert db.one("SELECT source FROM time_entries WHERE user_id = ?", user["id"])["source"] == "kiosk"
    for _ in range(8):
        client.post("/api/kiosk/punch", {"pin": "0000"}, expect=401)
    client.post("/api/kiosk/punch", {"pin": "4321"}, expect=429)


# -- timesheets & overtime --------------------------------------------------------------


def _entry(client, uid, start, end, brk=0):
    return client.post("/api/time-entries", {"user_id": uid, "clock_in": start, "clock_out": end, "break_minutes": brk})["item"]


def test_timesheet_overtime_across_local_day_boundaries(client, press):
    """Phoenix (UTC-7): a Saturday 8pm–11pm shift is Sunday in UTC but belongs to the
    local Saturday and to the same week for overtime."""
    user, api = press
    uid = user["id"]
    week = date(2026, 9, 6)  # a Sunday; org weeks start on Sunday
    assert st.week_start(week) == week
    for i in range(1, 6):  # Mon..Fri 08:00–17:00 local = 9h each
        d = week + timedelta(days=i)
        _entry(client, uid, f"{d}T08:00:00-07:00", f"{d}T17:00:00-07:00")
    sat = week + timedelta(days=6)
    _entry(client, uid, f"{sat}T20:00:00-07:00", f"{sat}T23:00:00-07:00")
    sheet = client.get("/api/timesheets", query_string={"start": week.isoformat(), "end": (week + timedelta(days=7)).isoformat(),
                                                         "user_id": uid})
    person = sheet["people"][0]
    assert person["totals"]["worked"] == 48 * 60
    assert person["totals"]["regular"] == 40 * 60 and person["totals"]["overtime"] == 8 * 60
    by_day = {d["date"]: d for d in person["days"]}
    assert by_day[sat.isoformat()]["worked"] == 180 and by_day[sat.isoformat()]["overtime"] == 180
    assert by_day[str(week + timedelta(days=5))]["overtime"] == 5 * 60  # Friday crosses 40h
    # with an 8h daily threshold, every 9h weekday carries 1h of daily overtime
    settings.set("staffing.overtime_daily_hours", 8)
    person = client.get("/api/timesheets", query_string={"start": week.isoformat(), "user_id": uid})["people"][0]
    by_day = {d["date"]: d for d in person["days"]}
    assert by_day[str(week + timedelta(days=1))]["overtime"] == 60
    assert person["totals"]["overtime"] == 8 * 60
    # a partial range still counts the whole week for overtime
    saturday_only = client.get("/api/timesheets", query_string={"start": sat.isoformat(), "end": (sat + timedelta(days=1)).isoformat(),
                                                                "user_id": uid})["people"][0]
    assert saturday_only["totals"]["overtime"] == 180


def test_timesheet_approval_export_and_privacy(client, press, make_user):
    user, api = press
    other, other_api = make_user("staff")
    client.patch(f"/api/staff/{user['id']}", {"employee_number": "PPS-4"})
    week = date(2026, 9, 13)
    _entry(client, user["id"], "2026-09-14T06:30:00-07:00", "2026-09-14T15:00:00-07:00", 30)
    _entry(client, other["id"], "2026-09-14T08:00:00-07:00", "2026-09-14T12:00:00-07:00")
    other_api.get("/api/timesheets", query_string={"start": week.isoformat(), "user_id": user["id"]}, expect=403)
    mine = api.get("/api/timesheets", query_string={"start": week.isoformat()})
    assert [p["user_id"] for p in mine["people"]] == [user["id"]] and mine["people"][0]["approved"] is False
    client.post("/api/timesheets/approve", {"start": week.isoformat(), "end": (week + timedelta(days=7)).isoformat(),
                                            "user_ids": [user["id"]]})
    assert api.get("/api/timesheets", query_string={"start": week.isoformat()})["people"][0]["approved"] is True
    resp = client.raw("get", "/api/timesheets/export.csv", query_string={"start": week.isoformat()})
    assert resp.status_code == 200 and "attachment" in resp.headers["Content-Disposition"]
    rows = list(csv.DictReader(io.StringIO(resp.get_data(as_text=True))))
    row = next(r for r in rows if r["Employee"] == "Alex Press")
    assert row["Employee number"] == "PPS-4" and row["In"] == "06:30" and row["Out"] == "15:00"
    assert row["Break minutes"] == "30" and row["Regular hours"] == "8.00" and row["Status"] == "approved"


def test_pay_periods(client):
    settings.set("staffing.pay_period", "biweekly")
    settings.set("staffing.pay_period_anchor", "2026-01-04")
    start, end = st.pay_period(date(2026, 1, 14))
    assert (start, end) == (date(2026, 1, 4), date(2026, 1, 18))
    assert st.pay_period(date(2026, 1, 20)) == (date(2026, 1, 18), date(2026, 2, 1))
    settings.set("staffing.pay_period", "weekly")
    assert st.pay_period(date(2026, 1, 14)) == (date(2026, 1, 11), date(2026, 1, 18))
    settings.set("org.week_start", 1)
    assert st.pay_period(date(2026, 1, 14)) == (date(2026, 1, 12), date(2026, 1, 19))


def test_manual_entry_validation_and_audit(client, press):
    user, api = press
    api.post("/api/time-entries", {"user_id": user["id"], "clock_in": iso(now())}, expect=403)
    client.post("/api/time-entries", {"user_id": user["id"], "clock_in": iso(now()), "clock_out": iso(now() - timedelta(hours=1))},
                expect=400)
    entry = _entry(client, user["id"], iso(now() - timedelta(hours=9)), iso(now() - timedelta(hours=1)), 30)
    assert entry["worked_minutes"] == pytest.approx(450, abs=0.1)
    edited = client.patch(f"/api/time-entries/{entry['id']}", {"break_minutes": 0})["item"]
    assert edited["worked_minutes"] == pytest.approx(480, abs=0.1)
    assert db.scalar("SELECT COUNT(*) FROM audit_log WHERE action LIKE 'time_entry.%'") == 2
    client.delete(f"/api/time-entries/{entry['id']}")


def test_clock_rounding(client, press):
    settings.set("staffing.clock_rounding_minutes", 15)
    user, _ = press
    entry = _entry(client, user["id"], "2026-09-14T07:53:00-07:00", "2026-09-14T16:08:00-07:00")
    assert entry["worked_minutes"] == 8 * 60 + 15  # to the nearest 15 min: 7:53 -> 8:00, 16:08 -> 16:15


# -- background jobs & module hooks --------------------------------------------------------


def test_shift_reminder_sent_once(client, press):
    user, api = press
    from pps_tools.switchboard.api import staffing as staffing_api

    start = now() + timedelta(minutes=30)
    client.post("/api/shifts", {"user_id": user["id"], "start_at": iso(start), "end_at": iso(start + timedelta(hours=4)),
                                "status": "published"})
    assert staffing_api.send_shift_reminders() == 1
    assert staffing_api.send_shift_reminders() == 0
    titles = [n["title"] for n in api.get("/api/notifications")["items"]]
    assert sum(t.startswith("Your shift starts") for t in titles) == 1


def test_auto_clock_out_flags_entry(client, press):
    user, api = press
    from pps_tools.switchboard.api import staffing as staffing_api

    with db.transaction():
        db.insert("time_entries", {"user_id": user["id"], "clock_in": iso(now() - timedelta(hours=20)), "source": "clock",
                                   "created_at": iso(now()), "updated_at": iso(now())})
    assert staffing_api.auto_clock_out() == 1
    entry = db.one("SELECT * FROM time_entries WHERE user_id = ?", user["id"])
    assert entry["flag"] == "auto_clock_out"
    assert st.minutes_between(entry["clock_in"], entry["clock_out"]) == pytest.approx(14 * 60, abs=0.1)
    assert any("automatically" in n["title"] for n in api.get("/api/notifications")["items"])
    assert any("forgot to clock out" in n["title"] for n in client.get("/api/notifications")["items"])


def test_on_shift_status_feeds_inbox_assignment(client, press):
    from pps_tools.switchboard.services import staff_status

    user, api = press
    start = now() - timedelta(hours=1)
    client.post("/api/shifts", {"user_id": user["id"], "start_at": iso(start), "end_at": iso(start + timedelta(hours=8)),
                                "status": "published"})
    assert user["id"] in staff_status.on_shift_user_ids()
    assert staff_status.status_map()[user["id"]] == "on_shift"
    api.post("/api/timeclock/in")
    api.post("/api/timeclock/break/start")
    assert staff_status.status_map()[user["id"]] == "on_break"


def test_search_and_counts(client, press):
    user, api = press
    items = client.get("/api/search", query_string={"q": "Alex"})["items"]
    assert any(i["url"] == f"/schedule/people/{user['id']}" for i in items)
    counts = client.get("/api/staffing/counts")
    assert set(counts) >= {"timeoff", "requests", "mine", "drafts", "clocked_in"}
    assert set(api.get("/api/staffing/counts")) == {"timeoff", "requests", "mine"}


def test_demo_seed(app):
    from pps_tools.switchboard.api import staffing as staffing_api
    from pps_tools.switchboard.seed import SeedContext, seed_core

    ctx = SeedContext()
    with db.transaction():
        seed_core(ctx)
        staffing_api.on_setup({"owner_id": ctx.uid("owner"), "demo": True})
        staffing_api.seed(ctx)
    assert db.scalar("SELECT COUNT(*) FROM shifts WHERE status = 'draft'") > 0
    assert db.scalar("SELECT COUNT(*) FROM shifts WHERE status = 'published' AND user_id IS NULL") >= 1
    assert db.scalar("SELECT COUNT(*) FROM time_entries WHERE clock_out IS NULL") >= 1
    assert db.scalar("SELECT COUNT(*) FROM shift_requests WHERE status = 'pending'") == 1
    assert {"positions", "locations", "skills"} <= set(ctx.data)
    week = parse_iso(st.day_start(date.fromisoformat(ctx.data["staffing_weeks"]["next"])))
    drafts = [st.serialize_shift(r) for r in db.query("SELECT * FROM shifts WHERE start_at >= ?", iso(week))]
    st.annotate_conflicts(drafts)
    kinds = {c["type"] for s in drafts for c in s["conflicts"]}
    assert {"time_off", "unavailable", "availability", "overtime"} <= kinds
