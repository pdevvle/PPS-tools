"""Time tracking (single entries and a weekly timesheet) and the mileage log."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from pps_tools.books import money
from pps_tools.books.models import (Customer, Employee, Item, Location, MileageTrip, TimeActivity, TrackingClass,
                                    Vehicle, Vendor)
from pps_tools.books.services import audit, prefs
from pps_tools.books.services import mileage as mileage_service
from pps_tools.books.services.dates import PERIOD_PRESETS, parse_date, period_range
from pps_tools.books.services.errors import ValidationError
from pps_tools.books.web import core

bp = Blueprint("time", __name__)

_DURATION = re.compile(r"^\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*$", re.I)


def parse_duration(text: str) -> Optional[int]:
    """Minutes from '1:30', '1.5', '90m', '1h 30m' or '2h'. None for blank."""
    text = (text or "").strip().lower()
    if not text:
        return None
    if ":" in text:
        h, _, m = text.partition(":")
        if not (h.strip() or "0").isdigit() or not (m.strip() or "0").isdigit():
            raise ValidationError(f"“{text}” isn't a duration. Use hours:minutes, like 1:30.")
        minutes = int(m.strip() or 0)
        if minutes >= 60:
            raise ValidationError(f"“{text}” has more than 59 minutes.")
        return int(h.strip() or 0) * 60 + minutes
    m = _DURATION.match(text)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    try:
        hours = Decimal(text.rstrip("h"))
    except ArithmeticError:
        raise ValidationError(f"“{text}” isn't a duration. Use hours:minutes, like 1:30.") from None
    if hours < 0 or hours > 24 * 7:
        raise ValidationError(f"“{text}” is out of range.")
    return int((hours * 60).to_integral_value())


def fmt_minutes(minutes: Optional[int]) -> str:
    if not minutes:
        return ""
    return f"{minutes // 60}:{minutes % 60:02d}"


@bp.app_template_filter("hm")
def _hm(minutes) -> str:
    return fmt_minutes(minutes)


def _parse_time(text: str):
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p"):
        try:
            return datetime.strptime(text.upper(), fmt).time()
        except ValueError:
            continue
    raise ValidationError(f"“{text}” isn't a time of day.")


def _choices(s) -> dict:
    return {
        "employees": s.scalars(select(Employee).where(Employee.active.is_(True)).order_by(Employee.display_name)).all(),
        "vendors": s.scalars(select(Vendor).where(Vendor.active.is_(True)).order_by(Vendor.display_name)).all(),
        "customers": s.scalars(select(Customer).where(Customer.active.is_(True)).order_by(Customer.display_name)).all(),
        "services": s.scalars(select(Item).where(Item.active.is_(True), Item.type.in_(("service", "non_inventory")))
                              .order_by(Item.name)).all(),
        "classes": s.scalars(select(TrackingClass).where(TrackingClass.active.is_(True)).order_by(TrackingClass.name)).all(),
        "locations": s.scalars(select(Location).where(Location.active.is_(True)).order_by(Location.name)).all(),
    }


def _own_employee_id() -> Optional[int]:
    """Users with the time-only role only see and enter their own time."""
    user = core.current_user()
    if user is None or user.role != "time":
        return None
    emp = core.db().scalar(select(Employee).where(Employee.user_id == user.id))
    return emp.id if emp else -1


# -- list ---------------------------------------------------------------------------------------------


@bp.route("/time")
@core.requires("time.view")
def index():
    s = core.db()
    preset = request.args.get("preset", "this_month")
    start, end = period_range(preset, core.today(), core.company().fiscal_year_start_month)
    if preset == "custom":
        start = parse_date(request.args.get("start"), start)
        end = parse_date(request.args.get("end"), end)
    q = select(TimeActivity)
    if start:
        q = q.where(TimeActivity.date >= start)
    if end:
        q = q.where(TimeActivity.date <= end)
    worker = request.args.get("worker", "")
    own = _own_employee_id()
    if own is not None:
        worker = f"employee:{own}"
    if worker.startswith("employee:"):
        q = q.where(TimeActivity.employee_id == int(worker.split(":")[1]))
    elif worker.startswith("vendor:"):
        q = q.where(TimeActivity.vendor_id == int(worker.split(":")[1]))
    cust = request.args.get("customer_id", type=int)
    if cust:
        q = q.where(TimeActivity.customer_id == cust)
    status = request.args.get("status", "")
    if status == "unbilled":
        q = q.where(TimeActivity.billable.is_(True), TimeActivity.billed_txn_id.is_(None))
    elif status == "billed":
        q = q.where(TimeActivity.billed_txn_id.isnot(None))
    elif status == "nonbillable":
        q = q.where(TimeActivity.billable.is_(False))
    rows = s.scalars(q.order_by(TimeActivity.date.desc(), TimeActivity.id.desc())).all()
    total = sum(r.minutes for r in rows)
    billable = sum(r.minutes for r in rows if r.billable)
    unbilled_amount = sum(money.line_amount(r.hours, r.hourly_rate or Decimal(0)) for r in rows
                          if r.billable and not r.billed_txn_id)
    return render_template("time/index.html", rows=rows, total=total, billable=billable,
                           unbilled_amount=unbilled_amount, preset=preset, start=start, end=end, worker=worker,
                           status=status, presets=PERIOD_PRESETS, own=own, **_choices(s))


# -- single entries ---------------------------------------------------------------------------------


@bp.route("/time/new", methods=["GET", "POST"])
@core.requires("time.edit")
def new():
    s = core.db()
    ta = TimeActivity(date=core.today(), billable=bool(prefs.get(s, "time_billable_by_default")), minutes=0,
                      break_minutes=0, taxable=False)
    if request.args.get("employee_id", type=int):
        ta.employee_id = request.args.get("employee_id", type=int)
    if request.args.get("customer_id", type=int):
        ta.customer_id = request.args.get("customer_id", type=int)
    own = _own_employee_id()
    if own is not None:
        ta.employee_id = own
    return _form(ta)


@bp.route("/time/<int:ta_id>", methods=["GET", "POST"])
@core.requires("time.view")
def edit(ta_id: int):
    ta = core.db().get(TimeActivity, ta_id) or abort(404)
    own = _own_employee_id()
    if own is not None and ta.employee_id != own:
        abort(403)
    if request.method == "POST" and not core.can("time.edit"):
        abort(403)
    return _form(ta)


def _form(ta: TimeActivity):
    s = core.db()
    if request.method == "POST":
        if core.f("action") == "delete" and ta.id:
            return _delete(ta)
        is_new = ta.id is None
        try:
            if ta.billed_txn_id:
                raise ValidationError("This time is on an invoice already. Remove it from the invoice to change it.")
            _fill(s, ta)
            if is_new:
                ta.created_by_id = core.current_user().id
                s.add(ta)
            s.flush()
            audit.record(s, core.current_user(), "create" if is_new else "update", "time", ta.id,
                         name=ta.worker_name, summary=f"{'Added' if is_new else 'Updated'} {fmt_minutes(ta.minutes)} "
                                                      f"for {ta.worker_name} on {ta.date:%m/%d/%Y}")
            s.commit()
        except ValidationError as exc:
            s.rollback()
            flash(str(exc), "error")
            return render_template("time/form.html", ta=ta, form=request.form, **_choices(s)), 422
        flash("Time saved.", "success")
        if core.f("next_action") == "save_new":
            return redirect(url_for("time.new", employee_id=ta.employee_id or None))
        return redirect(core.safe_next(url_for("time.index")))
    return render_template("time/form.html", ta=ta, form=None, **_choices(s))


def _fill(s, ta: TimeActivity) -> None:
    worker = core.f("worker") or ""
    own = _own_employee_id()
    if own is not None:
        worker = f"employee:{own}"
    ta.employee_id = ta.vendor_id = None
    kind, _, wid = worker.partition(":")
    if kind == "employee" and wid.isdigit() and s.get(Employee, int(wid)):
        ta.employee_id = int(wid)
    elif kind == "vendor" and wid.isdigit() and s.get(Vendor, int(wid)):
        ta.vendor_id = int(wid)
    else:
        raise ValidationError("Choose who did the work.", "worker")
    try:
        ta.date = parse_date(core.f("date"), core.today())
    except ValueError:
        raise ValidationError("Enter the date.", "date") from None
    ta.customer_id = core.f_int("customer_id")
    ta.item_id = core.f_int("item_id")
    ta.class_id = core.f_int("class_id")
    ta.location_id = core.f_int("location_id")
    ta.description = core.f("description") or None
    ta.billable = core.f_bool("billable")
    ta.taxable = core.f_bool("taxable") and ta.billable
    if core.f("mode") == "range":
        ta.start_time = _parse_time(core.f("start_time"))
        ta.end_time = _parse_time(core.f("end_time"))
        if ta.start_time is None or ta.end_time is None:
            raise ValidationError("Enter both a start and an end time.", "start_time")
        ta.break_minutes = parse_duration(core.f("break")) or 0
        start = datetime.combine(ta.date, ta.start_time)
        end = datetime.combine(ta.date, ta.end_time)
        if end <= start:
            end += timedelta(days=1)  # an overnight shift
        ta.minutes = int((end - start).total_seconds() // 60) - ta.break_minutes
    else:
        ta.start_time = ta.end_time = None
        ta.break_minutes = 0
        ta.minutes = parse_duration(core.f("duration")) or 0
    if ta.minutes <= 0:
        raise ValidationError("Enter how long the work took.", "duration")
    if ta.minutes > 24 * 60:
        raise ValidationError("One entry can't be more than 24 hours.", "duration")
    if ta.billable:
        if not ta.customer_id:
            raise ValidationError("Billable time needs a customer.", "customer_id")
        rate = money.to_decimal(core.f("hourly_rate"), None)
        if rate is None:
            rate = _default_rate(s, ta)
        if rate is None or rate < 0:
            raise ValidationError("Enter the hourly rate to bill.", "hourly_rate")
        ta.hourly_rate = rate
    else:
        ta.hourly_rate = None


def _default_rate(s, ta: TimeActivity) -> Optional[Decimal]:
    if ta.item_id:
        item = s.get(Item, ta.item_id)
        if item is not None and item.sales_price is not None:
            return item.sales_price
    if ta.employee_id:
        emp = s.get(Employee, ta.employee_id)
        if emp is not None and emp.billable_rate is not None:
            return emp.billable_rate
    return None


def _delete(ta: TimeActivity):
    s = core.db()
    if ta.billed_txn_id:
        flash("This time is on an invoice. Remove it from the invoice first.", "error")
        return redirect(url_for("time.edit", ta_id=ta.id))
    audit.record(s, core.current_user(), "delete", "time", ta.id, name=ta.worker_name,
                 summary=f"Deleted {fmt_minutes(ta.minutes)} for {ta.worker_name} on {ta.date:%m/%d/%Y}")
    s.delete(ta)
    s.commit()
    flash("Time entry deleted.", "success")
    return redirect(url_for("time.index"))


# -- weekly timesheet ----------------------------------------------------------------------------------


@bp.route("/time/timesheet", methods=["GET", "POST"])
@core.requires("time.view")
def timesheet():
    s = core.db()
    own = _own_employee_id()
    worker = request.values.get("worker", "")
    if own is not None:
        worker = f"employee:{own}"
    try:
        anchor = parse_date(request.values.get("week"), core.today())
    except ValueError:
        anchor = core.today()
    week_start = anchor - timedelta(days=anchor.weekday())
    days = [week_start + timedelta(days=i) for i in range(7)]
    kind, _, wid = worker.partition(":")
    wid = int(wid) if wid.isdigit() else None
    if request.method == "POST":
        if not core.can("time.edit"):
            abort(403)
        if not wid:
            flash("Choose whose time this is.", "error")
            return redirect(url_for("time.timesheet", week=week_start.isoformat()))
        try:
            saved = _save_timesheet(s, kind, wid, days)
            s.commit()
        except ValidationError as exc:
            s.rollback()
            flash(str(exc), "error")
            return redirect(url_for("time.timesheet", worker=worker, week=week_start.isoformat()))
        flash(f"Timesheet saved ({saved} entr{'y' if saved == 1 else 'ies'}).", "success")
        return redirect(url_for("time.timesheet", worker=worker, week=week_start.isoformat()))
    rows = []
    if wid:
        q = select(TimeActivity).where(TimeActivity.date >= days[0], TimeActivity.date <= days[-1])
        q = q.where(TimeActivity.employee_id == wid) if kind == "employee" else q.where(TimeActivity.vendor_id == wid)
        grouped: dict[tuple, dict] = {}
        for ta in s.scalars(q.order_by(TimeActivity.date, TimeActivity.id)):
            key = (ta.customer_id, ta.item_id, ta.billable, ta.description or "")
            row = grouped.setdefault(key, {"customer_id": ta.customer_id, "item_id": ta.item_id,
                                           "billable": ta.billable, "description": ta.description or "",
                                           "cells": [None] * 7, "locked": False})
            i = (ta.date - days[0]).days
            if row["cells"][i] is not None:
                # Two entries on the same day for the same line: show them on their own row.
                key = key + (ta.id,)
                row = grouped.setdefault(key, {"customer_id": ta.customer_id, "item_id": ta.item_id,
                                               "billable": ta.billable, "description": ta.description or "",
                                               "cells": [None] * 7, "locked": False})
            row["cells"][i] = ta
            if ta.billed_txn_id:
                row["locked"] = True
        rows = list(grouped.values())
    blank_rows = max(3 - len(rows), 1)
    return render_template("time/timesheet.html", days=days, week_start=week_start, worker=worker, rows=rows,
                           blank_rows=blank_rows, own=own, prev_week=week_start - timedelta(days=7),
                           next_week=week_start + timedelta(days=7),
                           billable_default=bool(prefs.get(s, "time_billable_by_default")), **_choices(s))


def _save_timesheet(s, kind: str, wid: int, days: list[date]) -> int:
    if kind == "employee" and not s.get(Employee, wid) or kind == "vendor" and not s.get(Vendor, wid):
        raise ValidationError("Choose whose time this is.")
    saved = 0
    for row in core.indexed_rows("r", bools=("billable",)):
        customer_id = int(row["customer_id"]) if row.get("customer_id", "").isdigit() else None
        item_id = int(row["item_id"]) if row.get("item_id", "").isdigit() else None
        billable = row.get("billable", False)
        description = row.get("description") or None
        for i, day in enumerate(days):
            ta_id = row.get(f"id{i}")
            ta = s.get(TimeActivity, int(ta_id)) if ta_id and ta_id.isdigit() else None
            minutes = parse_duration(row.get(f"d{i}", ""))
            if ta is not None and ta.billed_txn_id:
                continue  # billed time is shown read-only
            if not minutes:
                if ta is not None:
                    s.delete(ta)
                continue
            if billable and not customer_id:
                raise ValidationError("Billable time needs a customer on its row.")
            if ta is None:
                ta = TimeActivity(date=day, created_by_id=core.current_user().id)
                s.add(ta)
            ta.employee_id = wid if kind == "employee" else None
            ta.vendor_id = wid if kind == "vendor" else None
            ta.date = day
            ta.customer_id, ta.item_id, ta.billable, ta.description = customer_id, item_id, billable, description
            ta.minutes = minutes
            ta.start_time = ta.end_time = None
            ta.break_minutes = 0
            if billable and ta.hourly_rate is None:
                ta.hourly_rate = _default_rate(s, ta)
                if ta.hourly_rate is None:
                    raise ValidationError("Set a billable rate on the employee or a price on the service "
                                          "before entering billable time on the timesheet.")
            if not billable:
                ta.hourly_rate = None
            saved += 1
    s.flush()
    audit.record(s, core.current_user(), "update", "timesheet", wid,
                 summary=f"Saved timesheet for the week of {days[0]:%m/%d/%Y}")
    return saved


# -- mileage -----------------------------------------------------------------------------------------------


@bp.route("/mileage")
@core.requires("time.view")
def mileage():
    s = core.db()
    preset = request.args.get("preset", "this_year")
    start, end = period_range(preset, core.today(), core.company().fiscal_year_start_month)
    if preset == "custom":
        start = parse_date(request.args.get("start"), start)
        end = parse_date(request.args.get("end"), end)
    q = select(MileageTrip)
    if start:
        q = q.where(MileageTrip.date >= start)
    if end:
        q = q.where(MileageTrip.date <= end)
    vehicle_id = request.args.get("vehicle_id", type=int)
    if vehicle_id:
        q = q.where(MileageTrip.vehicle_id == vehicle_id)
    purpose = request.args.get("purpose", "")
    if purpose in ("business", "personal"):
        q = q.where(MileageTrip.purpose == purpose)
    trips = s.scalars(q.order_by(MileageTrip.date.desc(), MileageTrip.id.desc())).all()
    rows = []
    business = personal = Decimal(0)
    deduction = 0
    for t in trips:
        rate = mileage_service.rate_on(s, t.date) if t.purpose == "business" else None
        value = money.line_amount(t.miles, rate) if rate is not None else 0
        rows.append({"trip": t, "rate": rate, "value": value})
        if t.purpose == "business":
            business += t.miles or 0
            deduction += value
        else:
            personal += t.miles or 0
    vehicles = s.scalars(select(Vehicle).order_by(Vehicle.name)).all()
    return render_template("time/mileage.html", rows=rows, business=business, personal=personal,
                           deduction=deduction, vehicles=vehicles, preset=preset, start=start, end=end,
                           presets=PERIOD_PRESETS, purpose=purpose, current_rate=mileage_service.rate_on(s, core.today()))


@bp.route("/mileage/new", methods=["GET", "POST"])
@core.requires("time.edit")
def trip_new():
    trip = MileageTrip(date=core.today(), purpose="business")
    last = core.db().scalar(select(MileageTrip).order_by(MileageTrip.id.desc()).limit(1))
    if last is not None:
        trip.vehicle_id = last.vehicle_id
    return _trip_form(trip)


@bp.route("/mileage/<int:trip_id>", methods=["GET", "POST"])
@core.requires("time.view")
def trip_edit(trip_id: int):
    trip = core.db().get(MileageTrip, trip_id) or abort(404)
    if request.method == "POST" and not core.can("time.edit"):
        abort(403)
    return _trip_form(trip)


def _trip_form(trip: MileageTrip):
    s = core.db()
    vehicles = s.scalars(select(Vehicle).where(Vehicle.active.is_(True)).order_by(Vehicle.name)).all()
    customers = s.scalars(select(Customer).where(Customer.active.is_(True)).order_by(Customer.display_name)).all()
    if request.method == "POST":
        if core.f("action") == "delete" and trip.id:
            audit.record(s, core.current_user(), "delete", "mileage", trip.id,
                         summary=f"Deleted a {trip.miles}-mile trip on {trip.date:%m/%d/%Y}")
            s.delete(trip)
            s.commit()
            flash("Trip deleted.", "success")
            return redirect(url_for("time.mileage"))
        is_new = trip.id is None
        try:
            try:
                trip.date = parse_date(core.f("date"), core.today())
            except ValueError:
                raise ValidationError("Enter the date.", "date") from None
            miles = money.to_decimal(core.f("miles"), None)
            if core.f_bool("round_trip") and miles:
                miles *= 2
            if miles is None or miles <= 0:
                raise ValidationError("Enter the miles driven.", "miles")
            if miles > 5000:
                raise ValidationError("That's more than 5,000 miles for one trip; check the number.", "miles")
            trip.miles = miles.quantize(Decimal("0.1"))
            trip.vehicle_id = core.f_int("vehicle_id")
            if core.f("new_vehicle"):
                v = Vehicle(name=core.f("new_vehicle"), active=True)
                s.add(v)
                s.flush()
                trip.vehicle_id = v.id
            trip.purpose = "personal" if core.f("purpose") == "personal" else "business"
            trip.start_location = core.f("start_location") or None
            trip.end_location = core.f("end_location") or None
            trip.customer_id = core.f_int("customer_id")
            trip.notes = core.f("notes") or None
            if is_new:
                s.add(trip)
            s.flush()
            audit.record(s, core.current_user(), "create" if is_new else "update", "mileage", trip.id,
                         summary=f"{'Logged' if is_new else 'Updated'} a {trip.miles}-mile {trip.purpose} trip "
                                 f"on {trip.date:%m/%d/%Y}")
            s.commit()
        except (ValidationError, money.MoneyError) as exc:
            s.rollback()
            flash(str(exc), "error")
            return render_template("time/trip_form.html", trip=trip, vehicles=vehicles, customers=customers), 422
        flash("Trip saved.", "success")
        if core.f("next_action") == "save_new":
            return redirect(url_for("time.trip_new"))
        return redirect(url_for("time.mileage"))
    return render_template("time/trip_form.html", trip=trip, vehicles=vehicles, customers=customers,
                           rate=mileage_service.rate_on(s, trip.date or core.today()))


@bp.route("/mileage/summary.csv")
@core.requires("time.view")
def mileage_csv():
    """A year's log in the shape the IRS expects you to keep: date, miles, places, purpose."""
    import csv
    import io

    from flask import Response

    s = core.db()
    year = request.args.get("year", type=int) or core.today().year
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Vehicle", "From", "To", "Miles", "Purpose", "Customer", "Notes", "Rate", "Deduction"])
    total = Decimal(0)
    for t in s.scalars(select(MileageTrip).where(MileageTrip.date >= date(year, 1, 1), MileageTrip.date <= date(year, 12, 31))
                       .order_by(MileageTrip.date)):
        rate = mileage_service.rate_on(s, t.date) if t.purpose == "business" else None
        value = money.line_amount(t.miles, rate) if rate is not None else 0
        total += Decimal(value) / 100
        w.writerow([t.date.isoformat(), t.vehicle.name if t.vehicle else "", t.start_location or "", t.end_location or "",
                    t.miles, t.purpose, t.customer.display_name if t.customer else "", t.notes or "",
                    rate if rate is not None else "", f"{value / 100:.2f}" if value else ""])
    w.writerow([])
    w.writerow(["", "", "", "", "", "", "", "", "Total", f"{total:.2f}"])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="mileage-{year}.csv"'})


@bp.app_template_global("time_total_minutes")
def _time_total(rows) -> int:
    return sum((r.minutes for r in rows if r is not None), 0)


@bp.app_template_global("hours_of")
def _hours_of(minutes: int) -> str:
    return f"{Decimal(minutes or 0) / 60:.2f}"



@bp.app_template_global("time_amount")
def _time_amount(ta: TimeActivity) -> int:
    return money.line_amount(ta.hours, ta.hourly_rate or Decimal(0))
