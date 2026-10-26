"""Cash-basis view of the ledger.

On the accrual books an invoice hits income the day it's issued. On a cash
basis that income lands as the invoice is paid: each payment (or credit)
applied to it recognizes the same share of every one of the invoice's
entries, dated when the money moved. Bills, credit memos and vendor
credits work the same way. Everything else (sales receipts, expenses,
checks, deposits, journal entries...) is already cash and passes through.

Shares are computed cumulatively, so the last payment recognizes exactly
what's left and a fully paid invoice matches its accrual entries to the
cent; each slice is balanced so the cash-basis balance sheet balances too.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from pps_tools.books.models import LedgerEntry, Transaction, TransactionLink
from pps_tools.books.money import round_cents
from pps_tools.books.txn_types import SETTLE_LINKS

DEFERRED = ("invoice", "credit_memo", "bill", "vendor_credit")


@dataclass
class VEntry:
    """A ledger entry as it falls on the cash basis."""

    txn_id: int
    date: date
    account_id: int
    amount_cents: int
    customer_id: Optional[int]
    vendor_id: Optional[int]
    employee_id: Optional[int]
    item_id: Optional[int]
    class_id: Optional[int]
    location_id: Optional[int]
    line_id: Optional[int]
    memo: Optional[str]
    source_txn_id: int  # the payment/credit that triggered recognition (== txn_id if direct)


def _v(e: LedgerEntry, when: date, amount: int, source: int) -> VEntry:
    return VEntry(e.txn_id, when, e.account_id, amount, e.customer_id, e.vendor_id, e.employee_id,
                  e.item_id, e.class_id, e.location_id, e.line_id, e.memo, source)


def entries(s: Session, end: Optional[date] = None, account_ids: Optional[Iterable[int]] = None) -> list[VEntry]:
    """Every entry on the cash basis, dated on or before ``end``."""
    acct_filter = set(account_ids) if account_ids is not None else None
    out: list[VEntry] = []

    q = (select(LedgerEntry).join(Transaction, Transaction.id == LedgerEntry.txn_id)
         .where(Transaction.type.notin_(DEFERRED)))
    if end is not None:
        q = q.where(LedgerEntry.date <= end)
    for e in s.scalars(q):
        if acct_filter is None or e.account_id in acct_filter:
            out.append(_v(e, e.date, e.amount_cents, e.txn_id))

    docs = {t.id: t for t in s.scalars(select(Transaction).where(Transaction.type.in_(DEFERRED),
                                                                 Transaction.voided.is_(False)))}
    if not docs:
        return out
    doc_entries: dict[int, list[LedgerEntry]] = defaultdict(list)
    for e in s.scalars(select(LedgerEntry).where(LedgerEntry.txn_id.in_(list(docs)))):
        doc_entries[e.txn_id].append(e)

    links = s.scalars(select(TransactionLink).where(TransactionLink.link_type.in_(SETTLE_LINKS))).all()
    txn_dates = dict(s.execute(select(Transaction.id, Transaction.date)).all())
    settlements: dict[int, list[tuple[date, int, int]]] = defaultdict(list)
    for link in links:
        for doc_id in (link.from_txn_id, link.to_txn_id):
            if doc_id not in docs:
                continue
            if link.via_txn_id and link.via_txn_id in txn_dates:
                when = txn_dates[link.via_txn_id]
            elif link.link_type in ("credit", "vendor_credit"):
                when = max(txn_dates.get(link.from_txn_id, docs[doc_id].date),
                           txn_dates.get(link.to_txn_id, docs[doc_id].date))
            else:
                when = txn_dates.get(link.from_txn_id, docs[doc_id].date)
            when = max(when, docs[doc_id].date)
            other = link.to_txn_id if doc_id == link.from_txn_id else link.from_txn_id
            settlements[doc_id].append((when, link.amount_cents, other))

    for doc_id, doc in docs.items():
        ents = doc_entries.get(doc_id, [])
        if not ents:
            continue
        total = doc.total_cents
        if total == 0:
            for e in ents:
                if (end is None or e.date <= end) and (acct_filter is None or e.account_id in acct_filter):
                    out.append(_v(e, e.date, e.amount_cents, doc_id))
            continue
        applied = 0
        recognized = {e.id: 0 for e in ents}
        for when, amount, source in sorted(settlements.get(doc_id, []), key=lambda x: (x[0], x[2])):
            if end is not None and when > end:
                break
            applied = min(applied + amount, total)
            fraction = Decimal(applied) / Decimal(total)
            slice_: list[tuple[LedgerEntry, int]] = []
            for e in ents:
                target = round_cents(Decimal(e.amount_cents) * fraction / 100)
                slice_.append((e, target - recognized[e.id]))
                recognized[e.id] = target
            residual = sum(a for _, a in slice_)
            if residual and slice_:
                # Keep each slice balanced: park rounding on the largest entry.
                i = max(range(len(slice_)), key=lambda k: abs(slice_[k][0].amount_cents))
                e, a = slice_[i]
                slice_[i] = (e, a - residual)
                recognized[e.id] -= residual
            for e, a in slice_:
                if a and (acct_filter is None or e.account_id in acct_filter):
                    out.append(_v(e, when, a, source))
    return out
