"""Admin API: API tokens, outgoing webhooks, sidebar integrations, backup/export and
the audit log. Everything under /api/admin needs the 'admin' permission; the inbox
sidebar reads /api/integrations."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile

from flask import Blueprint, Response, request, send_file

from pps_tools.switchboard import config, db
from pps_tools.switchboard.api.core import APP_VERSION
from pps_tools.switchboard.services import hooks, inbox, integrations, settings, webhooks
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.util import now, now_iso, sha256, token
from pps_tools.switchboard.web import (
    as_bool, as_int, audit, bad_request, body, current_user, not_found, ok, require, require_fields,
)
from pps_tools.switchboard.worker import Task

bp = Blueprint("admin", __name__)

hooks.on("*", webhooks.on_event)


# -- API tokens ---------------------------------------------------------------------


def _token_row(r: dict) -> dict:
    return {
        "id": r["id"], "name": r["name"], "prefix": r["prefix"], "user_id": r["user_id"],
        "user_name": r.get("user_name"), "created_at": r["created_at"], "last_used_at": r["last_used_at"],
        "revoked_at": r["revoked_at"],
    }


@bp.get("/api/admin/tokens")
@require("admin")
def list_tokens():
    rows = db.query(
        "SELECT t.*, u.name AS user_name FROM api_tokens t JOIN users u ON u.id = t.user_id "
        "ORDER BY t.revoked_at IS NOT NULL, t.created_at DESC"
    )
    return ok({"items": [_token_row(r) for r in rows]})


@bp.post("/api/admin/tokens")
@require("admin")
def create_token():
    data = body()
    name = (data.get("name") or "").strip()[:80]
    if not name:
        bad_request("Name the token after what will use it, e.g. “Zapier”")
    raw = "sb_" + token(24)
    with db.transaction():
        tid = db.insert("api_tokens", {
            "user_id": current_user()["id"], "name": name, "token_hash": sha256(raw), "prefix": raw[:10],
            "created_at": now_iso(),
        })
        audit("api_token.create", "api_token", tid, {"name": name})
    row = db.one("SELECT t.*, u.name AS user_name FROM api_tokens t JOIN users u ON u.id = t.user_id WHERE t.id = ?", tid)
    return ok({"token": raw, "item": _token_row(row)}, 201)


@bp.delete("/api/admin/tokens/<int:tid>")
@require("admin")
def revoke_token(tid: int):
    row = db.one("SELECT * FROM api_tokens WHERE id = ?", tid)
    if not row:
        not_found("Token not found")
    with db.transaction():
        if not row["revoked_at"]:
            db.update("api_tokens", tid, {"revoked_at": now_iso()})
        audit("api_token.revoke", "api_token", tid, {"name": row["name"]})
    return ok()


# -- webhooks -----------------------------------------------------------------------


def _webhook_values(data: dict, partial: bool) -> dict:
    out: dict = {}
    if "name" in data or not partial:
        name = (data.get("name") or "").strip()[:80]
        if not name:
            bad_request("Give the webhook a name")
        out["name"] = name
    if "url" in data or not partial:
        url = (data.get("url") or "").strip()
        if not webhooks.valid_url(url):
            bad_request("Enter a full http(s) URL for the webhook")
        out["url"] = url
    if "events" in data or not partial:
        events = data.get("events") or ["*"]
        if not isinstance(events, list) or not all(isinstance(e, str) and e.strip() for e in events):
            bad_request("events must be a list of event names")
        out["events_json"] = db.jdump(sorted({e.strip() for e in events}))
    if "is_active" in data:
        out["is_active"] = 1 if as_bool(data["is_active"]) else 0
    return out


def _webhook(wid: int) -> dict:
    row = db.one("SELECT * FROM webhooks WHERE id = ?", wid)
    if not row:
        not_found("Webhook not found")
    return row


@bp.get("/api/admin/webhooks")
@require("admin")
def list_webhooks():
    rows = db.query("SELECT * FROM webhooks ORDER BY name COLLATE NOCASE")
    pending = {r["webhook_id"]: r["n"] for r in db.query(
        "SELECT webhook_id, COUNT(*) AS n FROM webhook_deliveries WHERE status = 'pending' GROUP BY webhook_id")}
    items = []
    for r in rows:
        item = webhooks.serialize(r)
        item["pending"] = pending.get(r["id"], 0)
        items.append(item)
    return ok({"items": items, "events": [{"name": n, "description": d} for n, d in webhooks.EVENT_CATALOG]})


@bp.post("/api/admin/webhooks")
@require("admin")
def create_webhook():
    values = _webhook_values(body(), partial=False)
    values.update({"secret": webhooks.new_secret(), "created_by": current_user()["id"], "created_at": now_iso()})
    values.setdefault("is_active", 1)
    with db.transaction():
        wid = db.insert("webhooks", values)
        audit("webhook.create", "webhook", wid, {"url": values["url"]})
    return ok({"item": webhooks.serialize(_webhook(wid))}, 201)


@bp.patch("/api/admin/webhooks/<int:wid>")
@require("admin")
def update_webhook(wid: int):
    _webhook(wid)
    with db.transaction():
        db.update("webhooks", wid, _webhook_values(body(), partial=True))
        audit("webhook.update", "webhook", wid)
    return ok({"item": webhooks.serialize(_webhook(wid))})


@bp.delete("/api/admin/webhooks/<int:wid>")
@require("admin")
def delete_webhook(wid: int):
    _webhook(wid)
    with db.transaction():
        db.delete("webhooks", wid)
        audit("webhook.delete", "webhook", wid)
    return ok()


@bp.post("/api/admin/webhooks/<int:wid>/rotate-secret")
@require("admin")
def rotate_secret(wid: int):
    _webhook(wid)
    with db.transaction():
        db.update("webhooks", wid, {"secret": webhooks.new_secret()})
        audit("webhook.rotate_secret", "webhook", wid)
    return ok({"item": webhooks.serialize(_webhook(wid))})


@bp.post("/api/admin/webhooks/<int:wid>/test")
@require("admin")
def test_webhook(wid: int):
    _webhook(wid)
    delivery = webhooks.send_test(wid)
    return ok({"delivery": webhooks.serialize_delivery(delivery), "item": webhooks.serialize(_webhook(wid))})


@bp.get("/api/admin/webhooks/<int:wid>/deliveries")
@require("admin")
def webhook_deliveries(wid: int):
    _webhook(wid)
    limit = min(as_int(request.args.get("limit"), "limit") or 50, 200)
    rows = db.query("SELECT * FROM webhook_deliveries WHERE webhook_id = ? ORDER BY id DESC LIMIT ?", wid, limit)
    return ok({"items": [webhooks.serialize_delivery(r) for r in rows]})


@bp.post("/api/admin/deliveries/<int:did>/retry")
@require("admin")
def retry_delivery(did: int):
    if not db.one("SELECT id FROM webhook_deliveries WHERE id = ?", did):
        not_found("Delivery not found")
    return ok({"delivery": webhooks.serialize_delivery(webhooks.retry(did))})


# -- sidebar integrations -------------------------------------------------------------


def _integration(iid: int) -> dict:
    row = integrations.get(iid)
    if not row:
        not_found("Integration not found")
    return row


@bp.get("/api/integrations")
@require("inbox")
def active_integrations():
    rows = db.query("SELECT * FROM integrations WHERE is_active = 1 ORDER BY position, id")
    return ok({"items": [integrations.serialize(r) for r in rows]})


@bp.get("/api/integrations/<int:iid>/context")
@require("inbox")
def integration_context(iid: int):
    row = _integration(iid)
    if not row["is_active"]:
        not_found("Integration not found")
    cid = as_int(request.args.get("conversation_id"), "conversation_id", allow_none=False)
    conv = inbox.get_for(current_user(), cid)
    return ok(integrations.context(row, conv))


@bp.get("/api/admin/integrations")
@require("admin")
def list_integrations():
    rows = db.query("SELECT * FROM integrations ORDER BY position, id")
    return ok({"items": [integrations.serialize(r, admin=True) for r in rows],
               "variables": list(integrations.VARIABLES)})


@bp.post("/api/admin/integrations")
@require("admin")
def create_integration():
    data = body()
    require_fields(data, "kind", "name")
    if data["kind"] not in integrations.KINDS:
        bad_request("Unknown integration kind")
    try:
        cfg = integrations.clean_config(data["kind"], data.get("config") or {})
    except integrations.IntegrationError as exc:
        bad_request(str(exc))
    position = (db.scalar("SELECT MAX(position) FROM integrations") or 0) + 1
    with db.transaction():
        iid = db.insert("integrations", {
            "kind": data["kind"], "name": data["name"].strip()[:80], "config_json": db.jdump(cfg),
            "is_active": 0 if data.get("is_active") is False else 1, "position": position, "created_at": now_iso(),
        })
        audit("integration.create", "integration", iid, {"kind": data["kind"]})
    return ok({"item": integrations.serialize(_integration(iid), admin=True)}, 201)


@bp.patch("/api/admin/integrations/<int:iid>")
@require("admin")
def update_integration(iid: int):
    row = _integration(iid)
    data = body()
    values: dict = {}
    if "name" in data:
        name = (data.get("name") or "").strip()[:80]
        if not name:
            bad_request("Name can't be empty")
        values["name"] = name
    if "config" in data:
        try:
            values["config_json"] = db.jdump(integrations.clean_config(row["kind"], data["config"] or {},
                                                                       db.jload(row["config_json"], {})))
        except integrations.IntegrationError as exc:
            bad_request(str(exc))
    if "is_active" in data:
        values["is_active"] = 1 if as_bool(data["is_active"]) else 0
    if "position" in data:
        values["position"] = as_int(data["position"], "position") or 0
    with db.transaction():
        db.update("integrations", iid, values)
        audit("integration.update", "integration", iid)
    integrations.clear_cache()
    return ok({"item": integrations.serialize(_integration(iid), admin=True)})


@bp.delete("/api/admin/integrations/<int:iid>")
@require("admin")
def delete_integration(iid: int):
    _integration(iid)
    with db.transaction():
        db.delete("integrations", iid)
        audit("integration.delete", "integration", iid)
    integrations.clear_cache()
    return ok()


@bp.post("/api/admin/integrations/test")
@require("admin")
def test_integration():
    """Check settings before (or after) saving. Pass id to reuse stored secrets."""
    data = body()
    existing = {}
    kind = data.get("kind")
    if data.get("id"):
        row = _integration(as_int(data["id"], "id"))
        kind = row["kind"]
        existing = db.jload(row["config_json"], {}) or {}
    if kind not in integrations.KINDS:
        bad_request("Unknown integration kind")
    try:
        cfg = integrations.clean_config(kind, data.get("config") or {}, existing)
    except integrations.IntegrationError as exc:
        return ok({"ok": False, "message": str(exc)})
    return ok(integrations.test(kind, cfg))


# -- backup, export, audit ------------------------------------------------------------


@bp.get("/api/admin/backup")
@require("admin")
def backup():
    """A consistent copy of the live database (SQLite online backup)."""
    cfg = config.current()
    fd, path = tempfile.mkstemp(prefix="switchboard-backup-", suffix=".db", dir=str(cfg.data_dir))
    os.close(fd)
    src = sqlite3.connect(str(db.path()))
    dst = sqlite3.connect(path)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()
    audit("data.backup")
    stamp = now().strftime("%Y%m%d-%H%M")
    response = send_file(path, as_attachment=True, download_name=f"switchboard-backup-{stamp}.db",
                         mimetype="application/vnd.sqlite3", max_age=0)
    response.headers["Cache-Control"] = "no-store"
    response.call_on_close(lambda: os.path.exists(path) and os.unlink(path))
    return response


USER_FIELDS = ("id", "email", "name", "role", "is_active", "title", "phone", "color", "timezone", "created_at",
               "last_seen_at")


def export_data() -> dict:
    """Everything a business would want to take elsewhere — minus secrets."""
    people = [{k: u[k] for k in USER_FIELDS} for u in db.query("SELECT * FROM users ORDER BY id")]
    for p in people:
        p["team_ids"] = users_svc.team_ids_of(p["id"])
    contacts = db.query("SELECT * FROM contacts ORDER BY id")
    handles: dict[int, list] = {}
    for h in db.query("SELECT contact_id, kind, value, label FROM contact_handles ORDER BY id"):
        handles.setdefault(h.pop("contact_id"), []).append(h)
    for c in contacts:
        c["custom"] = db.jload(c.pop("custom_json"), {})
        c["handles"] = handles.get(c["id"], [])
    labels_by: dict[int, list] = {}
    for r in db.query("SELECT conversation_id, label_id FROM conversation_labels"):
        labels_by.setdefault(r["conversation_id"], []).append(r["label_id"])
    assignees_by: dict[int, list] = {}
    for r in db.query("SELECT conversation_id, user_id FROM conversation_assignees"):
        assignees_by.setdefault(r["conversation_id"], []).append(r["user_id"])
    messages_by: dict[int, list] = {}
    for m in db.query(
        "SELECT id, conversation_id, direction, kind, from_name, from_handle, to_json, cc_json, subject, body_text, "
        "author_id, contact_id, status, date, sent_at FROM messages ORDER BY date, id"
    ):
        m["to"] = db.jload(m.pop("to_json"), [])
        m["cc"] = db.jload(m.pop("cc_json"), [])
        messages_by.setdefault(m.pop("conversation_id"), []).append(m)
    comments_by: dict[int, list] = {}
    for c in db.query("SELECT id, conversation_id, user_id, body, created_at FROM comments WHERE deleted_at IS NULL ORDER BY id"):
        comments_by.setdefault(c.pop("conversation_id"), []).append(c)
    conversations = []
    for c in db.query(
        "SELECT id, subject, channel_id, team_id, contact_id, status, priority, is_spam, created_at, closed_at, "
        "last_activity_at FROM conversations WHERE merged_into_id IS NULL ORDER BY id"
    ):
        c["label_ids"] = labels_by.get(c["id"], [])
        c["assignee_ids"] = assignees_by.get(c["id"], [])
        c["messages"] = messages_by.get(c["id"], [])
        c["comments"] = comments_by.get(c["id"], [])
        conversations.append(c)
    jobs = db.query("SELECT * FROM jobs ORDER BY id")
    ops_by: dict[int, list] = {}
    for o in db.query("SELECT * FROM job_operations ORDER BY job_id, sequence"):
        ops_by.setdefault(o["job_id"], []).append(o)
    checklist_by: dict[int, list] = {}
    for item in db.query("SELECT * FROM job_checklist ORDER BY job_id, position"):
        checklist_by.setdefault(item["job_id"], []).append(item)
    for j in jobs:
        j.pop("public_token", None)
        j["specs"] = db.jload(j.pop("specs_json"), {})
        j["tags"] = db.jload(j.pop("tags_json"), [])
        j["operations"] = ops_by.get(j["id"], [])
        j["checklist"] = checklist_by.get(j["id"], [])
    return {
        "app": "Switchboard",
        "version": APP_VERSION,
        "exported_at": now_iso(),
        "organization": {"name": settings.get("org.name"), "timezone": settings.get("org.timezone")},
        "people": people,
        "teams": users_svc.teams_with_members(),
        "organizations": db.query("SELECT * FROM organizations ORDER BY id"),
        "contacts": contacts,
        "labels": db.query("SELECT id, name, color, parent_id, visibility, owner_user_id FROM labels ORDER BY id"),
        "conversations": conversations,
        "jobs": jobs,
        "job_stages": db.query("SELECT * FROM job_stages ORDER BY position, id"),
        "shifts": db.query("SELECT * FROM shifts ORDER BY start_at"),
        "time_entries": db.query("SELECT * FROM time_entries ORDER BY clock_in"),
        "time_off_requests": db.query("SELECT * FROM time_off_requests ORDER BY start_date"),
        "tasks": db.query("SELECT * FROM tasks ORDER BY id"),
    }


@bp.get("/api/admin/export.json")
@require("admin")
def export_json():
    data = export_data()
    audit("data.export")
    stamp = now().strftime("%Y%m%d")
    return Response(
        json.dumps(data, default=str, ensure_ascii=False, indent=1),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="switchboard-export-{stamp}.json"', "Cache-Control": "no-store"},
    )


@bp.get("/api/admin/audit")
@require("admin")
def audit_log():
    limit = min(as_int(request.args.get("limit"), "limit") or 50, 200)
    before = as_int(request.args.get("before"), "before")
    rows = db.query(
        "SELECT a.*, u.name AS user_name FROM audit_log a LEFT JOIN users u ON u.id = a.user_id "
        "WHERE (? IS NULL OR a.id < ?) ORDER BY a.id DESC LIMIT ?",
        before, before, limit + 1,
    )
    more = len(rows) > limit
    items = []
    for r in rows[:limit]:
        r["data"] = db.jload(r.pop("data_json"), None)
        items.append(r)
    return ok({"items": items, "next": items[-1]["id"] if more and items else None})


# -- module hooks -------------------------------------------------------------------


def worker_tasks():
    return [
        Task("webhooks.deliver", 5, webhooks.process_deliveries),
        Task("webhooks.cleanup", 6 * 3600, webhooks.cleanup),
    ]


def seed(ctx) -> None:
    from pps_tools.switchboard.demo.admin import seed_admin

    seed_admin(ctx)

