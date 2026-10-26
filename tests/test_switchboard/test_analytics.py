"""Reports: percentile math, local-day bucketing, the inbox / team / jobs reports on
hand-built data, CSV export, validation, permissions and the demo history."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

import pytest

from pps_tools.switchboard import db
from pps_tools.switchboard.services import analytics, settings
from pps_tools.switchboard.util import get_zone, iso, now, now_iso, token

PHX = get_zone("America/Phoenix")  # the test workspace's timezone: UTC-7, no DST


def at(day: date, hm: str) -> str:
    """A Phoenix wall-clock time, stored the way the app stores instants."""
    h, m = (int(x) for x in hm.split(":"))
    return iso(datetime(day.year, day.month, day.day, h, m, tzinfo=PHX))


@pytest.fixture
def monday(client):
    """A Monday three weeks back, so every timestamp in these tests is in the past."""
    d = now().astimezone(PHX).date() - timedelta(days=21)
    return d - timedelta(days=d.weekday())


def set_setting(key, value):
    with db.transaction():
        settings.set(key, value)


def add_channel(visibility="shared", owner_id=None):
    with db.transaction():
        return db.insert("channels", {
            "type": "email", "name": f"Mail {token(3)}", "address": f"{token(4)}@shop.test", "visibility": visibility,
            "owner_user_id": owner_id, "config_json": "{}", "public_key": token(8), "created_at": now_iso(),
        })


def add_conversation(channel_id, inbound_at, reply_at=None, author_id=None, closed_at=None, closed_by=None, **fields):
    """One customer message, optionally one reply and a close."""
    with db.transaction():
        cid = db.insert("conversations", {
            "subject": fields.pop("subject", "Quote request"), "channel_id": channel_id,
            "status": "closed" if closed_at else "open", "last_activity_at": closed_at or reply_at or inbound_at,
            "last_message_at": reply_at or inbound_at, "last_inbound_at": inbound_at, "last_outbound_at": reply_at,
            "first_response_at": reply_at, "closed_at": closed_at, "closed_by": closed_by, "created_at": inbound_at,
            **fields,
        })
        db.insert("messages", {
            "conversation_id": cid, "channel_id": channel_id, "direction": "in", "kind": "email",
            "from_handle": "ann@cust.test", "status": "received", "date": inbound_at, "created_at": inbound_at,
        })
        if reply_at:
            db.insert("messages", {
                "conversation_id": cid, "channel_id": channel_id, "direction": "out", "kind": "email",
                "author_id": author_id, "status": "sent", "sent_at": reply_at, "date": reply_at, "created_at": reply_at,
            })
    return cid


# -- math ------------------------------------------------------------------------------


def test_percentile_uses_linear_interpolation():
    assert analytics.percentile([], 50) is None
    assert analytics.percentile([7], 90) == 7
    assert analytics.percentile([4, 1, 3, 2], 50) == 2.5
    assert analytics.percentile([10, 20, 30, 40, 50], 90) == 46
    assert analytics.stats([30, 10, 20, 100]) == {"count": 4, "median": 25.0, "average": 40.0, "p90": 79.0}
    assert analytics.stats([]) == {"count": 0, "median": None, "average": None, "p90": None}


def test_day_pieces_split_at_local_midnight():
    start = datetime(2026, 3, 9, 22, 0, tzinfo=PHX)
    pieces = analytics.day_pieces(start, start + timedelta(hours=4), PHX)
    assert pieces == [(date(2026, 3, 9), 120.0), (date(2026, 3, 10), 120.0)]
    assert analytics.day_pieces(start, start, PHX) == []


def test_week_start_follows_the_org_setting(client):
    wednesday = date(2026, 10, 28)
    set_setting("org.week_start", 1)
    assert analytics.week_start(wednesday) == date(2026, 10, 26)
    assert analytics.weekday_order()[0] == 0  # Monday first
    set_setting("org.week_start", 0)
    assert analytics.week_start(wednesday) == date(2026, 10, 25)
    assert analytics.weekday_order()[0] == 6  # Sunday first


def test_range_validation(client):
    client.get("/api/analytics/inbox?start=2026-05-10&end=2026-05-01", expect=400)
    client.get("/api/analytics/inbox?start=2024-01-01&end=2025-06-01", expect=400)
    client.get("/api/analytics/nope", expect=404)
    res = client.get("/api/analytics/inbox")
    assert res["period"]["days"] == 30 and res["period"]["timezone"] == "America/Phoenix"


# -- inbox -----------------------------------------------------------------------------


def test_inbox_report_math_and_local_day_buckets(client, owner, monday):
    set_setting("inbox.sla_first_response_minutes", 60)
    tue = monday + timedelta(days=1)
    shared = add_channel()
    personal = add_channel("personal", owner["id"])
    me = owner["id"]
    # 11:30 PM Monday in Phoenix is already Tuesday in UTC: it must count on Monday.
    add_conversation(shared, at(monday, "23:30"), at(tue, "00:10"), me, closed_at=at(tue, "09:00"), closed_by=me)  # 40 min
    add_conversation(shared, at(tue, "08:00"), at(tue, "08:10"), me)       # 10 min
    add_conversation(shared, at(tue, "09:00"), at(tue, "11:00"), me)       # 120 min
    add_conversation(personal, at(tue, "10:00"), at(tue, "10:01"), me)     # private: left out
    add_conversation(shared, at(tue, "10:00"), is_spam=1)                  # spam: left out

    res = client.get(f"/api/analytics/inbox?start={monday}&end={tue}")
    t = res["totals"]
    assert (t["conversations"], t["received"], t["sent"], t["closed"]) == (3, 3, 3, 1)
    assert t["median_first_response"] == 40.0
    assert res["daily"] == [
        {"date": monday.isoformat(), "received": 1, "sent": 0, "closed": 0},
        {"date": tue.isoformat(), "received": 2, "sent": 3, "closed": 1},
    ]
    assert res["first_response"] == {"count": 3, "median": 40.0, "average": 56.7, "p90": 104.0}
    assert res["resolution"] == {"count": 1, "median": 570.0, "average": 570.0, "p90": 570.0}
    assert res["sla"] == {"target_minutes": 60, "responded": 3, "within": 2, "late": 1, "waiting_over": 0,
                          "breaches": 1, "within_pct": 66.7}

    days = res["heatmap"]["weekdays"]
    cells = res["heatmap"]["cells"]
    assert cells[days.index("Mon")][23] == 1
    assert cells[days.index("Tue")][8] == 1 and cells[days.index("Tue")][9] == 1
    assert sum(map(sum, cells)) == 3 and res["heatmap"]["max"] == 1

    mine = next(a for a in res["agents"] if a["user_id"] == me)
    assert (mine["sent"], mine["closed"], mine["first_responses"], mine["median_first_response"]) == (3, 1, 3, 40.0)
    channels = {c["channel_id"]: c for c in res["channels"]}
    assert personal not in channels and (channels[shared]["received"], channels[shared]["sent"]) == (3, 3)

    # nothing happened before this period, so there's nothing to compare with; filters narrow everything
    assert res["previous"] is None
    assert client.get(f"/api/analytics/inbox?start={monday}&end={tue}&channel_id={personal}")["totals"]["received"] == 0


def test_previous_period_is_compared_only_once_history_covers_it(client, owner, monday):
    shared = add_channel()
    tue = monday + timedelta(days=1)
    add_conversation(shared, at(tue, "09:00"), at(tue, "09:30"), owner["id"])
    add_conversation(shared, at(monday - timedelta(days=1), "10:00"))   # Sunday: inside the previous 2 days
    # History starts on Sunday, but the previous period (Sat-Sun) starts on Saturday.
    assert client.get(f"/api/analytics/inbox?start={monday}&end={tue}")["previous"] is None
    add_conversation(shared, at(monday - timedelta(days=2), "10:00"))   # now it reaches Saturday
    prev = client.get(f"/api/analytics/inbox?start={monday}&end={tue}")["previous"]
    assert prev["received"] == 2
    assert client.get(f"/api/analytics/jobs?start={monday}&end={tue}")["previous"] is None   # no jobs at all
    assert client.get(f"/api/analytics/team?start={monday}&end={tue}")["previous"] is None   # no shifts or punches


def test_waiting_list_counts_unanswered_open_conversations(client, owner):
    shared = add_channel()
    two_hours_ago = iso(now() - timedelta(hours=2))
    waiting = add_conversation(shared, two_hours_ago, subject="Where is my order?")
    add_conversation(shared, iso(now() - timedelta(hours=3)), iso(now() - timedelta(hours=1)), owner["id"])
    res = client.get("/api/analytics/inbox")
    assert res["totals"]["waiting"] == 1
    item = res["waiting"]["items"][0]
    assert item["id"] == waiting and item["subject"] == "Where is my order?"
    assert 119 <= item["minutes"] <= 121


def test_csv_export(client, owner):
    shared = add_channel()
    add_conversation(shared, iso(now() - timedelta(hours=2)), subject="=HYPERLINK(\"http://evil.test\")")
    resp = client.raw("get", "/api/analytics/inbox?format=csv&table=daily")
    assert resp.status_code == 200 and resp.mimetype == "text/csv"
    assert resp.headers["Content-Disposition"].startswith('attachment; filename="inbox-daily-')
    rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
    assert rows[0] == ["Date", "Received", "Sent", "Closed"] and len(rows) == 31
    assert sum(int(r[1]) for r in rows[1:]) == 1

    waiting = client.raw("get", "/api/analytics/inbox?format=csv&table=waiting").get_data(as_text=True)
    assert "'=HYPERLINK" in waiting  # a spreadsheet won't run it as a formula
    client.get("/api/analytics/inbox?format=csv&table=bogus", expect=400)
    team_csv = client.raw("get", "/api/analytics/team?format=csv").get_data(as_text=True)
    assert team_csv.startswith("Person,Shifts,Scheduled hours")


def test_reports_need_analytics_permission(client, make_user):
    _, agent = make_user("agent")
    _, staff = make_user("staff")
    _, manager = make_user("manager")
    for report in ("inbox", "team", "jobs"):
        agent.get(f"/api/analytics/{report}", expect=403)
        staff.get(f"/api/analytics/{report}", expect=403)
        manager.get(f"/api/analytics/{report}")


# -- team ------------------------------------------------------------------------------


def test_team_report_hours_overtime_cost_late_and_time_off(client, make_user, monday):
    pat, _ = make_user("staff", name="Pat Press")
    uid = pat["id"]
    tue, wed, thu, fri = (monday + timedelta(days=n) for n in range(1, 5))
    stamp = now_iso()
    with db.transaction():
        db.execute(
            "INSERT INTO staff_profiles (user_id, hourly_rate) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET hourly_rate = excluded.hourly_rate", uid, 20,
        )
        shift = db.insert("shifts", {"user_id": uid, "start_at": at(monday, "08:00"), "end_at": at(monday, "16:30"),
                                     "break_minutes": 30, "status": "published", "created_at": stamp})
        db.insert("shifts", {"user_id": uid, "start_at": at(wed, "08:00"), "end_at": at(wed, "16:00"),
                             "status": "draft", "created_at": stamp})  # drafts don't count
        # 12 minutes late, 8.5 h on the clock with a 30-minute break = 8 h worked
        db.insert("time_entries", {"user_id": uid, "shift_id": shift, "clock_in": at(monday, "08:12"),
                                   "clock_out": at(monday, "16:42"), "break_minutes": 30, "status": "approved",
                                   "created_at": stamp})
        # an overnight entry splits at local midnight: 2 h Tuesday, 2 h Wednesday
        db.insert("time_entries", {"user_id": uid, "clock_in": at(tue, "22:00"), "clock_out": at(wed, "02:00"),
                                   "status": "approved", "created_at": stamp})
        db.insert("time_off_requests", {"user_id": uid, "start_date": thu.isoformat(), "end_date": fri.isoformat(),
                                        "status": "approved", "created_at": stamp})
        db.insert("time_off_requests", {"user_id": uid, "start_date": monday.isoformat(), "end_date": monday.isoformat(),
                                        "status": "denied", "created_at": stamp})
    set_setting("staffing.overtime_weekly_hours", 8)

    res = client.get(f"/api/analytics/team?start={monday}&end={fri}")
    p = next(r for r in res["people"] if r["user_id"] == uid)
    assert (p["scheduled_minutes"], p["worked_minutes"], p["overtime_minutes"]) == (480, 720, 240)
    assert p["labor_cost"] == 280.0  # 12 h x $20 + overtime premium 4 h x $10
    assert (p["shifts"], p["late"], p["timeoff_days"], p["variance_minutes"]) == (1, 1, 2.0, 240)
    daily = {d["date"]: d for d in res["daily"]}
    assert daily[monday.isoformat()] == {"date": monday.isoformat(), "scheduled_minutes": 480, "worked_minutes": 480}
    assert daily[tue.isoformat()]["worked_minutes"] == 120 and daily[wed.isoformat()]["worked_minutes"] == 120
    assert res["late"][0]["minutes_late"] == 12 and res["late"][0]["user_id"] == uid
    assert res["totals"]["late"] == 1 and res["totals"]["missing_rates"] == 0
    assert res["overtime_rule"] == {"weekly_hours": 8.0, "daily_hours": None}

    # with a 4-hour daily limit, Monday's 8 h has 4 h over; that beats the weekly rule
    set_setting("staffing.overtime_weekly_hours", 40)
    set_setting("staffing.overtime_daily_hours", 4)
    period = analytics.Period(monday, fri, PHX)
    p = next(r for r in analytics.team_report(period)["people"] if r["user_id"] == uid)
    assert p["overtime_minutes"] == 240


def test_a_second_punch_on_the_same_shift_is_not_late(client, make_user, monday):
    pat, _ = make_user("staff")
    uid = pat["id"]
    tue = monday + timedelta(days=1)
    stamp = now_iso()
    with db.transaction():
        shift = db.insert("shifts", {"user_id": uid, "start_at": at(monday, "08:00"), "end_at": at(monday, "16:00"),
                                     "status": "published", "created_at": stamp})
        db.insert("time_entries", {"user_id": uid, "shift_id": shift, "clock_in": at(monday, "07:58"),
                                   "clock_out": at(monday, "12:00"), "status": "approved", "created_at": stamp})
        # back from lunch on another job: same shift, not a late arrival
        db.insert("time_entries", {"user_id": uid, "shift_id": shift, "clock_in": at(monday, "12:30"),
                                   "clock_out": at(monday, "16:00"), "status": "approved", "created_at": stamp})
        db.insert("shifts", {"user_id": uid, "start_at": at(tue, "08:00"), "end_at": at(tue, "16:00"),
                             "status": "published", "created_at": stamp})
        # not linked to a shift: matched to Tuesday's by time, 20 minutes late
        db.insert("time_entries", {"user_id": uid, "clock_in": at(tue, "08:20"), "clock_out": at(tue, "16:00"),
                                   "status": "approved", "created_at": stamp})
    res = client.get(f"/api/analytics/team?start={monday}&end={tue}")
    assert [(x["user_id"], x["minutes_late"]) for x in res["late"]] == [(uid, 20)]


# -- jobs ------------------------------------------------------------------------------


def test_jobs_report_throughput_on_time_stage_times_and_hours(client, monday):
    tue, wed = monday + timedelta(days=1), monday + timedelta(days=2)
    stamp = now_iso()
    with db.transaction():
        prepress = db.insert("job_stages", {"name": "Prepress", "position": 1, "created_at": stamp})
        press = db.insert("job_stages", {"name": "Press", "position": 2, "wip_limit": 3, "created_at": stamp})
        done = db.insert("job_stages", {"name": "Done", "position": 3, "is_done": 1, "created_at": stamp})
        on_time = db.insert("jobs", {"number": "T-1", "title": "Menus", "stage_id": done, "created_at": at(monday, "09:00"),
                                     "due_at": at(wed, "17:00"), "completed_at": at(tue, "15:00"), "quote_amount": 100,
                                     "estimated_minutes": 120})
        db.insert("jobs", {"number": "T-2", "title": "Cards", "stage_id": done, "created_at": at(monday, "10:00"),
                           "due_at": at(monday, "12:00"), "completed_at": at(tue, "10:00"), "quote_amount": 50})
        db.insert("jobs", {"number": "T-3", "title": "Banner", "stage_id": press, "created_at": at(tue, "11:00"),
                           "due_at": at(monday, "12:00")})
        for when, src, dst in ((at(monday, "13:00"), prepress, press), (at(tue, "15:00"), press, done)):
            db.insert("job_activity", {"job_id": on_time, "type": "stage_changed", "created_at": when,
                                       "data_json": db.jdump({"from_id": src, "to_id": dst, "from": "x", "to": "y"})})
        owner_id = db.scalar("SELECT id FROM users ORDER BY id LIMIT 1")
        db.insert("time_entries", {"user_id": owner_id, "job_id": on_time, "clock_in": at(monday, "13:00"),
                                   "clock_out": at(monday, "14:30"), "status": "approved", "created_at": stamp})

    res = client.get(f"/api/analytics/jobs?start={monday}&end={tue}")
    t = res["totals"]
    assert (t["created"], t["completed"], t["revenue"]) == (3, 2, 150.0)
    assert (t["on_time"], t["with_due"], t["on_time_pct"]) == (1, 2, 50.0)
    assert (t["open"], t["overdue"]) == (1, 1)
    assert sum(w["created"] for w in res["weekly"]) == 3 and sum(w["completed"] for w in res["weekly"]) == 2
    wip = {w["name"]: w for w in res["wip"]}
    assert "Done" not in wip and wip["Press"]["jobs"] == 1 and wip["Press"]["wip_limit"] == 3
    stages = {s["name"]: s for s in res["time_in_stage"]}
    assert stages["Prepress"]["average_minutes"] == 240 and stages["Press"]["average_minutes"] == 1560
    hours = {h["number"]: h for h in res["hours"]}
    assert hours["T-1"]["estimated_minutes"] == 120 and hours["T-1"]["actual_minutes"] == 90
    assert hours["T-1"]["variance_pct"] == -25.0
    assert res["customers"][0]["name"] == "No customer" and res["customers"][0]["jobs"] == 3


# -- demo history ------------------------------------------------------------------------


def test_demo_history_makes_reports_meaningful(app):
    from pps_tools.switchboard.seed import seed_demo

    seed_demo()
    end = now().astimezone(PHX).date()
    period = analytics.Period(end - timedelta(days=29), end, PHX)
    inbox = analytics.inbox_report(period)
    assert inbox["totals"]["received"] > 50 and inbox["first_response"]["median"] is not None
    assert sum(1 for d in inbox["daily"] if d["received"]) > 15
    team = analytics.team_report(period)
    assert team["totals"]["worked_minutes"] > 0 and team["totals"]["labor_cost"] > 0
    if db.scalar("SELECT COUNT(*) FROM job_stages"):
        assert analytics.jobs_report(period)["totals"]["completed"] > 0
