"""Recurring transactions.

A template is edited on the normal transaction form (in "template mode")
with a schedule panel on top; the form's fields become the template's
payload, and ``services.recurring`` turns it back into transactions.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from pps_tools.books.models import RecurringTemplate, Transaction
from pps_tools.books.services import audit
from pps_tools.books.services import recurring as recurring_service
from pps_tools.books.services import users as user_service
from pps_tools.books.services.dates import next_occurrence, parse_date
from pps_tools.books.services.errors import BooksError, ValidationError
from pps_tools.books.txn_types import TXN_TYPES
from pps_tools.books.web import core
from pps_tools.books.web import txn as txn_views

bp = Blueprint("recurring", __name__)

INTERVALS = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "yearly": "Yearly"}
MODES = {"scheduled": "Scheduled", "reminder": "Reminder", "unscheduled": "Unscheduled"}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
_COLUMNS = [c.key for c in RecurringTemplate.__table__.columns]


def _load(tpl_id: int) -> RecurringTemplate:
    tpl = core.db().get(RecurringTemplate, tpl_id)
    if tpl is None:
        abort(404)
    if not user_service.can_view_type(core.current_user(), tpl.txn_type):
        abort(403)
    return tpl


def _require_edit(ttype: str) -> None:
    if not user_service.can_edit_type(core.current_user(), ttype):
        abort(403)


def describe(tpl) -> str:
    """'Every 2 months on day 15', 'Every week on Friday'..."""
    if tpl.mode == "unscheduled":
        return "Unscheduled"
    n = tpl.every or 1
    unit = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}.get(tpl.interval, tpl.interval)
    out = f"Every {unit}" if n == 1 else f"Every {n} {unit}s"
    if tpl.interval == "weekly" and tpl.day_of_week is not None:
        out += f" on {WEEKDAYS[tpl.day_of_week]}"
    elif tpl.interval == "monthly" and tpl.day_of_month is not None:
        out += " on the last day" if tpl.day_of_month == 0 else f" on day {tpl.day_of_month}"
    elif tpl.interval == "yearly" and tpl.month_of_year:
        day = "the last day" if tpl.day_of_month == 0 else (tpl.day_of_month or "")
        out += f" on {MONTHS[tpl.month_of_year - 1]} {day}".rstrip()
    return out


@bp.app_template_filter("schedule_text")
def _schedule_text(tpl) -> str:
    return describe(tpl)


# -- list --------------------------------------------------------------------------------------------


@bp.route("/recurring")
def index():
    s = core.db()
    user = core.current_user()
    q = select(RecurringTemplate)
    ttype = request.args.get("type")
    if ttype in TXN_TYPES:
        q = q.where(RecurringTemplate.txn_type == ttype)
    mode = request.args.get("mode")
    if mode in MODES:
        q = q.where(RecurringTemplate.mode == mode)
    show = request.args.get("show", "active")
    if show == "active":
        q = q.where(RecurringTemplate.active.is_(True))
    rows = [t for t in s.scalars(q.order_by(RecurringTemplate.name)) if user_service.can_view_type(user, t.txn_type)]
    today = core.today()
    due = [t for t in rows if t.mode == "reminder" and t.active and t.next_date
           and t.next_date - timedelta(days=t.days_in_advance or 0) <= today]
    counts = dict(s.execute(select(Transaction.recurring_template_id, func.count())
                            .where(Transaction.recurring_template_id.isnot(None))
                            .group_by(Transaction.recurring_template_id)).all())
    last = dict(s.execute(select(Transaction.recurring_template_id, func.max(Transaction.date))
                          .where(Transaction.recurring_template_id.isnot(None))
                          .group_by(Transaction.recurring_template_id)).all())
    types = [(code, TXN_TYPES[code].label) for code in recurring_service.RECURRABLE
             if user_service.can_edit_type(user, code)]
    return render_template("recurring/index.html", rows=rows, due=due, counts=counts, last=last, types=types,
                           modes=MODES, show=show, today=today)


# -- create / edit -----------------------------------------------------------------------------------


@bp.route("/recurring/new", methods=["GET", "POST"])
def new():
    s = core.db()
    src = None
    if request.args.get("from_txn", type=int):
        src = s.get(Transaction, request.args.get("from_txn", type=int)) or abort(404)
        ttype = src.type
    else:
        ttype = request.args.get("type") or "invoice"
    if ttype not in recurring_service.RECURRABLE:
        abort(404)
    _require_edit(ttype)
    today = core.today()
    tpl = RecurringTemplate(txn_type=ttype, mode="scheduled", interval="monthly", every=1, start_date=today,
                            days_in_advance=0, occurrences=0, active=True, auto_send=False, autopay=False)
    if request.method == "POST":
        return _save(tpl)
    info = TXN_TYPES[ttype]
    if src is not None:
        data = recurring_service.template_payload(src)
        tpl.name = f"{src.entity_name or info.label} {info.label.lower()}".strip()
        tpl.day_of_month = min(src.date.day, 28)
        tpl.start_date = _next_month_same_day(src.date)
        tpl.auto_send = info.customer_facing
    else:
        data = txn_views._new_defaults(info)
        if not isinstance(data, dict):  # pragma: no cover - a redirect
            return data
    return _render(tpl, data)


def _next_month_same_day(d):
    from pps_tools.books.services.dates import add_months

    return add_months(d.replace(day=1), 1, min(d.day, 28))


@bp.route("/recurring/<int:tpl_id>", methods=["GET", "POST"])
def edit(tpl_id: int):
    tpl = _load(tpl_id)
    if request.method == "POST":
        _require_edit(tpl.txn_type)
        return _save(tpl)
    data = dict(tpl.payload or {})
    data["type"] = tpl.txn_type
    return _render(tpl, data)


def _render(tpl, data: dict, status: int = 200):
    info = TXN_TYPES[tpl.txn_type]
    data = dict(data)
    data.pop("number", None)
    # The form's date field is required; it's hidden in template mode and ignored on save.
    data["date"] = (tpl.start_date or core.today()).isoformat()
    action = url_for("recurring.edit", tpl_id=tpl.id) if tpl.id else url_for("recurring.new", type=tpl.txn_type)
    page, code = txn_views.render_form(info, None, data, status=status, tpl=tpl, form_action=action,
                                       intervals=INTERVALS, modes=MODES, weekdays=WEEKDAYS, months=MONTHS)
    return page, code


def _apply_schedule(tpl, strict: bool = True) -> None:
    """Copy the schedule panel onto ``tpl`` (a template or a stand-in for re-rendering)."""
    def fail(message: str, field: str):
        if strict:
            raise ValidationError(message, field)

    tpl.name = (core.f("tpl_name") or "").strip()
    if not tpl.name:
        fail("Name the template.", "tpl_name")
    tpl.mode = core.f("tpl_mode") if core.f("tpl_mode") in MODES else "scheduled"
    tpl.interval = core.f("tpl_interval") if core.f("tpl_interval") in INTERVALS else "monthly"
    every = core.f_int("tpl_every") or 1
    if every < 1 or every > 365:
        fail("“Every” has to be between 1 and 365.", "tpl_every")
        every = 1
    tpl.every = every
    tpl.day_of_week = core.f_int("tpl_day_of_week") if tpl.interval == "weekly" else None
    if tpl.day_of_week is not None and not 0 <= tpl.day_of_week <= 6:
        tpl.day_of_week = None
    dom = core.f_int("tpl_day_of_month") if tpl.interval in ("monthly", "yearly") else None
    if dom is not None and not 0 <= dom <= 31:
        fail("Pick a day of the month.", "tpl_day_of_month")
        dom = None
    tpl.day_of_month = dom
    moy = core.f_int("tpl_month_of_year") if tpl.interval == "yearly" else None
    tpl.month_of_year = moy if moy and 1 <= moy <= 12 else None
    try:
        start = parse_date(core.f("tpl_start_date"), core.today())
        end = parse_date(core.f("tpl_end_date")) if core.f("tpl_end") == "date" else None
        nxt = parse_date(core.f("tpl_next_date")) if core.f("tpl_next_date") else None
    except ValueError:
        fail("Check the dates in the schedule.", "tpl_start_date")
        start, end, nxt = core.today(), None, None
    tpl.start_date = start
    tpl.end_date = end
    if end and end < start:
        fail("The end date is before the start date.", "tpl_end_date")
    tpl.max_occurrences = core.f_int("tpl_max_occurrences") if core.f("tpl_end") == "count" else None
    if tpl.max_occurrences is not None and tpl.max_occurrences < 1:
        fail("Enter how many times it should run.", "tpl_max_occurrences")
    tpl.days_in_advance = max(0, min(core.f_int("tpl_days_in_advance") or 0, 365))
    info = TXN_TYPES[tpl.txn_type]
    tpl.auto_send = core.f_bool("tpl_auto_send") and info.customer_facing
    tpl.autopay = core.f_bool("tpl_autopay") and tpl.txn_type == "invoice"
    tpl.active = core.f_bool("tpl_active") if "tpl_has_active" in request.form else True
    if not tpl.occurrences:
        tpl.next_date = tpl.start_date
    elif nxt:
        tpl.next_date = nxt
    if tpl.mode == "unscheduled":
        tpl.next_date = None
    elif tpl.next_date is None and tpl.active:
        tpl.next_date = max(tpl.start_date, core.today())


def _save(tpl: RecurringTemplate):
    s = core.db()
    info = TXN_TYPES[tpl.txn_type]
    is_new = tpl.id is None
    snapshot = {c: getattr(tpl, c) for c in _COLUMNS}
    try:
        payload = txn_views.parse_form(info, None)
        _apply_schedule(tpl)
        if tpl.autopay:
            from pps_tools.books.models import Customer

            cust = s.get(Customer, int(payload["customer_id"])) if payload.get("customer_id") else None
            if cust is None or not cust.stripe_payment_method_id:
                raise ValidationError("Autopay needs a customer with a card or bank account saved in Stripe. "
                                      "They can save one when they pay an invoice online.", "tpl_autopay")
        recurring_service.save_template(s, tpl, payload)
        audit.record(s, core.current_user(), "create" if is_new else "update", "recurring_template", tpl.id,
                     name=tpl.name, summary=f"{'Added' if is_new else 'Updated'} recurring {info.label.lower()} "
                                            f"“{tpl.name}” ({describe(tpl)})")
        s.commit()
    except BooksError as exc:
        s.rollback()
        flash(str(exc), "error")
        # Re-show what was typed on a stand-in, since the rollback expired the real template.
        stand_in = SimpleNamespace(**snapshot)
        _apply_schedule(stand_in, strict=False)
        try:
            data = txn_views.parse_form(info, None)
        except BooksError:
            data = {"type": info.code, "lines": []}
        return _render(stand_in, data, status=422)
    flash(f"Saved recurring template “{tpl.name}”.", "success")
    return redirect(url_for("recurring.index"))


# -- actions ------------------------------------------------------------------------------------------


@bp.route("/recurring/<int:tpl_id>/use")
def use(tpl_id: int):
    """Open a new transaction filled in from the template (QBO's 'Use')."""
    tpl = _load(tpl_id)
    _require_edit(tpl.txn_type)
    return redirect(url_for("txn.new", slug=TXN_TYPES[tpl.txn_type].slug, from_template=tpl.id))


@bp.route("/recurring/<int:tpl_id>/create-now", methods=["POST"])
def create_now(tpl_id: int):
    """Create the next occurrence immediately and move the schedule along."""
    tpl = _load(tpl_id)
    _require_edit(tpl.txn_type)
    s = core.db()
    try:
        txn = recurring_service.create_from_template(s, tpl, tpl.next_date or core.today(), user=core.current_user())
        if tpl.mode != "unscheduled" and tpl.next_date:
            recurring_service.advance(tpl)
        tpl.last_run_at = txn.created_at
        tpl.last_error = None
        s.commit()
    except BooksError as exc:
        s.rollback()
        flash(f"Couldn't create it: {exc}", "error")
        return redirect(url_for("recurring.index"))
    flash(f"Created {txn.info.label.lower()}{' ' + txn.number if txn.number else ''}.", "success")
    return redirect(url_for("txn.go", txn_id=txn.id))


@bp.route("/recurring/<int:tpl_id>/skip", methods=["POST"])
def skip(tpl_id: int):
    tpl = _load(tpl_id)
    _require_edit(tpl.txn_type)
    s = core.db()
    if tpl.next_date and tpl.active:
        skipped = tpl.next_date
        # A skipped date doesn't count toward "end after N times"; only the end date can end it.
        nxt = next_occurrence(tpl.next_date, tpl.interval, tpl.every, tpl.day_of_week, tpl.day_of_month,
                              tpl.month_of_year)
        if tpl.end_date and nxt > tpl.end_date:
            tpl.active = False
            tpl.next_date = None
            flash("That was the last date in the schedule, so the template is now inactive.", "info")
        else:
            tpl.next_date = nxt
        audit.record(s, core.current_user(), "update", "recurring_template", tpl.id, name=tpl.name,
                     summary=f"Skipped {skipped:%m/%d/%Y} for “{tpl.name}”")
        s.commit()
        flash(f"Skipped {skipped:%m/%d/%Y}.", "success")
    return redirect(url_for("recurring.index"))


@bp.route("/recurring/<int:tpl_id>/toggle", methods=["POST"])
def toggle(tpl_id: int):
    tpl = _load(tpl_id)
    _require_edit(tpl.txn_type)
    s = core.db()
    tpl.active = not tpl.active
    if tpl.active and tpl.mode != "unscheduled" and (tpl.next_date is None or tpl.next_date < core.today()):
        # Resuming picks up from today rather than back-filling every missed date.
        tpl.next_date = max(tpl.start_date, core.today())
    audit.record(s, core.current_user(), "update", "recurring_template", tpl.id, name=tpl.name,
                 summary=f"{'Resumed' if tpl.active else 'Paused'} “{tpl.name}”")
    s.commit()
    flash(f"“{tpl.name}” {'resumed' if tpl.active else 'paused'}.", "success")
    return redirect(url_for("recurring.index"))


@bp.route("/recurring/<int:tpl_id>/duplicate", methods=["POST"])
def duplicate(tpl_id: int):
    tpl = _load(tpl_id)
    _require_edit(tpl.txn_type)
    s = core.db()
    base = f"{tpl.name} (copy)"
    name, n = base, 2
    while s.scalar(select(RecurringTemplate.id).where(RecurringTemplate.name == name)):
        name, n = f"{base} {n}", n + 1
    copy = RecurringTemplate(**{c: getattr(tpl, c) for c in _COLUMNS if c not in ("id", "name", "created_at",
                                                                                   "occurrences", "last_run_at",
                                                                                   "last_error")})
    copy.name = name
    copy.occurrences = 0
    copy.active = False
    copy.next_date = None if copy.mode == "unscheduled" else max(copy.start_date, core.today())
    s.add(copy)
    s.flush()
    audit.record(s, core.current_user(), "create", "recurring_template", copy.id, name=copy.name,
                 summary=f"Duplicated “{tpl.name}”")
    s.commit()
    flash(f"Made a paused copy, “{name}”. Edit it, then resume it.", "success")
    return redirect(url_for("recurring.edit", tpl_id=copy.id))


@bp.route("/recurring/<int:tpl_id>/delete", methods=["POST"])
def delete(tpl_id: int):
    tpl = _load(tpl_id)
    _require_edit(tpl.txn_type)
    s = core.db()
    name = tpl.name
    # Transactions it made stay; they just stop pointing at the template.
    for txn in s.scalars(select(Transaction).where(Transaction.recurring_template_id == tpl.id)):
        txn.recurring_template_id = None
    s.delete(tpl)
    audit.record(s, core.current_user(), "delete", "recurring_template", tpl_id, name=name,
                 summary=f"Deleted recurring template “{name}”")
    s.commit()
    flash(f"Deleted “{name}”. Transactions it already created are unchanged.", "success")
    return redirect(url_for("recurring.index"))


@bp.route("/recurring/<int:tpl_id>/history")
def history(tpl_id: int):
    tpl = _load(tpl_id)
    rows = core.db().scalars(select(Transaction).where(Transaction.recurring_template_id == tpl.id)
                             .order_by(Transaction.date.desc(), Transaction.id.desc())).all()
    return render_template("recurring/history.html", tpl=tpl, rows=rows)


@bp.route("/recurring/run", methods=["POST"])
@core.requires("settings.edit")
def run_now():
    """Run everything that's due: recurring templates, reminders, late fees, report emails."""
    s = core.db()
    cfg = core.config()
    report = recurring_service.run_scheduled(s, cfg, core.today(), base_url=(cfg.base_url or request.host_url).rstrip("/"))
    s.commit()
    parts = [f"{len(report.created)} created"]
    for label, n in (("sent", report.sent), ("autopaid", report.autopaid), ("reminders", report.reminders),
                     ("late fees", report.late_fees), ("reports emailed", report.reports_emailed)):
        if n:
            parts.append(f"{n} {label}")
    flash("Ran scheduled work: " + ", ".join(parts) + ".", "success")
    for err in report.errors[:5]:
        flash(err, "error")
    return redirect(url_for("recurring.index"))
