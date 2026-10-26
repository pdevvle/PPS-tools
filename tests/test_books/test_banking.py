"""Bank feed: statement files, rules, matching, adding, undo, and reconciliation."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from pps_tools.books.models import BankFeedItem, BankRule, LedgerEntry, Reconciliation, Transaction
from pps_tools.books.services import banking
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.errors import ValidationError
from pps_tools.books.services.importers import bankfiles

CSV = b"""Date,Description,Amount,Balance
01/05/2026,CITY POWER & LIGHT AUTOPAY,-312.40,9687.60
01/06/2026,DEPOSIT,500.00,10187.60
01/06/2026,DEPOSIT,500.00,10687.60
01/09/2026,CHECK 1001,-1500.00,9187.60
"""

OFX = b"""OFXHEADER:100
DATA:OFXSGML
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>USD<BANKACCTFROM><ACCTID>000123456789</BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260110120000<TRNAMT>-42.17<FITID>202601100001<NAME>FUEL STOP 57442<MEMO>RIVERBEND PA
<STMTTRN><TRNTYPE>CHECK<DTPOSTED>20260111<TRNAMT>-250.00<FITID>202601110002<CHECKNUM>1002<NAME>CHECK 1002
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260112<TRNAMT>1200.00<FITID>202601120003<NAME>MOBILE DEPOSIT
</BANKTRANLIST><LEDGERBAL><BALAMT>10345.83<DTASOF>20260112</LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""


def test_csv_statement_reads_amounts_balance_and_keeps_same_day_twins_apart():
    stmt = bankfiles.parse("checking.csv", CSV)
    assert [ln.amount_cents for ln in stmt.lines] == [-31240, 50000, 50000, -150000]
    assert stmt.balance_cents == 918760 and stmt.balance_date == date(2026, 1, 9)
    ids = [ln.external_id for ln in stmt.lines]
    assert len(set(ids)) == 4  # two identical $500 deposits on the same day stay two lines


def test_card_csv_with_positive_charges_is_flipped():
    data = b"Transaction Date,Description,Amount\n01/02/2026,OFFICE SUPPLY STORE,45.10\n01/03/2026,PAYMENT THANK YOU,-200.00\n01/04/2026,COFFEE,4.50\n"
    stmt = bankfiles.parse("card.csv", data, card=True)
    assert [ln.amount_cents for ln in stmt.lines] == [-4510, 20000, -450]


def test_debit_credit_columns():
    data = b"Posted Date,Payee,Debit,Credit\n2026-01-02,RENT,2400.00,\n2026-01-03,TRANSFER IN,,750.25\n"
    stmt = bankfiles.parse("bank.csv", data)
    assert [ln.amount_cents for ln in stmt.lines] == [-240000, 75025]


def test_ofx_statement():
    stmt = bankfiles.parse("statement.qfx", OFX)
    assert [ln.amount_cents for ln in stmt.lines] == [-4217, -25000, 120000]
    assert stmt.lines[0].external_id == "ofx:202601100001" and stmt.lines[0].payee == "FUEL STOP 57442"
    assert stmt.lines[1].check_number == "1002"
    assert stmt.balance_cents == 1034583 and stmt.account_hint == "6789"


def test_importing_twice_adds_nothing(s, b, checking):
    first = banking.import_statement(s, checking, bankfiles.parse("a.csv", CSV), source="csv")
    again = banking.import_statement(s, checking, bankfiles.parse("a.csv", CSV), source="csv")
    assert (first.added, again.added, again.duplicates) == (4, 0, 4)


def test_rule_suggests_and_auto_adds(s, b, checking):
    utilities = b.acct("Utilities")
    power = b.vendor("City Power & Light")
    s.add(BankRule(name="Power", direction="out", account_ids=[checking.id], action="expense", vendor_id=power.id,
                   account_id=utilities.id, conditions=[{"field": "description", "op": "contains", "value": "city power"}],
                   auto_add=True, active=True))
    s.flush()
    result = banking.import_statement(s, checking, bankfiles.parse("a.csv", CSV), source="csv")
    assert result.auto_added == 1
    item = s.scalar(select(BankFeedItem).where(BankFeedItem.description.like("CITY POWER%")))
    assert item.status == "added" and item.txn.vendor_id == power.id
    assert b.balance("Utilities") == 31240
    # The bank side of an added transaction is already cleared.
    entry = s.scalar(select(LedgerEntry).where(LedgerEntry.txn_id == item.txn_id, LedgerEntry.account_id == checking.id))
    assert entry.cleared == "C"
    b.assert_balanced()


def test_feed_matches_a_check_already_in_the_books_and_undo(s, b, checking):
    rent = b.acct("Rent & Lease")
    landlord = b.vendor("Landlord")
    check = tx.save(s, {"type": "check", "payee": f"vendor:{landlord.id}", "account_id": checking.id, "number": "1001",
                        "date": "2026-01-08", "lines": [{"account_id": rent.id, "amount": "1500"}]})
    banking.import_statement(s, checking, bankfiles.parse("a.csv", CSV), source="csv")
    item = s.scalar(select(BankFeedItem).where(BankFeedItem.amount_cents == -150000))
    assert item.suggestion_source == "match" and item.suggested_match_txn_id == check.id
    banking.match(s, item, [check.id], None)
    assert item.status == "matched"
    with pytest.raises(ValidationError):
        banking.match(s, item, [check.id], None)
    banking.undo(s, item)
    assert item.status == "review"
    assert s.get(Transaction, check.id) is not None  # undoing a match keeps the check


def test_add_expense_from_the_feed_and_undo_removes_it(s, b, checking):
    banking.import_statement(s, checking, bankfiles.parse("a.csv", CSV), source="csv")
    item = s.scalar(select(BankFeedItem).where(BankFeedItem.description.like("CITY POWER%")))
    txn = banking.add_from_feed(s, item, None, account_id=b.acct("Utilities").id)
    assert txn.type == "expense" and txn.total_cents == 31240 and item.status == "added"
    banking.undo(s, item)
    assert item.status == "review" and s.get(Transaction, txn.id) is None
    b.assert_balanced()


def test_deposit_received_for_an_open_invoice(s, b, checking):
    cust = b.customer()
    inv = tx.save(s, {"type": "invoice", "customer_id": cust.id, "date": "2026-01-01",
                      "lines": [{"account_id": b.acct("Printing Services").id, "amount": "500"}]})
    banking.import_statement(s, checking, bankfiles.parse("a.csv", CSV), source="csv")
    item = s.scalars(select(BankFeedItem).where(BankFeedItem.amount_cents == 50000)).first()
    banking.receive_for_invoice(s, item, inv, None)
    assert inv.balance_cents == 0 and item.status == "added"
    assert b.balance("Checking") == 50000
    b.assert_balanced()


def _clear_all(s, rec):
    return [e.id for e in banking.reconcile_candidates(s, rec)]


def test_reconcile_with_fees_interest_and_an_adjustment(s, b, checking):
    tx.save(s, {"type": "deposit", "account_id": checking.id, "date": "2026-01-02", "memo": "Opening",
                "lines": [{"account_id": b.acct("Owner's Investment").id, "amount": "1000"}]})
    tx.save(s, {"type": "expense", "account_id": checking.id, "date": "2026-01-10",
                "lines": [{"account_id": b.acct("Office Supplies & Software").id, "amount": "100"}]})
    late = tx.save(s, {"type": "expense", "account_id": checking.id, "date": "2026-02-03",
                       "lines": [{"account_id": b.acct("Office Supplies & Software").id, "amount": "50"}]})
    # Statement: 1,000 in, 100 out, a $5 fee and $1.25 interest -> 896.25.
    rec = banking.start_reconciliation(s, checking, date(2026, 1, 31), 89625, service_charge=500, interest=125)
    assert rec.beginning_balance_cents == 0
    ids = _clear_all(s, rec)
    assert late.id not in {s.get(LedgerEntry, i).txn_id for i in ids}  # after the statement date
    banking.finish_reconciliation(s, rec, ids, None)
    assert rec.status == "completed"
    assert banking.reconciled_balance(s, checking.id) == 89625
    # Next month the statement says 846.00 but the books say 846.25: finish with an adjustment.
    rec2 = banking.start_reconciliation(s, checking, date(2026, 2, 28), 84600)
    assert rec2.beginning_balance_cents == 89625
    with pytest.raises(ValidationError, match="Still off by"):
        banking.finish_reconciliation(s, rec2, _clear_all(s, rec2), None)
    banking.finish_reconciliation(s, rec2, _clear_all(s, rec2), None, adjust=True)
    assert b.balance("reconciliation_discrepancies") == 25
    with pytest.raises(ValidationError, match="later reconciliations"):
        banking.undo_reconciliation(s, rec, None)
    banking.undo_reconciliation(s, rec2, None)
    assert s.get(Reconciliation, rec2.id).status == "in_progress"
    b.assert_balanced()
