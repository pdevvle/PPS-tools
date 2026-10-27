"""The address book: contacts, their handles, organizations and groups, merging
duplicates, and CSV import/export. Identity lookups (handle -> contact) live in
services/contacts.py; this module builds the editing side on top of it."""

from __future__ import annotations

import csv
import io

from pps_tools.switchboard import db
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import search
from pps_tools.switchboard.util import csv_cell, now_iso, norm_email, norm_phone, pick_color
from pps_tools.switchboard.web import bad_request, conflict, not_found

CONTACT_FIELDS = ("name", "title", "address", "notes")
ORG_FIELDS = ("name", "domain", "phone", "website", "address", "notes")


# -- serialization ------------------------------------------------------------------


def get_or_404(contact_id: int) -> dict:
    contact = contacts_svc.get(contact_id)
    if not contact:
        not_found("Contact not found")
    return contact


def _groups_by_contact(ids: list[int]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {i: [] for i in ids}
    if not ids:
        return out
    for r in db.query(
        f"SELECT contact_id, group_id FROM contact_group_members WHERE contact_id IN ({db.placeholders(ids)}) "
        f"ORDER BY group_id", ids,
    ):
        out.setdefault(r["contact_id"], []).append(r["group_id"])
    return out


def serialize(rows: list[dict], full: bool = False) -> list[dict]:
    """Contacts for lists (full=True adds handles, notes and custom fields)."""
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    org_ids = sorted({r["organization_id"] for r in rows if r.get("organization_id")})
    orgs = {o["id"]: o for o in db.query(
        f"SELECT id, name, domain FROM organizations WHERE id IN ({db.placeholders(org_ids)})", org_ids)} if org_ids else {}
    groups = _groups_by_contact(ids)
    activity = {r["contact_id"]: r for r in db.query(
        f"SELECT contact_id, MAX(last_activity_at) AS last_activity_at, COUNT(*) AS conversations "
        f"FROM conversations WHERE contact_id IN ({db.placeholders(ids)}) AND merged_into_id IS NULL "
        f"GROUP BY contact_id", ids,
    )}
    handles: dict[int, list[dict]] = {}
    if full:
        for h in db.query(
            f"SELECT id, contact_id, kind, value, label FROM contact_handles WHERE contact_id IN ({db.placeholders(ids)}) "
            f"ORDER BY id", ids,
        ):
            handles.setdefault(h["contact_id"], []).append({k: h[k] for k in ("id", "kind", "value", "label")})
    out = []
    for r in rows:
        act = activity.get(r["id"]) or {}
        item = {
            "id": r["id"],
            "name": r["name"],
            "display_name": contacts_svc.display_name(r),
            "email": r["email"],
            "phone": r["phone"],
            "title": r["title"],
            "organization": orgs.get(r["organization_id"]),
            "group_ids": groups.get(r["id"], []),
            "is_blocked": bool(r["is_blocked"]),
            "color": pick_color(r["email"] or r["phone"] or r["id"]),
            "last_activity_at": act.get("last_activity_at"),
            "conversation_count": act.get("conversations", 0),
            "created_at": r["created_at"],
        }
        if full:
            item.update({
                "handles": handles.get(r["id"], []),
                "address": r["address"],
                "notes": r["notes"],
                "custom": db.jload(r["custom_json"], {}) or {},
                "updated_at": r["updated_at"],
            })
        out.append(item)
    return out


def serialize_one(contact: dict) -> dict:
    return serialize([contact], full=True)[0]


# -- listing ------------------------------------------------------------------------


def list_contacts(q: str | None = None, organization_id: int | None = None, group_id: int | None = None,
                  blocked: bool | None = None, sort: str = "recent", limit: int = 50, offset: int = 0) -> dict:
    where, params = ["1 = 1"], []
    if q:
        hits = [r["ref_id"] for r in search.search(["contact"], q, 500)]
        like = f"%{q}%"
        clause = ("(c.name LIKE ? OR c.email LIKE ? OR c.phone LIKE ? OR c.title LIKE ? "
                  "OR c.id IN (SELECT contact_id FROM contact_handles WHERE value LIKE ?)"
                  " OR c.organization_id IN (SELECT id FROM organizations WHERE name LIKE ?)")
        params += [like, like, like, like, like, like]
        if hits:
            clause += f" OR c.id IN ({db.placeholders(hits)})"
            params += hits
        where.append(clause + ")")
    if organization_id:
        where.append("c.organization_id = ?")
        params.append(organization_id)
    if group_id:
        where.append("c.id IN (SELECT contact_id FROM contact_group_members WHERE group_id = ?)")
        params.append(group_id)
    if blocked is not None:
        where.append("c.is_blocked = ?")
        params.append(1 if blocked else 0)
    where_sql = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM contacts c WHERE {where_sql}", params)
    if sort == "name":
        order = "COALESCE(c.name, c.email, c.phone) COLLATE NOCASE"
    else:
        order = ("COALESCE((SELECT MAX(last_activity_at) FROM conversations v WHERE v.contact_id = c.id), c.created_at) DESC, "
                 "c.id DESC")
    rows = db.query(f"SELECT c.* FROM contacts c WHERE {where_sql} ORDER BY {order} LIMIT ? OFFSET ?",
                    [*params, limit, offset])
    return {"items": serialize(rows), "total": total}


# -- create / update ----------------------------------------------------------------


def _clean_handles(kind: str, values) -> list[tuple[str, str | None]]:
    out = []
    for v in values or []:
        if isinstance(v, dict):
            value, label = v.get("value") or v.get("handle"), v.get("label")
        else:
            value, label = v, None
        if not value:
            continue
        norm = contacts_svc.normalize(kind, value)
        if not norm:
            bad_request(f"'{value}' isn't a valid {'email address' if kind == 'email' else 'phone number'}",
                        code="invalid_handle")
        out.append((norm, label))
    return out


def _check_free(kind: str, value: str, contact_id: int | None = None) -> None:
    other = db.one("SELECT contact_id FROM contact_handles WHERE kind = ? AND value = ?", kind, value)
    if other and other["contact_id"] != contact_id:
        conflict(f"{value} already belongs to another contact", code="duplicate_handle",
                 contact_id=other["contact_id"])


def _org_id(data: dict) -> int | None:
    """organization_id, or organization_name (found case-insensitively or created)."""
    if data.get("organization_id"):
        org_id = int(data["organization_id"])
        if not db.one("SELECT id FROM organizations WHERE id = ?", org_id):
            bad_request("No such organization")
        return org_id
    name = (data.get("organization_name") or "").strip()
    if not name:
        return None
    return find_or_create_org(name)


def find_or_create_org(name: str, domain: str | None = None) -> int:
    row = db.one("SELECT id FROM organizations WHERE name = ? COLLATE NOCASE", name)
    if row:
        return row["id"]
    stamp = now_iso()
    oid = db.insert("organizations", {"name": name[:200], "domain": (domain or "").lower() or None,
                                      "created_at": stamp, "updated_at": stamp})
    reindex_org(oid)
    return oid


def create_contact(data: dict, user_id: int | None) -> dict:
    emails = _clean_handles("email", data.get("emails") or ([data["email"]] if data.get("email") else []))
    phones = _clean_handles("phone", data.get("phones") or ([data["phone"]] if data.get("phone") else []))
    name = (data.get("name") or "").strip() or None
    if not name and not emails and not phones:
        bad_request("Give the contact a name, email or phone number", code="validation")
    for value, _ in emails:
        _check_free("email", value)
    for value, _ in phones:
        _check_free("phone", value)
    stamp = now_iso()
    with db.transaction():
        org_id = _org_id(data)
        if not org_id and emails:
            org_id = contacts_svc.org_for_email(emails[0][0])
        cid = db.insert("contacts", {
            "name": name,
            "email": emails[0][0] if emails else None,
            "phone": phones[0][0] if phones else None,
            "organization_id": org_id,
            "title": (data.get("title") or "").strip() or None,
            "address": (data.get("address") or "").strip() or None,
            "notes": (data.get("notes") or "").strip() or None,
            "custom_json": db.jdump(_clean_custom(data.get("custom"))),
            "created_by": user_id,
            "created_at": stamp,
            "updated_at": stamp,
        })
        for value, label in emails:
            db.insert("contact_handles", {"contact_id": cid, "kind": "email", "value": value, "label": label})
        for value, label in phones:
            db.insert("contact_handles", {"contact_id": cid, "kind": "phone", "value": value, "label": label})
        for gid in data.get("group_ids") or []:
            add_to_group(int(gid), [cid])
        contacts_svc.reindex(cid)
    return contacts_svc.get(cid)


def _clean_custom(value) -> dict:
    if not value:
        return {}
    if not isinstance(value, dict):
        bad_request("custom must be an object")
    return {str(k)[:60]: ("" if v is None else str(v)[:500]) for k, v in value.items() if str(k).strip()}


def update_contact(contact_id: int, data: dict) -> dict:
    get_or_404(contact_id)
    changes: dict = {}
    for field in CONTACT_FIELDS:
        if field in data:
            changes[field] = (data[field] or "").strip() or None
    if "organization_id" in data or "organization_name" in data:
        changes["organization_id"] = _org_id(data)
    if "custom" in data:
        changes["custom_json"] = db.jdump(_clean_custom(data["custom"]))
    if "is_blocked" in data:
        changes["is_blocked"] = 1 if data["is_blocked"] else 0
    with db.transaction():
        if changes:
            changes["updated_at"] = now_iso()
            db.update("contacts", contact_id, changes)
        if "group_ids" in data:
            db.execute("DELETE FROM contact_group_members WHERE contact_id = ?", contact_id)
            for gid in data["group_ids"] or []:
                add_to_group(int(gid), [contact_id])
        contacts_svc.reindex(contact_id)
    return contacts_svc.get(contact_id)


def delete_contact(contact_id: int) -> None:
    get_or_404(contact_id)
    with db.transaction():
        db.delete("contacts", contact_id)
        search.unindex("contact", contact_id)


# -- handles ------------------------------------------------------------------------


def add_handle(contact_id: int, kind: str, value: str, label: str | None = None) -> dict:
    get_or_404(contact_id)
    if kind not in ("email", "phone"):
        bad_request("kind must be email or phone")
    cleaned = _clean_handles(kind, [value])
    if not cleaned:
        bad_request("Enter an email address or phone number")
    norm = cleaned[0][0]
    _check_free(kind, norm, contact_id)
    with db.transaction():
        existing = db.one("SELECT id FROM contact_handles WHERE kind = ? AND value = ?", kind, norm)
        if existing:
            db.update("contact_handles", existing["id"], {"label": label})
        else:
            contacts_svc.add_handle(contact_id, kind, norm, label)
        contacts_svc.reindex(contact_id)
    return contacts_svc.get(contact_id)


def remove_handle(contact_id: int, handle_id: int) -> dict:
    contact = get_or_404(contact_id)
    h = db.one("SELECT * FROM contact_handles WHERE id = ? AND contact_id = ?", handle_id, contact_id)
    if not h:
        not_found("No such email or phone on this contact")
    with db.transaction():
        db.delete("contact_handles", handle_id)
        primary = "email" if h["kind"] == "email" else "phone" if h["kind"] == "phone" else None
        if primary and (contact[primary] or "").lower() == h["value"].lower():
            nxt = db.one("SELECT value FROM contact_handles WHERE contact_id = ? AND kind = ? ORDER BY id LIMIT 1",
                         contact_id, h["kind"])
            db.update("contacts", contact_id, {primary: nxt["value"] if nxt else None, "updated_at": now_iso()})
        contacts_svc.reindex(contact_id)
    return contacts_svc.get(contact_id)


def make_primary(contact_id: int, handle_id: int) -> dict:
    get_or_404(contact_id)
    h = db.one("SELECT * FROM contact_handles WHERE id = ? AND contact_id = ?", handle_id, contact_id)
    if not h or h["kind"] not in ("email", "phone"):
        not_found("No such email or phone on this contact")
    with db.transaction():
        db.update("contacts", contact_id, {h["kind"]: h["value"], "updated_at": now_iso()})
    return contacts_svc.get(contact_id)


# -- merge --------------------------------------------------------------------------


def merge(keep_id: int, other_id: int) -> dict:
    """Fold ``other`` into ``keep``: handles, conversations, messages, jobs, chat
    visitors and groups move over; empty fields on ``keep`` are filled from ``other``."""
    if keep_id == other_id:
        bad_request("Pick two different contacts")
    keep = get_or_404(keep_id)
    other = get_or_404(other_id)
    with db.transaction():
        db.execute("UPDATE contact_handles SET contact_id = ? WHERE contact_id = ?", keep_id, other_id)
        for table in ("conversations", "messages", "chat_visitors"):
            db.execute(f"UPDATE {table} SET contact_id = ? WHERE contact_id = ?", keep_id, other_id)
        try:
            db.execute("UPDATE jobs SET contact_id = ? WHERE contact_id = ?", keep_id, other_id)
        except Exception:  # pragma: no cover - jobs table always exists, columns may change
            pass
        db.execute(
            "INSERT OR IGNORE INTO contact_group_members (group_id, contact_id) "
            "SELECT group_id, ? FROM contact_group_members WHERE contact_id = ?", keep_id, other_id,
        )
        fill = {}
        for field in ("name", "email", "phone", "organization_id", "title", "address"):
            if not keep[field] and other[field]:
                fill[field] = other[field]
        if other["notes"]:
            fill["notes"] = (keep["notes"] + "\n\n" + other["notes"]) if keep["notes"] else other["notes"]
        custom = {**(db.jload(other["custom_json"], {}) or {}), **(db.jload(keep["custom_json"], {}) or {})}
        fill["custom_json"] = db.jdump(custom)
        fill["is_blocked"] = 1 if (keep["is_blocked"] or other["is_blocked"]) else 0
        fill["updated_at"] = now_iso()
        db.update("contacts", keep_id, fill)
        db.delete("contacts", other_id)
        search.unindex("contact", other_id)
        contacts_svc.reindex(keep_id)
    return contacts_svc.get(keep_id)


# -- organizations ------------------------------------------------------------------


def serialize_orgs(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    counts = {r["organization_id"]: r["n"] for r in db.query(
        f"SELECT organization_id, COUNT(*) AS n FROM contacts WHERE organization_id IN ({db.placeholders(ids)}) "
        f"GROUP BY organization_id", ids)}
    out = []
    for r in rows:
        item = {k: r[k] for k in ("id", "name", "domain", "phone", "website", "address", "notes", "created_at")}
        item["custom"] = db.jload(r["custom_json"], {}) or {}
        item["contact_count"] = counts.get(r["id"], 0)
        item["color"] = pick_color(r["domain"] or r["name"])
        out.append(item)
    return out


def list_orgs(q: str | None = None, limit: int = 200) -> list[dict]:
    if q:
        like = f"%{q}%"
        rows = db.query("SELECT * FROM organizations WHERE name LIKE ? OR domain LIKE ? ORDER BY name COLLATE NOCASE LIMIT ?",
                        like, like, limit)
    else:
        rows = db.query("SELECT * FROM organizations ORDER BY name COLLATE NOCASE LIMIT ?", limit)
    return serialize_orgs(rows)


def get_org_or_404(org_id: int) -> dict:
    org = db.one("SELECT * FROM organizations WHERE id = ?", org_id)
    if not org:
        not_found("Organization not found")
    return org


def _org_values(data: dict, partial: bool) -> dict:
    out = {}
    for field in ORG_FIELDS:
        if field in data or (field == "name" and not partial):
            value = (data.get(field) or "").strip() or None
            if field == "domain" and value:
                value = value.lower().removeprefix("@").removeprefix("www.")
                if "/" in value or "@" in value or "." not in value:
                    bad_request("Domain should look like example.com")
            out[field] = value
    if "name" in out and not out["name"]:
        bad_request("Organization name is required")
    if "custom" in data:
        out["custom_json"] = db.jdump(_clean_custom(data["custom"]))
    return out


def create_org(data: dict) -> dict:
    values = _org_values(data, partial=False)
    if db.one("SELECT id FROM organizations WHERE name = ? COLLATE NOCASE", values["name"]):
        conflict("An organization with that name already exists", code="duplicate")
    stamp = now_iso()
    with db.transaction():
        oid = db.insert("organizations", {**values, "created_at": stamp, "updated_at": stamp})
        reindex_org(oid)
    return get_org_or_404(oid)


def update_org(org_id: int, data: dict) -> dict:
    get_org_or_404(org_id)
    values = _org_values(data, partial=True)
    with db.transaction():
        if values:
            values["updated_at"] = now_iso()
            db.update("organizations", org_id, values)
        reindex_org(org_id)
    return get_org_or_404(org_id)


def delete_org(org_id: int) -> None:
    get_org_or_404(org_id)
    with db.transaction():
        db.delete("organizations", org_id)
        search.unindex("organization", org_id)


def link_domain(org_id: int) -> int:
    """Attach every contact with an email at the org's domain (and no organization yet)."""
    org = get_org_or_404(org_id)
    domain = (org["domain"] or "").lower()
    if not domain:
        bad_request("Set the organization's domain first")
    if domain in contacts_svc.FREE_MAIL:
        bad_request(f"{domain} is a public email provider; link people individually instead")
    with db.transaction():
        ids = db.column(
            "SELECT DISTINCT c.id FROM contacts c JOIN contact_handles h ON h.contact_id = c.id "
            "WHERE h.kind = 'email' AND h.value LIKE ? AND c.organization_id IS NULL", f"%@{domain}",
        )
        for cid in ids:
            db.update("contacts", cid, {"organization_id": org_id, "updated_at": now_iso()})
    return len(ids)


def reindex_org(org_id: int) -> None:
    org = db.one("SELECT * FROM organizations WHERE id = ?", org_id)
    if not org:
        search.unindex("organization", org_id)
        return
    search.index("organization", org_id, org["name"], f"{org['domain'] or ''} {org['notes'] or ''} {org['address'] or ''}")


# -- groups -------------------------------------------------------------------------


def list_groups() -> list[dict]:
    rows = db.query(
        "SELECT g.*, (SELECT COUNT(*) FROM contact_group_members m WHERE m.group_id = g.id) AS member_count "
        "FROM contact_groups g ORDER BY g.name COLLATE NOCASE"
    )
    return rows


def create_group(name: str, color: str | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        bad_request("Group name is required")
    if db.one("SELECT id FROM contact_groups WHERE name = ?", name):
        conflict("A group with that name already exists", code="duplicate")
    with db.transaction():
        gid = db.insert("contact_groups", {"name": name[:80], "color": color or pick_color(name), "created_at": now_iso()})
    return db.one("SELECT * FROM contact_groups WHERE id = ?", gid)


def update_group(group_id: int, data: dict) -> dict:
    if not db.one("SELECT id FROM contact_groups WHERE id = ?", group_id):
        not_found("Group not found")
    values = {}
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            bad_request("Group name is required")
        values["name"] = name[:80]
    if "color" in data:
        values["color"] = data["color"]
    with db.transaction():
        db.update("contact_groups", group_id, values)
    return db.one("SELECT * FROM contact_groups WHERE id = ?", group_id)


def delete_group(group_id: int) -> None:
    with db.transaction():
        db.delete("contact_groups", group_id)


def add_to_group(group_id: int, contact_ids) -> None:
    if not db.one("SELECT id FROM contact_groups WHERE id = ?", group_id):
        not_found("Group not found")
    for cid in contact_ids:
        db.execute("INSERT OR IGNORE INTO contact_group_members (group_id, contact_id) "
                   "SELECT ?, id FROM contacts WHERE id = ?", group_id, int(cid))


def remove_from_group(group_id: int, contact_ids) -> None:
    for cid in contact_ids:
        db.execute("DELETE FROM contact_group_members WHERE group_id = ? AND contact_id = ?", group_id, int(cid))


# -- CSV ----------------------------------------------------------------------------

EXPORT_COLUMNS = ["name", "email", "phone", "organization", "title", "address", "notes", "other_emails",
                  "other_phones", "groups", "created_at"]

_HEADER_ALIASES = {
    "name": ("name", "full name", "full_name", "contact", "contact name", "display name"),
    "first_name": ("first name", "first_name", "given name", "firstname"),
    "last_name": ("last name", "last_name", "family name", "surname", "lastname"),
    "email": ("email", "e-mail", "email address", "e-mail address", "primary email", "email 1 - value"),
    "phone": ("phone", "phone number", "mobile", "mobile phone", "cell", "telephone", "primary phone",
              "phone 1 - value", "business phone"),
    "organization": ("organization", "organisation", "company", "company name", "business", "organization 1 - name"),
    "title": ("title", "job title", "position", "role", "organization 1 - title"),
    "notes": ("notes", "note", "comments"),
    "address": ("address", "street address", "mailing address"),
    "groups": ("groups", "group", "tags"),
}


def export_csv(rows: list[dict]) -> str:
    ids = [r["id"] for r in rows]
    orgs = {o["id"]: o["name"] for o in db.query("SELECT id, name FROM organizations")}
    group_names = {g["id"]: g["name"] for g in db.query("SELECT id, name FROM contact_groups")}
    groups = _groups_by_contact(ids)
    handles: dict[int, list[dict]] = {}
    if ids:
        for h in db.query(f"SELECT contact_id, kind, value FROM contact_handles WHERE contact_id IN ({db.placeholders(ids)}) ORDER BY id", ids):
            handles.setdefault(h["contact_id"], []).append(h)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    for r in rows:
        hs = handles.get(r["id"], [])
        writer.writerow([csv_cell(v) for v in (
            r["name"], r["email"], r["phone"], orgs.get(r["organization_id"]),
            r["title"], r["address"], r["notes"],
            ";".join(h["value"] for h in hs if h["kind"] == "email" and h["value"] != r["email"]),
            ";".join(h["value"] for h in hs if h["kind"] == "phone" and h["value"] != r["phone"]),
            ";".join(group_names[g] for g in groups.get(r["id"], []) if g in group_names),
            r["created_at"],
        )])
    return buf.getvalue()


def _map_headers(fieldnames: list[str]) -> dict[str, str]:
    mapping = {}
    for raw in fieldnames or []:
        key = (raw or "").strip().lower()
        for field, aliases in _HEADER_ALIASES.items():
            if key in aliases and field not in mapping:
                mapping[field] = raw
    return mapping


def import_csv(text: str, user_id: int | None) -> dict:
    """Create or update contacts from CSV. A row matches an existing contact by email,
    then phone; matched rows only fill in blanks (they never overwrite)."""
    if text.startswith("﻿"):
        text = text[1:]
    try:
        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t") if sample.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    cols = _map_headers(reader.fieldnames or [])
    if not ({"name", "first_name", "email", "phone"} & set(cols)):
        bad_request("The file needs a header row with at least a name, email or phone column", code="bad_csv")
    result = {"created": 0, "updated": 0, "skipped": 0, "errors": []}
    with db.transaction():
        for line_no, row in enumerate(reader, start=2):
            def col(field):
                return (row.get(cols[field]) or "").strip() if field in cols else ""

            name = col("name") or " ".join(p for p in (col("first_name"), col("last_name")) if p)
            email = norm_email(col("email")) if col("email") else None
            phone = norm_phone(col("phone")) if col("phone") else None
            if col("email") and not email:
                result["errors"].append({"line": line_no, "error": f"Invalid email '{col('email')}'"})
            if not (name or email or phone):
                result["skipped"] += 1
                continue
            existing = (contacts_svc.find("email", email) if email else None) or (contacts_svc.find("phone", phone) if phone else None)
            org_name = col("organization")
            group_names = [g.strip() for g in col("groups").replace(";", ",").split(",") if g.strip()]
            if existing:
                fill = {}
                for field, value in (("name", name), ("title", col("title")), ("notes", col("notes")), ("address", col("address"))):
                    if value and not existing[field]:
                        fill[field] = value
                if org_name and not existing["organization_id"]:
                    fill["organization_id"] = find_or_create_org(org_name)
                if email:
                    contacts_svc.add_handle(existing["id"], "email", email)
                if phone:
                    contacts_svc.add_handle(existing["id"], "phone", phone)
                if fill:
                    fill["updated_at"] = now_iso()
                    db.update("contacts", existing["id"], fill)
                contact_id = existing["id"]
                result["updated"] += 1
            else:
                stamp = now_iso()
                org_id = find_or_create_org(org_name) if org_name else (contacts_svc.org_for_email(email) if email else None)
                contact_id = db.insert("contacts", {
                    "name": name or None, "email": email, "phone": phone, "organization_id": org_id,
                    "title": col("title") or None, "notes": col("notes") or None, "address": col("address") or None,
                    "created_by": user_id, "created_at": stamp, "updated_at": stamp,
                })
                if email:
                    db.insert("contact_handles", {"contact_id": contact_id, "kind": "email", "value": email})
                if phone and not db.one("SELECT 1 AS x FROM contact_handles WHERE kind = 'phone' AND value = ?", phone):
                    db.insert("contact_handles", {"contact_id": contact_id, "kind": "phone", "value": phone})
                result["created"] += 1
            for gname in group_names:
                g = db.one("SELECT id FROM contact_groups WHERE name = ?", gname)
                gid = g["id"] if g else db.insert("contact_groups", {"name": gname[:80], "color": pick_color(gname),
                                                                      "created_at": now_iso()})
                db.execute("INSERT OR IGNORE INTO contact_group_members (group_id, contact_id) VALUES (?, ?)", gid, contact_id)
            contacts_svc.reindex(contact_id)
    return result
