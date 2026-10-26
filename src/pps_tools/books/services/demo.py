"""A demo company: six months of a small print shop's books.

Everything is made through the same services the app uses, so the demo
exercises posting, inventory, sales tax, the bank feed and reconciliation.
Names are invented; emails use example.com.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from pps_tools.books.models import (Account, BankRule, Budget, BudgetLine, Customer, Employee, Item, MileageTrip,
                                    PaymentMethod, RecurringTemplate, TaxAgency, TaxRate, Terms, TimeActivity,
                                    Transaction, Vehicle, Vendor)
from pps_tools.books.services import banking, prefs, recurring, setup
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.accounts import system_account_id
from pps_tools.books.services.dates import add_months, month_end
from pps_tools.books.services.importers.bankfiles import BankLine, Statement

DEMO_EMAIL = "demo@example.com"

CUSTOMERS = [
    ("Harbor Street Bakery", "Dana Whitfield", "orders@harborstreetbakery.example.com"),
    ("Northside Dental Group", "Priya Raman", "office@northsidedental.example.com"),
    ("Maple & Main Realty", "Chris Okafor", "marketing@maplemain.example.com"),
    ("Lakeview Little League", "Sam Patel", "board@lakeviewll.example.com"),
    ("Crescent Coffee Roasters", "Morgan Bell", "hello@crescentcoffee.example.com"),
    ("Summit Yoga Studio", "Riley Tran", "studio@summityoga.example.com"),
    ("Oak Hill Community Church", "Jordan Ellis", "office@oakhillchurch.example.com"),
    ("Bright Path Tutoring", "Avery Kim", "admin@brightpath.example.com"),
]
VENDORS = [
    ("Paper Source Wholesale", False), ("InkWorks Supply", False), ("Riverside Properties LLC", True),
    ("City Power & Light", False), ("FastFreight Couriers", False), ("Jordan Lee Design", True),
    ("Downtown Office Supply", False), ("Metro Press Repair", True),
]


def build(s: Session, password: str, today: Optional[date] = None, seed: int = 7) -> None:
    today = today or date.today()
    rnd = random.Random(seed)
    setup.create_company(s, "Riverbend Print Co.", DEMO_EMAIL, "Demo Owner", password, industry="print_shop",
                         state="PA")
    from pps_tools.books.models import Company

    company = s.get(Company, 1)
    company.email = "billing@riverbendprint.example.com"
    company.phone = "(555) 010-4477"
    company.address_line1, company.city, company.state, company.postal_code = "212 Mill Street", "Riverbend", "PA", "17000"
    prefs.set_many(s, {"track_time": True, "track_projects": True, "track_inventory": True,
                       "time_billable_by_default": True, "reminders_enabled": True, "reminder_days": [3, 15, 30],
                       "invoice_footer": "Thank you for your business! Checks payable to Riverbend Print Co."})
    acct = {a.name: a for a in s.scalars(select(Account))}
    checking, card = acct["Checking"], acct["Business Credit Card"]
    undeposited = system_account_id(s, "undeposited_funds")
    net30 = s.scalar(select(Terms).where(Terms.name == "Net 30"))
    methods = {m.name: m for m in s.scalars(select(PaymentMethod))}
    check_method = next((m for m in methods.values() if m.kind == "check"), None)
    card_method = next((m for m in methods.values() if m.kind == "card"), None)

    # Sales tax: a state rate plus a county rate, charged together.
    state_ag = TaxAgency(name="Commonwealth Dept. of Revenue", filing_frequency="monthly", active=True)
    county_ag = TaxAgency(name="Riverbend County Treasurer", filing_frequency="quarterly", active=True)
    s.add_all([state_ag, county_ag])
    s.flush()
    state_rate = TaxRate(name="State 6%", rate=Decimal("6"), agency_id=state_ag.id, active=True)
    county_rate = TaxRate(name="County 1%", rate=Decimal("1"), agency_id=county_ag.id, active=True)
    s.add_all([state_rate, county_rate])
    s.flush()
    combined = TaxRate(name="Riverbend 7%", is_combined=True, rate=Decimal(0), active=True,
                       components=[state_rate, county_rate])
    s.add(combined)
    s.flush()

    customers = []
    for i, (name, contact, email) in enumerate(CUSTOMERS):
        first, last = contact.split(" ", 1)
        c = Customer(display_name=name, company_name=name, first_name=first, last_name=last, email=email,
                     phone=f"(555) 010-{1100 + i * 37:04d}", bill_line1=f"{100 + i * 17} {['Main', 'Oak', 'Lake', 'Pine'][i % 4]} St",
                     bill_city="Riverbend", bill_state="PA", bill_postal="17000", terms_id=net30.id,
                     taxable=name != "Oak Hill Community Church", default_tax_rate_id=combined.id, active=True,
                     ship_same_as_bill=True, preferred_delivery="email",
                     tax_exemption_reason="Religious organization" if name == "Oak Hill Community Church" else None)
        s.add(c)
        customers.append(c)
    s.flush()
    project = Customer(display_name="Harbor Street Bakery: Spring Menu Rebrand", parent_id=customers[0].id,
                       is_project=True, project_status="in_progress", bill_with_parent=True,
                       email=customers[0].email, terms_id=net30.id, taxable=True, default_tax_rate_id=combined.id,
                       project_start=today - timedelta(days=40), project_end=today + timedelta(days=20), active=True,
                       ship_same_as_bill=True, preferred_delivery="email",
                       project_description="New menus, window posters and loyalty cards.")
    s.add(project)
    vendors = {}
    for name, t1099 in VENDORS:
        v = Vendor(display_name=name, company_name=name, terms_id=net30.id, track_1099=t1099, active=True,
                   email=f"ap@{name.split()[0].lower()}.example.com", bill_line1="1 Commerce Way", bill_city="Riverbend",
                   bill_state="PA", bill_postal="17000", tax_id="12-3456789" if t1099 else None, w9_on_file=t1099)
        s.add(v)
        vendors[name] = v
    s.flush()

    def item(name, type_, price, income, cost=None, expense=None, desc=None, **kw) -> Item:
        it = Item(name=name, type=type_, sales_price=Decimal(price) if price else None, description=desc or name,
                  income_account_id=acct[income].id if income else None, taxable=kw.pop("taxable", True),
                  cost=Decimal(cost) if cost else None, expense_account_id=acct[expense].id if expense else None,
                  active=True, **kw)
        if type_ == "inventory":
            it.asset_account_id = system_account_id(s, "inventory_asset")
            it.expense_account_id = system_account_id(s, "cogs")
            it.income_account_id = system_account_id(s, "sales_income")
        s.add(it)
        return it

    cards = item("Business Cards (500)", "service", "45.00", "Printing Services", desc="500 business cards, 16pt, full color both sides")
    flyers = item("Flyers (100)", "service", "35.00", "Printing Services", desc="100 flyers, 8.5x11, 100lb gloss")
    banner = item("Vinyl Banner 3x6 ft", "service", "85.00", "Printing Services", desc="13oz vinyl banner with grommets")
    posters = item("Posters 18x24", "service", "18.00", "Printing Services", desc="18x24 poster, satin")
    design = item("Graphic Design", "service", "65.00", "Graphic Design", unit="hr", taxable=False,
                  desc="Design time, billed hourly")
    rush = item("Rush Fee", "service", "25.00", "Rush Fees", desc="Next-day turnaround")
    gloss = item("Gloss Paper 100lb (ream)", "inventory", "28.00", None, cost="14.00", reorder_point=Decimal(10),
                 sku="PAP-G100", purchase_description="100lb gloss text, 500 sheets")
    cardstock = item("Cardstock 110lb (ream)", "inventory", "32.00", None, cost="16.00", reorder_point=Decimal(8),
                     sku="PAP-C110", purchase_description="110lb cover cardstock, 250 sheets")
    s.flush()

    alex = Employee(display_name="Alex Morgan", first_name="Alex", last_name="Morgan", email="alex@riverbendprint.example.com",
                    billable_rate=Decimal("65"), cost_rate=Decimal("28"), hire_date=today - timedelta(days=900), active=True)
    jamie = Employee(display_name="Jamie Chen", first_name="Jamie", last_name="Chen", email="jamie@riverbendprint.example.com",
                     billable_rate=Decimal("55"), cost_rate=Decimal("24"), hire_date=today - timedelta(days=400), active=True)
    s.add_all([alex, jamie])
    van = Vehicle(name="Delivery van", year=2021, make="Ford", model="Transit Connect", active=True)
    s.add(van)
    s.flush()

    start = add_months(today.replace(day=1), -6)
    # Opening balances: the owner's investment and a little starting stock.
    tx.save(s, {"type": "deposit", "account_id": checking.id, "date": start.isoformat(), "memo": "Owner investment",
                "lines": [{"account_id": acct["Owner's Investment"].id, "amount": "25000"}]}, source="import")
    tx.save(s, {"type": "inventory_adjustment", "date": start.isoformat(),
                "account_id": system_account_id(s, "opening_balance_equity"), "memo": "Starting stock",
                "lines": [{"item_id": gloss.id, "qty": "40"}, {"item_id": cardstock.id, "qty": "30"}]}, source="import")

    sale_items = [cards, flyers, banner, posters, rush]
    month = start
    inv_count = 0
    while month <= today:
        m_end = min(month_end(month), today)

        def day(n: int) -> date:
            return min(month + timedelta(days=n), m_end)

        # Rent, utilities, paper and ink.
        rent = tx.save(s, {"type": "bill", "vendor_id": vendors["Riverside Properties LLC"].id, "date": day(0).isoformat(),
                           "number": f"R-{month:%Y%m}", "lines": [{"account_id": acct["Rent & Lease"].id, "amount": "2400"}]})
        if day(4) <= today:
            tx.save(s, {"type": "bill_payment", "vendor_id": rent.vendor_id, "account_id": checking.id,
                        "date": day(4).isoformat(), "amount_cents": rent.total_cents,
                        "applications": [{"txn_id": rent.id, "amount_cents": rent.total_cents}]})
        if day(12) <= today:
            tx.save(s, {"type": "expense", "payee": f"vendor:{vendors['City Power & Light'].id}", "account_id": checking.id,
                        "date": day(12).isoformat(), "payment_method_id": None,
                        "lines": [{"account_id": acct["Utilities"].id, "amount": str(260 + rnd.randint(0, 90))}]})
        paper_bill = tx.save(s, {"type": "bill", "vendor_id": vendors["Paper Source Wholesale"].id,
                                 "date": day(2).isoformat(), "number": f"PS-{4100 + inv_count}",
                                 "lines": [{"item_id": gloss.id, "qty": str(rnd.randint(15, 25)), "rate": "14.00"},
                                           {"item_id": cardstock.id, "qty": str(rnd.randint(10, 18)), "rate": "16.00"},
                                           {"account_id": acct["Freight In"].id, "amount": "38.00"}]})
        if month < add_months(today.replace(day=1), -1) or day(25) <= today - timedelta(days=5):
            if day(25) <= today:
                tx.save(s, {"type": "bill_payment", "vendor_id": paper_bill.vendor_id, "account_id": checking.id,
                            "date": day(25).isoformat(), "amount_cents": paper_bill.total_cents,
                            "applications": [{"txn_id": paper_bill.id, "amount_cents": paper_bill.total_cents}]})
        if day(8) <= today:
            tx.save(s, {"type": "expense", "payee": f"vendor:{vendors['InkWorks Supply'].id}", "account_id": card.id,
                        "date": day(8).isoformat(),
                        "lines": [{"account_id": acct["Ink & Toner"].id, "amount": f"{rnd.randint(180, 420)}.{rnd.randint(0, 99):02d}"}]})
        if day(15) <= today:
            tx.save(s, {"type": "expense", "payee": f"vendor:{vendors['Downtown Office Supply'].id}", "account_id": card.id,
                        "date": day(15).isoformat(),
                        "lines": [{"account_id": acct["Office Supplies & Software"].id, "amount": f"{rnd.randint(40, 140)}.{rnd.randint(0, 99):02d}"}]})
        if day(20) <= today:
            tx.save(s, {"type": "cc_payment", "vendor_id": None, "account_id": checking.id, "to_account_id": card.id,
                        "date": day(20).isoformat(), "amount": str(rnd.randint(300, 500))})
        # Sales: invoices through the month, most paid within a few weeks.
        for _ in range(rnd.randint(6, 9)):
            d = day(rnd.randint(0, 27))
            if d > today:
                continue
            cust = rnd.choice(customers)
            lines = []
            for it in rnd.sample(sale_items, rnd.randint(1, 3)):
                lines.append({"item_id": it.id, "qty": str(rnd.choice([1, 1, 2, 3, 5]))})
            if rnd.random() < 0.35:
                lines.append({"item_id": rnd.choice([gloss, cardstock]).id, "qty": str(rnd.randint(1, 4))})
            inv = tx.save(s, {"type": "invoice", "customer_id": cust.id, "date": d.isoformat(),
                              "tax_rate_id": combined.id if cust.taxable else None, "lines": lines,
                              "email_to": cust.email})
            inv.sent_at = None
            inv_count += 1
            pay_on = d + timedelta(days=rnd.randint(5, 40))
            if pay_on <= today and rnd.random() < 0.85:
                tx.save(s, {"type": "payment", "customer_id": cust.id, "date": pay_on.isoformat(),
                            "amount_cents": inv.total_cents, "account_id": undeposited,
                            "payment_method_id": (check_method if rnd.random() < 0.6 else card_method).id
                            if check_method and card_method else None,
                            "ref_no": str(rnd.randint(1000, 9999)),
                            "applications": [{"txn_id": inv.id, "amount_cents": inv.total_cents}]})
        # Walk-in sales.
        for _ in range(rnd.randint(2, 4)):
            d = day(rnd.randint(0, 27))
            if d > today:
                continue
            tx.save(s, {"type": "sales_receipt", "customer_id": rnd.choice(customers).id, "date": d.isoformat(),
                        "account_id": undeposited, "tax_rate_id": combined.id,
                        "payment_method_id": card_method.id if card_method else None,
                        "lines": [{"item_id": rnd.choice([flyers, posters, cards]).id, "qty": str(rnd.randint(1, 3))}]})
        # Deposit what came in, twice a month.
        for dep_day in (14, 28):
            d = day(dep_day)
            if d > today:
                continue
            waiting = [t.id for t in tx.deposit_candidates(s, None) if t.date <= d]
            if waiting:
                tx.save(s, {"type": "deposit", "account_id": checking.id, "date": d.isoformat(), "deposits": waiting})
        month = add_months(month, 1)

    # Sales tax paid for every month that's closed.
    for ag in (state_ag,):
        from pps_tools.books.services import tax as tax_service

        pay_through = month_end(add_months(today.replace(day=1), -2))
        owed = tax_service.agency_balance(s, ag.id, pay_through)
        if owed > 0:
            tx.save(s, {"type": "sales_tax_payment", "tax_agency_id": ag.id, "account_id": checking.id,
                        "date": (pay_through + timedelta(days=18)).isoformat(), "amount_cents": owed,
                        "memo": f"Sales tax through {pay_through:%m/%d/%Y}"})

    # A 1099 contractor and a press repair.
    for i, amount in enumerate(("650", "780", "540")):
        d = today - timedelta(days=150 - i * 45)
        tx.save(s, {"type": "check", "payee": f"vendor:{vendors['Jordan Lee Design'].id}", "account_id": checking.id,
                    "date": d.isoformat(), "number": str(1201 + i),
                    "lines": [{"account_id": acct["Contract Labor"].id, "amount": amount,
                               "description": "Freelance design overflow"}]})
    tx.save(s, {"type": "bill", "vendor_id": vendors["Metro Press Repair"].id, "date": (today - timedelta(days=9)).isoformat(),
                "number": "MPR-2290", "lines": [{"account_id": acct["Press Maintenance"].id, "amount": "1175.00",
                                                 "description": "Roller replacement, offset press"}]})

    # Estimates: one waiting, one accepted.
    tx.save(s, {"type": "estimate", "customer_id": customers[2].id, "date": (today - timedelta(days=6)).isoformat(),
                "tax_rate_id": combined.id, "expiration_date": (today + timedelta(days=24)).isoformat(),
                "lines": [{"item_id": banner.id, "qty": "4"}, {"item_id": posters.id, "qty": "25"}]})
    tx.save(s, {"type": "estimate", "customer_id": customers[3].id, "date": (today - timedelta(days=20)).isoformat(),
                "tax_rate_id": combined.id, "status": "accepted",
                "lines": [{"item_id": banner.id, "qty": "6"}, {"item_id": flyers.id, "qty": "10"}]})

    # Project time, some of it already billed.
    for i in range(10):
        d = today - timedelta(days=35 - i * 3)
        s.add(TimeActivity(date=d, employee_id=(alex if i % 2 == 0 else jamie).id, customer_id=project.id, item_id=design.id,
                           minutes=rnd.choice([60, 90, 120, 150]), billable=True,
                           hourly_rate=Decimal("65"), description=rnd.choice(
                               ["Menu layout", "Poster concepts", "Loyalty card design", "Client revisions", "Prepress"])))
    s.flush()
    tx.save(s, {"type": "expense", "payee": f"vendor:{vendors['FastFreight Couriers'].id}", "account_id": card.id,
                "date": (today - timedelta(days=12)).isoformat(),
                "lines": [{"account_id": acct["Postage & Delivery"].id, "amount": "42.50", "customer_id": project.id,
                           "billable": True, "description": "Courier: proofs to client"}]})
    for i in range(14):
        d = today - timedelta(days=60 - i * 4)
        s.add(MileageTrip(date=d, vehicle_id=van.id, start_location="Shop", end_location=rnd.choice(
            ["Harbor Street Bakery", "Northside Dental", "Paper Source warehouse", "Lakeview fields", "Post office"]),
            miles=Decimal(str(rnd.choice([4.2, 7.8, 12.5, 18.0, 3.1]))), purpose="business",
            notes="Delivery"))

    # A monthly recurring invoice and its template.
    recurring.save_template(s, RecurringTemplate(
        name="Summit Yoga monthly flyers", txn_type="invoice", mode="scheduled", interval="monthly", every=1,
        day_of_month=1, start_date=add_months(today.replace(day=1), 1), occurrences=0, active=True, auto_send=True,
        days_in_advance=0), {"type": "invoice", "customer_id": customers[5].id, "tax_rate_id": combined.id,
                              "lines": [{"item_id": flyers.id, "qty": "2", "description": "Monthly class schedule flyers"}]})
    recurring.save_template(s, RecurringTemplate(
        name="Shop rent", txn_type="bill", mode="reminder", interval="monthly", every=1, day_of_month=1,
        start_date=add_months(today.replace(day=1), 1), occurrences=0, active=True, days_in_advance=5),
        {"type": "bill", "vendor_id": vendors["Riverside Properties LLC"].id,
         "lines": [{"account_id": acct["Rent & Lease"].id, "amount": "2400"}]})

    # This year's budget, from a rough monthly plan.
    fy = company.fiscal_year_start_month
    budget = Budget(name=f"FY{today.year} plan", fiscal_year=today.year if today.month >= fy else today.year - 1,
                    subdivide_by="none", active=True)
    s.add(budget)
    s.flush()
    plan = {"Printing Services": 5200, "Graphic Design": 900, "Paper & Stock": 1200, "Ink & Toner": 300,
            "Rent & Lease": 2400, "Utilities": 300, "Office Supplies & Software": 100}
    for name, monthly in plan.items():
        for period in range(1, 13):
            s.add(BudgetLine(budget_id=budget.id, account_id=acct[name].id, period=period, amount_cents=monthly * 100))

    # The bank feed: last two weeks of the checking statement, some already in the books.
    rule = BankRule(name="Power bill", direction="out", conditions=[{"field": "description", "op": "contains",
                                                                     "value": "CITY POWER"}],
                    action="expense", vendor_id=vendors["City Power & Light"].id, account_id=acct["Utilities"].id,
                    account_ids=[checking.id], active=True)
    s.add(rule)
    s.flush()
    lines = []
    for t in s.scalars(select(Transaction).where(Transaction.type.in_(("deposit", "bill_payment")),
                                                 Transaction.account_id == checking.id,
                                                 Transaction.date >= today - timedelta(days=14))):
        sign = 1 if t.type == "deposit" else -1
        lines.append(BankLine(date=t.date, amount_cents=sign * t.total_cents,
                              description=("DEPOSIT" if sign > 0 else f"CHECK {t.number or ''} {t.entity_name}").strip(),
                              external_id=f"demo-{t.id}"))
    extras = [(3, -1899, "RIVERBEND COFFEE HOUSE"), (5, -6400, "CITY POWER & LIGHT AUTOPAY"),
              (6, -2999, "SOFTWARE SUBSCRIPTION MONTHLY"), (9, 412, "INTEREST PAYMENT"), (11, -1250, "MONTHLY SERVICE FEE"),
              (2, -4750, "FUEL STOP 57442 RIVERBEND")]
    for ago, amount, desc in extras:
        lines.append(BankLine(date=today - timedelta(days=ago), amount_cents=amount, description=desc,
                              external_id=f"demo-x{ago}"))
    banking.import_statement(s, checking, Statement(lines=sorted(lines, key=lambda ln: ln.date)), source="demo",
                             filename="checking-demo.csv")
    s.flush()
