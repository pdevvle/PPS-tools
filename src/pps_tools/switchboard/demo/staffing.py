"""Demo staffing for Priority Print Service: who does what, when they can work, three
weeks of shifts (last week and this week published, next week still in draft with a
few conflicts to sort out), time off, a swap request and time-clock history."""

from __future__ import annotations

from datetime import date, timedelta

from pps_tools.switchboard import db
from pps_tools.switchboard.services import staffing as st
from pps_tools.switchboard.util import iso, now, now_iso, parse_iso

SKILLS = ["Offset press", "Digital press", "Wide format", "Guillotine cutter", "Folder", "Saddle stitch",
          "Prepress", "Forklift", "Delivery"]

# key: employee #, type, rate, hired (days ago), target h, max h, positions, skills {name: level}, location
PROFILES = {
    "owner": ("PPS-001", "full_time", 45.0, 3650, None, None, ["Front Desk", "Designer"], {"Prepress": 2}, "main"),
    "manager": ("PPS-002", "full_time", 32.0, 2100, 40, 45, ["Press Operator", "Bindery"],
                {"Offset press": 3, "Digital press": 3, "Prepress": 2, "Forklift": 2}, "main"),
    "frontdesk": ("PPS-007", "full_time", 21.0, 420, 40, 40, ["Front Desk"], {"Prepress": 1}, "main"),
    "designer": ("PPS-005", "full_time", 26.0, 980, 40, 40, ["Designer"],
                 {"Prepress": 3, "Wide format": 2, "Digital press": 1}, "main"),
    "press": ("PPS-004", "full_time", 24.0, 1500, 40, 48, ["Press Operator"],
              {"Offset press": 3, "Digital press": 2, "Guillotine cutter": 2, "Forklift": 1}, "main"),
    "bindery": ("PPS-006", "full_time", 20.0, 760, 38, 40, ["Bindery"],
                {"Folder": 3, "Saddle stitch": 3, "Guillotine cutter": 3}, "main"),
    "driver": ("PPS-008", "full_time", 19.0, 300, 40, 40, ["Driver"], {"Delivery": 3, "Forklift": 2}, "warehouse"),
    "parttime": ("PPS-011", "part_time", 18.0, 120, 20, 28, ["Press Operator", "Bindery"],
                 {"Digital press": 2, "Folder": 1, "Saddle stitch": 1}, "main"),
}

EMERGENCY = {
    "manager": "Lee Nguyen (spouse) · (602) 555-0181",
    "press": "Min Kim (mother) · (480) 555-0122",
    "bindery": "Chris Brooks (partner) · (623) 555-0175",
    "driver": "Dana Johnson (sister) · (602) 555-0109",
    "parttime": "Rosa Ortiz (mother) · (602) 555-0156",
}

# key, position, location, weekdays (Mon=0), start, end, break minutes
PATTERN = [
    ("manager", "Press Operator", "main", [0, 1, 2, 3, 4], "07:00", "15:30", 30),
    ("frontdesk", "Front Desk", "main", [0, 1, 2, 3, 4], "08:00", "17:00", 60),
    ("designer", "Designer", "main", [0, 1, 2, 3, 4], "08:30", "17:00", 30),
    ("press", "Press Operator", "main", [0, 1, 2, 3, 4], "06:30", "15:00", 30),
    ("bindery", "Bindery", "main", [0, 1, 2, 3], "08:00", "16:30", 30),
    ("bindery", "Bindery", "main", [4], "08:00", "14:00", 0),
    ("driver", "Driver", "warehouse", [0, 1, 2, 3, 4], "09:00", "17:30", 30),
    ("parttime", "Press Operator", "main", [1, 3], "16:00", "21:00", 0),
    ("parttime", "Bindery", "main", [5], "09:00", "15:00", 30),
]


def _shift(ctx, key, position, location, day: date, start, end, brk, status, stamp, notes=None):
    s_at, e_at = st.instants_for(day, start, end)
    return db.insert("shifts", {
        "user_id": ctx.uid(key) if key else None, "position_id": ctx.data["positions"][position],
        "location_id": ctx.data["locations"][location], "start_at": s_at, "end_at": e_at, "break_minutes": brk,
        "notes": notes, "status": status, "created_by": ctx.uid("manager"), "created_at": stamp, "updated_at": stamp,
        "published_at": stamp if status == "published" else None,
    })


def _week(ctx, week: date, status: str, stamp: str) -> list[int]:
    ids = []
    for day in (week + timedelta(days=i) for i in range(7)):
        for key, position, location, weekdays, start, end, brk in PATTERN:
            if day.weekday() in weekdays:
                ids.append(_shift(ctx, key, position, location, day, start, end, brk, status, stamp))
    return ids


def _entry(ctx, shift: dict, rng, extra_out_minutes=0, source="clock", flag=None, approved_by=None):
    start, end = parse_iso(shift["start_at"]), parse_iso(shift["end_at"])
    clock_in = start + timedelta(minutes=rng.randint(-7, 4))
    clock_out = end + timedelta(minutes=rng.randint(-3, 9) + extra_out_minutes)
    breaks = []
    if shift["break_minutes"]:
        mid = start + (end - start) / 2
        b_start = mid + timedelta(minutes=rng.randint(-20, 20))
        b_end = b_start + timedelta(minutes=shift["break_minutes"] + rng.randint(-2, 3))
        breaks.append({"start": iso(b_start), "end": iso(b_end)})
    total = st.break_minutes({"breaks_json": db.jdump(breaks), "break_minutes": 0})
    stamp = iso(clock_out)
    return db.insert("time_entries", {
        "user_id": shift["user_id"], "shift_id": shift["id"], "clock_in": iso(clock_in), "clock_out": iso(clock_out),
        "breaks_json": db.jdump(breaks), "break_minutes": int(round(total)), "source": source, "flag": flag,
        "status": "approved" if approved_by else "open", "approved_by": approved_by,
        "approved_at": stamp if approved_by else None, "created_by": shift["user_id"], "created_at": stamp,
        "updated_at": stamp,
    })


def seed_staffing(ctx) -> None:
    rng = ctx.rng
    stamp = now_iso()
    u = ctx.uid
    positions = {r["name"]: r["id"] for r in db.query("SELECT id, name FROM positions")}
    main = db.one("SELECT id FROM locations ORDER BY id LIMIT 1")["id"]
    db.update("locations", main, {"name": "Main shop", "address": "1410 E Washington St, Phoenix, AZ"})
    warehouse = db.insert("locations", {"name": "Warehouse — 19th Ave", "address": "2140 N 19th Ave, Phoenix, AZ",
                                        "color": "#f08c00", "created_at": stamp})
    ctx.data["positions"] = positions
    ctx.data["locations"] = {"main": main, "warehouse": warehouse}
    # Another module's seed may already have created some of these skills.
    for name in SKILLS:
        db.execute("INSERT OR IGNORE INTO skills (name, created_at) VALUES (?, ?)", name, stamp)
    ctx.data["skills"] = {r["name"].lower(): r["id"] for r in db.query("SELECT id, name FROM skills")}

    today = st.today()
    for key, (number, kind, rate, hired, target, maximum, pos_names, skills, loc) in PROFILES.items():
        uid = u(key)
        db.insert("staff_profiles", {
            "user_id": uid, "employee_number": number, "employment_type": kind, "hourly_rate": rate,
            "hire_date": (today - timedelta(days=hired)).isoformat(), "target_hours_week": target,
            "max_hours_week": maximum, "default_position_id": positions[pos_names[0]],
            "default_location_id": ctx.data["locations"][loc], "pto_hours_per_year": 80 if kind == "full_time" else 24,
            "emergency_contact": EMERGENCY.get(key), "is_schedulable": 0 if key == "owner" else 1, "updated_at": stamp,
        })
        for name in pos_names:
            db.insert("staff_positions", {"user_id": uid, "position_id": positions[name]})
        for name, level in skills.items():
            db.insert("staff_skills", {"user_id": uid, "skill_id": ctx.data["skills"][name.lower()], "level": level})

    # Jamie: weekday evenings + Saturdays. Taylor: not after 2pm on Fridays.
    for wd in range(5):
        db.insert("availability", {"user_id": u("parttime"), "weekday": wd, "start_time": "16:00", "end_time": "22:00",
                                   "kind": "available", "note": "Classes until 3"})
    db.insert("availability", {"user_id": u("parttime"), "weekday": 5, "start_time": "08:00", "end_time": "18:00",
                               "kind": "preferred"})
    db.insert("availability", {"user_id": u("bindery"), "weekday": 4, "start_time": "14:00", "end_time": "24:00",
                               "kind": "unavailable", "note": "Picks up kids"})

    this_week = st.week_start(today)
    last_week, next_week = this_week - timedelta(days=7), this_week + timedelta(days=7)
    _week(ctx, last_week, "published", iso(now() - timedelta(days=12)))
    _week(ctx, this_week, "published", iso(now() - timedelta(days=5)))
    _week(ctx, next_week, "draft", stamp)

    def day_of(week: date, weekday: int) -> date:
        return next(week + timedelta(days=i) for i in range(7) if (week + timedelta(days=i)).weekday() == weekday)

    # Open Saturday shifts, and next week's drafts that need a manager's attention.
    _shift(ctx, None, "Bindery", "main", day_of(this_week, 5), "08:00", "12:00", 0, "published",
           iso(now() - timedelta(days=5)), notes="Saturday finishing for the Arts Council programs")
    _shift(ctx, None, "Press Operator", "main", day_of(next_week, 5), "08:00", "12:00", 0, "draft", stamp)
    _shift(ctx, "press", "Press Operator", "main", day_of(next_week, 5), "08:00", "12:00", 0, "draft", stamp,
           notes="Fall Gala programs — second run")
    friday = day_of(next_week, 4)
    late = db.one("SELECT id FROM shifts WHERE user_id = ? AND start_at >= ? AND start_at < ?",
                  u("bindery"), st.day_start(friday), st.day_start(friday + timedelta(days=1)))
    s_at, e_at = st.instants_for(friday, "08:00", "17:00")
    db.update("shifts", late["id"], {"start_at": s_at, "end_at": e_at, "break_minutes": 30})
    _shift(ctx, "parttime", "Press Operator", "main", day_of(next_week, 2), "09:00", "13:00", 0, "draft", stamp)

    # Time off: Riley approved next Wed–Thu, Taylor pending in a couple of weeks, Jordan's past half day.
    riley_off = (day_of(next_week, 2), day_of(next_week, 3))
    db.insert("time_off_requests", {
        "user_id": u("driver"), "kind": "vacation", "start_date": riley_off[0].isoformat(),
        "end_date": riley_off[1].isoformat(), "hours": 16, "reason": "Family trip to Flagstaff", "status": "approved",
        "reviewed_by": u("manager"), "reviewed_at": iso(now() - timedelta(days=3)), "review_note": "Enjoy!",
        "created_at": iso(now() - timedelta(days=9)),
    })
    db.insert("time_off_requests", {
        "user_id": u("bindery"), "kind": "vacation", "start_date": (today + timedelta(days=16)).isoformat(),
        "end_date": (today + timedelta(days=18)).isoformat(), "hours": 24, "reason": "Sister's wedding in San Diego",
        "status": "pending", "created_at": iso(now() - timedelta(hours=20)),
    })
    db.insert("time_off_requests", {
        "user_id": u("designer"), "kind": "personal", "start_date": day_of(last_week, 4).isoformat(),
        "end_date": day_of(last_week, 4).isoformat(), "start_time": "13:00", "end_time": "17:00", "hours": 4,
        "reason": "Moving apartments", "status": "approved", "reviewed_by": u("manager"),
        "reviewed_at": iso(now() - timedelta(days=13)), "created_at": iso(now() - timedelta(days=15)),
    })
    jordan_fri = db.one("SELECT id FROM shifts WHERE user_id = ? AND start_at >= ? AND start_at < ?", u("designer"),
                        st.day_start(day_of(last_week, 4)), st.day_start(day_of(last_week, 4) + timedelta(days=1)))
    if jordan_fri:
        s_at, e_at = st.instants_for(day_of(last_week, 4), "08:30", "13:00")
        db.update("shifts", jordan_fri["id"], {"start_at": s_at, "end_at": e_at, "break_minutes": 0})

    # Time clock history: everything that has ended; Alex worked late all of last week.
    current = now()
    worked = db.query("SELECT * FROM shifts WHERE user_id IS NOT NULL AND status = 'published' AND end_at <= ? "
                      "AND start_at >= ? ORDER BY start_at", iso(current), st.day_start(last_week))
    riley_thursday = day_of(last_week, 3)
    for s in worked:
        in_last_week = st.local_date(s["start_at"]) < this_week
        extra = 60 if s["user_id"] == u("press") and in_last_week else 0
        flag = "auto_clock_out" if s["user_id"] == u("driver") and st.local_date(s["start_at"]) == riley_thursday else None
        approver = u("manager") if in_last_week and s["user_id"] not in (u("press"), u("driver")) else None
        source = "kiosk" if s["user_id"] in (u("press"), u("bindery"), u("parttime")) else "clock"
        _entry(ctx, s, rng, extra_out_minutes=extra, source=source, flag=flag, approved_by=approver)
    in_progress = db.query("SELECT * FROM shifts WHERE user_id IS NOT NULL AND status = 'published' AND start_at <= ? "
                           "AND end_at > ? ORDER BY start_at", iso(current), iso(current))
    for s in in_progress:
        clock_in = parse_iso(s["start_at"]) + timedelta(minutes=rng.randint(-6, 3))
        db.insert("time_entries", {
            "user_id": s["user_id"], "shift_id": s["id"], "clock_in": iso(min(clock_in, current)), "source": "kiosk",
            "created_by": s["user_id"], "created_at": iso(clock_in), "updated_at": iso(clock_in),
        })
    if not in_progress:
        clock_in = current - timedelta(minutes=95)
        db.insert("time_entries", {
            "user_id": u("manager"), "clock_in": iso(clock_in), "source": "clock", "notes": "Prepping Press 2 for service",
            "created_by": u("manager"), "created_at": iso(clock_in), "updated_at": iso(clock_in),
        })

    # Alex asks Jamie to cover his next shift (swap with Jamie's next evening shift if there is one).
    alex_next = db.one("SELECT * FROM shifts WHERE user_id = ? AND status = 'published' AND start_at > ? "
                       "ORDER BY start_at LIMIT 1", u("press"), iso(current + timedelta(hours=2)))
    if not alex_next:
        alex_next = db.one("SELECT * FROM shifts WHERE user_id = ? AND start_at > ? ORDER BY start_at LIMIT 1",
                           u("press"), iso(current + timedelta(hours=2)))
        db.update("shifts", alex_next["id"], {"status": "published", "published_at": stamp})
    jamie_next = db.one("SELECT * FROM shifts WHERE user_id = ? AND status = 'published' AND start_at > ? "
                        "AND position_id = ? ORDER BY start_at LIMIT 1", u("parttime"), iso(current), positions["Press Operator"])
    db.insert("shift_requests", {
        "kind": "swap", "shift_id": alex_next["id"], "requester_id": u("press"), "target_user_id": u("parttime"),
        "target_shift_id": jamie_next["id"] if jamie_next else None, "status": "pending",
        "note": "Doctor's appointment that morning — could we trade?", "created_at": iso(current - timedelta(hours=3)),
    })
    ctx.data["staffing_weeks"] = {"last": last_week.isoformat(), "this": this_week.isoformat(),
                                  "next": next_week.isoformat()}
