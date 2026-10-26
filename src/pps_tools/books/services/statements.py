"""Customer statements: balance forward, open item, and transaction statements."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pps_tools.books.models import Account, Customer, LedgerEntry, Statement, Transaction
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.reports.receivables import open_items_as_of
from pps_tools.books.txn_types import TXN_TYPES

AR_DOCS = ("invoice", "payment", "credit_memo", "customer_refund", "journal_entry")


def _ar_ids(s: Session) -> list[int]:
    return list(s.scalars(select(Account.id).where(Account.type == "ar")))


def balances(s: Session, as_of: date) -> dict[int, int]:
    ids = _ar_ids(s)
    return {cid: int(v or 0) for cid, v in s.execute(
        select(LedgerEntry.customer_id, func.sum(LedgerEntry.amount_cents))
        .where(LedgerEntry.account_id.in_(ids), LedgerEntry.customer_id.isnot(None), LedgerEntry.date <= as_of)
        .group_by(LedgerEntry.customer_id))}


def overdue_customers(s: Session, as_of: date) -> set[int]:
    return {it.txn.customer_id for it in open_items_as_of(s, "ar", as_of) if it.days_past_due > 0 and it.open_cents > 0}


def create(s: Session, customer: Customer, kind: str, statement_date: date, start: Optional[date],
           end: Optional[date]) -> Statement:
    if kind not in ("balance_forward", "open_item", "transaction"):
        kind = "balance_forward"
    st = Statement(customer_id=customer.id, kind=kind, statement_date=statement_date, start_date=start, end_date=end,
                   public_token=tx.new_token())
    st.customer = customer
    s.add(st)
    s.flush()
    st.balance_cents = build(s, st)["amount_due"]
    if not customer.portal_token:
        customer.portal_token = tx.new_token()
    return st


def _describe(t: Transaction) -> str:
    label = TXN_TYPES[t.type].label
    num = f" #{t.number}" if t.number else ""
    if t.type == "invoice" and t.due_date:
        return f"{label}{num} — due {t.due_date:%m/%d/%Y}"
    if t.type == "payment":
        return f"Payment{(' — ' + t.payment_method.name) if t.payment_method else ''}{(' ' + t.ref_no) if t.ref_no else ''}"
    return f"{label}{num}"


def build(s: Session, st: Statement) -> dict:
    """Lines, aging and amount due for a statement."""
    as_of = st.statement_date
    cid = st.customer_id
    ids = _ar_ids(s)
    items = open_items_as_of(s, "ar", as_of, [cid])
    aging = {"current": 0, "1_30": 0, "31_60": 0, "61_90": 0, "over_90": 0}
    for it in items:
        d = it.days_past_due
        key = "current" if d <= 0 else "1_30" if d <= 30 else "31_60" if d <= 60 else "61_90" if d <= 90 else "over_90"
        aging[key] += it.open_cents
    amount_due = sum(it.open_cents for it in items)
    lines = []
    opening = None
    if st.kind == "open_item":
        since = as_of - timedelta(days=365)
        running = 0
        for it in sorted(items, key=lambda i: (i.txn.date, i.txn.id)):
            if it.txn.date < since:
                continue
            running += it.open_cents
            lines.append({"date": it.txn.date, "description": _describe(it.txn), "amount": it.open_cents,
                          "balance": running})
    else:
        start = st.start_date or (as_of - timedelta(days=30))
        end = min(st.end_date or as_of, as_of)
        entries = s.execute(select(LedgerEntry.txn_id, func.sum(LedgerEntry.amount_cents))
                            .where(LedgerEntry.account_id.in_(ids), LedgerEntry.customer_id == cid,
                                   LedgerEntry.date >= start, LedgerEntry.date <= end)
                            .group_by(LedgerEntry.txn_id)).all()
        txns = {t.id: t for t in s.scalars(select(Transaction).where(Transaction.id.in_([e[0] for e in entries])))} \
            if entries else {}
        if st.kind == "balance_forward":
            opening = int(s.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).where(
                LedgerEntry.account_id.in_(ids), LedgerEntry.customer_id == cid, LedgerEntry.date < start)) or 0)
        running = opening or 0
        for txn_id, amount in sorted(entries, key=lambda e: (txns[e[0]].date, e[0])):
            t = txns[txn_id]
            running += int(amount)
            lines.append({"date": t.date, "description": _describe(t), "amount": int(amount), "balance": running})
        if st.kind == "balance_forward":
            amount_due = running
    return {"lines": lines, "aging": aging, "amount_due": amount_due, "opening": opening}
