"""Purchasing: bills, bill payments, vendor credits, expenses, checks, POs,
billable expenses; plus journal entries, transfers and the closing date."""

from datetime import date
from decimal import Decimal

import pytest

from pps_tools.books.models import LedgerEntry
from pps_tools.books.services import closing
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.errors import ClosedPeriodError, ValidationError


def test_bill_vendor_credit_and_bill_payment(s, b, checking):
    v = b.vendor()
    paper = b.acct("Paper & Stock")
    bill = tx.save(s, {"type": "bill", "vendor_id": v.id, "number": "INV-77", "date": "2026-02-01",
                       "lines": [{"account_id": paper.id, "amount": "400"},
                                 {"account_id": b.acct("Freight In").id, "amount": "35.50"}]})
    assert bill.total_cents == 43550
    assert bill.due_date == date(2026, 3, 3)
    assert b.balance("ap") == -43550
    vc = tx.save(s, {"type": "vendor_credit", "vendor_id": v.id, "applications": [],
                     "lines": [{"account_id": paper.id, "amount": "50"}]})
    assert vc.balance_cents == 5000
    bp = tx.save(s, {"type": "bill_payment", "vendor_id": v.id, "account_id": checking.id, "amount": "385.50",
                     "number": "2001",
                     "applications": [{"txn_id": bill.id, "amount": "385.50"}],
                     "credits": [{"txn_id": vc.id, "bill_id": bill.id, "amount": "50"}]})
    assert bill.balance_cents == 0
    assert vc.balance_cents == 0
    assert bp.balance_cents == 0
    assert b.balance("ap") == 0
    assert b.balance("Checking") == -38550
    assert b.balance("Paper & Stock") == 35000
    assert checking.next_check_number == 2002
    b.assert_balanced()
    with pytest.raises(ValidationError):  # duplicate bill number for the vendor
        tx.save(s, {"type": "bill", "vendor_id": v.id, "number": "INV-77",
                    "lines": [{"account_id": paper.id, "amount": "1"}]})


def test_expense_on_credit_card_then_pay_down_card(s, b, checking):
    v = b.vendor("Office Depot")
    card = b.acct("Business Credit Card")
    tx.save(s, {"type": "expense", "payee": f"vendor:{v.id}", "account_id": card.id,
                "lines": [{"account_id": b.acct("Office Supplies & Software").id, "amount": "89.99"}]})
    assert b.balance("Business Credit Card") == -8999
    tx.save(s, {"type": "cc_credit", "payee": f"vendor:{v.id}", "account_id": card.id,
                "lines": [{"account_id": b.acct("Office Supplies & Software").id, "amount": "9.99"}]})
    assert b.balance("Business Credit Card") == -8000
    tx.save(s, {"type": "cc_payment", "account_id": checking.id, "to_account_id": card.id, "amount": "80"})
    assert b.balance("Business Credit Card") == 0
    assert b.balance("Checking") == -8000
    b.assert_balanced()


def test_checks_number_themselves_and_reject_duplicates(s, b, checking):
    v = b.vendor()
    rent = b.acct("Rent & Lease")
    c1 = tx.save(s, {"type": "check", "payee": f"vendor:{v.id}", "account_id": checking.id,
                     "lines": [{"account_id": rent.id, "amount": "1500"}]})
    c2 = tx.save(s, {"type": "check", "payee": f"vendor:{v.id}", "account_id": checking.id,
                     "lines": [{"account_id": rent.id, "amount": "10"}]})
    assert (c1.number, c2.number) == ("1001", "1002")
    with pytest.raises(ValidationError):
        tx.save(s, {"type": "check", "payee": f"vendor:{v.id}", "account_id": checking.id, "number": "1001",
                    "lines": [{"account_id": rent.id, "amount": "10"}]})


def test_expense_cannot_post_to_ar(s, b, checking):
    with pytest.raises(ValidationError):
        tx.save(s, {"type": "expense", "account_id": checking.id,
                    "lines": [{"account_id": b.acct("ar").id, "amount": "10"}]})


def test_purchase_order_receipt_closes_po(s, b):
    v = b.vendor()
    paper = b.inventory()
    po = tx.save(s, {"type": "purchase_order", "vendor_id": v.id,
                     "lines": [{"item_id": paper.id, "qty": "100", "rate": "1.10"}]})
    assert po.status == "open" and po.total_cents == 11000
    assert b.balance("ap") == 0
    po_line = po.lines[0]
    tx.save(s, {"type": "bill", "vendor_id": v.id, "source_po_id": po.id,
                "lines": [{"item_id": paper.id, "qty": "60", "rate": "1.10", "source_type": "po_line",
                           "source_id": po_line.id}]})
    assert po_line.received_qty == Decimal(60)
    assert po.status == "open"
    bill2 = tx.save(s, {"type": "bill", "vendor_id": v.id, "source_po_id": po.id,
                        "lines": [{"item_id": paper.id, "qty": "40", "rate": "1.10", "source_type": "po_line",
                                   "source_id": po_line.id}]})
    assert po.status == "closed"
    tx.delete(s, bill2)
    assert po_line.received_qty == Decimal(60)


def test_billable_expense_marked_billed_by_invoice(s, b, checking):
    cust = b.customer()
    v = b.vendor()
    exp = tx.save(s, {"type": "expense", "payee": f"vendor:{v.id}", "account_id": checking.id,
                      "lines": [{"account_id": b.acct("Outsourced Printing").id, "amount": "120",
                                 "customer_id": cust.id, "billable": True}]})
    line = exp.lines[0]
    assert line.billable and line.billed_txn_id is None
    assert b.balance("Outsourced Printing", customer_id=cust.id) == 12000
    inv = tx.save(s, {"type": "invoice", "customer_id": cust.id, "lines": [
        {"account_id": b.acct("Printing Services").id, "description": "Outsourced job", "amount": "150",
         "kind": "item", "source_type": "expense_line", "source_id": line.id}]})
    assert line.billed_txn_id == inv.id
    tx.delete(s, inv)
    assert line.billed_txn_id is None


def test_journal_entry_rules(s, b, checking):
    with pytest.raises(ValidationError):
        tx.save(s, {"type": "journal_entry", "lines": [
            {"account_id": checking.id, "debit": "100"},
            {"account_id": b.acct("opening_balance_equity").id, "credit": "90"}]})
    with pytest.raises(ValidationError):  # A/R line needs a customer
        tx.save(s, {"type": "journal_entry", "lines": [
            {"account_id": b.acct("ar").id, "debit": "100"},
            {"account_id": b.acct("opening_balance_equity").id, "credit": "100"}]})
    je = tx.save(s, {"type": "journal_entry", "date": "2026-01-01", "lines": [
        {"account_id": checking.id, "debit": "5000", "description": "Opening balance"},
        {"account_id": b.acct("opening_balance_equity").id, "credit": "5000"}]})
    assert je.number == "1"
    assert je.total_cents == 500000
    assert b.balance("Checking") == 500000
    b.assert_balanced()


def test_transfer_requires_two_accounts(s, b, checking):
    savings = b.acct("Savings")
    with pytest.raises(ValidationError):
        tx.save(s, {"type": "transfer", "account_id": checking.id, "to_account_id": checking.id, "amount": "5"})
    tx.save(s, {"type": "transfer", "account_id": checking.id, "to_account_id": savings.id, "amount": "250"})
    assert b.balance("Savings") == 25000 and b.balance("Checking") == -25000


def test_closing_date_blocks_changes_without_password(s, b, checking):
    rent = b.acct("Rent & Lease")
    exp = tx.save(s, {"type": "expense", "date": "2025-12-15", "account_id": checking.id,
                      "lines": [{"account_id": rent.id, "amount": "100"}]})
    closing.set_closing(s, date(2025, 12, 31), password="s3cret-pass")
    with pytest.raises(ClosedPeriodError):
        tx.save(s, {"memo": "late edit"}, txn=exp)
    with pytest.raises(ClosedPeriodError):  # moving a new txn into the closed period
        tx.save(s, {"type": "expense", "date": "2025-12-20", "account_id": checking.id,
                    "lines": [{"account_id": rent.id, "amount": "1"}]})
    with pytest.raises(ClosedPeriodError):
        tx.delete(s, exp)
    tx.save(s, {"memo": "approved"}, txn=exp, closing_password="s3cret-pass")
    assert exp.memo == "approved"
    # Moving a closed-period transaction out of the period still needs the password.
    with pytest.raises(ClosedPeriodError):
        tx.save(s, {"date": "2026-01-05"}, txn=exp)


def test_editing_keeps_reconciled_marks(s, b, checking):
    rent = b.acct("Rent & Lease")
    exp = tx.save(s, {"type": "expense", "account_id": checking.id,
                      "lines": [{"account_id": rent.id, "amount": "100"}]})
    bank_entry = next(e for e in exp.entries if e.account_id == checking.id)
    bank_entry.cleared = "R"
    s.flush()
    tx.save(s, {"memo": "typo fixed"}, txn=exp)
    s.expire_all()
    entries = s.query(LedgerEntry).filter(LedgerEntry.txn_id == exp.id,
                                          LedgerEntry.account_id == checking.id).all()
    assert [e.cleared for e in entries] == ["R"]

