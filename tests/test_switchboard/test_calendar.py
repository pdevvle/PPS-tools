"""Calendar: calendars, recurrence (incl. DST), occurrence edits, overlays, ICS export,
the private feed, subscriptions, reminders and permissions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pps_tools.switchboard import db
from pps_tools.switchboard.services import calendars as cal_svc
from pps_tools.switchboard.util import iso, now, now_iso

UTC = timezone.utc


def events(client, start, end, **query):
    q = {"start": start, "end": end, **query}
    return client.get("/api/calendar/events", query_string=q)["items"]


def shop_calendar(client):
    return next(c for c in client.get("/api/calendars")["items"] if c["name"] == "Shop calendar")


def test_calendars_list_includes_personal_and_shared(client, owner):
    cals = client.get("/api/calendars")["items"]
    kinds = {(c["kind"], c["name"]) for c in cals}
    assert ("personal", "Olivia Owner") in kinds and ("shared", "Shop calendar") in kinds
    personal = next(c for c in cals if c["kind"] == "personal")
    assert personal["is_mine"] and personal["can_write"]


def test_event_crud_and_range_query(client):
    cal = shop_calendar(client)
    ev = client.post("/api/calendar/events", {"calendar_id": cal["id"], "title": "Team lunch",
                                              "start_at": "2026-11-06T19:00:00Z", "end_at": "2026-11-06T20:00:00Z",
                                              "location": "Taqueria"})["event"]
    assert ev["title"] == "Team lunch" and ev["calendar"]["name"] == "Shop calendar"
    found = events(client, "2026-11-01T00:00:00Z", "2026-11-08T00:00:00Z")
    assert [e["title"] for e in found] == ["Team lunch"]
    assert events(client, "2026-11-07T00:00:00Z", "2026-11-08T00:00:00Z") == []
    client.patch(f"/api/calendar/events/{ev['id']}", {"title": "Team lunch 🌮", "end_at": "2026-11-06T20:30:00Z"})
    got = client.get(f"/api/calendar/events/{ev['id']}")["event"]
    assert got["title"] == "Team lunch 🌮" and got["end"] == "2026-11-06T20:30:00.000Z"
    client.delete(f"/api/calendar/events/{ev['id']}")
    client.get(f"/api/calendar/events/{ev['id']}", expect=404)


def test_validation(client):
    client.post("/api/calendar/events", {"title": "", "start_at": "2026-11-06T19:00:00Z"}, expect=400)
    client.post("/api/calendar/events", {"title": "x", "start_at": "2026-11-06T19:00:00Z", "end_at": "2026-11-06T18:00:00Z"}, expect=400)
    err = client.post("/api/calendar/events", {"title": "x", "start_at": "2026-11-06T19:00:00Z", "rrule": "FREQ=HOURLY"}, expect=400)
    assert err["error"]["code"] == "bad_rrule"
    client.get("/api/calendar/events", query_string={"start": "2026-01-01T00:00:00Z", "end": "2027-12-01T00:00:00Z"}, expect=400)


def test_all_day_events(client):
    ev = client.post("/api/calendar/events", {"title": "Files due", "all_day": True, "start_date": "2026-11-05",
                                              "end_date": "2026-11-06"})["event"]
    assert ev["all_day"] and ev["start_date"] == "2026-11-05" and ev["end_date"] == "2026-11-06"
    # Phoenix midnight = 07:00Z
    assert ev["start"] == "2026-11-05T07:00:00.000Z" and ev["end"] == "2026-11-07T07:00:00.000Z"


@pytest.mark.parametrize("zone, first, second", [
    # US daylight saving ends Sunday 2026-11-01: 8am stays 8am on the wall clock
    ("America/New_York", "2026-10-26T12:00:00.000Z", "2026-11-02T13:00:00.000Z"),
    # Arizona has no DST
    ("America/Phoenix", "2026-10-26T15:00:00.000Z", "2026-11-02T15:00:00.000Z"),
])
def test_weekly_recurrence_keeps_wall_time(client, zone, first, second):
    client.patch("/api/settings", {"org.timezone": zone})
    client.post("/api/calendar/events", {"title": "Production meeting", "start_at": first,
                                         "end_at": iso(datetime.fromisoformat(first.replace("Z", "+00:00")) + timedelta(minutes=30)),
                                         "rrule": "FREQ=WEEKLY;BYDAY=MO"})
    found = events(client, "2026-10-25T00:00:00Z", "2026-11-04T00:00:00Z")
    assert [e["start"] for e in found] == [first, second]
    assert all(e["recurring"] for e in found)
    assert found[1]["original_start"] == second


def test_rrule_count_until_and_monthly_rules():
    tz = cal_svc.get_zone("America/Phoenix")
    r0, r1 = datetime(2026, 10, 1, tzinfo=UTC), datetime(2027, 3, 1, tzinfo=UTC)

    def starts(start, rrule, exdates=None):
        end = iso(datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(hours=1))
        return [iso(s)[:10] for s, _ in cal_svc.occurrences(start, end, rrule, exdates, r0, r1, tz)]

    assert starts("2026-10-27T16:00:00Z", "FREQ=WEEKLY;BYDAY=TU,TH;COUNT=4") == ["2026-10-27", "2026-10-29", "2026-11-03", "2026-11-05"]
    assert starts("2026-10-27T16:00:00Z", "FREQ=DAILY;UNTIL=20261030") == ["2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]
    assert starts("2026-10-30T16:00:00Z", "FREQ=MONTHLY;BYDAY=-1FR")[:3] == ["2026-10-30", "2026-11-27", "2026-12-25"]
    assert starts("2026-10-31T16:00:00Z", "FREQ=MONTHLY;BYMONTHDAY=31")[:3] == ["2026-10-31", "2026-12-31", "2027-01-31"]
    assert starts("2026-10-27T16:00:00Z", "FREQ=WEEKLY;INTERVAL=2;COUNT=3") == ["2026-10-27", "2026-11-10", "2026-11-24"]
    # COUNT counts excluded dates too (RFC 5545)
    assert starts("2026-10-27T16:00:00Z", "FREQ=DAILY;COUNT=3", ["2026-10-28T16:00:00.000Z"]) == ["2026-10-27", "2026-10-29"]
    # far-future ranges don't need to walk from the start (no COUNT)
    far = cal_svc.occurrences("2020-01-06T16:00:00Z", "2020-01-06T17:00:00Z", "FREQ=DAILY", [],
                              datetime(2026, 11, 2, tzinfo=UTC), datetime(2026, 11, 4, tzinfo=UTC), tz)
    assert [iso(s)[:10] for s, _ in far] == ["2026-11-02", "2026-11-03"]


def test_edit_one_following_and_delete_one(client):
    ev = client.post("/api/calendar/events", {"title": "Delivery run", "start_at": "2026-11-02T21:00:00Z",
                                              "end_at": "2026-11-02T23:00:00Z", "rrule": "FREQ=DAILY;COUNT=5"})["event"]
    eid = ev["id"]
    rng = ("2026-11-01T00:00:00Z", "2026-11-10T00:00:00Z")
    assert len(events(client, *rng)) == 5
    # just the 2nd occurrence moves an hour later
    client.patch(f"/api/calendar/events/{eid}?scope=one&original_start=2026-11-03T21:00:00Z",
                 {"title": "Delivery run (late)", "start_at": "2026-11-03T22:00:00Z", "end_at": "2026-11-04T00:00:00Z"})
    found = events(client, *rng)
    assert [(e["start"][:16], e["title"]) for e in found][:2] == [("2026-11-02T21:00", "Delivery run"),
                                                                  ("2026-11-03T22:00", "Delivery run (late)")]
    assert len(found) == 5
    # from the 4th on, the title changes
    client.patch(f"/api/calendar/events/{eid}?scope=following&original_start=2026-11-05T21:00:00Z", {"title": "Delivery (new route)"})
    titles = [e["title"] for e in events(client, *rng)]
    assert titles == ["Delivery run", "Delivery run (late)", "Delivery run", "Delivery (new route)", "Delivery (new route)"]
    # delete only the first occurrence
    client.delete(f"/api/calendar/events/{eid}?scope=one&original_start=2026-11-02T21:00:00Z")
    assert [e["start"][:10] for e in events(client, *rng)][0] == "2026-11-03"
    client.patch(f"/api/calendar/events/{eid}?scope=one", {"title": "x"}, expect=400)  # needs original_start


def test_moving_an_occurrence_with_scope_all_shifts_the_series(client):
    ev = client.post("/api/calendar/events", {"title": "Standup", "start_at": "2026-11-02T15:00:00Z",
                                              "end_at": "2026-11-02T15:15:00Z", "rrule": "FREQ=DAILY;COUNT=3"})["event"]
    client.patch(f"/api/calendar/events/{ev['id']}?scope=all&original_start=2026-11-03T15:00:00Z",
                 {"start_at": "2026-11-03T16:00:00Z", "end_at": "2026-11-03T16:15:00Z"})
    starts = [e["start"][:16] for e in events(client, "2026-11-01T00:00:00Z", "2026-11-10T00:00:00Z")]
    assert starts == ["2026-11-02T16:00", "2026-11-03T16:00", "2026-11-04T16:00"]


def _seed_overlays(owner_id):
    stamp = now_iso()
    with db.transaction():
        pos = db.insert("positions", {"name": "Press Operator", "color": "#e8590c", "created_at": stamp})
        db.insert("shifts", {"user_id": owner_id, "position_id": pos, "start_at": "2026-11-03T15:00:00.000Z",
                             "end_at": "2026-11-03T23:00:00.000Z", "status": "published", "created_at": stamp})
        db.insert("shifts", {"user_id": owner_id, "start_at": "2026-11-04T15:00:00.000Z", "end_at": "2026-11-04T23:00:00.000Z",
                             "status": "draft", "created_at": stamp})
        db.insert("time_off_requests", {"user_id": owner_id, "kind": "vacation", "start_date": "2026-11-05",
                                        "end_date": "2026-11-06", "status": "approved", "created_at": stamp})
        stage = db.insert("job_stages", {"name": "Printing", "color": "#7048e8", "created_at": stamp})
        job = db.insert("jobs", {"number": "J-1042", "title": "Gala programs", "stage_id": stage,
                                 "due_at": "2026-11-06T22:00:00.000Z", "created_at": stamp})
        db.insert("job_operations", {"job_id": job, "name": "Print covers", "user_id": owner_id,
                                     "start_at": "2026-11-04T16:00:00.000Z", "end_at": "2026-11-04T18:00:00.000Z",
                                     "created_at": stamp})


def test_overlays_from_other_modules(client, owner):
    _seed_overlays(owner["id"])
    rng = ("2026-11-01T00:00:00Z", "2026-11-10T00:00:00Z")
    assert events(client, *rng) == []
    items = events(client, *rng, overlays="shifts,jobs,operations,timeoff")
    kinds = sorted(i["kind"] for i in items)
    assert kinds == ["job_due", "operation", "shift", "timeoff"]   # draft shift excluded
    shift = next(i for i in items if i["kind"] == "shift")
    assert shift["title"] == "Shift · Press Operator" and shift["read_only"]
    off = next(i for i in items if i["kind"] == "timeoff")
    assert off["all_day"] and off["start_date"] == "2026-11-05" and off["end_date"] == "2026-11-06"
    assert next(i for i in items if i["kind"] == "job_due")["url"].startswith("/jobs/")


def test_ics_export_and_private_feed(client, owner, anon, make_user):
    _seed_overlays(owner["id"])
    mine = client.post("/api/calendar/events", {"title": "Chamber mixer, downtown", "start_at": iso(now() + timedelta(days=2)),
                                                "description": "Bring; cards\nand flyers"})["event"]
    other, other_client = make_user("agent")
    other_client.post("/api/calendar/events", {"title": "Private dentist", "start_at": iso(now() + timedelta(days=3))})
    shop = shop_calendar(client)
    weekly = client.post("/api/calendar/events", {"calendar_id": shop["id"], "title": "Weekly meeting",
                                                  "start_at": iso(now() + timedelta(days=1)), "rrule": "FREQ=WEEKLY;COUNT=3",
                                                  "attendees": [owner["id"]]})["event"]
    ics = client.raw("get", f"/api/calendars/{shop['id']}/export.ics")
    text = ics.get_data(as_text=True)
    assert ics.mimetype == "text/calendar" and text.startswith("BEGIN:VCALENDAR")
    assert text.count("SUMMARY:Weekly meeting") == 3          # expanded occurrences
    token = db.one("SELECT feed_token FROM users WHERE id = ?", owner["id"])["feed_token"]
    feed = anon.raw("get", f"/feeds/{token}.ics")
    body = feed.get_data(as_text=True)
    assert feed.status_code == 200
    assert "SUMMARY:Chamber mixer\\, downtown" in body and "DESCRIPTION:Bring\\; cards\\nand flyers" in body
    assert "SUMMARY:Weekly meeting" in body                    # invited
    assert "Private dentist" not in body                       # someone else's
    assert "SUMMARY:Shift · Press Operator" in body
    assert "SUMMARY:Time off" in body
    assert "J-1042 · Print covers" in body
    assert anon.raw("get", "/feeds/nope.ics").status_code == 404
    del mine, weekly, other


SAMPLE_ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:holiday-1\r
DTSTART;VALUE=DATE:20261126\r
DTEND;VALUE=DATE:20261127\r
SUMMARY:Thanksgiving\\, shop closed\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:standup\r
DTSTART;TZID=America/Phoenix:20261102T090000\r
DTEND;TZID=America/Phoenix:20261102T091500\r
RRULE:FREQ=DAILY;COUNT=4\r
EXDATE;TZID=America/Phoenix:20261103T090000\r
SUMMARY:Vendor standup\r
DESCRIPTION:Line one\\nline t\r
 wo\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:standup\r
RECURRENCE-ID;TZID=America/Phoenix:20261104T090000\r
DTSTART;TZID=America/Phoenix:20261104T100000\r
DURATION:PT30M\r
SUMMARY:Vendor standup (moved)\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:gone\r
DTSTART:20261102T200000Z\r
STATUS:CANCELLED\r
SUMMARY:Cancelled thing\r
END:VEVENT\r
END:VCALENDAR\r
"""


def test_parse_ics_and_subscription_import(client, monkeypatch):
    parsed = cal_svc.parse_ics(SAMPLE_ICS, cal_svc.get_zone("America/Phoenix"))
    by_title = {p["title"]: p for p in parsed}
    assert "Cancelled thing" not in by_title
    assert by_title["Thanksgiving, shop closed"]["all_day"]
    standup = by_title["Vendor standup"]
    assert standup["rrule"] == "FREQ=DAILY;COUNT=4" and standup["description"] == "Line one\nline two"
    assert standup["exdates"] == ["2026-11-03T16:00:00.000Z"]

    class Resp:
        status_code = 200
        encoding = "utf-8"
        content = SAMPLE_ICS.encode()

        def raise_for_status(self):
            pass

    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp())
    cal = client.post("/api/calendars", {"name": "Vendor calendar", "kind": "subscription",
                                         "ics_url": "webcal://vendor.test/cal.ics"}, expect=201)["calendar"]
    assert cal["sync_error"] is None and cal["can_write"] is False
    found = events(client, "2026-11-01T00:00:00Z", "2026-11-30T00:00:00Z")
    got = [(e["title"], e["start"][:16]) for e in found if e["calendar_id"] == cal["id"]]
    assert ("Vendor standup", "2026-11-02T16:00") in got
    assert ("Vendor standup (moved)", "2026-11-04T17:00") in got
    assert ("Vendor standup", "2026-11-04T16:00") not in got     # replaced by the override
    assert ("Vendor standup", "2026-11-03T16:00") not in got     # EXDATE
    assert all(e["read_only"] for e in found if e["calendar_id"] == cal["id"])
    ev_id = next(e for e in found if e["calendar_id"] == cal["id"])["event_id"]
    client.patch(f"/api/calendar/events/{ev_id}", {"title": "nope"}, expect=403)

    def boom(*a, **k):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", boom)
    res = client.post(f"/api/calendars/{cal['id']}/sync")
    assert "offline" in res["calendar"]["sync_error"]


def test_attendees_notified_and_reminders_fire_once(client, owner, make_user):
    agent, agent_client = make_user("agent")
    start = now() + timedelta(minutes=10)
    ev = client.post("/api/calendar/events", {"calendar_id": shop_calendar(client)["id"], "title": "Proof review",
                                              "start_at": iso(start), "attendees": [agent["id"]], "reminder_minutes": 15})["event"]
    invite = agent_client.get("/api/notifications")["items"][0]
    assert invite["title"].endswith("invited you: Proof review")
    assert cal_svc.process_reminders() == 1
    assert cal_svc.process_reminders() == 0
    assert agent_client.get("/api/notifications")["items"][0]["title"].startswith("Proof review starts at")
    owner_notes = client.get("/api/notifications")["items"]
    assert owner_notes and owner_notes[0]["title"].startswith("Proof review starts")
    del ev


def test_permissions(client, owner, make_user):
    _, staff = make_user("staff")
    shop = shop_calendar(client)
    ev = client.post("/api/calendar/events", {"calendar_id": shop["id"], "title": "Owner's event",
                                              "start_at": "2026-11-06T19:00:00Z"})["event"]
    staff.patch(f"/api/calendar/events/{ev['id']}", {"title": "hijack"}, expect=403)
    own = staff.post("/api/calendar/events", {"calendar_id": shop["id"], "title": "Staff event",
                                              "start_at": "2026-11-06T19:00:00Z"})["event"]
    staff.patch(f"/api/calendar/events/{own['id']}", {"title": "Staff event!"})
    staff.post("/api/calendars", {"name": "Staff shared", "kind": "shared"}, expect=403)
    # someone else's personal calendar is invisible
    personal = next(c for c in client.get("/api/calendars")["items"] if c["kind"] == "personal")
    secret = client.post("/api/calendar/events", {"calendar_id": personal["id"], "title": "Secret",
                                                  "start_at": "2026-11-06T19:00:00Z"})["event"]
    staff.get(f"/api/calendar/events/{secret['id']}", expect=404)
    staff.post("/api/calendar/events", {"calendar_id": personal["id"], "title": "x", "start_at": "2026-11-06T19:00:00Z"}, expect=404)
    assert "Secret" not in [e["title"] for e in events(staff, "2026-11-01T00:00:00Z", "2026-11-10T00:00:00Z")]


def test_agenda_and_search(client):
    client.post("/api/calendar/events", {"title": "Paper vendor visit", "start_at": iso(now() + timedelta(hours=3))})
    agenda = client.get("/api/calendar/agenda")["items"]
    assert [e["title"] for e in agenda] == ["Paper vendor visit"]
    items = client.get("/api/search", query_string={"q": "vendor visit"})["items"]
    assert any(i["type"] == "event" for i in items)
