"""Recurring transactions, payment reminders, late fees and scheduled report emails.

``run_scheduled`` is the one entry point: the ``pps books run-scheduled``
command calls it from cron, and the app calls it at most once an hour while
people use it, so a laptop install keeps up without a cron job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from pps_tools.books.db import utcnow
from pps_tools.books.models import RecurringTemplate, SavedReport, Transaction, User
from pps_tools.books.money import cents, percent_of
from pps_tools.books.services import prefs
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.dates import add_months, next_occurrence
from pps_tools.books.services.errors import BooksError, ValidationError
from pps_tools.books.txn_types import TXN_TYPES

log = logging.getLogger(__name__)

RECURRABLE = ("invoice", "estimate", "sales_receipt", "credit_memo", "refund_receipt", "delayed_charge",
              "delayed_credit", "bill", "expense", "check", "vendor_credit", "cc_credit", "purchase_order",
              "deposit", "transfer", "journal_entry", "cc_payment")


def template_payload(txn: Transaction) -> dict:
    data = tx.to_payload(txn, for_copy=True)
    for key in ("date", "due_date", "number", "applications", "deposits", "credits"):
        data.pop(key, None)
    for ln in data.get("lines") or []:
        ln.pop("source_type", None)
        ln.pop("source_id", None)
    return data


def save_template(s: Session, tpl: RecurringTemplate, payload: dict) -> RecurringTemplate:
    if tpl.txn_type not in RECURRABLE:
        raise ValidationError("That kind of transaction can't recur.")
    if not tpl.name:
        raise ValidationError("Name the template.")
    dup = s.scalar(select(RecurringTemplate.id).where(RecurringTemplate.name == tpl.name,
                                                      RecurringTemplate.id != (tpl.id or 0)))
    if dup:
        raise ValidationError("Another template has that name.")
    payload = dict(payload)
    payload["type"] = tpl.txn_type
    for key in ("date", "due_date", "number"):
        payload.pop(key, None)
    tpl.payload = payload
    tpl.customer_id = int(payload["customer_id"]) if payload.get("customer_id") else None
    tpl.vendor_id = int(payload["vendor_id"]) if payload.get("vendor_id") else None
    if tpl.next_date is None or (tpl.next_date < tpl.start_date and tpl.occurrences == 0):
        tpl.next_date = tpl.start_date
    # Remember a rough amount for the list (validated for real when it runs).
    total = 0
    for ln in payload.get("lines") or []:
        if ln.get("amount_cents") is not None:
            total += int(ln["amount_cents"])
        elif ln.get("debit_cents"):
            total += int(ln["debit_cents"])
        elif ln.get("qty") and ln.get("rate"):
            total += cents(Decimal(str(ln["qty"])) * Decimal(str(ln["rate"])))
        elif ln.get("amount"):
            total += cents(ln["amount"])
    tpl.amount_cents = total or int(payload.get("amount_cents") or 0)
    if tpl.id is None:
        s.add(tpl)
    s.flush()
    return tpl


def advance(tpl: RecurringTemplate) -> None:
    tpl.occurrences = (tpl.occurrences or 0) + 1
    nxt = next_occurrence(tpl.next_date, tpl.interval, tpl.every, tpl.day_of_week, tpl.day_of_month,
                          tpl.month_of_year)
    if (tpl.end_date and nxt > tpl.end_date) or (tpl.max_occurrences and tpl.occurrences >= tpl.max_occurrences):
        tpl.active = False
        tpl.next_date = None
    else:
        tpl.next_date = nxt


def create_from_template(s: Session, tpl: RecurringTemplate, on: Optional[date] = None,
                         user: Optional[User] = None) -> Transaction:
    data = dict(tpl.payload or {})
    data["type"] = tpl.txn_type
    data["date"] = (on or tpl.next_date or date.today()).isoformat()
    data["recurring_template_id"] = tpl.id
    lines = []
    for ln in data.get("lines") or []:
        ln = dict(ln)
        ln.pop("id", None)
        lines.append(ln)
    data["lines"] = lines
    return tx.save(s, data, user=user, source="recurring")


@dataclass
class RunReport:
    created: list[Transaction] = field(default_factory=list)
    sent: int = 0
    autopaid: int = 0
    reminders: int = 0
    late_fees: int = 0
    reports_emailed: int = 0
    errors: list[str] = field(default_factory=list)


def run_scheduled(s: Session, config, today: Optional[date] = None, base_url: str = "") -> RunReport:
    today = today or date.today()
    out = RunReport()
    templates = s.scalars(select(RecurringTemplate).where(RecurringTemplate.active.is_(True),
                                                          RecurringTemplate.mode == "scheduled",
                                                          RecurringTemplate.next_date.isnot(None))).all()
    for tpl in templates:
        guard = 0
        while tpl.active and tpl.next_date and tpl.next_date - timedelta(days=tpl.days_in_advance or 0) <= today \
                and guard < 60:
            guard += 1
            try:
                with s.begin_nested():
                    txn = create_from_template(s, tpl, tpl.next_date)
                    out.created.append(txn)
                    tpl.last_run_at = utcnow()
                    tpl.last_error = None
                    if tpl.txn_type == "invoice" and tpl.autopay:
                        _autopay(s, config, txn, out)
                    if tpl.auto_send and TXN_TYPES[tpl.txn_type].customer_facing and txn.balance_cents != 0:
                        _send(s, config, txn, base_url, out)
                    advance(tpl)
            except BooksError as exc:
                tpl.last_error = str(exc)[:1000]
                out.errors.append(f"{tpl.name}: {exc}")
                break
    if prefs.get(s, "reminders_enabled"):
        out.reminders = _reminders(s, config, today, base_url, out)
    if prefs.get(s, "late_fees_enabled"):
        out.late_fees = _late_fees(s, today, out)
    out.reports_emailed = _scheduled_reports(s, config, today, out)
    return out


def _send(s: Session, config, txn: Transaction, base_url: str, out: RunReport) -> None:
    from pps_tools.books.services import email as email_service

    to = txn.email_to or (txn.customer.email if txn.customer else None)
    if not to:
        return
    try:
        email_service.send_transaction(s, config, txn, to=to, base_url=base_url)
        out.sent += 1
    except BooksError as exc:
        out.errors.append(f"Sending {txn.info.label} {txn.number}: {exc}")


def _autopay(s: Session, config, txn: Transaction, out: RunReport) -> None:
    from pps_tools.books.services import stripe_service

    try:
        if stripe_service.autopay(s, config, txn) is not None:
            out.autopaid += 1
    except Exception as exc:  # card declined, needs authentication, Stripe down
        out.errors.append(f"Autopay for invoice {txn.number}: {exc}")


def _reminders(s: Session, config, today: date, base_url: str, out: RunReport) -> int:
    from pps_tools.books.services import email as email_service

    days = sorted(int(d) for d in (prefs.get(s, "reminder_days") or []))
    sent = 0
    for inv in s.scalars(select(Transaction).where(Transaction.type == "invoice", Transaction.balance_cents > 0,
                                                   Transaction.voided.is_(False), Transaction.due_date < today)):
        overdue = (today - inv.due_date).days
        due_marks = [d for d in days if d <= overdue]
        if not due_marks:
            continue
        mark_date = inv.due_date + timedelta(days=due_marks[-1])
        if inv.last_reminder_at and inv.last_reminder_at.date() >= mark_date:
            continue
        try:
            if email_service.send_reminder(s, config, inv, base_url):
                sent += 1
        except BooksError as exc:
            out.errors.append(f"Reminder for invoice {inv.number}: {exc}")
    return sent


def _late_fees(s: Session, today: date, out: RunReport) -> int:
    """One late fee per overdue invoice, as its own invoice (the original stays as issued)."""
    from pps_tools.books.services.accounts import system_account_id

    after = int(prefs.get(s, "late_fee_days") or 30)
    kind = prefs.get(s, "late_fee_type") or "fixed"
    value = prefs.get(s, "late_fee_value") or "0"
    made = 0
    income = system_account_id(s, "late_fee_income")
    for inv in s.scalars(select(Transaction).where(Transaction.type == "invoice", Transaction.balance_cents > 0,
                                                   Transaction.voided.is_(False), Transaction.due_date < today)):
        if (today - inv.due_date).days < after or (inv.memo or "").startswith("Late fee"):
            continue
        marker = f"Late fee for invoice {inv.number}"
        if s.scalar(select(Transaction.id).where(Transaction.type == "invoice", Transaction.memo == marker)):
            continue
        amount = percent_of(inv.balance_cents, value) if kind == "percent" else cents(value)
        if amount <= 0:
            continue
        try:
            with s.begin_nested():
                tx.save(s, {"type": "invoice", "customer_id": inv.customer_id, "date": today.isoformat(),
                            "memo": marker, "apply_credits": False, "terms_id": inv.terms_id,
                            "lines": [{"kind": "item", "account_id": income, "description": marker,
                                       "amount_cents": amount}]}, source="recurring")
                made += 1
        except BooksError as exc:
            out.errors.append(f"{marker}: {exc}")
    return made


def _scheduled_reports(s: Session, config, today: date, out: RunReport) -> int:
    from pps_tools.books.services import email as email_service
    from pps_tools.books.services import reports
    from pps_tools.books.services.reports.export import to_csv, to_pdf

    sent = 0
    for sr in s.scalars(select(SavedReport).where(SavedReport.email_schedule != "none", SavedReport.email_to.isnot(None))):
        due = {"daily": True, "weekly": today.weekday() == 0, "monthly": today.day == 1}.get(sr.email_schedule, False)
        if not due or (sr.last_emailed_at and sr.last_emailed_at.date() >= today):
            continue
        if sr.report_key not in reports.REGISTRY:
            continue
        try:
            r = reports.run(s, sr.report_key, reports.Params.from_args(sr.params or {}), today=today)
            email_service.send(s, config, sr.email_to, f"{sr.name} — {r.subtitle}",
                               f"Your scheduled report “{sr.name}” is attached.\n",
                               attachments=[(f"{sr.name}.pdf", to_pdf(r), "application/pdf"),
                                            (f"{sr.name}.csv", to_csv(r).encode(), "text/csv")],
                               object_type="saved_report", object_id=sr.id)
            sr.last_emailed_at = utcnow()
            sent += 1
        except BooksError as exc:
            out.errors.append(f"Report {sr.name}: {exc}")
    return sent
