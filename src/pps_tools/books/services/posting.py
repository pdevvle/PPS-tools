"""The posting engine: transaction -> general ledger entries.

Each posting type turns its document into debits and credits. Entries are
rebuilt from scratch every time a transaction is saved; cleared and
reconciled marks on bank-side entries are carried across the rebuild so
editing a memo doesn't undo a reconciliation. Cost of goods sold for
inventory items is posted separately by :mod:`.inventory`, which owns the
entries marked ``auto='cogs'``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pps_tools.books.models import Account, Item, LedgerEntry, Transaction, TransactionLine
from pps_tools.books.services.accounts import system_account_id
from pps_tools.books.services.errors import ValidationError


@dataclass
class Entry:
    account_id: int
    amount: int  # +debit / -credit
    line: Optional[TransactionLine] = None
    memo: Optional[str] = None
    customer_id: Optional[int] = None
    vendor_id: Optional[int] = None
    employee_id: Optional[int] = None
    item_id: Optional[int] = None
    class_id: Optional[int] = None
    location_id: Optional[int] = None
    tax_rate_id: Optional[int] = None
    tax_agency_id: Optional[int] = None
    qty: Optional[object] = None
    extra: dict = field(default_factory=dict)


def _is_amount_line(line: TransactionLine) -> bool:
    return line.kind in ("item", "account")


def income_account_id(s: Session, line: TransactionLine) -> int:
    if line.item_id:
        item = s.get(Item, line.item_id)  # not line.item: it can lag a changed item_id
        if item and item.income_account_id:
            return item.income_account_id
        if item and item.type == "inventory":
            return system_account_id(s, "sales_income")
    if line.account_id:
        return line.account_id
    return system_account_id(s, "uncategorized_income")


def purchase_account_id(s: Session, line: TransactionLine) -> int:
    """Where a purchase line is debited: its category, or the item's
    expense / inventory asset account."""
    if line.kind == "account" or not line.item_id:
        if not line.account_id:
            return system_account_id(s, "uncategorized_expense")
        return line.account_id
    item = s.get(Item, line.item_id)
    if item.type == "inventory":
        return item.asset_account_id or system_account_id(s, "inventory_asset")
    if item.expense_account_id:
        return item.expense_account_id
    if line.account_id:
        return line.account_id
    return system_account_id(s, "uncategorized_expense")


def _dims(txn: Transaction, line: Optional[TransactionLine] = None) -> dict:
    """Class and location: the line's own, else the transaction's."""
    return {
        "class_id": (line.class_id if line is not None else None) or txn.class_id,
        "location_id": (line.location_id if line is not None else None) or txn.location_id,
    }


def _ar_ap(s: Session, txn: Transaction, key: str) -> int:
    if txn.ar_ap_account_id:
        return txn.ar_ap_account_id
    txn.ar_ap_account_id = system_account_id(s, key)
    return txn.ar_ap_account_id


def _require_account(txn: Transaction, attr: str = "account_id") -> int:
    value = getattr(txn, attr)
    if not value:
        label = txn.info.header_account or "account"
        raise ValidationError(f"Choose the {label.lower()} for this {txn.info.label.lower()}.", attr)
    return value


# -- per-type builders ---------------------------------------------------------


def _sales_doc(s: Session, txn: Transaction, debit_account: int, sign: int) -> list[Entry]:
    """Invoice and sales receipt (sign=+1); credit memo and refund receipt (sign=-1)."""
    cust = txn.customer_id
    out: list[Entry] = []
    for line in txn.lines:
        if not _is_amount_line(line) or line.amount_cents == 0:
            continue
        out.append(Entry(income_account_id(s, line), -sign * line.amount_cents, line=line,
                         memo=line.description, customer_id=cust, item_id=line.item_id, qty=line.qty,
                         **_dims(txn, line)))
    if txn.discount_cents:
        out.append(Entry(system_account_id(s, "discounts_given"), sign * txn.discount_cents,
                         memo="Discount", customer_id=cust, **_dims(txn)))
    for tl in txn.tax_lines:
        if tl.amount_cents:
            out.append(Entry(system_account_id(s, "sales_tax_payable"), -sign * tl.amount_cents,
                             memo=f"Sales tax: {tl.tax_rate.name if tl.tax_rate else ''}".strip(),
                             customer_id=cust, tax_rate_id=tl.tax_rate_id, tax_agency_id=tl.agency_id,
                             **_dims(txn)))
    if txn.shipping_cents:
        out.append(Entry(system_account_id(s, "shipping_income"), -sign * txn.shipping_cents,
                         memo="Shipping", customer_id=cust, **_dims(txn)))
    out.insert(0, Entry(debit_account, sign * txn.total_cents, memo=txn.memo, customer_id=cust, **_dims(txn)))
    return out


def _purchase_doc(s: Session, txn: Transaction, credit_account: int, sign: int) -> list[Entry]:
    """Bill, expense, check (sign=+1); vendor credit, credit card credit (sign=-1)."""
    out: list[Entry] = []
    payee = {"vendor_id": txn.vendor_id, "customer_id": None, "employee_id": txn.employee_id}
    if txn.customer_id and not txn.vendor_id:
        payee["customer_id"] = txn.customer_id  # a check written to a customer (e.g. a refund)
    for line in txn.lines:
        if not _is_amount_line(line) or line.amount_cents == 0:
            continue
        dims = dict(payee)
        if line.customer_id:
            dims["customer_id"] = line.customer_id  # job costing / billable
        out.append(Entry(purchase_account_id(s, line), sign * line.amount_cents, line=line,
                         memo=line.description, item_id=line.item_id, qty=line.qty,
                         **dims, **_dims(txn, line)))
    out.insert(0, Entry(credit_account, -sign * txn.total_cents, memo=txn.memo, **payee, **_dims(txn)))
    return out


def _payment(s: Session, txn: Transaction) -> list[Entry]:
    deposit_to = _require_account(txn)
    ar = _ar_ap(s, txn, "ar")
    cust = txn.customer_id
    return [
        Entry(deposit_to, txn.total_cents, memo=txn.memo, customer_id=cust, **_dims(txn)),
        Entry(ar, -txn.total_cents, memo=txn.memo, customer_id=cust, **_dims(txn)),
    ]


def _customer_refund(s: Session, txn: Transaction) -> list[Entry]:
    paid_from = _require_account(txn)
    ar = _ar_ap(s, txn, "ar")
    cust = txn.customer_id
    return [
        Entry(ar, txn.total_cents, memo=txn.memo, customer_id=cust, **_dims(txn)),
        Entry(paid_from, -txn.total_cents, memo=txn.memo, customer_id=cust, **_dims(txn)),
    ]


def _bill_payment(s: Session, txn: Transaction) -> list[Entry]:
    paid_from = _require_account(txn)
    ap = _ar_ap(s, txn, "ap")
    vend = txn.vendor_id
    return [
        Entry(ap, txn.total_cents, memo=txn.memo, vendor_id=vend, **_dims(txn)),
        Entry(paid_from, -txn.total_cents, memo=txn.memo, vendor_id=vend, **_dims(txn)),
    ]


def _deposit(s: Session, txn: Transaction) -> list[Entry]:
    bank = _require_account(txn)
    out: list[Entry] = []
    for link in txn.links_out:
        if link.link_type != "deposit":
            continue
        src = link.to_txn
        # Money waiting in a holding account (Payments to deposit) moves to the bank.
        holding = src.account_id or system_account_id(s, "undeposited_funds")
        sign = -1 if src.type == "refund_receipt" else 1
        out.append(Entry(holding, -sign * link.amount_cents, memo=f"Deposit of {src.info.label.lower()}",
                         customer_id=src.customer_id, **_dims(txn)))
    for line in txn.lines:
        if line.kind != "account" or line.amount_cents == 0:
            continue
        if not line.account_id:
            raise ValidationError("Each deposit line needs an account.", "lines")
        out.append(Entry(line.account_id, -line.amount_cents, line=line, memo=line.description,
                         customer_id=line.customer_id, vendor_id=line.vendor_id,
                         employee_id=line.employee_id, **_dims(txn, line)))
    out.insert(0, Entry(bank, txn.total_cents, memo=txn.memo, **_dims(txn)))
    return out


def _transfer(s: Session, txn: Transaction) -> list[Entry]:
    src = _require_account(txn)
    dst = _require_account(txn, "to_account_id")
    if src == dst:
        raise ValidationError("Transfer from and to the same account.", "to_account_id")
    return [
        Entry(dst, txn.total_cents, memo=txn.memo, **_dims(txn)),
        Entry(src, -txn.total_cents, memo=txn.memo, **_dims(txn)),
    ]


def _cc_payment(s: Session, txn: Transaction) -> list[Entry]:
    bank = _require_account(txn)
    card = _require_account(txn, "to_account_id")
    return [
        Entry(card, txn.total_cents, memo=txn.memo, vendor_id=txn.vendor_id, **_dims(txn)),
        Entry(bank, -txn.total_cents, memo=txn.memo, vendor_id=txn.vendor_id, **_dims(txn)),
    ]


def _journal(s: Session, txn: Transaction) -> list[Entry]:
    out: list[Entry] = []
    for line in txn.lines:
        if line.kind != "account" or line.amount_cents == 0:
            continue
        out.append(Entry(line.account_id, line.signed_cents, line=line, memo=line.description,
                         customer_id=line.customer_id, vendor_id=line.vendor_id,
                         employee_id=line.employee_id, **_dims(txn, line)))
    return out


def _sales_tax_payment(s: Session, txn: Transaction) -> list[Entry]:
    paid_from = _require_account(txn)
    stp = system_account_id(s, "sales_tax_payable")
    return [
        Entry(stp, txn.total_cents, memo=txn.memo or "Sales tax payment", tax_agency_id=txn.tax_agency_id),
        Entry(paid_from, -txn.total_cents, memo=txn.memo or "Sales tax payment",
              tax_agency_id=txn.tax_agency_id),
    ]


def _sales_tax_adjustment(s: Session, txn: Transaction) -> list[Entry]:
    acct = _require_account(txn)
    stp = system_account_id(s, "sales_tax_payable")
    # Positive total increases what's owed to the agency.
    return [
        Entry(acct, txn.total_cents, memo=txn.memo or "Sales tax adjustment", tax_agency_id=txn.tax_agency_id),
        Entry(stp, -txn.total_cents, memo=txn.memo or "Sales tax adjustment", tax_agency_id=txn.tax_agency_id),
    ]


def build_entries(s: Session, txn: Transaction) -> list[Entry]:
    t = txn.type
    if not txn.info.posts or txn.voided:
        return []
    if t == "invoice":
        return _sales_doc(s, txn, _ar_ap(s, txn, "ar"), 1)
    if t == "sales_receipt":
        return _sales_doc(s, txn, _require_account(txn), 1)
    if t == "credit_memo":
        return _sales_doc(s, txn, _ar_ap(s, txn, "ar"), -1)
    if t == "refund_receipt":
        return _sales_doc(s, txn, _require_account(txn), -1)
    if t == "payment":
        return _payment(s, txn)
    if t == "customer_refund":
        return _customer_refund(s, txn)
    if t == "bill":
        return _purchase_doc(s, txn, _ar_ap(s, txn, "ap"), 1)
    if t == "vendor_credit":
        return _purchase_doc(s, txn, _ar_ap(s, txn, "ap"), -1)
    if t in ("expense", "check"):
        return _purchase_doc(s, txn, _require_account(txn), 1)
    if t == "cc_credit":
        return _purchase_doc(s, txn, _require_account(txn), -1)
    if t == "bill_payment":
        return _bill_payment(s, txn)
    if t == "deposit":
        return _deposit(s, txn)
    if t == "transfer":
        return _transfer(s, txn)
    if t == "cc_payment":
        return _cc_payment(s, txn)
    if t == "journal_entry":
        return _journal(s, txn)
    if t == "sales_tax_payment":
        return _sales_tax_payment(s, txn)
    if t == "sales_tax_adjustment":
        return _sales_tax_adjustment(s, txn)
    if t == "inventory_adjustment":
        return []  # posted by the inventory engine
    raise ValueError(f"no posting rule for {t}")


def post(s: Session, txn: Transaction) -> list[LedgerEntry]:
    """Replace the transaction's document entries with freshly built ones."""
    s.flush()
    old = s.scalars(select(LedgerEntry).where(LedgerEntry.txn_id == txn.id,
                                              LedgerEntry.auto.is_(None))).all()
    carried: dict[tuple, tuple[str, Optional[int]]] = {}
    counts: dict[tuple, int] = {}
    for e in sorted(old, key=lambda e: e.position):
        base = (e.account_id, e.line_id)
        n = counts.get(base, 0)
        counts[base] = n + 1
        if e.cleared:
            carried[base + (n,)] = (e.cleared, e.reconciliation_id)
    s.execute(delete(LedgerEntry).where(LedgerEntry.txn_id == txn.id, LedgerEntry.auto.is_(None)))
    s.expire(txn, ["entries"])

    specs = build_entries(s, txn)
    total = sum(e.amount for e in specs)
    if total != 0:
        raise ValidationError(
            f"This {txn.info.label.lower()} doesn't balance (off by {total / 100:.2f}).", "lines")

    created: list[LedgerEntry] = []
    counts = {}
    for pos, spec in enumerate(specs):
        if spec.amount == 0:
            continue
        line_id = spec.line.id if spec.line is not None else None
        base = (spec.account_id, line_id)
        n = counts.get(base, 0)
        counts[base] = n + 1
        cleared, rec_id = carried.get(base + (n,), ("", None))
        le = LedgerEntry(
            txn_id=txn.id, line_id=line_id, position=pos, date=txn.date, account_id=spec.account_id,
            amount_cents=spec.amount, customer_id=spec.customer_id, vendor_id=spec.vendor_id,
            employee_id=spec.employee_id, item_id=spec.item_id, class_id=spec.class_id,
            location_id=spec.location_id, tax_rate_id=spec.tax_rate_id, tax_agency_id=spec.tax_agency_id,
            qty=spec.qty, memo=spec.memo, cleared=cleared, reconciliation_id=rec_id,
        )
        s.add(le)
        created.append(le)
    s.flush()
    return created


def unpost(s: Session, txn: Transaction) -> None:
    s.execute(delete(LedgerEntry).where(LedgerEntry.txn_id == txn.id))
    s.expire(txn, ["entries"])


def check_account_types(s: Session, txn: Transaction) -> None:
    """Header accounts must be of the kinds the transaction type allows."""
    info = txn.info
    if info.header_account and txn.account_id and info.header_account_types:
        acct = s.get(Account, txn.account_id)
        if acct is None:
            raise ValidationError("Account not found.", "account_id")
        if acct.type not in info.header_account_types:
            raise ValidationError(f"{acct.full_name} can't be used as the {info.header_account.lower()}.",
                                  "account_id")
