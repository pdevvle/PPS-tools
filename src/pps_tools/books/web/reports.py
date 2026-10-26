"""Reports: catalog, viewer, exports, saved customizations."""

from __future__ import annotations

import re

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from pps_tools.books.models import (Account, Budget, Customer, Employee, Item, Location, SavedReport, TaxAgency,
                                    TrackingClass, Vendor)
from pps_tools.books.services import prefs
from pps_tools.books.services import reports as report_service
from pps_tools.books.services.accounts import ordered_accounts
from pps_tools.books.services.dates import PERIOD_PRESETS
from pps_tools.books.services.reports import CATEGORIES, REGISTRY, Params
from pps_tools.books.services.reports.export import to_csv, to_pdf
from pps_tools.books.txn_types import TXN_TYPES
from pps_tools.books.web import core

bp = Blueprint("reports", __name__)


@bp.route("/reports")
@core.requires("reports.view")
def index():
    s = core.db()
    q = (request.args.get("q") or "").strip().lower()
    favorites = set(prefs.get(s, "favorite_reports") or ["profit_and_loss", "balance_sheet", "ar_aging_summary",
                                                         "sales_by_customer_summary", "expenses_by_vendor_summary"])
    groups = []
    for cat, label in CATEGORIES:
        if cat == "favorites":
            items = [REGISTRY[k] for k in favorites if k in REGISTRY]
        else:
            items = [r for r in REGISTRY.values() if r.category == cat]
        if q:
            items = [r for r in items if q in r.title.lower() or q in r.description.lower()]
        if items:
            groups.append((cat, label, sorted(items, key=lambda r: r.title)))
    saved = s.scalars(select(SavedReport).order_by(SavedReport.name)).all()
    return render_template("reports/index.html", groups=groups, saved=saved, q=q, favorites=favorites)


@bp.route("/reports/favorite/<key>", methods=["POST"])
@core.requires("reports.view")
def toggle_favorite(key: str):
    s = core.db()
    favs = list(prefs.get(s, "favorite_reports") or ["profit_and_loss", "balance_sheet", "ar_aging_summary",
                                                     "sales_by_customer_summary", "expenses_by_vendor_summary"])
    if key in favs:
        favs.remove(key)
    elif key in REGISTRY:
        favs.append(key)
    prefs.set_many(s, {"favorite_reports": favs})
    s.commit()
    return redirect(request.referrer or url_for("reports.index"))


def _params(key: str) -> Params:
    rdef = REGISTRY[key]
    company = core.company()
    defaults = {"preset": rdef.default_preset, "basis": prefs.get(core.db(), "report_basis") or company.accounting_method}
    return Params.from_args(request.args.to_dict(), defaults)


def _filter_choices():
    s = core.db()
    return {
        "customers": s.scalars(select(Customer).order_by(Customer.display_name)).all(),
        "vendors": s.scalars(select(Vendor).order_by(Vendor.display_name)).all(),
        "employees": s.scalars(select(Employee).order_by(Employee.display_name)).all(),
        "accounts": ordered_accounts(s),
        "classes": s.scalars(select(TrackingClass).order_by(TrackingClass.name)).all(),
        "locations": s.scalars(select(Location).order_by(Location.name)).all(),
        "items": s.scalars(select(Item).order_by(Item.name)).all(),
        "agencies": s.scalars(select(TaxAgency).order_by(TaxAgency.name)).all(),
        "budgets": s.scalars(select(Budget).order_by(Budget.fiscal_year.desc())).all(),
    }


@bp.route("/reports/<key>")
@core.requires("reports.view")
def view(key: str):
    if key not in REGISTRY:
        abort(404)
    rdef = REGISTRY[key]
    p = _params(key)
    report = report_service.run(core.db(), key, p, today=core.today())
    return render_template("reports/view.html", report=report, rdef=rdef, p=p, presets=PERIOD_PRESETS,
                           txn_types=TXN_TYPES, saved_id=request.args.get("saved"), **_filter_choices())


def _filename(report, ext: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", report.title).strip("-").lower()
    return f"{base}.{ext}"


@bp.route("/reports/<key>.csv")
@core.requires("reports.view")
def export_csv(key: str):
    if key not in REGISTRY:
        abort(404)
    report = report_service.run(core.db(), key, _params(key), today=core.today())
    return Response(to_csv(report), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{_filename(report, "csv")}"'})


@bp.route("/reports/<key>.pdf")
@core.requires("reports.view")
def export_pdf(key: str):
    if key not in REGISTRY:
        abort(404)
    report = report_service.run(core.db(), key, _params(key), today=core.today())
    disposition = "inline" if request.args.get("inline") else "attachment"
    return Response(to_pdf(report), mimetype="application/pdf",
                    headers={"Content-Disposition": f'{disposition}; filename="{_filename(report, "pdf")}"'})


@bp.route("/reports/<key>/save", methods=["POST"])
@core.requires("reports.view")
def save(key: str):
    if key not in REGISTRY:
        abort(404)
    s = core.db()
    name = core.f("name") or REGISTRY[key].title
    params = {k: v for k, v in request.form.items() if k not in ("_csrf", "name", "email_schedule", "email_to", "shared")
              and v not in ("", None)}
    saved = SavedReport(name=name, report_key=key, params=params, shared=core.f_bool("shared"),
                        email_schedule=core.f("email_schedule") or "none", email_to=core.f("email_to") or None,
                        created_by_id=core.current_user().id)
    s.add(saved)
    s.commit()
    flash(f"Saved “{name}” to your custom reports.", "success")
    return redirect(url_for("reports.saved", saved_id=saved.id))


@bp.route("/reports/saved/<int:saved_id>")
@core.requires("reports.view")
def saved(saved_id: int):
    sr = core.db().get(SavedReport, saved_id) or abort(404)
    return redirect(url_for("reports.view", key=sr.report_key, saved=sr.id, **sr.params))


@bp.route("/reports/saved/<int:saved_id>/delete", methods=["POST"])
@core.requires("reports.view")
def delete_saved(saved_id: int):
    s = core.db()
    sr = s.get(SavedReport, saved_id) or abort(404)
    s.delete(sr)
    s.commit()
    flash("Custom report deleted.", "success")
    return redirect(url_for("reports.index"))
