"""Sales cycle: invoices, payments, deposits, credits, refunds, estimates."""

from datetime import date, timedelta

import pytest

from pps_tools.books.models import Transaction
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.errors import ValidationError


def invoice(s, cust, lines, **kw):
    data = {"type": "invoice", "customer_id": cust.id, "date": kw.pop("date", "2026-03-01"), "lines": lines}
    data.update(kw)
    return tx.save(s, data)


def test_invoice_totals_discount_tax_shipping_and_posting(s, b):
    cust = b.customer()
    cards = b.service("Business Cards", "0.10")
    design = b.service("Design", "75", income="Graphic Design", taxable=False)
    rate = b.tax_rate("State", "8.25")
    inv = invoice(s, cust, [
        {"item_id": cards.id, "qty": "1000"},  # $100.00 taxable
        {"item_id": design.id, "qty": "2"},  # $150.00 not taxable
    ], tax_rate_id=rate.id, discount_type="percent", discount_value="10", shipping="12.50")

    assert inv.subtotal_cents == 25000
    assert inv.discount_cents == 2500
    # discount before tax: taxable share of the $25 discount is $10 -> taxable $90
    assert inv.taxable_subtotal_cents == 9000
    assert inv.tax_cents == 743  # 8.25% of 90.00 = 7.425 -> 7.43
    assert inv.total_cents == 25000 - 2500 + 743 + 1250
    assert inv.balance_cents == inv.total_cents
    assert inv.number == "1001"
    assert inv.due_date == date(2026, 3, 31)  # Net 30 default

    assert b.balance("ar") == inv.total_cents
    assert b.balance("Printing Services") == -10000
    assert b.balance("Graphic Design") == -15000
    assert b.balance("discounts_given") == 2500
    assert b.balance("sales_tax_payable") == -743
    assert b.balance("shipping_income") == -1250
    b.assert_balanced()
    assert tx.status(inv, today=date(2026, 3, 5))[0] == "open"
    assert tx.status(inv, today=date(2026, 4, 5))[0] == "overdue"


def test_payment_auto_applies_then_deposit_clears_payments_to_deposit(s, b, checking):
    cust = b.customer()
    item = b.service()
    inv1 = invoice(s, cust, [{"item_id": item.id, "qty": "500"}], date="2026-01-10")  # $50
    inv2 = invoice(s, cust, [{"item_id": item.id, "qty": "300"}], date="2026-01-20")  # $30
    pay = tx.save(s, {"type": "payment", "customer_id": cust.id, "date": "2026-02-01", "amount": "65.00"})
    assert inv1.balance_cents == 0  # oldest first
    assert inv2.balance_cents == 1500
    assert pay.balance_cents == 0
    assert b.balance("undeposited_funds") == 6500
    assert b.balance("ar") == 1500

    dep = tx.save(s, {"type": "deposit", "account_id": checking.id, "date": "2026-02-02",
                      "deposits": [pay.id],
                      "lines": [{"account_id": b.acct("Interest Earned").id, "amount": "1.25"}]})
    assert dep.total_cents == 6625
    assert b.balance("undeposited_funds") == 0
    assert b.balance("Checking") == 6625
    assert tx.is_deposited(s, pay)
    with pytest.raises(ValidationError):
        tx.delete(s, pay)
    b.assert_balanced()

    # Taking the payment back out of the deposit returns it to Payments to deposit.
    tx.save(s, {"deposits": []}, txn=dep)
    assert dep.total_cents == 125
    assert b.balance("undeposited_funds") == 6500


def test_overpayment_becomes_credit_and_new_invoice_uses_it(s, b):
    cust = b.customer()
    item = b.service(price="1")
    inv = invoice(s, cust, [{"item_id": item.id, "qty": "40"}])
    pay = tx.save(s, {"type": "payment", "customer_id": cust.id, "amount": "100",
                      "applications": [{"txn_id": inv.id, "amount": "40"}]})
    assert pay.balance_cents == 6000  # unapplied credit
    assert b.balance("ar", customer_id=cust.id) == -6000
    inv2 = invoice(s, cust, [{"item_id": item.id, "qty": "25"}])
    assert inv2.balance_cents == 0
    assert pay.balance_cents == 3500
    # Editing the payment's memo must not drop the credit that inv2 used.
    tx.save(s, {"memo": "check 1234"}, txn=pay)
    assert inv2.balance_cents == 0
    assert pay.balance_cents == 3500
    b.assert_balanced()


def test_cannot_apply_more_than_open_balance(s, b):
    cust = b.customer()
    item = b.service(price="1")
    inv = invoice(s, cust, [{"item_id": item.id, "qty": "10"}])
    with pytest.raises(ValidationError):
        tx.save(s, {"type": "payment", "customer_id": cust.id, "amount": "20",
                    "applications": [{"txn_id": inv.id, "amount": "20"}]})


def test_credit_memo_applied_in_receive_payment(s, b):
    cust = b.customer()
    item = b.service(price="1")
    inv = invoice(s, cust, [{"item_id": item.id, "qty": "100"}])
    cm = tx.save(s, {"type": "credit_memo", "customer_id": cust.id, "applications": [],
                     "lines": [{"item_id": item.id, "qty": "30"}]})
    assert cm.balance_cents == 3000
    pay = tx.save(s, {"type": "payment", "customer_id": cust.id, "amount": "70",
                      "applications": [{"txn_id": inv.id, "amount": "70"}],
                      "credits": [{"txn_id": cm.id, "invoice_id": inv.id, "amount": "30"}]})
    assert inv.balance_cents == 0
    assert cm.balance_cents == 0
    assert b.balance("ar", customer_id=cust.id) == 0
    # Deleting the payment releases the credit too.
    tx.delete(s, pay)
    assert inv.balance_cents == 10000
    assert cm.balance_cents == 3000
    b.assert_balanced()


def test_void_invoice_unapplies_payment(s, b):
    cust = b.customer()
    item = b.service(price="1")
    inv = invoice(s, cust, [{"item_id": item.id, "qty": "10"}])
    pay = tx.save(s, {"type": "payment", "customer_id": cust.id, "amount": "10"})
    assert inv.balance_cents == 0
    tx.void(s, inv)
    assert inv.voided and inv.balance_cents == 0
    assert pay.balance_cents == 1000
    assert b.balance("Printing Services") == 0
    assert tx.status(inv)[0] == "void"
    with pytest.raises(ValidationError):
        tx.save(s, {"memo": "x"}, txn=inv)
    b.assert_balanced()


def test_invoice_total_cannot_drop_below_payments(s, b):
    cust = b.customer()
    item = b.service(price="1")
    inv = invoice(s, cust, [{"item_id": item.id, "qty": "50"}])
    tx.save(s, {"type": "payment", "customer_id": cust.id, "amount": "50"})
    line_id = inv.lines[0].id
    with pytest.raises(ValidationError):
        tx.save(s, {"lines": [{"id": line_id, "item_id": item.id, "qty": "20"}]}, txn=inv)


def test_sales_receipt_and_refund_receipt(s, b, checking):
    cust = b.customer()
    item = b.service(price="5")
    sr = tx.save(s, {"type": "sales_receipt", "customer_id": cust.id, "account_id": checking.id,
                     "lines": [{"item_id": item.id, "qty": "4"}]})
    assert b.balance("Checking") == 2000
    rr = tx.save(s, {"type": "refund_receipt", "customer_id": cust.id, "account_id": checking.id,
                     "lines": [{"item_id": item.id, "qty": "1"}]})
    assert rr.total_cents == 500
    assert b.balance("Checking") == 1500
    assert b.balance("Printing Services") == -1500
    assert sr.number == "1001" and rr.number == "1001"
    b.assert_balanced()


def test_customer_refund_of_credit_balance(s, b, checking):
    cust = b.customer()
    item = b.service(price="1")
    cm = tx.save(s, {"type": "credit_memo", "customer_id": cust.id, "applications": [],
                     "lines": [{"item_id": item.id, "qty": "25"}]})
    ref = tx.save(s, {"type": "customer_refund", "customer_id": cust.id, "account_id": checking.id,
                      "amount": "25", "applications": [{"txn_id": cm.id, "amount": "25"}]})
    assert cm.balance_cents == 0
    assert ref.balance_cents == 0
    assert b.balance("ar", customer_id=cust.id) == 0
    assert b.balance("Checking") == -2500
    b.assert_balanced()


def test_estimate_converts_and_closes(s, b):
    cust = b.customer()
    item = b.service(price="1")
    est = tx.save(s, {"type": "estimate", "customer_id": cust.id, "lines": [{"item_id": item.id, "qty": "10"}]})
    assert est.status == "pending"
    assert b.balance("ar") == 0  # estimates don't post
    inv = invoice(s, cust, [{"item_id": item.id, "qty": "10"}], source_estimate_id=est.id)
    assert est.status == "closed"
    tx.delete(s, inv)
    assert est.status == "accepted"


def test_delete_and_edit_are_audited(s, b):
    from sqlalchemy import select

    from pps_tools.books.models import AuditLog

    cust = b.customer()
    item = b.service(price="1")
    inv = invoice(s, cust, [{"item_id": item.id, "qty": "10"}])
    tx.save(s, {"memo": "updated"}, txn=inv)
    tx.delete(s, inv)
    actions = [a.action for a in s.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert actions[-3:] == ["create", "update", "delete"]
    assert s.get(Transaction, inv.id) is None


def test_bundle_expands_into_components(s, b):
    from decimal import Decimal

    from pps_tools.books.models import BundleComponent, Item

    cards = b.service("Cards", "0.10")
    flyers = b.service("Flyers", "0.25")
    kit = Item(name="Starter kit", type="bundle")
    kit.components = [BundleComponent(item_id=cards.id, qty=Decimal(500), position=0),
                      BundleComponent(item_id=flyers.id, qty=Decimal(100), position=1)]
    s.add(kit)
    s.flush()
    cust = b.customer()
    inv = invoice(s, cust, [{"item_id": kit.id, "qty": "2"}])
    kinds = [(ln.kind, ln.item_id, ln.qty) for ln in inv.lines]
    assert kinds[0][0] == "description"
    assert kinds[1] == ("item", cards.id, Decimal(1000))
    assert inv.total_cents == 10000 + 5000


def test_due_on_receipt_and_day_of_month_terms(s, b):
    from pps_tools.books.models import Terms
    from pps_tools.books.services.dates import due_date

    t = Terms(name="15th of next month", kind="day_of_month", day_of_month=15, cutoff_days=10)
    assert due_date(t, date(2026, 3, 2)) == date(2026, 3, 15)
    assert due_date(t, date(2026, 3, 10)) == date(2026, 4, 15)  # within cutoff
    assert due_date(t, date(2026, 3, 20)) == date(2026, 4, 15)
    cust = b.customer(terms_id=b.terms("Due on receipt").id)
    item = b.service(price="1")
    inv = invoice(s, cust, [{"item_id": item.id, "qty": "1"}], date="2026-05-05")
    assert inv.due_date == date(2026, 5, 5)
    assert inv.due_date - inv.date == timedelta(0)
