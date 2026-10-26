"""Payments: the Stripe connection, balance check, sync and refunds."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from pps_tools.books import money
from pps_tools.books.models import StripeEvent, Transaction
from pps_tools.books.services import prefs
from pps_tools.books.services import stripe_service as stripe_svc
from pps_tools.books.services.accounts import balances_by_account
from pps_tools.books.services.errors import BooksError, StripeNotConfigured
from pps_tools.books.web import core

bp = Blueprint("payments", __name__)


@bp.route("/payments")
@core.requires("sales.view")
def index():
    s = core.db()
    cfg = core.config()
    st = stripe_svc.settings(s, cfg)
    clearing = stripe_svc.clearing(s)
    books_balance = balances_by_account(s).get(clearing.id, 0)
    stripe_balance = None
    error = None
    if st.configured and request.args.get("check") == "1":
        try:
            stripe_balance = stripe_svc.balance(s, cfg)
        except Exception as exc:  # network, bad key
            error = str(exc)
    recent = s.scalars(select(Transaction).where(Transaction.source == "stripe")
                       .order_by(Transaction.date.desc(), Transaction.id.desc()).limit(40)).all()
    events = s.scalars(select(StripeEvent).order_by(StripeEvent.received_at.desc()).limit(15)).all()
    month_start = core.today().replace(day=1)
    collected = s.scalar(select(func.coalesce(func.sum(Transaction.total_cents), 0)).where(
        Transaction.type == "payment", Transaction.source == "stripe", Transaction.voided.is_(False),
        Transaction.date >= month_start)) or 0
    fees = sum(t.total_cents for t in s.scalars(select(Transaction).where(
        Transaction.type == "expense", Transaction.source == "stripe", Transaction.date >= month_start,
        Transaction.voided.is_(False), Transaction.stripe_object_id.like("fee:%"))))
    last_sync = prefs.get(s, "stripe_last_sync")
    return render_template("payments/index.html", st=st, enabled=stripe_svc.enabled(s, cfg), clearing=clearing,
                           books_balance=books_balance, stripe_balance=stripe_balance, error=error, recent=recent,
                           events=events, collected=collected, fees=fees,
                           last_sync=datetime.fromtimestamp(last_sync, tz=timezone.utc) if last_sync else None,
                           payout_account=stripe_svc.payout_account(s),
                           webhook_url=f"{(cfg.base_url or request.host_url).rstrip('/')}{url_for('stripe_hooks.webhook')}")


@bp.route("/payments/sync", methods=["POST"])
@core.requires("banking.edit")
def sync():
    s = core.db()
    days = core.f_int("days") or 30
    since = int((datetime.now(tz=timezone.utc) - timedelta(days=days)).timestamp())
    try:
        counts = stripe_svc.sync(s, core.config(), since=since, user=core.current_user())
        s.commit()
        flash("Synced with Stripe: " + ", ".join(f"{v} {k}" for k, v in counts.items() if v and k != "skipped")
              + (" — nothing new." if not any(v for k, v in counts.items() if k != "skipped") else "."), "success")
    except StripeNotConfigured as exc:
        s.rollback()
        flash(str(exc), "error")
    except BooksError as exc:
        s.rollback()
        flash(str(exc), "error")
    except Exception as exc:  # Stripe API errors
        s.rollback()
        flash(f"Stripe said: {exc}", "error")
    return redirect(url_for("payments.index"))


@bp.route("/payments/refund/<int:txn_id>", methods=["GET", "POST"])
@core.requires("payments.refund")
def refund(txn_id: int):
    s = core.db()
    payment = s.get(Transaction, txn_id) or abort(404)
    if payment.type != "payment" or not payment.stripe_payment_intent_id:
        abort(404)
    refunded = sum(t.total_cents for t in s.scalars(select(Transaction).where(
        Transaction.type == "refund_receipt", Transaction.stripe_payment_intent_id == payment.stripe_payment_intent_id,
        Transaction.voided.is_(False))))
    if request.method == "POST":
        try:
            amount = money.cents(core.f("amount") or "0")
            rr = stripe_svc.refund(s, core.config(), payment, amount, core.current_user(), reason=core.f("reason"))
            s.commit()
            flash(f"Refunded {money.fmt(amount)} to {payment.entity_name}'s card. Stripe keeps its original fee.",
                  "success")
            return redirect(url_for("txn.go", txn_id=rr.id))
        except (BooksError, money.MoneyError) as exc:
            s.rollback()
            flash(str(exc), "error")
        except Exception as exc:
            s.rollback()
            flash(f"Stripe said: {exc}", "error")
    return render_template("payments/refund.html", payment=payment, refunded=refunded,
                           remaining=payment.total_cents - refunded)
