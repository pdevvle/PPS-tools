"""CSV imports: customers, vendors, products and services, the chart of
accounts, and journal entries.

``preview`` reads the header and guesses which column feeds which field;
``run`` imports with the mapping the person confirmed. Each row succeeds or
fails on its own (inside a savepoint), so one bad row doesn't sink the file.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pps_tools.books import money
from pps_tools.books.models import (ACCOUNT_TYPES, DETAIL_TYPES, Account, Customer, Item, ItemCategory, LedgerEntry,
                                    Location, Terms, TrackingClass, User, Vendor)
from pps_tools.books.services import audit
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.accounts import system_account_id, validate_account
from pps_tools.books.services.dates import parse_date
from pps_tools.books.services.errors import BooksError, ValidationError

MAX_ROWS = 20000


@dataclass
class ImportField:
    key: str
    label: str
    required: bool = False
    aliases: tuple[str, ...] = ()
    hint: str = ""


@dataclass
class ImportSpec:
    kind: str
    label: str
    fields: list[ImportField]
    description: str


def _f(key, label, *aliases, required=False, hint=""):
    return ImportField(key, label, required, tuple(aliases), hint)


ADDRESS = [
    _f("bill_line1", "Street", "street", "address", "billing address", "billing street", "address 1",
       "street address", "billing address line 1", "address line 1"),
    _f("bill_line2", "Street line 2", "address 2", "billing address line 2", "address line 2", "suite"),
    _f("bill_city", "City", "city", "billing city", "billing address city"),
    _f("bill_state", "State", "state", "billing state", "province", "billing address state", "region"),
    _f("bill_postal", "ZIP", "zip", "zip code", "postal code", "billing zip", "billing address postal code",
       "postcode"),
    _f("bill_country", "Country", "country", "billing country", "billing address country"),
]

SPECS: dict[str, ImportSpec] = {
    "customers": ImportSpec("customers", "Customers", [
        _f("display_name", "Customer name", "name", "customer", "display name", "customer name", "full name",
           required=True),
        _f("company_name", "Company", "company", "company name", "business name"),
        _f("first_name", "First name", "first", "given name"), _f("last_name", "Last name", "last", "family name",
                                                                   "surname"),
        _f("email", "Email", "email", "email address", "e-mail", "main email"),
        _f("phone", "Phone", "phone", "phone number", "telephone", "main phone", "work phone"),
        _f("mobile", "Mobile", "mobile", "cell", "mobile phone", "cell phone"),
        _f("website", "Website", "website", "web", "url"),
        *ADDRESS,
        _f("terms", "Terms", "terms", "payment terms"),
        _f("taxable", "Taxable", "taxable", "tax", hint="yes/no"),
        _f("resale_number", "Resale number", "resale no", "resale number", "tax id", "exemption details"),
        _f("notes", "Notes", "notes", "note", "memo"),
        _f("opening_balance", "Open balance", "balance", "open balance", "opening balance", "balance total",
           hint="Becomes an opening-balance invoice"),
        _f("opening_date", "Open balance as of", "as of", "balance date", "opening balance date"),
    ], "Names, contact details, addresses and what they owe you today."),
    "vendors": ImportSpec("vendors", "Vendors", [
        _f("display_name", "Vendor name", "name", "vendor", "display name", "vendor name", "supplier", required=True),
        _f("company_name", "Company", "company", "company name"),
        _f("first_name", "First name", "first"), _f("last_name", "Last name", "last"),
        _f("email", "Email", "email", "email address"),
        _f("phone", "Phone", "phone", "phone number", "telephone"),
        _f("website", "Website", "website", "url"),
        *ADDRESS,
        _f("terms", "Terms", "terms"),
        _f("account_number", "Account no.", "account no", "account number", "acct no"),
        _f("tax_id", "Tax ID", "tax id", "ein", "ssn", "tin", "business id no"),
        _f("track_1099", "Track for 1099", "1099", "track 1099", "1099 tracking", "eligible for 1099", hint="yes/no"),
        _f("notes", "Notes", "notes", "memo"),
        _f("opening_balance", "Open balance", "balance", "open balance", "opening balance",
           hint="Becomes an opening-balance bill"),
        _f("opening_date", "Open balance as of", "as of", "balance date"),
    ], "Suppliers and contractors, and what you owe them today."),
    "items": ImportSpec("items", "Products and services", [
        _f("name", "Name", "name", "product", "service", "product/service", "product/service name", "item",
           "item name", required=True),
        _f("sku", "SKU", "sku", "item code", "code", "part number"),
        _f("type", "Type", "type", "item type", hint="service, non-inventory or inventory"),
        _f("category", "Category", "category", "product category"),
        _f("description", "Sales description", "description", "sales description"),
        _f("sales_price", "Sales price", "price", "sales price", "rate", "sales price/rate", "unit price"),
        _f("income_account", "Income account", "income account"),
        _f("taxable", "Taxable", "taxable", "is taxable", hint="yes/no"),
        _f("purchase_description", "Purchase description", "purchase description"),
        _f("cost", "Cost", "cost", "purchase cost", "unit cost"),
        _f("expense_account", "Expense account", "expense account", "cogs account"),
        _f("qty_on_hand", "Quantity on hand", "qty", "quantity", "qty on hand", "quantity on hand", "stock"),
        _f("as_of", "Quantity as of", "as of", "inventory start date", "as of date"),
        _f("reorder_point", "Reorder point", "reorder point", "reorder", "low stock alert"),
    ], "What you sell and buy. Inventory starting quantities come in at cost."),
    "accounts": ImportSpec("accounts", "Chart of accounts", [
        _f("number", "Number", "number", "account number", "no", "acct no", "account #", "code"),
        _f("name", "Name", "name", "account", "account name", required=True,
           hint="Parent:Child makes a sub-account"),
        _f("type", "Type", "type", "account type", required=True),
        _f("detail_type", "Detail type", "detail type", "detail"),
        _f("description", "Description", "description"),
        _f("opening_balance", "Opening balance", "balance", "opening balance", "beginning balance"),
        _f("opening_date", "Balance as of", "as of", "balance date", "opening balance date"),
    ], "Accounts with their types; balances become opening entries against Opening Balance Equity."),
    "journal": ImportSpec("journal", "Journal entries", [
        _f("date", "Date", "date", "journal date", "transaction date", required=True),
        _f("number", "Journal no.", "journal no", "journal number", "entry no", "number", "no", "ref",
           hint="Rows with the same date and number make one entry"),
        _f("account", "Account", "account", "account name", "account number", required=True),
        _f("debit", "Debit", "debit", "debits", "dr"),
        _f("credit", "Credit", "credit", "credits", "cr"),
        _f("amount", "Amount (signed)", "amount", hint="Positive for debits, negative for credits"),
        _f("description", "Description", "description", "memo", "line description"),
        _f("name", "Name", "name", "customer", "vendor", "payee"),
        _f("class", "Class", "class"),
        _f("location", "Location", "location", "department"),
    ], "Journal lines; rows sharing a date and number become one balanced entry."),
}


# -- reading ---------------------------------------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9#/]+", " ", (text or "").lower()).strip()


def read_csv(data: bytes | str) -> tuple[list[str], list[list[str]]]:
    if isinstance(data, bytes):
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    else:
        text = data
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if not rows:
        raise ValidationError("The file is empty.")
    # Exports often start with a title block; the header is the first row with 2+ filled cells.
    start = next((i for i, r in enumerate(rows[:10]) if sum(1 for c in r if c.strip()) >= 2), 0)
    header = [h.strip() for h in rows[start]]
    body = [r + [""] * (len(header) - len(r)) for r in rows[start + 1:]]
    if len(body) > MAX_ROWS:
        raise ValidationError(f"Import at most {MAX_ROWS:,} rows at a time.")
    return header, body


def guess_mapping(kind: str, header: list[str]) -> dict[str, Optional[int]]:
    spec = SPECS[kind]
    normalized = [_norm(h) for h in header]
    used: set[int] = set()
    out: dict[str, Optional[int]] = {}
    for fl in spec.fields:
        choices = [_norm(fl.label), _norm(fl.key.replace("_", " ")), *(_norm(a) for a in fl.aliases)]
        idx = next((i for c in choices for i, h in enumerate(normalized) if h == c and i not in used), None)
        out[fl.key] = idx
        if idx is not None:
            used.add(idx)
    return out


@dataclass
class Preview:
    header: list[str]
    sample: list[list[str]]
    mapping: dict[str, Optional[int]]
    rows: int


def preview(kind: str, data: bytes | str) -> Preview:
    if kind not in SPECS:
        raise ValidationError("Unknown import type.")
    header, body = read_csv(data)
    return Preview(header, body[:5], guess_mapping(kind, header), len(body))


# -- importing ------------------------------------------------------------------------------------------


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)

    @property
    def ok(self) -> int:
        return self.created + self.updated


def run(s: Session, kind: str, data: bytes | str, mapping: dict[str, Optional[int]], user: Optional[User] = None,
        on_duplicate: str = "skip", default_date: Optional[date] = None) -> ImportResult:
    spec = SPECS.get(kind)
    if spec is None:
        raise ValidationError("Unknown import type.")
    for fl in spec.fields:
        if fl.required and mapping.get(fl.key) is None:
            raise ValidationError(f"Choose the column for “{fl.label}”.")
    header, body = read_csv(data)
    ctx = _Ctx(s, user, on_duplicate, default_date or date.today())
    result = ImportResult()

    def value(row: list[str], key: str) -> str:
        idx = mapping.get(key)
        return row[idx].strip() if idx is not None and idx < len(row) else ""

    if kind == "journal":
        _import_journal(ctx, body, value, result)
    else:
        handler: Callable = {"customers": _customer, "vendors": _vendor, "items": _item, "accounts": _account}[kind]
        rows = list(enumerate(body, start=2))
        if kind == "accounts":
            # Parents first, so "Parent:Child" rows find their parent.
            rows.sort(key=lambda nr: value(nr[1], "name").count(":"))
        for n, row in rows:
            get = lambda key, row=row: value(row, key)  # noqa: E731
            try:
                with s.begin_nested():
                    outcome = handler(ctx, get)
                if outcome == "created":
                    result.created += 1
                elif outcome == "updated":
                    result.updated += 1
                else:
                    result.skipped += 1
            except (BooksError, money.MoneyError, ValueError) as exc:
                result.errors.append((n, str(exc)))
    audit.record(s, user, "import", kind, None,
                 summary=f"Imported {spec.label.lower()}: {result.created} added, {result.updated} updated, "
                         f"{result.skipped} skipped, {len(result.errors)} with errors")
    return result


@dataclass
class _Ctx:
    s: Session
    user: Optional[User]
    on_duplicate: str
    default_date: date
    _terms: dict = field(default_factory=dict)

    def terms_id(self, name: str) -> Optional[int]:
        if not name:
            return None
        key = name.lower()
        if key not in self._terms:
            t = self.s.scalar(select(Terms).where(func.lower(Terms.name) == key))
            if t is None:
                m = re.match(r"^net\s*(\d+)$", key)
                t = Terms(name=name, kind="days", due_days=int(m.group(1)) if m else 0, active=True)
                self.s.add(t)
                self.s.flush()
            self._terms[key] = t.id
        return self._terms[key]


def _yes(text: str) -> Optional[bool]:
    if not text:
        return None
    return text.strip().lower() in ("y", "yes", "true", "1", "x", "taxable", "on")


def _opening_date(ctx: _Ctx, text: str) -> date:
    return parse_date(text, ctx.default_date) if text else ctx.default_date


def _set(obj, attr: str, value: Any, overwrite: bool) -> None:
    if value in (None, ""):
        return
    if overwrite or getattr(obj, attr) in (None, ""):
        setattr(obj, attr, value)


def _person(ctx: _Ctx, model, get, extra: Callable) -> str:
    s = ctx.s
    name = get("display_name") or " ".join(p for p in (get("first_name"), get("last_name")) if p) or get("company_name")
    if not name:
        raise ValidationError("No name.")
    obj = s.scalar(select(model).where(func.lower(model.display_name) == name.lower()))
    outcome = "created"
    if obj is not None:
        if ctx.on_duplicate != "update":
            return "skipped"
        outcome = "updated"
    else:
        obj = model(display_name=name, active=True)
        s.add(obj)
    overwrite = outcome == "updated"
    for attr in ("company_name", "first_name", "last_name", "email", "phone", "website", "bill_line1", "bill_line2",
                 "bill_city", "bill_state", "bill_postal", "bill_country", "notes"):
        _set(obj, attr, get(attr) or None, overwrite)
    if get("email") and "@" not in get("email"):
        raise ValidationError(f"“{get('email')}” isn't an email address.")
    if get("terms"):
        obj.terms_id = ctx.terms_id(get("terms"))
    extra(obj, overwrite)
    s.flush()
    balance = money.cents(get("opening_balance")) if get("opening_balance") else 0
    if balance and outcome == "created":
        when = _opening_date(ctx, get("opening_date"))
        obe = system_account_id(s, "opening_balance_equity")
        if model is Customer:
            tx.save(s, {"type": "invoice", "customer_id": obj.id, "date": when.isoformat(), "memo": "Opening balance",
                        "apply_credits": False, "tax_rate_id": None,
                        "lines": [{"kind": "item", "account_id": obe, "description": "Opening balance",
                                   "amount_cents": balance, "taxable": False}]}, user=ctx.user, source="import")
        else:
            tx.save(s, {"type": "bill", "vendor_id": obj.id, "date": when.isoformat(), "memo": "Opening balance",
                        "lines": [{"kind": "account", "account_id": obe, "description": "Opening balance",
                                   "amount_cents": balance}]}, user=ctx.user, source="import")
    return outcome


def _customer(ctx: _Ctx, get) -> str:
    def extra(c: Customer, overwrite: bool) -> None:
        _set(c, "mobile", get("mobile") or None, overwrite)
        _set(c, "resale_number", get("resale_number") or None, overwrite)
        taxable = _yes(get("taxable"))
        if taxable is not None:
            c.taxable = taxable
        elif c.taxable is None:
            c.taxable = True
        if c.ship_same_as_bill is None:
            c.ship_same_as_bill = True
        if not c.preferred_delivery:
            c.preferred_delivery = "email"

    return _person(ctx, Customer, get, extra)


def _vendor(ctx: _Ctx, get) -> str:
    def extra(v: Vendor, overwrite: bool) -> None:
        _set(v, "account_number", get("account_number") or None, overwrite)
        _set(v, "tax_id", get("tax_id") or None, overwrite)
        t1099 = _yes(get("track_1099"))
        if t1099 is not None:
            v.track_1099 = t1099
        elif v.track_1099 is None:
            v.track_1099 = False

    return _person(ctx, Vendor, get, extra)


def find_account(s: Session, text: str) -> Optional[Account]:
    """By number, full name ('Parent:Child'), 'number name', or a unique plain name."""
    text = (text or "").strip()
    if not text:
        return None
    acct = s.scalar(select(Account).where(Account.number == text))
    if acct is not None:
        return acct
    m = re.match(r"^(\d[\w.-]*)\s+(.*)$", text)
    if m:
        acct = s.scalar(select(Account).where(Account.number == m.group(1)))
        if acct is not None:
            return acct
        text = m.group(2)
    accounts = s.scalars(select(Account)).all()
    by_full = [a for a in accounts if a.full_name.lower() == text.lower()]
    if by_full:
        return by_full[0]
    leaf = text.split(":")[-1].strip().lower()
    by_name = [a for a in accounts if a.name.lower() == leaf]
    return by_name[0] if len(by_name) == 1 else None


def _account_type(text: str) -> Optional[str]:
    t = _norm(text)
    if not t:
        return None
    for code, info in ACCOUNT_TYPES.items():
        if t in (_norm(code), _norm(info.label), _norm(info.section)):
            return code
    synonyms = {"accounts receivable": "ar", "a r": "ar", "receivable": "ar", "accounts payable": "ap", "a p": "ap",
                "payable": "ap", "credit card": "credit_card", "cost of goods sold": "cogs", "cost of sales": "cogs",
                "expense": "expense", "expenses": "expense", "other current asset": "other_current_asset",
                "fixed asset": "fixed_asset", "other asset": "other_asset",
                "other current liability": "other_current_liability", "long term liability": "long_term_liability",
                "equity": "equity", "income": "income", "revenue": "income", "other income": "other_income",
                "other expense": "other_expense", "bank": "bank", "cash": "bank"}
    return synonyms.get(t)


def _account(ctx: _Ctx, get) -> str:
    s = ctx.s
    full = get("name")
    parts = [p.strip() for p in full.split(":") if p.strip()]
    if not parts:
        raise ValidationError("No account name.")
    acct_type = _account_type(get("type"))
    if acct_type is None:
        raise ValidationError(f"Unknown account type “{get('type')}”.")
    parent = None
    if len(parts) > 1:
        parent = find_account(s, ":".join(parts[:-1]))
        if parent is None:
            raise ValidationError(f"Parent account “{':'.join(parts[:-1])}” isn't in the chart yet.")
    existing = s.scalar(select(Account).where(func.lower(Account.name) == parts[-1].lower(),
                                              Account.parent_id.is_(None) if parent is None
                                              else Account.parent_id == parent.id))
    if existing is None and get("number"):
        existing = s.scalar(select(Account).where(Account.number == get("number")))
    outcome = "created"
    if existing is not None:
        if ctx.on_duplicate != "update":
            return "skipped"
        acct = existing
        outcome = "updated"
        if acct.system_key and acct.type != acct_type:
            raise ValidationError(f"{acct.name} is a built-in account; its type stays {acct.type_label}.")
    else:
        acct = Account(name=parts[-1], active=True)
        s.add(acct)
    acct.name = parts[-1]
    acct.type = acct_type
    acct.parent_id = parent.id if parent else None
    acct.number = get("number") or acct.number
    detail = get("detail_type")
    if detail:
        match = next((d for d in DETAIL_TYPES.get(acct_type, []) if _norm(d) == _norm(detail)), None)
        acct.detail_type = match or detail[:80]
    acct.description = get("description") or acct.description
    validate_account(s, acct)
    s.flush()
    balance = money.cents(get("opening_balance")) if get("opening_balance") else 0
    if balance and outcome == "created":
        opening_entry(s, acct, balance, _opening_date(ctx, get("opening_date")), ctx.user)
    return outcome


def opening_entry(s: Session, acct: Account, balance_cents: int, when: date, user: Optional[User] = None):
    """A journal entry that gives ``acct`` its starting balance against Opening Balance Equity.

    ``balance_cents`` is in the account's normal direction (a loan's balance is
    positive). Bank and card opening balances are marked reconciled, so the
    first reconciliation starts from them.
    """
    obe = system_account_id(s, "opening_balance_equity")
    if acct.id == obe:
        raise ValidationError("Opening Balance Equity can't have an opening balance of its own.")
    debit = balance_cents * acct.normal
    lines = [{"kind": "account", "account_id": acct.id, "description": "Opening balance",
              "posting_type": "debit" if debit > 0 else "credit", "amount_cents": abs(debit)},
             {"kind": "account", "account_id": obe, "description": f"Opening balance: {acct.full_name}",
              "posting_type": "credit" if debit > 0 else "debit", "amount_cents": abs(debit)}]
    je = tx.save(s, {"type": "journal_entry", "date": when.isoformat(), "memo": f"Opening balance for {acct.full_name}",
                     "lines": lines}, user=user, source="import")
    if acct.type in ("bank", "credit_card"):
        for e in s.scalars(select(LedgerEntry).where(LedgerEntry.txn_id == je.id, LedgerEntry.account_id == acct.id)):
            e.cleared = "R"
    return je


def _item(ctx: _Ctx, get) -> str:
    s = ctx.s
    name = get("name")
    if not name:
        raise ValidationError("No name.")
    it = s.scalar(select(Item).where(func.lower(Item.name) == name.lower()))
    outcome = "created"
    if it is not None:
        if ctx.on_duplicate != "update":
            return "skipped"
        outcome = "updated"
    else:
        it = Item(name=name, active=True, taxable=True)
        s.add(it)
    t = _norm(get("type"))
    new_type = ("inventory" if "inventory" in t and "non" not in t else "non_inventory" if "non" in t
                else "service" if t else None)
    if outcome == "updated" and new_type and new_type != it.type:
        raise ValidationError(f"{name} already exists as a {it.type_label.lower()}; its type can't change on import.")
    it.type = new_type or it.type or "service"
    overwrite = outcome == "updated"
    _set(it, "sku", get("sku") or None, overwrite)
    _set(it, "description", get("description") or None, overwrite)
    _set(it, "purchase_description", get("purchase_description") or None, overwrite)
    if get("sales_price"):
        it.sales_price = money.to_decimal(get("sales_price"))
    if get("cost"):
        it.cost = money.to_decimal(get("cost"))
    taxable = _yes(get("taxable"))
    if taxable is not None:
        it.taxable = taxable
    if get("category"):
        path = [p.strip() for p in get("category").split(":") if p.strip()]
        parent = None
        for part in path:
            cat = s.scalar(select(ItemCategory).where(func.lower(ItemCategory.name) == part.lower(),
                                                      ItemCategory.parent_id.is_(None) if parent is None
                                                      else ItemCategory.parent_id == parent.id))
            if cat is None:
                cat = ItemCategory(name=part, parent_id=parent.id if parent else None)
                s.add(cat)
                s.flush()
            parent = cat
        it.category_id = parent.id if parent else None
    for field_name, attr in (("income_account", "income_account_id"), ("expense_account", "expense_account_id")):
        if get(field_name):
            acct = find_account(s, get(field_name))
            if acct is None:
                raise ValidationError(f"Account “{get(field_name)}” isn't in the chart of accounts.")
            setattr(it, attr, acct.id)
    if it.type == "inventory":
        it.asset_account_id = it.asset_account_id or system_account_id(s, "inventory_asset")
        it.expense_account_id = it.expense_account_id or system_account_id(s, "cogs")
        it.income_account_id = it.income_account_id or system_account_id(s, "sales_income")
        if get("reorder_point"):
            it.reorder_point = money.to_decimal(get("reorder_point"))
    else:
        it.income_account_id = it.income_account_id or system_account_id(
            s, "services_income" if it.type == "service" else "sales_income")
    s.flush()
    qty = money.to_decimal(get("qty_on_hand"), None) if get("qty_on_hand") else None
    if it.type == "inventory" and qty and outcome == "created":
        when = _opening_date(ctx, get("as_of"))
        it.cost = it.cost or Decimal(0)
        tx.save(s, {"type": "inventory_adjustment", "date": when.isoformat(),
                    "account_id": system_account_id(s, "opening_balance_equity"),
                    "memo": f"Starting quantity for {it.name}", "lines": [{"item_id": it.id, "qty": str(qty)}]},
                user=ctx.user, source="import")
        it.inventory_start_date = when
    return outcome


def _import_journal(ctx: _Ctx, body: list[list[str]], value, result: ImportResult) -> None:
    s = ctx.s
    groups: dict[tuple, list[tuple[int, list[str]]]] = {}
    for n, row in enumerate(body, start=2):
        key = (value(row, "date"), value(row, "number"))
        groups.setdefault(key, []).append((n, row))
    lookups: dict[tuple[str, str], Optional[int]] = {}

    def lookup(model, text: str) -> Optional[int]:
        if not text:
            return None
        key = (model.__name__, text.lower())
        if key not in lookups:
            col = model.display_name if model in (Customer, Vendor) else model.name
            lookups[key] = s.scalar(select(model.id).where(func.lower(col) == text.lower()))
        return lookups[key]

    for (when, number), rows in groups.items():
        first_row = rows[0][0]
        try:
            with s.begin_nested():
                entry_date = parse_date(when)
                if entry_date is None:
                    raise ValidationError("No date.")
                lines = []
                for n, row in rows:
                    acct = find_account(s, value(row, "account"))
                    if acct is None:
                        raise ValidationError(f"Row {n}: account “{value(row, 'account')}” isn't in the chart.")
                    debit = money.cents(value(row, "debit")) if value(row, "debit") else 0
                    credit = money.cents(value(row, "credit")) if value(row, "credit") else 0
                    if not debit and not credit and value(row, "amount"):
                        signed = money.cents(value(row, "amount"))
                        debit, credit = (signed, 0) if signed > 0 else (0, -signed)
                    if not debit and not credit:
                        continue
                    line = {"kind": "account", "account_id": acct.id, "description": value(row, "description") or None,
                            "posting_type": "debit" if debit else "credit", "amount_cents": debit or credit,
                            "class_id": lookup(TrackingClass, value(row, "class")),
                            "location_id": lookup(Location, value(row, "location"))}
                    name = value(row, "name")
                    if name:
                        cid, vid = lookup(Customer, name), lookup(Vendor, name)
                        if cid:
                            line["name"] = f"customer:{cid}"
                        elif vid:
                            line["name"] = f"vendor:{vid}"
                    lines.append(line)
                debits = sum(ln["amount_cents"] for ln in lines if ln["posting_type"] == "debit")
                credits = sum(ln["amount_cents"] for ln in lines if ln["posting_type"] == "credit")
                if debits != credits:
                    raise ValidationError(f"Entry {number or ''} on {when} doesn't balance: debits "
                                          f"{money.fmt(debits)}, credits {money.fmt(credits)}.")
                data = {"type": "journal_entry", "date": entry_date.isoformat(), "lines": lines,
                        "memo": "Imported journal entry"}
                if number:
                    data["number"] = number
                tx.save(s, data, user=ctx.user, source="import")
            result.created += 1
        except (BooksError, money.MoneyError, ValueError) as exc:
            result.errors.append((first_row, str(exc)))
