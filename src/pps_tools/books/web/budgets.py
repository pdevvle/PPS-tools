"""Budgets: a grid of P&L accounts by fiscal month, optionally split by
customer, class or location."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select

from pps_tools.books.models import Budget, BudgetLine, Customer, Location, TrackingClass
from pps_tools.books.money import MoneyError, cents, percent_of
from pps_tools.books.services import audit
from pps_tools.books.services import dates as D
from pps_tools.books.services.accounts import ordered_accounts
from pps_tools.books.services.errors import ValidationError
from pps_tools.books.services.reports.engine import Aggregator
from pps_tools.books.web import core

bp = Blueprint("budgets", __name__)

PL_TYPES = ["income", "cogs", "expense", "other_income", "other_expense"]
CREDIT_NORMAL = ("income", "other_income")
SUBDIVISIONS = {"none": "Don't subdivide", "customer": "Customer", "class": "Class", "location": "Location"}
_SUB_MODELS = {"customer": Customer, "class": TrackingClass, "location": Location}


def _months(budget: Budget) -> list[tuple[date, date, str]]:
    start = date(budget.fiscal_year, core.company().fiscal_year_start_month, 1)
    out = []
    for i in range(12):
        a = D.add_months(start, i)
        out.append((a, D.month_end(a), a.strftime("%b")))
    return out


def _subdivisions(s, kind: str) -> list:
    model = _SUB_MODELS.get(kind)
    if model is None:
        return []
    order = model.display_name if model is Customer else model.name
    return list(s.scalars(select(model).where(model.active.is_(True)).order_by(order)))


@bp.route("/budgets", methods=["GET", "POST"])
@core.requires("accounting.view")
def index():
    s = core.db()
    if request.method == "POST":
        if not core.can("accounting.edit"):
            abort(403)
        try:
            budget = _create(s)
            s.commit()
        except ValidationError as exc:
            s.rollback()
            flash(str(exc), "error")
            return redirect(url_for("budgets.index"))
        flash(f"Created budget “{budget.name}”.", "success")
        return redirect(url_for("budgets.edit", budget_id=budget.id))
    rows = s.scalars(select(Budget).order_by(Budget.fiscal_year.desc(), Budget.name)).all()
    totals = {}
    types = {a.id: a.type for a in ordered_accounts(s, types=PL_TYPES)}
    for b in rows:
        inc = exp = 0
        for bl in b.lines:
            if types.get(bl.account_id) in CREDIT_NORMAL:
                inc += bl.amount_cents
            else:
                exp += bl.amount_cents
        totals[b.id] = (inc, exp)
    this_fy = D.fiscal_year_start(core.today(), core.company().fiscal_year_start_month).year
    return render_template("budgets/index.html", rows=rows, totals=totals, subdivisions=SUBDIVISIONS,
                           years=[this_fy + 1, this_fy, this_fy - 1, this_fy - 2])


def _create(s) -> Budget:
    name = core.f("name") or ""
    if not name:
        raise ValidationError("Name the budget.", "name")
    if s.scalar(select(Budget.id).where(func.lower(Budget.name) == name.lower())):
        raise ValidationError("There's already a budget with that name.", "name")
    year = core.f_int("fiscal_year") or core.today().year
    sub = core.f("subdivide_by") if core.f("subdivide_by") in SUBDIVISIONS else "none"
    budget = Budget(name=name, fiscal_year=year, subdivide_by=sub, active=True)
    s.add(budget)
    s.flush()
    source = core.f("prefill") or "blank"
    if source == "actuals":
        _prefill_from_actuals(s, budget, core.f("adjust_pct") or "0")
    elif source.startswith("budget:") and source[7:].isdigit():
        other = s.get(Budget, int(source[7:]))
        if other is not None:
            same_split = other.subdivide_by == budget.subdivide_by
            for bl in other.lines:
                if bl.subdivision_id is not None and not same_split:
                    continue
                s.add(BudgetLine(budget_id=budget.id, account_id=bl.account_id, period=bl.period,
                                 subdivision_id=bl.subdivision_id if same_split else None,
                                 amount_cents=bl.amount_cents))
    audit.record(s, core.current_user(), "create", "budget", budget.id, name=budget.name,
                 summary=f"Created budget {budget.name} for fiscal {year}")
    return budget


def _prefill_from_actuals(s, budget: Budget, adjust: str) -> None:
    """Last fiscal year's actual amounts, month by month, optionally up or down a percent."""
    try:
        pct = Decimal(str(adjust).strip().rstrip("%") or "0")
    except InvalidOperation:
        raise ValidationError("The adjustment has to be a percent, like 5 or -10.", "adjust_pct") from None
    types = {a.id: a.type for a in ordered_accounts(s, types=PL_TYPES)}
    dim = budget.subdivide_by if budget.subdivide_by != "none" else None
    agg = Aggregator(s, core.company().accounting_method or "accrual")
    for i, (start, end, _) in enumerate(_months(budget)):
        prior_start, prior_end = D.add_months(start, -12), D.month_end(D.add_months(start, -12))
        for (account_id, dim_value), amount in agg.totals(prior_start, prior_end, dim).items():
            if account_id not in types or not amount:
                continue
            if dim and dim_value is None:
                continue
            value = -amount if types[account_id] in CREDIT_NORMAL else amount
            value += percent_of(value, pct)
            if value:
                s.add(BudgetLine(budget_id=budget.id, account_id=account_id, period=i + 1,
                                 subdivision_id=dim_value if dim else None, amount_cents=value))
    s.flush()


@bp.route("/budgets/<int:budget_id>", methods=["GET", "POST"])
@core.requires("accounting.view")
def edit(budget_id: int):
    s = core.db()
    budget = s.get(Budget, budget_id) or abort(404)
    subs = _subdivisions(s, budget.subdivide_by)
    sub_id = request.values.get("sub", type=int) if budget.subdivide_by != "none" else None
    if budget.subdivide_by != "none" and sub_id is None and subs:
        sub_id = subs[0].id
    if request.method == "POST":
        if not core.can("accounting.edit"):
            abort(403)
        try:
            _save_grid(s, budget, sub_id)
            budget.name = core.f("name") or budget.name
            budget.active = core.f_bool("active")
            audit.record(s, core.current_user(), "update", "budget", budget.id, name=budget.name,
                         summary=f"Updated budget {budget.name}")
            s.commit()
        except ValidationError as exc:
            s.rollback()
            flash(str(exc), "error")
            return redirect(url_for("budgets.edit", budget_id=budget.id, sub=sub_id))
        flash("Budget saved.", "success")
        return redirect(url_for("budgets.edit", budget_id=budget.id, sub=sub_id))
    accounts = ordered_accounts(s, active_only=True, types=PL_TYPES)
    grid: dict[int, list[int]] = defaultdict(lambda: [0] * 12)
    for bl in budget.lines:
        if bl.subdivision_id == sub_id:
            grid[bl.account_id][bl.period - 1] += bl.amount_cents
    sections = []
    for t, label in (("income", "Income"), ("cogs", "Cost of Goods Sold"), ("expense", "Expenses"),
                     ("other_income", "Other Income"), ("other_expense", "Other Expenses")):
        accts = [a for a in accounts if a.type == t]
        if accts:
            sections.append((label, accts))
    return render_template("budgets/edit.html", budget=budget, months=_months(budget), sections=sections,
                           grid=grid, subs=subs, sub_id=sub_id, subdivisions=SUBDIVISIONS,
                           credit_normal=CREDIT_NORMAL)


def _save_grid(s, budget: Budget, sub_id) -> None:
    values: dict[tuple[int, int], int] = {}
    for key, raw in request.form.items():
        if not key.startswith("b-"):
            continue
        try:
            _, account_id, period = key.split("-")
            account_id, period = int(account_id), int(period)
        except ValueError:
            continue
        if not 1 <= period <= 12:
            continue
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            amount = cents(raw)
        except MoneyError:
            raise ValidationError(f"“{raw}” isn't an amount.") from None
        if amount:
            values[(account_id, period)] = amount
    s.execute(sa_delete(BudgetLine).where(BudgetLine.budget_id == budget.id,
                                          BudgetLine.subdivision_id.is_(None) if sub_id is None
                                          else BudgetLine.subdivision_id == sub_id))
    for (account_id, period), amount in values.items():
        s.add(BudgetLine(budget_id=budget.id, account_id=account_id, period=period, subdivision_id=sub_id,
                         amount_cents=amount))
    s.flush()
    s.expire(budget, ["lines"])


@bp.route("/budgets/<int:budget_id>/delete", methods=["POST"])
@core.requires("accounting.edit")
def delete(budget_id: int):
    s = core.db()
    budget = s.get(Budget, budget_id) or abort(404)
    name = budget.name
    s.delete(budget)
    audit.record(s, core.current_user(), "delete", "budget", budget_id, name=name, summary=f"Deleted budget {name}")
    s.commit()
    flash(f"Deleted budget “{name}”.", "success")
    return redirect(url_for("budgets.index"))
