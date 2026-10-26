"""Move a company over from QuickBooks Online, as of a conversion date.

This is the conversion accountants do by hand, automated:

1. Lists: chart of accounts, terms, payment methods, classes, locations
   (QBO departments), sales tax agencies and rates, customers and projects,
   vendors, employees, and products and services.
2. Open items: every unpaid invoice and bill, open credit memo and unapplied
   payment, with its original number, date and due date so aging and
   statements carry on. Each comes in as one line against Opening Balance
   Equity, so its income or expense isn't counted a second time.
3. Inventory: quantities on hand at their purchase cost.
4. Balances: the trial balance on the conversion date as one journal entry.
   A/R, A/P and inventory are left out of it (the open items and quantities
   above make up those balances) and the difference goes to Opening Balance
   Equity. When the details agree with the trial balance, Opening Balance
   Equity ends where it was in QBO; any difference left there is reported.

Bank and card balances in that entry are marked reconciled, so the first
reconciliation here starts from the conversion date. History before the
conversion date stays in QuickBooks (export its reports before you cancel).

Re-running is safe: what was imported is remembered by QBO id and skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator, Optional, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pps_tools.books import money
from pps_tools.books.db import utcnow
from pps_tools.books.models import (DETAIL_TYPES, Account, Customer, Employee, Item, ItemCategory, LedgerEntry,
                                    Location, PaymentMethod, TaxAgency, TaxRate, Terms, TrackingClass, User, Vendor)
from pps_tools.books.services import audit, prefs
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.accounts import system_account, system_account_id, validate_account
from pps_tools.books.services.dates import parse_date
from pps_tools.books.services.errors import BooksError

PAGE = 1000

ACCOUNT_TYPE_MAP = {
    "Bank": "bank", "Accounts Receivable": "ar", "Other Current Asset": "other_current_asset",
    "Fixed Asset": "fixed_asset", "Other Asset": "other_asset", "Accounts Payable": "ap", "Credit Card": "credit_card",
    "Other Current Liability": "other_current_liability", "Long Term Liability": "long_term_liability",
    "Equity": "equity", "Income": "income", "Cost of Goods Sold": "cogs", "Expense": "expense",
    "Other Income": "other_income", "Other Expense": "other_expense",
}
# QBO account sub-types that are the same thing as one of our built-in accounts.
SYSTEM_SUBTYPES = {
    "AccountsReceivable": "ar", "AccountsPayable": "ap", "UndepositedFunds": "undeposited_funds",
    "OpeningBalanceEquity": "opening_balance_equity", "RetainedEarnings": "retained_earnings",
    "SalesTaxPayable": "sales_tax_payable", "GlobalTaxPayable": "sales_tax_payable",
}


class Client(Protocol):
    def query(self, sql: str) -> dict: ...
    def _request(self, method: str, path: str, **kwargs) -> dict: ...


@dataclass
class MigrationReport:
    counts: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    obe_difference_cents: int = 0

    def add(self, what: str, n: int = 1) -> None:
        self.counts[what] = self.counts.get(what, 0) + n

    def skip(self, what: str, n: int = 1) -> None:
        self.skipped[what] = self.skipped.get(what, 0) + n


def _words(camel: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", camel or "").strip()


def _ref(obj: dict, key: str) -> Optional[str]:
    ref = obj.get(key)
    return str(ref["value"]) if isinstance(ref, dict) and ref.get("value") not in (None, "") else None


def _dec(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _cents(value: Any) -> int:
    d = _dec(value)
    return money.round_cents(d * 100) if d is not None else 0


def _addr(obj: dict, key: str, prefix: str) -> dict:
    a = obj.get(key) or {}
    return {f"{prefix}_line1": a.get("Line1"), f"{prefix}_line2": a.get("Line2"), f"{prefix}_city": a.get("City"),
            f"{prefix}_state": a.get("CountrySubDivisionCode"), f"{prefix}_postal": a.get("PostalCode"),
            f"{prefix}_country": a.get("Country")}


class Migration:
    def __init__(self, s: Session, client: Client, conversion_date: date, user: Optional[User] = None):
        self.s = s
        self.client = client
        self.when = conversion_date
        self.user = user
        self.report = MigrationReport()
        state = dict(prefs.get(s, "qbo_import") or {})
        self.map: dict[str, dict[str, int]] = {k: dict(v) for k, v in (state.get("map") or {}).items()}
        self.done: set[str] = set(state.get("done") or [])
        # Inventory quantities seen while importing items: {item_id: qty}.
        self._qty: Optional[dict[int, Decimal]] = None

    # -- plumbing -----------------------------------------------------------------------------------

    def _all(self, entity: str, where: str = "") -> Iterator[dict]:
        start = 1
        while True:
            sql = f"SELECT * FROM {entity}{' WHERE ' + where if where else ''} STARTPOSITION {start} MAXRESULTS {PAGE}"
            rows = (self.client.query(sql).get("QueryResponse") or {}).get(entity) or []
            yield from rows
            if len(rows) < PAGE:
                return
            start += PAGE

    def _id(self, entity: str, qbo_id: Optional[str]) -> Optional[int]:
        return self.map.get(entity, {}).get(str(qbo_id)) if qbo_id else None

    def _remember(self, entity: str, qbo_id: Any, local_id: int) -> None:
        self.map.setdefault(entity, {})[str(qbo_id)] = local_id

    def _save_state(self) -> None:
        prefs.set_many(self.s, {"qbo_import": {"map": self.map, "done": sorted(self.done),
                                               "conversion_date": self.when.isoformat(),
                                               "updated_at": utcnow().isoformat()}})

    def _step(self, name: str, fn) -> None:
        """Run one part in a savepoint so a failure leaves the others in place."""
        saved = ({k: dict(v) for k, v in self.map.items()}, set(self.done),
                 dict(self._qty) if self._qty is not None else None)
        try:
            with self.s.begin_nested():
                fn()
            self._save_state()
            self.s.flush()
        except (BooksError, money.MoneyError, KeyError, ValueError, TypeError) as exc:
            # The savepoint undid the rows; forget the ids that pointed at them.
            self.map, self.done, self._qty = saved
            self.report.errors.append(f"{name}: {exc}")

    def _row(self, label: str, name: str, fn) -> None:
        """One record in its own savepoint: a bad row is reported and skipped."""
        saved = {k: dict(v) for k, v in self.map.items()}
        try:
            with self.s.begin_nested():
                fn()
        except (BooksError, money.MoneyError, ValueError) as exc:
            self.map = saved
            self.report.errors.append(f"{label} “{name}”: {exc}")

    def run(self, lists: bool = True, open_items: bool = True, balances: bool = True) -> MigrationReport:
        if lists:
            for name, fn in (("Accounts", self.accounts), ("Terms", self.terms), ("Payment methods", self.payment_methods),
                             ("Classes", self.classes), ("Locations", self.locations), ("Sales tax", self.sales_tax),
                             ("Customers", self.customers), ("Vendors", self.vendors), ("Employees", self.employees),
                             ("Products and services", self.items)):
                self._step(name, fn)
        if open_items and "open_items" not in self.done:
            self._step("Open invoices and bills", self.open_items)
        if balances and "balances" not in self.done:
            self._step("Inventory", self.inventory)
            self._step("Trial balance", self.trial_balance)
        audit.record(self.s, self.user, "import", "quickbooks", None,
                     summary="Imported from QuickBooks Online: " + ", ".join(f"{n} {k}" for k, n in self.report.counts.items()))
        self._save_state()
        return self.report

    # -- lists -----------------------------------------------------------------------------------------

    def accounts(self) -> None:
        rows = list(self._all("Account"))
        rows.sort(key=lambda r: (r.get("FullyQualifiedName") or r.get("Name") or "").count(":"))
        claimed: set[str] = set()
        for r in rows:
            self._row("Account", r.get("Name") or str(r["Id"]), lambda r=r: self._account(r, claimed))

    def _account(self, r: dict, claimed: set[str]) -> None:
        s = self.s
        qid = str(r["Id"])
        if self._id("Account", qid):
            self.report.skip("accounts")
            return
        atype = ACCOUNT_TYPE_MAP.get(r.get("AccountType"))
        if atype is None:
            self.report.errors.append(f"Account {r.get('Name')}: unknown type {r.get('AccountType')}")
            return
        subtype = r.get("AccountSubType") or ""
        key = SYSTEM_SUBTYPES.get(subtype)
        if key is None and atype in ("ar", "ap"):
            key = atype
        if key is None and subtype == "Inventory" and "inventory_asset" not in claimed:
            key = "inventory_asset"
        if key and key not in claimed and not r.get("SubAccount"):
            claimed.add(key)
            acct = system_account(s, key)
            if r.get("AcctNum") and not acct.number:
                acct.number = r["AcctNum"]
            self._remember("Account", qid, acct.id)
            self.report.add("accounts mapped to built-in ones")
            return
        parent_id = self._id("Account", _ref(r, "ParentRef"))
        name = (r.get("Name") or "").replace(":", "-").strip()
        existing = s.scalar(select(Account).where(func.lower(Account.name) == name.lower(),
                                                  Account.parent_id.is_(None) if parent_id is None
                                                  else Account.parent_id == parent_id))
        if existing is not None and existing.type == atype:
            self._remember("Account", qid, existing.id)
            self.report.skip("accounts")
            return
        if existing is not None:
            name = f"{name} ({_words(r.get('AccountType'))})"
        detail = _words(subtype)
        match = next((d for d in DETAIL_TYPES.get(atype, []) if d.lower().replace(" ", "") ==
                      detail.lower().replace(" ", "")), None)
        number = r.get("AcctNum") or None
        if number and s.scalar(select(Account.id).where(Account.number == number)):
            number = None
        acct = Account(name=name, type=atype, detail_type=match or detail[:80] or None, parent_id=parent_id,
                       number=number, description=r.get("Description"), active=bool(r.get("Active", True)))
        validate_account(s, acct)
        s.add(acct)
        s.flush()
        self._remember("Account", qid, acct.id)
        self.report.add("accounts")

    def terms(self) -> None:
        for r in self._all("Term"):
            if self._id("Term", r["Id"]):
                continue
            t = self.s.scalar(select(Terms).where(func.lower(Terms.name) == (r.get("Name") or "").lower()))
            if t is None:
                date_driven = r.get("Type") == "DATE_DRIVEN"
                t = Terms(name=r.get("Name") or f"Terms {r['Id']}", kind="day_of_month" if date_driven else "days",
                          due_days=int(r.get("DueDays") or 0), day_of_month=r.get("DayOfMonthDue"),
                          cutoff_days=r.get("DueNextMonthDays"), discount_pct=_dec(r.get("DiscountPercent")),
                          discount_days=r.get("DiscountDays"), active=bool(r.get("Active", True)))
                self.s.add(t)
                self.s.flush()
                self.report.add("terms")
            self._remember("Term", r["Id"], t.id)

    def payment_methods(self) -> None:
        for r in self._all("PaymentMethod"):
            if self._id("PaymentMethod", r["Id"]):
                continue
            name = r.get("Name") or f"Method {r['Id']}"
            pm = self.s.scalar(select(PaymentMethod).where(func.lower(PaymentMethod.name) == name.lower()))
            if pm is None:
                kind = "card" if r.get("Type") == "CREDIT_CARD" else (
                    "check" if "check" in name.lower() else "cash" if "cash" in name.lower() else "other")
                pm = PaymentMethod(name=name, kind=kind, active=bool(r.get("Active", True)))
                self.s.add(pm)
                self.s.flush()
                self.report.add("payment methods")
            self._remember("PaymentMethod", r["Id"], pm.id)

    def _tree(self, entity: str, model, label: str) -> None:
        rows = sorted(self._all(entity), key=lambda r: (r.get("FullyQualifiedName") or "").count(":"))
        for r in rows:
            if self._id(entity, r["Id"]):
                continue
            parent_id = self._id(entity, _ref(r, "ParentRef"))
            name = (r.get("Name") or "").strip() or f"{label} {r['Id']}"
            obj = self.s.scalar(select(model).where(func.lower(model.name) == name.lower(),
                                                    model.parent_id.is_(None) if parent_id is None
                                                    else model.parent_id == parent_id))
            if obj is None:
                obj = model(name=name, parent_id=parent_id, active=bool(r.get("Active", True)))
                self.s.add(obj)
                self.s.flush()
                self.report.add(label)
            self._remember(entity, r["Id"], obj.id)

    def classes(self) -> None:
        self._tree("Class", TrackingClass, "classes")
        if self.map.get("Class") and prefs.get(self.s, "track_classes") == "off":
            prefs.set_many(self.s, {"track_classes": "per_line"})

    def locations(self) -> None:
        self._tree("Department", Location, "locations")
        if self.map.get("Department"):
            prefs.set_many(self.s, {"track_locations": True})

    def sales_tax(self) -> None:
        s = self.s
        for r in self._all("TaxAgency"):
            if self._id("TaxAgency", r["Id"]):
                continue
            name = r.get("DisplayName") or f"Agency {r['Id']}"
            ag = s.scalar(select(TaxAgency).where(func.lower(TaxAgency.name) == name.lower()))
            if ag is None:
                ag = TaxAgency(name=name, filing_frequency="quarterly", reporting_method="accrual", active=True)
                s.add(ag)
                s.flush()
                self.report.add("tax agencies")
            self._remember("TaxAgency", r["Id"], ag.id)
        for r in self._all("TaxRate"):
            if self._id("TaxRate", r["Id"]):
                continue
            name = r.get("Name") or f"Rate {r['Id']}"
            rate = s.scalar(select(TaxRate).where(func.lower(TaxRate.name) == name.lower()))
            if rate is None:
                rate = TaxRate(name=name, rate=_dec(r.get("RateValue")) or Decimal(0),
                               agency_id=self._id("TaxAgency", _ref(r, "AgencyRef")), is_combined=False,
                               description=r.get("Description"), active=bool(r.get("Active", True)))
                s.add(rate)
                s.flush()
                self.report.add("tax rates")
            self._remember("TaxRate", r["Id"], rate.id)
        for r in self._all("TaxCode"):
            details = ((r.get("SalesTaxRateList") or {}).get("TaxRateDetail")) or []
            comps = [self._id("TaxRate", _ref(d, "TaxRateRef")) for d in details]
            comps = [c for c in comps if c]
            if len(comps) < 2 or self._id("TaxCode", r["Id"]):
                if len(comps) == 1:
                    self._remember("TaxCode", r["Id"], comps[0])
                continue
            name = r.get("Name") or f"Tax code {r['Id']}"
            combined = s.scalar(select(TaxRate).where(func.lower(TaxRate.name) == name.lower()))
            if combined is None:
                combined = TaxRate(name=name, is_combined=True, rate=Decimal(0), active=bool(r.get("Active", True)),
                                   components=[s.get(TaxRate, c) for c in comps])
                s.add(combined)
                s.flush()
                self.report.add("combined tax rates")
            self._remember("TaxCode", r["Id"], combined.id)

    def _person(self, entity: str, model, r: dict) -> Optional[Any]:
        qid = str(r["Id"])
        if self._id(entity, qid):
            self.report.skip(entity.lower() + "s")
            return None
        name = (r.get("DisplayName") or "").strip() or f"{entity} {qid}"
        if self.s.scalar(select(model.id).where(func.lower(model.display_name) == name.lower())):
            # Same name already here (created by hand or an earlier import): link to it.
            existing = self.s.scalar(select(model).where(func.lower(model.display_name) == name.lower()))
            self._remember(entity, qid, existing.id)
            self.report.skip(entity.lower() + "s")
            return None
        obj = model(display_name=name, active=bool(r.get("Active", True)))
        obj.company_name = r.get("CompanyName")
        obj.title = r.get("Title")
        obj.first_name = r.get("GivenName")
        obj.middle_name = r.get("MiddleName")
        obj.last_name = r.get("FamilyName")
        obj.suffix = r.get("Suffix")
        obj.email = (r.get("PrimaryEmailAddr") or {}).get("Address")
        obj.phone = (r.get("PrimaryPhone") or {}).get("FreeFormNumber")
        obj.mobile = (r.get("Mobile") or {}).get("FreeFormNumber")
        obj.fax = (r.get("Fax") or {}).get("FreeFormNumber")
        obj.website = (r.get("WebAddr") or {}).get("URI")
        obj.notes = r.get("Notes")
        for k, v in _addr(r, "BillAddr" if entity != "Employee" else "PrimaryAddr", "bill").items():
            setattr(obj, k, v)
        return obj

    def customers(self) -> None:
        rows = sorted(self._all("Customer"), key=lambda r: (r.get("FullyQualifiedName") or "").count(":"))
        for r in rows:
            def one(r=r) -> None:
                c = self._person("Customer", Customer, r)
                if c is None:
                    return
                ship = _addr(r, "ShipAddr", "ship")
                c.ship_same_as_bill = not any(ship.values())
                for k, v in ship.items():
                    setattr(c, k, v)
                c.taxable = bool(r.get("Taxable", True))
                c.resale_number = r.get("ResaleNum")
                c.terms_id = self._id("Term", _ref(r, "SalesTermRef"))
                c.payment_method_id = self._id("PaymentMethod", _ref(r, "PaymentMethodRef"))
                c.default_tax_rate_id = self._id("TaxCode", _ref(r, "DefaultTaxCodeRef"))
                c.parent_id = self._id("Customer", _ref(r, "ParentRef"))
                c.bill_with_parent = bool(r.get("BillWithParent", False))
                c.is_project = bool(r.get("IsProject", False))
                if c.is_project:
                    c.project_status = "in_progress"
                c.cc_email = None
                c.preferred_delivery = "email"
                self.s.add(c)
                self.s.flush()
                self._remember("Customer", r["Id"], c.id)
                self.report.add("projects" if c.is_project else "customers")

            self._row("Customer", r.get("DisplayName") or str(r["Id"]), one)

    def vendors(self) -> None:
        for r in self._all("Vendor"):
            def one(r=r) -> None:
                v = self._person("Vendor", Vendor, r)
                if v is None:
                    return
                v.terms_id = self._id("Term", _ref(r, "TermRef"))
                v.account_number = r.get("AcctNum")
                tin = r.get("TaxIdentifier") or ""
                # QBO masks tax IDs in the API ("XXXXX1234"); keep only real digits.
                v.tax_id = tin if tin and "X" not in tin.upper() else None
                v.track_1099 = bool(r.get("Vendor1099", False))
                self.s.add(v)
                self.s.flush()
                self._remember("Vendor", r["Id"], v.id)
                self.report.add("vendors")
                if tin and v.tax_id is None and v.track_1099:
                    self.report.notes.append(f"{v.display_name}: QuickBooks doesn't share full tax IDs; add it before filing 1099s.")

            self._row("Vendor", r.get("DisplayName") or str(r["Id"]), one)

    def employees(self) -> None:
        for r in self._all("Employee"):
            e = self._person("Employee", Employee, r)
            if e is None:
                continue
            e.employee_number = r.get("EmployeeNumber")
            e.hire_date = parse_date(r.get("HiredDate")) if r.get("HiredDate") else None
            e.release_date = parse_date(r.get("ReleasedDate")) if r.get("ReleasedDate") else None
            e.billable_rate = _dec(r.get("BillRate"))
            e.cost_rate = _dec(r.get("CostRate"))
            self.s.add(e)
            self.s.flush()
            self._remember("Employee", r["Id"], e.id)
            self.report.add("employees")

    def items(self) -> None:
        s = self.s
        rows = list(self._all("Item"))
        categories = [r for r in rows if r.get("Type") == "Category"]
        categories.sort(key=lambda r: (r.get("FullyQualifiedName") or "").count(":"))
        for r in categories:
            if self._id("Category", r["Id"]):
                continue
            cat = ItemCategory(name=r.get("Name") or "Category", parent_id=self._id("Category", _ref(r, "ParentRef")))
            s.add(cat)
            s.flush()
            self._remember("Category", r["Id"], cat.id)
            self.report.add("product categories")
        kinds = {"Service": "service", "NonInventory": "non_inventory", "Inventory": "inventory", "Group": "bundle"}
        for r in rows:
            if r.get("Type") == "Category" or self._id("Item", r["Id"]):
                continue
            itype = kinds.get(r.get("Type"), "non_inventory")
            if itype == "bundle":
                self.report.notes.append(f"Bundle “{r.get('Name')}” needs its components added by hand.")
            name = (r.get("FullyQualifiedName") or r.get("Name") or "").strip() or f"Item {r['Id']}"
            existing = s.scalar(select(Item).where(func.lower(Item.name) == name.lower()))
            if existing is not None:
                self._remember("Item", r["Id"], existing.id)
                self.report.skip("products")
                continue
            it = Item(name=name, sku=r.get("Sku"), type=itype, description=r.get("Description"),
                      sales_price=_dec(r.get("UnitPrice")), purchase_description=r.get("PurchaseDesc"),
                      cost=_dec(r.get("PurchaseCost")), taxable=bool(r.get("Taxable", True)),
                      active=bool(r.get("Active", True)), reorder_point=_dec(r.get("ReorderPoint")),
                      income_account_id=self._id("Account", _ref(r, "IncomeAccountRef")),
                      expense_account_id=self._id("Account", _ref(r, "ExpenseAccountRef")),
                      category_id=self._id("Category", _ref(r, "ParentRef")))
            if itype == "inventory":
                it.asset_account_id = self._id("Account", _ref(r, "AssetAccountRef")) or system_account_id(s, "inventory_asset")
                it.income_account_id = it.income_account_id or system_account_id(s, "sales_income")
                it.expense_account_id = it.expense_account_id or system_account_id(s, "cogs")
            s.add(it)
            s.flush()
            self._remember("Item", r["Id"], it.id)
            if itype == "inventory" and _dec(r.get("QtyOnHand")):
                self._qty = self._qty if self._qty is not None else {}
                self._qty[it.id] = _dec(r.get("QtyOnHand"))
            self.report.add("products and services")

    # -- open items --------------------------------------------------------------------------------------

    def open_items(self) -> None:
        s = self.s
        obe = system_account_id(s, "opening_balance_equity")
        when = self.when.isoformat()

        def doc(kind: str, party_key: str, party_id: Optional[int], r: dict, amount: int, label: str) -> None:
            if not party_id or amount <= 0:
                return
            original = _cents(r.get("TotalAmt"))
            desc = f"Open balance from QuickBooks {label} {r.get('DocNumber') or ''}".strip()
            if original and original != amount:
                desc += f" (originally {money.fmt(original)})"
            txn_date = r.get("TxnDate") or when
            data = {"type": kind, party_key: party_id, "date": txn_date, "memo": desc,
                    "lines": [{"kind": "item" if kind in ("invoice", "credit_memo") else "account", "account_id": obe,
                               "description": desc, "amount_cents": amount, "taxable": False}]}
            if kind in ("invoice", "bill"):
                data["due_date"] = r.get("DueDate") or txn_date
                if kind == "invoice":
                    data["apply_credits"] = False
                    data["email_to"] = (r.get("BillEmail") or {}).get("Address")
            if r.get("DocNumber"):
                data["number"] = r["DocNumber"]
                data["allow_duplicate"] = True

            def save() -> None:
                tx.save(s, data, user=self.user, source="import")
                self.report.add(f"open {label}s")

            self._row(label.capitalize(), r.get("DocNumber") or str(r.get("Id")), save)

        for r in self._all("Invoice", "Balance > '0'"):
            doc("invoice", "customer_id", self._id("Customer", _ref(r, "CustomerRef")), r, _cents(r.get("Balance")),
                "invoice")
        for r in self._all("CreditMemo"):
            remaining = _cents(r.get("RemainingCredit", r.get("Balance")))
            doc("credit_memo", "customer_id", self._id("Customer", _ref(r, "CustomerRef")), r, remaining, "credit memo")
        for r in self._all("Payment", "UnappliedAmt > '0'"):
            r = dict(r, DocNumber=r.get("PaymentRefNum"))
            doc("credit_memo", "customer_id", self._id("Customer", _ref(r, "CustomerRef")), r,
                _cents(r.get("UnappliedAmt")), "unapplied payment")
        for r in self._all("Bill", "Balance > '0'"):
            doc("bill", "vendor_id", self._id("Vendor", _ref(r, "VendorRef")), r, _cents(r.get("Balance")), "bill")
        for r in self._all("VendorCredit"):
            doc("vendor_credit", "vendor_id", self._id("Vendor", _ref(r, "VendorRef")), r, _cents(r.get("Balance")),
                "vendor credit")
        self.done.add("open_items")

    # -- balances ------------------------------------------------------------------------------------------

    def inventory(self) -> None:
        s = self.s
        qty = self._qty
        if qty is None:
            # Items were imported in an earlier run: ask QBO again for what's on hand.
            qty = {}
            for r in self._all("Item", "Type = 'Inventory'"):
                local = self._id("Item", r["Id"])
                if local and _dec(r.get("QtyOnHand")):
                    qty[local] = _dec(r.get("QtyOnHand"))
        lines = []
        for item_id, q in qty.items():
            it = s.get(Item, item_id)
            if it is None or q <= 0:
                continue
            it.cost = it.cost or Decimal(0)
            it.inventory_start_date = self.when
            lines.append({"item_id": item_id, "qty": str(q)})
        if lines:
            tx.save(s, {"type": "inventory_adjustment", "date": self.when.isoformat(),
                        "account_id": system_account_id(s, "opening_balance_equity"),
                        "memo": "Inventory on hand from QuickBooks", "lines": lines}, user=self.user, source="import")
            self.report.add("inventory items with quantities", len(lines))

    def trial_balance(self) -> None:
        s = self.s
        from pps_tools.books.models import Company
        from pps_tools.books.services.dates import fiscal_year_start

        company = s.get(Company, 1)
        fy_start = fiscal_year_start(self.when, company.fiscal_year_start_month if company else 1)
        data = self.client._request("GET", "/reports/TrialBalance", params={
            "start_date": fy_start.isoformat(), "end_date": self.when.isoformat(), "accounting_method": "Accrual"})
        balances: dict[int, int] = {}
        for qid, debit, credit in _trial_balance_rows(data.get("Rows") or {}):
            local = self._id("Account", qid)
            if local is None:
                self.report.errors.append(f"Trial balance account {qid} wasn't imported; its balance is in Opening Balance Equity.")
                continue
            balances[local] = balances.get(local, 0) + debit - credit
        obe = system_account_id(s, "opening_balance_equity")
        sub_ledgers = {system_account_id(s, "ar"), system_account_id(s, "ap")}
        sub_ledgers |= set(s.scalars(select(Item.asset_account_id).where(Item.type == "inventory",
                                                                          Item.asset_account_id.isnot(None))))
        sub_ledgers.add(system_account_id(s, "inventory_asset"))
        lines = []
        for acct_id, amount in sorted(balances.items()):
            if not amount or acct_id in sub_ledgers or acct_id == obe:
                continue
            lines.append({"kind": "account", "account_id": acct_id, "description": "Balance from QuickBooks",
                          "posting_type": "debit" if amount > 0 else "credit", "amount_cents": abs(amount)})
        plug = -sum(ln["amount_cents"] if ln["posting_type"] == "debit" else -ln["amount_cents"] for ln in lines)
        if plug:
            lines.append({"kind": "account", "account_id": obe, "description": "Balances carried by open items and inventory",
                          "posting_type": "debit" if plug > 0 else "credit", "amount_cents": abs(plug)})
        if lines:
            je = tx.save(s, {"type": "journal_entry", "date": self.when.isoformat(),
                             "memo": f"Balances from QuickBooks Online as of {self.when:%m/%d/%Y}", "lines": lines},
                         user=self.user, source="import")
            cash_accounts = set(s.scalars(select(Account.id).where(Account.type.in_(("bank", "credit_card")))))
            agencies = s.scalars(select(TaxAgency.id).where(TaxAgency.active.is_(True))).all()
            stp = system_account_id(s, "sales_tax_payable")
            for e in s.scalars(select(LedgerEntry).where(LedgerEntry.txn_id == je.id)):
                if e.account_id in cash_accounts:
                    e.cleared = "R"
                if e.account_id == stp and len(agencies) == 1:
                    e.tax_agency_id = agencies[0]
            if balances.get(stp) and len(agencies) != 1:
                self.report.notes.append("Sales tax owed at conversion isn't assigned to an agency; record a sales tax "
                                         "adjustment per agency to split it.")
            self.report.add("trial balance lines", len(lines))
        s.flush()
        expected_obe = balances.get(obe, 0)
        actual_obe = int(s.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0))
                                  .where(LedgerEntry.account_id == obe)) or 0)
        self.report.obe_difference_cents = actual_obe - expected_obe
        if self.report.obe_difference_cents:
            self.report.notes.append(
                f"Opening Balance Equity is {money.fmt(abs(self.report.obe_difference_cents))} "
                f"{'higher' if self.report.obe_difference_cents < 0 else 'lower'} than in QuickBooks. That's usually "
                "inventory valued differently or an invoice paid after the conversion date; check A/R, A/P and "
                "inventory against the QuickBooks balance sheet.")
        self.done.add("balances")


def _trial_balance_rows(rows: dict) -> Iterator[tuple[str, int, int]]:
    for row in rows.get("Row") or []:
        if "Rows" in row:
            yield from _trial_balance_rows(row["Rows"])
        cols = row.get("ColData") or []
        if len(cols) >= 3 and cols[0].get("id"):
            yield str(cols[0]["id"]), _cents((cols[1].get("value") or "0").replace(",", "")), \
                _cents((cols[2].get("value") or "0").replace(",", ""))
