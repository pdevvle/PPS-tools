"""FIFO inventory costing and sales tax."""

from datetime import date
from decimal import Decimal

from pps_tools.books.models import TaxRate
from pps_tools.books.services import inventory
from pps_tools.books.services import tax as tax_service
from pps_tools.books.services import transactions as tx


def buy(s, b, item, qty, rate, when, vendor=None):
    vendor = vendor or b.vendor(f"Vendor {when}")
    return tx.save(s, {"type": "bill", "vendor_id": vendor.id, "date": when,
                       "lines": [{"item_id": item.id, "qty": str(qty), "rate": str(rate)}]})


def sell(s, b, item, qty, when, cust=None, price="5"):
    cust = cust or b.customer(f"Customer {when}")
    return tx.save(s, {"type": "invoice", "customer_id": cust.id, "date": when,
                       "lines": [{"item_id": item.id, "qty": str(qty), "rate": price}]})


def test_fifo_cost_of_goods_sold(s, b):
    paper = b.inventory()
    buy(s, b, paper, 100, "1.00", "2026-01-05")
    buy(s, b, paper, 100, "2.00", "2026-01-10")
    inv = sell(s, b, paper, 150, "2026-01-15")
    assert b.balance("cogs") == 100 * 100 + 50 * 200
    assert paper.qty_on_hand == Decimal(50)
    assert paper.inventory_value_cents == 10000
    assert b.balance("inventory_asset") == 10000
    cogs_entries = [e for e in inv.entries if e.auto == "cogs"]
    assert {e.amount_cents for e in cogs_entries} == {20000, -20000}
    b.assert_balanced()


def test_backdated_purchase_recosts_later_sales(s, b):
    paper = b.inventory()
    buy(s, b, paper, 100, "2.00", "2026-01-10")
    sell(s, b, paper, 100, "2026-01-15")
    assert b.balance("cogs") == 20000
    buy(s, b, paper, 100, "1.00", "2026-01-01")  # cheaper stock that arrived earlier
    assert b.balance("cogs") == 10000  # the sale now uses the older, cheaper layer
    assert paper.qty_on_hand == Decimal(100)
    assert b.balance("inventory_asset") == 20000
    b.assert_balanced()


def test_negative_inventory_trues_up_when_stock_arrives(s, b):
    paper = b.inventory(cost="1.50")
    sell(s, b, paper, 10, "2026-02-01")
    assert b.balance("cogs") == 1500  # costed at the item's purchase cost
    assert paper.qty_on_hand == Decimal(-10)
    buy(s, b, paper, 30, "1.80", "2026-02-05")
    assert b.balance("cogs") == 1800  # corrected to the actual cost
    assert paper.qty_on_hand == Decimal(20)
    assert b.balance("inventory_asset") == paper.inventory_value_cents == 3600
    b.assert_balanced()


def test_returns_and_adjustments(s, b, checking):
    paper = b.inventory()
    buy(s, b, paper, 10, "3.00", "2026-03-01")
    cust = b.customer()
    sell(s, b, paper, 4, "2026-03-02", cust=cust)
    tx.save(s, {"type": "credit_memo", "customer_id": cust.id, "date": "2026-03-03", "applications": [],
                "lines": [{"item_id": paper.id, "qty": "1", "rate": "5"}]})
    assert paper.qty_on_hand == Decimal(7)
    assert b.balance("cogs") == 900
    adj = tx.save(s, {"type": "inventory_adjustment", "date": "2026-03-04",
                      "lines": [{"item_id": paper.id, "new_qty": "5"}]})
    assert adj.lines[0].qty == Decimal(-2)
    assert paper.qty_on_hand == Decimal(5)
    assert b.balance("inventory_shrinkage") == 600
    assert adj.total_cents == -600
    v = b.vendor("Returns Vendor")
    tx.save(s, {"type": "vendor_credit", "vendor_id": v.id, "date": "2026-03-05", "applications": [],
                "lines": [{"item_id": paper.id, "qty": "2", "rate": "2.50"}]})
    assert paper.qty_on_hand == Decimal(3)
    assert b.balance("inventory_asset") == paper.inventory_value_cents == 900
    b.assert_balanced()
    _, _, rows = inventory.history(s, paper.id)
    assert [r.qty for r in rows] == [10, -4, 1, -2, -2]
    assert inventory.valuation_as_of(s, paper.id, date(2026, 3, 2)) == (Decimal(6), 1800)


def test_void_sale_restores_stock(s, b):
    paper = b.inventory()
    buy(s, b, paper, 10, "1.00", "2026-01-01")
    inv = sell(s, b, paper, 6, "2026-01-02")
    tx.void(s, inv)
    assert paper.qty_on_hand == Decimal(10)
    assert b.balance("cogs") == 0


def test_combined_rate_splits_by_agency(s, b):
    state = b.tax_rate("WA State", "6.5", "WA Dept of Revenue")
    city = b.tax_rate("Seattle", "3.85", "Seattle City")
    combo = TaxRate(name="Seattle combined", is_combined=True, components=[state, city])
    s.add(combo)
    s.flush()
    assert combo.effective_rate == Decimal("10.35")
    cust = b.customer()
    cards = b.service(price="1")
    inv = tx.save(s, {"type": "invoice", "customer_id": cust.id, "tax_rate_id": combo.id, "date": "2026-04-02",
                      "lines": [{"item_id": cards.id, "qty": "200"}]})
    assert inv.tax_cents == 1300 + 770
    assert tax_service.agency_balance(s, state.agency_id) == 1300
    assert tax_service.agency_balance(s, city.agency_id) == 770
    rows = tax_service.liability_by_rate(s, date(2026, 4, 1), date(2026, 6, 30))
    assert {(r.rate_name, r.taxable_cents, r.tax_cents) for r in rows} == {
        ("WA State", 20000, 1300), ("Seattle", 20000, 770)}

    # Override the tax amount by hand; components keep their proportions.
    tx.save(s, {"tax_amount": "20.00", "tax_override": True}, txn=inv)
    assert inv.tax_cents == 2000 and inv.tax_override
    assert sum(tl.amount_cents for tl in inv.tax_lines) == 2000
    # Pay the state.
    tx.save(s, {"type": "sales_tax_payment", "tax_agency_id": state.agency_id,
                "account_id": b.acct("Checking").id, "amount": "12.56"})
    assert tax_service.agency_balance(s, state.agency_id) == 0
    b.assert_balanced()


def test_exempt_customer_pays_no_tax(s, b):
    rate = b.tax_rate()
    cust = b.customer(taxable=False, tax_exemption_reason="Resale")
    cards = b.service(price="1")
    inv = tx.save(s, {"type": "invoice", "customer_id": cust.id, "tax_rate_id": rate.id,
                      "lines": [{"item_id": cards.id, "qty": "100"}]})
    assert inv.tax_cents == 0 and inv.tax_exempt_reason == "Resale"
