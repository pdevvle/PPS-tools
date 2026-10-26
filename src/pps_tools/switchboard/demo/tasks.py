"""Demo tasks: follow-ups on the demo conversations and jobs, some overdue, some today."""

from __future__ import annotations

from datetime import timedelta

from pps_tools.switchboard import db
from pps_tools.switchboard.services import search
from pps_tools.switchboard.util import iso, now_iso


def _job_ids(ctx) -> list[int]:
    jobs = ctx.data.get("jobs")
    if not jobs:
        return []
    values = jobs.values() if isinstance(jobs, dict) else jobs
    out = []
    for v in values:
        if isinstance(v, int):
            out.append(v)
        elif isinstance(v, dict) and v.get("id"):
            out.append(int(v["id"]))
    return [j for j in out if db.one("SELECT id FROM jobs WHERE id = ?", j)]


def seed_tasks(ctx) -> None:
    u = ctx.uid
    convs = ctx.data.get("conversations") or {}
    jobs = _job_ids(ctx)
    office = ctx.teams.get("office")
    production = ctx.teams.get("production")

    def at(days, hour, minute=0):
        return iso(ctx.local(days=days, hour=hour, minute=minute))

    rows = [
        # title, assignee, creator, due, priority, conversation key, job index, team, status, description
        ("Send Lena the quote for 200 trifold menus", "frontdesk", "frontdesk", at(0, 15), "high", "menus", None, office, "todo",
         "<p>100lb gloss text, 11x17 folded to letter, 4/4. Include the 45 min prepress rebuild.</p>"),
        ("Rebuild Desert Bloom menu file with 1/8\" bleed", "designer", "frontdesk", at(0, 13), "normal", "menus", 0, production,
         "in_progress", "<p>Last season's PDF only has 1/16\" bleed and the fold marks are off.</p>"),
        ("Chase Marcus for proof approval", "designer", "designer", at(-1, 16), "high", "cards", None, office, "todo", None),
        ("Call Coach Dana about banner sizes and grommets", "frontdesk", "owner", at(0, 11), "urgent", "banners", None, office,
         "todo", "<p>3x6 vinyl, 15 banners. Confirm hemming + grommets every 2 ft and pickup Friday.</p>"),
        ("Order 13oz vinyl (3 rolls) for the league banners", "manager", "manager", at(1, 10), "high", "banners", None, production,
         "todo", None),
        ("Hold Friday on Press 1 for the Arts Council programs", "manager", "manager", at(-2, 12), "normal", "programs", None,
         production, "done", None),
        ("Clean Press 2 rollers before the service visit", "press", "manager", at(2, 9), "normal", None, 1, production, "todo", None),
        ("Restock 100lb gloss text — down to 2 cartons", "bindery", "manager", at(3, 12), "normal", None, None, production, "todo", None),
        ("Deliver Copperline label samples", "driver", "frontdesk", at(1, 14), "normal", None, None, None, "todo",
         "<p>Sample pack is on the shelf by the door, labeled COPPERLINE.</p>"),
        ("Update the price sheet after the Mohawk increase", "owner", "owner", at(6, 17), "low", None, None, office, "todo", None),
        ("Back up the RIP server", "manager", "manager", None, "low", None, None, production, "todo", None),
        ("Post the holiday hours on the website", "frontdesk", "owner", at(-3, 12), "normal", None, None, office, "done", None),
    ]
    created = ctx.ago(days=1, hours=2)
    for i, (title, assignee, creator, due, priority, conv_key, job_idx, team, status, desc) in enumerate(rows, start=1):
        cid = convs.get(conv_key) if conv_key else None
        job_id = jobs[job_idx] if job_idx is not None and job_idx < len(jobs) else None
        conv = db.one("SELECT last_activity_at FROM conversations WHERE id = ?", cid) if cid else None
        made_at = min(conv["last_activity_at"], now_iso()) if conv else created
        completed = None
        if status == "done":
            completed = due or made_at
        tid = db.insert("tasks", {
            "title": title, "description": desc, "status": status, "priority": priority, "due_at": due,
            "assignee_id": u(assignee), "team_id": team, "conversation_id": cid, "job_id": job_id, "position": i,
            "created_by": u(creator), "created_at": made_at, "updated_at": made_at,
            "completed_at": completed, "completed_by": u(assignee) if completed else None,
            # the demo starts "already notified" about anything due earlier
            "due_notified_at": now_iso() if due and due <= iso(ctx.now + timedelta(hours=1)) else None,
            "overdue_notified_at": now_iso() if due and due <= now_iso() else None,
        })
        search.index("task", tid, title, desc or "")
        if cid:
            db.insert("conversation_events", {"conversation_id": cid, "user_id": u(creator), "type": "task_created",
                                              "data_json": db.jdump({"task_id": tid, "title": title}), "created_at": made_at})
