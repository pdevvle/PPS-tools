"""Jobs API: stages, spec fields, equipment, templates, jobs, operations, the
production schedule, and the customer-facing proof page."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, redirect, render_template_string, request

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.services import files, inbox, settings
from pps_tools.switchboard.services import jobs as jobs_svc
from pps_tools.switchboard.services import scheduling
from pps_tools.switchboard.services import search as search_svc
from pps_tools.switchboard.util import iso, now, now_iso, parse_iso, pick_color
from pps_tools.switchboard.web import (
    ApiError, as_bool, as_int, audit, bad_request, body, can, current_user, forbidden, login_required, not_found, ok,
    require, require_fields,
)
from pps_tools.switchboard.worker import Task

bp = Blueprint("jobs", __name__)


def _changed(what: str) -> None:
    realtime.emit("settings.changed", {"what": what})
    realtime.emit("job.changed", {"id": None, "reason": what})


def _reorder(table: str, ids) -> None:
    ids = [int(i) for i in ids or []]
    existing = set(db.column(f"SELECT id FROM {table}"))
    if not ids or not set(ids) <= existing:
        bad_request("Send the ids in their new order")
    for i, row_id in enumerate(ids):
        db.update(table, row_id, {"position": i})


# -- stages -------------------------------------------------------------------------


def _stage_values(data: dict, partial: bool) -> dict:
    out = {}
    if "name" in data or not partial:
        name = (data.get("name") or "").strip()
        if not name:
            bad_request("Stage name is required")
        out["name"] = name[:60]
    if "color" in data:
        out["color"] = data["color"] or None
    if "is_done" in data:
        out["is_done"] = 1 if as_bool(data["is_done"]) else 0
    if "wip_limit" in data:
        limit = as_int(data["wip_limit"], "wip_limit")
        out["wip_limit"] = limit if limit and limit > 0 else None
    return out


@bp.get("/api/job-stages")
@login_required
def list_stages():
    return ok({"items": jobs_svc.stages()})


@bp.post("/api/job-stages")
@require("manage_jobs")
def create_stage():
    values = _stage_values(body(), partial=False)
    with db.transaction():
        values.setdefault("color", pick_color(values["name"]))
        values["position"] = (db.scalar("SELECT MAX(position) FROM job_stages") or 0) + 1
        values["created_at"] = now_iso()
        sid = db.insert("job_stages", values)
        _changed("job_stages")
    return ok({"stage": jobs_svc.stage(sid)}, 201)


@bp.patch("/api/job-stages/<int:sid>")
@require("manage_jobs")
def update_stage(sid: int):
    if not jobs_svc.stage(sid):
        not_found("Stage not found")
    with db.transaction():
        db.update("job_stages", sid, _stage_values(body(), partial=True))
        _changed("job_stages")
    return ok({"stage": jobs_svc.stage(sid)})


@bp.delete("/api/job-stages/<int:sid>")
@require("manage_jobs")
def delete_stage(sid: int):
    if not jobs_svc.stage(sid):
        not_found("Stage not found")
    if db.scalar("SELECT COUNT(*) FROM job_stages") <= 1:
        bad_request("Keep at least one stage")
    in_use = db.scalar("SELECT COUNT(*) FROM jobs WHERE stage_id = ?", sid)
    move_to = as_int(request.args.get("move_to") or body().get("move_to"), "move_to")
    if in_use and not (move_to and move_to != sid and jobs_svc.stage(move_to)):
        bad_request(f"{in_use} job(s) are in this stage — choose a stage to move them to", code="stage_in_use",
                    count=in_use)
    with db.transaction():
        if in_use:
            db.execute("UPDATE jobs SET stage_id = ?, stage_entered_at = ? WHERE stage_id = ?", move_to, now_iso(), sid)
        db.delete("job_stages", sid)
        _changed("job_stages")
    return ok()


@bp.post("/api/job-stages/reorder")
@require("manage_jobs")
def reorder_stages():
    with db.transaction():
        _reorder("job_stages", body().get("ids"))
        _changed("job_stages")
    return ok({"items": jobs_svc.stages()})


# -- spec fields --------------------------------------------------------------------


def _field_values(data: dict, partial: bool) -> dict:
    out = {}
    if "label" in data or not partial:
        label = (data.get("label") or "").strip()
        if not label:
            bad_request("Field label is required")
        out["label"] = label[:60]
    if "type" in data or not partial:
        kind = data.get("type") or "text"
        if kind not in jobs_svc.FIELD_TYPES:
            bad_request("Unknown field type")
        out["type"] = kind
    if "options" in data:
        opts = data["options"]
        if isinstance(opts, str):
            opts = [o for o in opts.split("\n")]
        out["options_json"] = db.jdump([str(o).strip()[:80] for o in opts or [] if str(o).strip()][:50])
    return out


def _field_key(label: str) -> str:
    import re

    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40] or "field"
    key, n = base, 2
    while db.one("SELECT 1 AS taken FROM job_fields WHERE key = ?", key):
        key, n = f"{base}_{n}", n + 1
    return key


@bp.get("/api/job-fields")
@login_required
def list_fields():
    return ok({"items": jobs_svc.fields()})


@bp.post("/api/job-fields")
@require("manage_jobs")
def create_field():
    data = body()
    values = _field_values(data, partial=False)
    with db.transaction():
        values["key"] = _field_key(data.get("key") or values["label"])
        values["position"] = (db.scalar("SELECT MAX(position) FROM job_fields") or 0) + 1
        values["created_at"] = now_iso()
        fid = db.insert("job_fields", values)
        _changed("job_fields")
    return ok({"field": next(f for f in jobs_svc.fields() if f["id"] == fid)}, 201)


@bp.patch("/api/job-fields/<int:fid>")
@require("manage_jobs")
def update_field(fid: int):
    if not db.one("SELECT id FROM job_fields WHERE id = ?", fid):
        not_found("Field not found")
    with db.transaction():
        db.update("job_fields", fid, _field_values(body(), partial=True))
        _changed("job_fields")
    return ok({"field": next(f for f in jobs_svc.fields() if f["id"] == fid)})


@bp.delete("/api/job-fields/<int:fid>")
@require("manage_jobs")
def delete_field(fid: int):
    with db.transaction():
        db.delete("job_fields", fid)
        _changed("job_fields")
    return ok()


@bp.post("/api/job-fields/reorder")
@require("manage_jobs")
def reorder_fields():
    with db.transaction():
        _reorder("job_fields", body().get("ids"))
        _changed("job_fields")
    return ok({"items": jobs_svc.fields()})


# -- equipment ----------------------------------------------------------------------


def _resource_values(data: dict, partial: bool) -> dict:
    out = {}
    if "name" in data or not partial:
        name = (data.get("name") or "").strip()
        if not name:
            bad_request("Equipment needs a name")
        out["name"] = name[:80]
    for f in ("kind", "color", "notes"):
        if f in data:
            value = data[f]
            out[f] = (value.strip()[:500] or None) if isinstance(value, str) else value
    if "location_id" in data:
        lid = as_int(data["location_id"], "location_id")
        if lid and not db.one("SELECT id FROM locations WHERE id = ?", lid):
            bad_request("No such location")
        out["location_id"] = lid
    if "hourly_cost" in data:
        value = data["hourly_cost"]
        try:
            out["hourly_cost"] = None if value in (None, "") else float(value)
        except (TypeError, ValueError):
            bad_request("Hourly cost must be a number")
    if "is_active" in data:
        out["is_active"] = 1 if as_bool(data["is_active"]) else 0
    return out


@bp.get("/api/resources")
@login_required
def list_resources():
    return ok({"items": jobs_svc.resources()})


@bp.post("/api/resources")
@require("manage_jobs")
def create_resource():
    values = _resource_values(body(), partial=False)
    with db.transaction():
        values.setdefault("color", pick_color(values["name"]))
        values["position"] = (db.scalar("SELECT MAX(position) FROM resources") or 0) + 1
        values["created_at"] = now_iso()
        rid = db.insert("resources", values)
        _changed("resources")
    return ok({"resource": next(r for r in jobs_svc.resources() if r["id"] == rid)}, 201)


@bp.patch("/api/resources/<int:rid>")
@require("manage_jobs")
def update_resource(rid: int):
    if not db.one("SELECT id FROM resources WHERE id = ?", rid):
        not_found("Equipment not found")
    with db.transaction():
        db.update("resources", rid, _resource_values(body(), partial=True))
        _changed("resources")
    return ok({"resource": next(r for r in jobs_svc.resources() if r["id"] == rid)})


@bp.delete("/api/resources/<int:rid>")
@require("manage_jobs")
def delete_resource(rid: int):
    with db.transaction():
        db.delete("resources", rid)
        _changed("resources")
    return ok()


@bp.post("/api/resources/reorder")
@require("manage_jobs")
def reorder_resources():
    with db.transaction():
        _reorder("resources", body().get("ids"))
        _changed("resources")
    return ok({"items": jobs_svc.resources()})


# -- templates ----------------------------------------------------------------------


def _template_values(data: dict, partial: bool) -> dict:
    out = {}
    if "name" in data or not partial:
        name = (data.get("name") or "").strip()
        if not name:
            bad_request("Template name is required")
        out["name"] = name[:80]
    if "description" in data:
        out["description"] = (data.get("description") or "").strip()[:2000] or None
    if "operations" in data:
        ops = []
        for op in data.get("operations") or []:
            if not isinstance(op, dict) or not (op.get("name") or "").strip():
                continue
            ops.append({
                "name": op["name"].strip()[:120],
                "resource_id": as_int(op.get("resource_id"), "resource_id"),
                "skill_id": as_int(op.get("skill_id"), "skill_id"),
                "duration_minutes": max(5, as_int(op.get("duration_minutes"), "duration_minutes") or 60),
            })
        out["operations_json"] = db.jdump(ops)
    if "checklist" in data:
        items = [str(i if isinstance(i, str) else (i or {}).get("title") or "").strip()[:300] for i in data.get("checklist") or []]
        out["checklist_json"] = db.jdump([i for i in items if i])
    if "specs" in data:
        out["specs_json"] = db.jdump(jobs_svc._clean_specs(data.get("specs")))
    return out


@bp.get("/api/job-templates")
@login_required
def list_templates():
    return ok({"items": jobs_svc.templates()})


@bp.get("/api/job-templates/<int:tid>")
@login_required
def get_template(tid: int):
    t = db.one("SELECT * FROM job_templates WHERE id = ?", tid)
    if not t:
        not_found("Template not found")
    return ok({"template": jobs_svc.serialize_template(t)})


@bp.post("/api/job-templates")
@require("manage_jobs")
def create_template():
    data = body()
    with db.transaction():
        if data.get("from_job_id"):
            job = jobs_svc.get_or_404(int(data["from_job_id"]))
            ops = jobs_svc.operations(job["id"])
            data = {
                "name": data.get("name") or job["title"],
                "description": data.get("description"),
                "operations": [{"name": o["name"], "resource_id": o["resource_id"], "skill_id": o["skill_id"],
                                "duration_minutes": o["duration_minutes"]} for o in ops],
                "checklist": [c["title"] for c in jobs_svc.checklist_items(job["id"])],
                "specs": db.jload(job["specs_json"], {}),
            }
        values = _template_values(data, partial=False)
        values.setdefault("operations_json", "[]")
        values.setdefault("checklist_json", "[]")
        values.setdefault("specs_json", "{}")
        values["created_at"] = values["updated_at"] = now_iso()
        tid = db.insert("job_templates", values)
        _changed("job_templates")
    return ok({"template": jobs_svc.serialize_template(db.one("SELECT * FROM job_templates WHERE id = ?", tid))}, 201)


@bp.patch("/api/job-templates/<int:tid>")
@require("manage_jobs")
def update_template(tid: int):
    if not db.one("SELECT id FROM job_templates WHERE id = ?", tid):
        not_found("Template not found")
    values = _template_values(body(), partial=True)
    values["updated_at"] = now_iso()
    with db.transaction():
        db.update("job_templates", tid, values)
        _changed("job_templates")
    return ok({"template": jobs_svc.serialize_template(db.one("SELECT * FROM job_templates WHERE id = ?", tid))})


@bp.delete("/api/job-templates/<int:tid>")
@require("manage_jobs")
def delete_template(tid: int):
    with db.transaction():
        db.delete("job_templates", tid)
        _changed("job_templates")
    return ok()


# -- jobs ---------------------------------------------------------------------------

SORTS = {
    "due": "j.due_at IS NULL, j.due_at", "number": "j.id", "created": "j.created_at", "updated": "j.updated_at",
    "title": "j.title COLLATE NOCASE", "priority": "CASE j.priority WHEN 'rush' THEN 0 WHEN 'high' THEN 1 "
                                                   "WHEN 'normal' THEN 2 ELSE 3 END",
    "stage": "(SELECT position FROM job_stages WHERE id = j.stage_id)",
}


def _filters(args, user) -> tuple[list[str], list]:
    where, params = [], []
    if as_bool(args.get("archived")):
        where.append("j.archived_at IS NOT NULL")
    elif not as_bool(args.get("include_archived")):
        where.append("j.archived_at IS NULL")
    if args.get("stage_id"):
        where.append("j.stage_id = ?")
        params.append(as_int(args.get("stage_id"), "stage_id"))
    done = jobs_svc.done_stage_ids()
    if args.get("done") in ("0", "false") and done:
        where.append(f"(j.stage_id IS NULL OR j.stage_id NOT IN ({db.placeholders(done)}))")
        params += done
    elif args.get("done") in ("1", "true"):
        where.append(f"j.stage_id IN ({db.placeholders(done)})")
        params += done
    assignee = as_int(args.get("assignee_id"), "assignee_id")
    if as_bool(args.get("mine")):
        assignee = user["id"]
    if assignee:
        where.append("(EXISTS (SELECT 1 FROM job_assignees a WHERE a.job_id = j.id AND a.user_id = ?) "
                     "OR EXISTS (SELECT 1 FROM job_operations o WHERE o.job_id = j.id AND o.user_id = ?))")
        params += [assignee, assignee]
    for key in ("contact_id", "organization_id"):
        if args.get(key):
            where.append(f"j.{key} = ?")
            params.append(as_int(args.get(key), key))
    if args.get("priority"):
        prios = [p for p in str(args.get("priority")).split(",") if p in jobs_svc.PRIORITIES]
        if prios:
            where.append(f"j.priority IN ({db.placeholders(prios)})")
            params += prios
    if args.get("due_from"):
        where.append("j.due_at >= ?")
        params.append(iso(parse_iso(args["due_from"])) if parse_iso(args["due_from"]) else args["due_from"])
    if args.get("due_to"):
        where.append("j.due_at < ?")
        params.append(iso(parse_iso(args["due_to"])) if parse_iso(args["due_to"]) else args["due_to"])
    if args.get("due") == "overdue":
        where.append("j.due_at < ?")
        params.append(now_iso())
    elif args.get("due") == "week":
        where.append("j.due_at < ?")
        params.append(iso(now() + timedelta(days=7)))
    q = (args.get("q") or "").strip()
    if q:
        ids = [r["ref_id"] for r in search_svc.search(["job"], q, 500)]
        like = f"%{q}%"
        clause = "(j.number LIKE ? OR j.title LIKE ? OR j.po_number LIKE ?"
        params_q = [like, like, like]
        if ids:
            clause += f" OR j.id IN ({db.placeholders(ids)})"
            params_q += ids
        where.append(clause + ")")
        params += params_q
    return where, params


@bp.get("/api/jobs")
@login_required
def list_jobs():
    args = request.args
    where, params = _filters(args, current_user())
    sort = SORTS.get(args.get("sort") or "due", SORTS["due"])
    direction = "DESC" if args.get("dir") == "desc" else "ASC"
    limit = min(as_int(args.get("limit"), "limit") or 200, 500)
    offset = as_int(args.get("offset"), "offset") or 0
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.scalar(f"SELECT COUNT(*) FROM jobs j {clause}", params)
    rows = db.query(f"SELECT j.* FROM jobs j {clause} ORDER BY {sort} {direction}, j.id DESC LIMIT ? OFFSET ?",
                    [*params, limit, offset])
    return ok({"items": jobs_svc.summaries(rows), "total": total})


@bp.get("/api/jobs/board")
@login_required
def board():
    args = request.args
    where, params = _filters(args, current_user())
    done_days = as_int(args.get("done_days"), "done_days") or 14
    done = jobs_svc.done_stage_ids()
    if done:
        where.append(f"(j.stage_id NOT IN ({db.placeholders(done)}) OR j.completed_at IS NULL OR j.completed_at >= ?)")
        params += [*done, iso(now() - timedelta(days=done_days))]
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.query(f"SELECT j.* FROM jobs j {clause} ORDER BY j.position, j.id", params)
    items = jobs_svc.summaries(rows)
    counts = {r["stage_id"]: r["n"] for r in db.query(
        "SELECT stage_id, COUNT(*) AS n FROM jobs WHERE archived_at IS NULL GROUP BY stage_id")}
    stages = []
    for st in jobs_svc.stages():
        col = [j for j in items if j["stage_id"] == st["id"]]
        total = counts.get(st["id"], 0)
        stages.append({**st, "jobs": col, "count": total,
                       "over_wip": bool(st["wip_limit"] and total > st["wip_limit"])})
    orphans = [j for j in items if j["stage_id"] not in {s["id"] for s in stages}]
    return ok({"stages": stages, "unstaged": orphans, "done_days": done_days})


@bp.post("/api/jobs")
@require("manage_jobs")
def create_job():
    job = jobs_svc.create(current_user(), body())
    return ok({"job": jobs_svc.summary(job)}, 201)


@bp.get("/api/jobs/<int:job_id>")
@login_required
def get_job(job_id: int):
    from pps_tools.switchboard.services import notify

    data = jobs_svc.detail(current_user(), job_id)
    with db.transaction():
        notify.mark_entity_read(current_user()["id"], "job", job_id)
    return ok(data)


@bp.patch("/api/jobs/<int:job_id>")
@require("manage_jobs")
def update_job(job_id: int):
    job = jobs_svc.update(current_user(), jobs_svc.get_or_404(job_id), body())
    return ok({"job": jobs_svc.summary(job)})


@bp.post("/api/jobs/<int:job_id>/move")
@require("manage_jobs")
def move_job(job_id: int):
    data = body()
    require_fields(data, "stage_id")
    job = jobs_svc.move(current_user(), jobs_svc.get_or_404(job_id), as_int(data["stage_id"], "stage_id"),
                        as_int(data.get("position"), "position"))
    out = jobs_svc.summary(job)
    out["wip_exceeded"] = job.get("wip_exceeded", False)
    return ok({"job": out})


@bp.post("/api/jobs/<int:job_id>/archive")
@require("manage_jobs")
def archive_job(job_id: int):
    archived = as_bool(body().get("archived", True))
    return ok({"job": jobs_svc.summary(jobs_svc.archive(current_user(), jobs_svc.get_or_404(job_id), archived))})


@bp.delete("/api/jobs/<int:job_id>")
@require("admin")
def delete_job(job_id: int):
    job = jobs_svc.get_or_404(job_id)
    jobs_svc.delete(job)
    audit("job.delete", "job", job_id, {"number": job["number"]})
    return ok()


def _on_job(user: dict, job_id: int) -> bool:
    return user["id"] in jobs_svc.assignees(job_id) or bool(db.one(
        "SELECT 1 AS yes FROM job_operations WHERE job_id = ? AND user_id = ?", job_id, user["id"]))


# checklist


@bp.post("/api/jobs/<int:job_id>/checklist")
@require("manage_jobs")
def add_check(job_id: int):
    item = jobs_svc.add_check(current_user(), jobs_svc.get_or_404(job_id), body().get("title"))
    item["is_done"] = bool(item["is_done"])
    return ok({"item": item}, 201)


@bp.patch("/api/job-checklist/<int:item_id>")
@login_required
def update_check(item_id: int):
    item = db.one("SELECT * FROM job_checklist WHERE id = ?", item_id)
    if not item:
        not_found("Checklist item not found")
    user = current_user()
    data = body()
    if not can(user, "manage_jobs"):
        if set(data) - {"is_done"} or not _on_job(user, item["job_id"]):
            forbidden("You can tick items on jobs you're working on")
    item = jobs_svc.update_check(user, item, data)
    item["is_done"] = bool(item["is_done"])
    return ok({"item": item})


@bp.delete("/api/job-checklist/<int:item_id>")
@require("manage_jobs")
def delete_check(item_id: int):
    item = db.one("SELECT * FROM job_checklist WHERE id = ?", item_id)
    if not item:
        not_found("Checklist item not found")
    jobs_svc.delete_check(item)
    return ok()


# comments


@bp.post("/api/jobs/<int:job_id>/comments")
@login_required
def add_comment(job_id: int):
    row = jobs_svc.add_comment(current_user(), jobs_svc.get_or_404(job_id), body().get("body") or "")
    return ok({"activity": {**row, "data": db.jload(row["data_json"], {})}}, 201)


@bp.patch("/api/job-activity/<int:aid>")
@login_required
def edit_comment(aid: int):
    item = db.one("SELECT * FROM job_activity WHERE id = ?", aid)
    if not item:
        not_found("Comment not found")
    row = jobs_svc.edit_comment(current_user(), item, body().get("body") or "")
    return ok({"activity": {**row, "data": db.jload(row["data_json"], {})}})


@bp.delete("/api/job-activity/<int:aid>")
@login_required
def delete_comment(aid: int):
    item = db.one("SELECT * FROM job_activity WHERE id = ?", aid)
    if not item:
        not_found("Comment not found")
    jobs_svc.delete_comment(current_user(), item)
    return ok()


# files & proofs


@bp.post("/api/jobs/<int:job_id>/files")
@login_required
def add_files(job_id: int):
    user = current_user()
    job = jobs_svc.get_or_404(job_id)
    data = body()
    proof = as_bool(data.get("is_proof"))
    if not can(user, "manage_jobs") and (proof or not _on_job(user, job_id)):
        forbidden("You can add files to jobs you're working on")
    return ok({"files": jobs_svc.add_files(user, job, data.get("attachment_ids"), proof)}, 201)


@bp.patch("/api/jobs/<int:job_id>/files/<int:att_id>")
@require("manage_jobs")
def update_file(job_id: int, att_id: int):
    return ok({"files": jobs_svc.set_proof(current_user(), jobs_svc.get_or_404(job_id), att_id,
                                           as_bool(body().get("is_proof")))})


@bp.delete("/api/jobs/<int:job_id>/files/<int:att_id>")
@login_required
def delete_file(job_id: int, att_id: int):
    user = current_user()
    att = db.one("SELECT * FROM attachments WHERE id = ?", att_id)
    if not can(user, "manage_jobs") and not (att and att["uploaded_by"] == user["id"]):
        forbidden("You can only remove files you added")
    jobs_svc.remove_file(user, jobs_svc.get_or_404(job_id), att_id)
    return ok()


@bp.post("/api/jobs/<int:job_id>/share")
@require("manage_jobs")
def share_job(job_id: int):
    return ok(jobs_svc.share(current_user(), jobs_svc.get_or_404(job_id)))


@bp.delete("/api/jobs/<int:job_id>/share")
@require("manage_jobs")
def unshare_job(job_id: int):
    jobs_svc.unshare(current_user(), jobs_svc.get_or_404(job_id))
    return ok()


# conversations


@bp.post("/api/jobs/<int:job_id>/conversations")
@require("manage_jobs")
def link_conversation(job_id: int):
    data = body()
    require_fields(data, "conversation_id")
    linked = jobs_svc.link_conversation(current_user(), jobs_svc.get_or_404(job_id),
                                        as_int(data["conversation_id"], "conversation_id"))
    return ok({"linked": linked})


@bp.delete("/api/jobs/<int:job_id>/conversations/<int:cid>")
@require("manage_jobs")
def unlink_conversation(job_id: int, cid: int):
    jobs_svc.unlink_conversation(current_user(), jobs_svc.get_or_404(job_id), cid)
    return ok()


@bp.get("/api/conversations/<int:cid>/jobs")
@login_required
def conversation_jobs(cid: int):
    return ok(jobs_svc.for_conversation(current_user(), cid))


# operations


@bp.post("/api/jobs/<int:job_id>/operations")
@require("manage_jobs")
def add_operation(job_id: int):
    data = body()
    require_fields(data, "name")
    return ok({"operation": jobs_svc.add_operation(current_user(), jobs_svc.get_or_404(job_id), data)}, 201)


@bp.post("/api/jobs/<int:job_id>/operations/reorder")
@require("manage_jobs")
def reorder_operations(job_id: int):
    return ok({"items": jobs_svc.reorder_operations(jobs_svc.get_or_404(job_id), body().get("ids"))})


@bp.post("/api/jobs/<int:job_id>/operations/from-template")
@require("manage_jobs")
def operations_from_template(job_id: int):
    job = jobs_svc.get_or_404(job_id)
    tid = as_int(body().get("template_id"), "template_id")
    template = db.one("SELECT * FROM job_templates WHERE id = ?", tid) if tid else None
    if not template:
        bad_request("Choose a template")
    with db.transaction():
        jobs_svc.apply_template(job_id, template)
        jobs_svc.add_activity(job_id, "template_applied", current_user()["id"], {"template": template["name"]})
        jobs_svc.touch(job_id, "operations", schedule=True)
    return ok({"items": jobs_svc.operations(job["id"])})


@bp.patch("/api/operations/<int:op_id>")
@login_required
def update_operation(op_id: int):
    return ok({"operation": jobs_svc.update_operation(current_user(), jobs_svc.get_operation(op_id), body())})


@bp.delete("/api/operations/<int:op_id>")
@require("manage_jobs")
def delete_operation(op_id: int):
    jobs_svc.delete_operation(current_user(), jobs_svc.get_operation(op_id))
    return ok()


# -- schedule -----------------------------------------------------------------------


@bp.get("/api/schedule")
@login_required
def get_schedule():
    args = request.args
    start = args.get("start") or iso(now().replace(hour=0, minute=0, second=0, microsecond=0))
    end = args.get("end")
    if not end and parse_iso(start):
        end = iso(parse_iso(start) + timedelta(days=1))
    group = "user" if args.get("group") == "user" else "resource"
    return ok(scheduling.board(start, end, group))


@bp.post("/api/schedule/auto")
@require("manage_jobs")
def auto_schedule():
    data = body()
    ids = data.get("job_ids")
    if ids is not None and not isinstance(ids, list):
        bad_request("job_ids must be a list")
    return ok(scheduling.auto_schedule(ids, data.get("from"), as_bool(data.get("apply")), current_user()))


# -- customer proof page ------------------------------------------------------------

PUBLIC_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{{ job.number }} · {{ org }}</title>
<style>
:root { --bg:#f3f4f7; --card:#fff; --text:#161b26; --muted:#6b7385; --border:#e2e5eb; --accent:#3b5bdb; --ok:#237a34; --ok-bg:#e8f6eb; --warn:#a05e00; --warn-bg:#fff6dc; }
@media (prefers-color-scheme: dark) { :root { --bg:#0d1016; --card:#161a22; --text:#e8ebf1; --muted:#9aa3b5; --border:#262c37; --accent:#6d8cff; --ok:#69db7c; --ok-bg:rgba(81,207,102,.13); --warn:#ffd43b; --warn-bg:rgba(252,196,25,.13); } }
* { box-sizing: border-box; }
body { margin:0; font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; background:var(--bg); color:var(--text); }
main { max-width:720px; margin:0 auto; padding:24px 16px 48px; }
.brand { font-weight:700; font-size:18px; margin-bottom:16px; }
.card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:20px; margin-bottom:16px; }
h1 { font-size:22px; margin:0 0 4px; letter-spacing:-.01em; }
.muted { color:var(--muted); }
.steps { display:flex; flex-wrap:wrap; gap:6px; margin:14px 0 4px; padding:0; list-style:none; }
.steps li { font-size:12.5px; padding:3px 10px; border-radius:999px; border:1px solid var(--border); color:var(--muted); }
.steps li.done { color:var(--text); }
.steps li.current { background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }
.facts { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin-top:14px; }
.facts div { font-size:13px; } .facts b { display:block; font-size:15px; }
.proof { display:block; margin:12px 0; border:1px solid var(--border); border-radius:10px; overflow:hidden; color:inherit; text-decoration:none; }
.proof img { display:block; width:100%; height:auto; background:#fff; }
.proof .name { padding:10px 12px; font-weight:600; display:flex; justify-content:space-between; gap:8px; }
.banner { padding:12px 14px; border-radius:10px; margin-bottom:16px; font-weight:600; }
.banner.ok { background:var(--ok-bg); color:var(--ok); } .banner.warn { background:var(--warn-bg); color:var(--warn); }
label { display:block; font-size:13px; font-weight:600; margin:12px 0 4px; }
input, textarea { width:100%; font:inherit; padding:10px 12px; border:1px solid var(--border); border-radius:8px; background:var(--card); color:var(--text); }
textarea { min-height:90px; resize:vertical; }
.actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:16px; }
button { font:inherit; font-weight:600; padding:11px 18px; border-radius:8px; border:1px solid var(--border); background:var(--card); color:var(--text); cursor:pointer; }
button.primary { background:var(--ok); border-color:var(--ok); color:#fff; }
@media (prefers-color-scheme: dark) { button.primary { color:#0d1016; } }
footer { text-align:center; font-size:12px; color:var(--muted); margin-top:24px; }
</style></head>
<body><main>
<div class="brand">{{ org }}</div>
{% if done == 'approved' %}<div class="banner ok">Thank you — your approval was sent. We'll take it from here.</div>
{% elif done == 'changes' %}<div class="banner warn">Thanks — we got your notes and will send an updated proof.</div>{% endif %}
{% if error == 'name' %}<div class="banner warn">Please enter your name so we know who approved it.</div>
{% elif error == 'comment' %}<div class="banner warn">Please tell us what you'd like changed.</div>
{% elif error == 'too_many' %}<div class="banner warn">Too many submissions — please try again in a little while.</div>{% endif %}
<section class="card">
  <div class="muted">Job {{ job.number }}</div>
  <h1>{{ job.title }}</h1>
  <ul class="steps">{% for s in stages %}<li class="{{ 'current' if s.id == job.stage_id else ('done' if s.passed else '') }}">{{ s.name }}</li>{% endfor %}</ul>
  <div class="facts">
    <div><span class="muted">Status</span><b>{{ stage_name or 'In progress' }}</b></div>
    {% if due %}<div><span class="muted">Due</span><b>{{ due }}</b></div>{% endif %}
    {% if job.quantity %}<div><span class="muted">Quantity</span><b>{{ '{:,}'.format(job.quantity) }}</b></div>{% endif %}
    {% if proof_status %}<div><span class="muted">Proof</span><b>{{ proof_status }}</b></div>{% endif %}
  </div>
</section>
{% if proofs %}
<section class="card">
  <h2 style="font-size:17px;margin:0 0 4px">Your proof{{ 's' if proofs|length > 1 else '' }}</h2>
  <p class="muted" style="margin:0">Please check spelling, phone numbers, colors and sizes carefully.</p>
  {% for p in proofs %}
  <a class="proof" href="{{ p.url }}" target="_blank" rel="noopener">
    {% if p.is_image %}<img src="{{ p.url }}" alt="{{ p.filename }}">{% endif %}
    <div class="name"><span>{{ p.filename }}</span><span class="muted">Open</span></div>
  </a>
  {% endfor %}
</section>
<section class="card">
  {% if job.proof_status == 'approved' %}<p style="margin:0 0 6px"><b>Approved</b> by {{ job.proof_decided_by }}.</p>
  <p class="muted" style="margin:0">Need another change? Leave a note below.</p>{% endif %}
  <form method="post" action="{{ base }}/changes" id="decide">
    <label for="name">Your name</label>
    <input id="name" name="name" autocomplete="name" required maxlength="120">
    <label for="comment">Notes for our team <span class="muted">(required to request changes)</span></label>
    <textarea id="comment" name="comment" maxlength="4000"></textarea>
    <div class="actions">
      <button class="primary" type="submit" formaction="{{ base }}/approve" onclick="document.getElementById('comment').required=false">Approve proof</button>
      <button type="submit" formaction="{{ base }}/changes" onclick="document.getElementById('comment').required=true">Request changes</button>
    </div>
  </form>
</section>
{% else %}
<section class="card"><p class="muted" style="margin:0">There's no proof to review yet — we'll email you as soon as it's ready.</p></section>
{% endif %}
<footer>Questions? Just reply to our last email. · {{ org }}</footer>
</main></body></html>"""

_decisions: dict[str, list[float]] = {}


def _public_job(tok: str) -> dict:
    job = db.one("SELECT * FROM jobs WHERE public_token = ? AND archived_at IS NULL", tok)
    if not job:
        not_found("This link is no longer active")
    return job


@bp.get("/public/jobs/<tok>")
def public_job(tok: str):
    try:
        job = _public_job(tok)
    except ApiError:
        return "This link is no longer active.", 404
    stages = jobs_svc.stages()
    current = next((s for s in stages if s["id"] == job["stage_id"]), None)
    shown = [s for s in stages if not s["is_done"] or (current and s["id"] == current["id"])]
    passed = True
    for s in shown:
        if current and s["id"] == current["id"]:
            passed = False
        s["passed"] = passed
    due = None
    if job["due_at"]:
        due = parse_iso(job["due_at"]).astimezone(settings.timezone()).strftime("%a, %b %-d")
    status_text = {"pending": "Waiting for your review", "approved": "Approved",
                   "changes_requested": "Changes requested"}.get(job["proof_status"] or "")
    html = render_template_string(
        PUBLIC_PAGE, job=job, org=settings.get("org.name"), stages=shown, stage_name=current["name"] if current else None,
        due=due, proofs=jobs_svc.public_proofs(job), proof_status=status_text, done=request.args.get("done"),
        error=request.args.get("error"),
        base=f"/public/jobs/{tok}",
    )
    return html, 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
                       "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"}


def _decide(tok: str, decision: str):
    import time as _time

    job = _public_job(tok)
    data = body()

    def fail(code: str, message: str, status: int = 400):
        if not request.is_json:  # the HTML form: back to the page with a message
            return redirect(f"/public/jobs/{tok}?error={code}", code=303)
        raise ApiError(status, code, message)

    recent = [t for t in _decisions.get(tok, []) if t > _time.time() - 3600]
    if len(recent) >= 20:
        return fail("too_many", "Too many submissions — please try again later", 429)
    name = (data.get("name") or "").strip()
    comment = (data.get("comment") or "").strip()
    if not name:
        return fail("name", "Please enter your name")
    if decision == "changes" and not comment:
        return fail("comment", "Tell us what to change")
    _decisions[tok] = recent + [_time.time()]
    jobs_svc.customer_decision(job, "approve" if decision == "approve" else "changes", name, comment)
    if request.is_json:
        return ok({"ok": True, "status": "approved" if decision == "approve" else "changes_requested"})
    return redirect(f"/public/jobs/{tok}?done={'approved' if decision == 'approve' else 'changes'}", code=303)


@bp.post("/public/jobs/<tok>/approve")
def public_approve(tok: str):
    return _decide(tok, "approve")


@bp.post("/public/jobs/<tok>/changes")
def public_changes(tok: str):
    return _decide(tok, "changes")


# -- module hooks -------------------------------------------------------------------


files.register_access("job", lambda user, job_id: bool(user and user.get("is_active", 1)))


def bootstrap(user: dict) -> dict:
    return {
        "job_stages": jobs_svc.stages(),
        "job_fields": jobs_svc.fields(),
        "resources": jobs_svc.resources(),
        "job_templates": [{"id": t["id"], "name": t["name"], "description": t["description"]} for t in jobs_svc.templates()],
        "job_skills": jobs_svc.skills(),
        "resource_locations": db.query("SELECT id, name FROM locations WHERE is_active = 1 ORDER BY name COLLATE NOCASE"),
    }


def badges(user: dict) -> dict:
    return {"jobs": jobs_svc.badge_count(user)}


def search(user: dict, q: str, limit: int) -> list[dict]:
    ids = [r["ref_id"] for r in search_svc.search(["job"], q, limit * 2)]
    like = f"{q}%"
    rows = db.query(
        f"SELECT * FROM jobs WHERE archived_at IS NULL AND (number LIKE ? OR id IN ({db.placeholders(ids)})) "
        f"ORDER BY updated_at DESC LIMIT ?",
        [like, *ids, limit],
    )
    stages = {s["id"]: s["name"] for s in jobs_svc.stages()}
    out = []
    for j in jobs_svc.summaries(rows):
        sub = " · ".join(x for x in [j["customer"], stages.get(j["stage_id"])] if x)
        out.append({"type": "job", "id": j["id"], "title": f"{j['number']} · {j['title']}", "subtitle": sub,
                    "url": jobs_svc.link(j["id"]), "icon": "square-kanban", "group": "Jobs"})
    return out


def worker_tasks():
    return [Task("jobs.due_alerts", 300, jobs_svc.notify_due)]


DEFAULT_STAGES = [
    ("Quote", "#868e96", 0), ("Approved", "#1971c2", 0), ("Prepress", "#7048e8", 0), ("Proofing", "#ae3ec9", 0),
    ("Printing", "#e8590c", 0), ("Finishing", "#f08c00", 0), ("Ready for pickup", "#0c8599", 0),
    ("Delivered", "#2f9e44", 1),
]

DEFAULT_FIELDS = [
    ("product", "Product", "text", []),
    ("paper_stock", "Paper stock", "text", []),
    ("finished_size", "Finished size", "text", []),
    ("ink", "Ink", "select", ["4/4", "4/0", "1/1", "1/0"]),
    ("finishing", "Finishing", "text", []),
    ("proof_required", "Proof required", "checkbox", []),
]

DEFAULT_RESOURCES = [
    ("Digital Press 1", "press", "#e8590c"), ("Digital Press 2", "press", "#f08c00"),
    ("Wide Format Printer", "wide format", "#1971c2"), ("Guillotine Cutter", "cutter", "#c2255c"),
    ("Folder", "folder", "#7048e8"), ("Saddle Stitcher", "bindery", "#ae3ec9"), ("Laminator", "finishing", "#0c8599"),
    ("Delivery Van", "vehicle", "#2f9e44"),
]

DEFAULT_SKILLS = ["Prepress", "Digital press", "Wide format", "Bindery", "Cutting", "Delivery"]


def on_setup(ctx: dict) -> None:
    stamp = now_iso()
    for i, (name, color, done) in enumerate(DEFAULT_STAGES):
        db.insert("job_stages", {"name": name, "color": color, "position": i, "is_done": done, "created_at": stamp})
    for i, (key, label, kind, options) in enumerate(DEFAULT_FIELDS):
        db.insert("job_fields", {"key": key, "label": label, "type": kind, "options_json": db.jdump(options),
                                 "position": i, "created_at": stamp})
    res = {}
    for i, (name, kind, color) in enumerate(DEFAULT_RESOURCES):
        res[name] = db.insert("resources", {"name": name, "kind": kind, "color": color, "position": i, "created_at": stamp})
    sk = {name: jobs_svc.ensure_skill(name) for name in DEFAULT_SKILLS}

    def op(name, minutes, resource=None, skill=None):
        return {"name": name, "duration_minutes": minutes, "resource_id": res.get(resource), "skill_id": sk.get(skill)}

    common = ["Files received", "Proof approved", "Stock pulled", "Quality check", "Customer notified"]
    templates = [
        ("Business cards", "500–1,000 cards per name, 16pt stock.",
         [op("Prepress", 30, None, "Prepress"), op("Print", 30, "Digital Press 1", "Digital press"),
          op("Cut", 20, "Guillotine Cutter", "Cutting"), op("Pack", 10, None, "Bindery")],
         common, {"product": "Business cards", "paper_stock": "16pt matte", "finished_size": "3.5 × 2 in", "ink": "4/4",
                  "proof_required": True}),
        ("Trifold brochure", "Letter trifold, 100lb gloss text.",
         [op("Prepress", 45, None, "Prepress"), op("Print", 60, "Digital Press 1", "Digital press"),
          op("Fold", 45, "Folder", "Bindery"), op("Pack", 15, None, "Bindery")],
         common, {"product": "Trifold brochure", "paper_stock": "100lb gloss text", "finished_size": "8.5 × 11 in (folded to 3.67 × 8.5)",
                  "ink": "4/4", "finishing": "Trifold", "proof_required": True}),
        ("Saddle-stitched booklet", "Booklets with cover, folded and stapled.",
         [op("Prepress & imposition", 90, None, "Prepress"), op("Print", 120, "Digital Press 1", "Digital press"),
          op("Fold & stitch", 90, "Saddle Stitcher", "Bindery"), op("Trim", 30, "Guillotine Cutter", "Cutting"),
          op("Pack", 20, None, "Bindery")],
         common, {"product": "Booklet", "paper_stock": "80lb gloss text + 100lb gloss cover", "finished_size": "5.5 × 8.5 in",
                  "ink": "4/4", "finishing": "Saddle stitch", "proof_required": True}),
        ("Vinyl banner", "13oz vinyl with hems and grommets.",
         [op("Prepress", 30, None, "Prepress"), op("Print", 120, "Wide Format Printer", "Wide format"),
          op("Hem & grommet", 60, None, "Bindery"), op("Pack", 15, None, "Bindery")],
         ["Files received", "Proof approved", "Grommet spacing confirmed", "Quality check", "Customer notified"],
         {"product": "Vinyl banner", "paper_stock": "13oz scrim vinyl", "finished_size": "3 × 6 ft", "ink": "4/0",
          "finishing": "Hemmed, grommets every 2 ft", "proof_required": True}),
        ("Menus", "Laminated menus, folded or flat.",
         [op("Prepress", 45, None, "Prepress"), op("Print", 60, "Digital Press 2", "Digital press"),
          op("Laminate", 60, "Laminator", "Bindery"), op("Fold & trim", 30, "Folder", "Cutting"), op("Pack", 10, None, "Bindery")],
         common, {"product": "Menus", "paper_stock": "100lb gloss cover", "finished_size": "11 × 17 in folded", "ink": "4/4",
                  "finishing": "Laminated, half fold", "proof_required": True}),
    ]
    for name, desc, ops, checklist, specs in templates:
        db.insert("job_templates", {"name": name, "description": desc, "operations_json": db.jdump(ops),
                                    "checklist_json": db.jdump(checklist), "specs_json": db.jdump(specs),
                                    "created_at": stamp, "updated_at": stamp})


def seed(ctx) -> None:
    from pps_tools.switchboard.demo.jobs import seed_jobs

    seed_jobs(ctx)
