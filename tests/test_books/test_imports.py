"""CSV imports and the QuickBooks Online migration."""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func, select

from pps_tools.books.models import Account, Customer, Item, LedgerEntry, Transaction, Vendor
from pps_tools.books.services import prefs
from pps_tools.books.services.importers import lists as importer
from pps_tools.books.services.importers.qbo import Migration


def _run(s, kind, text, **kw):
    pv = importer.preview(kind, text.encode())
    return importer.run(s, kind, text.encode(), pv.mapping, **kw), pv


def test_customers_with_header_guessing_and_opening_balances(s, b):
    text = ("Customer Name,Email Address,Phone,Street,City,State,Zip,Terms,Open Balance,As Of\n"
            "Harbor Bakery,orders@harbor.example.com,555-0101,1 Main St,Riverbend,PA,17000,Net 15,250.00,2026-01-01\n"
            "Lakeview League,board@lakeview.example.com,,,,,,,,\n"
            ",nobody@example.com,,,,,,,,\n")
    result, pv = _run(s, "customers", text, default_date=date(2026, 1, 1))
    assert pv.mapping["display_name"] == 0 and pv.mapping["bill_postal"] == 6 and pv.mapping["opening_balance"] == 8
    assert (result.created, len(result.errors)) == (2, 1)
    harbor = s.scalar(select(Customer).where(Customer.display_name == "Harbor Bakery"))
    assert harbor.bill_city == "Riverbend" and harbor.terms.name == "Net 15" and harbor.terms.due_days == 15
    inv = s.scalar(select(Transaction).where(Transaction.customer_id == harbor.id))
    assert inv.type == "invoice" and inv.balance_cents == 25000
    assert b.balance("opening_balance_equity") == -25000
    again, _ = _run(s, "customers", text)
    assert again.created == 0 and again.skipped == 2
    b.assert_balanced()


def test_update_existing_fills_blanks(s, b):
    b.customer("Harbor Bakery", email=None)
    result, _ = _run(s, "customers", "Name,Email\nHarbor Bakery,new@harbor.example.com\n", on_duplicate="update")
    assert result.updated == 1
    assert s.scalar(select(Customer.email).where(Customer.display_name == "Harbor Bakery")) == "new@harbor.example.com"


def test_vendors_with_1099_flag(s, b):
    result, _ = _run(s, "vendors", "Vendor,Tax ID,1099,Balance\nJordan Lee Design,123-45-6789,yes,800\nPaper Co,,no,\n")
    assert result.created == 2
    jordan = s.scalar(select(Vendor).where(Vendor.display_name == "Jordan Lee Design"))
    assert jordan.track_1099 and jordan.masked_tax_id == "•••••6789"
    assert b.balance("ap") == -80000


def test_items_including_inventory_and_categories(s, b):
    text = ("Product/Service Name,SKU,Type,Category,Sales Price,Cost,Qty On Hand,As Of,Income Account\n"
            "Business Cards,BC-500,Service,Printing:Cards,45.00,,,,Printing Services\n"
            "Gloss Paper,PAP-1,Inventory,Paper,28,14,10,2026-01-01,\n"
            "Mystery,,Service,,1,,,,No Such Account\n")
    result, _ = _run(s, "items", text)
    assert result.created == 2 and len(result.errors) == 1 and "No Such Account" in result.errors[0][1]
    cards = s.scalar(select(Item).where(Item.name == "Business Cards"))
    assert cards.category.full_name == "Printing:Cards" and cards.income_account.name == "Printing Services"
    paper = s.scalar(select(Item).where(Item.name == "Gloss Paper"))
    assert paper.type == "inventory" and paper.qty_on_hand == 10 and paper.inventory_value_cents == 14000
    b.assert_balanced()


def test_chart_of_accounts_with_subaccounts_and_balances(s, b):
    text = ("Number,Account,Type,Detail Type,Balance\n"
            "1050,Money Market,Bank,Money Market,5000\n"
            "6125,Rent & Lease:Storage Unit,Expenses,,\n"
            "2750,Equipment Loan,Long Term Liabilities,,12000\n"
            ",Bad Type Account,Wizardry,,\n")
    result, _ = _run(s, "accounts", text, default_date=date(2026, 1, 1))
    assert result.created == 3 and len(result.errors) == 1
    mm = s.scalar(select(Account).where(Account.name == "Money Market"))
    assert b.balance("Money Market") == 500000
    storage = s.scalar(select(Account).where(Account.name == "Storage Unit"))
    assert storage.parent.name == "Rent & Lease" and storage.number == "6125"
    assert b.balance("Equipment Loan") == -1200000
    # Bank opening balances come in reconciled, so the first reconciliation starts there.
    assert {e.cleared for e in s.scalars(select(LedgerEntry).where(LedgerEntry.account_id == mm.id))} == {"R"}
    b.assert_balanced()


def test_journal_entries_group_by_date_and_number_and_must_balance(s, b):
    text = ("Date,Journal No,Account,Debit,Credit,Description\n"
            "2026-01-31,JE-1,Depreciation Expense,250,,Monthly depreciation\n"
            "2026-01-31,JE-1,Accumulated Depreciation,,250,\n"
            "2026-01-31,JE-2,Checking,100,,\n"
            "2026-01-31,JE-2,Owner's Investment,,90,\n")
    result, _ = _run(s, "journal", text)
    assert result.created == 1 and len(result.errors) == 1 and "doesn't balance" in result.errors[0][1]
    assert b.balance("Depreciation Expense") == 25000
    je = s.scalar(select(Transaction).where(Transaction.type == "journal_entry", Transaction.number == "JE-1"))
    assert je is not None
    b.assert_balanced()


# -- QuickBooks Online --------------------------------------------------------------------------------


class FakeQBO:
    def __init__(self, data: dict[str, list], tb_rows: list):
        self.data = data
        self.tb_rows = tb_rows
        self.queries = []

    def query(self, sql: str) -> dict:
        self.queries.append(sql)
        entity = re.search(r"FROM (\w+)", sql).group(1)
        rows = list(self.data.get(entity, []))
        where = re.search(r"WHERE (.+?) STARTPOSITION", sql)
        if where and "Balance > '0'" in where.group(1):
            rows = [r for r in rows if float(r.get("Balance", 0)) > 0]
        if where and "UnappliedAmt > '0'" in where.group(1):
            rows = [r for r in rows if float(r.get("UnappliedAmt", 0)) > 0]
        if where and "Type = 'Inventory'" in where.group(1):
            rows = [r for r in rows if r.get("Type") == "Inventory"]
        start = int(re.search(r"STARTPOSITION (\d+)", sql).group(1))
        return {"QueryResponse": {entity: rows[start - 1:start - 1 + 1000]}}

    def _request(self, method, path, **kwargs):
        assert path == "/reports/TrialBalance"
        return {"Rows": {"Row": [{"ColData": [{"value": name, "id": qid}, {"value": dr}, {"value": cr}]}
                                 for qid, name, dr, cr in self.tb_rows] +
                         [{"Summary": {"ColData": [{"value": "TOTAL"}]}, "type": "Section"}]}}


def _qbo_company():
    accounts = [
        {"Id": "1", "Name": "Business Checking", "AccountType": "Bank", "AccountSubType": "Checking", "AcctNum": "1001"},
        {"Id": "2", "Name": "Accounts Receivable (A/R)", "AccountType": "Accounts Receivable",
         "AccountSubType": "AccountsReceivable"},
        {"Id": "3", "Name": "Accounts Payable (A/P)", "AccountType": "Accounts Payable", "AccountSubType": "AccountsPayable"},
        {"Id": "4", "Name": "Inventory Asset", "AccountType": "Other Current Asset", "AccountSubType": "Inventory"},
        {"Id": "5", "Name": "Opening Balance Equity", "AccountType": "Equity", "AccountSubType": "OpeningBalanceEquity"},
        {"Id": "6", "Name": "Retained Earnings", "AccountType": "Equity", "AccountSubType": "RetainedEarnings"},
        {"Id": "7", "Name": "Print Sales", "AccountType": "Income", "AccountSubType": "SalesOfProductIncome"},
        {"Id": "8", "Name": "Shop Rent", "AccountType": "Expense", "AccountSubType": "RentOrLeaseOfBuildings"},
        {"Id": "9", "Name": "Warehouse", "AccountType": "Expense", "AccountSubType": "RentOrLeaseOfBuildings",
         "SubAccount": True, "ParentRef": {"value": "8"}, "FullyQualifiedName": "Shop Rent:Warehouse"},
        {"Id": "10", "Name": "Visa Card", "AccountType": "Credit Card", "AccountSubType": "CreditCard"},
    ]
    data = {
        "Account": accounts,
        "Term": [{"Id": "1", "Name": "Net 30", "Type": "STANDARD", "DueDays": 30},
                 {"Id": "2", "Name": "Net 10 Special", "Type": "STANDARD", "DueDays": 10}],
        "PaymentMethod": [{"Id": "1", "Name": "Visa", "Type": "CREDIT_CARD"}],
        "Class": [{"Id": "1", "Name": "Retail"}], "Department": [{"Id": "1", "Name": "Main Street"}],
        "TaxAgency": [{"Id": "1", "DisplayName": "State Revenue"}],
        "TaxRate": [{"Id": "1", "Name": "State 6%", "RateValue": "6", "AgencyRef": {"value": "1"}}],
        "TaxCode": [{"Id": "2", "Name": "State", "SalesTaxRateList": {"TaxRateDetail": [{"TaxRateRef": {"value": "1"}}]}}],
        "Customer": [
            {"Id": "1", "DisplayName": "Harbor Bakery", "PrimaryEmailAddr": {"Address": "a@harbor.example.com"},
             "BillAddr": {"Line1": "1 Main", "City": "Riverbend", "CountrySubDivisionCode": "PA", "PostalCode": "17000"},
             "SalesTermRef": {"value": "1"}, "DefaultTaxCodeRef": {"value": "2"}, "Taxable": True},
            {"Id": "2", "DisplayName": "Spring Menu", "ParentRef": {"value": "1"}, "IsProject": True, "Job": True,
             "FullyQualifiedName": "Harbor Bakery:Spring Menu"},
        ],
        "Vendor": [{"Id": "1", "DisplayName": "Paper Co", "Vendor1099": False},
                   {"Id": "2", "DisplayName": "Jordan Lee", "Vendor1099": True, "TaxIdentifier": "XXXXX6789"}],
        "Employee": [{"Id": "1", "DisplayName": "Alex Morgan", "BillRate": 65, "CostRate": 28}],
        "Item": [
            {"Id": "1", "Name": "Business Cards", "Type": "Service", "UnitPrice": 45, "IncomeAccountRef": {"value": "7"}},
            {"Id": "2", "Name": "Gloss Paper", "Type": "Inventory", "UnitPrice": 28, "PurchaseCost": 14, "QtyOnHand": 10,
             "IncomeAccountRef": {"value": "7"}, "AssetAccountRef": {"value": "4"}},
        ],
        "Invoice": [{"Id": "10", "DocNumber": "1042", "TxnDate": "2025-12-15", "DueDate": "2026-01-14",
                     "CustomerRef": {"value": "1"}, "TotalAmt": 400, "Balance": 300},
                    {"Id": "11", "DocNumber": "1043", "TxnDate": "2025-12-20", "CustomerRef": {"value": "1"},
                     "TotalAmt": 100, "Balance": 0}],
        "CreditMemo": [], "VendorCredit": [],
        "Payment": [{"Id": "20", "TxnDate": "2025-12-28", "CustomerRef": {"value": "2"}, "TotalAmt": 50, "UnappliedAmt": 50}],
        "Bill": [{"Id": "30", "DocNumber": "PC-77", "TxnDate": "2025-12-10", "DueDate": "2026-01-09",
                  "VendorRef": {"value": "1"}, "TotalAmt": 120, "Balance": 120}],
    }
    # Trial balance on 12/31/2025: checking 5,000; A/R 250 (300 open less 50 unapplied); inventory 140;
    # A/P 120; visa 75 owed; equity and P&L make up the rest.
    tb = [("1", "Business Checking", "5000.00", ""), ("2", "A/R", "250.00", ""), ("4", "Inventory Asset", "140.00", ""),
          ("3", "A/P", "", "120.00"), ("10", "Visa Card", "", "75.00"), ("6", "Retained Earnings", "", "3000.00"),
          ("7", "Print Sales", "", "6195.00"), ("8", "Shop Rent", "3600.00", ""), ("9", "Warehouse", "400.00", "")]
    return data, tb


def test_qbo_migration_lists_open_items_and_balances(s, b):
    data, tb = _qbo_company()
    fake = FakeQBO(data, tb)
    report = Migration(s, fake, date(2025, 12, 31)).run()
    assert not report.errors, report.errors
    assert report.counts["accounts"] >= 4 and report.counts["customers"] == 1 and report.counts["projects"] == 1
    warehouse = s.scalar(select(Account).where(Account.name == "Warehouse"))
    assert warehouse.parent.name == "Shop Rent"
    proj = s.scalar(select(Customer).where(Customer.display_name == "Spring Menu"))
    assert proj.is_project and proj.parent.display_name == "Harbor Bakery"
    harbor = proj.parent
    assert harbor.default_tax_rate.name == "State 6%" and harbor.terms.name == "Net 30"
    inv = s.scalar(select(Transaction).where(Transaction.type == "invoice", Transaction.number == "1042"))
    assert inv.balance_cents == 30000 and inv.due_date == date(2026, 1, 14) and "originally $400.00" in inv.memo
    assert s.scalar(select(func.count(Transaction.id)).where(Transaction.number == "1043")) == 0  # paid in QBO
    assert b.balance("Business Checking") == 500000 and b.balance("ar") == 25000 and b.balance("ap") == -12000
    assert b.balance("inventory_asset") == 14000 and b.balance("Visa Card") == -7500
    assert b.balance("Print Sales") == -619500 and b.balance("Warehouse") == 40000
    # Everything ties out, so Opening Balance Equity ends where QBO had it (zero here).
    assert report.obe_difference_cents == 0 and b.balance("opening_balance_equity") == 0
    checking = s.scalar(select(Account).where(Account.name == "Business Checking"))
    assert {e.cleared for e in s.scalars(select(LedgerEntry).where(LedgerEntry.account_id == checking.id))} == {"R"}
    jordan = s.scalar(select(Vendor).where(Vendor.display_name == "Jordan Lee"))
    assert jordan.track_1099 and jordan.tax_id is None
    assert any("tax IDs" in n for n in report.notes)
    b.assert_balanced()

    # A second run brings nothing over twice.
    before = s.scalar(select(func.count(Transaction.id)))
    again = Migration(s, FakeQBO(data, tb), date(2025, 12, 31)).run()
    assert s.scalar(select(func.count(Transaction.id))) == before
    assert again.counts.get("customers", 0) == 0
    assert set(prefs.get(s, "qbo_import")["done"]) == {"open_items", "balances"}


def test_qbo_failed_step_forgets_its_ids(s, b):
    data, tb = _qbo_company()
    data["Customer"] = data["Customer"][:1]
    data["Invoice"] = [{"Id": "10", "DocNumber": "1042", "TxnDate": "not-a-date", "CustomerRef": {"value": "1"},
                        "TotalAmt": 400, "Balance": 300}]
    report = Migration(s, FakeQBO(data, tb), date(2025, 12, 31)).run(balances=False)
    assert any("1042" in e for e in report.errors)
    assert s.scalar(select(func.count(Transaction.id)).where(Transaction.type == "invoice")) == 0
    b.assert_balanced()
