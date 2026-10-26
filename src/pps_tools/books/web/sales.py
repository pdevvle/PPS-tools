"""Sales: overview, all sales, invoices, estimates, statements."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Optional

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select

from pps_tools.books.db import utcnow
from pps_tools.books.models import Customer, Statement, Transaction
from pps_tools.books.services import dates as D
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.errors import BooksError
from pps_tools.books.services.reports.financial import pl_summary
from pps_tools.books.txn_types import TXN_TYPES
from pps_tools.books.web import core

bp = Blueprint("sales", __name__)

SALES_LIST_TYPES = ("invoice", "payment", "sales_receipt", "credit_memo", "refund_receipt", "estimate",
                    "delayed_charge", "delayed_credit", "customer_refund")


def filtered_txns(types: Iterable[str], party: str = "customer"):
    """Transactions of ``types`` filtered by the list page's query string."""
    s = core.db()
    args = request.args
    q = select(Transaction).where(Transaction.type.in_(list(types)))
    ttype = args.get("type")
    if ttype and ttype in TXN_TYPES:
        q = q.where(Transaction.type == ttype)
    preset = args.get("period", "")
    start = end = None
    if preset == "custom":
        try:
            start = D.parse_date(args.get("start")) if args.get("start") else None
            end = D.parse_date(args.get("end")) if args.get("end") else None
        except ValueError:
            start = end = None
    elif preset:
        start, end = D.period_range(preset, core.today(), core.company().fiscal_year_start_month)
    if start:
        q = q.where(Transaction.date >= start)
    if end:
        q = q.where(Transaction.date <= end)
    pid = args.get("party_id", type=int)
    if pid:
        q = q.where((Transaction.customer_id if party == "customer" else Transaction.vendor_id) == pid)
    needle = (args.get("q") or "").strip()
    if needle:
        like = f"%{needle}%"
        q = q.where(or_(Transaction.number.ilike(like), Transaction.memo.ilike(like), Transaction.ref_no.ilike(like)))
    status = args.get("status", "")
    today = core.today()
    if status == "open":
        q = q.where(Transaction.balance_cents > 0, Transaction.voided.is_(False))
    elif status == "overdue":
        q = q.where(Transaction.balance_cents > 0, Transaction.due_date < today, Transaction.voided.is_(False))
    elif status == "paid":
        q = q.where(Transaction.balance_cents == 0, Transaction.voided.is_(False))
    elif status == "partial":
        q = q.where(Transaction.balance_cents > 0, Transaction.balance_cents < Transaction.total_cents)
    elif status == "unsent":
        q = q.where(Transaction.sent_at.is_(None), Transaction.voided.is_(False))
    elif status == "voided":
        q = q.where(Transaction.voided.is_(True))
    elif status in ("pending", "accepted", "rejected", "closed"):
        q = q.where(Transaction.status == status)
    sort = args.get("sort", "date_desc")
    order = {"date_desc": (Transaction.date.desc(), Transaction.id.desc()), "date": (Transaction.date, Transaction.id),
             "due": (Transaction.due_date, Transaction.id), "amount_desc": (Transaction.total_cents.desc(),),
             "number": (Transaction.number,)}.get(sort, (Transaction.date.desc(), Transaction.id.desc()))
    total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
    page, offset, pages = core.paginate(total, 50)
    rows = s.scalars(q.order_by(*order).offset(offset).limit(50)).all()
    sums = s.execute(select(func.coalesce(func.sum(Transaction.total_cents), 0),
                            func.coalesce(func.sum(Transaction.balance_cents), 0)).select_from(
        q.where(Transaction.voided.is_(False)).subquery())).one()
    return rows, total, page, pages, {"total": int(sums[0]), "balance": int(sums[1])}


@bp.route("/sales")
@core.requires("sales.view")
def overview():
    s = core.db()
    today = core.today()
    company = core.company()
    ystart, yend = D.fiscal_year_bounds(today, company.fiscal_year_start_month)
    pl = pl_summary(s, ystart, today, company.accounting_method)
    buckets = {"current": 0, "1_30": 0, "31_60": 0, "61_90": 0, "over_90": 0}
    for inv in s.scalars(select(Transaction).where(Transaction.type == "invoice", Transaction.balance_cents > 0,
                                                   Transaction.voided.is_(False))):
        days = (today - (inv.due_date or inv.date)).days
        key = "current" if days <= 0 else "1_30" if days <= 30 else "31_60" if days <= 60 else "61_90" if days <= 90 \
            else "over_90"
        buckets[key] += inv.balance_cents
    recent_payments = s.scalars(select(Transaction).where(Transaction.type.in_(("payment", "sales_receipt")),
                                                          Transaction.voided.is_(False))
                                .order_by(Transaction.date.desc(), Transaction.id.desc()).limit(8)).all()
    recent_invoices = s.scalars(select(Transaction).where(Transaction.type == "invoice")
                                .order_by(Transaction.date.desc(), Transaction.id.desc()).limit(8)).all()
    top = s.execute(select(Customer, func.sum(Transaction.balance_cents)).join(
        Transaction, Transaction.customer_id == Customer.id).where(Transaction.type == "invoice",
                                                                    Transaction.balance_cents > 0,
                                                                    Transaction.voided.is_(False))
        .group_by(Customer.id).order_by(func.sum(Transaction.balance_cents).desc()).limit(6)).all()
    return render_template("sales/overview.html", pl=pl, buckets=buckets, recent_payments=recent_payments,
                           recent_invoices=recent_invoices, top=top, ystart=ystart)


@bp.route("/sales/all")
@core.requires("sales.view")
def all_sales():
    rows, total, page, pages, sums = filtered_txns(SALES_LIST_TYPES)
    return render_template("sales/list.html", rows=rows, total=total, page=page, pages=pages, sums=sums,
                           title="All sales", types=SALES_LIST_TYPES, party="customer",
                           statuses=[("", "All statuses"), ("open", "Open"), ("overdue", "Overdue"), ("paid", "Paid"),
                                     ("voided", "Voided")], parties=_customers())


@bp.route("/invoices")
@core.requires("sales.view")
def invoices():
    rows, total, page, pages, sums = filtered_txns(("invoice",))
    return render_template("sales/list.html", rows=rows, total=total, page=page, pages=pages, sums=sums,
                           title="Invoices", types=None, fixed_type="invoice", party="customer", batch=True,
                           statuses=[("", "All"), ("open", "Unpaid"), ("overdue", "Overdue"), ("partial", "Partially paid"),
                                     ("unsent", "Not sent"), ("paid", "Paid"), ("voided", "Voided")], parties=_customers())


@bp.route("/estimates")
@core.requires("sales.view")
def estimates():
    rows, total, page, pages, sums = filtered_txns(("estimate",))
    return render_template("sales/list.html", rows=rows, total=total, page=page, pages=pages, sums=sums,
                           title="Estimates", types=None, fixed_type="estimate", party="customer",
                           statuses=[("", "All"), ("pending", "Pending"), ("accepted", "Accepted"),
                                     ("rejected", "Rejected"), ("closed", "Closed"), ("voided", "Voided")],
                           parties=_customers())


def _customers():
    return core.db().scalars(select(Customer).where(Customer.active.is_(True)).order_by(Customer.display_name)).all()


@bp.route("/invoices/batch", methods=["POST"])
@core.requires("sales.edit")
def invoice_batch():
    s = core.db()
    ids = [int(i) for i in request.form.getlist("ids") if i.isdigit()]
    action = core.f("action")
    txns = [t for t in (s.get(Transaction, i) for i in ids) if t is not None and t.type in SALES_LIST_TYPES]
    if not txns:
        flash("Select at least one transaction.", "error")
        return redirect(core.safe_next(url_for("sales.invoices")))
    if action == "print":
        from pps_tools.books.services import pdf as pdf_service

        data = pdf_service.render_many(s, txns, base_url=_base_url())
        return Response(data, mimetype="application/pdf", headers={"Content-Disposition": 'inline; filename="batch.pdf"'})
    if action == "send":
        from pps_tools.books.services import email as email_service

        sent = failed = 0
        for t in txns:
            if not (t.email_to or (t.customer and t.customer.email)):
                failed += 1
                continue
            try:
                email_service.send_transaction(s, core.config(), t, to=t.email_to or t.customer.email,
                                               base_url=_base_url(), user=core.current_user())
                sent += 1
            except BooksError:
                failed += 1
        s.commit()
        flash(f"Sent {sent}." + (f" {failed} skipped (no email address or an error)." if failed else ""),
              "success" if sent else "error")
    elif action == "mark_sent":
        for t in txns:
            t.sent_at = t.sent_at or utcnow()
        s.commit()
        flash(f"Marked {len(txns)} as sent.", "success")
    return redirect(core.safe_next(url_for("sales.invoices")))


def _base_url() -> str:
    return (core.config().base_url or request.host_url).rstrip("/")


# -- statements ------------------------------------------------------------------------


@bp.route("/statements", methods=["GET", "POST"])
@core.requires("sales.view")
def statements():
    s = core.db()
    from pps_tools.books.services import statements as st_service

    today = core.today()
    kind = request.values.get("kind", "balance_forward")
    stmt_date = D.parse_date(request.values.get("statement_date"), today)
    start = D.parse_date(request.values.get("start"), stmt_date - timedelta(days=30))
    end = D.parse_date(request.values.get("end"), stmt_date)
    who = request.values.get("who", "balance")
    customers = s.scalars(select(Customer).where(Customer.active.is_(True)).order_by(Customer.display_name)).all()
    balances = st_service.balances(s, stmt_date)
    if who == "balance":
        customers = [c for c in customers if balances.get(c.id, 0) != 0]
    elif who == "overdue":
        overdue = st_service.overdue_customers(s, stmt_date)
        customers = [c for c in customers if c.id in overdue]
    if request.method == "POST":
        if not core.can("sales.edit"):
            abort(403)
        ids = [int(i) for i in request.form.getlist("customer_ids") if i.isdigit()]
        action = core.f("action", "print")
        made = []
        for cid in ids:
            c = s.get(Customer, cid)
            if c is None:
                continue
            made.append(st_service.create(s, c, kind, stmt_date, start, end))
        s.commit()
        if not made:
            flash("Choose at least one customer.", "error")
            return redirect(url_for("sales.statements"))
        if action == "email":
            from pps_tools.books.services import email as email_service

            sent = 0
            for st in made:
                if st.customer.email:
                    email_service.send_statement(s, core.config(), st, base_url=_base_url(), user=core.current_user())
                    sent += 1
            s.commit()
            flash(f"Emailed {sent} statement{'s' if sent != 1 else ''}." + (
                f" {len(made) - sent} customers have no email address." if sent < len(made) else ""), "success")
            return redirect(url_for("sales.statements"))
        from pps_tools.books.services import pdf as pdf_service

        data = pdf_service.render_statements(s, made, base_url=_base_url())
        return Response(data, mimetype="application/pdf",
                        headers={"Content-Disposition": 'inline; filename="statements.pdf"'})
    return render_template("sales/statements.html", customers=customers, balances=balances, kind=kind,
                           statement_date=stmt_date, start=start, end=end, who=who)
