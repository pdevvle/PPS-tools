"""Demo jobs: a print shop's week — quotes, proofs out for approval, work on press,
finishing, pickups and deliveries — linked to the demo inbox conversations."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from pps_tools.switchboard import db
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import files
from pps_tools.switchboard.services import jobs as jobs_svc
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.util import iso, now_iso, token

PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def _workdays(ctx, n: int):
    """The n-th working day counting from today (0 = today or the next weekday);
    negative n counts back from the last working day before today."""
    day = ctx.now.astimezone(ctx.tz).date()
    if n >= 0:
        seen = -1
        while True:
            if day.weekday() < 5:
                seen += 1
                if seen == n:
                    return day
            day += timedelta(days=1)
    seen = 0
    while True:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            seen -= 1
            if seen == n:
                return day


def _at(ctx, n: int, hour: int, minute: int = 0) -> str:
    return iso(datetime.combine(_workdays(ctx, n), time(hour, minute), tzinfo=ctx.tz))


def _slot(ctx, uid: int, n: int, hour: int, minute: int, minutes: int) -> tuple[str, str]:
    """Preferred time on the n-th working day, nudged inside the person's published
    shift that day when staffing has one (so the demo starts without stray conflicts)."""
    start = datetime.combine(_workdays(ctx, n), time(hour, minute), tzinfo=ctx.tz)
    end = start + timedelta(minutes=minutes)
    day0 = datetime.combine(start.date(), time(0, 0), tzinfo=ctx.tz)
    shifts = db.query(
        "SELECT start_at, end_at FROM shifts WHERE user_id = ? AND status = 'published' AND start_at < ? AND end_at > ? "
        "ORDER BY start_at", uid, iso(day0 + timedelta(days=1)), iso(day0),
    )
    spans = [(datetime.fromisoformat(r["start_at"].replace("Z", "+00:00")), datetime.fromisoformat(r["end_at"].replace("Z", "+00:00")))
             for r in shifts]
    if spans and not any(a <= start and end <= b for a, b in spans):
        a, b = spans[0]
        start = min(max(start, a), b - timedelta(minutes=minutes))
        end = start + timedelta(minutes=minutes)
    return iso(start), iso(end)


def _saturday(ctx, hour: int) -> str:
    day = ctx.now.astimezone(ctx.tz).date() + timedelta(days=2)
    while day.weekday() != 5:
        day += timedelta(days=1)
    return iso(datetime.combine(day, time(hour, 0), tzinfo=ctx.tz))


def _contact(email=None, phone=None, name=None, org=None):
    c = contacts_svc.resolve("email", email, name) if email else contacts_svc.resolve("phone", phone, name)
    if org and c and not c["organization_id"]:
        db.update("contacts", c["id"], {"organization_id": org})
        c["organization_id"] = org
    return c


def _org(name, domain=None, phone=None):
    row = db.one("SELECT id FROM organizations WHERE name = ?", name)
    if row:
        return row["id"]
    return db.insert("organizations", {"name": name, "domain": domain, "phone": phone, "created_at": now_iso(),
                                       "updated_at": now_iso()})


def seed_jobs(ctx) -> None:
    from pps_tools.switchboard.api.jobs import link_template_skills

    u = ctx.uid
    link_template_skills()  # staffing's demo has created its skills by now
    stages = {s["name"]: s["id"] for s in jobs_svc.stages()}
    resources = {r["name"]: r["id"] for r in jobs_svc.resources()}
    templates = {t["name"]: t["id"] for t in jobs_svc.templates()}
    skills = {s["name"]: s["id"] for s in jobs_svc.skills()}
    convs = ctx.data.get("conversations", {})
    ctx.data["stages"], ctx.data["resources"] = stages, resources

    # Who can do what, for the auto-scheduler (shared with staffing; ignore duplicates).
    for key, names in {
        "designer": [("Prepress", 3)], "press": [("Digital press", 3), ("Wide format", 2)],
        "parttime": [("Digital press", 1), ("Finishing", 1)],
        "bindery": [("Guillotine cutter", 3), ("Folder", 3), ("Saddle stitch", 3), ("Finishing", 3)],
        "driver": [("Delivery", 3)], "manager": [("Digital press", 2), ("Finishing", 2)],
    }.items():
        for name, level in names:
            if name in skills:
                db.execute("INSERT OR IGNORE INTO staff_skills (user_id, skill_id, level) VALUES (?, ?, ?)",
                           u(key), skills[name], level)

    desert = _org("Desert Bloom Café")
    saguaro = _org("Saguaro Realty Group")
    arts = _org("Phoenix Arts Council")
    copper = _org("Copperline Brewing")
    league = _org("Valley Little League", None, "(602) 555-0164")
    dental = _org("Sonoran Dental Studio", "sonorandental.example", "(480) 555-0190")
    foodbank = _org("Mesa Food Bank", "mesafoodbank.example", "(480) 555-0102")
    lena = _contact("lena@desertbloomcafe.example", name="Lena Ortiz", org=desert)
    marcus = _contact("marcus@saguarorealty.example", name="Marcus Hale", org=saguaro)
    priya = _contact("priya@phxarts.example", name="Priya Raman", org=arts)
    tom = _contact("tom@copperlinebrewing.example", name="Tom Becker", org=copper)
    grace = _contact("grace.kim@mail.example", name="Grace Kim")
    dana = _contact(phone="+16025550164", name="Dana Price", org=league)
    maya = _contact("maya@sonorandental.example", name="Dr. Maya Chen", org=dental)
    luis = _contact("luis@mesafoodbank.example", name="Luis Romero", org=foodbank)

    sam = users_svc.get(u("frontdesk"))
    created = {}

    def make(key, title, stage, *, contact=None, template=None, conversation=None, due=None, qty=None, quote=None,
             priority="normal", people=(), days_ago=3, description=None, specs=None, po=None, address=None, tags=()):
        data = {"title": title, "stage_id": stages[stage], "priority": priority, "due_at": due, "quantity": qty,
                "quote_amount": quote, "description": description, "po_number": po, "address": address,
                "tags": list(tags)}
        if contact:
            data["contact_id"] = contact["id"]
        if template:
            data["template_id"] = templates[template]
        if specs:
            data["specs"] = specs
        if conversation and convs.get(conversation):
            data["conversation_id"] = convs[conversation]
        job = jobs_svc.create(sam, data)
        stamp = ctx.ago(days=days_ago, hours=ctx.rng.randint(0, 6))
        entered = ctx.ago(days=days_ago - 1) if days_ago > 1 else stamp
        db.update("jobs", job["id"], {"created_at": stamp, "updated_at": stamp, "stage_entered_at": entered})
        db.execute("UPDATE job_activity SET created_at = ? WHERE job_id = ?", stamp, job["id"])
        for p in people:
            db.execute("INSERT OR IGNORE INTO job_assignees (job_id, user_id) VALUES (?, ?)", job["id"], u(p))
        created[key] = job["id"]
        jobs_svc.reindex(job["id"])
        return job["id"]

    def at(person, n, hour, minute, minutes):
        return _slot(ctx, u(person), n, hour, minute, minutes)

    def plan(job_id, steps):
        """steps: {sequence: (start, end, person key, status)}; status done/in_progress."""
        ops = {o["sequence"]: o for o in db.query("SELECT * FROM job_operations WHERE job_id = ?", job_id)}
        for seq, (start, end, person, status) in steps.items():
            op = ops[seq]
            values = {"start_at": start, "end_at": end, "user_id": u(person) if person else op["user_id"]}
            if start and end:
                values["duration_minutes"] = max(5, int((datetime.fromisoformat(end.replace("Z", "+00:00"))
                                                         - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds() // 60))
            if status in ("done", "in_progress"):
                values.update({"status": status, "started_at": start, "started_by": values["user_id"]})
            if status == "done":
                values.update({"completed_at": end, "completed_by": values["user_id"]})
            db.update("job_operations", op["id"], values)

    def history(job_id, names, start, step_hours=20):
        # Keep the timeline in order: the job exists before its first move.
        created_at = db.one("SELECT created_at FROM jobs WHERE id = ?", job_id)["created_at"]
        if created_at > iso(start):
            earlier = iso(start - timedelta(minutes=40))
            db.execute("UPDATE job_activity SET created_at = ? WHERE job_id = ? AND created_at = ?", earlier, job_id, created_at)
            db.update("jobs", job_id, {"created_at": earlier})
        t = start
        prev = None
        for name in names:
            if prev:
                db.insert("job_activity", {"job_id": job_id, "user_id": u("manager"), "type": "stage_changed",
                                           "data_json": db.jdump({"from": prev, "to": name, "from_id": stages[prev],
                                                                  "to_id": stages[name]}),
                                           "created_at": iso(t)})
                db.update("jobs", job_id, {"stage_entered_at": iso(t)})
                t += timedelta(hours=step_hours)
            prev = name

    def check(job_id, done_titles):
        for item in db.query("SELECT * FROM job_checklist WHERE job_id = ?", job_id):
            if item["title"] in done_titles:
                db.update("job_checklist", item["id"], {"is_done": 1, "done_by": u("frontdesk"), "done_at": ctx.ago(days=1)})

    def comment(job_id, who, html, hours_ago, mentions=()):
        db.insert("job_activity", {"job_id": job_id, "user_id": u(who), "type": "comment", "body": html,
                                   "data_json": db.jdump({"mentions": [u(m) for m in mentions]}),
                                   "created_at": ctx.ago(hours=hours_ago)})

    def mention(key, name):
        return f'<span data-mention="{u(key)}">@{name}</span>'

    # 1. Business cards, proof out for approval.
    cards = make("cards", "Business cards — 3 new agents", "Proofing", contact=marcus, template="Business cards",
                 conversation="cards", due=_at(ctx, 2, 17), qty=1500, quote=187.50, people=("designer", "frontdesk"),
                 days_ago=1, specs={"finished_size": "3.5 × 2 in", "paper_stock": "16pt silk, spot UV logo"},
                 description="Same layout as the 2025 cards. Ana Ruiz, Ben Cho (Realtors), Kayla Moss (Office Manager). 500 each.")
    plan(cards, {1: (*at("designer", -1, 10, 0, 45), "designer", "done"),
                 2: (*at("press", 1, 13, 0, 30), "press", None),
                 3: (*at("bindery", 1, 13, 40, 20), "bindery", None),
                 4: (*at("bindery", 1, 14, 0, 10), "bindery", None)})
    proof = files.save_bytes(PDF, "saguaro-cards-proof-v1.pdf", "application/pdf", u("designer"), owner_type="job", owner_id=cards)
    db.insert("job_proofs", {"attachment_id": proof["id"], "job_id": cards, "created_at": ctx.ago(hours=20)})
    db.update("jobs", cards, {"public_token": token(18), "proof_status": "pending"})
    check(cards, {"Files received", "Stock pulled"})
    comment(cards, "designer", f"<p>Proof is out to Marcus. {mention('frontdesk', 'Sam Patel')} can you nudge him tomorrow morning if we haven't heard back?</p>",
            19, mentions=("frontdesk",))
    history(cards, ["Quote", "Approved", "Prepress", "Proofing"], ctx.now - timedelta(days=1, hours=4), step_hours=2)

    # 2. Menus: quote stage, file needs rebuilding.
    menus = make("menus", "Fall menus — 200 trifold", "Quote", contact=lena, template="Menus", conversation="menus",
                 due=_at(ctx, 8, 12), qty=200, quote=486.00, people=("frontdesk", "designer"), days_ago=0,
                 specs={"finished_size": "11 × 17 in, trifold to letter", "paper_stock": "100lb gloss text", "finishing": "Trifold, no lamination"})
    comment(menus, "designer", "<p>Last year's file only has 1/16\" bleed. I'll rebuild it — budget 45 min of prepress.</p>", 2)

    # 3. Rush banners for opening day.
    banners = make("banners", "Opening day banners — 15 × 3×6 ft", "Approved", contact=dana, template="Vinyl banner",
                   conversation="banners", due=_saturday(ctx, 8), qty=15, quote=1125.00, priority="rush",
                   people=("owner", "press"), days_ago=0, address="Desert Sky Park, field 3", tags=("Rush", "Delivery"),
                   description="Sponsor logos coming by email tonight. Two rows of grommets for the outfield fence.")
    db.update("job_operations", db.one("SELECT id FROM job_operations WHERE job_id = ? AND sequence = 2", banners)["id"],
              {"duration_minutes": 300})
    jobs_svc.add_operation(sam, jobs_svc.get(banners), {"name": "Deliver to the ballpark", "resource_id": resources["Delivery Van"],
                                                        "skill_id": skills.get("Delivery"), "duration_minutes": 45})
    plan(banners, {1: (*at("designer", 0, 13, 0, 30), "designer", None),
                   2: (*at("press", 1, 7, 30, 300), "press", None),
                   3: (*at("bindery", 1, 14, 15, 120), "bindery", None),
                   5: (*at("driver", 2, 9, 30, 45), "driver", None)})
    check(banners, {"Proof approved"})

    # 4. Gala programs: files arrive later this week.
    programs = make("programs", "Fall Gala programs — 500 booklets", "Prepress", contact=priya, template="Saddle-stitched booklet",
                    conversation="programs", due=_at(ctx, 4, 12), qty=500, quote=1640.00, people=("manager", "designer"),
                    days_ago=2, po="PAC-2026-118", specs={"finished_size": "5.5 × 8.5 in, 16 pp + cover"})
    plan(programs, {1: (*at("designer", 2, 9, 0, 90), "designer", None),
                    2: (*at("press", 3, 7, 0, 120), "press", None),
                    3: (*at("bindery", 3, 10, 0, 90), "bindery", None),
                    4: (*at("bindery", 3, 13, 0, 30), "bindery", None)})
    comment(programs, "manager", f"<p>Press 1 is held Friday morning. {mention('press', 'Alex Kim')} please stage the 100lb cover stock Thursday.</p>",
            30, mentions=("press",))

    # 5. Can labels inquiry.
    make("labels", "Seasonal IPA can labels — 3,000", "Quote", contact=tom, due=_at(ctx, 15, 17), qty=3000,
         people=("frontdesk",), days_ago=0, specs={"product": "Can labels", "finished_size": "Die-cut to brewery dieline"},
         description="Need the brewery's dieline. Roll labels — likely outsource to our label partner; quote both options.")

    # 6. Wedding invitations, delivered.
    wedding = make("wedding", "Wedding invitations & RSVP cards", "Delivered", contact=grace, qty=120, quote=389.00,
                   people=("designer",), days_ago=16, specs={"product": "Invitations", "paper_stock": "130lb cotton cover",
                                                              "finished_size": "5 × 7 in", "ink": "4/0", "finishing": "Envelopes, belly bands"})
    for i, (name, mins) in enumerate([("Design & proof", 120), ("Print", 60), ("Cut & assemble", 180)], start=1):
        db.insert("job_operations", {"job_id": wedding, "name": name, "sequence": i, "duration_minutes": mins,
                                     "status": "done", "start_at": ctx.ago(days=12 - i), "end_at": ctx.ago(days=12 - i, minutes=-mins),
                                     "completed_at": ctx.ago(days=12 - i, minutes=-mins), "created_at": ctx.ago(days=16)})
    db.update("jobs", wedding, {"completed_at": ctx.ago(days=8)})
    history(wedding, ["Quote", "Approved", "Prepress", "Proofing", "Printing", "Finishing", "Ready for pickup", "Delivered"],
            ctx.now - timedelta(days=15), step_hours=26)

    # 7. Loyalty cards on press right now.
    loyalty = make("loyalty", "Loyalty punch cards — 1,000", "Printing", contact=lena, template="Business cards", qty=1000,
                   quote=96.00, due=_at(ctx, 1, 12), people=("press",), days_ago=4,
                   specs={"product": "Punch cards", "paper_stock": "14pt uncoated (writable)", "ink": "4/1"})
    # On press right now if the shop is open; otherwise first thing next working day.
    local_now = ctx.now.astimezone(ctx.tz)
    live = local_now.weekday() < 5 and 8 <= local_now.hour < 14
    if live:
        print_step = (iso(ctx.now - timedelta(minutes=20)), iso(ctx.now + timedelta(minutes=25)), "press", "in_progress")
        cut_step = (iso(ctx.now + timedelta(minutes=45)), iso(ctx.now + timedelta(minutes=65)), "bindery", None)
    else:
        print_step = (*at("press", 0, 10, 0, 45), "press", None)
        cut_step = (*at("bindery", 0, 11, 0, 20), "bindery", None)
    plan(loyalty, {1: (*at("designer", -2, 9, 0, 30), "designer", "done"), 2: print_step, 3: cut_step})
    db.update("job_operations", db.one("SELECT id FROM job_operations WHERE job_id = ? AND sequence = 2", loyalty)["id"],
              {"resource_id": resources["Digital Press 2"]})
    check(loyalty, {"Files received", "Proof approved", "Stock pulled"})

    # 8. Yard signs in finishing; Taylor's afternoon overlaps another job (shows as a conflict).
    signs = make("signs", "Open house yard signs — 20 coroplast", "Finishing", contact=marcus, qty=20, quote=420.00,
                 due=_at(ctx, 1, 16), people=("bindery",), days_ago=5,
                 specs={"product": "Yard signs", "paper_stock": "4mm coroplast", "finished_size": "18 × 24 in", "ink": "4/4",
                        "finishing": "H-stakes"})
    for i, (name, res, who, (start, end), status) in enumerate([
        ("Print", "Wide Format Printer", "press", at("press", -1, 12, 0, 120), "done"),
        ("Install H-stakes", None, "bindery", at("bindery", 0, 13, 0, 180), None),
    ], start=1):
        db.insert("job_operations", {"job_id": signs, "name": name, "sequence": i, "resource_id": resources.get(res),
                                     "user_id": u(who), "duration_minutes": 120 if i == 1 else 180, "start_at": start,
                                     "end_at": end, "status": status or "pending",
                                     "completed_at": end if status == "done" else None, "created_at": ctx.ago(days=5)})

    # 9. Posters ready for pickup.
    posters = make("posters", "Gala posters 18×24 — 50", "Ready for pickup", contact=priya, qty=50, quote=275.00,
                   due=_at(ctx, 0, 17), people=("frontdesk",), days_ago=6,
                   specs={"product": "Posters", "paper_stock": "100lb gloss text", "finished_size": "18 × 24 in", "ink": "4/0"})
    db.insert("job_checklist", {"job_id": posters, "title": "Customer notified", "position": 1})
    db.insert("job_checklist", {"job_id": posters, "title": "Quality check", "position": 2, "is_done": 1,
                                "done_by": u("bindery"), "done_at": ctx.ago(hours=5)})

    # 10. Overdue stickers nobody scheduled.
    make("stickers", "Tap handle stickers — 250", "Approved", contact=tom, qty=250, quote=145.00,
         due=_at(ctx, -1, 17), priority="high", people=("press",), days_ago=7,
         specs={"product": "Stickers", "paper_stock": "White vinyl", "finished_size": "3 in circle", "finishing": "Kiss cut"})
    stickers = created["stickers"]
    for i, (name, res, mins) in enumerate([("Print", "Wide Format Printer", 60), ("Contour cut", None, 45)], start=1):
        db.insert("job_operations", {"job_id": stickers, "name": name, "sequence": i, "resource_id": resources.get(res),
                                     "duration_minutes": mins, "status": "pending", "created_at": ctx.ago(days=7)})

    # 11. Sponsor postcards quote.
    make("postcards", "Sponsor thank-you postcards — 300", "Quote", contact=dana, qty=300, due=_at(ctx, 10, 17),
         people=("frontdesk",), days_ago=0, specs={"product": "Postcards", "finished_size": "6 × 9 in", "ink": "4/4"})

    # 12. Appointment cards on press this afternoon.
    dental_job = make("dental", "Appointment cards — 2,500", "Printing", contact=maya, template="Business cards", qty=2500,
                      quote=210.00, due=_at(ctx, 1, 17), people=("press", "bindery"), days_ago=3,
                      specs={"product": "Appointment cards", "paper_stock": "14pt uncoated", "ink": "4/1"})
    plan(dental_job, {1: (*at("designer", -1, 9, 0, 30), "designer", "done"),
                      2: (*at("press", 0, 13, 45, 60), "press", None),
                      3: (*at("bindery", 0, 15, 0, 30), "bindery", None)})  # clashes with the H-stakes: one to fix

    # 13. Food bank flyers, delivered.
    flyers = make("flyers", "Volunteer drive flyers — 500", "Delivered", contact=luis, qty=500, quote=118.00, people=("press",),
                  days_ago=9, address="Mesa Food Bank, 1112 E Main St",
                  specs={"product": "Flyers", "paper_stock": "70lb text", "finished_size": "8.5 × 11 in", "ink": "4/0"})
    db.update("jobs", flyers, {"completed_at": ctx.ago(days=3)})
    history(flyers, ["Quote", "Approved", "Printing", "Ready for pickup", "Delivered"], ctx.now - timedelta(days=8), step_hours=30)

    # 14. Brochures waiting for the auto-scheduler.
    make("brochures", "Listing brochures — 250 trifold", "Prepress", contact=marcus, template="Trifold brochure", qty=250,
         quote=310.00, due=_at(ctx, 6, 12), people=("designer",), days_ago=1,
         specs={"product": "Listing brochures", "ink": "4/4"})

    ctx.data["jobs"] = created
