"""Taxes: the sales tax center, rates and agencies, and 1099 filing prep."""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from pps_tools.books.models import Customer, TaxAgency, TaxRate, Transaction, TransactionTaxLine, Vendor
from pps_tools.books.services import audit
from pps_tools.books.services import tax as tax_service
from pps_tools.books.services.errors import ValidationError
from pps_tools.books.services.reports.other import BOXES_1099, forms_needed, nec_threshold, payments_1099
from pps_tools.books.web import core

bp = Blueprint("tax", __name__)

FREQUENCIES = {"monthly": "Monthly", "quarterly": "Quarterly", "annually": "Yearly"}


# -- sales tax center ---------------------------------------------------------------------------


@bp.route("/taxes")
@core.requires("accounting.view")
def index():
    s = core.db()
    today = core.today()
    agencies = s.scalars(select(TaxAgency).where(TaxAgency.active.is_(True)).order_by(TaxAgency.name)).all()
    cards = []
    for ag in agencies:
        periods = []
        for start, end in tax_service.filing_periods(ag, today, count=4):
            rows = tax_service.liability_by_rate(s, start, end, agency_id=ag.id)
            owed_at_end = tax_service.agency_balance(s, ag.id, end)
            # Payments made after the period count against the oldest balance first.
            paid_after = tax_service.payments_to_agency(s, ag.id, end + timedelta(days=1), None)
            periods.append({
                "start": start, "end": end, "due": end + timedelta(days=20),
                "taxable": sum(r.taxable_cents for r in rows), "tax": sum(r.tax_cents for r in rows),
                "adjustments": tax_service.adjustments_for_agency(s, ag.id, start, end),
                "owed_at_end": owed_at_end, "unpaid": max(0, owed_at_end - paid_after),
                "open": end >= today,
            })
        payments = s.scalars(select(Transaction).where(Transaction.type == "sales_tax_payment",
                                                       Transaction.tax_agency_id == ag.id,
                                                       Transaction.voided.is_(False))
                             .order_by(Transaction.date.desc()).limit(5)).all()
        cards.append({"agency": ag, "owed": tax_service.agency_balance(s, ag.id), "periods": periods,
                      "payments": payments})
    rates_count = s.scalar(select(func.count(TaxRate.id)).where(TaxRate.active.is_(True))) or 0
    exempt = s.scalar(select(func.count(Customer.id)).where(Customer.taxable.is_(False),
                                                             Customer.active.is_(True))) or 0
    return render_template("tax/index.html", cards=cards, rates_count=rates_count, exempt=exempt,
                           frequencies=FREQUENCIES)


# -- rates and agencies ------------------------------------------------------------------------------


@bp.route("/taxes/rates", methods=["GET", "POST"])
@core.requires("accounting.view")
def rates():
    s = core.db()
    if request.method == "POST":
        if not core.can("accounting.edit"):
            abort(403)
        what = core.f("what")
        try:
            if what == "agency":
                _save_agency(s)
            elif what == "rate":
                _save_rate(s)
            elif what == "toggle_rate":
                rate = s.get(TaxRate, core.f_int("id")) or abort(404)
                rate.active = not rate.active
                audit.record(s, core.current_user(), "update", "tax_rate", rate.id, name=rate.name,
                             summary=f"{'Reactivated' if rate.active else 'Made inactive'} tax rate {rate.name}")
            elif what == "toggle_agency":
                ag = s.get(TaxAgency, core.f_int("id")) or abort(404)
                ag.active = not ag.active
                audit.record(s, core.current_user(), "update", "tax_agency", ag.id, name=ag.name,
                             summary=f"{'Reactivated' if ag.active else 'Made inactive'} agency {ag.name}")
            else:
                abort(400)
            s.commit()
        except ValidationError as exc:
            s.rollback()
            flash(str(exc), "error")
            return _render_rates(), 422
        flash("Saved.", "success")
        return redirect(url_for("tax.rates"))
    return _render_rates()


def _render_rates():
    s = core.db()
    agencies = s.scalars(select(TaxAgency).order_by(TaxAgency.active.desc(), TaxAgency.name)).all()
    all_rates = s.scalars(select(TaxRate).order_by(TaxRate.active.desc(), TaxRate.name)).all()
    used = dict(s.execute(select(TransactionTaxLine.tax_rate_id, func.count(func.distinct(TransactionTaxLine.txn_id)))
                          .group_by(TransactionTaxLine.tax_rate_id)).all())
    edit_agency = s.get(TaxAgency, request.args.get("agency", type=int)) if request.args.get("agency") else None
    edit_rate = s.get(TaxRate, request.args.get("rate", type=int)) if request.args.get("rate") else None
    return render_template("tax/rates.html", agencies=agencies, rates=all_rates, used=used,
                           single_rates=[r for r in all_rates if not r.is_combined and r.active],
                           edit_agency=edit_agency, edit_rate=edit_rate, frequencies=FREQUENCIES)


def _save_agency(s) -> None:
    ag_id = core.f_int("id")
    ag = s.get(TaxAgency, ag_id) if ag_id else TaxAgency()
    if ag is None:
        abort(404)
    name = core.f("name") or ""
    if not name:
        raise ValidationError("Name the agency.", "name")
    dup = s.scalar(select(TaxAgency.id).where(func.lower(TaxAgency.name) == name.lower(), TaxAgency.id != (ag.id or 0)))
    if dup:
        raise ValidationError("There's already an agency with that name.", "name")
    ag.name = name
    ag.registration_number = core.f("registration_number") or None
    ag.filing_frequency = core.f("filing_frequency") if core.f("filing_frequency") in FREQUENCIES else "quarterly"
    ag.reporting_method = "cash" if core.f("reporting_method") == "cash" else "accrual"
    if ag.id is None:
        ag.active = True
        s.add(ag)
    s.flush()
    audit.record(s, core.current_user(), "update" if ag_id else "create", "tax_agency", ag.id, name=ag.name,
                 summary=f"{'Updated' if ag_id else 'Added'} tax agency {ag.name}")


def _save_rate(s) -> None:
    rate_id = core.f_int("id")
    rate = s.get(TaxRate, rate_id) if rate_id else TaxRate()
    if rate is None:
        abort(404)
    name = core.f("name") or ""
    if not name:
        raise ValidationError("Name the rate.", "name")
    dup = s.scalar(select(TaxRate.id).where(func.lower(TaxRate.name) == name.lower(), TaxRate.id != (rate.id or 0)))
    if dup:
        raise ValidationError("There's already a rate with that name.", "name")
    combined = core.f("kind") == "combined"
    if rate.id and rate.is_combined != combined and s.scalar(
            select(TransactionTaxLine.id).where(TransactionTaxLine.tax_rate_id == rate.id).limit(1)):
        raise ValidationError("A rate that's been charged can't switch between single and combined.")
    rate.name = name
    rate.description = core.f("description") or None
    rate.is_combined = combined
    if combined:
        ids = [int(x) for x in request.form.getlist("component_ids") if x.isdigit()]
        comps = [c for c in (s.get(TaxRate, i) for i in ids) if c is not None and not c.is_combined and c.id != rate.id]
        if len(comps) < 2:
            raise ValidationError("A combined rate needs at least two component rates.")
        rate.components = comps
        rate.rate = Decimal(0)
        rate.agency_id = None
    else:
        try:
            pct = Decimal((core.f("rate") or "").rstrip("%"))
        except InvalidOperation:
            raise ValidationError("Enter the rate as a percent, like 6.25.", "rate") from None
        if pct < 0 or pct > 100:
            raise ValidationError("The rate has to be between 0% and 100%.", "rate")
        if rate.id and pct != rate.rate and s.scalar(
                select(TransactionTaxLine.id).where(TransactionTaxLine.tax_rate_id == rate.id).limit(1)):
            raise ValidationError("This rate is on past sales. Make it inactive and add a new rate instead, "
                                  "so old invoices keep the rate they were charged.", "rate")
        agency_id = core.f_int("agency_id")
        if not agency_id or s.get(TaxAgency, agency_id) is None:
            raise ValidationError("Choose the agency the tax is paid to.", "agency_id")
        rate.rate = pct
        rate.agency_id = agency_id
        rate.components = []
    if rate.id is None:
        rate.active = True
        s.add(rate)
    s.flush()
    audit.record(s, core.current_user(), "update" if rate_id else "create", "tax_rate", rate.id, name=rate.name,
                 summary=f"{'Updated' if rate_id else 'Added'} tax rate {rate.name} ({rate.effective_rate}%)")


# -- 1099s ----------------------------------------------------------------------------------------


def _year() -> int:
    year = request.args.get("year", type=int)
    if year is None:
        # Forms are due January 31; through March (late filers, corrections) default to last year.
        today = core.today()
        year = today.year - 1 if today.month <= 3 else today.year
    return year


def _rows_1099(s, year: int) -> tuple[list[dict], int, list[str]]:
    start, end = date(year, 1, 1), date(year, 12, 31)
    data = payments_1099(s, start, end)
    threshold = nec_threshold(s, year)
    vendors = s.scalars(select(Vendor).where(Vendor.track_1099.is_(True)).order_by(Vendor.display_name)).all()
    rows = []
    for v in vendors:
        boxes = data.get(v.id, {})
        sums = {b: sum(a for _, a, _ in boxes.get(b, [])) for b in BOXES_1099}
        total = sum(sums.values())
        forms = forms_needed(sums, threshold)
        problems = []
        if forms and not v.tax_id:
            problems.append("No tax ID")
        if forms and not (v.bill_line1 and v.bill_city and v.bill_postal):
            problems.append("Incomplete address")
        if forms and not v.w9_on_file:
            problems.append("No W-9 on file")
        rows.append({"vendor": v, "sums": sums, "total": total, "forms": forms, "problems": problems})
    used = [b for b in BOXES_1099 if any(r["sums"][b] for r in rows)]
    return rows, threshold, used


@bp.route("/taxes/1099")
@core.requires("purchases.view")
def form_1099():
    s = core.db()
    year = _year()
    rows, threshold, used = _rows_1099(s, year)
    show = request.args.get("show", "needed")
    if show == "needed":
        visible = [r for r in rows if r["forms"]]
    elif show == "paid":
        visible = [r for r in rows if r["total"]]
    else:
        visible = rows
    untracked = s.scalars(
        select(Vendor).where(Vendor.track_1099.is_(False), Vendor.active.is_(True), Vendor.id.in_(
            select(Transaction.vendor_id).where(Transaction.type.in_(("check", "bill_payment", "expense")),
                                                Transaction.voided.is_(False),
                                                Transaction.date >= date(year, 1, 1),
                                                Transaction.date <= date(year, 12, 31))))
        .order_by(Vendor.display_name).limit(50)).all()
    return render_template("tax/form_1099.html", rows=visible, all_rows=rows, year=year, threshold=threshold,
                           used=used, boxes=BOXES_1099, show=show, untracked=untracked,
                           years=list(range(core.today().year, core.today().year - 6, -1)))


@bp.route("/taxes/1099.csv")
@core.requires("purchases.view")
def form_1099_csv():
    """One row per vendor that needs a form: what the IRS IRIS portal or a filing service asks for."""
    s = core.db()
    year = _year()
    rows, _, _ = _rows_1099(s, year)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Form", "Recipient name", "Business name", "TIN", "Address", "City", "State", "ZIP",
                "Email", "NEC Box 1", "MISC Box 1", "MISC Box 2", "MISC Box 3", "MISC Box 6", "MISC Box 10"])
    for r in rows:
        v = r["vendor"]
        for form in r["forms"]:
            amounts = [r["sums"]["NEC-1"] if form == "NEC" else 0] + [
                r["sums"][b] if form == "MISC" else 0 for b in ("MISC-1", "MISC-2", "MISC-3", "MISC-6", "MISC-10")]
            w.writerow([f"1099-{form}", v.contact_name or v.display_name, v.company_name or "", v.tax_id or "",
                        " ".join(p for p in (v.bill_line1, v.bill_line2) if p), v.bill_city or "",
                        v.bill_state or "", v.bill_postal or "", v.email or ""]
                       + [f"{a / 100:.2f}" if a else "" for a in amounts])
    audit.record(s, core.current_user(), "export", "form_1099", year, summary=f"Exported {year} 1099 data")
    s.commit()
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="1099-{year}.csv"'})


@bp.route("/taxes/1099/track", methods=["POST"])
@core.requires("lists.edit")
def track_1099():
    s = core.db()
    ids = [int(x) for x in request.form.getlist("vendor_ids") if x.isdigit()]
    for v in s.scalars(select(Vendor).where(Vendor.id.in_(ids))):
        v.track_1099 = True
        audit.record(s, core.current_user(), "update", "vendor", v.id, name=v.display_name,
                     summary=f"Tracked {v.display_name} for 1099s")
    s.commit()
    flash(f"Now tracking {len(ids)} vendor{'s' if len(ids) != 1 else ''} for 1099s.", "success")
    return redirect(url_for("tax.form_1099", year=request.form.get("year")))
