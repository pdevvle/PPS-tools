"""Demo history for Reports: about six weeks of closed conversations, worked shifts and
finished jobs, so the charts have something to show on day one.

Everything here lies in the past and is closed or done; the live demo threads, shifts
and jobs from the other modules stay as they are. Each part only runs when those
modules' demo data doesn't already cover that history, and history shifts/punches stop
the day before the earliest existing ones so nobody is double-booked.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta

from pps_tools.switchboard import db
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import search
from pps_tools.switchboard.util import iso, parse_iso, snippet, text_to_html

HISTORY_DAYS = 42

CUSTOMERS = [
    ("Lena Ortiz", "lena@desertbloomcafe.example"),
    ("Marcus Hale", "marcus@saguarorealty.example"),
    ("Ana Ruiz", "ana@saguarorealty.example"),
    ("Priya Raman", "priya@phxarts.example"),
    ("Tom Becker", "tom@copperlinebrewing.example"),
    ("Dana Price", "dana.price@valleyll.example"),
    ("Grace Kim", "grace.kim@mail.example"),
    ("Hector Alvarez", "hector@alvarezlandscaping.example"),
    ("Mei Chen", "mei@chenfamilydental.example"),
    ("Owen Brooks", "owen@brooksrealty.example"),
    ("Sofia Martinez", "sofia@cactuscandles.example"),
    ("Jamal Wright", "jamal@wrightfitness.example"),
    ("Erin Walsh", "erin@sunrisechurch.example"),
    ("Luis Navarro", "luis@navarroauto.example"),
    ("Kate Morgan", "kate.morgan@mail.example"),
    ("Ben Foster", "ben@fosterlaw.example"),
    ("Nora Patel", "nora@mesahomecare.example"),
    ("Chris Young", "chris@tempebikes.example"),
]

TOPICS = [
    ("Quote: {n} trifold brochures", "Quote request", 800),
    ("Business cards for new hires", "Order", 160),
    ("Reorder — door hangers", "Order", 420),
    ("Proof question on our postcards", "Proof", 0),
    ("Banner for the weekend event", "Rush", 260),
    ("Invoice copy please", "Billing", 0),
    ("Menu update and reprint", "Order", 520),
    ("Price check on yard signs", "Quote request", 640),
    ("Rush flyers for Saturday", "Rush", 300),
    ("Booklet printing — {n} copies", "Quote request", 1900),
    ("Can you match our brand blue?", "Proof", 0),
    ("Window decals", "Quote request", 380),
]

INBOUND = [
    "Hi! Could you send a quote for {n}? Full color, both sides. Thanks!",
    "Hello, we'd like to reorder the same as last time. Can you get them to us this week?",
    "Quick question about the proof you sent — can the logo be a little bigger?",
    "Do you have time to print these by Friday? Files attached.",
    "Can you resend last month's invoice? Our bookkeeper needs a copy.",
]
REPLIES = [
    "Happy to help! I'll put a quote together and send it over this afternoon.",
    "Yes, we can do that. I'll send a proof first thing tomorrow.",
    "Good catch — updated proof attached. Let us know if it looks right.",
    "Friday works. We'll confirm as soon as the files check out.",
    "Sent! Let me know if you need anything else.",
]
FOLLOW_UPS = ["Perfect, thank you!", "Approved — go ahead.", "Looks great, thanks so much.", "Got it, thanks!"]

PRODUCTS = [
    ("Trifold brochures", 500, 380, 240), ("Business cards", 1000, 95, 60), ("Postcards", 2500, 410, 180),
    ("Vinyl banner 3x8", 2, 190, 90), ("Saddle-stitched booklets", 300, 1650, 600), ("Door hangers", 5000, 720, 300),
    ("Yard signs", 40, 520, 240), ("Rack cards", 1000, 260, 150), ("Restaurant menus", 200, 340, 210),
    ("Letterhead", 1000, 210, 120),
]


def _local(ctx, day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=ctx.tz)


def _business_day(day: date) -> bool:
    return day.weekday() < 5


def _next_business_morning(ctx, dt: datetime) -> datetime:
    day = dt.astimezone(ctx.tz).date() + timedelta(days=1)
    while not _business_day(day):
        day += timedelta(days=1)
    return _local(ctx, day, 8, ctx.rng.randint(5, 50))


def _channel_ids(ctx) -> dict:
    chans = dict(ctx.data.get("channels") or {})
    for row in db.query("SELECT id, type FROM channels WHERE visibility = 'shared'"):
        chans.setdefault({"email": "orders", "sms": "sms", "chat": "chat", "whatsapp": "whatsapp"}.get(row["type"], row["type"]),
                         row["id"])
    return chans


# -- inbox ----------------------------------------------------------------------------


def _seed_inbox_history(ctx) -> list[dict]:
    """Closed conversations over the last six weeks. Returns customer contacts used."""
    cutoff = iso(ctx.now - timedelta(days=9))
    if db.scalar("SELECT COUNT(*) FROM conversations WHERE created_at < ?", cutoff) >= 10:
        return []
    chans = _channel_ids(ctx)
    if not chans.get("orders"):
        return []
    channel_rows = {r["id"]: r for r in db.query("SELECT * FROM channels")}
    labels = {r["name"]: r["id"] for r in db.query("SELECT id, name FROM labels WHERE visibility = 'shared'")}
    rng = ctx.rng
    responders = [(ctx.uid("frontdesk"), 50), (ctx.uid("designer"), 20), (ctx.uid("manager"), 15), (ctx.uid("owner"), 15)]
    commenters = [ctx.uid("designer"), ctx.uid("manager"), ctx.uid("frontdesk")]
    contacts = []
    for name, email in CUSTOMERS:
        c = contacts_svc.resolve("email", email, name)
        if c:
            contacts.append(c)
    today = ctx.now.astimezone(ctx.tz).date()

    def pick(weighted):
        total = sum(w for _, w in weighted)
        x = rng.uniform(0, total)
        for item, w in weighted:
            x -= w
            if x <= 0:
                return item
        return weighted[-1][0]

    for days_ago in range(HISTORY_DAYS, 0, -1):
        day = today - timedelta(days=days_ago)
        count = rng.randint(4, 9) if _business_day(day) else rng.randint(0, 2)
        if day.weekday() == 0:
            count += 2  # Monday catch-up
        for _ in range(count):
            kind = pick([("email", 62), ("sms", 20), ("chat", 12), ("whatsapp", 6)]) if _business_day(day) else "chat"
            channel_id = chans.get({"email": "orders"}.get(kind, kind)) or chans["orders"]
            channel = channel_rows[channel_id]
            kind = channel["type"]
            contact = rng.choice(contacts)
            topic, label, _value = rng.choice(TOPICS)
            n = rng.choice([250, 500, 1000, 2500])
            hour = pick([(8, 10), (9, 16), (10, 16), (11, 12), (12, 6), (13, 12), (14, 12), (15, 9), (16, 6), (17, 3), (19, 2), (21, 1)])
            arrived = _local(ctx, day, hour, rng.randint(0, 59))
            # first response: quick in business hours, next morning otherwise
            if _business_day(day) and 8 <= hour < 16:
                delay = min(600.0, math.exp(rng.gauss(math.log(32), 0.9)))
                responded = arrived + timedelta(minutes=delay)
            else:
                responded = _next_business_morning(ctx, arrived)
            responder = pick(responders)
            phone = contact.get("phone") or f"+1602555{rng.randint(1000, 9999)}"
            handle = contact["email"] if kind == "email" else phone
            thread_key = None if kind == "email" else (phone if kind != "chat" else f"visitor-{rng.randint(10**6, 10**7)}")
            subject = topic.format(n=n) if kind == "email" else None
            body = rng.choice(INBOUND).format(n=f"{n} pieces")
            stamp = iso(arrived)
            cid = db.insert("conversations", {
                "subject": subject, "channel_id": channel_id, "team_id": channel["team_id"], "contact_id": contact["id"],
                "thread_key": thread_key, "status": "open", "last_activity_at": stamp, "created_at": stamp,
            })
            messages = [("in", arrived, body, None)]
            messages.append(("out", responded, rng.choice(REPLIES), responder))
            t = responded
            for _ in range(rng.choice([0, 0, 1, 1, 2])):
                t = t + timedelta(minutes=rng.randint(40, 600))
                messages.append(("in", t, rng.choice(FOLLOW_UPS), None))
                t = t + timedelta(minutes=rng.randint(5, 180))
                messages.append(("out", t, rng.choice(REPLIES), responder))
            messages = [m for m in messages if m[1] <= ctx.now]
            last_in = last_out = None
            for direction, at, text, author in messages:
                mid = db.insert("messages", {
                    "conversation_id": cid, "channel_id": channel_id, "direction": direction, "kind": kind,
                    "from_name": contact["name"] if direction == "in" else None,
                    "from_handle": handle if direction == "in" else channel["address"],
                    "to_json": db.jdump([{"name": None, "handle": channel["address"] if direction == "in" else handle}]),
                    "subject": subject, "body_text": text, "body_html": text_to_html(text) if kind in ("email", "chat") else None,
                    "snippet": snippet(text, 200), "author_id": author, "contact_id": contact["id"] if direction == "in" else None,
                    "status": "received" if direction == "in" else "sent", "sent_at": iso(at) if direction == "out" else None,
                    "external_id": f"<history.{cid}.{at.timestamp():.0f}.{direction}@pps.demo>",
                    "date": iso(at), "created_at": iso(at),
                })
                search.index("message", mid, subject, text, parent_id=cid)
                if direction == "in":
                    last_in = at
                else:
                    last_out = at
            if rng.random() < 0.25:
                author = rng.choice(commenters)
                at = responded - timedelta(minutes=rng.randint(2, 20))
                db.insert("comments", {"conversation_id": cid, "user_id": author, "created_at": iso(max(at, arrived)),
                                       "body": "<p>I can take this one.</p>" if author == responder else "<p>Checked the file — it's print-ready.</p>"})
            last = max(at for _, at, _, _ in messages)
            closed = min(last + timedelta(hours=rng.uniform(0.3, 26)), ctx.now - timedelta(minutes=1))
            closed = max(closed, last)
            closer = responder if rng.random() < 0.8 else rng.choice(commenters)
            n_msgs = len(messages)
            db.update("conversations", cid, {
                "status": "closed", "closed_at": iso(closed), "closed_by": closer, "message_count": n_msgs,
                "comment_count": db.scalar("SELECT COUNT(*) FROM comments WHERE conversation_id = ?", cid),
                "last_message_at": iso(last), "last_inbound_at": iso(last_in) if last_in else None,
                "last_outbound_at": iso(last_out) if last_out else None, "last_activity_at": iso(last),
                "first_response_at": iso(responded) if last_out else None,
                "preview": snippet(messages[-1][2], 200),
            })
            db.insert("conversation_assignees", {"conversation_id": cid, "user_id": responder, "assigned_by": responder,
                                                 "assigned_at": iso(arrived + timedelta(minutes=1))})
            db.insert("conversation_users", {"conversation_id": cid, "user_id": responder, "following": 1, "in_inbox": 0,
                                             "starred": 0, "last_read_at": iso(closed)})
            if label in labels:
                db.insert("conversation_labels", {"conversation_id": cid, "label_id": labels[label], "added_by": responder,
                                                  "added_at": iso(arrived + timedelta(minutes=2))})
    return contacts


# -- jobs -----------------------------------------------------------------------------


def _seed_job_history(ctx, contacts: list[dict]) -> list[dict]:
    """Finished (and since archived) jobs that moved through every stage. Returns
    [{id, start, minutes}]: when production happened, for the time-clock history."""
    if db.scalar("SELECT COUNT(*) FROM jobs WHERE completed_at IS NOT NULL") >= 8:
        return []
    stages = db.query("SELECT * FROM job_stages ORDER BY position, id")
    flow = [s for s in stages if not s["is_done"]]
    done = next((s for s in stages if s["is_done"]), None)
    if not flow or not done:
        return []
    rng = ctx.rng
    if not contacts:
        contacts = db.query("SELECT * FROM contacts ORDER BY id LIMIT 20")
    today = ctx.now.astimezone(ctx.tz).date()
    windows = []
    created_by = ctx.uid("frontdesk")
    for i in range(34):
        number = f"J-{901 + i}"
        if db.one("SELECT 1 AS x FROM jobs WHERE number = ?", number):
            continue
        product, qty, quote, minutes = rng.choice(PRODUCTS)
        contact = rng.choice(contacts) if contacts else None
        day = today - timedelta(days=rng.randint(6, HISTORY_DAYS))
        while not _business_day(day):
            day -= timedelta(days=1)
        created = _local(ctx, day, rng.randint(8, 15), rng.randint(0, 59))
        t = created
        moves = []  # (from stage, to stage, when)
        current = flow[0]
        for st in flow[1:] + [done]:
            t = t + timedelta(hours=rng.uniform(1.5, 26))
            moves.append((current, st, t))
            current = st
        completed = t
        if completed >= ctx.now:
            continue
        due = created + timedelta(days=rng.choice([3, 4, 5, 7, 10]))
        if rng.random() < 0.15:
            due = completed - timedelta(hours=rng.uniform(3, 30))  # a few run late
        org_id = contact.get("organization_id") if contact else None
        jid = db.insert("jobs", {
            "number": number, "title": f"{qty:,} {product.lower()}" + (f" — {contact['name']}" if contact else ""),
            "description": None, "stage_id": done["id"], "priority": rng.choice(["normal", "normal", "normal", "high", "rush"]),
            "contact_id": contact["id"] if contact else None, "organization_id": org_id, "due_at": iso(due),
            "quantity": qty, "specs_json": db.jdump({"product": product}),
            "quote_amount": round(quote * rng.uniform(0.85, 1.25), 2), "estimated_minutes": minutes,
            "tags_json": "[]", "position": float(i), "created_by": created_by, "created_at": iso(created),
            "updated_at": iso(completed), "completed_at": iso(completed), "stage_entered_at": iso(completed),
            "archived_at": iso(min(completed + timedelta(days=2), ctx.now)),
        })
        for from_st, to_st, at in moves:
            db.insert("job_activity", {
                "job_id": jid, "user_id": created_by, "type": "stage_changed", "body": None,
                "data_json": db.jdump({"from_id": from_st["id"], "to_id": to_st["id"], "from": from_st["name"],
                                       "to": to_st["name"]}),
                "created_at": iso(at),
            })
        # production happens part-way through the flow
        work_start = moves[max(0, len(moves) // 2 - 1)][2]
        windows.append({"id": jid, "start": work_start, "minutes": minutes})
    return windows


# -- team ---------------------------------------------------------------------------

STAFF = [
    # key, weekdays, start, end, break, hourly rate
    ("press", (0, 1, 2, 3, 4), (7, 0), (15, 30), 30, 24.0),
    ("bindery", (0, 1, 2, 3, 4), (8, 0), (16, 30), 30, 19.5),
    ("driver", (0, 1, 2, 3, 4), (10, 0), (18, 0), 30, 18.0),
    ("parttime", (1, 3, 5), (9, 0), (14, 0), 0, 16.5),
    ("designer", (0, 1, 2, 3, 4), (8, 30), (17, 0), 30, 27.0),
    ("frontdesk", (0, 1, 2, 3, 4), (8, 0), (16, 30), 30, 20.0),
    ("manager", (0, 1, 2, 3, 4), (7, 30), (16, 0), 30, 32.0),
]


def _position_for(key: str, positions: list[dict]) -> int | None:
    words = {"press": ("press",), "bindery": ("bindery", "finish"), "driver": ("driver", "deliver"),
             "parttime": ("assist", "press"), "designer": ("design", "prepress"), "frontdesk": ("front", "customer", "desk"),
             "manager": ("manager", "lead", "supervisor")}[key]
    for w in words:
        for p in positions:
            if w in p["name"].lower():
                return p["id"]
    return None


def _seed_team_history(ctx, job_windows: list[dict]) -> None:
    cutoff = iso(ctx.now - timedelta(days=7))
    if db.scalar("SELECT COUNT(*) FROM time_entries WHERE clock_in < ?", cutoff) >= 20:
        return
    earliest = db.scalar("SELECT MIN(start_at) FROM (SELECT start_at FROM shifts UNION ALL SELECT clock_in FROM time_entries)")
    today = ctx.now.astimezone(ctx.tz).date()
    stop = today
    if earliest:
        stop = min(today, parse_iso(earliest).astimezone(ctx.tz).date())
    positions = db.query("SELECT * FROM positions")
    rng = ctx.rng
    stamp = iso(ctx.now)
    for key, _days, _s, _e, _brk, rate in STAFF:
        uid = ctx.uid(key)
        db.execute(
            "INSERT OR IGNORE INTO staff_profiles (user_id, employment_type, hourly_rate, default_position_id, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            uid, "part_time" if key == "parttime" else "full_time", rate, _position_for(key, positions), stamp,
        )
    busy_week = today - timedelta(days=17)
    for days_ago in range(35, 0, -1):
        day = today - timedelta(days=days_ago)
        if day >= stop:
            break
        for key, weekdays, (sh, sm), (eh, em), brk, _rate in STAFF:
            if day.weekday() not in weekdays:
                continue
            uid = ctx.uid(key)
            if rng.random() < 0.04:
                continue  # called in sick
            start = _local(ctx, day, sh, sm)
            end = _local(ctx, day, eh, em)
            sid = db.insert("shifts", {
                "user_id": uid, "position_id": _position_for(key, positions), "start_at": iso(start), "end_at": iso(end),
                "break_minutes": brk, "status": "published", "created_by": ctx.uid("manager"),
                "created_at": iso(start - timedelta(days=5)), "published_at": iso(start - timedelta(days=4)),
            })
            late = rng.random() < 0.07
            clock_in = start + timedelta(minutes=rng.randint(8, 25) if late else rng.randint(-8, 3))
            extra = 0
            if key == "press" and abs((day - busy_week).days) <= 3:
                extra = rng.randint(90, 150)  # a busy week with overtime on press
            clock_out = end + timedelta(minutes=rng.randint(-5, 12) + extra)
            jobs_today = [w for w in job_windows if w["start"].astimezone(ctx.tz).date() == day]
            if key in ("press", "bindery", "parttime") and jobs_today:
                midday = clock_in + (clock_out - clock_in) / 2
                for job, (a, b) in zip((jobs_today[0], jobs_today[-1]), ((clock_in, midday), (midday, clock_out))):
                    db.insert("time_entries", {
                        "user_id": uid, "shift_id": sid, "job_id": job["id"], "clock_in": iso(a), "clock_out": iso(b),
                        "break_minutes": brk // 2, "source": "clock", "status": "approved",
                        "approved_by": ctx.uid("manager"), "approved_at": iso(b), "created_at": iso(a),
                    })
                continue
            db.insert("time_entries", {
                "user_id": uid, "shift_id": sid, "clock_in": iso(clock_in), "clock_out": iso(clock_out),
                "break_minutes": brk, "source": "clock", "status": "approved", "approved_by": ctx.uid("manager"),
                "approved_at": iso(clock_out), "created_at": iso(clock_in),
            })
    if not db.scalar("SELECT COUNT(*) FROM time_off_requests WHERE end_date < ?", today.isoformat()):
        for key, back, length in (("bindery", 24, 2), ("designer", 11, 1)):
            start = today - timedelta(days=back)
            db.insert("time_off_requests", {
                "user_id": ctx.uid(key), "kind": "vacation", "start_date": start.isoformat(),
                "end_date": (start + timedelta(days=length - 1)).isoformat(), "status": "approved",
                "reviewed_by": ctx.uid("manager"), "reviewed_at": iso(_local(ctx, start - timedelta(days=9), 10)),
                "created_at": iso(_local(ctx, start - timedelta(days=10), 9)),
            })


def seed_history(ctx) -> None:
    contacts = _seed_inbox_history(ctx)
    windows = _seed_job_history(ctx, contacts)
    _seed_team_history(ctx, windows)
