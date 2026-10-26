"""Tasks API."""

from __future__ import annotations

from flask import Blueprint, request

from pps_tools.switchboard import db
from pps_tools.switchboard.services import tasks as tasks_svc
from pps_tools.switchboard.services import search as search_svc
from pps_tools.switchboard.web import as_bool, as_int, bad_request, body, current_user, login_required, ok
from pps_tools.switchboard.worker import Task

bp = Blueprint("tasks", __name__)


@bp.get("/api/tasks")
@login_required
def list_tasks():
    args = request.args
    view = args.get("view") or "mine"
    if view not in tasks_svc.VIEWS:
        bad_request(f"Unknown view '{view}'")
    items = tasks_svc.list_tasks(
        current_user(), view=view, q=(args.get("q") or "").strip() or None,
        conversation_id=as_int(args.get("conversation_id"), "conversation_id"),
        job_id=as_int(args.get("job_id"), "job_id"),
        assignee_id=as_int(args.get("assignee_id"), "assignee_id"),
        include_done=as_bool(args.get("include_done")),
    )
    return ok({"items": items})


@bp.get("/api/tasks/counts")
@login_required
def task_counts():
    user = current_user()
    clause, params = tasks_svc.visible_clause(user)
    uid = user["id"]
    now = tasks_svc.now_iso()
    row = db.one(
        "SELECT "
        "SUM(CASE WHEN t.assignee_id = ? AND t.status != 'done' THEN 1 ELSE 0 END) AS mine, "
        "SUM(CASE WHEN t.created_by = ? AND t.status != 'done' THEN 1 ELSE 0 END) AS created, "
        "SUM(CASE WHEN t.status != 'done' THEN 1 ELSE 0 END) AS open, "
        "SUM(CASE WHEN t.status != 'done' AND t.due_at IS NOT NULL AND t.due_at < ? THEN 1 ELSE 0 END) AS overdue "
        f"FROM tasks t WHERE {clause}",
        [uid, uid, now, *params],
    )
    return ok({k: row[k] or 0 for k in ("mine", "created", "open", "overdue")})


@bp.post("/api/tasks")
@login_required
def create_task():
    task = tasks_svc.create(current_user(), body())
    return ok({"task": tasks_svc.serialize([task], current_user())[0]}, 201)


@bp.get("/api/tasks/<int:task_id>")
@login_required
def get_task(task_id: int):
    task = tasks_svc.get_for(current_user(), task_id)
    return ok({"task": tasks_svc.serialize([task], current_user())[0]})


@bp.patch("/api/tasks/<int:task_id>")
@login_required
def update_task(task_id: int):
    task = tasks_svc.update(current_user(), task_id, body())
    return ok({"task": tasks_svc.serialize([task], current_user())[0]})


@bp.delete("/api/tasks/<int:task_id>")
@login_required
def delete_task(task_id: int):
    tasks_svc.delete(current_user(), task_id)
    return ok()


@bp.post("/api/tasks/reorder")
@login_required
def reorder_tasks():
    ids = body().get("ids")
    if not isinstance(ids, list) or not ids:
        bad_request("ids must be a non-empty list")
    tasks_svc.reorder(current_user(), ids)
    return ok()


# -- module hooks -------------------------------------------------------------------


def badges(user: dict) -> dict:
    return {"tasks": tasks_svc.badge_count(user["id"])}


def search(user: dict, q: str, limit: int) -> list[dict]:
    items = tasks_svc.list_tasks(user, view="all", q=q, include_done=True, limit=limit)
    return [{
        "type": "task", "id": t["id"], "title": t["title"],
        "subtitle": ("Done" if t["status"] == "done" else ("Due " + tasks_svc.fmt_local(t["due_at"]) if t["due_at"] else "No due date")),
        "url": f"/tasks?task={t['id']}", "icon": "square-check-big", "group": "Tasks",
    } for t in items]


def worker_tasks():
    return [Task("tasks.due", 60, tasks_svc.process_due)]


def seed(ctx) -> None:
    from pps_tools.switchboard.demo.tasks import seed_tasks

    seed_tasks(ctx)


__all__ = ["bp", "search_svc"]
