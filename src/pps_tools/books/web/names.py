"""Customers, vendors and employees."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select

from pps_tools.books import money
from pps_tools.books.models import (Account, Customer, Employee, LedgerEntry, PaymentMethod, Statement, TaxRate,
                                    Terms, TimeActivity, Transaction, User, Vendor)
from pps_tools.books.services import audit
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.accounts import ordered_accounts, system_account_id
from pps_tools.books.services.errors import BooksError, ValidationError
from pps_tools.books.web import core

bp = Blueprint("names", __name__)

PERSON_FIELDS = ["title", "first_name", "middle_name", "last_name", "suffix", "company_name", "email", "phone",
                 "mobile", "fax", "website", "notes", "bill_line1", "bill_line2", "bill_city", "bill_state",
                 "bill_postal", "bill_country"]


def _apply_person(obj, fields: list[str]) -> None:
    for name in fields:
        if name in request.form:
            setattr(obj, name, core.f(name) or None)


def _display_name(obj) -> str:
    name = core.f("display_name") or obj.company_name or " ".join(
        p for p in (obj.first_name, obj.last_name) if p) or ""
    if not name.strip():
        raise ValidationError("Enter a display name.", "display_name")
    return name.strip()


def _unique(model, name: str, current_id: Optional[int]) -> None:
    dup = core.db().scalar(select(model.id).where(func.lower(model.display_name) == name.lower(),
                                                  model.id != (current_id or 0)))
    if dup:
        raise ValidationError(f"“{name}” is already used. Display names must be unique.", "display_name")


def _balances(kind: str) -> dict[int, int]:
    s = core.db()
    acct_type = "ar" if kind == "customer" else "ap"
    ids = list(s.scalars(select(Account.id).where(Account.type == acct_type)))
    col = LedgerEntry.customer_id if kind == "customer" else LedgerEntry.vendor_id
    sign = 1 if kind == "customer" else -1
    return {pid: sign * int(v or 0) for pid, v in s.execute(
        select(col, func.sum(LedgerEntry.amount_cents)).where(LedgerEntry.account_id.in_(ids), col.isnot(None))
        .group_by(col))}


def _overdue(kind: str) -> dict[int, int]:
    s = core.db()
    ttype = "invoice" if kind == "customer" else "bill"
    col = Transaction.customer_id if kind == "customer" else Transaction.vendor_id
    return {pid: int(v or 0) for pid, v in s.execute(
        select(col, func.sum(Transaction.balance_cents)).where(
            Transaction.type == ttype, Transaction.balance_cents > 0, Transaction.due_date < core.today(),
            Transaction.voided.is_(False)).group_by(col))}


def _opening_balance(party, kind: str) -> None:
    """Opening balance for a new name: an invoice or bill dated as of the balance date."""
    amount = money.cents(core.f("opening_balance") or "0")
    if not amount:
        return
    as_of = core.f("opening_balance_date") or date.today().isoformat()
    obe = system_account_id(core.db(), "opening_balance_equity")
    if kind == "customer":
        tx.save(core.db(), {"type": "invoice", "customer_id": party.id, "date": as_of, "due_date": as_of,
                            "message": "", "apply_credits": False,
                            "lines": [{"kind": "item", "account_id": obe, "description": "Opening balance",
                                       "amount_cents": amount}]}, user=core.current_user())
    else:
        tx.save(core.db(), {"type": "bill", "vendor_id": party.id, "date": as_of, "due_date": as_of,
                            "lines": [{"kind": "account", "account_id": obe, "description": "Opening balance",
                                       "amount_cents": amount}]}, user=core.current_user())


# -- customers -----------------------------------------------------------------------------


@bp.route("/customers")
@core.requires("sales.view")
def customers():
    s = core.db()
    q = select(Customer)
    show = request.args.get("show", "active")
    if show == "active":
        q = q.where(Customer.active.is_(True))
    elif show == "inactive":
        q = q.where(Customer.active.is_(False))
    needle = (request.args.get("q") or "").strip()
    if needle:
        like = f"%{needle}%"
        q = q.where(or_(Customer.display_name.ilike(like), Customer.company_name.ilike(like),
                        Customer.email.ilike(like), Customer.phone.ilike(like)))
    rows = s.scalars(q.order_by(Customer.display_name)).all()
    bals = _balances("customer")
    overdue = _overdue("customer")
    filt = request.args.get("filter")
    if filt == "overdue":
        rows = [c for c in rows if overdue.get(c.id)]
    elif filt == "open":
        rows = [c for c in rows if bals.get(c.id)]
    totals = {"open": sum(v for v in bals.values() if v > 0), "overdue": sum(overdue.values()),
              "count_open": sum(1 for v in bals.values() if v > 0), "count_overdue": len(overdue)}
    return render_template("names/customers.html", rows=rows, bals=bals, overdue=overdue, show=show, totals=totals)


@bp.route("/customers/new", methods=["GET", "POST"])
@core.requires("lists.edit")
def customer_new():
    return _customer_form(Customer(active=True, taxable=True, ship_same_as_bill=True, preferred_delivery="email"))


@bp.route("/customers/<int:cid>/edit", methods=["GET", "POST"])
@core.requires("lists.edit")
def customer_edit(cid: int):
    c = core.db().get(Customer, cid) or abort(404)
    return _customer_form(c)


def _customer_form(c: Customer):
    s = core.db()
    if request.method == "POST":
        is_new = c.id is None
        try:
            _apply_person(c, PERSON_FIELDS + ["cc_email", "bcc_email", "ship_line1", "ship_line2", "ship_city",
                                              "ship_state", "ship_postal", "ship_country", "tax_exemption_reason",
                                              "resale_number", "project_description"])
            c.display_name = _display_name(c)
            _unique(Customer, c.display_name, c.id)
            c.ship_same_as_bill = core.f_bool("ship_same_as_bill")
            c.terms_id = core.f_int("terms_id")
            c.payment_method_id = core.f_int("payment_method_id")
            c.preferred_delivery = core.f("preferred_delivery") or "email"
            c.taxable = not core.f_bool("tax_exempt")
            c.default_tax_rate_id = core.f_int("default_tax_rate_id")
            parent_id = core.f_int("parent_id")
            if parent_id and parent_id == c.id:
                raise ValidationError("A customer can't be its own parent.", "parent_id")
            c.parent_id = parent_id
            c.bill_with_parent = core.f_bool("bill_with_parent") and bool(parent_id)
            c.autopay = core.f_bool("autopay") and bool(c.stripe_payment_method_id)
            if is_new:
                s.add(c)
            s.flush()
            if is_new:
                _opening_balance(c, "customer")
            audit.record(s, core.current_user(), "create" if is_new else "update", "customer", c.id,
                         summary=f"{'Added' if is_new else 'Updated'} customer {c.display_name}", name=c.display_name)
            s.commit()
        except BooksError as exc:
            s.rollback()
            flash(str(exc), "error")
            return _render_customer_form(c, request.form), 422
        flash(f"Customer {c.display_name} saved.", "success")
        nxt = request.args.get("next")
        if nxt and nxt.startswith("/"):
            sep = "&" if "?" in nxt else "?"
            return redirect(f"{nxt}{sep}customer_id={c.id}")
        return redirect(url_for("names.customer", cid=c.id))
    return _render_customer_form(c, None)


def _render_customer_form(c: Customer, form):
    s = core.db()
    return render_template(
        "names/customer_form.html", c=c, form=form,
        terms=s.scalars(select(Terms).where(Terms.active.is_(True)).order_by(Terms.due_days)).all(),
        methods=s.scalars(select(PaymentMethod).where(PaymentMethod.active.is_(True)).order_by(PaymentMethod.name)).all(),
        rates=s.scalars(select(TaxRate).where(TaxRate.active.is_(True)).order_by(TaxRate.name)).all(),
        parents=s.scalars(select(Customer).where(Customer.active.is_(True), Customer.id != (c.id or 0))
                          .order_by(Customer.display_name)).all())


@bp.route("/customers/<int:cid>")
@core.requires("sales.view")
def customer(cid: int):
    s = core.db()
    c = s.get(Customer, cid) or abort(404)
    from pps_tools.books.services.reports.engine import customer_scope

    scope = customer_scope(s, cid)
    tab = request.args.get("tab", "transactions")
    q = select(Transaction).where(Transaction.customer_id.in_(scope))
    ttype = request.args.get("type")
    if ttype:
        q = q.where(Transaction.type == ttype)
    status = request.args.get("status")
    if status == "open":
        q = q.where(Transaction.balance_cents > 0)
    total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
    page, offset, pages = core.paginate(total, 50)
    txns = s.scalars(q.order_by(Transaction.date.desc(), Transaction.id.desc()).offset(offset).limit(50)).all()
    bal = sum(_balances("customer").get(i, 0) for i in scope)
    overdue = sum(_overdue("customer").get(i, 0) for i in scope)
    statements = s.scalars(select(Statement).where(Statement.customer_id == cid)
                           .order_by(Statement.statement_date.desc()).limit(20)).all()
    unbilled_time = s.scalar(select(func.count(TimeActivity.id)).where(
        TimeActivity.customer_id.in_(scope), TimeActivity.billable.is_(True), TimeActivity.billed_txn_id.is_(None))) or 0
    from pps_tools.books.services import attachments as attach_service

    return render_template("names/customer.html", c=c, txns=txns, page=page, pages=pages, total=total, balance=bal,
                           overdue=overdue, tab=tab, statements=statements, unbilled_time=unbilled_time,
                           attachments=attach_service.for_object(s, "customer", c.id),
                           children=s.scalars(select(Customer).where(Customer.parent_id == cid)).all())


@bp.route("/customers/<int:cid>/active", methods=["POST"])
@core.requires("lists.edit")
def customer_active(cid: int):
    s = core.db()
    c = s.get(Customer, cid) or abort(404)
    make_active = core.f_bool("active")
    if not make_active:
        bal = _balances("customer").get(cid, 0)
        if bal:
            flash(f"{c.display_name} still has a balance of {money.fmt(bal)}. Settle it before making them inactive.",
                  "error")
            return redirect(url_for("names.customer", cid=cid))
    c.active = make_active
    audit.record(s, core.current_user(), "update", "customer", c.id, name=c.display_name,
                 summary=f"{'Reactivated' if make_active else 'Made inactive'} customer {c.display_name}")
    s.commit()
    flash(f"{c.display_name} is now {'active' if make_active else 'inactive'}.", "success")
    return redirect(url_for("names.customer", cid=cid))


@bp.route("/customers/<int:cid>/portal", methods=["POST"])
@core.requires("sales.edit")
def customer_portal(cid: int):
    s = core.db()
    c = s.get(Customer, cid) or abort(404)
    if not c.portal_token:
        c.portal_token = tx.new_token()
    s.commit()
    base = (core.config().base_url or request.host_url).rstrip("/")
    flash(f"Customer portal link: {base}{url_for('public.portal', token=c.portal_token)}", "info")
    return redirect(url_for("names.customer", cid=cid))


# -- vendors -------------------------------------------------------------------------------


@bp.route("/vendors")
@core.requires("purchases.view")
def vendors():
    s = core.db()
    q = select(Vendor)
    show = request.args.get("show", "active")
    if show == "active":
        q = q.where(Vendor.active.is_(True))
    elif show == "inactive":
        q = q.where(Vendor.active.is_(False))
    needle = (request.args.get("q") or "").strip()
    if needle:
        like = f"%{needle}%"
        q = q.where(or_(Vendor.display_name.ilike(like), Vendor.company_name.ilike(like), Vendor.email.ilike(like)))
    rows = s.scalars(q.order_by(Vendor.display_name)).all()
    bals = _balances("vendor")
    overdue = _overdue("vendor")
    if request.args.get("filter") == "overdue":
        rows = [v for v in rows if overdue.get(v.id)]
    elif request.args.get("filter") == "open":
        rows = [v for v in rows if bals.get(v.id)]
    elif request.args.get("filter") == "1099":
        rows = [v for v in rows if v.track_1099]
    totals = {"open": sum(v for v in bals.values() if v > 0), "overdue": sum(overdue.values())}
    return render_template("names/vendors.html", rows=rows, bals=bals, overdue=overdue, show=show, totals=totals)


@bp.route("/vendors/new", methods=["GET", "POST"])
@core.requires("lists.edit")
def vendor_new():
    return _vendor_form(Vendor(active=True))


@bp.route("/vendors/<int:vid>/edit", methods=["GET", "POST"])
@core.requires("lists.edit")
def vendor_edit(vid: int):
    v = core.db().get(Vendor, vid) or abort(404)
    return _vendor_form(v)


def _vendor_form(v: Vendor):
    s = core.db()
    if request.method == "POST":
        is_new = v.id is None
        try:
            _apply_person(v, PERSON_FIELDS + ["cc_email", "account_number"])
            v.display_name = _display_name(v)
            _unique(Vendor, v.display_name, v.id)
            v.terms_id = core.f_int("terms_id")
            v.default_expense_account_id = core.f_int("default_expense_account_id")
            v.track_1099 = core.f_bool("track_1099")
            v.w9_on_file = core.f_bool("w9_on_file")
            tin = core.f("tax_id")
            if tin and "•" not in tin:
                v.tax_id = tin
            if is_new:
                s.add(v)
            s.flush()
            if is_new:
                _opening_balance(v, "vendor")
            audit.record(s, core.current_user(), "create" if is_new else "update", "vendor", v.id,
                         summary=f"{'Added' if is_new else 'Updated'} vendor {v.display_name}", name=v.display_name)
            s.commit()
        except BooksError as exc:
            s.rollback()
            flash(str(exc), "error")
            return _render_vendor_form(v), 422
        flash(f"Vendor {v.display_name} saved.", "success")
        nxt = request.args.get("next")
        if nxt and nxt.startswith("/"):
            sep = "&" if "?" in nxt else "?"
            return redirect(f"{nxt}{sep}vendor_id={v.id}&payee=vendor:{v.id}")
        return redirect(url_for("names.vendor", vid=v.id))
    return _render_vendor_form(v)


def _render_vendor_form(v: Vendor):
    s = core.db()
    return render_template(
        "names/vendor_form.html", v=v,
        terms=s.scalars(select(Terms).where(Terms.active.is_(True)).order_by(Terms.due_days)).all(),
        accounts=[a for a in ordered_accounts(s, active_only=True) if a.type in ("expense", "cogs", "other_expense",
                                                                                  "other_current_asset", "fixed_asset")])


@bp.route("/vendors/<int:vid>")
@core.requires("purchases.view")
def vendor(vid: int):
    s = core.db()
    v = s.get(Vendor, vid) or abort(404)
    q = select(Transaction).where(Transaction.vendor_id == vid)
    ttype = request.args.get("type")
    if ttype:
        q = q.where(Transaction.type == ttype)
    total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
    page, offset, pages = core.paginate(total, 50)
    txns = s.scalars(q.order_by(Transaction.date.desc(), Transaction.id.desc()).offset(offset).limit(50)).all()
    year = core.today().year
    from pps_tools.books.services.reports.other import payments_1099

    paid_1099 = sum(a for rows in payments_1099(s, date(year, 1, 1), date(year, 12, 31)).get(vid, {}).values()
                    for _, a, _ in rows) if v.track_1099 else 0
    from pps_tools.books.services import attachments as attach_service

    return render_template("names/vendor.html", v=v, txns=txns, page=page, pages=pages, total=total,
                           balance=_balances("vendor").get(vid, 0), overdue=_overdue("vendor").get(vid, 0),
                           paid_1099=paid_1099, year=year, attachments=attach_service.for_object(s, "vendor", v.id))


@bp.route("/vendors/<int:vid>/active", methods=["POST"])
@core.requires("lists.edit")
def vendor_active(vid: int):
    s = core.db()
    v = s.get(Vendor, vid) or abort(404)
    make_active = core.f_bool("active")
    if not make_active and _balances("vendor").get(vid, 0):
        flash(f"You still owe {v.display_name} money. Pay or credit it before making them inactive.", "error")
        return redirect(url_for("names.vendor", vid=vid))
    v.active = make_active
    audit.record(s, core.current_user(), "update", "vendor", v.id, name=v.display_name,
                 summary=f"{'Reactivated' if make_active else 'Made inactive'} vendor {v.display_name}")
    s.commit()
    flash(f"{v.display_name} is now {'active' if make_active else 'inactive'}.", "success")
    return redirect(url_for("names.vendor", vid=vid))


# -- employees -----------------------------------------------------------------------------


@bp.route("/employees")
@core.requires("time.view")
def employees():
    s = core.db()
    show = request.args.get("show", "active")
    q = select(Employee)
    if show == "active":
        q = q.where(Employee.active.is_(True))
    rows = s.scalars(q.order_by(Employee.display_name)).all()
    return render_template("names/employees.html", rows=rows, show=show)


@bp.route("/employees/new", methods=["GET", "POST"])
@core.requires("lists.edit")
def employee_new():
    return _employee_form(Employee(active=True))


@bp.route("/employees/<int:eid>", methods=["GET", "POST"])
@core.requires("time.view")
def employee(eid: int):
    e = core.db().get(Employee, eid) or abort(404)
    if request.method == "POST" and not core.can("lists.edit"):
        abort(403)
    return _employee_form(e)


def _employee_form(e: Employee):
    s = core.db()
    if request.method == "POST":
        is_new = e.id is None
        try:
            _apply_person(e, PERSON_FIELDS + ["employee_number", "ssn_last4"])
            e.display_name = _display_name(e)
            _unique(Employee, e.display_name, e.id)
            from pps_tools.books.services.dates import parse_date

            e.hire_date = parse_date(core.f("hire_date")) if core.f("hire_date") else None
            e.release_date = parse_date(core.f("release_date")) if core.f("release_date") else None
            e.billable_rate = money.to_decimal(core.f("billable_rate"), None)
            e.cost_rate = money.to_decimal(core.f("cost_rate"), None)
            e.user_id = core.f_int("user_id")
            e.active = core.f_bool("active") if not is_new else True
            if e.ssn_last4 and (len(e.ssn_last4) != 4 or not e.ssn_last4.isdigit()):
                raise ValidationError("Enter only the last four digits of the SSN.", "ssn_last4")
            if is_new:
                s.add(e)
            s.flush()
            audit.record(s, core.current_user(), "create" if is_new else "update", "employee", e.id,
                         summary=f"{'Added' if is_new else 'Updated'} employee {e.display_name}", name=e.display_name)
            s.commit()
        except (BooksError, money.MoneyError, ValueError) as exc:
            s.rollback()
            flash(str(exc), "error")
            return _render_employee(e), 422
        flash(f"Employee {e.display_name} saved.", "success")
        return redirect(url_for("names.employee", eid=e.id))
    return _render_employee(e)


def _render_employee(e: Employee):
    s = core.db()
    time_rows = []
    if e.id:
        time_rows = s.scalars(select(TimeActivity).where(TimeActivity.employee_id == e.id)
                              .order_by(TimeActivity.date.desc()).limit(25)).all()
    return render_template("names/employee.html", e=e, time_rows=time_rows,
                           users=s.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all())
