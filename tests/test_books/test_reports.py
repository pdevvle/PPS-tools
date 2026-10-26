"""Reports: financial statements tie out, cash basis, aging, and every
registered report runs on a populated company."""

from datetime import date

import pytest

from pps_tools.books.services import reports
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.reports import Params


def row(report, name):
    """The row labelled ``name`` (account rows may carry a number prefix)."""
    for r in report.rows:
        label = r.cells.get("name") or r.cells.get("type") or r.cells.get("num") or ""
        if label == name or (label.endswith(" " + name) and label.split(" ", 1)[0].isdigit()):
            return r
    raise AssertionError(f"no row {name!r} in {[r.cells.get('name') for r in report.rows]}")


@pytest.fixture
def books(s, b, checking):
    """A quarter of activity: sales, a partial payment, expenses, a bill, inventory, a loan."""
    cust = b.customer("Acme Corp")
    cust2 = b.customer("Beta LLC")
    cards = b.service("Business Cards", "0.10")
    design = b.service("Design", "75", income="Graphic Design", taxable=False)
    paper = b.inventory()
    vendor = b.vendor("Paper Supply Co", track_1099=True)
    tax = b.tax_rate("State", "5")
    tx.save(s, {"type": "journal_entry", "date": "2025-12-31", "lines": [
        {"account_id": checking.id, "debit": "10000"},
        {"account_id": b.acct("opening_balance_equity").id, "credit": "10000"}]})
    tx.save(s, {"type": "bill", "vendor_id": vendor.id, "date": "2026-01-05",
                "lines": [{"item_id": paper.id, "qty": "100", "rate": "1"}]})
    inv1 = tx.save(s, {"type": "invoice", "customer_id": cust.id, "date": "2026-01-10", "tax_rate_id": tax.id,
                       "lines": [{"item_id": cards.id, "qty": "1000"}, {"item_id": design.id, "qty": "2"},
                                 {"item_id": paper.id, "qty": "40", "rate": "3"}]})
    # $100 cards + $150 design + $120 paper = 370; tax 5% of 220 = 11 -> 381
    tx.save(s, {"type": "payment", "customer_id": cust.id, "date": "2026-02-01", "amount": "190.50",
                "account_id": checking.id, "applications": [{"txn_id": inv1.id, "amount": "190.50"}]})
    tx.save(s, {"type": "sales_receipt", "customer_id": cust2.id, "date": "2026-02-15", "account_id": checking.id,
                "lines": [{"item_id": design.id, "qty": "1"}]})
    tx.save(s, {"type": "expense", "payee": f"vendor:{vendor.id}", "date": "2026-02-20", "account_id": checking.id,
                "lines": [{"account_id": b.acct("Rent & Lease").id, "amount": "1200"}]})
    tx.save(s, {"type": "check", "payee": f"vendor:{vendor.id}", "date": "2026-03-01", "account_id": checking.id,
                "lines": [{"account_id": b.acct("Contract Labor").id, "amount": "2500"}]})
    tx.save(s, {"type": "bill", "vendor_id": vendor.id, "date": "2026-03-05",
                "lines": [{"account_id": b.acct("Utilities").id, "amount": "300"}]})
    tx.save(s, {"type": "deposit", "date": "2026-03-10", "account_id": checking.id,
                "lines": [{"account_id": b.acct("Loan Payable").id, "amount": "5000"}]})
    return {"cust": cust, "inv1": inv1, "vendor": vendor}


def run(s, key, **kw):
    p = Params(**kw)
    return reports.run(s, key, p, today=date(2026, 3, 31))


def test_profit_and_loss_accrual(s, books):
    r = run(s, "profit_and_loss", preset="custom", start=date(2026, 1, 1), end=date(2026, 3, 31))
    assert row(r, "Total Income").cells["total"] == 10000 + 15000 + 12000 + 7500
    assert row(r, "Total Cost of Goods Sold").cells["total"] == 4000
    assert row(r, "Gross Profit").cells["total"] == 44500 - 4000
    assert row(r, "Total Expenses").cells["total"] == 120000 + 250000 + 30000
    assert row(r, "Net Income").cells["total"] == 40500 - 400000


def test_profit_and_loss_cash_basis_recognizes_paid_share(s, books):
    r = run(s, "profit_and_loss", preset="custom", start=date(2026, 1, 1), end=date(2026, 3, 31), basis="cash")
    # Half of the $381 invoice is paid: half of its $370 of income lands, plus the cash sale.
    assert row(r, "Total Income").cells["total"] == 18500 + 7500
    assert row(r, "Total Cost of Goods Sold").cells["total"] == 2000
    # The unpaid utilities bill isn't an expense yet on a cash basis.
    assert row(r, "Total Expenses").cells["total"] == 120000 + 250000


def test_balance_sheet_balances_on_both_bases(s, books):
    for basis in ("accrual", "cash"):
        r = run(s, "balance_sheet", preset="custom", end=date(2026, 3, 31), basis=basis)
        assets = row(r, "Total Assets").cells["total"]
        le = row(r, "Total Liabilities and Equity").cells["total"]
        assert assets == le, basis
        assert not r.notes


def test_balance_sheet_retained_earnings_rolls_forward(s, b, books, checking):
    # An expense last fiscal year shows up as retained earnings this year.
    tx.save(s, {"type": "expense", "date": "2025-06-01", "account_id": checking.id,
                "lines": [{"account_id": b.acct("Utilities").id, "amount": "50"}]})
    r = run(s, "balance_sheet", preset="custom", end=date(2026, 3, 31))
    assert row(r, "Retained Earnings").cells["total"] == -5000
    assert row(r, "Total Assets").cells["total"] == row(r, "Total Liabilities and Equity").cells["total"]


def test_trial_balance_totals_match(s, books):
    r = run(s, "trial_balance", preset="custom", end=date(2026, 3, 31))
    total = row(r, "TOTAL")
    assert total.cells["debit"] == total.cells["credit"] > 0


def test_cash_flow_ties_to_cash_accounts(s, b, books):
    r = run(s, "cash_flow", preset="custom", start=date(2026, 1, 1), end=date(2026, 3, 31))
    begin = row(r, "Cash at beginning of period").cells["total"]
    end = row(r, "Cash at end of period").cells["total"]
    assert begin == 1000000
    assert end == b.balance("Checking") + b.balance("undeposited_funds")
    assert row(r, "Net cash provided by financing activities").cells["total"] == 500000


def test_pl_by_month_and_customer_columns(s, books):
    r = run(s, "profit_and_loss", preset="custom", start=date(2026, 1, 1), end=date(2026, 3, 31), columns="month")
    keys = [c.key for c in r.columns]
    assert keys[:4] == ["name", "c0", "c1", "c2"]
    inc = row(r, "Total Income").cells
    assert inc["c0"] == 37000 and inc["c1"] == 7500 and inc["total"] == 44500
    r = run(s, "pl_by_customer", preset="custom", start=date(2026, 1, 1), end=date(2026, 3, 31))
    labels = [c.label for c in r.columns]
    assert "Acme Corp" in labels and "Beta LLC" in labels


def test_pl_compare_previous_year(s, books):
    r = run(s, "profit_and_loss", preset="custom", start=date(2026, 1, 1), end=date(2026, 3, 31),
            compare="prev_year")
    ni = row(r, "Net Income").cells
    assert ni["prev"] == 0 and ni["chg"] == ni["total"]


def test_ar_aging_buckets(s, b, books):
    cust = books["cust"]
    r = run(s, "ar_aging_summary", preset="custom", end=date(2026, 3, 31))
    acme = row(r, "Acme Corp").cells
    # Invoice dated Jan 10, Net 30 -> due Feb 9, 50 days late on Mar 31: the 31-60 bucket.
    assert acme["b2"] == 19050 and acme["total"] == 19050
    # As of Jan 31 the full invoice was open and current.
    r = run(s, "ar_aging_summary", preset="custom", end=date(2026, 1, 31))
    assert row(r, "Acme Corp").cells["b0"] == 38100
    detail = run(s, "ar_aging_detail", preset="custom", end=date(2026, 3, 31), customer_id=cust.id)
    assert row(detail, "TOTAL").cells["open"] == 19050


def test_ap_and_vendor_balances(s, books):
    r = run(s, "vendor_balance_summary", preset="custom", end=date(2026, 3, 31))
    assert row(r, "Paper Supply Co").cells["total"] == 10000 + 30000
    r = run(s, "unpaid_bills", preset="custom", end=date(2026, 3, 31))
    assert row(r, "TOTAL").cells["open"] == 40000


def test_1099_summary_counts_cash_and_check_payments(s, books):
    r = run(s, "contractor_1099_summary", preset="custom", start=date(2026, 1, 1), end=date(2026, 12, 31))
    paper = row(r, "Paper Supply Co").cells
    assert paper["total"] == 120000 + 250000
    assert paper["file"] == "1099-NEC"  # over the $2,000 2026 threshold
    assert "2026: $2,000" in r.notes[0]


def test_1099_forms_use_each_box_threshold():
    from pps_tools.books.services.reports.other import forms_needed

    assert forms_needed({"NEC-1": 199_999}, 200_000) == []
    assert forms_needed({"NEC-1": 200_000}, 200_000) == ["NEC"]
    # Royalties need a 1099-MISC from $10 and attorneys' gross proceeds from $600, whatever the NEC threshold.
    assert forms_needed({"MISC-2": 1_000}, 200_000) == ["MISC"]
    assert forms_needed({"MISC-10": 60_000}, 200_000) == ["MISC"]
    assert forms_needed({"MISC-1": 150_000, "MISC-3": 150_000}, 200_000) == []
    assert forms_needed({"NEC-1": 250_000, "MISC-1": 250_000}, 200_000) == ["NEC", "MISC"]


def test_sales_by_product_includes_margin(s, books):
    r = run(s, "sales_by_product_summary", preset="custom", start=date(2026, 1, 1), end=date(2026, 3, 31))
    paper = row(r, "Gloss Paper 100lb").cells
    assert paper["amount"] == 12000 and paper["cogs"] == 4000 and paper["margin"] == 8000


def test_sales_tax_liability(s, books):
    r = run(s, "sales_tax_liability", preset="custom", start=date(2026, 1, 1), end=date(2026, 3, 31))
    assert row(r, "State").cells["taxable"] == 22000
    assert row(r, "State").cells["tax"] == 1100


def test_general_ledger_running_balance(s, b, books, checking):
    r = run(s, "general_ledger", preset="custom", start=date(2026, 1, 1), end=date(2026, 3, 31),
            account_id=checking.id)
    begin = next(rw for rw in r.rows if rw.cells.get("type") == "Beginning Balance")
    assert begin.cells["balance"] == 1000000
    last = [rw for rw in r.rows if rw.kind == "data"][-1]
    assert last.cells["balance"] == b.balance("Checking")


@pytest.mark.parametrize("key", sorted(reports.REGISTRY))
def test_every_report_runs(s, books, key):
    rdef = reports.REGISTRY[key]
    p = Params(preset=rdef.default_preset)
    r = reports.run(s, key, p, today=date(2026, 3, 31))
    assert r.title and r.columns is not None
    for rw in r.rows:
        for col in r.columns:
            v = rw.cells.get(col.key)
            if col.kind == "money" and v is not None:
                assert isinstance(v, int), (key, col.key, v)
