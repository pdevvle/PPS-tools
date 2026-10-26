"""Numbers for the home dashboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pps_tools.books.models import (Account, BankFeedItem, Item, LedgerEntry, RecurringTemplate, Transaction,
                                    TransactionLink)
from pps_tools.books.services import dates as D
from pps_tools.books.services.accounts import balances_by_account, system_account_id
from pps_tools.books.services.reports.engine import Aggregator, compare_range, Params
from pps_tools.books.services.reports.financial import pl_summary


@dataclass
class Snapshot:
    start: Optional[date]
    end: Optional[date]
    basis: str
    income: int = 0
    expenses: int = 0
    net: int = 0
    prev_income: int = 0
    prev_expenses: int = 0
    prev_net: int = 0
    prev_label: str = ""
    months: list[dict] = field(default_factory=list)  # {label, income, expenses}
    expense_categories: list[dict] = field(default_factory=list)  # {name, amount, account_id}
    open_invoices: int = 0
    open_invoice_count: int = 0
    overdue: int = 0
    overdue_count: int = 0
    paid_30: int = 0
    deposited_30: int = 0
    bank_accounts: list[dict] = field(default_factory=list)
    cash_total: int = 0
    cash_trend: list[dict] = field(default_factory=list)  # {label, date, balance}
    bills_due: int = 0
    bills_due_count: int = 0
    tasks: list[dict] = field(default_factory=list)


def build(s: Session, start: Optional[date], end: Optional[date], basis: str = "accrual",
          today: Optional[date] = None) -> Snapshot:
    today = today or date.today()
    snap = Snapshot(start, end, basis)
    pl = pl_summary(s, start, end, basis)
    snap.income = pl["income"] + pl["other_income"]
    snap.expenses = pl["cogs"] + pl["expense"] + pl["other_expense"]
    snap.net = pl["net"]
    p = Params(preset="custom", start=start, end=end, compare="prev_period")
    ps, pe, label = compare_range(p)
    if ps:
        prev = pl_summary(s, ps, pe, basis)
        snap.prev_income = prev["income"] + prev["other_income"]
        snap.prev_expenses = prev["cogs"] + prev["expense"] + prev["other_expense"]
        snap.prev_net = prev["net"]
        snap.prev_label = f"{ps:%b %d} – {pe:%b %d, %Y}"

    # Income vs expenses for the last 6 months (ending at the period end).
    anchor = (end or today).replace(day=1)
    agg = Aggregator(s, basis)
    types = dict(s.execute(select(Account.id, Account.type)).all())
    for i in range(5, -1, -1):
        m_start = D.add_months(anchor, -i)
        m_end = D.month_end(m_start)
        vals = agg.by_account(m_start, m_end)
        inc = -sum(v for aid, v in vals.items() if types.get(aid) in ("income", "other_income"))
        exp = sum(v for aid, v in vals.items() if types.get(aid) in ("cogs", "expense", "other_expense"))
        snap.months.append({"label": m_start.strftime("%b"), "full": m_start.strftime("%B %Y"),
                            "income": inc, "expenses": exp})

    # Top expense categories in the period.
    vals = agg.by_account(start, end)
    accounts = {a.id: a for a in s.scalars(select(Account))}
    cats = sorted(((aid, v) for aid, v in vals.items()
                   if types.get(aid) in ("cogs", "expense", "other_expense") and v > 0), key=lambda x: -x[1])
    for aid, v in cats[:5]:
        snap.expense_categories.append({"name": accounts[aid].name, "amount": v, "account_id": aid})
    if len(cats) > 5:
        snap.expense_categories.append({"name": f"Everything else ({len(cats) - 5})",
                                        "amount": sum(v for _, v in cats[5:]), "account_id": None})

    # Receivables
    inv_q = select(Transaction).where(Transaction.type == "invoice", Transaction.voided.is_(False),
                                      Transaction.balance_cents > 0)
    for inv in s.scalars(inv_q):
        snap.open_invoices += inv.balance_cents
        snap.open_invoice_count += 1
        if inv.due_date and inv.due_date < today:
            snap.overdue += inv.balance_cents
            snap.overdue_count += 1
    since = today - timedelta(days=30)
    uf = system_account_id(s, "undeposited_funds")
    for pay in s.scalars(select(Transaction).where(Transaction.type.in_(("payment", "sales_receipt")),
                                                   Transaction.voided.is_(False), Transaction.date >= since)):
        snap.paid_30 += pay.total_cents
        if pay.account_id != uf or s.scalar(select(TransactionLink.id).where(
                TransactionLink.to_txn_id == pay.id, TransactionLink.link_type == "deposit").limit(1)):
            snap.deposited_30 += pay.total_cents

    # Bills due within a week
    for bill in s.scalars(select(Transaction).where(Transaction.type == "bill", Transaction.voided.is_(False),
                                                    Transaction.balance_cents > 0)):
        if bill.due_date and bill.due_date <= today + timedelta(days=7):
            snap.bills_due += bill.balance_cents
            snap.bills_due_count += 1

    # Bank and card accounts
    bals = balances_by_account(s)
    for a in sorted((a for a in accounts.values() if a.type in ("bank", "credit_card") and a.active),
                    key=lambda a: (a.type != "bank", a.number or "", a.name)):
        review = s.scalar(select(func.count(BankFeedItem.id)).where(BankFeedItem.account_id == a.id,
                                                                     BankFeedItem.status == "review")) or 0
        last_feed = s.scalars(select(BankFeedItem).where(BankFeedItem.account_id == a.id)
                              .order_by(BankFeedItem.date.desc()).limit(1)).first()
        from pps_tools.books.models import BankImportBatch

        stmt = s.scalars(select(BankImportBatch).where(BankImportBatch.account_id == a.id,
                                                       BankImportBatch.statement_balance_cents.isnot(None))
                         .order_by(BankImportBatch.created_at.desc()).limit(1)).first()
        books = bals.get(a.id, 0) * a.normal
        snap.bank_accounts.append({"account": a, "books": books, "review": review,
                                   "bank_balance": stmt.statement_balance_cents if stmt else None,
                                   "updated": last_feed.date if last_feed else None})
        if a.type == "bank":
            snap.cash_total += books
    # Cash trend: month-end bank balances for the last 6 months.
    bank_ids = [a.id for a in accounts.values() if a.type == "bank"]
    for i in range(5, -1, -1):
        m_end = D.month_end(D.add_months(anchor, -i))
        point = min(m_end, today) if m_end >= anchor else m_end
        total = s.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).where(
            LedgerEntry.account_id.in_(bank_ids), LedgerEntry.date <= point)) if bank_ids else 0
        snap.cash_trend.append({"label": point.strftime("%b"), "date": point, "balance": int(total or 0)})

    # To-do list
    review_total = sum(b["review"] for b in snap.bank_accounts)
    if review_total:
        snap.tasks.append({"label": f"{review_total} bank transaction{'s' if review_total != 1 else ''} to review",
                           "endpoint": "banking.feed", "args": {}})
    if snap.overdue_count:
        snap.tasks.append({"label": f"{snap.overdue_count} overdue invoice{'s' if snap.overdue_count != 1 else ''}",
                           "endpoint": "sales.invoices", "args": {"status": "overdue"}})
    if snap.bills_due_count:
        snap.tasks.append({"label": f"{snap.bills_due_count} bill{'s' if snap.bills_due_count != 1 else ''} due this week",
                           "endpoint": "expenses.pay_bills", "args": {}})
    unsent = s.scalar(select(func.count(Transaction.id)).where(
        Transaction.type == "invoice", Transaction.sent_at.is_(None), Transaction.voided.is_(False),
        Transaction.balance_cents > 0)) or 0
    if unsent:
        snap.tasks.append({"label": f"{unsent} unpaid invoice{'s' if unsent != 1 else ''} not sent yet",
                           "endpoint": "sales.invoices", "args": {"status": "unsent"}})
    reminders = s.scalar(select(func.count(RecurringTemplate.id)).where(
        RecurringTemplate.mode == "reminder", RecurringTemplate.active.is_(True),
        RecurringTemplate.next_date <= today)) or 0
    if reminders:
        snap.tasks.append({"label": f"{reminders} recurring reminder{'s' if reminders != 1 else ''} due",
                           "endpoint": "recurring.index", "args": {}})
    low = [it for it in s.scalars(select(Item).where(Item.type == "inventory", Item.active.is_(True))) if it.low_stock]
    if low:
        snap.tasks.append({"label": f"{len(low)} product{'s' if len(low) != 1 else ''} low in stock",
                           "endpoint": "reports.view", "args": {"key": "low_stock"}})
    needs_review = s.scalar(select(func.count(Transaction.id)).where(Transaction.needs_review.is_(True))) or 0
    if needs_review:
        snap.tasks.append({"label": f"{needs_review} automatic transaction{'s' if needs_review != 1 else ''} to check",
                           "endpoint": "reports.view", "args": {"key": "automatic_transactions"}})
    from pps_tools.books.models import Attachment

    inbox = s.scalar(select(func.count(Attachment.id)).where(Attachment.receipt_status == "inbox")) or 0
    if inbox:
        snap.tasks.append({"label": f"{inbox} receipt{'s' if inbox != 1 else ''} waiting", "endpoint": "banking.receipts",
                           "args": {}})
    return snap
