"""Small lists: terms, payment methods, classes, locations, tags and vehicles.

Each list is described once in ``LISTS`` and edited by the same two views.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from pps_tools.books.models import (Customer, Location, MileageTrip, PaymentMethod, Tag, Terms, TrackingClass,
                                    Transaction, TransactionLine, Vehicle)
from pps_tools.books.services import audit
from pps_tools.books.services.errors import ValidationError
from pps_tools.books.web import core

bp = Blueprint("lists", __name__)


@dataclass
class Field:
    name: str
    label: str
    kind: str = "text"  # text | int | decimal | select | parent
    options: list[tuple[str, str]] = field(default_factory=list)
    required: bool = False
    hint: str = ""


@dataclass
class ListSpec:
    key: str
    label: str
    singular: str
    model: Any
    fields: list[Field]
    description: str
    has_active: bool = True

    def display(self, row) -> str:
        return getattr(row, "full_name", None) or row.name


LISTS: dict[str, ListSpec] = {
    "terms": ListSpec("terms", "Terms", "term", Terms, [
        Field("name", "Name", required=True),
        Field("kind", "Due", "select", [("days", "Within a number of days"), ("day_of_month", "On a day of the month")]),
        Field("due_days", "Days", "int", hint="Net 30 → 30"),
        Field("day_of_month", "Day of month", "int"),
        Field("cutoff_days", "Push to next month if issued within (days)", "int"),
        Field("discount_pct", "Early-payment discount %", "decimal"),
        Field("discount_days", "If paid within (days)", "int"),
    ], "When invoices and bills are due, and early-payment discounts."),
    "payment-methods": ListSpec("payment-methods", "Payment methods", "payment method", PaymentMethod, [
        Field("name", "Name", required=True),
        Field("kind", "Kind", "select", [("cash", "Cash"), ("check", "Check"), ("card", "Credit card"),
                                         ("ach", "Bank transfer"), ("other", "Other")]),
    ], "How customers pay you and how you pay vendors."),
    "classes": ListSpec("classes", "Classes", "class", TrackingClass, [
        Field("name", "Name", required=True), Field("parent_id", "Sub-class of", "parent"),
    ], "Departments, product lines or anything you want a P&L for."),
    "locations": ListSpec("locations", "Locations", "location", Location, [
        Field("name", "Name", required=True), Field("parent_id", "Sub-location of", "parent"),
    ], "Stores, offices or territories."),
    "tags": ListSpec("tags", "Tags", "tag", Tag, [
        Field("name", "Name", required=True), Field("group_name", "Group"),
    ], "Free-form labels for transactions; filter reports by them.", has_active=False),
    "vehicles": ListSpec("vehicles", "Vehicles", "vehicle", Vehicle, [
        Field("name", "Name", required=True), Field("year", "Year", "int"), Field("make", "Make"),
        Field("model", "Model"),
    ], "Cars and trucks you log business mileage for."),
}


def _spec(kind: str) -> ListSpec:
    spec = LISTS.get(kind)
    if spec is None:
        abort(404)
    return spec


@bp.route("/lists")
@core.requires("sales.view")
def index():
    s = core.db()
    counts = {key: s.scalar(select(func.count()).select_from(spec.model)) or 0 for key, spec in LISTS.items()}
    return render_template("lists/index.html", lists=LISTS, counts=counts)


@bp.route("/lists/<kind>", methods=["GET", "POST"])
@core.requires("sales.view")
def show(kind: str):
    spec = _spec(kind)
    s = core.db()
    editing = None
    if request.args.get("edit", type=int):
        editing = s.get(spec.model, request.args.get("edit", type=int)) or abort(404)
    if request.method == "POST":
        if not core.can("lists.edit"):
            abort(403)
        row_id = core.f_int("id")
        row = s.get(spec.model, row_id) if row_id else spec.model()
        if row is None:
            abort(404)
        try:
            _fill(s, spec, row)
            if row.id is None:
                s.add(row)
            s.flush()
            audit.record(s, core.current_user(), "update" if row_id else "create", spec.key, row.id,
                         name=row.name, summary=f"{'Updated' if row_id else 'Added'} {spec.singular} {row.name}")
            s.commit()
        except ValidationError as exc:
            s.rollback()
            flash(str(exc), "error")
            return _render(spec, row if row_id else None), 422
        flash(f"Saved {spec.singular} “{row.name}”.", "success")
        return redirect(url_for("lists.show", kind=kind))
    return _render(spec, editing)


def _render(spec: ListSpec, editing):
    s = core.db()
    q = select(spec.model)
    show = request.args.get("show", "active")
    if spec.has_active and show == "active":
        q = q.where(spec.model.active.is_(True))
    rows = sorted(s.scalars(q).all(), key=lambda r: spec.display(r).lower())
    parents = []
    if any(fl.kind == "parent" for fl in spec.fields):
        parents = [r for r in rows if editing is None or r.id != editing.id]
    usage = _usage(s, spec)
    return render_template("lists/show.html", spec=spec, rows=rows, editing=editing, parents=parents,
                           show=show, usage=usage)


def _fill(s, spec: ListSpec, row) -> None:
    for fl in spec.fields:
        raw = (request.form.get(fl.name) or "").strip()
        if fl.required and not raw:
            raise ValidationError(f"Enter a {fl.label.lower()}.", fl.name)
        if fl.kind in ("int", "parent"):
            if raw and not raw.lstrip("-").isdigit():
                raise ValidationError(f"{fl.label} must be a whole number.", fl.name)
            value: Any = int(raw) if raw else None
            if fl.kind == "parent" and value is not None:
                if row.id is not None and value == row.id:
                    raise ValidationError("A list entry can't be its own parent.", fl.name)
                parent = s.get(spec.model, value)
                while parent is not None:
                    if row.id is not None and parent.id == row.id:
                        raise ValidationError("That would make a loop of parents.", fl.name)
                    parent = parent.parent
        elif fl.kind == "decimal":
            try:
                value = Decimal(raw.rstrip("%")) if raw else None
            except InvalidOperation:
                raise ValidationError(f"{fl.label} must be a number.", fl.name) from None
        elif fl.kind == "select":
            value = raw if raw in dict(fl.options) else fl.options[0][0]
        else:
            value = raw or None
        if fl.name == "due_days" and value is None:
            value = 0
        setattr(row, fl.name, value)
    if spec.has_active:
        row.active = core.f_bool("active") if "active" in request.form or row.id else True
    dup = s.scalar(select(spec.model.id).where(func.lower(spec.model.name) == row.name.lower(),
                                               spec.model.id != (row.id or 0),
                                               *([spec.model.parent_id == row.parent_id]
                                                 if hasattr(spec.model, "parent_id") else [])))
    if dup:
        raise ValidationError(f"There's already a {spec.singular} named “{row.name}”.", "name")


def _usage(s, spec: ListSpec) -> dict[int, int]:
    """How many transactions use each entry, so people know what deactivating affects."""
    if spec.model is Terms:
        q = select(Transaction.terms_id, func.count()).where(Transaction.terms_id.isnot(None)).group_by(Transaction.terms_id)
    elif spec.model is PaymentMethod:
        q = (select(Transaction.payment_method_id, func.count()).where(Transaction.payment_method_id.isnot(None))
             .group_by(Transaction.payment_method_id))
    elif spec.model is TrackingClass:
        # Classes live on lines or on the header, depending on the tracking setting.
        used: dict[int, set[int]] = {}
        for cid, tid in s.execute(select(TransactionLine.class_id, TransactionLine.txn_id)
                                  .where(TransactionLine.class_id.isnot(None))):
            used.setdefault(cid, set()).add(tid)
        for cid, tid in s.execute(select(Transaction.class_id, Transaction.id).where(Transaction.class_id.isnot(None))):
            used.setdefault(cid, set()).add(tid)
        return {cid: len(tids) for cid, tids in used.items()}
    elif spec.model is Location:
        q = (select(Transaction.location_id, func.count()).where(Transaction.location_id.isnot(None))
             .group_by(Transaction.location_id))
    elif spec.model is Vehicle:
        q = (select(MileageTrip.vehicle_id, func.count()).where(MileageTrip.vehicle_id.isnot(None))
             .group_by(MileageTrip.vehicle_id))
    elif spec.model is Tag:
        from pps_tools.books.models.transactions import transaction_tags

        q = select(transaction_tags.c.tag_id, func.count()).group_by(transaction_tags.c.tag_id)
    else:  # pragma: no cover
        return {}
    return {k: v for k, v in s.execute(q)}


@bp.route("/lists/<kind>/<int:row_id>/toggle", methods=["POST"])
@core.requires("lists.edit")
def toggle(kind: str, row_id: int):
    spec = _spec(kind)
    s = core.db()
    row = s.get(spec.model, row_id) or abort(404)
    if not spec.has_active:
        abort(400)
    row.active = not row.active
    audit.record(s, core.current_user(), "update", spec.key, row.id, name=row.name,
                 summary=f"{'Reactivated' if row.active else 'Made inactive'} {spec.singular} {row.name}")
    s.commit()
    flash(f"“{row.name}” is now {'active' if row.active else 'inactive'}.", "success")
    return redirect(url_for("lists.show", kind=kind, show=request.args.get("show", "active")))


@bp.route("/lists/<kind>/<int:row_id>/delete", methods=["POST"])
@core.requires("lists.edit")
def delete(kind: str, row_id: int):
    spec = _spec(kind)
    s = core.db()
    row = s.get(spec.model, row_id) or abort(404)
    if _usage(s, spec).get(row.id):
        flash(f"“{row.name}” is used on transactions. Make it inactive instead.", "error")
        return redirect(url_for("lists.show", kind=kind))
    if spec.model is Terms and s.scalar(select(Customer.id).where(Customer.terms_id == row.id).limit(1)):
        flash("Customers use these terms. Make them inactive instead.", "error")
        return redirect(url_for("lists.show", kind=kind))
    if hasattr(spec.model, "parent_id") and s.scalar(select(spec.model.id).where(spec.model.parent_id == row.id).limit(1)):
        flash(f"“{row.name}” has sub-entries. Move or delete those first.", "error")
        return redirect(url_for("lists.show", kind=kind))
    name = row.name
    s.delete(row)
    audit.record(s, core.current_user(), "delete", spec.key, row_id, name=name,
                 summary=f"Deleted {spec.singular} {name}")
    s.commit()
    flash(f"Deleted “{name}”.", "success")
    return redirect(url_for("lists.show", kind=kind))


def label_for(spec: ListSpec, row, fl: Field) -> Optional[str]:
    value = getattr(row, fl.name)
    if value is None:
        return ""
    if fl.kind == "select":
        return dict(fl.options).get(value, value)
    if fl.kind == "parent":
        parent = getattr(row, "parent", None)
        return parent.full_name if parent else ""
    return str(value)


@bp.app_template_global("list_cell")
def _list_cell(spec: ListSpec, row, fl: Field) -> str:
    return label_for(spec, row, fl) or ""
