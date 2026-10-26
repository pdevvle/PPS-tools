"""Pages customers see without signing in: invoices, estimates, receipts,
statements, the customer portal, and paying through Stripe."""

from __future__ import annotations

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from pps_tools.books import money
from pps_tools.books.db import utcnow
from pps_tools.books.models import Customer, Statement, Transaction
from pps_tools.books.services import audit, prefs
from pps_tools.books.services import stripe_service as stripe_svc
from pps_tools.books.services.errors import BooksError, StripeNotConfigured
from pps_tools.books.web import core

bp = Blueprint("public", __name__)


def _base_url() -> str:
    return (core.config().base_url or request.host_url).rstrip("/")


def _by_token(token: str) -> Transaction:
    txn = core.db().scalar(select(Transaction).where(Transaction.public_token == token))
    if txn is None or not txn.info.customer_facing:
        abort(404)
    return txn


def _can_pay(txn: Transaction) -> bool:
    s = core.db()
    return (txn.type == "invoice" and not txn.voided and txn.balance_cents > 0
            and stripe_svc.enabled(s, core.config()) and (txn.allow_online_card or txn.allow_online_ach))


@bp.route("/p/<token>")
def view(token: str):
    s = core.db()
    txn = _by_token(token)
    if txn.viewed_at is None and core.current_user() is None:
        txn.viewed_at = utcnow()
        s.commit()
    return render_template("public/doc.html", txn=txn, can_pay=_can_pay(txn),
                           allow_partial=bool(prefs.get(s, "stripe_allow_partial")),
                           save_cards=bool(prefs.get(s, "stripe_save_cards")), company=core.company())


@bp.route("/p/<token>/pdf")
def pdf(token: str):
    txn = _by_token(token)
    from pps_tools.books.services import pdf as pdf_service

    data = pdf_service.render_transaction(core.db(), txn, base_url=_base_url())
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{pdf_service.filename_for(txn)}"'})


@bp.route("/p/<token>/pay", methods=["POST"])
def pay(token: str):
    s = core.db()
    txn = _by_token(token)
    if not _can_pay(txn):
        flash("This invoice can't be paid online right now.", "error")
        return redirect(url_for("public.view", token=token))
    amount = None
    if prefs.get(s, "stripe_allow_partial") and core.f("amount"):
        try:
            amount = money.cents(core.f("amount"))
        except money.MoneyError:
            flash("Enter the amount as a number.", "error")
            return redirect(url_for("public.view", token=token))
    try:
        url = stripe_svc.create_checkout(s, core.config(), [txn], _base_url(), amount_cents=amount,
                                         save_card=core.f_bool("save_card"), return_token=token)
        s.commit()
    except (BooksError, StripeNotConfigured) as exc:
        s.rollback()
        flash(str(exc), "error")
        return redirect(url_for("public.view", token=token))
    except Exception:  # Stripe network/API error
        s.rollback()
        current_app.logger.exception("Stripe checkout failed")
        flash("We couldn't reach the payment processor. Please try again in a minute.", "error")
        return redirect(url_for("public.view", token=token))
    return redirect(url, code=303)


@bp.route("/p/<token>/paid")
def paid(token: str):
    s = core.db()
    txn = _by_token(token)
    session_id = request.args.get("session_id")
    payment = None
    if session_id and txn.stripe_checkout_session_id == session_id:
        try:
            payment = stripe_svc.finish_checkout(s, core.config(), session_id)
            s.commit()
        except Exception:  # the webhook will record it
            s.rollback()
    s.refresh(txn)
    return render_template("public/paid.html", txn=txn, payment=payment, company=core.company())


@bp.route("/p/<token>/accept", methods=["POST"])
def accept(token: str):
    s = core.db()
    txn = _by_token(token)
    if txn.type != "estimate" or txn.status not in ("pending", "accepted"):
        abort(400)
    name = core.f("name")
    if not name:
        flash("Type your name to accept.", "error")
        return redirect(url_for("public.view", token=token))
    txn.status = "accepted"
    txn.accepted_by = name[:120]
    txn.accepted_at = utcnow()
    audit.record(s, None, "update", "transaction", txn.id, txn=txn,
                 summary=f"Estimate {txn.number} accepted online by {name}")
    s.commit()
    _notify_company(txn, f"{txn.entity_name} accepted estimate {txn.number}",
                    f"{name} accepted estimate {txn.number} for {money.fmt(txn.total_cents)}.")
    flash("Thanks! The estimate is accepted.", "success")
    return redirect(url_for("public.view", token=token))


@bp.route("/p/<token>/decline", methods=["POST"])
def decline(token: str):
    s = core.db()
    txn = _by_token(token)
    if txn.type != "estimate" or txn.status != "pending":
        abort(400)
    txn.status = "rejected"
    audit.record(s, None, "update", "transaction", txn.id, txn=txn, summary=f"Estimate {txn.number} declined online")
    s.commit()
    _notify_company(txn, f"{txn.entity_name} declined estimate {txn.number}", core.f("reason") or "No reason given.")
    flash("We've let them know. Thanks for considering it.", "info")
    return redirect(url_for("public.view", token=token))


def _notify_company(txn: Transaction, subject: str, body: str) -> None:
    company = core.company()
    if not company or not company.email:
        return
    from pps_tools.books.services import email as email_service

    s = core.db()
    try:
        email_service.send(s, core.config(), to=company.email, subject=subject, body=body,
                           object_type="transaction", object_id=txn.id)
        s.commit()
    except BooksError:
        s.rollback()


# -- customer portal ------------------------------------------------------------------------------


def _portal_customer(token: str) -> Customer:
    c = core.db().scalar(select(Customer).where(Customer.portal_token == token))
    if c is None:
        abort(404)
    return c


@bp.route("/portal/<token>")
def portal(token: str):
    s = core.db()
    c = _portal_customer(token)
    open_invoices = s.scalars(select(Transaction).where(Transaction.customer_id == c.id, Transaction.type == "invoice",
                                                        Transaction.balance_cents > 0, Transaction.voided.is_(False))
                              .order_by(Transaction.due_date)).all()
    for inv in open_invoices:
        from pps_tools.books.services.transactions import ensure_token

        ensure_token(inv)
    history = s.scalars(select(Transaction).where(Transaction.customer_id == c.id,
                                                  Transaction.type.in_(("invoice", "payment", "sales_receipt",
                                                                        "credit_memo", "estimate")),
                                                  Transaction.voided.is_(False))
                        .order_by(Transaction.date.desc()).limit(30)).all()
    for t in history:
        if t.info.customer_facing:
            from pps_tools.books.services.transactions import ensure_token

            ensure_token(t)
    s.commit()
    return render_template("public/portal.html", c=c, open_invoices=open_invoices, history=history,
                           can_pay=stripe_svc.enabled(s, core.config()), company=core.company(), token=token)


@bp.route("/portal/<token>/pay", methods=["POST"])
def portal_pay(token: str):
    s = core.db()
    c = _portal_customer(token)
    ids = [int(i) for i in request.form.getlist("invoice_ids") if i.isdigit()]
    invoices = [t for t in (s.get(Transaction, i) for i in ids)
                if t is not None and t.customer_id == c.id and t.type == "invoice" and t.balance_cents > 0]
    if not invoices:
        flash("Choose the invoices to pay.", "error")
        return redirect(url_for("public.portal", token=token))
    try:
        url = stripe_svc.create_checkout(s, core.config(), invoices, _base_url(), save_card=core.f_bool("save_card"),
                                         return_token=invoices[0].public_token)
        s.commit()
    except (BooksError, StripeNotConfigured) as exc:
        s.rollback()
        flash(str(exc), "error")
        return redirect(url_for("public.portal", token=token))
    except Exception:
        s.rollback()
        flash("We couldn't reach the payment processor. Please try again in a minute.", "error")
        return redirect(url_for("public.portal", token=token))
    return redirect(url, code=303)


@bp.route("/s/<token>")
def statement(token: str):
    s = core.db()
    st = s.scalar(select(Statement).where(Statement.public_token == token))
    if st is None:
        abort(404)
    from pps_tools.books.services import pdf as pdf_service

    data = pdf_service.render_statements(s, [st], base_url=_base_url())
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": 'inline; filename="statement.pdf"'})
