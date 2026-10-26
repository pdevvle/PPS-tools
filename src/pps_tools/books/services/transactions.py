"""Saving, voiding and deleting transactions.

Every way a transaction comes into being — a form, the API, a recurring
template, a bank-feed match, a Stripe webhook, an import — goes through
:func:`save`, which takes a plain dict (strings are fine; amounts in
dollars) and does the rest: defaults, line math, discounts and tax,
applying payments and credits, posting to the ledger, inventory costing,
open balances, closing-date checks and the audit trail.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from pps_tools.books import money
from pps_tools.books.db import atomic, utcnow
from pps_tools.books.models import (Account, BankFeedItem, Customer, CustomFieldValue, Employee,
                                    Item, Tag, TaxAgency, TaxRate, Terms, TimeActivity, Transaction,
                                    TransactionLine, TransactionLink, TransactionTaxLine, User, Vendor)
from pps_tools.books.money import cents, to_decimal
from pps_tools.books.services import audit, closing, numbering, posting, prefs
from pps_tools.books.services import tax as tax_service
from pps_tools.books.services.accounts import system_account_id
from pps_tools.books.services.dates import due_date as terms_due_date
from pps_tools.books.services.dates import parse_date
from pps_tools.books.services.errors import ValidationError
from pps_tools.books.txn_types import SETTLE_LINKS, TXN_TYPES, TxnType

SALES_LIKE = ("estimate", "invoice", "sales_receipt", "credit_memo", "refund_receipt",
              "delayed_charge", "delayed_credit")
PURCHASE_LIKE = ("purchase_order", "bill", "vendor_credit", "expense", "check", "cc_credit")

_HEADER_TEXT = ["ref_no", "billing_address", "shipping_address", "ship_via", "tracking_no", "memo",
                "message", "statement_memo", "email_to", "email_cc", "email_bcc", "tax_exempt_reason",
                "accepted_by", "currency"]
_HEADER_IDS = ["terms_id", "payment_method_id", "class_id", "location_id", "account_id", "to_account_id",
               "ar_ap_account_id", "tax_rate_id", "tax_agency_id"]
_HEADER_DATES = ["ship_date", "expiration_date"]
_HEADER_BOOLS = ["discount_before_tax", "print_later", "allow_online_card", "allow_online_ach",
                 "needs_review"]
_INTERNAL = ["stripe_checkout_session_id", "stripe_payment_intent_id", "stripe_charge_id",
             "stripe_object_id", "stripe_fee_cents", "recurring_template_id"]


# -- small parsers -------------------------------------------------------------


def _id(value: Any) -> Optional[int]:
    if value in (None, "", "None", "null", 0, "0"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"Invalid id: {value!r}")


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "on", "yes", "y")


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dec(value: Any) -> Optional[Decimal]:
    try:
        return to_decimal(value, None)
    except money.MoneyError as exc:
        raise ValidationError(str(exc))


def _amount(d: dict, key: str = "amount") -> Optional[int]:
    """Cents from ``key_cents`` (int) or ``key`` (dollars)."""
    if d.get(f"{key}_cents") not in (None, ""):
        return int(d[f"{key}_cents"])
    if d.get(key) in (None, ""):
        return None
    try:
        return cents(d[key])
    except money.MoneyError as exc:
        raise ValidationError(str(exc), key)


def new_token() -> str:
    return secrets.token_urlsafe(24)


def ensure_token(txn: Transaction) -> str:
    if not txn.public_token:
        txn.public_token = new_token()
    return txn.public_token


def parse_payee(value: Any) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """'vendor:3' / 'customer:5' / 'employee:2' -> (customer_id, vendor_id, employee_id)."""
    text = _text(value)
    if not text:
        return None, None, None
    kind, _, raw = text.partition(":")
    pid = _id(raw)
    if kind in ("c", "customer"):
        return pid, None, None
    if kind in ("v", "vendor"):
        return None, pid, None
    if kind in ("e", "employee"):
        return None, None, pid
    raise ValidationError(f"Unknown payee {value!r}")


def payee_key(txn_or_line) -> str:
    if getattr(txn_or_line, "vendor_id", None):
        return f"vendor:{txn_or_line.vendor_id}"
    if getattr(txn_or_line, "customer_id", None):
        return f"customer:{txn_or_line.customer_id}"
    if getattr(txn_or_line, "employee_id", None):
        return f"employee:{txn_or_line.employee_id}"
    return ""


# -- save ----------------------------------------------------------------------


@atomic
def save(s: Session, data: dict, txn: Optional[Transaction] = None, user: Optional[User] = None,
         closing_password: Optional[str] = None, source: Optional[str] = None) -> Transaction:
    is_new = txn is None
    ttype = data.get("type") or (txn.type if txn else None)
    if ttype not in TXN_TYPES:
        raise ValidationError(f"Unknown transaction type {ttype!r}")
    info = TXN_TYPES[ttype]

    before = None
    old_date = None
    old_items: set[int] = set()
    old_related: set[int] = set()
    if is_new:
        txn = Transaction(type=ttype, source=source or data.get("source") or "manual",
                          created_by_id=user.id if user else None)
        s.add(txn)
    else:
        if txn.type != ttype:
            raise ValidationError("A transaction's type can't be changed.")
        if txn.voided:
            raise ValidationError("A voided transaction can't be edited.")
        before = audit.snapshot(txn)
        old_date = txn.date
        old_items = inventory_item_ids(s, txn)
        old_related = related_ids(s, txn)
        txn.updated_by_id = user.id if user else None

    _apply_header(s, txn, data, info, is_new)
    closing.guard(s, [old_date, txn.date], user, closing_password)
    if "lines" in data:
        _apply_lines(s, txn, data["lines"], info)
    _compute_totals(s, txn, data, info)
    _validate(s, txn, data, info)
    s.flush()

    _apply_links(s, txn, data, info, is_new)
    if "custom_fields" in data:
        _apply_custom_fields(s, txn, data["custom_fields"])
    if "tag_ids" in data:
        ids = [_id(t) for t in (data.get("tag_ids") or []) if _id(t)]
        txn.tags = list(s.scalars(select(Tag).where(Tag.id.in_(ids)))) if ids else []

    posting.post(s, txn)
    _sync_billed_sources(s, txn)
    _sync_po_receipts(s, txn)

    from pps_tools.books.services import inventory  # local: inventory imports this module

    inventory.recompute_items(s, old_items | inventory_item_ids(s, txn))
    refresh_balances(s, {txn.id} | old_related | related_ids(s, txn))
    if info.open_item and txn.balance_cents < 0:
        applied = txn.total_cents - txn.balance_cents
        raise ValidationError(
            f"{money.fmt(applied)} is already applied to this {info.label.lower()}; "
            f"its total can't be less than that.", "lines")
    _sync_workflow_statuses(s, txn, old_related)

    if info.number_seq and txn.number:
        numbering.note_used(s, info.number_seq, txn.number)

    audit.record(s, user, "create" if is_new else "update", "transaction", txn.id,
                 before=before, after=audit.snapshot(txn), txn=txn)
    s.flush()
    return txn


def _apply_header(s: Session, txn: Transaction, data: dict, info: TxnType, is_new: bool) -> None:
    if "date" in data or is_new:
        try:
            txn.date = parse_date(data.get("date"), date.today())
        except ValueError as exc:
            raise ValidationError(str(exc), "date")

    # who
    if info.entity == "customer":
        if "customer_id" in data:
            txn.customer_id = _id(data["customer_id"])
    elif info.entity == "vendor":
        if "vendor_id" in data:
            txn.vendor_id = _id(data["vendor_id"])
    elif info.entity == "payee":
        if "payee" in data:
            txn.customer_id, txn.vendor_id, txn.employee_id = parse_payee(data["payee"])
        else:
            for f in ("customer_id", "vendor_id", "employee_id"):
                if f in data:
                    setattr(txn, f, _id(data[f]))
    elif info.entity == "agency":
        if "tax_agency_id" in data:
            txn.tax_agency_id = _id(data["tax_agency_id"])

    for f in _HEADER_TEXT:
        if f in data:
            setattr(txn, f, _text(data[f]))
    for f in _HEADER_IDS:
        if f in data:
            setattr(txn, f, _id(data[f]))
    for f in _HEADER_DATES:
        if f in data:
            try:
                setattr(txn, f, parse_date(data[f]))
            except ValueError as exc:
                raise ValidationError(str(exc), f)
    for f in _HEADER_BOOLS:
        if f in data:
            setattr(txn, f, _bool(data[f]))
    for f in _INTERNAL:
        if f in data:
            setattr(txn, f, data[f])
    if "status" in data and info.statuses:
        status = _text(data["status"])
        if status and status not in info.statuses:
            raise ValidationError(f"Unknown status {status!r}")
        txn.status = status
    if "discount_type" in data:
        txn.discount_type = _text(data["discount_type"])
    if "discount_value" in data:
        txn.discount_value = _dec(data["discount_value"])
    if "exchange_rate" in data:
        txn.exchange_rate = _dec(data["exchange_rate"])

    customer = s.get(Customer, txn.customer_id) if txn.customer_id else None
    vendor = s.get(Vendor, txn.vendor_id) if txn.vendor_id else None

    if is_new:
        if info.statuses and not txn.status:
            txn.status = info.statuses[0]
        if customer is not None and txn.type in SALES_LIKE + ("payment",):
            if not txn.billing_address and "billing_address" not in data:
                txn.billing_address = _customer_bill_to(customer)
            if not txn.shipping_address and "shipping_address" not in data and txn.type in SALES_LIKE:
                ship = customer.shipping_address()
                txn.shipping_address = ship or None
            if not txn.email_to and "email_to" not in data:
                txn.email_to = customer.email
            if "payment_method_id" not in data and customer.payment_method_id and txn.type in (
                    "sales_receipt", "payment"):
                txn.payment_method_id = customer.payment_method_id
            if txn.type in ("estimate", "invoice", "sales_receipt", "credit_memo", "refund_receipt") \
                    and "tax_rate_id" not in data and customer.default_tax_rate_id:
                txn.tax_rate_id = customer.default_tax_rate_id
        if vendor is not None and txn.type == "purchase_order" and not txn.email_to and "email_to" not in data:
            txn.email_to = vendor.email
        if txn.type in ("invoice", "estimate", "sales_receipt") and "message" not in data:
            key = "default_estimate_message" if txn.type == "estimate" else "default_invoice_message"
            txn.message = prefs.get(s, key) or None
        if txn.type in ("invoice", "estimate", "sales_receipt", "credit_memo") and "discount_before_tax" not in data:
            txn.discount_before_tax = bool(prefs.get(s, "discount_before_tax"))
        if info.default_header_account and not txn.account_id and "account_id" not in data:
            key = info.default_header_account
            if key == "undeposited_funds" and not prefs.get(s, "deposit_to_undeposited_funds"):
                pass
            else:
                txn.account_id = system_account_id(s, key)
        if txn.type == "invoice" and "allow_online_card" not in data:
            txn.allow_online_card = bool(prefs.get(s, "stripe_card"))
            txn.allow_online_ach = bool(prefs.get(s, "stripe_ach"))

    # terms and due date
    if info.has_terms:
        if is_new and not txn.terms_id and "terms_id" not in data:
            if txn.type == "invoice":
                txn.terms_id = (customer.terms_id if customer else None) or _id(prefs.get(s, "default_terms_id"))
            else:
                txn.terms_id = (vendor.terms_id if vendor else None) or _id(prefs.get(s, "default_bill_terms_id"))
        if data.get("due_date"):
            try:
                txn.due_date = parse_date(data["due_date"])
            except ValueError as exc:
                raise ValidationError(str(exc), "due_date")
        elif is_new or "terms_id" in data or "date" in data or not txn.due_date:
            terms = s.get(Terms, txn.terms_id) if txn.terms_id else None
            txn.due_date = terms_due_date(terms, txn.date)
    elif "due_date" in data:
        txn.due_date = parse_date(data.get("due_date"))

    # numbers
    if "number" in data:
        txn.number = _text(data["number"])
    if not txn.number:
        if info.number_seq and (is_new or "number" in data):
            txn.number = numbering.take(s, info.number_seq)
        elif txn.type == "check" and txn.account_id and not txn.print_later:
            acct = s.get(Account, txn.account_id)
            if acct is not None and acct.type == "bank":
                txn.number = numbering.take_check_number(s, acct)
    elif txn.type in ("check", "bill_payment") and txn.account_id:
        acct = s.get(Account, txn.account_id)
        if acct is not None and acct.type == "bank":
            numbering.note_check_number(acct, txn.number)


def _customer_bill_to(customer: Customer) -> str:
    lines = [customer.company_name or customer.display_name]
    contact = customer.contact_name
    if contact and contact != lines[0]:
        lines.append(contact)
    addr = customer.billing_address()
    if addr:
        lines.append(addr)
    return "\n".join(lines)


def _blank_line(ld: dict) -> bool:
    keys = ("item_id", "account_id", "description", "amount", "amount_cents", "debit", "credit", "qty", "rate")
    return all(ld.get(k) in (None, "") for k in keys) and not ld.get("kind") in ("subtotal",)


def _apply_lines(s: Session, txn: Transaction, rows: list[dict], info: TxnType) -> None:
    existing = {ln.id: ln for ln in txn.lines}
    is_sale = txn.type in SALES_LIKE
    result: list[TransactionLine] = []
    position = 0
    for ld in rows or []:
        if _blank_line(ld):
            continue
        lid = _id(ld.get("id"))
        line = existing.pop(lid, None) if lid else None
        if line is None:
            line = TransactionLine()
        item_id = _id(ld.get("item_id"))
        item = s.get(Item, item_id) if item_id else None
        if item_id and item is None:
            raise ValidationError(f"Product/service {item_id} not found.", "lines")

        if item is not None and item.type == "bundle":
            result.append(_fill_simple_line(line, position, kind="description", description=item.name))
            position += 1
            bundle_qty = _dec(ld.get("qty")) or Decimal(1)
            for comp in item.components:
                cl = TransactionLine()
                _fill_line(s, txn, cl, {"item_id": comp.item_id, "qty": comp.qty * bundle_qty,
                                        "class_id": ld.get("class_id"), "taxable": None}, position,
                           is_sale, info)
                result.append(cl)
                position += 1
            continue

        _fill_line(s, txn, line, ld, position, is_sale, info, item=item)
        result.append(line)
        position += 1
    txn.lines = result


def _fill_simple_line(line: TransactionLine, position: int, kind: str, description: str) -> TransactionLine:
    line.position = position
    line.kind = kind
    line.description = description
    line.item_id = None
    line.account_id = None
    line.amount_cents = 0
    line.qty = None
    line.rate = None
    return line


def _fill_line(s: Session, txn: Transaction, line: TransactionLine, ld: dict, position: int,
               is_sale: bool, info: TxnType, item: Optional[Item] = None) -> None:
    line.position = position
    item_id = _id(ld.get("item_id"))
    if item is None and item_id:
        item = s.get(Item, item_id)
    account_id = _id(ld.get("account_id"))
    kind = _text(ld.get("kind"))
    if not kind:
        kind = "item" if item_id else ("account" if account_id or txn.type in ("journal_entry", "deposit")
                                       else "description")
    if txn.type in ("journal_entry", "deposit"):
        kind = "account" if kind != "description" else kind
    line.kind = kind
    line.item_id = item_id if kind == "item" else None
    line.account_id = account_id
    is_new_line = line.id is None

    desc = ld.get("description")
    if desc is None and is_new_line and item is not None:
        desc = item.description if is_sale else (item.purchase_description or item.description)
    line.description = _text(desc)
    line.service_date = parse_date(ld.get("service_date")) if ld.get("service_date") else None
    line.class_id = _id(ld.get("class_id"))
    line.location_id = _id(ld.get("location_id"))

    # Name on journal/deposit lines, or billable customer on expense lines.
    if "name" in ld or "payee" in ld:
        line.customer_id, line.vendor_id, line.employee_id = parse_payee(ld.get("name") or ld.get("payee"))
    else:
        line.customer_id = _id(ld.get("customer_id"))
        line.vendor_id = _id(ld.get("vendor_id"))
        line.employee_id = _id(ld.get("employee_id"))
    line.billable = _bool(ld.get("billable", False)) and bool(line.customer_id)
    line.markup_pct = _dec(ld.get("markup_pct"))
    line.payment_method_id = _id(ld.get("payment_method_id"))
    line.ref_no = _text(ld.get("ref_no"))
    if "source_type" in ld:
        line.source_type = _text(ld.get("source_type"))
        line.source_id = _id(ld.get("source_id"))

    if kind in ("description", "subtotal"):
        line.qty = None
        line.rate = None
        line.amount_cents = 0
        line.posting_type = None
        line.taxable = False
        return

    if txn.type == "journal_entry":
        debit = _amount(ld, "debit")
        credit = _amount(ld, "credit")
        if debit and credit:
            raise ValidationError("A journal line can have a debit or a credit, not both.", "lines")
        if debit is None and credit is None and ld.get("posting_type"):
            line.posting_type = ld["posting_type"]
            line.amount_cents = _amount(ld) or 0
        elif credit:
            line.posting_type = "credit"
            line.amount_cents = credit
        else:
            line.posting_type = "debit"
            line.amount_cents = debit or 0
        if line.amount_cents < 0:
            line.amount_cents = -line.amount_cents
            line.posting_type = "credit" if line.posting_type == "debit" else "debit"
        line.qty = None
        line.rate = None
        return

    if txn.type == "inventory_adjustment":
        if item is None or item.type != "inventory":
            raise ValidationError("Inventory adjustments need inventory products.", "lines")
        new_qty = _dec(ld.get("new_qty"))
        change = _dec(ld.get("qty"))
        if change is None and new_qty is not None:
            change = new_qty - (item.qty_on_hand or Decimal(0))
        line.qty = change or Decimal(0)
        line.new_qty = new_qty
        line.rate = None
        line.amount_cents = 0
        return

    qty = _dec(ld.get("qty"))
    rate = _dec(ld.get("rate"))
    amount = _amount(ld)
    if kind == "item":
        if rate is None and amount is None and item is not None and is_new_line:
            rate = item.sales_price if is_sale else item.cost
        if qty is None and (rate is not None or item is not None) and amount is None:
            qty = Decimal(1)
        if rate is not None and qty is not None:
            amount = money.line_amount(qty, rate)
        elif amount is not None and qty:
            rate = (Decimal(amount) / Decimal(100) / qty).quantize(Decimal("0.00001"))
    line.qty = qty if kind == "item" else None
    line.rate = rate if kind == "item" else None
    line.amount_cents = amount or 0
    line.posting_type = None

    taxable = ld.get("taxable")
    if taxable is None or taxable == "":
        line.taxable = bool(item.taxable) if (item is not None and is_sale) else (
            line.taxable if not is_new_line else False)
        if is_new_line and item is not None and is_sale:
            line.taxable = bool(item.taxable)
    else:
        line.taxable = _bool(taxable)
    if not is_sale:
        line.taxable = False


def _compute_totals(s: Session, txn: Transaction, data: dict, info: TxnType) -> None:
    t = txn.type
    if info.has_amount:
        amt = _amount(data)
        if amt is not None:
            txn.total_cents = amt
        elif txn.total_cents is None:
            txn.total_cents = 0
        txn.subtotal_cents = txn.total_cents
        return
    if t == "journal_entry":
        debits = sum(ln.amount_cents for ln in txn.lines if ln.posting_type == "debit")
        txn.subtotal_cents = txn.total_cents = debits
        return
    if t == "inventory_adjustment":
        txn.subtotal_cents = txn.total_cents = 0
        return
    if t == "deposit":
        return  # computed once the deposited payments are linked

    amount_lines = [ln for ln in txn.lines if ln.kind in ("item", "account")]
    subtotal = sum(ln.amount_cents for ln in amount_lines)
    txn.subtotal_cents = subtotal

    if not info.has_tax:
        txn.discount_cents = 0
        txn.tax_cents = 0
        txn.taxable_subtotal_cents = 0
        txn.tax_lines = []
        txn.shipping_cents = 0
        txn.total_cents = subtotal
        return

    # discount
    discount = 0
    if txn.discount_type == "percent" and txn.discount_value:
        discount = money.round_cents(Decimal(subtotal) * txn.discount_value / Decimal(10000))
    elif txn.discount_type == "amount" and txn.discount_value:
        discount = money.round_cents(txn.discount_value)
    if subtotal >= 0:
        discount = max(0, min(discount, subtotal))
    txn.discount_cents = discount

    if "shipping" in data or "shipping_cents" in data:
        txn.shipping_cents = _amount(data, "shipping") or 0

    customer = s.get(Customer, txn.customer_id) if txn.customer_id else None
    exempt = customer is not None and not customer.taxable
    taxable_lines = sum(ln.amount_cents for ln in amount_lines if ln.taxable)
    if discount and txn.discount_before_tax and subtotal:
        taxable_share = money.allocate(discount, [taxable_lines, subtotal - taxable_lines]) \
            if subtotal - taxable_lines >= 0 and taxable_lines >= 0 else [0, 0]
        taxable_base = taxable_lines - taxable_share[0]
    else:
        taxable_base = taxable_lines
    if txn.shipping_cents and prefs.get(s, "shipping_taxable"):
        taxable_base += txn.shipping_cents
    rate = s.get(TaxRate, txn.tax_rate_id) if txn.tax_rate_id else None
    if exempt:
        taxable_base = 0
        if not txn.tax_exempt_reason:
            txn.tax_exempt_reason = customer.tax_exemption_reason or "Tax exempt"
    override = None
    if data.get("tax_amount") not in (None, "") and _bool(data.get("tax_override", True)):
        override = cents(data["tax_amount"])
    elif "tax_override" not in data and "tax_amount" not in data and txn.tax_override:
        override = txn.tax_cents  # a manual tax amount survives edits that don't mention tax
    txn.tax_override = override is not None
    parts = tax_service.compute(rate, taxable_base, override) if (rate and not exempt) else []
    txn.tax_lines = [TransactionTaxLine(tax_rate_id=p.rate.id, agency_id=p.rate.agency_id,
                                        taxable_cents=p.taxable_cents, amount_cents=p.amount_cents)
                     for p in parts]
    for tl, p in zip(txn.tax_lines, parts):
        tl.tax_rate = p.rate
    txn.taxable_subtotal_cents = taxable_base
    txn.tax_cents = sum(p.amount_cents for p in parts)
    txn.total_cents = subtotal - discount + txn.tax_cents + (txn.shipping_cents or 0)


def _validate(s: Session, txn: Transaction, data: dict, info: TxnType) -> None:
    t = txn.type
    if info.entity == "customer" and not txn.customer_id:
        raise ValidationError("Choose a customer.", "customer_id")
    if info.entity == "vendor" and not txn.vendor_id and t != "cc_payment":
        raise ValidationError("Choose a vendor.", "vendor_id")
    if info.entity == "agency" and not txn.tax_agency_id:
        raise ValidationError("Choose a tax agency.", "tax_agency_id")
    if txn.customer_id and s.get(Customer, txn.customer_id) is None:
        raise ValidationError("Customer not found.", "customer_id")
    if txn.vendor_id and s.get(Vendor, txn.vendor_id) is None:
        raise ValidationError("Vendor not found.", "vendor_id")
    if txn.employee_id and s.get(Employee, txn.employee_id) is None:
        raise ValidationError("Employee not found.", "employee_id")
    if txn.tax_agency_id and s.get(TaxAgency, txn.tax_agency_id) is None:
        raise ValidationError("Tax agency not found.", "tax_agency_id")
    posting.check_account_types(s, txn)
    if info.header_account and info.posts and not txn.account_id and t not in ("deposit",):
        raise ValidationError(f"Choose the {info.header_account.lower()}.", "account_id")
    if t == "deposit" and not txn.account_id:
        raise ValidationError("Choose the account to deposit to.", "account_id")
    if t in ("transfer", "cc_payment") and not txn.to_account_id:
        raise ValidationError("Choose the account to transfer to." if t == "transfer"
                              else "Choose the credit card account.", "to_account_id")
    if t == "cc_payment":
        card = s.get(Account, txn.to_account_id)
        if card is None or card.type != "credit_card":
            raise ValidationError("Choose a credit card account.", "to_account_id")
    if t == "transfer" and txn.account_id == txn.to_account_id:
        raise ValidationError("Transfer from and to the same account.", "to_account_id")
    if info.has_amount and txn.total_cents < 0:
        raise ValidationError("The amount can't be negative.", "amount")
    if info.has_amount and txn.total_cents == 0 and t not in ("payment", "bill_payment"):
        raise ValidationError("Enter an amount.", "amount")
    if t == "journal_entry":
        debits = sum(ln.amount_cents for ln in txn.lines if ln.posting_type == "debit")
        credits = sum(ln.amount_cents for ln in txn.lines if ln.posting_type == "credit")
        if debits != credits:
            raise ValidationError(
                f"Debits ({money.fmt(debits)}) and credits ({money.fmt(credits)}) must be equal.", "lines")
        if not any(ln.amount_cents for ln in txn.lines):
            raise ValidationError("A journal entry needs at least two lines.", "lines")
        for ln in txn.lines:
            if ln.kind != "account":
                continue
            if not ln.account_id:
                raise ValidationError("Every journal line needs an account.", "lines")
            acct = s.get(Account, ln.account_id)
            if acct is None:
                raise ValidationError("Account not found.", "lines")
            if acct.type == "ar" and not ln.customer_id:
                raise ValidationError("Journal lines to Accounts Receivable need a customer.", "lines")
            if acct.type == "ap" and not ln.vendor_id:
                raise ValidationError("Journal lines to Accounts Payable need a vendor.", "lines")
    if txn.type in PURCHASE_LIKE or t == "deposit":
        for ln in txn.lines:
            if ln.kind == "account" and ln.account_id:
                acct = s.get(Account, ln.account_id)
                if acct is None:
                    raise ValidationError("Account not found.", "lines")
                if acct.type in ("ar", "ap") and t != "deposit":
                    raise ValidationError(
                        f"Use a payment or bill payment instead of categorizing to {acct.name}.", "lines")
    if info.item_lines and t not in ("inventory_adjustment",) and not info.account_lines:
        for ln in txn.lines:
            if ln.kind == "account" and not ln.account_id:
                raise ValidationError("Choose a product or service for each line.", "lines")
    if t in ("invoice", "sales_receipt", "credit_memo", "refund_receipt", "estimate", "bill", "expense",
             "check", "vendor_credit", "cc_credit", "purchase_order", "delayed_charge", "delayed_credit"):
        if not any(ln.kind in ("item", "account") for ln in txn.lines):
            raise ValidationError("Add at least one line.", "lines")
    if t in ("bill", "expense", "check", "vendor_credit", "cc_credit") and txn.total_cents < 0:
        raise ValidationError(f"A {info.label.lower()} can't total less than zero.", "lines")
    if t in ("invoice", "sales_receipt") and txn.total_cents < 0:
        raise ValidationError(f"An {info.label.lower()} can't total less than zero; use a credit memo.", "lines")
    if t == "inventory_adjustment":
        if not txn.lines:
            raise ValidationError("Add at least one product to adjust.", "lines")
    if t == "check" and txn.number and prefs.get(s, "warn_duplicate_check_numbers") and not data.get("allow_duplicate"):
        dup = s.scalar(select(Transaction.id).where(
            Transaction.type.in_(("check", "bill_payment")), Transaction.number == txn.number,
            Transaction.account_id == txn.account_id, Transaction.id != (txn.id or 0),
            Transaction.voided.is_(False)).limit(1))
        if dup:
            raise ValidationError(f"Check number {txn.number} is already used for this account.", "number")
    if t == "bill" and txn.number and prefs.get(s, "warn_duplicate_bill_numbers") and not data.get("allow_duplicate"):
        dup = s.scalar(select(Transaction.id).where(
            Transaction.type == "bill", Transaction.number == txn.number, Transaction.vendor_id == txn.vendor_id,
            Transaction.id != (txn.id or 0), Transaction.voided.is_(False)).limit(1))
        if dup:
            raise ValidationError(f"Bill number {txn.number} was already entered for this vendor.", "number")


# -- links ---------------------------------------------------------------------

_OWNED_LINKS = {
    "payment": ("payment",),
    "credit_memo": ("credit",),
    "customer_refund": ("refund",),
    "bill_payment": ("bill_payment",),
    "vendor_credit": ("vendor_credit",),
    "deposit": ("deposit",),
    "invoice": ("estimate", "delayed"),
    "bill": ("po",),
}


def _open_balance_excluding(s: Session, target: Transaction, exclude_txn_id: int) -> int:
    settled_out = s.scalar(select(func.coalesce(func.sum(TransactionLink.amount_cents), 0)).where(
        TransactionLink.from_txn_id == target.id, TransactionLink.link_type.in_(SETTLE_LINKS),
        TransactionLink.to_txn_id != exclude_txn_id,
        or_(TransactionLink.via_txn_id.is_(None), TransactionLink.via_txn_id != exclude_txn_id)))
    settled_in = s.scalar(select(func.coalesce(func.sum(TransactionLink.amount_cents), 0)).where(
        TransactionLink.to_txn_id == target.id, TransactionLink.link_type.in_(SETTLE_LINKS),
        TransactionLink.from_txn_id != exclude_txn_id,
        or_(TransactionLink.via_txn_id.is_(None), TransactionLink.via_txn_id != exclude_txn_id)))
    return target.total_cents - int(settled_out or 0) - int(settled_in or 0)


def _apply_links(s: Session, txn: Transaction, data: dict, info: TxnType, is_new: bool) -> None:
    """Rebuild the links this transaction owns, for whichever parts the payload mentions.

    A link is owned by the transaction whose screen made it: a payment owns
    its applications (``via_txn_id`` empty) and the credits it applied
    (``via_txn_id`` = the payment). Editing a credit memo therefore never
    drops a credit that some payment screen applied.
    """
    t = txn.type
    owned = _OWNED_LINKS.get(t, ())
    manage_apps = "applications" in data or (is_new and t in ("payment", "bill_payment", "credit_memo",
                                                               "vendor_credit", "customer_refund"))
    manage_credits = "credits" in data
    manage_deposits = t == "deposit" and ("deposits" in data or is_new)
    manage_sources = (t == "invoice" and ("source_estimate_id" in data or "lines" in data or is_new)) or \
        (t == "bill" and ("source_po_id" in data or is_new))

    for link in list(txn.links_out):
        if link.via_txn_id is not None or link.link_type not in owned:
            continue
        if link.link_type in ("payment", "credit", "refund", "bill_payment", "vendor_credit") and manage_apps:
            s.delete(link)
        elif link.link_type == "deposit" and manage_deposits:
            s.delete(link)
        elif link.link_type in ("estimate", "delayed", "po") and manage_sources:
            s.delete(link)
    if manage_credits:
        for link in s.scalars(select(TransactionLink).where(TransactionLink.via_txn_id == txn.id)).all():
            s.delete(link)
    s.flush()
    s.expire(txn, ["links_out", "links_in"])

    def add_link(from_id: int, to_id: int, ltype: str, amount: int, via: Optional[int] = None) -> None:
        s.add(TransactionLink(from_txn_id=from_id, to_txn_id=to_id, link_type=ltype, amount_cents=amount,
                              via_txn_id=via))

    if t in ("payment", "bill_payment", "credit_memo", "vendor_credit", "customer_refund"):
        party_field = "customer_id" if info.open_item == "ar" else "vendor_id"
        if manage_apps:
            apps = data.get("applications")
            if apps is None and t in ("payment", "bill_payment") and prefs.get(s, "auto_apply_payments") \
                    and txn.total_cents > 0 and not data.get("credits"):
                apps = _auto_apply(s, txn, info.applies_to, party_field, txn.total_cents)
            applied_total = 0
            for app in apps or []:
                amt = _amount(app)
                target_id = _id(app.get("txn_id"))
                if not target_id or not amt:
                    continue
                target = s.get(Transaction, target_id)
                if target is None or target.type not in info.applies_to or target.voided:
                    raise ValidationError("Can't apply to that transaction.", "applications")
                if getattr(target, party_field) != getattr(txn, party_field):
                    raise ValidationError("That transaction belongs to someone else.", "applications")
                if amt < 0:
                    raise ValidationError("Applied amounts can't be negative.", "applications")
                open_bal = _open_balance_excluding(s, target, txn.id)
                if amt > open_bal:
                    num = f" {target.number}" if target.number else ""
                    raise ValidationError(f"{target.info.label}{num} only has {money.fmt(open_bal)} open.",
                                          "applications")
                add_link(txn.id, target.id, info.link_type, amt)
                applied_total += amt
                s.flush()
            # What this credit already settled elsewhere (applied in another screen, refunded).
            used_elsewhere = int(s.scalar(select(func.coalesce(func.sum(TransactionLink.amount_cents), 0)).where(
                TransactionLink.from_txn_id == txn.id, TransactionLink.link_type.in_(SETTLE_LINKS),
                TransactionLink.via_txn_id.isnot(None))) or 0) + int(s.scalar(
                select(func.coalesce(func.sum(TransactionLink.amount_cents), 0)).where(
                    TransactionLink.to_txn_id == txn.id, TransactionLink.link_type == "refund")) or 0)
            if applied_total + used_elsewhere > txn.total_cents:
                if t in ("credit_memo", "vendor_credit"):
                    raise ValidationError(
                        f"You can apply at most {money.fmt(txn.total_cents - used_elsewhere)} of this credit.",
                        "applications")
                if t == "customer_refund":
                    raise ValidationError("The refund is less than the credits applied.", "applications")
                raise ValidationError(
                    f"Applied amounts ({money.fmt(applied_total)}) are more than the "
                    f"{'payment' if t == 'payment' else 'amount paid'} ({money.fmt(txn.total_cents)}).",
                    "applications")
            if t == "customer_refund" and applied_total != txn.total_cents:
                raise ValidationError("Apply the whole refund to the customer's credits.", "applications")

        # Credits used inside a Receive Payment / Pay Bills screen.
        for cr in (data.get("credits") or []) if manage_credits else []:
            amt = _amount(cr)
            credit_id = _id(cr.get("txn_id"))
            target_id = _id(cr.get("invoice_id") or cr.get("bill_id") or cr.get("target_id"))
            if not amt or not credit_id or not target_id:
                continue
            credit = s.get(Transaction, credit_id)
            target = s.get(Transaction, target_id)
            if credit is None or target is None or credit.voided or target.voided:
                raise ValidationError("Credit not found.", "credits")
            if getattr(credit, party_field) != getattr(txn, party_field) or \
                    getattr(target, party_field) != getattr(txn, party_field):
                raise ValidationError("That credit belongs to someone else.", "credits")
            if credit.info.open_sign != -1 or target.info.open_sign != 1 or credit.id == txn.id:
                raise ValidationError("Only credits can be applied to open items.", "credits")
            if amt > _open_balance_excluding(s, credit, txn.id):
                raise ValidationError("The credit applied is more than what's available.", "credits")
            if amt > _open_balance_excluding(s, target, txn.id):
                raise ValidationError("Too much applied to one transaction.", "credits")
            link_type = "credit" if info.open_item == "ar" else "vendor_credit"
            add_link(credit.id, target.id, link_type, amt, via=txn.id)
            s.flush()

    elif t == "invoice" and manage_sources:
        est_id = _id(data.get("source_estimate_id"))
        if est_id:
            est = s.get(Transaction, est_id)
            if est is None or est.type != "estimate" or est.customer_id != txn.customer_id:
                raise ValidationError("Estimate not found for this customer.", "source_estimate_id")
            add_link(txn.id, est.id, "estimate", txn.total_cents)
        delayed = {ln.source_id for ln in txn.lines if ln.source_type == "delayed_line" and ln.source_id}
        if delayed:
            parents = set(s.scalars(select(TransactionLine.txn_id).where(TransactionLine.id.in_(delayed))))
            for parent_id in parents:
                add_link(txn.id, parent_id, "delayed", 0)
        if is_new and prefs.get(s, "auto_apply_credits") and txn.total_cents > 0 and data.get("apply_credits", True):
            s.flush()
            remaining = txn.total_cents
            credits = s.scalars(select(Transaction).where(
                Transaction.customer_id == txn.customer_id, Transaction.type.in_(("credit_memo", "payment")),
                Transaction.balance_cents > 0, Transaction.voided.is_(False))
                .order_by(Transaction.date, Transaction.id)).all()
            for cr in credits:
                if remaining <= 0:
                    break
                use = min(_open_balance_excluding(s, cr, txn.id), remaining)
                if use > 0:
                    # via = the invoice, so editing the credit memo keeps this application.
                    add_link(cr.id, txn.id, "credit", use, via=txn.id)
                    remaining -= use
    elif t == "bill" and manage_sources:
        po_id = _id(data.get("source_po_id"))
        if po_id:
            po = s.get(Transaction, po_id)
            if po is None or po.type != "purchase_order" or po.vendor_id != txn.vendor_id:
                raise ValidationError("Purchase order not found for this vendor.", "source_po_id")
            add_link(txn.id, po.id, "po", txn.total_cents)
    elif t == "deposit":
        if manage_deposits:
            for dep in data.get("deposits") or []:
                src_id = _id(dep.get("txn_id") if isinstance(dep, dict) else dep)
                if not src_id:
                    continue
                src = s.get(Transaction, src_id)
                if src is None or src.type not in info.applies_to or src.voided:
                    raise ValidationError("That payment can't be deposited.", "deposits")
                holding = s.get(Account, src.account_id) if src.account_id else None
                if holding is None or holding.system_key != "undeposited_funds":
                    raise ValidationError(f"{src.info.label} {src.number or ''} was already deposited to "
                                          f"{holding.name if holding else 'an account'}.", "deposits")
                other = s.scalar(select(TransactionLink.id).where(TransactionLink.to_txn_id == src.id,
                                                                  TransactionLink.link_type == "deposit",
                                                                  TransactionLink.from_txn_id != txn.id))
                if other:
                    raise ValidationError(f"{src.info.label} {src.number or ''} is already in another deposit.",
                                          "deposits")
                add_link(txn.id, src.id, "deposit", src.total_cents)
        _deposit_total(s, txn)
    s.flush()
    s.expire(txn, ["links_out", "links_in"])


def _deposit_total(s: Session, txn: Transaction) -> None:
    s.flush()
    linked = 0
    for link in s.scalars(select(TransactionLink).where(TransactionLink.from_txn_id == txn.id,
                                                        TransactionLink.link_type == "deposit")):
        src = s.get(Transaction, link.to_txn_id)
        linked += -link.amount_cents if src.type == "refund_receipt" else link.amount_cents
    lines = sum(ln.amount_cents for ln in txn.lines if ln.kind == "account")
    txn.subtotal_cents = txn.total_cents = linked + lines
    if not txn.lines and linked == 0:
        raise ValidationError("Select payments to deposit or add deposit lines.", "lines")


def _auto_apply(s: Session, txn: Transaction, target_types: Iterable[str], party_field: str,
                amount: int) -> list[dict]:
    opens = s.scalars(select(Transaction).where(
        getattr(Transaction, party_field) == getattr(txn, party_field), Transaction.type.in_(list(target_types)),
        Transaction.balance_cents > 0, Transaction.voided.is_(False), Transaction.id != (txn.id or 0))
        .order_by(Transaction.due_date, Transaction.date, Transaction.id)).all()
    # An exact match on one open item wins over oldest-first.
    for o in opens:
        if o.balance_cents == amount:
            return [{"txn_id": o.id, "amount_cents": amount}]
    apps, remaining = [], amount
    for o in opens:
        if remaining <= 0:
            break
        use = min(o.balance_cents, remaining)
        apps.append({"txn_id": o.id, "amount_cents": use})
        remaining -= use
    return apps


def _apply_custom_fields(s: Session, txn: Transaction, values: dict) -> None:
    existing = {v.field_id: v for v in s.scalars(select(CustomFieldValue).where(CustomFieldValue.txn_id == txn.id))}
    for raw_id, value in (values or {}).items():
        fid = _id(raw_id)
        if not fid:
            continue
        text = _text(value) or ""
        if fid in existing:
            existing[fid].value = text
        elif text:
            s.add(CustomFieldValue(field_id=fid, txn_id=txn.id, value=text))


# -- side effects on related records ---------------------------------------------------


def _sync_billed_sources(s: Session, txn: Transaction) -> None:
    """Invoice lines pulled from billable expenses, time and delayed charges
    mark their source as billed (and release sources no longer on the invoice)."""
    if txn.type not in ("invoice", "sales_receipt"):
        return
    expense_ids = {ln.source_id for ln in txn.lines if ln.source_type == "expense_line" and ln.source_id}
    time_ids = {ln.source_id for ln in txn.lines if ln.source_type == "time" and ln.source_id}
    for ln in s.scalars(select(TransactionLine).where(TransactionLine.billed_txn_id == txn.id)).all():
        if ln.id not in expense_ids:
            ln.billed_txn_id = None
    for ln_id in expense_ids:
        ln = s.get(TransactionLine, ln_id)
        if ln is not None:
            ln.billed_txn_id = txn.id
    for ta in s.scalars(select(TimeActivity).where(TimeActivity.billed_txn_id == txn.id)).all():
        if ta.id not in time_ids:
            ta.billed_txn_id = None
    for ta_id in time_ids:
        ta = s.get(TimeActivity, ta_id)
        if ta is not None:
            ta.billed_txn_id = txn.id
    delayed_line_ids = {ln.source_id for ln in txn.lines if ln.source_type == "delayed_line" and ln.source_id}
    for ln_id in delayed_line_ids:
        ln = s.get(TransactionLine, ln_id)
        if ln is not None:
            ln.billed_txn_id = txn.id


def _sync_po_receipts(s: Session, txn: Transaction) -> None:
    """Bills built from a purchase order update the quantities received on it."""
    if txn.type not in ("bill", "expense", "check"):
        return
    s.flush()
    po_line_ids = {ln.source_id for ln in txn.lines if ln.source_type == "po_line" and ln.source_id}
    previously = set(s.scalars(select(TransactionLine.id).where(
        TransactionLine.billed_txn_id == txn.id, TransactionLine.txn_id.in_(
            select(Transaction.id).where(Transaction.type == "purchase_order")))))
    recompute_po_lines(s, po_line_ids | previously)


def recompute_po_lines(s: Session, po_line_ids: Iterable[int]) -> None:
    ids = [i for i in po_line_ids if i]
    if not ids:
        return
    for po_line in s.scalars(select(TransactionLine).where(TransactionLine.id.in_(ids))).all():
        received_lines = s.scalars(select(TransactionLine).join(Transaction, Transaction.id == TransactionLine.txn_id)
                                   .where(TransactionLine.source_type == "po_line",
                                          TransactionLine.source_id == po_line.id,
                                          Transaction.voided.is_(False))).all()
        qty = sum((ln.qty or Decimal(0) for ln in received_lines), Decimal(0))
        amount = sum(ln.amount_cents for ln in received_lines)
        if po_line.kind == "item":
            po_line.received_qty = qty
            po_line.closed = po_line.closed or (po_line.qty is not None and qty >= po_line.qty)
        else:
            po_line.received_qty = Decimal(amount) / Decimal(100)
            po_line.closed = po_line.closed or amount >= po_line.amount_cents
        po_line.billed_txn_id = received_lines[-1].txn_id if received_lines else None
        po = s.get(Transaction, po_line.txn_id)
        if po is not None:
            lines = [ln for ln in po.lines if ln.kind in ("item", "account")]
            po.status = "closed" if lines and all(ln.closed for ln in lines) else "open"


def _sync_workflow_statuses(s: Session, txn: Transaction, old_related: set[int]) -> None:
    for rid in old_related | related_ids(s, txn):
        other = s.get(Transaction, rid)
        if other is None:
            continue
        if other.type == "estimate":
            linked = s.scalar(select(TransactionLink.id).where(TransactionLink.to_txn_id == other.id,
                                                               TransactionLink.link_type == "estimate").limit(1))
            if linked and other.status in ("pending", "accepted"):
                other.status = "closed"
            elif not linked and other.status in ("closed", "converted"):
                other.status = "accepted"
        if other.type in ("delayed_charge", "delayed_credit"):
            billed = s.scalar(select(TransactionLine.id).where(
                TransactionLine.txn_id == other.id, TransactionLine.billed_txn_id.isnot(None)).limit(1))
            other.status = "closed" if billed else "open"


def refresh_balances(s: Session, txn_ids: Iterable[int]) -> None:
    s.flush()
    for tid in {i for i in txn_ids if i}:
        t = s.get(Transaction, tid)
        if t is None:
            continue
        if t.voided or not t.info.open_item:
            t.balance_cents = 0
            continue
        out_sum = s.scalar(select(func.coalesce(func.sum(TransactionLink.amount_cents), 0)).where(
            TransactionLink.from_txn_id == tid, TransactionLink.link_type.in_(SETTLE_LINKS)))
        in_sum = s.scalar(select(func.coalesce(func.sum(TransactionLink.amount_cents), 0)).where(
            TransactionLink.to_txn_id == tid, TransactionLink.link_type.in_(SETTLE_LINKS)))
        t.balance_cents = t.total_cents - int(out_sum or 0) - int(in_sum or 0)


def related_ids(s: Session, txn: Transaction) -> set[int]:
    if txn.id is None:
        return set()
    s.flush()
    rows = s.execute(select(TransactionLink.from_txn_id, TransactionLink.to_txn_id).where(
        or_(TransactionLink.from_txn_id == txn.id, TransactionLink.to_txn_id == txn.id,
            TransactionLink.via_txn_id == txn.id))).all()
    out = set()
    for a, b in rows:
        out.add(a)
        out.add(b)
    out.discard(txn.id)
    return out


def inventory_item_ids(s: Session, txn: Transaction) -> set[int]:
    ids = {ln.item_id for ln in txn.lines if ln.item_id}
    if not ids:
        return set()
    return set(s.scalars(select(Item.id).where(Item.id.in_(ids), Item.type == "inventory")))


# -- void / delete -------------------------------------------------------------------


def _deposit_holding_check(s: Session, txn: Transaction, verb: str) -> None:
    dep = s.scalar(select(Transaction).join(TransactionLink, TransactionLink.from_txn_id == Transaction.id).where(
        TransactionLink.to_txn_id == txn.id, TransactionLink.link_type == "deposit", Transaction.voided.is_(False)))
    if dep is not None:
        raise ValidationError(
            f"This {txn.info.label.lower()} is part of a deposit on {dep.date:%m/%d/%Y}. "
            f"Remove it from that deposit before you {verb} it.")


def _release_sources(s: Session, txn: Transaction) -> None:
    for ln in s.scalars(select(TransactionLine).where(TransactionLine.billed_txn_id == txn.id)).all():
        ln.billed_txn_id = None
    for ta in s.scalars(select(TimeActivity).where(TimeActivity.billed_txn_id == txn.id)).all():
        ta.billed_txn_id = None
    for item in s.scalars(select(BankFeedItem).where(BankFeedItem.txn_id == txn.id)).all():
        item.txn_id = None
        item.status = "review"
        item.reviewed_at = None


@atomic
def void(s: Session, txn: Transaction, user: Optional[User] = None,
         closing_password: Optional[str] = None) -> Transaction:
    if txn.voided:
        return txn
    closing.guard(s, [txn.date], user, closing_password)
    _deposit_holding_check(s, txn, "void")
    before = audit.snapshot(txn)
    related = related_ids(s, txn)
    items = inventory_item_ids(s, txn)
    po_lines = {ln.source_id for ln in txn.lines if ln.source_type == "po_line"}
    for link in list(txn.links_out) + list(txn.links_in):
        s.delete(link)
    for link in s.scalars(select(TransactionLink).where(TransactionLink.via_txn_id == txn.id)).all():
        s.delete(link)
    _release_sources(s, txn)
    txn.voided = True
    txn.voided_at = utcnow()
    txn.memo = f"Voided{': ' + txn.memo if txn.memo else ''}"
    posting.unpost(s, txn)
    s.flush()

    from pps_tools.books.services import inventory

    inventory.recompute_items(s, items)
    refresh_balances(s, related | {txn.id})
    recompute_po_lines(s, po_lines)
    _sync_workflow_statuses(s, txn, related)
    audit.record(s, user, "void", "transaction", txn.id, before=before, after=audit.snapshot(txn), txn=txn)
    s.flush()
    return txn


@atomic
def delete(s: Session, txn: Transaction, user: Optional[User] = None,
           closing_password: Optional[str] = None) -> None:
    closing.guard(s, [txn.date], user, closing_password)
    _deposit_holding_check(s, txn, "delete")
    before = audit.snapshot(txn)
    related = related_ids(s, txn)
    items = inventory_item_ids(s, txn)
    po_lines = {ln.source_id for ln in txn.lines if ln.source_type == "po_line"}
    tid, label, tnum, tdate, total, name, ttype = (txn.id, txn.info.label, txn.number, txn.date,
                                                   txn.total_cents, txn.entity_name, txn.type)
    _release_sources(s, txn)
    for link in s.scalars(select(TransactionLink).where(TransactionLink.via_txn_id == txn.id)).all():
        s.delete(link)
    s.delete(txn)
    s.flush()

    from pps_tools.books.services import inventory

    inventory.recompute_items(s, items)
    refresh_balances(s, related)
    recompute_po_lines(s, po_lines)
    for rid in related:
        other = s.get(Transaction, rid)
        if other is not None and other.type == "estimate":
            if not s.scalar(select(TransactionLink.id).where(TransactionLink.to_txn_id == rid,
                                                             TransactionLink.link_type == "estimate")):
                if other.status in ("closed", "converted"):
                    other.status = "accepted"
        if other is not None and other.type in ("delayed_charge", "delayed_credit"):
            other.status = "open"
    entry = audit.record(s, user, "delete", "transaction", tid, before=before,
                         summary=f"Deleted {label}{' ' + tnum if tnum else ''} {money.fmt(total)}")
    entry.txn_type, entry.txn_date, entry.amount_cents, entry.name = ttype, tdate, total, name
    s.flush()


# -- reading back ----------------------------------------------------------------------


def to_payload(txn: Transaction, for_copy: bool = False) -> dict:
    """The dict :func:`save` would need to recreate this transaction."""
    def d(v):
        return v.isoformat() if isinstance(v, date) else v

    data: dict[str, Any] = {
        "type": txn.type,
        "date": d(txn.date),
        "due_date": d(txn.due_date),
        "number": txn.number,
        "customer_id": txn.customer_id, "vendor_id": txn.vendor_id, "employee_id": txn.employee_id,
        "tax_agency_id": txn.tax_agency_id,
        "account_id": txn.account_id, "to_account_id": txn.to_account_id,
        "terms_id": txn.terms_id, "payment_method_id": txn.payment_method_id, "ref_no": txn.ref_no,
        "billing_address": txn.billing_address, "shipping_address": txn.shipping_address,
        "ship_via": txn.ship_via, "ship_date": d(txn.ship_date), "tracking_no": txn.tracking_no,
        "memo": txn.memo, "message": txn.message, "statement_memo": txn.statement_memo,
        "email_to": txn.email_to, "email_cc": txn.email_cc, "email_bcc": txn.email_bcc,
        "class_id": txn.class_id, "location_id": txn.location_id, "tax_rate_id": txn.tax_rate_id,
        "discount_type": txn.discount_type,
        "discount_value": format(txn.discount_value, "f") if txn.discount_value is not None else None,
        "discount_before_tax": txn.discount_before_tax,
        "shipping_cents": txn.shipping_cents,
        "expiration_date": d(txn.expiration_date), "status": txn.status,
        "allow_online_card": txn.allow_online_card, "allow_online_ach": txn.allow_online_ach,
        "tag_ids": [t.id for t in txn.tags],
    }
    if txn.info.entity == "payee":
        data["payee"] = payee_key(txn)
    if txn.info.has_amount:
        data["amount_cents"] = txn.total_cents
    if txn.tax_override:
        data["tax_override"] = True
        data["tax_amount"] = money.fmt_plain(txn.tax_cents)
    lines = []
    for ln in txn.lines:
        row: dict[str, Any] = {
            "kind": ln.kind, "item_id": ln.item_id, "account_id": ln.account_id,
            "description": ln.description,
            "qty": format(ln.qty, "f") if ln.qty is not None else None,
            "rate": format(ln.rate, "f") if ln.rate is not None else None,
            "amount_cents": ln.amount_cents, "taxable": ln.taxable,
            "service_date": d(ln.service_date), "class_id": ln.class_id, "location_id": ln.location_id,
            "customer_id": ln.customer_id, "vendor_id": ln.vendor_id, "employee_id": ln.employee_id,
            "billable": ln.billable,
            "markup_pct": format(ln.markup_pct, "f") if ln.markup_pct is not None else None,
            "payment_method_id": ln.payment_method_id, "ref_no": ln.ref_no,
        }
        if txn.type == "journal_entry":
            row["debit_cents" if ln.posting_type == "debit" else "credit_cents"] = ln.amount_cents
            row.pop("amount_cents")
        if txn.type == "inventory_adjustment":
            row["qty"] = format(ln.qty, "f") if ln.qty is not None else None
        if not for_copy:
            row["id"] = ln.id
            row["source_type"] = ln.source_type
            row["source_id"] = ln.source_id
        lines.append(row)
    data["lines"] = lines
    if for_copy:
        for k in ("number", "due_date", "status"):
            data.pop(k, None)
        data["date"] = date.today().isoformat()
    else:
        apps = [{"txn_id": l.to_txn_id, "amount_cents": l.amount_cents} for l in txn.links_out
                if l.link_type == txn.info.link_type and txn.info.link_type != "deposit"]
        if apps:
            data["applications"] = apps
        if txn.type == "deposit":
            data["deposits"] = [l.to_txn_id for l in txn.links_out if l.link_type == "deposit"]
    return data


def status(txn: Transaction, today: Optional[date] = None) -> tuple[str, str]:
    """(code, label) for lists and badges."""
    today = today or date.today()
    if txn.voided:
        return "void", "Voided"
    t = txn.type
    if t in ("estimate",):
        labels = {"pending": "Pending", "accepted": "Accepted", "rejected": "Rejected",
                  "closed": "Closed", "converted": "Converted"}
        if txn.status == "pending" and txn.expiration_date and txn.expiration_date < today:
            return "expired", "Expired"
        return txn.status or "pending", labels.get(txn.status or "pending", txn.status or "")
    if t in ("purchase_order", "delayed_charge", "delayed_credit"):
        return txn.status or "open", (txn.status or "open").title()
    if t in ("invoice", "bill"):
        if txn.balance_cents <= 0:
            return "paid", "Paid"
        overdue = txn.due_date is not None and txn.due_date < today
        days = (today - txn.due_date).days if overdue else 0
        if txn.balance_cents < txn.total_cents:
            return ("overdue" if overdue else "partial"), (
                f"Partially paid, overdue {days} days" if overdue else "Partially paid")
        if overdue:
            return "overdue", f"Overdue {days} day{'s' if days != 1 else ''}"
        if t == "invoice":
            if txn.viewed_at:
                return "viewed", "Viewed"
            if txn.sent_at:
                return "sent", "Sent"
            due = (txn.due_date - today).days if txn.due_date else 0
            return "open", "Due today" if due == 0 else f"Due in {due} days"
        return "open", "Open"
    if t in ("payment", "credit_memo", "vendor_credit", "bill_payment"):
        if txn.balance_cents > 0:
            return "unapplied", f"{money.fmt(txn.balance_cents)} unapplied" if t in ("payment", "bill_payment") \
                else f"{money.fmt(txn.balance_cents)} available"
        if t == "payment" and txn.account_id:
            return "closed", "Closed"
        return "closed", "Closed" if t != "payment" else "Applied"
    if t in ("sales_receipt",):
        return "paid", "Paid"
    return "posted", ""


def open_items(s: Session, kind: str, party_id: int, types: Iterable[str],
               exclude_txn: Optional[Transaction] = None) -> list[tuple[Transaction, int]]:
    """Open invoices/bills or available credits for a customer/vendor, with
    the balance as it was before ``exclude_txn`` applied anything to them."""
    party_field = Transaction.customer_id if kind == "ar" else Transaction.vendor_id
    q = select(Transaction).where(party_field == party_id, Transaction.type.in_(list(types)),
                                  Transaction.voided.is_(False)).order_by(Transaction.due_date, Transaction.date,
                                                                          Transaction.id)
    out = []
    for t in s.scalars(q).all():
        if exclude_txn is not None and exclude_txn.id:
            if t.id == exclude_txn.id:
                continue
            bal = _open_balance_excluding(s, t, exclude_txn.id)
        else:
            bal = t.balance_cents
        if bal > 0:
            out.append((t, bal))
    return out


def deposit_candidates(s: Session, deposit: Optional[Transaction] = None) -> list[Transaction]:
    """Payments and receipts sitting in Payments to deposit."""
    uf = system_account_id(s, "undeposited_funds")
    q = select(Transaction).where(Transaction.account_id == uf,
                                  Transaction.type.in_(("payment", "sales_receipt", "refund_receipt")),
                                  Transaction.voided.is_(False)).order_by(Transaction.date, Transaction.id)
    out = []
    for t in s.scalars(q).all():
        link = s.scalar(select(TransactionLink).where(TransactionLink.to_txn_id == t.id,
                                                      TransactionLink.link_type == "deposit"))
        if link is None or (deposit is not None and link.from_txn_id == deposit.id):
            if t.total_cents:
                out.append(t)
    return out


def is_deposited(s: Session, txn: Transaction) -> bool:
    if txn.account_id and txn.account_id != system_account_id(s, "undeposited_funds"):
        return True
    return bool(s.scalar(select(TransactionLink.id).where(TransactionLink.to_txn_id == txn.id,
                                                          TransactionLink.link_type == "deposit").limit(1)))


def mark_sent(txn: Transaction, when: Optional[datetime] = None) -> None:
    txn.sent_at = when or utcnow()
