"""Global search: names, products, accounts and transactions (by number,
reference, memo, or amount)."""

from __future__ import annotations

import re

from flask import Blueprint, redirect, render_template, request, url_for
from sqlalchemy import or_, select

from pps_tools.books import money
from pps_tools.books.models import Account, Customer, Employee, Item, Transaction, TransactionLine, Vendor
from pps_tools.books.services import users as user_service
from pps_tools.books.web import core

bp = Blueprint("search", __name__)

_AMOUNT = re.compile(r"^\$?\s*-?[\d,]+(\.\d{1,2})?$")
LIMIT = 25


@bp.route("/search")
def index():
    s = core.db()
    user = core.current_user()
    needle = (request.args.get("q") or "").strip()
    results: dict[str, list] = {}
    if not needle:
        return render_template("search/index.html", q=needle, results=results, total=0)
    like = f"%{needle}%"
    if core.can("sales.view"):
        results["Customers"] = s.scalars(select(Customer).where(or_(
            Customer.display_name.ilike(like), Customer.company_name.ilike(like), Customer.email.ilike(like),
            Customer.phone.ilike(like), Customer.first_name.ilike(like), Customer.last_name.ilike(like)))
            .order_by(Customer.display_name).limit(LIMIT)).all()
        results["Products and services"] = s.scalars(select(Item).where(or_(
            Item.name.ilike(like), Item.sku.ilike(like), Item.description.ilike(like))).order_by(Item.name)
            .limit(LIMIT)).all()
    if core.can("purchases.view"):
        results["Vendors"] = s.scalars(select(Vendor).where(or_(
            Vendor.display_name.ilike(like), Vendor.company_name.ilike(like), Vendor.email.ilike(like),
            Vendor.account_number.ilike(like))).order_by(Vendor.display_name).limit(LIMIT)).all()
    if core.can("time.view"):
        results["Employees"] = s.scalars(select(Employee).where(or_(
            Employee.display_name.ilike(like), Employee.email.ilike(like))).order_by(Employee.display_name)
            .limit(LIMIT)).all()
    if core.can("accounting.view"):
        results["Accounts"] = s.scalars(select(Account).where(or_(
            Account.name.ilike(like), Account.number.ilike(like), Account.description.ilike(like)))
            .order_by(Account.name).limit(LIMIT)).all()

    conds = [Transaction.number.ilike(like), Transaction.ref_no.ilike(like), Transaction.memo.ilike(like),
             Transaction.stripe_payment_intent_id == needle, Transaction.stripe_charge_id == needle]
    line_match = select(TransactionLine.txn_id).where(TransactionLine.description.ilike(like))
    conds.append(Transaction.id.in_(line_match))
    if _AMOUNT.match(needle):
        try:
            amount = abs(money.cents(needle))
        except money.MoneyError:
            amount = None
        if amount:
            conds += [Transaction.total_cents == amount, Transaction.total_cents == -amount,
                      Transaction.balance_cents == amount]
    names = [c.id for c in results.get("Customers", [])]
    vendors = [v.id for v in results.get("Vendors", [])]
    if names:
        conds.append(Transaction.customer_id.in_(names))
    if vendors:
        conds.append(Transaction.vendor_id.in_(vendors))
    txns = [t for t in s.scalars(select(Transaction).where(or_(*conds))
                                 .order_by(Transaction.date.desc(), Transaction.id.desc()).limit(LIMIT * 4))
            if user_service.can_view_type(user, t.type)][:LIMIT * 2]
    results["Transactions"] = txns
    results = {k: v for k, v in results.items() if v}
    total = sum(len(v) for v in results.values())
    # One exact hit on a transaction number goes straight to it.
    exact = [t for t in txns if t.number and t.number.lower() == needle.lower()]
    if total == len(exact) == 1 and request.args.get("go") != "0":
        return redirect(url_for("txn.go", txn_id=exact[0].id))
    return render_template("search/index.html", q=needle, results=results, total=total)
