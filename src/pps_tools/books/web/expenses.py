"""Expenses: all purchases, bills, pay bills, purchase orders."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from pps_tools.books import money
from pps_tools.books.models import Account, PaymentMethod, Transaction, Vendor
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.accounts import ordered_accounts
from pps_tools.books.services.errors import BooksError, ValidationError
from pps_tools.books.web import core
from pps_tools.books.web.sales import filtered_txns

bp = Blueprint("expenses", __name__)

EXPENSE_LIST_TYPES = ("expense", "check", "bill", "bill_payment", "vendor_credit", "cc_credit", "purchase_order",
                      "cc_payment")


def _vendors():
    return core.db().scalars(select(Vendor).where(Vendor.active.is_(True)).order_by(Vendor.display_name)).all()


@bp.route("/expenses")
@core.requires("purchases.view")
def index():
    rows, total, page, pages, sums = filtered_txns(EXPENSE_LIST_TYPES, party="vendor")
    return render_template("sales/list.html", rows=rows, total=total, page=page, pages=pages, sums=sums,
                           title="Expense transactions", types=EXPENSE_LIST_TYPES, party="vendor",
                           statuses=[("", "All statuses"), ("open", "Open"), ("overdue", "Overdue"), ("paid", "Paid"),
                                     ("voided", "Voided")], parties=_vendors())


@bp.route("/bills")
@core.requires("purchases.view")
def bills():
    rows, total, page, pages, sums = filtered_txns(("bill",), party="vendor")
    return render_template("sales/list.html", rows=rows, total=total, page=page, pages=pages, sums=sums,
                           title="Bills", types=None, fixed_type="bill", party="vendor",
                           statuses=[("", "All"), ("open", "Unpaid"), ("overdue", "Overdue"), ("partial", "Partially paid"),
                                     ("paid", "Paid"), ("voided", "Voided")], parties=_vendors())


@bp.route("/purchase-orders")
@core.requires("purchases.view")
def purchase_orders():
    rows, total, page, pages, sums = filtered_txns(("purchase_order",), party="vendor")
    return render_template("sales/list.html", rows=rows, total=total, page=page, pages=pages, sums=sums,
                           title="Purchase orders", types=None, fixed_type="purchase_order", party="vendor",
                           statuses=[("", "All"), ("open", "Open"), ("closed", "Closed")], parties=_vendors())


@bp.route("/bills/pay", methods=["GET", "POST"])
@core.requires("purchases.view")
def pay_bills():
    """Pay several bills at once: one bill payment (check) per vendor."""
    s = core.db()
    pay_accounts = [a for a in ordered_accounts(s, active_only=True, types=["bank", "credit_card"])]
    if request.method == "POST":
        if not core.can("purchases.edit"):
            abort(403)
        account_id = core.f_int("account_id")
        pay_date = core.f("date") or date.today().isoformat()
        start_check = core.f("starting_check")
        print_later = core.f_bool("print_later")
        method_id = core.f_int("payment_method_id")
        per_vendor: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for row in core.indexed_rows("b"):
            if row.get("pay") not in ("1", "on"):
                continue
            bill = s.get(Transaction, int(row["txn_id"]))
            amount = money.cents(row.get("amount") or "0")
            if bill is None or bill.type != "bill" or amount <= 0:
                continue
            per_vendor[bill.vendor_id].append((bill.id, amount))
        if not per_vendor:
            flash("Select at least one bill to pay.", "error")
            return redirect(url_for("expenses.pay_bills"))
        made = []
        try:
            acct = s.get(Account, account_id) if account_id else None
            if acct is None:
                raise ValidationError("Choose the account to pay from.")
            check_no = int(start_check) if (start_check or "").isdigit() else None
            for vendor_id, apps in sorted(per_vendor.items(), key=lambda kv: s.get(Vendor, kv[0]).display_name.lower()):
                data = {"type": "bill_payment", "vendor_id": vendor_id, "account_id": account_id, "date": pay_date,
                        "amount_cents": sum(a for _, a in apps), "payment_method_id": method_id,
                        "applications": [{"txn_id": b, "amount_cents": a} for b, a in apps],
                        "print_later": print_later}
                if acct.type == "bank" and check_no is not None and not print_later:
                    data["number"] = str(check_no)
                    check_no += 1
                made.append(tx.save(s, data, user=core.current_user()))
            s.commit()
        except BooksError as exc:
            s.rollback()
            flash(str(exc), "error")
            return redirect(url_for("expenses.pay_bills"))
        total = sum(t.total_cents for t in made)
        flash(f"Paid {money.fmt(total)} with {len(made)} bill payment{'s' if len(made) != 1 else ''}.", "success")
        if core.f("then") == "print" and acct.type == "bank":
            from pps_tools.books.services import pdf as pdf_service

            return Response(pdf_service.render_checks(s, made), mimetype="application/pdf",
                            headers={"Content-Disposition": 'inline; filename="checks.pdf"'})
        return redirect(url_for("expenses.bills", status="paid"))
    vendor_id = request.args.get("vendor_id", type=int)
    q = select(Transaction).where(Transaction.type == "bill", Transaction.balance_cents > 0,
                                  Transaction.voided.is_(False))
    if vendor_id:
        q = q.where(Transaction.vendor_id == vendor_id)
    due = request.args.get("due", "all")
    today = core.today()
    bills = s.scalars(q.order_by(Transaction.due_date, Transaction.date)).all()
    if due == "overdue":
        bills = [b for b in bills if b.due_date and b.due_date < today]
    elif due == "week":
        bills = [b for b in bills if b.due_date and (b.due_date - today).days <= 7]
    credits: dict[int, int] = defaultdict(int)
    for vc in s.scalars(select(Transaction).where(Transaction.type.in_(("vendor_credit", "bill_payment")),
                                                  Transaction.balance_cents > 0, Transaction.voided.is_(False))):
        credits[vc.vendor_id] += vc.balance_cents
    bank = next((a for a in pay_accounts if a.type == "bank" and a.system_key != "stripe_clearing"), None)
    methods = s.scalars(select(PaymentMethod).where(PaymentMethod.active.is_(True)).order_by(PaymentMethod.name)).all()
    return render_template("expenses/pay_bills.html", bills=bills, credits=credits, pay_accounts=pay_accounts,
                           default_account=bank, vendors=_vendors(), vendor_id=vendor_id, due=due, methods=methods)
