"""The audit log: every change, by whom and when."""

from __future__ import annotations

from datetime import datetime, time

from flask import Blueprint, abort, render_template, request
from sqlalchemy import func, or_, select

from pps_tools.books.models import AuditLog, User
from pps_tools.books.services import audit as audit_service
from pps_tools.books.services.dates import PERIOD_PRESETS, parse_date, period_range
from pps_tools.books.web import core

bp = Blueprint("audit", __name__)

ACTIONS = ["create", "update", "delete", "void", "login", "logout", "settings", "close_books", "export", "import"]


@bp.route("/audit")
@core.requires("audit.view")
def index():
    s = core.db()
    preset = request.args.get("preset", "last_30_days")
    start, end = period_range(preset, core.today(), core.company().fiscal_year_start_month)
    if preset == "custom":
        start = parse_date(request.args.get("start"), start)
        end = parse_date(request.args.get("end"), end)
    q = select(AuditLog)
    if start:
        q = q.where(AuditLog.ts >= datetime.combine(start, time.min))
    if end:
        q = q.where(AuditLog.ts <= datetime.combine(end, time.max))
    uid = request.args.get("user_id", type=int)
    if uid:
        q = q.where(AuditLog.user_id == uid)
    action = request.args.get("action")
    if action in ACTIONS:
        q = q.where(AuditLog.action == action)
    otype = request.args.get("object_type")
    if otype:
        q = q.where(AuditLog.object_type == otype)
    needle = (request.args.get("q") or "").strip()
    if needle:
        like = f"%{needle}%"
        q = q.where(or_(AuditLog.summary.ilike(like), AuditLog.name.ilike(like)))
    total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
    page, offset, pages = core.paginate(total, per_page=100)
    rows = s.scalars(q.order_by(AuditLog.ts.desc(), AuditLog.id.desc()).offset(offset).limit(100)).all()
    users = s.scalars(select(User).order_by(User.name)).all()
    types = [t for (t,) in s.execute(select(AuditLog.object_type).distinct().order_by(AuditLog.object_type))]
    return render_template("audit/index.html", rows=rows, users=users, types=types, actions=ACTIONS, preset=preset,
                           presets=PERIOD_PRESETS, start=start, end=end, page=page, pages=pages, total=total)


@bp.route("/audit/<int:entry_id>")
@core.requires("audit.view")
def view(entry_id: int):
    entry = core.db().get(AuditLog, entry_id) or abort(404)
    return render_template("audit/view.html", e=entry, changes=audit_service.changes(entry.before, entry.after))
