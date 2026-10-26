"""Chart of accounts: system accounts, templates, balances and validation."""

from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pps_tools.books.models import (ACCOUNT_TYPES, DETAIL_TYPES, SYSTEM_ACCOUNTS, Account,
                                    LedgerEntry, Transaction, TransactionLine)
from pps_tools.books.services.errors import ValidationError

# (name, type, detail type, number) for a new company's chart. System
# accounts are added on top of whichever template is chosen.
TEMPLATES: dict[str, list[tuple[str, str, str, str]]] = {
    "general": [
        ("Checking", "bank", "Checking", "1000"),
        ("Savings", "bank", "Savings", "1010"),
        ("Petty Cash", "bank", "Cash on hand", "1020"),
        ("Prepaid Expenses", "other_current_asset", "Prepaid Expenses", "1300"),
        ("Furniture & Equipment", "fixed_asset", "Machinery & Equipment", "1500"),
        ("Vehicles", "fixed_asset", "Vehicles", "1510"),
        ("Accumulated Depreciation", "fixed_asset", "Accumulated Depreciation", "1590"),
        ("Security Deposits", "other_asset", "Security Deposits", "1800"),
        ("Business Credit Card", "credit_card", "Credit Card", "2100"),
        ("Payroll Liabilities", "other_current_liability", "Payroll Tax Payable", "2300"),
        ("Customer Deposits", "other_current_liability", "Customer Deposits", "2350"),
        ("Line of Credit", "other_current_liability", "Line of Credit", "2400"),
        ("Loan Payable", "long_term_liability", "Notes Payable", "2700"),
        ("Owner's Investment", "equity", "Partner Contributions", "3100"),
        ("Owner's Draw", "equity", "Partner Distributions", "3200"),
        ("Interest Earned", "other_income", "Interest Earned", "7000"),
        ("Other Income", "other_income", "Other Miscellaneous Income", "7100"),
        ("Advertising & Marketing", "expense", "Advertising/Promotional", "6000"),
        ("Bank Fees & Service Charges", "expense", "Bank Charges", "6010"),
        ("Contract Labor", "expense", "Cost of Labor", "6020"),
        ("Depreciation Expense", "other_expense", "Depreciation", "8100"),
        ("Dues & Subscriptions", "expense", "Dues & subscriptions", "6030"),
        ("Equipment Rental", "expense", "Equipment Rental", "6040"),
        ("Insurance", "expense", "Insurance", "6050"),
        ("Interest Paid", "expense", "Interest Paid", "6060"),
        ("Legal & Professional Services", "expense", "Legal & Professional Fees", "6070"),
        ("Meals", "expense", "Travel Meals", "6080"),
        ("Office Supplies & Software", "expense", "Office/General Administrative Expenses", "6090"),
        ("Payroll Expenses", "expense", "Payroll Expenses", "6100"),
        ("Postage & Delivery", "expense", "Shipping, Freight & Delivery", "6110"),
        ("Rent & Lease", "expense", "Rent or Lease of Buildings", "6120"),
        ("Repairs & Maintenance", "expense", "Repair & Maintenance", "6130"),
        ("Taxes & Licenses", "expense", "Taxes Paid", "6140"),
        ("Telephone & Internet", "expense", "Communication", "6150"),
        ("Travel", "expense", "Travel", "6160"),
        ("Utilities", "expense", "Utilities", "6170"),
        ("Vehicle Expenses", "expense", "Auto", "6180"),
        ("Penalties & Settlements", "other_expense", "Penalties & Settlements", "8200"),
    ],
    "print_shop": [
        ("Printing Presses & Equipment", "fixed_asset", "Machinery & Equipment", "1520"),
        ("Bindery Equipment", "fixed_asset", "Machinery & Equipment", "1530"),
        ("Printing Services", "income", "Service/Fee Income", "4010"),
        ("Graphic Design", "income", "Service/Fee Income", "4020"),
        ("Rush Fees", "income", "Service/Fee Income", "4030"),
        ("Paper & Stock", "cogs", "Supplies & Materials - COGS", "5010"),
        ("Ink & Toner", "cogs", "Supplies & Materials - COGS", "5020"),
        ("Outsourced Printing", "cogs", "Other Costs of Services - COS", "5030"),
        ("Plates & Prepress", "cogs", "Supplies & Materials - COGS", "5040"),
        ("Freight In", "cogs", "Shipping, Freight & Delivery - COS", "5050"),
        ("Press Maintenance", "expense", "Repair & Maintenance", "6135"),
    ],
}

SYSTEM_NUMBERS = {
    "ar": "1200", "undeposited_funds": "1250", "inventory_asset": "1400", "uncategorized_asset": "1490",
    "stripe_clearing": "1030", "ap": "2000", "sales_tax_payable": "2200", "opening_balance_equity": "3000",
    "retained_earnings": "3900", "sales_income": "4000", "services_income": "4005",
    "shipping_income": "4100", "late_fee_income": "4110", "discounts_given": "4900",
    "refunds_given": "4910", "uncategorized_income": "4999", "cogs": "5000",
    "inventory_shrinkage": "5900", "merchant_fees": "6015", "chargebacks": "6016",
    "uncategorized_expense": "6999", "reconciliation_discrepancies": "8900",
    "exchange_gain_loss": "8950", "sales_tax_adjustments": "8960",
}


def system_account(s: Session, key: str) -> Account:
    """The account the software uses for ``key`` ('ar', 'undeposited_funds'...),
    created on first use so older books pick up new system accounts."""
    acct = s.scalar(select(Account).where(Account.system_key == key))
    if acct is not None:
        return acct
    if key not in SYSTEM_ACCOUNTS:
        raise KeyError(key)
    name, type_, detail = SYSTEM_ACCOUNTS[key]
    existing = s.scalar(select(Account).where(Account.name == name, Account.type == type_,
                                              Account.system_key.is_(None)))
    if existing is not None:
        existing.system_key = key
        return existing
    acct = Account(name=name, type=type_, detail_type=detail, system_key=key,
                   number=SYSTEM_NUMBERS.get(key))
    s.add(acct)
    s.flush()
    return acct


def system_account_id(s: Session, key: str) -> int:
    return system_account(s, key).id


def install_chart(s: Session, template: str = "general", with_numbers: bool = True) -> None:
    for key in SYSTEM_ACCOUNTS:
        acct = system_account(s, key)
        if not with_numbers:
            acct.number = None
    names = TEMPLATES["general"] + (TEMPLATES.get(template, []) if template != "general" else [])
    for name, type_, detail, number in names:
        if s.scalar(select(Account.id).where(Account.name == name)) is None:
            s.add(Account(name=name, type=type_, detail_type=detail,
                          number=number if with_numbers else None))
    s.flush()


def validate_account(s: Session, acct: Account) -> None:
    if not acct.name or not acct.name.strip():
        raise ValidationError("Account name is required.", "name")
    if ":" in acct.name:
        raise ValidationError("Account names can't contain a colon (it separates sub-accounts).", "name")
    if acct.type not in ACCOUNT_TYPES:
        raise ValidationError("Choose an account type.", "type")
    if not acct.detail_type:
        acct.detail_type = DETAIL_TYPES[acct.type][0]
    if acct.parent_id:
        parent = s.get(Account, acct.parent_id)
        if parent is None:
            raise ValidationError("Parent account not found.", "parent_id")
        if parent.type != acct.type:
            raise ValidationError("A sub-account must have the same type as its parent.", "parent_id")
        node = parent
        while node is not None:
            if node.id == acct.id:
                raise ValidationError("An account can't be its own parent.", "parent_id")
            node = node.parent
    # no_autoflush: a new account already added to the session must not be flushed and then found as its own duplicate.
    with s.no_autoflush:
        dup = s.scalar(select(Account).where(func.lower(Account.name) == acct.name.strip().lower(),
                                             Account.parent_id.is_(acct.parent_id) if acct.parent_id is None
                                             else Account.parent_id == acct.parent_id,
                                             Account.id != (acct.id or 0)))
        dupn = s.scalar(select(Account).where(Account.number == acct.number, Account.id != (acct.id or 0))) \
            if acct.number else None
    if dup is not None:
        raise ValidationError(f"Another account is already named “{acct.name}”.", "name")
    if dupn is not None:
        raise ValidationError(f"Account number {acct.number} is already used by {dupn.full_name}.", "number")
    if acct.system_key and acct.id:
        expected_type = SYSTEM_ACCOUNTS.get(acct.system_key, (None, acct.type))[1]
        if expected_type != acct.type:
            raise ValidationError("The type of a system account can't be changed.", "type")


def account_in_use(s: Session, account_id: int) -> bool:
    if s.scalar(select(LedgerEntry.id).where(LedgerEntry.account_id == account_id).limit(1)):
        return True
    if s.scalar(select(TransactionLine.id).where(TransactionLine.account_id == account_id).limit(1)):
        return True
    return bool(s.scalar(select(Transaction.id).where(
        (Transaction.account_id == account_id) | (Transaction.to_account_id == account_id)).limit(1)))


def descendant_ids(s: Session, account_id: int) -> list[int]:
    out, frontier = [account_id], [account_id]
    while frontier:
        kids = s.scalars(select(Account.id).where(Account.parent_id.in_(frontier))).all()
        out.extend(kids)
        frontier = list(kids)
    return out


def balance(s: Session, account_ids: Iterable[int], as_of: Optional[date] = None,
            start: Optional[date] = None, cleared_only: bool = False) -> int:
    """Signed (debit-positive) ledger total for the accounts."""
    q = select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).where(
        LedgerEntry.account_id.in_(list(account_ids)))
    if as_of is not None:
        q = q.where(LedgerEntry.date <= as_of)
    if start is not None:
        q = q.where(LedgerEntry.date >= start)
    if cleared_only:
        q = q.where(LedgerEntry.cleared.in_(("C", "R")))
    return int(s.scalar(q) or 0)


def display_balance(s: Session, acct: Account, as_of: Optional[date] = None,
                    include_children: bool = True) -> int:
    """Balance in the account's natural sign (a credit card's debt is positive)."""
    ids = descendant_ids(s, acct.id) if include_children else [acct.id]
    return balance(s, ids, as_of) * acct.normal


def balances_by_account(s: Session, as_of: Optional[date] = None,
                        start: Optional[date] = None) -> dict[int, int]:
    q = select(LedgerEntry.account_id, func.sum(LedgerEntry.amount_cents)).group_by(LedgerEntry.account_id)
    if as_of is not None:
        q = q.where(LedgerEntry.date <= as_of)
    if start is not None:
        q = q.where(LedgerEntry.date >= start)
    return {aid: int(total or 0) for aid, total in s.execute(q)}


def ordered_accounts(s: Session, active_only: bool = False, types: Optional[Iterable[str]] = None) -> list[Account]:
    """Accounts in chart order: by type, then parent before children, by number/name."""
    q = select(Account)
    if active_only:
        q = q.where(Account.active.is_(True))
    if types:
        q = q.where(Account.type.in_(list(types)))
    accounts = s.scalars(q).all()
    by_parent: dict[Optional[int], list[Account]] = {}
    ids = {a.id for a in accounts}
    for a in accounts:
        parent = a.parent_id if a.parent_id in ids else None
        by_parent.setdefault(parent, []).append(a)

    def sort_key(a: Account):
        return (ACCOUNT_TYPES[a.type].order, a.number or "~", a.name.lower())

    out: list[Account] = []

    def walk(parent_id: Optional[int]) -> None:
        for a in sorted(by_parent.get(parent_id, []), key=sort_key):
            out.append(a)
            walk(a.id)

    walk(None)
    return out
