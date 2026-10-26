"""Jobs: work orders moving through stages, with operations (scheduled steps), a
checklist, files/proofs, comments and links to inbox conversations.

Everyone signed in can see jobs. Editing the job itself needs ``manage_jobs``; people
on the floor (role staff) can comment, tick checklist items and start/finish the
operations they're assigned to.
"""

from __future__ import annotations

from datetime import timedelta

from pps_tools.switchboard import config, db, realtime
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import files, hooks, inbox, notify, reactions, search, settings
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.services.sanitize import is_blank, mention_ids, sanitize
from pps_tools.switchboard.util import html_to_text, iso, norm_iso, now, now_iso, parse_iso, snippet, token
from pps_tools.switchboard.web import bad_request, can, forbidden, not_found

settings.register_defaults({
    "jobs.number_prefix": "J-",
    "jobs.next_number": 1001,
    # When the auto-scheduler may place work (org-local time; days 0=Mon..6=Sun).
    "jobs.work_hours": {"start": "07:00", "end": "18:00", "days": [0, 1, 2, 3, 4]},
    "jobs.due_soon_hours": 24,
})

PRIORITIES = ("low", "normal", "high", "rush")
PRIORITY_RANK = {"rush": 0, "high": 1, "normal": 2, "low": 3}
FIELD_TYPES = ("text", "number", "select", "checkbox", "date", "textarea")
OP_STATUSES = ("pending", "in_progress", "done")


def link(job_id: int) -> str:
    return f"/jobs/{job_id}"


def public_url(tok: str) -> str:
    return f"{config.current().base_url}/public/jobs/{tok}"


# -- reference data -----------------------------------------------------------------


def stages() -> list[dict]:
    rows = db.query("SELECT * FROM job_stages ORDER BY position, id")
    for r in rows:
        r["is_done"] = bool(r["is_done"])
    return rows


def stage(stage_id: int | None) -> dict | None:
    return db.one("SELECT * FROM job_stages WHERE id = ?", stage_id) if stage_id else None


def default_stage() -> dict | None:
    return db.one("SELECT * FROM job_stages WHERE is_done = 0 ORDER BY position, id LIMIT 1") or \
        db.one("SELECT * FROM job_stages ORDER BY position, id LIMIT 1")


def done_stage_ids() -> list[int]:
    return db.column("SELECT id FROM job_stages WHERE is_done = 1")


def fields() -> list[dict]:
    rows = db.query("SELECT * FROM job_fields ORDER BY position, id")
    for r in rows:
        r["options"] = db.jload(r.pop("options_json"), [])
    return rows


def resources(active_only: bool = False) -> list[dict]:
    rows = db.query(
        "SELECT * FROM resources " + ("WHERE is_active = 1 " if active_only else "") + "ORDER BY position, name COLLATE NOCASE"
    )
    for r in rows:
        r["is_active"] = bool(r["is_active"])
    return rows


def templates() -> list[dict]:
    rows = db.query("SELECT * FROM job_templates ORDER BY name COLLATE NOCASE")
    return [serialize_template(t) for t in rows]


def serialize_template(t: dict) -> dict:
    return {
        "id": t["id"], "name": t["name"], "description": t["description"],
        "operations": db.jload(t["operations_json"], []), "checklist": db.jload(t["checklist_json"], []),
        "specs": db.jload(t["specs_json"], {}), "created_at": t["created_at"], "updated_at": t["updated_at"],
    }


def skills() -> list[dict]:
    return db.query("SELECT id, name FROM skills ORDER BY name COLLATE NOCASE")


def ensure_skill(name: str) -> int:
    """Skills are shared with staffing; create by name if missing."""
    db.execute("INSERT OR IGNORE INTO skills (name, created_at) VALUES (?, ?)", name, now_iso())
    return db.one("SELECT id FROM skills WHERE name = ?", name)["id"]


# -- numbering ----------------------------------------------------------------------


def next_number() -> str:
    """Claim the next job number. Call inside a transaction: the write lock makes it
    atomic. Reads the counter from the table, not the settings cache."""
    row = db.one("SELECT value_json FROM settings WHERE key = 'jobs.next_number'")
    n = int(db.jload(row["value_json"]) if row else settings.DEFAULTS["jobs.next_number"])
    prefix = settings.get("jobs.number_prefix") or ""
    while db.one("SELECT 1 AS taken FROM jobs WHERE number = ?", f"{prefix}{n}"):
        n += 1
    settings.set("jobs.next_number", n + 1)
    return f"{prefix}{n}"


# -- reads --------------------------------------------------------------------------


def get(job_id: int) -> dict | None:
    return db.one("SELECT * FROM jobs WHERE id = ?", job_id)


def get_or_404(job_id: int) -> dict:
    job = get(job_id)
    if not job:
        not_found("Job not found")
    return job


def assignees(job_id: int) -> list[int]:
    return db.column("SELECT user_id FROM job_assignees WHERE job_id = ? ORDER BY user_id", job_id)


def due_state(job: dict, is_done: bool, current=None) -> str | None:
    if is_done or job.get("archived_at") or not job.get("due_at"):
        return None
    current = current or now()
    due = parse_iso(job["due_at"])
    if due < current:
        return "overdue"
    if due < current + timedelta(hours=float(settings.get("jobs.due_soon_hours") or 24)):
        return "soon"
    return None


def summaries(rows: list[dict]) -> list[dict]:
    """List/board form of jobs, loaded in a handful of batched queries."""
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    ph = db.placeholders(ids)
    assignee_map: dict[int, list[int]] = {}
    for a in db.query(f"SELECT job_id, user_id FROM job_assignees WHERE job_id IN ({ph}) ORDER BY user_id", ids):
        assignee_map.setdefault(a["job_id"], []).append(a["user_id"])
    checklist = {r["job_id"]: r for r in db.query(
        f"SELECT job_id, COUNT(*) AS total, SUM(is_done) AS done FROM job_checklist WHERE job_id IN ({ph}) GROUP BY job_id", ids)}
    ops = {r["job_id"]: r for r in db.query(
        f"SELECT job_id, COUNT(*) AS total, SUM(status = 'done') AS done, SUM(start_at IS NOT NULL) AS scheduled, "
        f"SUM(status = 'in_progress') AS active, SUM(duration_minutes) AS minutes "
        f"FROM job_operations WHERE job_id IN ({ph}) GROUP BY job_id", ids)}
    convs = {r["job_id"]: r["n"] for r in db.query(
        f"SELECT job_id, COUNT(*) AS n FROM job_conversations WHERE job_id IN ({ph}) GROUP BY job_id", ids)}
    comments = {r["job_id"]: r["n"] for r in db.query(
        f"SELECT job_id, COUNT(*) AS n FROM job_activity WHERE type = 'comment' AND job_id IN ({ph}) GROUP BY job_id", ids)}
    file_counts = {r["owner_id"]: r["n"] for r in db.query(
        f"SELECT owner_id, COUNT(*) AS n FROM attachments WHERE owner_type = 'job' AND owner_id IN ({ph}) GROUP BY owner_id", ids)}
    contact_ids = sorted({r["contact_id"] for r in rows if r["contact_id"]})
    contact_map = {c["id"]: c for c in db.query(
        f"SELECT * FROM contacts WHERE id IN ({db.placeholders(contact_ids)})", contact_ids)} if contact_ids else {}
    org_ids = sorted({r["organization_id"] for r in rows if r["organization_id"]})
    org_map = {o["id"]: o for o in db.query(
        f"SELECT id, name FROM organizations WHERE id IN ({db.placeholders(org_ids)})", org_ids)} if org_ids else {}
    done_ids = set(done_stage_ids())
    current = now()
    out = []
    for r in rows:
        c = contact_map.get(r["contact_id"])
        o = org_map.get(r["organization_id"])
        cl = checklist.get(r["id"]) or {}
        op = ops.get(r["id"]) or {}
        is_done = r["stage_id"] in done_ids
        out.append({
            "id": r["id"],
            "number": r["number"],
            "title": r["title"],
            "stage_id": r["stage_id"],
            "priority": r["priority"],
            "is_done": is_done,
            "contact": {"id": c["id"], "name": c["name"], "display_name": contacts_svc.display_name(c),
                        "email": c["email"], "phone": c["phone"]} if c else None,
            "organization": o,
            "customer": (o or {}).get("name") or (contacts_svc.display_name(c) if c else None),
            "due_at": r["due_at"],
            "due_state": due_state(r, is_done, current),
            "quantity": r["quantity"],
            "quote_amount": r["quote_amount"],
            "estimated_minutes": r["estimated_minutes"],
            "tags": db.jload(r["tags_json"], []),
            "position": r["position"],
            "assignee_ids": assignee_map.get(r["id"], []),
            "checklist": {"done": cl.get("done") or 0, "total": cl.get("total") or 0},
            "operations": {"done": op.get("done") or 0, "total": op.get("total") or 0,
                           "scheduled": op.get("scheduled") or 0, "active": op.get("active") or 0,
                           "minutes": op.get("minutes") or 0},
            "conversation_count": convs.get(r["id"], 0),
            "comment_count": comments.get(r["id"], 0),
            "file_count": file_counts.get(r["id"], 0),
            "proof_status": r["proof_status"],
            "stage_entered_at": r["stage_entered_at"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "completed_at": r["completed_at"],
            "archived_at": r["archived_at"],
        })
    return out


def summary(job: dict) -> dict:
    return summaries([job])[0]


def serialize_operation(op: dict) -> dict:
    return {k: op[k] for k in (
        "id", "job_id", "name", "sequence", "resource_id", "user_id", "skill_id", "duration_minutes", "start_at",
        "end_at", "status", "notes", "started_at", "started_by", "completed_at", "completed_by", "created_at",
    )}


def operations(job_id: int) -> list[dict]:
    return [serialize_operation(o) for o in
            db.query("SELECT * FROM job_operations WHERE job_id = ? ORDER BY sequence, id", job_id)]


def checklist_items(job_id: int) -> list[dict]:
    rows = db.query("SELECT * FROM job_checklist WHERE job_id = ? ORDER BY position, id", job_id)
    for r in rows:
        r["is_done"] = bool(r["is_done"])
    return rows


def activity_items(job_id: int) -> list[dict]:
    rows = db.query("SELECT * FROM job_activity WHERE job_id = ? ORDER BY created_at, id", job_id)
    reacts = reactions.for_targets("job_activity", [r["id"] for r in rows if r["type"] == "comment"])
    return [{
        "id": r["id"], "type": r["type"], "user_id": r["user_id"], "body": r["body"],
        "data": db.jload(r["data_json"], {}), "created_at": r["created_at"], "reactions": reacts.get(r["id"], []),
    } for r in rows]


def job_files(job_id: int) -> list[dict]:
    proof_ids = set(db.column("SELECT attachment_id FROM job_proofs WHERE job_id = ?", job_id))
    out = []
    for att in files.for_owner("job", job_id):
        item = files.serialize(att)
        item["is_proof"] = att["id"] in proof_ids
        item["uploaded_by"] = att["uploaded_by"]
        item["created_at"] = att["created_at"]
        out.append(item)
    return out


def time_tracked(job_id: int) -> dict:
    """Minutes clocked against this job (time clock entries with job_id)."""
    rows = db.query("SELECT user_id, clock_in, clock_out, break_minutes FROM time_entries WHERE job_id = ?", job_id)
    current = now()
    per_user: dict[int, float] = {}
    running = []
    for r in rows:
        start = parse_iso(r["clock_in"])
        end = parse_iso(r["clock_out"]) if r["clock_out"] else current
        minutes = max(0.0, (end - start).total_seconds() / 60 - (r["break_minutes"] or 0))
        per_user[r["user_id"]] = per_user.get(r["user_id"], 0) + minutes
        if not r["clock_out"]:
            running.append(r["user_id"])
    total = sum(per_user.values())
    return {
        "total_minutes": round(total),
        "by_user": [{"user_id": u, "minutes": round(m)} for u, m in sorted(per_user.items(), key=lambda x: -x[1])],
        "running_user_ids": sorted(set(running)),
    }


def linked_conversations(user: dict, job_id: int) -> tuple[list[dict], int]:
    rows = db.query(
        "SELECT c.* FROM job_conversations jc JOIN conversations c ON c.id = jc.conversation_id "
        "WHERE jc.job_id = ? AND c.merged_into_id IS NULL ORDER BY c.last_activity_at DESC", job_id,
    )
    visible, hidden = [], 0
    for c in rows:
        if not inbox.can_view(user, c["id"]):
            hidden += 1
            continue
        contact = contacts_svc.get(c["contact_id"])
        ch = db.one("SELECT type, name FROM channels WHERE id = ?", c["channel_id"]) if c["channel_id"] else None
        visible.append({
            "id": c["id"], "subject": c["subject"], "status": c["status"], "preview": c["preview"],
            "contact_name": contacts_svc.display_name(contact, None) if contact else None,
            "channel_type": ch["type"] if ch else None, "last_activity_at": c["last_activity_at"],
            "deleted": bool(c["deleted_at"]),
        })
    return visible, hidden


def job_tasks(job_id: int) -> list[dict]:
    return db.query(
        "SELECT id, title, status, priority, due_at, assignee_id, completed_at FROM tasks WHERE job_id = ? "
        "ORDER BY status = 'done', due_at IS NULL, due_at, id", job_id,
    )


def detail(user: dict, job_id: int) -> dict:
    job = get_or_404(job_id)
    out = summary(job)
    out.update({
        "description": job["description"],
        "specs": db.jload(job["specs_json"], {}),
        "po_number": job["po_number"],
        "address": job["address"],
        "template_id": job["template_id"],
        "public_token": job["public_token"],
        "public_url": public_url(job["public_token"]) if job["public_token"] else None,
        "proof_decided_at": job["proof_decided_at"],
        "proof_decided_by": job["proof_decided_by"],
        "created_by": job["created_by"],
    })
    ops = operations(job_id)
    convs, hidden = linked_conversations(user, job_id)
    time = time_tracked(job_id)
    estimate = job["estimated_minutes"] or sum(o["duration_minutes"] or 0 for o in ops) or None
    return {
        "job": out,
        "operations": ops,
        "checklist": checklist_items(job_id),
        "activity": activity_items(job_id),
        "conversations": convs,
        "hidden_conversation_count": hidden,
        "files": job_files(job_id),
        "tasks": job_tasks(job_id),
        "time": time,
        "estimate_minutes": estimate,
        "actual_minutes": time["total_minutes"],
    }


# -- writes -------------------------------------------------------------------------


def add_activity(job_id: int, type_: str, user_id: int | None = None, data: dict | None = None,
                 body: str | None = None, at: str | None = None) -> int:
    return db.insert("job_activity", {
        "job_id": job_id, "user_id": user_id, "type": type_, "body": body,
        "data_json": db.jdump(data or {}), "created_at": at or now_iso(),
    })


def touch(job_id: int | None, reason: str = "updated", schedule: bool = False) -> None:
    """Everyone can see jobs, so changes are broadcast."""
    realtime.emit("job.changed", {"id": job_id, "reason": reason})
    if schedule:
        realtime.emit("schedule.changed", {"job_id": job_id})


def badge_refresh(user_ids) -> None:
    ids = [u for u in user_ids if u]
    if ids:
        realtime.emit("badges.changed", {}, users=ids)


def reindex(job_id: int) -> None:
    job = get(job_id)
    if not job:
        search.unindex("job", job_id)
        return
    contact = contacts_svc.get(job["contact_id"])
    org = db.one("SELECT name FROM organizations WHERE id = ?", job["organization_id"]) if job["organization_id"] else None
    specs = db.jload(job["specs_json"], {}) or {}
    body = " ".join(str(x) for x in [
        job["description"] or "", contacts_svc.display_name(contact, "") if contact else "", (org or {}).get("name") or "",
        job["po_number"] or "", " ".join(str(v) for v in specs.values() if v not in (None, "", False)),
        " ".join(db.jload(job["tags_json"], [])),
    ])
    search.index("job", job_id, f"{job['number']} {job['title']}", body)


def _clean_specs(specs) -> dict:
    if specs is None:
        return {}
    if not isinstance(specs, dict):
        bad_request("specs must be an object")
    out = {}
    for k, v in specs.items():
        if not isinstance(k, str) or len(k) > 60:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v.strip()[:500] if isinstance(v, str) else v
    return out


def _clean_tags(tags) -> list[str]:
    if not tags:
        return []
    if isinstance(tags, str):
        tags = [t for t in tags.split(",")]
    return list(dict.fromkeys(str(t).strip()[:40] for t in tags if str(t).strip()))[:20]


def _num(value, name, kind=float):
    if value in (None, ""):
        return None
    try:
        return kind(value)
    except (TypeError, ValueError):
        bad_request(f"'{name}' must be a number")


def _common_fields(data: dict) -> dict:
    out = {}
    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            bad_request("A job needs a title")
        out["title"] = title[:200]
    if "description" in data:
        out["description"] = (data.get("description") or "").strip()[:20000] or None
    if "priority" in data:
        if data["priority"] not in PRIORITIES:
            bad_request("Priority must be low, normal, high or rush")
        out["priority"] = data["priority"]
    if "due_at" in data:
        if data["due_at"] in (None, ""):
            out["due_at"] = None
        else:
            due = norm_iso(data["due_at"])
            if not due:
                bad_request("Due date isn't a valid date/time")
            out["due_at"] = due
    if "quantity" in data:
        q = _num(data["quantity"], "quantity", int)
        if q is not None and q < 0:
            bad_request("Quantity can't be negative")
        out["quantity"] = q
    if "quote_amount" in data:
        out["quote_amount"] = _num(data["quote_amount"], "quote_amount")
    if "estimated_minutes" in data:
        out["estimated_minutes"] = _num(data["estimated_minutes"], "estimated_minutes", int)
    for f in ("po_number", "address"):
        if f in data:
            out[f] = (data.get(f) or "").strip()[:500] or None
    if "tags" in data:
        out["tags_json"] = db.jdump(_clean_tags(data["tags"]))
    if "specs" in data:
        out["specs_json"] = db.jdump(_clean_specs(data["specs"]))
    if "contact_id" in data:
        cid = _num(data["contact_id"], "contact_id", int)
        if cid and not contacts_svc.get(cid):
            bad_request("No such contact")
        out["contact_id"] = cid
    if "organization_id" in data:
        oid = _num(data["organization_id"], "organization_id", int)
        if oid and not db.one("SELECT id FROM organizations WHERE id = ?", oid):
            bad_request("No such organization")
        out["organization_id"] = oid
    return out


def _end_position(stage_id: int | None) -> float:
    top = db.scalar("SELECT MAX(position) FROM jobs WHERE stage_id IS ? AND archived_at IS NULL", stage_id)
    return (top or 0) + 1


def create(user: dict, data: dict) -> dict:
    data = dict(data or {})
    conv = None
    if data.get("conversation_id"):
        conv = inbox.get_for(user, int(data["conversation_id"]))
    template = None
    if data.get("template_id"):
        template = db.one("SELECT * FROM job_templates WHERE id = ?", int(data["template_id"]))
        if not template:
            bad_request("No such template")
    if conv:
        data.setdefault("contact_id", conv["contact_id"])
        if not (data.get("title") or "").strip():
            data["title"] = conv["subject"] or inbox.title_of(conv)
    if template and not (data.get("title") or "").strip():
        data["title"] = template["name"]
    values = _common_fields({**data, "title": data.get("title")})
    st = stage(int(data["stage_id"])) if data.get("stage_id") else default_stage()
    if data.get("stage_id") and not st:
        bad_request("No such stage")
    if values.get("contact_id") and not values.get("organization_id"):
        contact = contacts_svc.get(values["contact_id"])
        if contact and contact["organization_id"]:
            values["organization_id"] = contact["organization_id"]
    specs = {}
    if template:
        specs.update(db.jload(template["specs_json"], {}) or {})
    specs.update(db.jload(values.get("specs_json"), {}) or {})
    values["specs_json"] = db.jdump(specs)
    stamp = now_iso()
    with db.transaction():
        values.update({
            "number": next_number(),
            "stage_id": st["id"] if st else None,
            "template_id": template["id"] if template else None,
            "position": _end_position(st["id"] if st else None),
            "stage_entered_at": stamp,
            "created_by": user["id"] if user else None,
            "created_at": stamp,
            "updated_at": stamp,
            "completed_at": stamp if st and st["is_done"] else None,
        })
        values.setdefault("tags_json", "[]")
        job_id = db.insert("jobs", values)
        if template:
            apply_template(job_id, template)
        for i, title in enumerate(data.get("checklist") or []):
            if str(title).strip():
                db.insert("job_checklist", {"job_id": job_id, "title": str(title).strip()[:300],
                                            "position": 1000 + i})
        add_activity(job_id, "created", user["id"] if user else None, {
            "template": template["name"] if template else None, "conversation_id": conv["id"] if conv else None,
        })
        if conv:
            _link_conversation(user, job_id, conv)
        if data.get("assignee_ids"):
            set_assignees(job_id, data["assignee_ids"], user["id"] if user else None)
        files.claim(data.get("attachment_ids"), "job", job_id, user["id"] if user else None)
        reindex(job_id)
        touch(job_id, "created", schedule=True)
        hooks.fire("job.created", {"job_id": job_id, "conversation_id": conv["id"] if conv else None,
                                   "by": user["id"] if user else None})
    return get(job_id)


def apply_template(job_id: int, template: dict) -> None:
    seq = (db.scalar("SELECT MAX(sequence) FROM job_operations WHERE job_id = ?", job_id) or 0)
    stamp = now_iso()
    for op in db.jload(template["operations_json"], []) or []:
        seq += 1
        db.insert("job_operations", {
            "job_id": job_id, "name": (op.get("name") or "Step")[:120], "sequence": seq,
            "resource_id": op.get("resource_id"), "skill_id": op.get("skill_id"),
            "duration_minutes": max(5, int(op.get("duration_minutes") or 60)), "status": "pending", "created_at": stamp,
        })
    pos = (db.scalar("SELECT MAX(position) FROM job_checklist WHERE job_id = ?", job_id) or 0)
    for item in db.jload(template["checklist_json"], []) or []:
        title = item if isinstance(item, str) else (item or {}).get("title")
        if title:
            pos += 1
            db.insert("job_checklist", {"job_id": job_id, "title": str(title)[:300], "position": pos})


def update(user: dict, job: dict, data: dict) -> dict:
    values = _common_fields(data)
    job_id = job["id"]
    with db.transaction():
        changed = [k.replace("_json", "") for k, v in values.items() if job.get(k) != v]
        if values:
            values["updated_at"] = now_iso()
            db.update("jobs", job_id, values)
        if "due_at" in values and values["due_at"] != job["due_at"]:
            add_activity(job_id, "due_changed", user["id"], {"from": job["due_at"], "to": values["due_at"]})
            changed = [c for c in changed if c != "due_at"]
            badge_refresh(assignees(job_id))
        if "priority" in values and values["priority"] != job["priority"]:
            add_activity(job_id, "priority_changed", user["id"], {"from": job["priority"], "to": values["priority"]})
            changed = [c for c in changed if c != "priority"]
        if changed:
            add_activity(job_id, "updated", user["id"], {"fields": sorted(changed)})
        if "assignee_ids" in data:
            set_assignees(job_id, data["assignee_ids"], user["id"])
        if "stage_id" in data and data["stage_id"] and int(data["stage_id"]) != job["stage_id"]:
            move(user, get(job_id), int(data["stage_id"]))
        reindex(job_id)
        touch(job_id, "updated", schedule="due_at" in values)
    return get(job_id)


def set_assignees(job_id: int, user_ids, by: int | None) -> tuple[list[int], list[int]]:
    job = get(job_id)
    wanted = {int(u) for u in (user_ids or [])} & set(users_svc.active_ids())
    current = set(assignees(job_id))
    added = sorted(wanted - current)
    removed = sorted(current - wanted)
    for uid in added:
        db.insert("job_assignees", {"job_id": job_id, "user_id": uid})
    for uid in removed:
        db.execute("DELETE FROM job_assignees WHERE job_id = ? AND user_id = ?", job_id, uid)
    if added:
        add_activity(job_id, "assigned", by, {"user_ids": added})
        actor = users_svc.name_of(by, "Switchboard") if by else "Switchboard"
        notify.notify(added, "assigned", f"{actor} put you on {job['number']}: {job['title']}",
                      body=_due_text(job), link=link(job_id), actor_id=by, entity_type="job", entity_id=job_id)
        hooks.fire("job.assigned", {"job_id": job_id, "user_ids": added, "by": by})
    if removed:
        add_activity(job_id, "unassigned", by, {"user_ids": removed})
    badge_refresh(added + removed)
    return added, removed


def _due_text(job: dict) -> str | None:
    if not job.get("due_at"):
        return None
    local = parse_iso(job["due_at"]).astimezone(settings.timezone())
    return "Due " + local.strftime("%a %b %-d, %-I:%M %p") if hasattr(local, "strftime") else None


def move(user: dict | None, job: dict, stage_id: int, position: int | None = None) -> dict:
    """Move to a stage (and/or to index ``position`` within its column)."""
    st = stage(stage_id)
    if not st:
        bad_request("No such stage")
    job_id = job["id"]
    by = user["id"] if user else None
    with db.transaction():
        siblings = db.query(
            "SELECT id, position FROM jobs WHERE stage_id = ? AND id != ? AND archived_at IS NULL ORDER BY position, id",
            stage_id, job_id,
        )
        if position is None or position >= len(siblings):
            new_pos = (siblings[-1]["position"] + 1) if siblings else 1.0
        else:
            idx = max(0, int(position))
            after = siblings[idx]["position"]
            before = siblings[idx - 1]["position"] if idx > 0 else after - 2
            new_pos = (before + after) / 2
            if abs(after - before) < 1e-6:
                for i, s in enumerate(siblings):
                    db.update("jobs", s["id"], {"position": float(i * 2 + (2 if i >= idx else 0))})
                new_pos = float(idx * 2 + 1)
        values = {"position": new_pos, "updated_at": now_iso()}
        moved = stage_id != job["stage_id"]
        if moved:
            old = stage(job["stage_id"])
            values["stage_id"] = stage_id
            values["stage_entered_at"] = now_iso()
            values["completed_at"] = (job["completed_at"] or now_iso()) if st["is_done"] else None
            db.update("jobs", job_id, values)
            add_activity(job_id, "stage_changed", by, {
                "from_id": job["stage_id"], "to_id": stage_id,
                "from": old["name"] if old else None, "to": st["name"],
            })
            people = set(assignees(job_id))
            notify.notify(people, "job", f"{job['number']} moved to {st['name']}", body=job["title"],
                          link=link(job_id), actor_id=by, entity_type="job", entity_id=job_id)
            hooks.fire("job.stage_changed", {"job_id": job_id, "from_stage_id": job["stage_id"], "to_stage_id": stage_id,
                                             "by": by})
            if st["is_done"] and not (old and old["is_done"]):
                hooks.fire("job.completed", {"job_id": job_id, "by": by})
            badge_refresh(people)
        else:
            db.update("jobs", job_id, values)
        wip = st["wip_limit"]
        touch(job_id, "moved", schedule=moved)
    over = bool(wip) and db.scalar(
        "SELECT COUNT(*) FROM jobs WHERE stage_id = ? AND archived_at IS NULL", stage_id) > wip
    out = get(job_id)
    out["wip_exceeded"] = over
    return out


def archive(user: dict, job: dict, archived: bool) -> dict:
    with db.transaction():
        db.update("jobs", job["id"], {"archived_at": now_iso() if archived else None, "updated_at": now_iso()})
        add_activity(job["id"], "archived" if archived else "unarchived", user["id"])
        touch(job["id"], "archived", schedule=True)
        badge_refresh(assignees(job["id"]))
    return get(job["id"])


def delete(job: dict) -> None:
    with db.transaction():
        people = assignees(job["id"])
        files.delete_for_owner("job", job["id"])
        search.unindex("job", job["id"])
        db.execute("UPDATE tasks SET job_id = NULL WHERE job_id = ?", job["id"])
        db.execute("UPDATE time_entries SET job_id = NULL WHERE job_id = ?", job["id"])
        db.execute("UPDATE shifts SET job_id = NULL WHERE job_id = ?", job["id"])
        db.delete("jobs", job["id"])
        touch(job["id"], "deleted", schedule=True)
        badge_refresh(people)


# -- checklist ----------------------------------------------------------------------


def add_check(user: dict, job: dict, title: str) -> dict:
    title = (title or "").strip()
    if not title:
        bad_request("Checklist items need a title")
    with db.transaction():
        pos = (db.scalar("SELECT MAX(position) FROM job_checklist WHERE job_id = ?", job["id"]) or 0) + 1
        cid = db.insert("job_checklist", {"job_id": job["id"], "title": title[:300], "position": pos})
        touch(job["id"], "checklist")
    return db.one("SELECT * FROM job_checklist WHERE id = ?", cid)


def update_check(user: dict, item: dict, data: dict) -> dict:
    values = {}
    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            bad_request("Checklist items need a title")
        values["title"] = title[:300]
    if "is_done" in data:
        done = bool(data["is_done"])
        values.update({"is_done": 1 if done else 0, "done_by": user["id"] if done else None,
                       "done_at": now_iso() if done else None})
    if "position" in data:
        values["position"] = _num(data["position"], "position", int) or 0
    with db.transaction():
        db.update("job_checklist", item["id"], values)
        if "is_done" in values and bool(values["is_done"]) != bool(item["is_done"]):
            add_activity(item["job_id"], "checked" if values["is_done"] else "unchecked", user["id"],
                         {"item": item["title"]})
        touch(item["job_id"], "checklist")
    return db.one("SELECT * FROM job_checklist WHERE id = ?", item["id"])


def delete_check(item: dict) -> None:
    with db.transaction():
        db.delete("job_checklist", item["id"])
        touch(item["job_id"], "checklist")


# -- comments -----------------------------------------------------------------------


def add_comment(user: dict, job: dict, body_html: str) -> dict:
    body = sanitize(body_html, "basic")
    if is_blank(body):
        bad_request("Write something first")
    active = set(users_svc.active_ids())
    mentioned = [u for u in mention_ids(body) if u in active and u != user["id"]]
    text = html_to_text(body)
    with db.transaction():
        aid = add_activity(job["id"], "comment", user["id"], {"mentions": mentioned}, body=body)
        notify.notify(mentioned, "mention", f"{user['name']} mentioned you on {job['number']}",
                      body=snippet(text, 140), link=link(job["id"]), actor_id=user["id"], entity_type="job",
                      entity_id=job["id"])
        others = set(assignees(job["id"])) - set(mentioned) - {user["id"]}
        notify.notify(others, "job", f"{user['name']} commented on {job['number']}: {job['title']}",
                      body=snippet(text, 140), link=link(job["id"]), actor_id=user["id"], entity_type="job",
                      entity_id=job["id"])
        touch(job["id"], "comment")
        hooks.fire("job.comment", {"job_id": job["id"], "activity_id": aid, "user_id": user["id"], "mentions": mentioned})
    return db.one("SELECT * FROM job_activity WHERE id = ?", aid)


def edit_comment(user: dict, item: dict, body_html: str) -> dict:
    if item["type"] != "comment":
        bad_request("Only comments can be edited")
    if item["user_id"] != user["id"]:
        forbidden("You can only edit your own comments")
    body = sanitize(body_html, "basic")
    if is_blank(body):
        bad_request("A comment can't be empty")
    with db.transaction():
        data = db.jload(item["data_json"], {}) or {}
        data["edited_at"] = now_iso()
        db.update("job_activity", item["id"], {"body": body, "data_json": db.jdump(data)})
        touch(item["job_id"], "comment")
    return db.one("SELECT * FROM job_activity WHERE id = ?", item["id"])


def delete_comment(user: dict, item: dict) -> None:
    if item["type"] != "comment":
        bad_request("Only comments can be deleted")
    if item["user_id"] != user["id"] and user["role"] not in ("owner", "admin"):
        forbidden("You can only delete your own comments")
    with db.transaction():
        db.delete("job_activity", item["id"])
        db.execute("DELETE FROM reactions WHERE target_type = 'job_activity' AND target_id = ?", item["id"])
        touch(item["job_id"], "comment")


# -- files & proofs -----------------------------------------------------------------


def add_files(user: dict, job: dict, attachment_ids, proof: bool = False) -> list[dict]:
    ids = [int(i) for i in attachment_ids or [] if str(i).isdigit()]
    if not ids:
        bad_request("Upload a file first")
    with db.transaction():
        before = {a["id"] for a in files.for_owner("job", job["id"])}
        files.claim(ids, "job", job["id"], user["id"])
        added = [a for a in files.for_owner("job", job["id"]) if a["id"] not in before]
        if not added:
            bad_request("Those files couldn't be attached")
        if proof:
            for a in added:
                db.execute("INSERT OR IGNORE INTO job_proofs (attachment_id, job_id, created_at) VALUES (?, ?, ?)",
                           a["id"], job["id"], now_iso())
            if job["public_token"]:
                db.update("jobs", job["id"], {"proof_status": "pending", "proof_decided_at": None, "proof_decided_by": None})
        add_activity(job["id"], "proof_added" if proof else "files_added", user["id"],
                     {"names": [a["filename"] for a in added]})
        touch(job["id"], "files")
    return job_files(job["id"])


def set_proof(user: dict, job: dict, att_id: int, is_proof: bool) -> list[dict]:
    att = db.one("SELECT * FROM attachments WHERE id = ? AND owner_type = 'job' AND owner_id = ?", att_id, job["id"])
    if not att:
        not_found("File not found")
    with db.transaction():
        if is_proof:
            db.execute("INSERT OR IGNORE INTO job_proofs (attachment_id, job_id, created_at) VALUES (?, ?, ?)",
                       att_id, job["id"], now_iso())
        else:
            db.execute("DELETE FROM job_proofs WHERE attachment_id = ?", att_id)
        touch(job["id"], "files")
    return job_files(job["id"])


def remove_file(user: dict, job: dict, att_id: int) -> None:
    att = db.one("SELECT * FROM attachments WHERE id = ? AND owner_type = 'job' AND owner_id = ?", att_id, job["id"])
    if not att:
        not_found("File not found")
    with db.transaction():
        files.delete(att)
        add_activity(job["id"], "file_removed", user["id"], {"name": att["filename"]})
        touch(job["id"], "files")


def share(user: dict, job: dict) -> dict:
    with db.transaction():
        tok = job["public_token"] or token(18)
        values = {"public_token": tok}
        if not job["proof_status"]:
            values["proof_status"] = "pending"
        db.update("jobs", job["id"], values)
        if not job["public_token"]:
            add_activity(job["id"], "shared", user["id"])
        touch(job["id"], "shared")
    return {"public_token": tok, "url": public_url(tok)}


def unshare(user: dict, job: dict) -> None:
    with db.transaction():
        db.update("jobs", job["id"], {"public_token": None})
        add_activity(job["id"], "unshared", user["id"])
        touch(job["id"], "shared")


def customer_decision(job: dict, decision: str, name: str | None, comment: str | None) -> None:
    """The customer approved the proof or asked for changes on the public page."""
    name = (name or "").strip()[:120] or "Customer"
    comment = (comment or "").strip()[:4000] or None
    status = "approved" if decision == "approve" else "changes_requested"
    stamp = now_iso()
    with db.transaction():
        db.update("jobs", job["id"], {"proof_status": status, "proof_decided_at": stamp, "proof_decided_by": name})
        add_activity(job["id"], "proof_approved" if status == "approved" else "changes_requested", None,
                     {"name": name, "comment": comment})
        people = set(assignees(job["id"])) | ({job["created_by"]} if job["created_by"] else set())
        title = (f"{name} approved the proof for {job['number']}" if status == "approved"
                 else f"{name} requested changes on {job['number']}")
        notify.notify(people, "job", title, body=comment or job["title"], link=link(job["id"]),
                      entity_type="job", entity_id=job["id"])
        touch(job["id"], "proof")
        hooks.fire("job.proof_approved" if status == "approved" else "job.changes_requested",
                   {"job_id": job["id"], "name": name, "comment": comment})


def public_proofs(job: dict) -> list[dict]:
    rows = db.query(
        "SELECT a.* FROM job_proofs p JOIN attachments a ON a.id = p.attachment_id WHERE p.job_id = ? ORDER BY a.id",
        job["id"],
    )
    return [{"filename": a["filename"], "url": files.public_url(a), "is_image": files.is_image(a),
             "size": a["size"]} for a in rows]


# -- conversations ------------------------------------------------------------------


def _link_conversation(user: dict, job_id: int, conv: dict) -> bool:
    cur = db.execute("INSERT OR IGNORE INTO job_conversations (job_id, conversation_id, created_at) VALUES (?, ?, ?)",
                     job_id, conv["id"], now_iso())
    if not cur.rowcount:
        return False
    job = get(job_id)
    by = user["id"] if user else None
    add_activity(job_id, "conversation_linked", by, {"conversation_id": conv["id"], "subject": conv["subject"]})
    inbox.add_event(conv["id"], "job_linked", by, {"job_id": job_id, "number": job["number"], "title": job["title"]})
    inbox.touch(conv["id"], "job")
    return True


def link_conversation(user: dict, job: dict, conversation_id: int) -> bool:
    conv = inbox.get_for(user, conversation_id)
    with db.transaction():
        linked = _link_conversation(user, job["id"], conv)
        if linked and not job["contact_id"] and conv["contact_id"]:
            contact = contacts_svc.get(conv["contact_id"])
            db.update("jobs", job["id"], {"contact_id": conv["contact_id"],
                                          "organization_id": job["organization_id"] or (contact or {}).get("organization_id")})
            reindex(job["id"])
        touch(job["id"], "conversation")
    return linked


def unlink_conversation(user: dict, job: dict, conversation_id: int) -> None:
    with db.transaction():
        cur = db.execute("DELETE FROM job_conversations WHERE job_id = ? AND conversation_id = ?", job["id"], conversation_id)
        if cur.rowcount:
            add_activity(job["id"], "conversation_unlinked", user["id"], {"conversation_id": conversation_id})
            conv = inbox.get(conversation_id)
            if conv:
                inbox.add_event(conversation_id, "job_unlinked", user["id"], {"job_id": job["id"], "number": job["number"]})
                inbox.touch(conversation_id, "job")
        touch(job["id"], "conversation")


def for_conversation(user: dict, conversation_id: int) -> dict:
    conv = inbox.get_for(user, conversation_id)
    linked = db.query(
        "SELECT j.* FROM job_conversations jc JOIN jobs j ON j.id = jc.job_id WHERE jc.conversation_id = ? "
        "ORDER BY j.archived_at IS NOT NULL, j.created_at DESC", conversation_id,
    )
    linked_ids = {j["id"] for j in linked}
    others = []
    if conv["contact_id"]:
        others = [j for j in db.query(
            "SELECT * FROM jobs WHERE contact_id = ? AND archived_at IS NULL ORDER BY created_at DESC LIMIT 8",
            conv["contact_id"],
        ) if j["id"] not in linked_ids]
    return {"jobs": summaries(linked), "customer_jobs": summaries(others)}


# -- operations ---------------------------------------------------------------------


def get_operation(op_id: int) -> dict:
    op = db.one("SELECT * FROM job_operations WHERE id = ?", op_id)
    if not op:
        not_found("Operation not found")
    return op


def _op_fields(data: dict) -> dict:
    out = {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            bad_request("Give the step a name")
        out["name"] = name[:120]
    for key, table in (("resource_id", "resources"), ("user_id", "users"), ("skill_id", "skills")):
        if key in data:
            value = _num(data[key], key, int)
            if value and not db.one(f"SELECT id FROM {table} WHERE id = ?", value):
                bad_request(f"No such {key.replace('_id', '')}")
            out[key] = value
    if "duration_minutes" in data:
        dur = _num(data["duration_minutes"], "duration_minutes", int)
        if dur is None or dur < 5 or dur > 60 * 24 * 14:
            bad_request("Duration must be between 5 minutes and two weeks")
        out["duration_minutes"] = dur
    if "notes" in data:
        out["notes"] = (data.get("notes") or "").strip()[:2000] or None
    return out


def add_operation(user: dict, job: dict, data: dict) -> dict:
    values = _op_fields({"name": data.get("name"), **{k: v for k, v in data.items() if k != "name"}})
    values.setdefault("duration_minutes", 60)
    with db.transaction():
        seq = (db.scalar("SELECT MAX(sequence) FROM job_operations WHERE job_id = ?", job["id"]) or 0) + 1
        values.update({"job_id": job["id"], "sequence": seq, "status": "pending", "created_at": now_iso()})
        op_id = db.insert("job_operations", values)
        if data.get("start_at"):
            _schedule(op_id, data.get("start_at"), data.get("end_at"))
        touch(job["id"], "operations", schedule=True)
    return serialize_operation(get_operation(op_id))


def _schedule(op_id: int, start_at, end_at=None) -> None:
    op = get_operation(op_id)
    if start_at in (None, ""):
        db.update("job_operations", op_id, {"start_at": None, "end_at": None})
        return
    start = parse_iso(start_at)
    if not start:
        bad_request("Start time isn't valid")
    if end_at:
        end = parse_iso(end_at)
        if not end or end <= start:
            bad_request("End must be after start")
        minutes = int(round((end - start).total_seconds() / 60))
        db.update("job_operations", op_id, {"start_at": iso(start), "end_at": iso(end), "duration_minutes": max(5, minutes)})
    else:
        end = start + timedelta(minutes=op["duration_minutes"] or 60)
        db.update("job_operations", op_id, {"start_at": iso(start), "end_at": iso(end)})


def can_work_operation(user: dict, op: dict) -> bool:
    """Floor staff may start/finish steps assigned to them or on jobs they're on."""
    if can(user, "manage_jobs"):
        return True
    return op["user_id"] == user["id"] or user["id"] in assignees(op["job_id"])


def update_operation(user: dict, op: dict, data: dict) -> dict:
    manager = can(user, "manage_jobs")
    status_only = set(data) <= {"status", "notes"}
    if not manager and not (status_only and can_work_operation(user, op)):
        forbidden("Only schedulers can change this step")
    values = _op_fields(data) if manager else ({"notes": _op_fields(data)["notes"]} if "notes" in data else {})
    job = get(op["job_id"])
    with db.transaction():
        if values:
            db.update("job_operations", op["id"], values)
        reschedule = manager and ("start_at" in data or "end_at" in data or "duration_minutes" in data)
        if reschedule:
            current = get_operation(op["id"])
            start = data.get("start_at", current["start_at"]) if "start_at" in data else current["start_at"]
            end = data.get("end_at") if "end_at" in data else (None if "duration_minutes" in data or "start_at" in data else current["end_at"])
            _schedule(op["id"], start, end)
            fresh = get_operation(op["id"])
            if fresh["start_at"] != op["start_at"] or fresh["end_at"] != op["end_at"]:
                add_activity(op["job_id"], "operation_scheduled" if fresh["start_at"] else "operation_unscheduled",
                             user["id"], {"operation_id": op["id"], "name": fresh["name"], "start_at": fresh["start_at"],
                                          "end_at": fresh["end_at"], "resource_id": fresh["resource_id"],
                                          "user_id": fresh["user_id"]})
        if "user_id" in values and values["user_id"] and values["user_id"] != op["user_id"] and values["user_id"] != user["id"]:
            fresh = get_operation(op["id"])
            when = ""
            if fresh["start_at"]:
                when = " · " + parse_iso(fresh["start_at"]).astimezone(settings.timezone()).strftime("%a %-I:%M %p")
            notify.notify([values["user_id"]], "assigned", f"{user['name']} assigned you “{fresh['name']}” on {job['number']}",
                          body=f"{job['title']}{when}", link=link(job["id"]), actor_id=user["id"], entity_type="job",
                          entity_id=job["id"])
        if "status" in data:
            status = data["status"]
            if status not in OP_STATUSES:
                bad_request("Status must be pending, in_progress or done")
            if status != op["status"]:
                stamp = now_iso()
                change = {"status": status}
                if status == "in_progress":
                    change.update({"started_at": op["started_at"] or stamp, "started_by": op["started_by"] or user["id"],
                                   "completed_at": None, "completed_by": None})
                elif status == "done":
                    change.update({"completed_at": stamp, "completed_by": user["id"],
                                   "started_at": op["started_at"] or stamp, "started_by": op["started_by"] or user["id"]})
                else:
                    change.update({"started_at": None, "started_by": None, "completed_at": None, "completed_by": None})
                db.update("job_operations", op["id"], change)
                add_activity(op["job_id"], {"in_progress": "operation_started", "done": "operation_done"}.get(status, "operation_reset"),
                             user["id"], {"operation_id": op["id"], "name": op["name"]})
                hooks.fire("job.operation_status", {"job_id": op["job_id"], "operation_id": op["id"], "status": status,
                                                     "by": user["id"]})
        db.update("jobs", op["job_id"], {"updated_at": now_iso()})
        touch(op["job_id"], "operations", schedule=True)
    return serialize_operation(get_operation(op["id"]))


def delete_operation(user: dict, op: dict) -> None:
    with db.transaction():
        db.delete("job_operations", op["id"])
        add_activity(op["job_id"], "operation_removed", user["id"], {"name": op["name"]})
        touch(op["job_id"], "operations", schedule=True)


def reorder_operations(job: dict, ids) -> list[dict]:
    ids = [int(i) for i in ids or []]
    existing = set(db.column("SELECT id FROM job_operations WHERE job_id = ?", job["id"]))
    if set(ids) != existing:
        bad_request("Send every step of this job, in the new order")
    with db.transaction():
        for i, op_id in enumerate(ids, start=1):
            db.update("job_operations", op_id, {"sequence": i})
        touch(job["id"], "operations", schedule=True)
    return operations(job["id"])


# -- due alerts (worker) --------------------------------------------------------------


def notify_due(current=None) -> int:
    """Tell assignees once when a job becomes due soon, and once when it's overdue.
    A changed due date gets fresh alerts."""
    current = current or now()
    soon = current + timedelta(hours=float(settings.get("jobs.due_soon_hours") or 24))
    done = done_stage_ids()
    rows = db.query(
        f"SELECT * FROM jobs WHERE archived_at IS NULL AND due_at IS NOT NULL AND due_at < ? "
        f"AND (stage_id IS NULL OR stage_id NOT IN ({db.placeholders(done)}))",
        [iso(soon), *done],
    )
    sent = 0
    for job in rows:
        kind = "overdue" if parse_iso(job["due_at"]) < current else "due_soon"
        already = db.one(
            "SELECT 1 AS seen FROM job_activity WHERE job_id = ? AND type = ? AND json_extract(data_json, '$.due_at') = ?",
            job["id"], kind, job["due_at"],
        )
        if already:
            continue
        with db.transaction():
            add_activity(job["id"], kind, None, {"due_at": job["due_at"]})
            people = assignees(job["id"])
            title = (f"Overdue: {job['number']} {job['title']}" if kind == "overdue"
                     else f"Due soon: {job['number']} {job['title']}")
            notify.notify(people, "job", title, body=_due_text(job), link=link(job["id"]), entity_type="job",
                          entity_id=job["id"])
            badge_refresh(people)
            touch(job["id"], kind)
        sent += 1
    return sent


def badge_count(user: dict) -> int:
    done = done_stage_ids()
    soon = iso(now() + timedelta(hours=float(settings.get("jobs.due_soon_hours") or 24)))
    return db.scalar(
        f"SELECT COUNT(*) FROM jobs j JOIN job_assignees a ON a.job_id = j.id WHERE a.user_id = ? "
        f"AND j.archived_at IS NULL AND j.due_at IS NOT NULL AND j.due_at < ? "
        f"AND (j.stage_id IS NULL OR j.stage_id NOT IN ({db.placeholders(done)}))",
        [user["id"], soon, *done],
    ) or 0
