"""One set of views for every transaction type, driven by the type registry."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from flask import (Blueprint, Response, abort, flash, jsonify, redirect, render_template, request,
                   url_for)
from sqlalchemy import select

from pps_tools.books import money
from pps_tools.books.models import (Account, AuditLog, CustomFieldDef, CustomFieldValue, Customer, Employee,
                                    Item, Location, PaymentMethod, Tag, TaxAgency, TaxRate, Terms, TimeActivity,
                                    TrackingClass, Transaction, TransactionLine, TransactionLink, Vendor)
from pps_tools.books.services import applications, audit
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.accounts import ordered_accounts, system_account_id
from pps_tools.books.services.errors import BooksError, ClosedPeriodError
from pps_tools.books.services import users as user_service
from pps_tools.books.txn_types import BY_SLUG, TXN_TYPES, TxnType
from pps_tools.books.web import core

bp = Blueprint("txn", __name__)


def _info_for_slug(slug: str) -> TxnType:
    info = BY_SLUG.get(slug)
    if info is None:
        abort(404)
    return info


def _load(txn_id: int) -> Transaction:
    txn = core.db().get(Transaction, txn_id)
    if txn is None:
        abort(404)
    if not user_service.can_view_type(core.current_user(), txn.type):
        abort(403)
    return txn


def _require_edit(ttype: str) -> None:
    if not user_service.can_edit_type(core.current_user(), ttype):
        abort(403)


# -- reading the form ------------------------------------------------------------------


HEADER_FIELDS = ["date", "due_date", "number", "customer_id", "vendor_id", "tax_agency_id", "account_id",
                 "to_account_id", "terms_id", "payment_method_id", "ref_no", "billing_address", "shipping_address",
                 "ship_via", "ship_date", "tracking_no", "memo", "message", "statement_memo", "email_to", "email_cc",
                 "email_bcc", "class_id", "location_id", "tax_rate_id", "discount_type", "discount_value",
                 "expiration_date", "status", "amount", "shipping", "payee"]


def parse_form(info: TxnType, txn: Optional[Transaction]) -> dict[str, Any]:
    data: dict[str, Any] = {"type": info.code}
    for name in HEADER_FIELDS:
        if name in request.form:
            data[name] = core.f(name)
    for flag in ("discount_before_tax", "print_later", "allow_online_card", "allow_online_ach"):
        if f"has_{flag}" in request.form:
            data[flag] = core.f_bool(flag)
    if "tax_override" in request.form or "tax_amount" in request.form:
        data["tax_override"] = core.f_bool("tax_override")
        if data["tax_override"]:
            data["tax_amount"] = core.f("tax_amount")
    if "has_lines" in request.form:
        rows = core.indexed_rows("l", bools=("taxable", "billable"))
        data["lines"] = [_clean_line(r) for r in rows]
    if "has_tags" in request.form:
        data["tag_ids"] = request.form.getlist("tag_ids")
    cf = {k[3:]: v for k, v in request.form.items() if k.startswith("cf_")}
    if cf:
        data["custom_fields"] = cf
    if "source_estimate_id" in request.form:
        data["source_estimate_id"] = core.f("source_estimate_id")
    if "source_po_id" in request.form:
        data["source_po_id"] = core.f("source_po_id")
    if core.f_int("recurring_template_id"):
        data["recurring_template_id"] = core.f_int("recurring_template_id")
    if core.f_bool("allow_duplicate"):
        data["allow_duplicate"] = True

    if info.code in ("payment", "bill_payment", "customer_refund", "credit_memo", "vendor_credit") \
            and "has_apply" in request.form:
        targets = [(int(r["txn_id"]), money.cents(r.get("amount") or "0"))
                   for r in core.indexed_rows("ap") if r.get("txn_id")]
        credits = [(int(r["txn_id"]), money.cents(r.get("amount") or "0"))
                   for r in core.indexed_rows("cr") if r.get("txn_id")]
        if info.code in ("payment", "bill_payment"):
            cash = money.cents(data.get("amount") or "0")
            split = applications.split(targets, credits, cash)
            data["applications"] = split.applications
            data["credits"] = [{"txn_id": c["txn_id"], "target_id": c["target_id"], "amount_cents": c["amount_cents"]}
                               for c in split.credits]
        else:
            data["applications"] = [{"txn_id": t, "amount_cents": a} for t, a in targets if a]
            if info.code == "customer_refund":
                data["amount_cents"] = sum(a for _, a in targets)
                data.pop("amount", None)
    if info.code == "deposit" and "has_deposits" in request.form:
        data["deposits"] = [int(x) for x in request.form.getlist("deposit_ids") if x.isdigit()]
    return data


def _clean_line(r: dict) -> dict:
    out = {k: v for k, v in r.items() if k != "pos"}
    for key in ("id", "item_id", "account_id", "class_id", "location_id", "customer_id", "payment_method_id",
                "source_id"):
        if key in out and out[key] in ("", "None"):
            out[key] = None
    if "name" in out and not out["name"]:
        out.pop("name")
    if out.get("kind") == "":
        out.pop("kind")
    return out


# -- form context ------------------------------------------------------------------------


def _choices(s) -> dict[str, Any]:
    accounts = ordered_accounts(s, active_only=True)
    items = s.scalars(select(Item).where(Item.active.is_(True)).order_by(Item.name)).all()
    return {
        "customers": s.scalars(select(Customer).where(Customer.active.is_(True)).order_by(Customer.display_name)).all(),
        "vendors": s.scalars(select(Vendor).where(Vendor.active.is_(True)).order_by(Vendor.display_name)).all(),
        "employees": s.scalars(select(Employee).where(Employee.active.is_(True)).order_by(Employee.display_name)).all(),
        "items": items,
        "items_json": {it.id: {"name": it.name, "type": it.type, "price": str(it.sales_price) if it.sales_price is not None else "",
                               "cost": str(it.cost) if it.cost is not None else "", "desc": it.description or "",
                               "pdesc": it.purchase_description or it.description or "", "taxable": it.taxable,
                               "sku": it.sku or "", "onhand": str(it.qty_on_hand or 0) if it.type == "inventory" else None}
                       for it in items},
        "accounts": accounts,
        "terms": s.scalars(select(Terms).where(Terms.active.is_(True)).order_by(Terms.due_days)).all(),
        "terms_json": {t.id: {"days": t.due_days, "kind": t.kind, "dom": t.day_of_month, "cutoff": t.cutoff_days}
                       for t in s.scalars(select(Terms))},
        "payment_methods": s.scalars(select(PaymentMethod).where(PaymentMethod.active.is_(True))
                                     .order_by(PaymentMethod.name)).all(),
        "classes": s.scalars(select(TrackingClass).where(TrackingClass.active.is_(True)).order_by(TrackingClass.name)).all(),
        "locations": s.scalars(select(Location).where(Location.active.is_(True)).order_by(Location.name)).all(),
        "tax_rates": s.scalars(select(TaxRate).where(TaxRate.active.is_(True)).order_by(TaxRate.name)).all(),
        "tax_agencies": s.scalars(select(TaxAgency).where(TaxAgency.active.is_(True)).order_by(TaxAgency.name)).all(),
        "tags": s.scalars(select(Tag).order_by(Tag.group_name, Tag.name)).all(),
    }


def _display_lines(data: dict) -> list[dict]:
    """Payload lines -> strings for the form inputs."""
    out = []
    for ln in data.get("lines") or []:
        row = dict(ln)
        for key in ("amount", "debit", "credit"):
            cents_key = f"{key}_cents"
            if row.get(cents_key) is not None and row.get(key) in (None, ""):
                row[key] = money.fmt_plain(row[cents_key])
        if row.get("kind") is None:
            row["kind"] = "item" if row.get("item_id") else "account"
        if row.get("customer_id") and not row.get("name"):
            row["name"] = f"customer:{row['customer_id']}"
        elif row.get("vendor_id") and not row.get("name"):
            row["name"] = f"vendor:{row['vendor_id']}"
        elif row.get("employee_id") and not row.get("name"):
            row["name"] = f"employee:{row['employee_id']}"
        for key in ("qty", "rate", "new_qty"):
            v = row.get(key)
            if v not in (None, ""):
                try:
                    d = Decimal(str(v))
                    row[key] = str(int(d)) if d == d.to_integral_value() else format(d.normalize(), "f")
                except ArithmeticError:
                    pass
        out.append(row)
    return out


def _header_accounts(s, info: TxnType) -> list[Account]:
    if not info.header_account_types:
        return []
    return [a for a in ordered_accounts(s, active_only=True) if a.type in info.header_account_types]


def _apply_rows(s, info: TxnType, txn: Optional[Transaction], party_id: Optional[int]) -> dict[str, list]:
    """Open items and credits for the apply table (payments, bill payments, credits, refunds)."""
    if not party_id:
        return {"targets": [], "credits": []}
    kind = "ar" if info.open_item == "ar" else "ap"
    existing_apps: dict[int, int] = {}
    existing_credits: dict[int, int] = {}
    if txn is not None and txn.id:
        for link in txn.links_out:
            if link.link_type == info.link_type:
                existing_apps[link.to_txn_id] = existing_apps.get(link.to_txn_id, 0) + link.amount_cents
        for link in s.scalars(select(TransactionLink).where(TransactionLink.via_txn_id == txn.id)):
            existing_apps[link.to_txn_id] = existing_apps.get(link.to_txn_id, 0) + link.amount_cents
            existing_credits[link.from_txn_id] = existing_credits.get(link.from_txn_id, 0) + link.amount_cents
    if info.code in ("payment", "bill_payment"):
        target_types = ("invoice",) if kind == "ar" else ("bill",)
        credit_types = ("credit_memo", "payment") if kind == "ar" else ("vendor_credit", "bill_payment")
    elif info.code == "customer_refund":
        target_types, credit_types = ("credit_memo", "payment"), ()
    else:  # credit_memo / vendor_credit applied to invoices / bills
        target_types, credit_types = info.applies_to, ()
    targets = []
    for t, bal in tx.open_items(s, kind, party_id, target_types, exclude_txn=txn):
        targets.append({"txn": t, "open": bal, "applied": existing_apps.get(t.id, 0)})
    for tid, amt in existing_apps.items():
        if not any(r["txn"].id == tid for r in targets):
            t = s.get(Transaction, tid)
            if t is not None and t.type in target_types:
                targets.append({"txn": t, "open": amt, "applied": amt})
    credits = []
    for t, bal in (tx.open_items(s, kind, party_id, credit_types, exclude_txn=txn) if credit_types else []):
        credits.append({"txn": t, "open": bal, "applied": existing_credits.get(t.id, 0)})
    for cid, amt in existing_credits.items():
        if not any(r["txn"].id == cid for r in credits):
            t = s.get(Transaction, cid)
            if t is not None:
                credits.append({"txn": t, "open": amt, "applied": amt})
    targets.sort(key=lambda r: (r["txn"].due_date or r["txn"].date, r["txn"].id))
    return {"targets": targets, "credits": credits}


def _related(s, txn: Transaction) -> list[dict]:
    out = []
    for link in txn.links_out:
        other = link.to_txn
        out.append({"txn": other, "type": link.link_type, "amount": link.amount_cents, "dir": "to"})
    for link in txn.links_in:
        other = link.from_txn
        out.append({"txn": other, "type": link.link_type, "amount": link.amount_cents, "dir": "from"})
    for link in s.scalars(select(TransactionLink).where(TransactionLink.via_txn_id == txn.id)):
        out.append({"txn": link.from_txn, "type": "credit used", "amount": link.amount_cents, "dir": "via"})
    return out


def render_form(info: TxnType, txn: Optional[Transaction], data: dict, status: int = 200, **extra):
    s = core.db()
    ctx = _choices(s)
    lines = _display_lines(data)
    party_id = data.get("customer_id") if info.open_item == "ar" else data.get("vendor_id")
    try:
        party_id = int(party_id) if party_id else None
    except (TypeError, ValueError):
        party_id = None
    apply = _apply_rows(s, info, txn, party_id) if info.applies_to and info.code != "deposit" else None
    deposits = tx.deposit_candidates(s, txn) if info.code == "deposit" else []
    selected_deposits = set(data.get("deposits") or [])
    custom_fields = s.scalars(select(CustomFieldDef).where(CustomFieldDef.active.is_(True))
                              .order_by(CustomFieldDef.position)).all()
    custom_fields = [cf for cf in custom_fields if info.code in (cf.applies_to or "").split(",")]
    cf_values = {}
    if txn is not None and txn.id:
        cf_values = {v.field_id: v.value for v in s.scalars(select(CustomFieldValue)
                                                              .where(CustomFieldValue.txn_id == txn.id))}
    for k, v in (data.get("custom_fields") or {}).items():
        cf_values[int(k)] = v
    from pps_tools.books.services import attachments as attach_service

    attachments = attach_service.for_object(s, "transaction", txn.id) if txn is not None and txn.id else []
    history = []
    if txn is not None and txn.id:
        history = s.scalars(select(AuditLog).where(AuditLog.object_type == "transaction",
                                                   AuditLog.object_id == txn.id).order_by(AuditLog.ts.desc())
                            .limit(10)).all()
    billable = []
    if info.code == "invoice" and party_id:
        billable = _billable_for(s, party_id, txn)
    from pps_tools.books.services.recurring import RECURRABLE

    return render_template(
        "txn/form.html", info=info, txn=txn, data=data, lines=lines, apply=apply, deposits=deposits,
        recurrable=RECURRABLE,
        selected_deposits=selected_deposits, header_accounts=_header_accounts(s, info), custom_fields=custom_fields,
        cf_values=cf_values, attachments=attachments, history=history, billable=billable,
        related=_related(s, txn) if txn is not None and txn.id else [],
        closing_date=core.company().closing_date, readonly=bool(txn and txn.voided)
        or not user_service.can_edit_type(core.current_user(), info.code), **ctx, **extra), status


def _billable_for(s, customer_id: int, txn: Optional[Transaction]) -> list[dict]:
    """Unbilled billable expense lines, time and delayed charges for a customer."""
    out = []
    already = {(ln.source_type, ln.source_id) for ln in (txn.lines if txn else []) if ln.source_type}
    q = (select(TransactionLine, Transaction).join(Transaction, Transaction.id == TransactionLine.txn_id)
         .where(TransactionLine.customer_id == customer_id, TransactionLine.billable.is_(True),
                TransactionLine.billed_txn_id.is_(None), Transaction.voided.is_(False),
                Transaction.type.in_(("expense", "check", "bill", "cc_credit"))))
    for ln, t in s.execute(q):
        if ("expense_line", ln.id) in already:
            continue
        markup = ln.markup_pct or Decimal(0)
        amount = money.round_cents(Decimal(ln.amount_cents) / 100 * (1 + markup / 100))
        out.append({"kind": "expense", "source_type": "expense_line", "source_id": ln.id, "date": t.date,
                    "description": ln.description or (ln.item.name if ln.item else t.entity_name),
                    "item_id": ln.item_id, "account_id": ln.account_id, "qty": ln.qty, "rate": None,
                    "amount": amount, "label": f"{t.info.label} {t.number or ''} · {t.entity_name}"})
    for ta in s.scalars(select(TimeActivity).where(TimeActivity.customer_id == customer_id,
                                                   TimeActivity.billable.is_(True),
                                                   TimeActivity.billed_txn_id.is_(None))):
        if ("time", ta.id) in already:
            continue
        hours = ta.hours
        rate = ta.hourly_rate or Decimal(0)
        out.append({"kind": "time", "source_type": "time", "source_id": ta.id, "date": ta.date,
                    "description": f"{ta.date:%m/%d} {ta.worker_name}: {ta.description or (ta.item.name if ta.item else 'Time')}",
                    "item_id": ta.item_id, "qty": hours, "rate": rate,
                    "amount": money.line_amount(hours, rate), "label": f"Time · {ta.worker_name}",
                    "taxable": ta.taxable})
    for dc in s.scalars(select(Transaction).where(Transaction.customer_id == customer_id,
                                                  Transaction.type.in_(("delayed_charge", "delayed_credit")),
                                                  Transaction.status == "open", Transaction.voided.is_(False))):
        sign = -1 if dc.type == "delayed_credit" else 1
        for ln in dc.lines:
            if ln.kind != "item" or ("delayed_line", ln.id) in already:
                continue
            out.append({"kind": "delayed", "source_type": "delayed_line", "source_id": ln.id, "date": dc.date,
                        "description": ln.description or (ln.item.name if ln.item else ""), "item_id": ln.item_id,
                        "qty": (ln.qty or Decimal(1)) * sign if ln.qty is not None else None, "rate": ln.rate,
                        "amount": sign * ln.amount_cents, "label": f"{dc.info.label} {dc.number or ''}",
                        "taxable": ln.taxable})
    out.sort(key=lambda r: r["date"])
    return out


# -- defaults for new transactions ---------------------------------------------------------


def _new_defaults(info: TxnType) -> dict:
    s = core.db()
    args = request.args
    data: dict[str, Any] = {"type": info.code, "date": date.today().isoformat(), "lines": []}
    for key in ("customer_id", "vendor_id", "account_id", "to_account_id", "tax_agency_id", "payee", "amount", "memo"):
        if args.get(key):
            data[key] = args.get(key)
    if args.get("from_template"):
        from pps_tools.books.models import RecurringTemplate

        tpl = s.get(RecurringTemplate, int(args["from_template"]))
        if tpl is not None and tpl.txn_type == info.code:
            data = dict(tpl.payload or {})
            data["type"] = info.code
            data["date"] = date.today().isoformat()
            data["recurring_template_id"] = tpl.id
            data["lines"] = [{k: v for k, v in ln.items() if k != "id"} for ln in data.get("lines") or []]
            if info.number_seq:
                from pps_tools.books.services import numbering

                data["number"] = numbering.peek(s, info.number_seq)
            return data
    if args.get("copy_of"):
        src = s.get(Transaction, int(args["copy_of"]))
        if src is not None and src.type == info.code:
            data = tx.to_payload(src, for_copy=True)
            data["memo"] = src.memo
            return data
    if args.get("from_estimate") and info.code == "invoice":
        est = s.get(Transaction, int(args["from_estimate"]))
        if est is not None and est.type == "estimate":
            data = tx.to_payload(est, for_copy=True)
            data["type"] = "invoice"
            data["source_estimate_id"] = est.id
            data["date"] = date.today().isoformat()
            data["message"] = None
            data.pop("expiration_date", None)
            return data
    if args.get("from_po") and info.code in ("bill", "check", "expense"):
        po = s.get(Transaction, int(args["from_po"]))
        if po is not None and po.type == "purchase_order":
            data.update({"vendor_id": po.vendor_id, "source_po_id": po.id, "lines": []})
            if info.code != "bill":
                data["payee"] = f"vendor:{po.vendor_id}"
            for ln in po.lines:
                if ln.kind not in ("item", "account") or ln.closed:
                    continue
                remaining = (ln.qty or Decimal(0)) - (ln.received_qty or Decimal(0)) if ln.kind == "item" else None
                row = {"kind": ln.kind, "item_id": ln.item_id, "account_id": ln.account_id,
                       "description": ln.description, "source_type": "po_line", "source_id": ln.id,
                       "customer_id": ln.customer_id, "billable": ln.billable, "class_id": ln.class_id}
                if ln.kind == "item":
                    row.update({"qty": str(remaining if remaining and remaining > 0 else ln.qty),
                                "rate": str(ln.rate) if ln.rate is not None else None})
                else:
                    received = int((ln.received_qty or Decimal(0)) * 100)
                    row["amount_cents"] = max(ln.amount_cents - received, 0)
                data["lines"].append(row)
            return data
    if args.get("invoice_id") and info.code == "payment":
        inv = s.get(Transaction, int(args["invoice_id"]))
        if inv is not None:
            data["customer_id"] = inv.customer_id
            data["preapply"] = {inv.id: inv.balance_cents}
            data["amount"] = money.fmt_plain(inv.balance_cents)
    if args.get("bill_id") and info.code == "bill_payment":
        bill = s.get(Transaction, int(args["bill_id"]))
        if bill is not None:
            data["vendor_id"] = bill.vendor_id
            data["preapply"] = {bill.id: bill.balance_cents}
            data["amount"] = money.fmt_plain(bill.balance_cents)
    if info.has_terms and not data.get("terms_id"):
        # The company's default terms, until a customer or vendor with their own terms is chosen.
        from pps_tools.books.services import prefs
        from pps_tools.books.services.dates import due_date

        default = prefs.get(s, "default_terms_id" if info.open_item == "ar" else "default_bill_terms_id")
        terms = s.get(Terms, int(default)) if default else None
        if terms is not None:
            data["terms_id"] = terms.id
            data["due_date"] = due_date(terms, date.today()).isoformat()
    if info.code in ("estimate", "invoice", "sales_receipt", "credit_memo", "refund_receipt") and not data.get("lines"):
        data["lines"] = [{"kind": "item"}, {"kind": "item"}]
    if info.code in ("bill", "expense", "check", "vendor_credit", "cc_credit", "purchase_order") and not data.get("lines"):
        data["lines"] = [{"kind": "account"}, {"kind": "account"}]
    if info.code == "journal_entry":
        data["lines"] = [{"kind": "account"} for _ in range(4)]
    if info.code == "deposit":
        data["lines"] = [{"kind": "account"}]
    if info.code == "inventory_adjustment":
        data["lines"] = [{"kind": "item"} for _ in range(3)]
        data["account_id"] = system_account_id(s, "inventory_shrinkage")
    if info.default_header_account and "account_id" not in data:
        from pps_tools.books.services import prefs

        key = info.default_header_account
        if key != "undeposited_funds" or prefs.get(s, "deposit_to_undeposited_funds"):
            data["account_id"] = system_account_id(s, key)
    if info.code in ("check", "bill_payment") and not data.get("account_id"):
        bank = next((a for a in ordered_accounts(s, active_only=True, types=["bank"])
                     if a.system_key != "stripe_clearing"), None)
        if bank:
            data["account_id"] = bank.id
    if info.code == "check" and data.get("account_id"):
        acct = s.get(Account, int(data["account_id"]))
        if acct is not None:
            data["number"] = str(acct.next_check_number or 1001)
    if info.number_seq:
        from pps_tools.books.services import numbering

        data["number"] = numbering.peek(s, info.number_seq)
    return data


# -- routes ------------------------------------------------------------------------------------


@bp.route("/txn/<int:txn_id>")
def go(txn_id: int):
    txn = _load(txn_id)
    return redirect(url_for("txn.edit", slug=txn.info.slug, txn_id=txn.id))


@bp.route("/t/<slug>/new", methods=["GET", "POST"])
def new(slug: str):
    info = _info_for_slug(slug)
    _require_edit(info.code)
    if request.method == "POST":
        return _save(info, None)
    return render_form(info, None, _new_defaults(info))[0]


@bp.route("/t/<slug>/<int:txn_id>", methods=["GET", "POST"])
def edit(slug: str, txn_id: int):
    txn = _load(txn_id)
    info = txn.info
    if info.slug != slug:
        return redirect(url_for("txn.edit", slug=info.slug, txn_id=txn.id))
    if request.method == "POST":
        _require_edit(info.code)
        return _save(info, txn)
    data = tx.to_payload(txn)
    return render_form(info, txn, data)[0]


def _save(info: TxnType, txn: Optional[Transaction]):
    s = core.db()
    user = core.current_user()
    try:
        data = parse_form(info, txn)
        password = request.form.get("closing_password")
        if password is None and core.f_bool("confirm_closed"):
            password = ""
        saved = tx.save(s, data, txn=txn, user=user, closing_password=password)
        _attach_uploads(s, saved)
        if txn is None and data.get("recurring_template_id"):
            _advance_reminder(s, int(data["recurring_template_id"]))
        s.commit()
    except ClosedPeriodError as exc:
        s.rollback()
        flash(str(exc), "error")
        return _rerender(info, txn, request.form, closing=True)
    except BooksError as exc:
        s.rollback()
        flash(str(exc), "error")
        return _rerender(info, txn, request.form)
    action = request.form.get("next_action", "save")
    label = f"{info.label}{' ' + saved.number if saved.number else ''}"
    flash(f"{label} saved.", "success")
    if action == "save_new":
        return redirect(url_for("txn.new", slug=info.slug))
    if action == "save_send" and (info.customer_facing or info.vendor_facing):
        return redirect(url_for("txn.send", txn_id=saved.id))
    if action == "save_print":
        return redirect(url_for("txn.pdf", txn_id=saved.id, print=1))
    if action == "save_close":
        return redirect(core.safe_next(_list_url(info)))
    return redirect(url_for("txn.edit", slug=info.slug, txn_id=saved.id))


def _advance_reminder(s, tpl_id: int) -> None:
    """Creating the transaction a reminder template asked for moves the reminder to its next date."""
    from pps_tools.books.models import RecurringTemplate
    from pps_tools.books.services import recurring as recurring_service

    tpl = s.get(RecurringTemplate, tpl_id)
    if tpl is not None and tpl.mode == "reminder" and tpl.active and tpl.next_date:
        recurring_service.advance(tpl)


def _attach_uploads(s, txn: Transaction) -> None:
    files = [f for f in request.files.getlist("attachments") if f and f.filename]
    if not files:
        return
    from pps_tools.books.services import attachments as attach_service

    for fs in files:
        att = attach_service.store(s, core.config(), fs.filename, fs.read(), fs.mimetype, core.current_user())
        attach_service.link(s, att, "transaction", txn.id)


def _rerender(info: TxnType, txn: Optional[Transaction], form, closing: bool = False):
    try:
        data = parse_form(info, txn)
    except BooksError:
        data = {"type": info.code}
    data["lines"] = data.get("lines") or (tx.to_payload(txn)["lines"] if txn else [])
    page, status = render_form(info, txn, data, status=422)
    return page, status


def _list_url(info: TxnType) -> str:
    return {
        "invoice": url_for("sales.invoices"), "estimate": url_for("sales.estimates"),
        "bill": url_for("expenses.bills"), "purchase_order": url_for("expenses.purchase_orders"),
        "journal_entry": url_for("accounting.journal_entries"),
    }.get(info.code, url_for("sales.all_sales") if info.section == "sales" else url_for("expenses.index")
          if info.section == "expenses" else url_for("dashboard.home"))


@bp.route("/t/<int:txn_id>/void", methods=["POST"])
def void(txn_id: int):
    txn = _load(txn_id)
    _require_edit(txn.type)
    s = core.db()
    try:
        password = request.form.get("closing_password")
        tx.void(s, txn, user=core.current_user(), closing_password=password if password is not None else (
            "" if core.f_bool("confirm_closed") else None))
        s.commit()
        flash(f"{txn.info.label} voided.", "success")
    except BooksError as exc:
        s.rollback()
        flash(str(exc), "error")
    return redirect(url_for("txn.edit", slug=txn.info.slug, txn_id=txn.id))


@bp.route("/t/<int:txn_id>/delete", methods=["POST"])
def delete(txn_id: int):
    txn = _load(txn_id)
    _require_edit(txn.type)
    s = core.db()
    info = txn.info
    try:
        password = request.form.get("closing_password")
        tx.delete(s, txn, user=core.current_user(), closing_password=password if password is not None else (
            "" if core.f_bool("confirm_closed") else None))
        s.commit()
        flash(f"{info.label} deleted.", "success")
        return redirect(core.safe_next(_list_url(info)))
    except BooksError as exc:
        s.rollback()
        flash(str(exc), "error")
        return redirect(url_for("txn.edit", slug=info.slug, txn_id=txn_id))


@bp.route("/t/<int:txn_id>/copy")
def copy(txn_id: int):
    txn = _load(txn_id)
    return redirect(url_for("txn.new", slug=txn.info.slug, copy_of=txn.id))


@bp.route("/t/<int:txn_id>/status", methods=["POST"])
def set_status(txn_id: int):
    txn = _load(txn_id)
    _require_edit(txn.type)
    s = core.db()
    new_status = core.f("status")
    if new_status not in txn.info.statuses:
        abort(400)
    before = audit.snapshot(txn)
    txn.status = new_status
    if txn.type == "purchase_order" and new_status == "closed":
        for ln in txn.lines:
            ln.closed = True
    if txn.type == "purchase_order" and new_status == "open":
        for ln in txn.lines:
            ln.closed = bool(ln.qty is not None and ln.received_qty is not None and ln.received_qty >= ln.qty)
    audit.record(s, core.current_user(), "update", "transaction", txn.id, before=before, after=audit.snapshot(txn),
                 txn=txn, summary=f"Marked {txn.info.label.lower()} {txn.number or ''} {new_status}")
    s.commit()
    flash(f"{txn.info.label} marked {new_status}.", "success")
    return redirect(url_for("txn.edit", slug=txn.info.slug, txn_id=txn.id))


@bp.route("/t/<int:txn_id>/history")
def history(txn_id: int):
    txn = _load(txn_id)
    s = core.db()
    entries = s.scalars(select(AuditLog).where(AuditLog.object_type == "transaction", AuditLog.object_id == txn.id)
                        .order_by(AuditLog.ts.desc())).all()
    rows = [(e, audit.changes(e.before, e.after)) for e in entries]
    return render_template("txn/history.html", txn=txn, rows=rows)


@bp.route("/t/<int:txn_id>/pdf")
def pdf(txn_id: int):
    txn = _load(txn_id)
    from pps_tools.books.services import pdf as pdf_service

    data = pdf_service.render_transaction(core.db(), txn, base_url=_base_url())
    disposition = "inline" if request.args.get("print") or request.args.get("inline") else "attachment"
    filename = pdf_service.filename_for(txn)
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'{disposition}; filename="{filename}"'})


@bp.route("/t/<int:txn_id>/check")
def print_check(txn_id: int):
    txn = _load(txn_id)
    if txn.type not in ("check", "bill_payment", "expense", "customer_refund"):
        abort(404)
    from pps_tools.books.services import pdf as pdf_service

    s = core.db()
    data = pdf_service.render_checks(s, [txn])
    if txn.print_later:
        txn.print_later = False
    from pps_tools.books.db import utcnow

    txn.printed_at = utcnow()
    s.commit()
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="check-{txn.number or txn.id}.pdf"'})


def _base_url() -> str:
    cfg = core.config()
    return (cfg.base_url or request.host_url).rstrip("/")


@bp.route("/t/<int:txn_id>/send", methods=["GET", "POST"])
def send(txn_id: int):
    txn = _load(txn_id)
    info = txn.info
    if not (info.customer_facing or info.vendor_facing):
        abort(404)
    from pps_tools.books.services import email as email_service

    s = core.db()
    if request.method == "POST":
        _require_edit(txn.type)
        try:
            email_service.send_transaction(s, core.config(), txn, to=core.f("to", ""), cc=core.f("cc"),
                                           bcc=core.f("bcc"), subject=core.f("subject", ""), body=core.f("body", ""),
                                           base_url=_base_url(), user=core.current_user(),
                                           attach_pdf=core.f_bool("attach_pdf"))
            s.commit()
            flash(f"{info.label} sent to {core.f('to')}.", "success")
        except BooksError as exc:
            s.rollback()
            flash(str(exc), "error")
            return redirect(url_for("txn.send", txn_id=txn.id))
        return redirect(url_for("txn.edit", slug=info.slug, txn_id=txn.id))
    draft = email_service.draft_for(s, txn, base_url=_base_url())
    s.commit()  # a public link token may have been created
    return render_template("txn/send.html", txn=txn, draft=draft)


@bp.route("/t/<int:txn_id>/link")
def share_link(txn_id: int):
    txn = _load(txn_id)
    if not txn.info.customer_facing:
        abort(404)
    tx.ensure_token(txn)
    core.db().commit()
    return jsonify({"url": f"{_base_url()}{url_for('public.view', token=txn.public_token)}"})


# -- JSON helpers for the forms ----------------------------------------------------------------


@bp.route("/ui/customer/<int:cid>")
def ui_customer(cid: int):
    s = core.db()
    c = s.get(Customer, cid)
    if c is None:
        abort(404)
    from pps_tools.books.services.transactions import _customer_bill_to

    ttype = request.args.get("type", "invoice")
    txn = s.get(Transaction, int(request.args["txn_id"])) if request.args.get("txn_id") else None
    data = {"email": c.email or "", "terms_id": c.terms_id, "billing_address": _customer_bill_to(c),
            "shipping_address": c.shipping_address(), "taxable": c.taxable,
            "tax_rate_id": c.default_tax_rate_id, "payment_method_id": c.payment_method_id,
            "notes": c.notes or "", "exempt_reason": c.tax_exemption_reason or ""}
    info = TXN_TYPES.get(ttype)
    if info is not None and info.applies_to and ttype != "deposit":
        rows = _apply_rows(s, info, txn, cid)
        data["targets"] = [_apply_json(r) for r in rows["targets"]]
        data["credits"] = [_apply_json(r) for r in rows["credits"]]
    if ttype == "invoice":
        data["billable"] = [{**b, "date": b["date"].isoformat(), "qty": str(b["qty"]) if b["qty"] is not None else "",
                             "rate": str(b["rate"]) if b["rate"] is not None else "",
                             "amount": money.fmt_plain(b["amount"])} for b in _billable_for(s, cid, txn)]
    return jsonify(data)


@bp.route("/ui/vendor/<int:vid>")
def ui_vendor(vid: int):
    s = core.db()
    v = s.get(Vendor, vid)
    if v is None:
        abort(404)
    ttype = request.args.get("type", "bill")
    txn = s.get(Transaction, int(request.args["txn_id"])) if request.args.get("txn_id") else None
    data = {"email": v.email or "", "terms_id": v.terms_id, "address": v.billing_address(),
            "default_account_id": v.default_expense_account_id}
    info = TXN_TYPES.get(ttype)
    if info is not None and info.applies_to and info.open_item == "ap":
        rows = _apply_rows(s, info, txn, vid)
        data["targets"] = [_apply_json(r) for r in rows["targets"]]
        data["credits"] = [_apply_json(r) for r in rows["credits"]]
    if ttype in ("bill", "check", "expense"):
        data["open_pos"] = [{"id": po.id, "number": po.number, "date": po.date.isoformat(),
                             "total": money.fmt(po.total_cents)}
                            for po in s.scalars(select(Transaction).where(
                                Transaction.type == "purchase_order", Transaction.vendor_id == vid,
                                Transaction.status == "open", Transaction.voided.is_(False)))]
    return jsonify(data)


def _apply_json(r: dict) -> dict:
    t = r["txn"]
    return {"id": t.id, "label": f"{t.info.label} #{t.number}" if t.number else t.info.label,
            "date": t.date.strftime("%m/%d/%Y"), "due": t.due_date.strftime("%m/%d/%Y") if t.due_date else "",
            "original": money.fmt_plain(t.total_cents), "open": money.fmt_plain(r["open"]),
            "applied": money.fmt_plain(r["applied"]) if r["applied"] else ""}


@bp.route("/ui/next-check/<int:account_id>")
def ui_next_check(account_id: int):
    acct = core.db().get(Account, account_id)
    if acct is None:
        abort(404)
    return jsonify({"number": str(acct.next_check_number or 1001) if acct.type == "bank" else ""})
