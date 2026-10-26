"""Contact identity: map an email address / phone number / chat visitor to a contact,
creating one on first contact. The contacts module builds its CRUD on top of this."""

from __future__ import annotations

from pps_tools.switchboard import db
from pps_tools.switchboard.services import search
from pps_tools.switchboard.util import now_iso, norm_email, norm_phone

# Don't link people at these domains to an organization by domain.
FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "comcast.net",
    "cox.net", "att.net", "sbcglobal.net", "verizon.net", "ymail.com", "mail.com", "zoho.com",
}


def normalize(kind: str, value: str | None) -> str | None:
    if kind == "email":
        return norm_email(value)
    if kind == "phone":
        return norm_phone(value)
    return (value or "").strip() or None


def kind_for(handle: str | None) -> str:
    return "email" if handle and "@" in handle else "phone"


def find(kind: str, value: str | None) -> dict | None:
    value = normalize(kind, value)
    if not value:
        return None
    return db.one(
        "SELECT c.* FROM contact_handles h JOIN contacts c ON c.id = h.contact_id WHERE h.kind = ? AND h.value = ?",
        kind, value,
    )


def add_handle(contact_id: int, kind: str, value: str, label: str | None = None) -> None:
    value = normalize(kind, value)
    if not value:
        return
    existing = db.one("SELECT contact_id FROM contact_handles WHERE kind = ? AND value = ?", kind, value)
    if existing:
        return
    db.insert("contact_handles", {"contact_id": contact_id, "kind": kind, "value": value, "label": label})
    primary = "email" if kind == "email" else "phone" if kind == "phone" else None
    if primary:
        db.execute(f"UPDATE contacts SET {primary} = COALESCE({primary}, ?) WHERE id = ?", value, contact_id)


def org_for_email(email: str | None) -> int | None:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].lower()
    if domain in FREE_MAIL:
        return None
    row = db.one("SELECT id FROM organizations WHERE domain = ? ORDER BY id LIMIT 1", domain)
    return row["id"] if row else None


def resolve(kind: str, value: str | None, name: str | None = None, create: bool = True,
            created_by: int | None = None) -> dict | None:
    """The contact owning this handle; created (and auto-linked to an organization by
    email domain) when new. Fills in a missing name."""
    value = normalize(kind, value)
    if not value:
        return None
    name = (name or "").strip().strip('"') or None
    if name and normalize("email", name) == value:
        name = None
    contact = find(kind, value)
    if contact:
        if name and not contact["name"]:
            db.update("contacts", contact["id"], {"name": name, "updated_at": now_iso()})
            contact["name"] = name
            reindex(contact["id"])
        return contact
    if not create:
        return None
    stamp = now_iso()
    cid = db.insert("contacts", {
        "name": name,
        "email": value if kind == "email" else None,
        "phone": value if kind == "phone" else None,
        "organization_id": org_for_email(value) if kind == "email" else None,
        "created_by": created_by,
        "created_at": stamp,
        "updated_at": stamp,
    })
    db.insert("contact_handles", {"contact_id": cid, "kind": kind, "value": value, "label": None})
    reindex(cid)
    return db.one("SELECT * FROM contacts WHERE id = ?", cid)


def get(contact_id: int | None) -> dict | None:
    if not contact_id:
        return None
    return db.one("SELECT * FROM contacts WHERE id = ?", contact_id)


def display_name(contact: dict | None, fallback: str = "Unknown") -> str:
    if not contact:
        return fallback
    return contact.get("name") or contact.get("email") or contact.get("phone") or fallback


def handles(contact_id: int) -> list[dict]:
    return db.query("SELECT kind, value, label FROM contact_handles WHERE contact_id = ? ORDER BY id", contact_id)


def summary(contact: dict | None) -> dict | None:
    """Compact form used in conversation lists and sidebars."""
    if not contact:
        return None
    org = db.one("SELECT id, name FROM organizations WHERE id = ?", contact["organization_id"]) if contact.get("organization_id") else None
    return {
        "id": contact["id"],
        "name": contact.get("name"),
        "display_name": display_name(contact),
        "email": contact.get("email"),
        "phone": contact.get("phone"),
        "title": contact.get("title"),
        "organization": org,
        "is_blocked": bool(contact.get("is_blocked")),
    }


def reindex(contact_id: int) -> None:
    c = get(contact_id)
    if not c:
        search.unindex("contact", contact_id)
        return
    hs = " ".join(h["value"] for h in handles(contact_id))
    search.index("contact", contact_id, c.get("name") or c.get("email") or c.get("phone"),
                 f"{hs} {c.get('title') or ''} {c.get('notes') or ''}")
