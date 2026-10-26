"""Contacts API: people, their emails/phones, organizations, groups, merge, CSV."""

from __future__ import annotations

import sqlite3

from flask import Blueprint, Response, request

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.services import contact_book, hooks, inbox_query
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import search as search_svc
from pps_tools.switchboard.web import (
    as_bool, as_int, bad_request, body, can, current_user, ok, require, require_fields,
)

bp = Blueprint("contacts", __name__)


def _changed(contact_id: int | None = None) -> None:
    realtime.emit("contact.changed", {"id": contact_id})


def _jobs_for(where: str, params: list) -> list[dict]:
    try:
        return db.query(
            "SELECT j.id, j.number, j.title, j.due_at, j.completed_at, j.archived_at, j.priority, "
            "s.name AS stage_name, s.color AS stage_color, s.is_done AS stage_done "
            f"FROM jobs j LEFT JOIN job_stages s ON s.id = j.stage_id WHERE {where} "
            "ORDER BY COALESCE(j.completed_at, j.due_at, j.created_at) DESC LIMIT 50", params,
        )
    except sqlite3.OperationalError:  # jobs schema not available
        return []


def _tasks_for_contact(contact_id: int) -> list[dict]:
    return db.query(
        "SELECT t.id, t.title, t.status, t.due_at, t.assignee_id, t.conversation_id, t.job_id FROM tasks t "
        "WHERE t.conversation_id IN (SELECT id FROM conversations WHERE contact_id = ?) "
        "OR t.job_id IN (SELECT id FROM jobs WHERE contact_id = ?) "
        "ORDER BY (t.status = 'done'), COALESCE(t.due_at, t.created_at) LIMIT 50",
        contact_id, contact_id,
    )


# -- contacts -----------------------------------------------------------------------


@bp.get("/api/contacts")
@require("inbox")
def list_contacts():
    args = request.args
    blocked = args.get("blocked")
    return ok(contact_book.list_contacts(
        q=(args.get("q") or "").strip() or None,
        organization_id=as_int(args.get("organization_id"), "organization_id"),
        group_id=as_int(args.get("group_id"), "group_id"),
        blocked=None if blocked in (None, "") else as_bool(blocked),
        sort=args.get("sort") or "recent",
        limit=min(as_int(args.get("limit"), "limit") or 50, 500),
        offset=max(as_int(args.get("offset"), "offset") or 0, 0),
    ))


@bp.post("/api/contacts")
@require("inbox")
def create_contact():
    contact = contact_book.create_contact(body(), current_user()["id"])
    _changed(contact["id"])
    hooks.fire("contact.created", {"contact_id": contact["id"], "by": current_user()["id"]})
    return ok({"contact": contact_book.serialize_one(contact)}, 201)


@bp.get("/api/contacts/<int:contact_id>")
@require("inbox")
def get_contact(contact_id: int):
    contact = contact_book.get_or_404(contact_id)
    user = current_user()
    conversations = inbox_query.contact_history(user, contact_id, exclude=None, limit=30)
    return ok({
        "contact": contact_book.serialize_one(contact),
        "conversations": conversations,
        "jobs": _jobs_for("j.contact_id = ?", [contact_id]),
        "tasks": _tasks_for_contact(contact_id),
    })


@bp.patch("/api/contacts/<int:contact_id>")
@require("inbox")
def update_contact(contact_id: int):
    contact = contact_book.update_contact(contact_id, body())
    _changed(contact_id)
    return ok({"contact": contact_book.serialize_one(contact)})


@bp.delete("/api/contacts/<int:contact_id>")
@require("inbox")
def delete_contact(contact_id: int):
    contact_book.delete_contact(contact_id)
    _changed(contact_id)
    return ok()


@bp.post("/api/contacts/<int:contact_id>/merge")
@require("inbox")
def merge_contacts(contact_id: int):
    data = body()
    require_fields(data, "other_id")
    contact = contact_book.merge(contact_id, int(data["other_id"]))
    _changed(contact_id)
    _changed(int(data["other_id"]))
    hooks.fire("contact.merged", {"contact_id": contact_id, "merged_id": int(data["other_id"]), "by": current_user()["id"]})
    return ok({"contact": contact_book.serialize_one(contact)})


@bp.post("/api/contacts/<int:contact_id>/handles")
@require("inbox")
def add_handle(contact_id: int):
    data = body()
    require_fields(data, "kind", "value")
    contact = contact_book.add_handle(contact_id, data["kind"], data["value"], (data.get("label") or "").strip() or None)
    _changed(contact_id)
    return ok({"contact": contact_book.serialize_one(contact)}, 201)


@bp.delete("/api/contacts/<int:contact_id>/handles/<int:handle_id>")
@require("inbox")
def remove_handle(contact_id: int, handle_id: int):
    contact = contact_book.remove_handle(contact_id, handle_id)
    _changed(contact_id)
    return ok({"contact": contact_book.serialize_one(contact)})


@bp.post("/api/contacts/<int:contact_id>/handles/<int:handle_id>/primary")
@require("inbox")
def primary_handle(contact_id: int, handle_id: int):
    contact = contact_book.make_primary(contact_id, handle_id)
    _changed(contact_id)
    return ok({"contact": contact_book.serialize_one(contact)})


@bp.post("/api/contacts/<int:contact_id>/block")
@require("inbox")
def block_contact(contact_id: int):
    blocked = as_bool(body().get("blocked", True))
    contact = contact_book.update_contact(contact_id, {"is_blocked": blocked})
    _changed(contact_id)
    return ok({"contact": contact_book.serialize_one(contact)})


@bp.get("/api/contacts/export.csv")
@require("inbox")
def export_contacts():
    args = request.args
    where, params = ["1 = 1"], []
    if args.get("organization_id"):
        where.append("organization_id = ?")
        params.append(as_int(args.get("organization_id"), "organization_id"))
    if args.get("group_id"):
        where.append("id IN (SELECT contact_id FROM contact_group_members WHERE group_id = ?)")
        params.append(as_int(args.get("group_id"), "group_id"))
    rows = db.query(f"SELECT * FROM contacts WHERE {' AND '.join(where)} ORDER BY COALESCE(name, email, phone) COLLATE NOCASE", params)
    return Response(contact_book.export_csv(rows), mimetype="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="contacts.csv"'})


@bp.post("/api/contacts/import")
@require("inbox")
def import_contacts():
    upload = request.files.get("file")
    if upload:
        raw = upload.read()
    else:
        raw = (body().get("csv") or "").encode("utf-8")
    if not raw.strip():
        bad_request("Choose a CSV file to import")
    if len(raw) > 5 * 1024 * 1024:
        bad_request("That file is too big (5 MB max)")
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    result = contact_book.import_csv(text, current_user()["id"])
    _changed()
    return ok(result)


# -- organizations ------------------------------------------------------------------


@bp.get("/api/organizations")
@require("inbox")
def list_orgs():
    return ok({"items": contact_book.list_orgs((request.args.get("q") or "").strip() or None)})


@bp.post("/api/organizations")
@require("inbox")
def create_org():
    org = contact_book.create_org(body())
    _changed()
    return ok({"organization": contact_book.serialize_orgs([org])[0]}, 201)


@bp.get("/api/organizations/<int:org_id>")
@require("inbox")
def get_org(org_id: int):
    org = contact_book.get_org_or_404(org_id)
    people = db.query("SELECT * FROM contacts WHERE organization_id = ? ORDER BY COALESCE(name, email) COLLATE NOCASE", org_id)
    user = current_user()
    conversations = []
    seen = set()
    for person in people[:25]:
        for conv in inbox_query.contact_history(user, person["id"], exclude=None, limit=10):
            if conv["id"] not in seen:
                seen.add(conv["id"])
                conversations.append(conv)
    conversations.sort(key=lambda c: c["last_activity_at"], reverse=True)
    return ok({
        "organization": contact_book.serialize_orgs([org])[0],
        "contacts": contact_book.serialize(people),
        "conversations": conversations[:30],
        "jobs": _jobs_for("j.organization_id = ? OR j.contact_id IN (SELECT id FROM contacts WHERE organization_id = ?)",
                          [org_id, org_id]),
    })


@bp.patch("/api/organizations/<int:org_id>")
@require("inbox")
def update_org(org_id: int):
    org = contact_book.update_org(org_id, body())
    _changed()
    return ok({"organization": contact_book.serialize_orgs([org])[0]})


@bp.delete("/api/organizations/<int:org_id>")
@require("inbox")
def delete_org(org_id: int):
    contact_book.delete_org(org_id)
    _changed()
    return ok()


@bp.post("/api/organizations/<int:org_id>/link-domain")
@require("inbox")
def link_domain(org_id: int):
    linked = contact_book.link_domain(org_id)
    _changed()
    return ok({"linked": linked})


# -- groups -------------------------------------------------------------------------


@bp.get("/api/contact-groups")
@require("inbox")
def list_groups():
    return ok({"items": contact_book.list_groups()})


@bp.post("/api/contact-groups")
@require("inbox")
def create_group():
    data = body()
    group = contact_book.create_group(data.get("name"), data.get("color"))
    realtime.emit("settings.changed", {"what": "contact_groups"})
    return ok({"group": group}, 201)


@bp.patch("/api/contact-groups/<int:group_id>")
@require("inbox")
def update_group(group_id: int):
    group = contact_book.update_group(group_id, body())
    realtime.emit("settings.changed", {"what": "contact_groups"})
    return ok({"group": group})


@bp.delete("/api/contact-groups/<int:group_id>")
@require("inbox")
def delete_group(group_id: int):
    contact_book.delete_group(group_id)
    realtime.emit("settings.changed", {"what": "contact_groups"})
    return ok()


@bp.post("/api/contact-groups/<int:group_id>/members")
@require("inbox")
def group_members(group_id: int):
    data = body()
    ids = data.get("contact_ids") or []
    if not isinstance(ids, list):
        bad_request("contact_ids must be a list")
    with db.transaction():
        if as_bool(data.get("remove")):
            contact_book.remove_from_group(group_id, ids)
        else:
            contact_book.add_to_group(group_id, ids)
    _changed()
    return ok()


# -- module hooks -------------------------------------------------------------------


def bootstrap(user: dict) -> dict:
    if not can(user, "inbox"):
        return {}
    return {"contact_groups": contact_book.list_groups()}


def search(user: dict, q: str, limit: int) -> list[dict]:
    if not can(user, "inbox"):
        return []
    res = contact_book.list_contacts(q=q, limit=limit)["items"]
    out = [{
        "type": "contact", "id": c["id"], "title": c["display_name"],
        "subtitle": " · ".join(x for x in (c["title"], (c["organization"] or {}).get("name"), c["email"] or c["phone"]) if x),
        "url": f"/contacts/{c['id']}", "icon": "contact-round", "group": "Contacts",
    } for c in res]
    org_ids = [r["ref_id"] for r in search_svc.search(["organization"], q, limit)]
    like = f"%{q}%"
    org_ids += db.column("SELECT id FROM organizations WHERE name LIKE ? LIMIT ?", like, limit)
    seen = set()
    for oid in org_ids:
        if oid in seen or len(seen) >= limit:
            continue
        seen.add(oid)
        org = db.one("SELECT id, name, domain FROM organizations WHERE id = ?", oid)
        if org:
            out.append({"type": "organization", "id": org["id"], "title": org["name"], "subtitle": org["domain"] or "",
                        "url": f"/contacts/orgs/{org['id']}", "icon": "building", "group": "Contacts"})
    return out


def seed(ctx) -> None:
    from pps_tools.switchboard.demo.contacts import seed_contacts

    seed_contacts(ctx)


__all__ = ["bp", "contacts_svc"]
