"""POST /stripe/webhook — Stripe event deliveries (signature-verified)."""

from __future__ import annotations

from flask import Blueprint, request

from pps_tools.books.services import stripe_service as stripe_svc
from pps_tools.books.web import core

bp = Blueprint("stripe_hooks", __name__)


@bp.route("/stripe/webhook", methods=["POST"])
def webhook():
    s = core.db()
    status, message = stripe_svc.handle_webhook(s, core.config(), request.get_data(),
                                                request.headers.get("Stripe-Signature"))
    s.commit()  # on errors this keeps the event row and its message; Stripe retries the delivery
    return {"status": message}, status
