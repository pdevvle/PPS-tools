"""Projects: sub-customers flagged as projects, with job costing."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select

from pps_tools.books import money
from pps_tools.books.models import ACCOUNT_TYPES, Account, Customer, TimeActivity, Transaction, TransactionLine
from pps_tools.books.services import audit
from pps_tools.books.services.dates import parse_date
from pps_tools.books.services.errors import ValidationError
from pps_tools.books.services.reports.engine import Aggregator
from pps_tools.books.web import core

bp = Blueprint("projects", __name__)

STATUSES = {"not_started": "Not started", "in_progress": "In progress", "completed": "Completed",
            "canceled": "Canceled"}


def financials(s, projects: list[Customer]) -> dict[int, dict]:
    """Income, costs, labor cost and profit per project, plus what's unbilled and unpaid (accrual)."""
    ids = [p.id for p in projects]
    if not ids:
        return {}
    types = dict(s.execute(select(Account.id, Account.type)).all())
    out: dict[int, dict] = {pid: defaultdict(int) for pid in ids}
    for (aid, cid), v in Aggregator(s, "accrual").totals(None, None, "customer").items():
        if cid not in out:
            continue
        cls = ACCOUNT_TYPES[types[aid]].classification
        if cls == "income":
            out[cid]["income"] -= v
        elif cls == "expense":
            out[cid]["costs"] += v
    for ta in s.scalars(select(TimeActivity).where(TimeActivity.customer_id.in_(ids))):
        row = out[ta.customer_id]
        row["minutes"] += ta.minutes
        if ta.employee is not None and ta.employee.cost_rate is not None:
            row["labor"] += money.round_cents(ta.employee.cost_rate * Decimal(ta.minutes) / Decimal(60))
        if ta.billable and not ta.billed_txn_id:
            row["unbilled_time"] += money.line_amount(ta.hours, ta.hourly_rate or Decimal(0))
    for cid, bal in s.execute(select(Transaction.customer_id, func.sum(Transaction.balance_cents))
                              .where(Transaction.customer_id.in_(ids), Transaction.type == "invoice",
                                     Transaction.voided.is_(False)).group_by(Transaction.customer_id)):
        out[cid]["open_ar"] = int(bal or 0)
    for cid, amt in s.execute(select(TransactionLine.customer_id, func.sum(TransactionLine.amount_cents))
                              .join(Transaction, Transaction.id == TransactionLine.txn_id)
                              .where(TransactionLine.customer_id.in_(ids), TransactionLine.billable.is_(True),
                                     TransactionLine.billed_txn_id.is_(None), Transaction.voided.is_(False))
                              .group_by(TransactionLine.customer_id)):
        out[cid]["unbilled_expenses"] = int(amt or 0)
    for row in out.values():
        row["profit"] = row["income"] - row["costs"] - row["labor"]
        row["margin"] = (Decimal(row["profit"]) * 100 / row["income"]).quantize(Decimal("0.1")) if row["income"] else None
    return {k: dict(v) for k, v in out.items()}


@bp.route("/projects", methods=["GET", "POST"])
@core.requires("sales.view")
def index():
    s = core.db()
    if request.method == "POST":
        if not core.can("sales.edit"):
            abort(403)
        try:
            project = _create(s)
            s.commit()
        except ValidationError as exc:
            s.rollback()
            flash(str(exc), "error")
            return redirect(url_for("projects.index"))
        flash(f"Created project “{project.display_name}”.", "success")
        return redirect(url_for("projects.view", pid=project.id))
    q = select(Customer).where(Customer.is_project.is_(True))
    status = request.args.get("status", "open")
    if status == "open":
        q = q.where(or_(Customer.project_status.is_(None), Customer.project_status.in_(("not_started", "in_progress"))))
    elif status in STATUSES:
        q = q.where(Customer.project_status == status)
    needle = (request.args.get("q") or "").strip()
    if needle:
        q = q.where(Customer.display_name.ilike(f"%{needle}%"))
    projects = s.scalars(q.order_by(Customer.display_name)).all()
    fin = financials(s, projects)
    customers = s.scalars(select(Customer).where(Customer.active.is_(True), Customer.is_project.is_(False))
                          .order_by(Customer.display_name)).all()
    return render_template("projects/index.html", projects=projects, fin=fin, statuses=STATUSES, status=status,
                           customers=customers)


def _create(s) -> Customer:
    name = core.f("name") or ""
    parent_id = core.f_int("customer_id")
    parent = s.get(Customer, parent_id) if parent_id else None
    if not name:
        raise ValidationError("Name the project.", "name")
    if parent is None:
        raise ValidationError("Choose the customer the project is for.", "customer_id")
    if s.scalar(select(Customer.id).where(func.lower(Customer.display_name) == name.lower())):
        raise ValidationError("A customer or project already has that name. Project names have to be unique.", "name")
    p = Customer(display_name=name, parent_id=parent.id, bill_with_parent=True, is_project=True,
                 project_status="in_progress", email=parent.email, terms_id=parent.terms_id, taxable=parent.taxable,
                 default_tax_rate_id=parent.default_tax_rate_id, active=True,
                 bill_line1=parent.bill_line1, bill_line2=parent.bill_line2, bill_city=parent.bill_city,
                 bill_state=parent.bill_state, bill_postal=parent.bill_postal, bill_country=parent.bill_country)
    try:
        p.project_start = parse_date(core.f("project_start"))
        p.project_end = parse_date(core.f("project_end"))
    except ValueError:
        raise ValidationError("Check the project dates.") from None
    p.project_description = core.f("project_description") or None
    s.add(p)
    s.flush()
    audit.record(s, core.current_user(), "create", "customer", p.id, name=p.display_name,
                 summary=f"Created project {p.display_name} for {parent.display_name}")
    return p


@bp.route("/projects/<int:pid>", methods=["GET", "POST"])
@core.requires("sales.view")
def view(pid: int):
    s = core.db()
    project = s.get(Customer, pid) or abort(404)
    if not project.is_project:
        return redirect(url_for("names.customer", cid=pid))
    if request.method == "POST":
        if not core.can("sales.edit"):
            abort(403)
        try:
            name = core.f("name") or project.display_name
            dup = s.scalar(select(Customer.id).where(func.lower(Customer.display_name) == name.lower(),
                                                     Customer.id != project.id))
            if dup:
                raise ValidationError("A customer or project already has that name.", "name")
            project.display_name = name
            status = core.f("project_status")
            project.project_status = status if status in STATUSES else project.project_status
            project.project_start = parse_date(core.f("project_start"))
            project.project_end = parse_date(core.f("project_end"))
            project.project_description = core.f("project_description") or None
            project.active = project.project_status != "canceled" or core.f_bool("keep_active")
            audit.record(s, core.current_user(), "update", "customer", project.id, name=project.display_name,
                         summary=f"Updated project {project.display_name}")
            s.commit()
        except (ValidationError, ValueError) as exc:
            s.rollback()
            flash(str(exc) if isinstance(exc, ValidationError) else "Check the project dates.", "error")
            return redirect(url_for("projects.view", pid=pid))
        flash("Project saved.", "success")
        return redirect(url_for("projects.view", pid=pid))
    fin = financials(s, [project]).get(project.id, {})
    tab = request.args.get("tab", "transactions")
    txn_ids = set(s.scalars(select(Transaction.id).where(Transaction.customer_id == project.id)))
    txn_ids |= set(s.scalars(select(TransactionLine.txn_id).where(TransactionLine.customer_id == project.id)))
    txns = s.scalars(select(Transaction).where(Transaction.id.in_(txn_ids))
                     .order_by(Transaction.date.desc(), Transaction.id.desc()).limit(200)).all() if txn_ids else []
    time_rows = s.scalars(select(TimeActivity).where(TimeActivity.customer_id == project.id)
                          .order_by(TimeActivity.date.desc())).all()
    return render_template("projects/view.html", project=project, fin=fin, tab=tab, txns=txns, time_rows=time_rows,
                           statuses=STATUSES)
