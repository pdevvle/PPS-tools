"""Tasks: to-dos for one person or a team, optionally tied to a conversation or a job.

Anyone signed in can see tasks, except tasks on conversations they can't see.
Assignees are notified on assignment, an hour before the due time, and once overdue.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, time, timedelta

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.services import inbox, notify, search, settings
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.services.sanitize import sanitize
from pps_tools.switchboard.util import html_to_text, iso, now, now_iso, parse_iso
from pps_tools.switchboard.web import bad_request, forbidden, not_found

STATUSES = ("todo", "in_progress", "done")
PRIORITIES = ("low", "normal", "high", "urgent")
VIEWS = ("mine", "created", "team", "all", "overdue", "done")
MANAGER_ROLES = ("owner", "admin", "manager")


def visible_clause(user: dict) -> tuple[str, list]:
    clause, params = inbox.visibility_clause(user, alias="vc")
    uid = user["id"]
    return (
        "(t.conversation_id IS NULL OR t.assignee_id = ? OR t.created_by = ? OR EXISTS "
        f"(SELECT 1 FROM conversations vc WHERE vc.id = t.conversation_id AND {clause}))",
        [uid, uid, *params],
    )


def fmt_local(value: str) -> str:
    """'Tue Oct 27, 3:00 PM' in the org timezone (portable: no %-d)."""
    dt = parse_iso(value).astimezone(settings.timezone())
    return f"{dt:%a %b} {dt.day}, {dt.hour % 12 or 12}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'}"


def get(task_id: int) -> dict | None:
    return db.one("SELECT * FROM tasks WHERE id = ?", task_id)


def get_for(user: dict, task_id: int) -> dict:
    clause, params = visible_clause(user)
    task = db.one(f"SELECT t.* FROM tasks t WHERE t.id = ? AND {clause}", [task_id, *params])
    if not task:
        not_found("Task not found")
    return task


def end_of_today_iso() -> str:
    tz = settings.timezone()
    today = now().astimezone(tz).date()
    return iso(datetime.combine(today + timedelta(days=1), time(0, 0), tzinfo=tz))


def serialize(rows: list[dict], user: dict | None = None) -> list[dict]:
    if not rows:
        return []
    conv_ids = sorted({r["conversation_id"] for r in rows if r["conversation_id"]})
    convs = {}
    for cid in conv_ids:
        conv = inbox.get(cid)
        if conv and (user is None or inbox.can_view(user, cid)):
            convs[cid] = {"id": cid, "subject": inbox.title_of(conv), "status": conv["status"]}
    job_ids = sorted({r["job_id"] for r in rows if r["job_id"]})
    jobs = {}
    if job_ids:
        try:
            jobs = {j["id"]: j for j in db.query(
                f"SELECT id, number, title FROM jobs WHERE id IN ({db.placeholders(job_ids)})", job_ids)}
        except sqlite3.OperationalError:  # pragma: no cover - jobs schema unavailable
            jobs = {}
    current = now_iso()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "title": r["title"],
            "description": r["description"],
            "status": r["status"],
            "priority": r["priority"],
            "due_at": r["due_at"],
            "overdue": bool(r["due_at"] and r["status"] != "done" and r["due_at"] < current),
            "assignee_id": r["assignee_id"],
            "team_id": r["team_id"],
            "conversation_id": r["conversation_id"],
            "conversation": convs.get(r["conversation_id"]),
            "job_id": r["job_id"],
            "job": jobs.get(r["job_id"]),
            "position": r["position"],
            "created_by": r["created_by"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "completed_at": r["completed_at"],
            "completed_by": r["completed_by"],
        })
    return out


def list_tasks(user: dict, view: str = "mine", q: str | None = None, conversation_id: int | None = None,
               job_id: int | None = None, assignee_id: int | None = None, include_done: bool = False,
               limit: int = 500) -> list[dict]:
    clause, params = visible_clause(user)
    where = [clause]
    uid = user["id"]
    order = "t.position, COALESCE(t.due_at, '9999'), t.id"
    if conversation_id or job_id:
        if conversation_id:
            inbox.get_for(user, conversation_id)
            where.append("t.conversation_id = ?")
            params.append(conversation_id)
        if job_id:
            where.append("t.job_id = ?")
            params.append(job_id)
        include_done = True
        order = "(t.status = 'done'), t.position, COALESCE(t.due_at, '9999'), t.id"
    elif view == "mine":
        where.append("t.assignee_id = ?")
        params.append(uid)
    elif view == "created":
        where.append("t.created_by = ?")
        params.append(uid)
    elif view == "team":
        team_ids = users_svc.team_ids_of(uid)
        if not team_ids:
            return []
        ph = db.placeholders(team_ids)
        where.append(f"(t.team_id IN ({ph}) OR t.assignee_id IN (SELECT user_id FROM team_members WHERE team_id IN ({ph})))")
        params += team_ids + team_ids
    elif view == "overdue":
        where.append("t.due_at IS NOT NULL AND t.due_at < ? AND t.status != 'done'")
        params.append(now_iso())
    elif view == "done":
        where.append("t.status = 'done'")
        order = "t.completed_at DESC, t.id DESC"
        include_done = True
    elif view != "all":
        bad_request(f"Unknown view '{view}'")
    if assignee_id:
        where.append("t.assignee_id = ?")
        params.append(assignee_id)
    if q:
        like = f"%{q}%"
        hits = [r["ref_id"] for r in search.search(["task"], q, 300)]
        cond = "(t.title LIKE ? OR t.description LIKE ?"
        params += [like, like]
        if hits:
            cond += f" OR t.id IN ({db.placeholders(hits)})"
            params += hits
        where.append(cond + ")")
    if not include_done:
        # recently finished tasks stay visible for a day so a check-off doesn't vanish
        where.append("(t.status != 'done' OR t.completed_at >= ?)")
        params.append(iso(now() - timedelta(hours=24)))
    rows = db.query(f"SELECT t.* FROM tasks t WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?", [*params, limit])
    return serialize(rows, user)


def _validate(user: dict, data: dict, partial: bool) -> dict:
    out: dict = {}
    if "title" in data or not partial:
        title = (data.get("title") or "").strip()
        if not title:
            bad_request("Give the task a title", code="validation")
        out["title"] = title[:300]
    if "description" in data:
        desc = sanitize(data.get("description") or "", "basic")
        out["description"] = desc if html_to_text(desc).strip() or "<img" in desc else None
    if "status" in data:
        if data["status"] not in STATUSES:
            bad_request("status must be todo, in_progress or done")
        out["status"] = data["status"]
    if "priority" in data:
        if data["priority"] not in PRIORITIES:
            bad_request("priority must be low, normal, high or urgent")
        out["priority"] = data["priority"]
    if "due_at" in data:
        if data["due_at"] in (None, ""):
            out["due_at"] = None
        else:
            due = parse_iso(data["due_at"])
            if not due:
                bad_request("due_at must be an ISO date-time")
            out["due_at"] = iso(due)
    if "assignee_id" in data:
        aid = data["assignee_id"]
        if aid in (None, ""):
            out["assignee_id"] = None
        else:
            target = users_svc.get(int(aid))
            if not target or not target["is_active"]:
                bad_request("Can't assign to that person")
            out["assignee_id"] = target["id"]
    if "team_id" in data:
        tid = data["team_id"]
        if tid not in (None, "") and not db.one("SELECT id FROM teams WHERE id = ?", int(tid)):
            bad_request("No such team")
        out["team_id"] = int(tid) if tid not in (None, "") else None
    if "conversation_id" in data:
        cid = data["conversation_id"]
        if cid not in (None, ""):
            inbox.get_for(user, int(cid))
            out["conversation_id"] = int(cid)
        else:
            out["conversation_id"] = None
    if "job_id" in data:
        jid = data["job_id"]
        if jid not in (None, ""):
            try:
                exists = db.one("SELECT id FROM jobs WHERE id = ?", int(jid))
            except sqlite3.OperationalError:  # pragma: no cover
                exists = None
            if not exists:
                bad_request("No such job")
            out["job_id"] = int(jid)
        else:
            out["job_id"] = None
    return out


def _emit(task: dict, extra_users=()) -> None:
    realtime.emit("task.changed", {"id": task["id"], "conversation_id": task["conversation_id"], "job_id": task["job_id"]})
    people = {u for u in (task["assignee_id"], *extra_users) if u}
    if people:
        realtime.emit("badges.changed", {}, users=sorted(people))


def _notify_assignee(task: dict, actor: dict) -> None:
    if not task["assignee_id"] or task["assignee_id"] == actor["id"]:
        return
    due = ""
    if task["due_at"]:
        due = "Due " + fmt_local(task["due_at"])
    notify.notify([task["assignee_id"]], "task", f"{actor['name']} assigned you a task: {task['title']}",
                  body=due or None, link=f"/tasks?task={task['id']}", actor_id=actor["id"],
                  entity_type="task", entity_id=task["id"])


def _index(task: dict) -> None:
    search.index("task", task["id"], task["title"], html_to_text(task["description"] or ""))


def create(user: dict, data: dict) -> dict:
    values = _validate(user, data, partial=False)
    if "assignee_id" not in data:
        values["assignee_id"] = user["id"]
    stamp = now_iso()
    values.setdefault("status", "todo")
    values.setdefault("priority", "normal")
    position = db.scalar("SELECT COALESCE(MAX(position), 0) + 1 FROM tasks") or 1
    values.update({"position": position, "created_by": user["id"], "created_at": stamp, "updated_at": stamp})
    if values["status"] == "done":
        values.update({"completed_at": stamp, "completed_by": user["id"]})
    with db.transaction():
        tid = db.insert("tasks", values)
        task = get(tid)
        _index(task)
        _notify_assignee(task, user)
        if task["conversation_id"]:
            inbox.add_event(task["conversation_id"], "task_created", user["id"], {"task_id": tid, "title": task["title"]})
            inbox.touch(task["conversation_id"], "task")
        _emit(task)
    return task


def can_edit(user: dict, task: dict) -> bool:
    return True  # anyone who can see a task may update it (small teams share work)


def can_delete(user: dict, task: dict) -> bool:
    return user["id"] in (task["created_by"], task["assignee_id"]) or user["role"] in MANAGER_ROLES


def update(user: dict, task_id: int, data: dict) -> dict:
    task = get_for(user, task_id)
    values = _validate(user, data, partial=True)
    if not values:
        return task
    stamp = now_iso()
    if "status" in values and values["status"] != task["status"]:
        if values["status"] == "done":
            values.update({"completed_at": stamp, "completed_by": user["id"]})
        else:
            values.update({"completed_at": None, "completed_by": None})
    if "due_at" in values and values["due_at"] != task["due_at"]:
        values.update({"due_notified_at": None, "overdue_notified_at": None})
    values["updated_at"] = stamp
    with db.transaction():
        db.update("tasks", task_id, values)
        new = get(task_id)
        _index(new)
        if "assignee_id" in values and values["assignee_id"] != task["assignee_id"]:
            _notify_assignee(new, user)
        if new["conversation_id"] and new["status"] != task["status"] and new["status"] == "done":
            inbox.add_event(new["conversation_id"], "task_completed", user["id"], {"task_id": task_id, "title": new["title"]})
            inbox.touch(new["conversation_id"], "task")
        elif new["conversation_id"]:
            inbox.touch(new["conversation_id"], "task")
        _emit(new, extra_users=[task["assignee_id"]])
    return new


def delete(user: dict, task_id: int) -> None:
    task = get_for(user, task_id)
    if not can_delete(user, task):
        forbidden("Only the creator, the assignee or a manager can delete this task")
    with db.transaction():
        db.delete("tasks", task_id)
        search.unindex("task", task_id)
        if task["conversation_id"]:
            inbox.touch(task["conversation_id"], "task")
        _emit(task)


def reorder(user: dict, ids: list[int]) -> None:
    clause, params = visible_clause(user)
    with db.transaction():
        for pos, tid in enumerate(ids, start=1):
            if db.one(f"SELECT t.id FROM tasks t WHERE t.id = ? AND {clause}", [int(tid), *params]):
                db.update("tasks", int(tid), {"position": pos})
        realtime.emit("task.changed", {"ids": [int(i) for i in ids]})


def badge_count(user_id: int) -> int:
    return db.scalar(
        "SELECT COUNT(*) FROM tasks WHERE assignee_id = ? AND status != 'done' AND due_at IS NOT NULL AND due_at < ?",
        user_id, end_of_today_iso(),
    )


def process_due() -> int:
    """Notify assignees an hour before a task is due, and again once it's overdue."""
    current = now()
    stamp = iso(current)
    soon = iso(current + timedelta(hours=1))
    sent = 0
    due_soon = db.query(
        "SELECT * FROM tasks WHERE status != 'done' AND assignee_id IS NOT NULL AND due_at > ? AND due_at <= ? "
        "AND due_notified_at IS NULL", stamp, soon,
    )
    for t in due_soon:
        with db.transaction():
            db.update("tasks", t["id"], {"due_notified_at": stamp})
            notify.notify([t["assignee_id"]], "task", f"Due within the hour: {t['title']}", link=f"/tasks?task={t['id']}",
                          entity_type="task", entity_id=t["id"], include_actor=True)
            sent += 1
    overdue = db.query(
        "SELECT * FROM tasks WHERE status != 'done' AND assignee_id IS NOT NULL AND due_at <= ? "
        "AND overdue_notified_at IS NULL", stamp,
    )
    for t in overdue:
        with db.transaction():
            db.update("tasks", t["id"], {"overdue_notified_at": stamp, "due_notified_at": t["due_notified_at"] or stamp})
            notify.notify([t["assignee_id"]], "task", f"Overdue: {t['title']}", link=f"/tasks?task={t['id']}",
                          entity_type="task", entity_id=t["id"], include_actor=True)
            realtime.emit("badges.changed", {}, users=[t["assignee_id"]])
            sent += 1
    return sent
