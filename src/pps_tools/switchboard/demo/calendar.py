"""Demo calendar: the shop calendar's regular rhythm plus this week's one-offs."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from pps_tools.switchboard import db
from pps_tools.switchboard.util import iso, now_iso


def _days_until(ctx, weekday: int) -> int:
    """Days from today to the next ``weekday`` (0 = Monday); 0 when it's today."""
    today = ctx.now.astimezone(ctx.tz).date()
    return (weekday - today.weekday()) % 7


def _last_friday_of_last_month(today) -> int:
    """Day offset from today to the last Friday of the previous month."""
    first = today.replace(day=1)
    day = first - timedelta(days=1)
    while day.weekday() != 4:
        day -= timedelta(days=1)
    return (day - today).days


def seed_calendar(ctx) -> None:
    u = ctx.uid
    shop = db.one("SELECT id FROM calendars WHERE kind = 'shared' AND name = 'Shop calendar'")
    shop_id = shop["id"] if shop else db.insert("calendars", {"name": "Shop calendar", "color": "#0c8599", "kind": "shared",
                                                             "created_by": u("owner"), "created_at": now_iso()})
    deliveries = db.insert("calendars", {"name": "Deliveries", "color": "#f08c00", "kind": "shared",
                                         "created_by": u("manager"), "created_at": now_iso()})
    morgan = db.insert("calendars", {"name": "Morgan Reyes", "color": "#3b5bdb", "kind": "personal",
                                     "owner_user_id": u("owner"), "created_by": u("owner"), "created_at": now_iso()})
    today = ctx.now.astimezone(ctx.tz).date()

    def local(day_offset, hh, mm=0):
        return iso(datetime.combine(today + timedelta(days=day_offset), time(hh, mm), tzinfo=ctx.tz))

    def all_day(day_offset, days=1):
        start = datetime.combine(today + timedelta(days=day_offset), time(0, 0), tzinfo=ctx.tz)
        return iso(start), iso(start + timedelta(days=days))

    def attendees(*keys):
        return db.jdump([{"user_id": u(k)} for k in keys])

    monday = -today.weekday()  # this week's Monday (may be in the past: the series started then)
    rows = [
        dict(calendar_id=shop_id, title="Weekly production meeting", location="Press room",
             start_at=local(monday - 21, 8), end_at=local(monday - 21, 8, 30), rrule="FREQ=WEEKLY;BYDAY=MO",
             attendees_json=attendees("manager", "press", "bindery", "designer", "parttime", "owner"), reminder_minutes=10,
             description="What's on each press this week, maintenance, staffing gaps."),
        dict(calendar_id=deliveries, title="Delivery run — Scottsdale & Tempe", location="Van 1",
             start_at=local(monday - 14 + 1, 14), end_at=local(monday - 14 + 1, 16), rrule="FREQ=WEEKLY;BYDAY=TU,TH",
             attendees_json=attendees("driver"), reminder_minutes=30),
        dict(calendar_id=deliveries, title="Saguaro Realty — card drop-off", location="4400 N Scottsdale Rd",
             start_at=local(1, 15), end_at=local(1, 15, 30), attendees_json=attendees("driver")),
        dict(calendar_id=shop_id, title="Mohawk Paper rep visit (Steve Alvarez)", location="Front office",
             start_at=local(_days_until(ctx, 2) or 7, 10), end_at=local(_days_until(ctx, 2) or 7, 11),
             attendees_json=attendees("owner", "manager"), reminder_minutes=15,
             description="Q1 pricing on coated stocks; ask about cotton stock lead times."),
        dict(calendar_id=shop_id, title="Press 2 maintenance — roller service", location="Press 2",
             start_at=local(_days_until(ctx, 3), 13), end_at=local(_days_until(ctx, 3), 16),
             attendees_json=attendees("manager", "press"), reminder_minutes=60),
        dict(calendar_id=shop_id, title="Team lunch 🌮", location="Taqueria Los Altos",
             start_at=local(_days_until(ctx, 4), 12), end_at=local(_days_until(ctx, 4), 13),
             attendees_json=attendees("owner", "manager", "frontdesk", "designer", "press", "bindery", "driver", "parttime")),
        dict(calendar_id=shop_id, title="Fall Gala programs — files due", all_day=1,
             **dict(zip(("start_at", "end_at"), all_day(2))), attendees_json=attendees("manager", "designer")),
        dict(calendar_id=shop_id, title="Inventory count", all_day=1, rrule="FREQ=MONTHLY;BYDAY=-1FR",
             **dict(zip(("start_at", "end_at"), all_day(_last_friday_of_last_month(today)))),
             attendees_json=attendees("bindery", "manager")),
        dict(calendar_id=morgan, title="Chamber of Commerce mixer", location="Downtown Phoenix Chamber",
             start_at=local(_days_until(ctx, 3) or 7, 17, 30), end_at=local(_days_until(ctx, 3) or 7, 19), reminder_minutes=60),
        dict(calendar_id=morgan, title="Payroll review", start_at=local(1, 16), end_at=local(1, 16, 30),
             attendees_json=attendees("manager")),
    ]
    stamp = ctx.ago(days=3)
    for row in rows:
        row.setdefault("attendees_json", "[]")
        row.setdefault("all_day", 0)
        creator = u("manager") if row["calendar_id"] == deliveries else u("owner")
        db.insert("calendar_events", {**row, "created_by": creator, "created_at": stamp, "updated_at": stamp})
