"""Recurring schedules, reminders and late fees; budgets; statements, PDFs and email."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from sqlalchemy import select

from pps_tools.books.models import EmailMessage, RecurringTemplate, Transaction
from pps_tools.books.services import email as email_service
from pps_tools.books.services import pdf, prefs, recurring, statements
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.dates import next_occurrence

CFG = SimpleNamespace(smtp_host=None, smtp_port=587, smtp_user=None, smtp_password=None, smtp_from=None, smtp_tls=True,
                      stripe_secret_key=None, stripe_webhook_secret=None, stripe_publishable_key=None,
                      anthropic_api_key=None, base_url="https://books.example.com")


def _template(s, b, **kw):
    cust = b.customer()
    item = b.service()
    tpl = RecurringTemplate(name=kw.pop("name", "Monthly cards"), txn_type="invoice", mode=kw.pop("mode", "scheduled"),
                            interval="monthly", every=1, day_of_month=kw.pop("day_of_month", 1),
                            start_date=kw.pop("start", date(2026, 1, 1)), occurrences=0, active=True,
                            days_in_advance=0, **kw)
    return recurring.save_template(s, tpl, {"type": "invoice", "customer_id": cust.id,
                                            "lines": [{"item_id": item.id, "qty": "100", "rate": "0.50"}]}), cust


def test_next_occurrence_handles_month_ends_and_weekdays():
    assert next_occurrence(date(2026, 1, 31), "monthly", 1, day_of_month=0) == date(2026, 2, 28)
    assert next_occurrence(date(2026, 1, 15), "monthly", 3, day_of_month=15) == date(2026, 4, 15)
    assert next_occurrence(date(2026, 1, 2), "weekly", 1, day_of_week=4) == date(2026, 1, 9)  # Fridays
    assert next_occurrence(date(2024, 2, 29), "yearly", 1) == date(2025, 2, 28)


def test_scheduled_template_catches_up_and_respects_the_end(s, b):
    tpl, cust = _template(s, b, max_occurrences=3)
    assert tpl.amount_cents == 5000
    report = recurring.run_scheduled(s, CFG, today=date(2026, 5, 10))
    assert len(report.created) == 3 and not report.errors
    dates = sorted(t.date for t in s.scalars(select(Transaction).where(Transaction.recurring_template_id == tpl.id)))
    assert dates == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    assert not tpl.active and tpl.next_date is None
    assert recurring.run_scheduled(s, CFG, today=date(2026, 6, 1)).created == []


def test_reminder_templates_are_not_created_automatically(s, b):
    _template(s, b, name="Rent reminder", mode="reminder")
    assert recurring.run_scheduled(s, CFG, today=date(2026, 3, 1)).created == []


def test_auto_send_goes_to_the_outbox_without_smtp(s, b):
    tpl, cust = _template(s, b, auto_send=True)
    report = recurring.run_scheduled(s, CFG, today=date(2026, 1, 1))
    assert report.sent == 1
    msg = s.scalar(select(EmailMessage).where(EmailMessage.object_type == "transaction"))
    assert msg.status == "logged" and msg.to_addr == cust.email and msg.attachment_names[0].endswith(".pdf")
    assert "Invoice" in msg.subject or "invoice" in msg.subject.lower()


def test_reminders_once_per_mark_and_late_fee_once(s, b):
    cust = b.customer()
    inv = tx.save(s, {"type": "invoice", "customer_id": cust.id, "date": "2026-01-01", "due_date": "2026-01-31",
                      "lines": [{"account_id": b.acct("Printing Services").id, "amount": "200"}]})
    prefs.set_many(s, {"reminders_enabled": True, "reminder_days": [3, 15], "late_fees_enabled": True,
                       "late_fee_type": "percent", "late_fee_value": "1.5", "late_fee_days": 10})
    r1 = recurring.run_scheduled(s, CFG, today=date(2026, 2, 5))  # 5 days late: the 3-day reminder
    assert r1.reminders == 1 and r1.late_fees == 0
    assert recurring.run_scheduled(s, CFG, today=date(2026, 2, 6)).reminders == 0
    r3 = recurring.run_scheduled(s, CFG, today=date(2026, 2, 20))  # 20 days late: 15-day reminder and the fee
    assert r3.reminders == 1 and r3.late_fees == 1
    fee = s.scalar(select(Transaction).where(Transaction.memo == f"Late fee for invoice {inv.number}"))
    assert fee.total_cents == 300 and fee.customer_id == cust.id
    assert recurring.run_scheduled(s, CFG, today=date(2026, 3, 30)).late_fees == 0
    b.assert_balanced()


def test_statement_amount_due_aging_and_pdf(s, b):
    cust = b.customer()
    acct = b.acct("Printing Services")
    tx.save(s, {"type": "invoice", "customer_id": cust.id, "date": "2026-01-01", "due_date": "2026-01-31",
                "lines": [{"account_id": acct.id, "amount": "100"}]})
    tx.save(s, {"type": "invoice", "customer_id": cust.id, "date": "2026-03-01", "due_date": "2026-03-31",
                "lines": [{"account_id": acct.id, "amount": "40"}]})
    st = statements.create(s, cust, "open_item", date(2026, 3, 15), None, None)
    data = statements.build(s, st)
    assert data["amount_due"] == 14000 and st.balance_cents == 14000
    assert data["aging"]["31_60"] == 10000 and data["aging"]["current"] == 4000
    out = pdf.render_statements(s, [st], base_url="https://books.example.com")
    assert out[:5] == b"%PDF-"
    msg = email_service.send_statement(s, CFG, st, "https://books.example.com")
    assert msg.status == "logged" and "/portal/" in msg.body_text


def test_invoice_and_check_pdfs_render(s, b, checking):
    cust = b.customer()
    inv = tx.save(s, {"type": "invoice", "customer_id": cust.id, "date": "2026-01-01",
                      "lines": [{"account_id": b.acct("Printing Services").id, "amount": "1234.56",
                                 "description": "Posters & banners <rush>"}]})
    assert pdf.render_transaction(s, inv, base_url="https://x")[:5] == b"%PDF-"
    v = b.vendor()
    chk = tx.save(s, {"type": "check", "payee": f"vendor:{v.id}", "account_id": checking.id,
                      "lines": [{"account_id": b.acct("Rent & Lease").id, "amount": "1500.25"}]})
    assert pdf.render_checks(s, [chk])[:5] == b"%PDF-"


def test_budget_prefill_from_last_years_actuals_with_an_increase(s, b, monkeypatch):
    from pps_tools.books.models import Budget, Company
    from pps_tools.books.web import budgets as budget_views
    from pps_tools.books.web import core

    tx.save(s, {"type": "expense", "account_id": b.acct("Checking").id, "date": "2025-03-10",
                "lines": [{"account_id": b.acct("Utilities").id, "amount": "200"}]})
    cust = b.customer()
    tx.save(s, {"type": "invoice", "customer_id": cust.id, "date": "2025-03-12",
                "lines": [{"account_id": b.acct("Printing Services").id, "amount": "1000"}]})
    budget = Budget(name="FY26", fiscal_year=2026, subdivide_by="none", active=True)
    s.add(budget)
    s.flush()
    monkeypatch.setattr(core, "company", lambda: s.get(Company, 1))  # the view reads the fiscal year from here
    budget_views._prefill_from_actuals(s, budget, "10")
    lines = {(bl.account_id, bl.period): bl.amount_cents for bl in budget.lines}
    assert lines[(b.acct("Utilities").id, 3)] == 22000  # $200 last March, plus 10%
    assert lines[(b.acct("Printing Services").id, 3)] == 110000  # income budgets as a positive amount
    assert all(period == 3 for (_, period) in lines)
