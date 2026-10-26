"""Home dashboard."""

from __future__ import annotations

from flask import Blueprint, render_template, request

from pps_tools.books.services import dashboard as dash
from pps_tools.books.services import dates as D
from pps_tools.books.web import charts, core

bp = Blueprint("dashboard", __name__)

PERIODS = [("this_month", "This month"), ("this_quarter", "This quarter"), ("this_year_to_date", "This year to date"),
           ("last_month", "Last month"), ("last_quarter", "Last quarter"), ("last_year", "Last year"),
           ("last_30_days", "Last 30 days"), ("last_90_days", "Last 90 days")]


@bp.route("/")
@bp.route("/dashboard")
def home():
    s = core.db()
    company = core.company()
    preset = request.args.get("period", "this_month")
    if preset not in dict(PERIODS):
        preset = "this_month"
    basis = request.args.get("basis") or company.accounting_method
    start, end = D.period_range(preset, core.today(), company.fiscal_year_start_month)
    snap = dash.build(s, start, end, basis, core.today())
    pl_chart = charts.column_chart(
        [m["label"] for m in snap.months],
        [{"name": "Income", "values": [m["income"] for m in snap.months], "slot": 1},
         {"name": "Expenses", "values": [m["expenses"] for m in snap.months], "slot": 2}],
        full_labels=[m["full"] for m in snap.months], title="Income and expenses, last six months")
    cash_chart = charts.line_chart(
        [{"label": p["label"], "full": f"{p['date']:%b %d, %Y}", "value": p["balance"]} for p in snap.cash_trend],
        title="Cash in bank accounts, month end")
    from flask import url_for

    cat_rows = [{"name": c["name"], "amount": c["amount"],
                 "href": url_for("reports.view", key="transaction_detail_by_account", account_id=c["account_id"],
                                 preset="custom", start=start.isoformat() if start else "",
                                 end=end.isoformat() if end else "") if c["account_id"] else None}
                for c in snap.expense_categories]
    return render_template("dashboard.html", snap=snap, periods=PERIODS, preset=preset, basis=basis,
                           pl_chart=pl_chart, cash_chart=cash_chart, cat_bars=charts.hbar_rows(cat_rows),
                           period_label=dict(PERIODS)[preset])
