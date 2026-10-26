"""Audit trail: who changed what, with before/after snapshots."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from pps_tools.books.models import AuditLog, Transaction, User
from pps_tools.books.money import fmt


def snapshot(txn: Transaction) -> dict[str, Any]:
    """A JSON-safe picture of a transaction for the audit history."""
    def val(v: Any) -> Any:
        if v is None or isinstance(v, (int, str, bool, float)):
            return v
        return str(v)

    header_fields = [
        "type", "number", "date", "due_date", "customer_id", "vendor_id", "employee_id", "tax_agency_id",
        "account_id", "to_account_id", "terms_id", "payment_method_id", "ref_no", "memo", "message",
        "class_id", "location_id", "subtotal_cents", "discount_cents", "tax_cents", "shipping_cents",
        "total_cents", "balance_cents", "status", "voided", "tax_rate_id",
    ]
    data: dict[str, Any] = {f: val(getattr(txn, f)) for f in header_fields}
    data["entity"] = txn.entity_name
    data["lines"] = [
        {
            "kind": ln.kind, "item_id": ln.item_id, "account_id": ln.account_id,
            "description": ln.description, "qty": val(ln.qty), "rate": val(ln.rate),
            "amount_cents": ln.amount_cents, "posting_type": ln.posting_type, "taxable": ln.taxable,
            "customer_id": ln.customer_id, "class_id": ln.class_id, "billable": ln.billable,
        }
        for ln in txn.lines
    ]
    data["links"] = [
        {"to": ln.to_txn_id, "type": ln.link_type, "amount_cents": ln.amount_cents} for ln in txn.links_out
    ]
    return data


def record(s: Session, user: Optional[User], action: str, object_type: str, object_id: Optional[int],
           summary: str = "", before: Optional[dict] = None, after: Optional[dict] = None,
           txn: Optional[Transaction] = None, name: Optional[str] = None, ip: Optional[str] = None) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        user_name=user.name if user else "System",
        action=action,
        object_type=object_type,
        object_id=object_id,
        summary=summary[:500],
        before=before,
        after=after,
        name=name,
        ip=ip,
    )
    if txn is not None:
        entry.txn_type = txn.type
        entry.txn_date = txn.date
        entry.amount_cents = txn.total_cents
        entry.name = name or txn.entity_name
        if not summary:
            label = txn.info.label
            num = f" {txn.number}" if txn.number else ""
            entry.summary = f"{action.title()} {label}{num} {fmt(txn.total_cents)}"
    s.add(entry)
    return entry


def changes(before: Optional[dict], after: Optional[dict]) -> list[tuple[str, Any, Any]]:
    """Field-level differences for the history view."""
    before = before or {}
    after = after or {}
    out = []
    for key in sorted(set(before) | set(after)):
        if key == "lines" or key == "links":
            if before.get(key) != after.get(key):
                out.append((key, f"{len(before.get(key) or [])} rows", f"{len(after.get(key) or [])} rows"))
            continue
        if before.get(key) != after.get(key):
            out.append((key, before.get(key), after.get(key)))
    return out
