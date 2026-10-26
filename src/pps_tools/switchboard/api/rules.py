"""Automation rules API (admins): CRUD, ordering, dry runs, apply-to-existing, history.
The engine itself lives in services/rules.py and listens to inbox hooks."""

from __future__ import annotations

from flask import Blueprint

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.services import inbox
from pps_tools.switchboard.services import rules as engine
from pps_tools.switchboard.util import now_iso
from pps_tools.switchboard.web import as_int, audit, bad_request, body, current_user, not_found, ok, require

bp = Blueprint("rules", __name__)

engine.register_hooks()


def _get(rid: int) -> dict:
    rule = db.one("SELECT * FROM rules WHERE id = ?", rid)
    if not rule:
        not_found("Rule not found")
    return rule


def _changed() -> None:
    realtime.emit("rules.changed", {})


@bp.get("/api/rules")
@require("admin")
def list_rules():
    rows = db.query("SELECT * FROM rules ORDER BY position, id")
    items = []
    for r in rows:
        item = engine.serialize(r)
        item["summary"] = [engine.describe_action(a) for a in item["actions"]]
        items.append(item)
    return ok({"items": items})


@bp.get("/api/rules/options")
@require("admin")
def rule_options():
    """Everything the rule editor's pickers need, in one call."""
    return ok({
        "triggers": engine.TRIGGERS,
        "fields": {k: list(v) for k, v in engine.FIELD_OPS.items()},
        "actions": list(engine.ACTION_TYPES),
        "channels": db.query("SELECT id, name, type, address FROM channels ORDER BY type, name COLLATE NOCASE"),
        "labels": db.query("SELECT id, name, color FROM labels WHERE visibility = 'shared' ORDER BY position, name COLLATE NOCASE"),
        "teams": db.query("SELECT id, name, color FROM teams ORDER BY name COLLATE NOCASE"),
        "users": db.query("SELECT id, name, color, role FROM users WHERE is_active = 1 ORDER BY name COLLATE NOCASE"),
        "responses": db.query("SELECT id, title, shortcut FROM canned_responses WHERE visibility != 'personal' "
                              "ORDER BY title COLLATE NOCASE"),
        "groups": db.query("SELECT id, name, color FROM contact_groups ORDER BY name COLLATE NOCASE"),
    })


@bp.get("/api/rules/<int:rid>")
@require("admin")
def get_rule(rid: int):
    return ok({"rule": engine.serialize(_get(rid))})


@bp.post("/api/rules")
@require("admin")
def create_rule():
    values = engine.normalize(body())
    values.setdefault("match", "all")
    values["position"] = (db.scalar("SELECT MAX(position) FROM rules") or 0) + 1
    values["created_by"] = current_user()["id"]
    values["created_at"] = values["updated_at"] = now_iso()
    with db.transaction():
        rid = db.insert("rules", values)
        audit("rule.create", "rule", rid, {"name": values["name"]})
        _changed()
    return ok({"rule": engine.serialize(_get(rid))}, 201)


@bp.patch("/api/rules/<int:rid>")
@require("admin")
def update_rule(rid: int):
    _get(rid)
    values = engine.normalize(body(), partial=True)
    if values:
        values["updated_at"] = now_iso()
        with db.transaction():
            db.update("rules", rid, values)
            audit("rule.update", "rule", rid, {k: v for k, v in values.items() if not k.endswith("_json")})
            _changed()
    return ok({"rule": engine.serialize(_get(rid))})


@bp.delete("/api/rules/<int:rid>")
@require("admin")
def delete_rule(rid: int):
    rule = _get(rid)
    with db.transaction():
        db.delete("rules", rid)
        audit("rule.delete", "rule", rid, {"name": rule["name"]})
        _changed()
    return ok()


@bp.post("/api/rules/reorder")
@require("admin")
def reorder_rules():
    ids = body().get("ids")
    if not isinstance(ids, list) or not ids:
        bad_request("Send the rule ids in their new order")
    with db.transaction():
        for position, rid in enumerate(ids, start=1):
            db.update("rules", int(rid), {"position": position})
        _changed()
    return ok({"items": [engine.serialize(r) for r in db.query("SELECT * FROM rules ORDER BY position, id")]})


@bp.post("/api/rules/<int:rid>/test")
@require("admin")
def test_rule(rid: int):
    rule = _get(rid)
    cid = as_int(body().get("conversation_id"), "conversation_id")
    if not cid:
        bad_request("Pick a conversation to test against")
    inbox.get_for(current_user(), cid)
    return ok(engine.dry_run(rule, cid))


@bp.post("/api/rules/<int:rid>/apply")
@require("admin")
def apply_rule(rid: int):
    rule = _get(rid)
    if rule["trigger"] not in ("incoming", "new_conversation"):
        bad_request("Only rules for incoming messages can be applied to existing conversations")
    limit = min(as_int(body().get("limit"), "limit") or 200, 1000)
    result = engine.apply_to_existing(rule, limit=limit)
    audit("rule.apply", "rule", rid, result)
    return ok(result)


@bp.get("/api/rules/<int:rid>/runs")
@require("admin")
def rule_runs(rid: int):
    _get(rid)
    rows = db.query(
        "SELECT r.*, c.subject AS conversation_subject FROM rule_runs r LEFT JOIN conversations c ON c.id = r.conversation_id "
        "WHERE r.rule_id = ? ORDER BY r.id DESC LIMIT 50", rid,
    )
    for r in rows:
        r["actions"] = db.jload(r.pop("actions_json"), [])
    return ok({"items": rows})


def seed(ctx) -> None:
    from pps_tools.switchboard.demo.rules import seed_rules

    seed_rules(ctx)
