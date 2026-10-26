"""Who owes you and what you owe: aging, balances, open items."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pps_tools.books.models import Customer, LedgerEntry, Transaction, TransactionLink, Vendor
from pps_tools.books.services.accounts import system_account_id
from pps_tools.books.services.reports.engine import (Col, Params, Report, as_of_label, customer_scope,
                                                     period_label, register, report_link, txn_link)
from pps_tools.books.services.transactions import status as txn_status
from pps_tools.books.txn_types import SETTLE_LINKS, TXN_TYPES

AR_TYPES = ("invoice", "credit_memo", "payment", "customer_refund")
AP_TYPES = ("bill", "vendor_credit", "bill_payment")


@dataclass
class OpenItem:
    txn: Transaction
    open_cents: int  # signed: positive owed, negative credit
    due: date
    days_past_due: int


def open_items_as_of(s: Session, kind: str, as_of: Optional[date], party_ids: Optional[list[int]] = None
                     ) -> list[OpenItem]:
    """Open invoices/bills and unapplied credits, as they stood on ``as_of``."""
    as_of = as_of or date.today()
    types = AR_TYPES if kind == "ar" else AP_TYPES
    party = Transaction.customer_id if kind == "ar" else Transaction.vendor_id
    q = select(Transaction).where(Transaction.type.in_(types), Transaction.voided.is_(False),
                                  Transaction.date <= as_of, party.isnot(None))
    if party_ids is not None:
        q = q.where(party.in_(party_ids))
    txns = {t.id: t for t in s.scalars(q)}
    if not txns:
        return []
    dates = dict(s.execute(select(Transaction.id, Transaction.date)).all())
    settled: dict[int, int] = defaultdict(int)
    for link in s.scalars(select(TransactionLink).where(TransactionLink.link_type.in_(SETTLE_LINKS))):
        when = dates.get(link.via_txn_id) if link.via_txn_id else max(dates.get(link.from_txn_id, as_of),
                                                                       dates.get(link.to_txn_id, as_of))
        if when is None or when > as_of:
            continue
        settled[link.from_txn_id] += link.amount_cents
        settled[link.to_txn_id] += link.amount_cents
    out = []
    for t in txns.values():
        remaining = t.total_cents - settled.get(t.id, 0)
        if remaining == 0:
            continue
        sign = TXN_TYPES[t.type].open_sign
        due = t.due_date or t.date
        out.append(OpenItem(t, sign * remaining, due, max(0, (as_of - due).days)))
    out.sort(key=lambda o: (o.due, o.txn.date, o.txn.id))
    return out


def _buckets(p: Params) -> list[tuple[str, int, Optional[int]]]:
    """[(label, min_days, max_days)] starting with Current."""
    step, n = max(1, p.aging_interval or 30), max(1, p.aging_periods or 4)
    out = [("Current", 0, 0)]
    for i in range(n):
        lo, hi = i * step + 1, (i + 1) * step
        out.append((f"{lo} - {hi}", lo, hi))
    out.append((f"{n * step + 1} and over", n * step + 1, None))
    return out


def _bucket_index(days: int, buckets) -> int:
    for i, (_, lo, hi) in enumerate(buckets):
        if hi is None and days >= lo:
            return i
        if lo <= days <= (hi if hi is not None else days):
            return i
    return 0


def _party_names(s: Session, kind: str) -> dict[int, str]:
    model = Customer if kind == "ar" else Vendor
    return dict(s.execute(select(model.id, model.display_name)).all())


def _aging_summary(s: Session, p: Params, kind: str) -> Report:
    as_of = p.end or date.today()
    scope = customer_scope(s, p.customer_id) if kind == "ar" else ([p.vendor_id] if p.vendor_id else None)
    items = open_items_as_of(s, kind, as_of, scope)
    buckets = _buckets(p)
    names = _party_names(s, kind)
    key = "ar_aging_summary" if kind == "ar" else "ap_aging_summary"
    title = "A/R Aging Summary" if kind == "ar" else "A/P Aging Summary"
    r = Report(key, title, as_of_label(as_of))
    r.columns = [Col("name", "", "text")] + [Col(f"b{i}", label) for i, (label, _, _) in enumerate(buckets)] + [
        Col("total", "Total")]
    rows: dict[int, list[int]] = defaultdict(lambda: [0] * len(buckets))
    for it in items:
        party = it.txn.customer_id if kind == "ar" else it.txn.vendor_id
        rows[party][_bucket_index(it.days_past_due, buckets)] += it.open_cents
    totals = [0] * len(buckets)
    detail_key = "ar_aging_detail" if kind == "ar" else "ap_aging_detail"
    for party in sorted(rows, key=lambda pid: names.get(pid, "").lower()):
        vals = rows[party]
        if p.past_due_only and not any(vals[1:]):
            continue
        cells = {"name": names.get(party, "?"), "total": sum(vals)}
        cells.update({f"b{i}": v or None for i, v in enumerate(vals)})
        link_field = "customer_id" if kind == "ar" else "vendor_id"
        r.add(cells, 1, "data", link=report_link(detail_key, p, **{link_field: party}))
        totals = [a + b for a, b in zip(totals, vals)]
    cells = {"name": "TOTAL", "total": sum(totals)}
    cells.update({f"b{i}": v for i, v in enumerate(totals)})
    r.add(cells, 0, "grand")
    r.chart = {"type": "bar", "labels": [b[0] for b in buckets], "values": totals}
    return r


def _aging_detail(s: Session, p: Params, kind: str) -> Report:
    as_of = p.end or date.today()
    scope = customer_scope(s, p.customer_id) if kind == "ar" else ([p.vendor_id] if p.vendor_id else None)
    items = open_items_as_of(s, kind, as_of, scope)
    buckets = _buckets(p)
    names = _party_names(s, kind)
    key = "ar_aging_detail" if kind == "ar" else "ap_aging_detail"
    title = "A/R Aging Detail" if kind == "ar" else "A/P Aging Detail"
    r = Report(key, title, as_of_label(as_of))
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("name", "Customer" if kind == "ar" else "Vendor", "text"), Col("due", "Due date", "date"),
                 Col("past_due", "Past due", "int"), Col("amount", "Amount"), Col("open", "Open balance")]
    by_bucket: dict[int, list[OpenItem]] = defaultdict(list)
    for it in items:
        by_bucket[_bucket_index(it.days_past_due, buckets)].append(it)
    grand = 0
    for i in reversed(range(len(buckets))):
        group = by_bucket.get(i, [])
        if not group:
            continue
        if p.past_due_only and i == 0:
            continue
        label = buckets[i][0] + ("" if i == 0 else " days past due")
        r.add({"date": None, "type": label}, 0, "section")
        sub = 0
        for it in sorted(group, key=lambda o: (o.due, o.txn.id)):
            t = it.txn
            sign = TXN_TYPES[t.type].open_sign
            party = t.customer_id if kind == "ar" else t.vendor_id
            r.add({"date": t.date, "type": t.info.label, "num": t.number or "", "name": names.get(party, ""),
                   "due": it.due, "past_due": it.days_past_due, "amount": sign * t.total_cents,
                   "open": it.open_cents}, 1, "data", link=txn_link(t.id))
            sub += it.open_cents
        r.add({"type": f"Total for {label}", "open": sub}, 0, "subtotal")
        grand += sub
    r.add({"type": "TOTAL", "open": grand}, 0, "grand")
    return r


@register("ar_aging_summary", "A/R Aging Summary", "receivables",
          "How much each customer owes and how late it is.", kind="as_of",
          options=("customer", "aging"), default_preset="today")
def ar_aging_summary(s: Session, p: Params) -> Report:
    return _aging_summary(s, p, "ar")


@register("ar_aging_detail", "A/R Aging Detail", "receivables",
          "Every open invoice and credit, by how late it is.", kind="as_of",
          options=("customer", "aging"), default_preset="today")
def ar_aging_detail(s: Session, p: Params) -> Report:
    return _aging_detail(s, p, "ar")


@register("ap_aging_summary", "A/P Aging Summary", "payables",
          "How much you owe each vendor and how late it is.", kind="as_of",
          options=("vendor", "aging"), default_preset="today")
def ap_aging_summary(s: Session, p: Params) -> Report:
    return _aging_summary(s, p, "ap")


@register("ap_aging_detail", "A/P Aging Detail", "payables",
          "Every unpaid bill and vendor credit, by how late it is.", kind="as_of",
          options=("vendor", "aging"), default_preset="today")
def ap_aging_detail(s: Session, p: Params) -> Report:
    return _aging_detail(s, p, "ap")


def _ledger_party_balances(s: Session, kind: str, as_of: Optional[date]) -> dict[int, int]:
    acct = system_account_id(s, "ar" if kind == "ar" else "ap")
    from pps_tools.books.models import Account

    ids = list(s.scalars(select(Account.id).where(Account.type == ("ar" if kind == "ar" else "ap"))))
    if acct not in ids:
        ids.append(acct)
    col = LedgerEntry.customer_id if kind == "ar" else LedgerEntry.vendor_id
    q = select(col, func.sum(LedgerEntry.amount_cents)).where(LedgerEntry.account_id.in_(ids), col.isnot(None)) \
        .group_by(col)
    if as_of:
        q = q.where(LedgerEntry.date <= as_of)
    sign = 1 if kind == "ar" else -1
    return {pid: sign * int(v or 0) for pid, v in s.execute(q)}


def _balance_summary(s: Session, p: Params, kind: str) -> Report:
    as_of = p.end or date.today()
    bals = _ledger_party_balances(s, kind, as_of)
    names = _party_names(s, kind)
    key = "customer_balance_summary" if kind == "ar" else "vendor_balance_summary"
    title = "Customer Balance Summary" if kind == "ar" else "Vendor Balance Summary"
    r = Report(key, title, as_of_label(as_of))
    r.columns = [Col("name", "", "text"), Col("total", "Total")]
    total = 0
    detail = "customer_balance_detail" if kind == "ar" else "vendor_balance_detail"
    field = "customer_id" if kind == "ar" else "vendor_id"
    for pid in sorted(bals, key=lambda i: names.get(i, "").lower()):
        if not bals[pid] and not p.include_zero:
            continue
        r.add({"name": names.get(pid, "?"), "total": bals[pid]}, 1, "data",
              link=report_link(detail, p, **{field: pid}))
        total += bals[pid]
    r.add({"name": "TOTAL", "total": total}, 0, "grand")
    return r


def _balance_detail(s: Session, p: Params, kind: str) -> Report:
    as_of = p.end or date.today()
    scope = customer_scope(s, p.customer_id) if kind == "ar" else ([p.vendor_id] if p.vendor_id else None)
    items = open_items_as_of(s, kind, as_of, scope)
    names = _party_names(s, kind)
    key = "customer_balance_detail" if kind == "ar" else "vendor_balance_detail"
    title = "Customer Balance Detail" if kind == "ar" else "Vendor Balance Detail"
    r = Report(key, title, as_of_label(as_of))
    r.columns = [Col("date", "Date", "date"), Col("type", "Transaction type", "text"), Col("num", "Num", "text"),
                 Col("due", "Due date", "date"), Col("amount", "Amount"), Col("open", "Open balance"),
                 Col("balance", "Balance")]
    by_party: dict[int, list[OpenItem]] = defaultdict(list)
    for it in items:
        by_party[it.txn.customer_id if kind == "ar" else it.txn.vendor_id].append(it)
    grand = 0
    for pid in sorted(by_party, key=lambda i: names.get(i, "").lower()):
        r.add({"date": None, "type": names.get(pid, "?")}, 0, "section")
        running = 0
        for it in sorted(by_party[pid], key=lambda o: (o.txn.date, o.txn.id)):
            t = it.txn
            running += it.open_cents
            r.add({"date": t.date, "type": t.info.label, "num": t.number or "", "due": it.due,
                   "amount": TXN_TYPES[t.type].open_sign * t.total_cents, "open": it.open_cents,
                   "balance": running}, 1, "data", link=txn_link(t.id))
        r.add({"type": f"Total for {names.get(pid, '?')}", "open": running}, 0, "subtotal")
        grand += running
    r.add({"type": "TOTAL", "open": grand}, 0, "grand")
    return r


@register("customer_balance_summary", "Customer Balance Summary", "receivables",
          "Each customer's balance.", kind="as_of", default_preset="today")
def customer_balance_summary(s: Session, p: Params) -> Report:
    return _balance_summary(s, p, "ar")


@register("customer_balance_detail", "Customer Balance Detail", "receivables",
          "Each customer's open invoices and credits.", kind="as_of", options=("customer",),
          default_preset="today")
def customer_balance_detail(s: Session, p: Params) -> Report:
    return _balance_detail(s, p, "ar")


@register("vendor_balance_summary", "Vendor Balance Summary", "payables", "What you owe each vendor.",
          kind="as_of", default_preset="today")
def vendor_balance_summary(s: Session, p: Params) -> Report:
    return _balance_summary(s, p, "ap")


@register("vendor_balance_detail", "Vendor Balance Detail", "payables",
          "Each vendor's unpaid bills and credits.", kind="as_of", options=("vendor",), default_preset="today")
def vendor_balance_detail(s: Session, p: Params) -> Report:
    return _balance_detail(s, p, "ap")


@register("open_invoices", "Open Invoices", "receivables", "Invoices not yet paid in full.", kind="as_of",
          options=("customer",), default_preset="today")
def open_invoices(s: Session, p: Params) -> Report:
    as_of = p.end or date.today()
    items = [i for i in open_items_as_of(s, "ar", as_of, customer_scope(s, p.customer_id))
             if i.txn.type == "invoice"]
    names = _party_names(s, "ar")
    r = Report("open_invoices", "Open Invoices", as_of_label(as_of))
    r.columns = [Col("date", "Date", "date"), Col("num", "Num", "text"), Col("terms", "Terms", "text"),
                 Col("due", "Due date", "date"), Col("past_due", "Past due", "int"), Col("amount", "Amount"),
                 Col("open", "Open balance")]
    by_party: dict[int, list[OpenItem]] = defaultdict(list)
    for it in items:
        by_party[it.txn.customer_id].append(it)
    grand = 0
    for pid in sorted(by_party, key=lambda i: names.get(i, "").lower()):
        r.add({"date": None, "num": names.get(pid, "")}, 0, "section")
        sub = 0
        for it in by_party[pid]:
            t = it.txn
            r.add({"date": t.date, "num": t.number or "", "terms": t.terms.name if t.terms else "", "due": it.due,
                   "past_due": it.days_past_due, "amount": t.total_cents, "open": it.open_cents}, 1, "data",
                  link=txn_link(t.id))
            sub += it.open_cents
        r.add({"num": f"Total for {names.get(pid, '')}", "open": sub}, 0, "subtotal")
        grand += sub
    r.add({"num": "TOTAL", "open": grand}, 0, "grand")
    return r


@register("collections", "Collections Report", "receivables",
          "Overdue invoices with the customer's phone and email.", kind="as_of", default_preset="today")
def collections(s: Session, p: Params) -> Report:
    as_of = p.end or date.today()
    items = [i for i in open_items_as_of(s, "ar", as_of) if i.txn.type == "invoice" and i.days_past_due > 0]
    r = Report("collections", "Collections Report", as_of_label(as_of))
    r.columns = [Col("date", "Date", "date"), Col("num", "Num", "text"), Col("due", "Due date", "date"),
                 Col("past_due", "Past due", "int"), Col("contact", "Phone / email", "text"),
                 Col("amount", "Amount"), Col("open", "Open balance")]
    by_party: dict[int, list[OpenItem]] = defaultdict(list)
    for it in items:
        by_party[it.txn.customer_id].append(it)
    customers = {c.id: c for c in s.scalars(select(Customer).where(Customer.id.in_(list(by_party))))} \
        if by_party else {}
    grand = 0
    for pid in sorted(by_party, key=lambda i: customers[i].display_name.lower()):
        c = customers[pid]
        r.add({"num": c.display_name, "contact": " · ".join(x for x in (c.phone, c.email) if x)}, 0, "section")
        sub = 0
        for it in by_party[pid]:
            t = it.txn
            r.add({"date": t.date, "num": t.number or "", "due": it.due, "past_due": it.days_past_due,
                   "amount": t.total_cents, "open": it.open_cents}, 1, "data", link=txn_link(t.id))
            sub += it.open_cents
        r.add({"num": f"Total for {c.display_name}", "open": sub}, 0, "subtotal")
        grand += sub
    r.add({"num": "TOTAL", "open": grand}, 0, "grand")
    return r


@register("invoice_list", "Invoice List", "sales", "Invoices issued in a period with their status.",
          options=("customer",), default_preset="this_month")
def invoice_list(s: Session, p: Params) -> Report:
    q = select(Transaction).where(Transaction.type == "invoice")
    if p.start:
        q = q.where(Transaction.date >= p.start)
    if p.end:
        q = q.where(Transaction.date <= p.end)
    if p.customer_id:
        q = q.where(Transaction.customer_id.in_(customer_scope(s, p.customer_id)))
    names = _party_names(s, "ar")
    r = Report("invoice_list", "Invoice List", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("num", "Num", "text"), Col("name", "Customer", "text"),
                 Col("due", "Due date", "date"), Col("status", "Status", "text"), Col("amount", "Amount"),
                 Col("open", "Open balance")]
    total = open_total = 0
    for t in s.scalars(q.order_by(Transaction.date, Transaction.id)):
        amt = 0 if t.voided else t.total_cents
        r.add({"date": t.date, "num": t.number or "", "name": names.get(t.customer_id, ""), "due": t.due_date,
               "status": txn_status(t)[1], "amount": amt, "open": t.balance_cents}, 1, "data", link=txn_link(t.id))
        total += amt
        open_total += t.balance_cents
    r.add({"num": "TOTAL", "amount": total, "open": open_total}, 0, "grand")
    return r


@register("unpaid_bills", "Unpaid Bills", "payables", "Bills you haven't paid, by vendor.", kind="as_of",
          options=("vendor",), default_preset="today")
def unpaid_bills(s: Session, p: Params) -> Report:
    as_of = p.end or date.today()
    items = [i for i in open_items_as_of(s, "ap", as_of, [p.vendor_id] if p.vendor_id else None)
             if i.txn.type == "bill"]
    names = _party_names(s, "ap")
    r = Report("unpaid_bills", "Unpaid Bills", as_of_label(as_of))
    r.columns = [Col("date", "Date", "date"), Col("num", "Num", "text"), Col("due", "Due date", "date"),
                 Col("past_due", "Past due", "int"), Col("amount", "Amount"), Col("open", "Open balance")]
    by_party: dict[int, list[OpenItem]] = defaultdict(list)
    for it in items:
        by_party[it.txn.vendor_id].append(it)
    grand = 0
    for pid in sorted(by_party, key=lambda i: names.get(i, "").lower()):
        r.add({"num": names.get(pid, "")}, 0, "section")
        sub = 0
        for it in by_party[pid]:
            t = it.txn
            r.add({"date": t.date, "num": t.number or "", "due": it.due, "past_due": it.days_past_due,
                   "amount": t.total_cents, "open": it.open_cents}, 1, "data", link=txn_link(t.id))
            sub += it.open_cents
        r.add({"num": f"Total for {names.get(pid, '')}", "open": sub}, 0, "subtotal")
        grand += sub
    r.add({"num": "TOTAL", "open": grand}, 0, "grand")
    return r


@register("bill_payment_list", "Bill Payment List", "payables", "Bill payments made in a period.",
          options=("vendor",), default_preset="this_month")
def bill_payment_list(s: Session, p: Params) -> Report:
    q = select(Transaction).where(Transaction.type == "bill_payment", Transaction.voided.is_(False))
    if p.start:
        q = q.where(Transaction.date >= p.start)
    if p.end:
        q = q.where(Transaction.date <= p.end)
    if p.vendor_id:
        q = q.where(Transaction.vendor_id == p.vendor_id)
    names = _party_names(s, "ap")
    r = Report("bill_payment_list", "Bill Payment List", period_label(p))
    r.columns = [Col("date", "Date", "date"), Col("num", "Num", "text"), Col("name", "Vendor", "text"),
                 Col("account", "Payment account", "text"), Col("bills", "Bills paid", "text"),
                 Col("amount", "Amount")]
    total = 0
    for t in s.scalars(q.order_by(Transaction.date, Transaction.id)):
        bills = ", ".join(sorted(link.to_txn.number or f"#{link.to_txn_id}" for link in t.links_out
                                 if link.link_type == "bill_payment"))
        r.add({"date": t.date, "num": t.number or "", "name": names.get(t.vendor_id, ""),
               "account": t.account.full_name if t.account else "", "bills": bills, "amount": t.total_cents},
              1, "data", link=txn_link(t.id))
        total += t.total_cents
    r.add({"num": "TOTAL", "amount": total}, 0, "grand")
    return r


@register("statement_list", "Statement List", "receivables", "Customer statements you've sent.",
          options=("customer",), default_preset="this_year")
def statement_list(s: Session, p: Params) -> Report:
    from pps_tools.books.models import Statement

    q = select(Statement).order_by(Statement.statement_date.desc())
    if p.start:
        q = q.where(Statement.statement_date >= p.start)
    if p.end:
        q = q.where(Statement.statement_date <= p.end)
    if p.customer_id:
        q = q.where(Statement.customer_id == p.customer_id)
    names = _party_names(s, "ar")
    r = Report("statement_list", "Statement List", period_label(p))
    r.columns = [Col("date", "Statement date", "date"), Col("name", "Customer", "text"),
                 Col("kind", "Type", "text"), Col("sent", "Sent", "text"), Col("balance", "Balance")]
    for st in s.scalars(q):
        r.add({"date": st.statement_date, "name": names.get(st.customer_id, ""),
               "kind": st.kind.replace("_", " ").title(), "sent": f"{st.sent_at:%m/%d/%Y}" if st.sent_at else "",
               "balance": st.balance_cents}, 1, "data", link=f"/customers/{st.customer_id}/statement/{st.id}")
    return r
