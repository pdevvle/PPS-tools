"""Stripe: checkout, webhooks, fees, payouts, refunds, disputes, sync and autopay,
against a fake Stripe client and real signed webhook payloads."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from pps_tools.books.models import StripeEvent, Transaction
from pps_tools.books.services import prefs
from pps_tools.books.services import stripe_service as st
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.errors import ValidationError

WHSEC = "whsec_test_secret"
NOW = 1767225600  # 2026-01-01T00:00:00Z


class _NS:
    """A namespace whose methods record their calls."""

    def __init__(self, fake, name):
        self._fake, self._name = fake, name

    def __getattr__(self, method):
        def call(*args, **kwargs):
            self._fake.calls.append((f"{self._name}.{method}", args, kwargs))
            return self._fake.handle(self._name, method, *args, **kwargs)
        return call


class FakeStripe:
    """Just enough of StripeClient.v1 for the books."""

    def __init__(self):
        self.calls = []
        self.intents: dict[str, dict] = {}
        self.refunds: dict[str, dict] = {}
        self.payouts: dict[str, dict] = {}
        self.balance_txns: list[dict] = []
        self.sessions: dict[str, dict] = {}
        self.n = 0
        self.v1 = SimpleNamespace(
            customers=_NS(self, "customers"), payment_intents=_NS(self, "payment_intents"),
            charges=_NS(self, "charges"), balance_transactions=_NS(self, "balance_transactions"),
            refunds=_NS(self, "refunds"), payouts=_NS(self, "payouts"), balance=_NS(self, "balance"),
            checkout=SimpleNamespace(sessions=_NS(self, "checkout.sessions")))

    def _id(self, prefix):
        self.n += 1
        return f"{prefix}_{self.n:04d}"

    def add_intent(self, amount, fee, metadata=None, customer=None, brand="visa", last4="4242", pm="pm_card_1"):
        pi_id, ch_id, bt_id = self._id("pi"), self._id("ch"), self._id("txn")
        bt = {"id": bt_id, "type": "charge", "amount": amount, "fee": fee, "net": amount - fee, "currency": "usd",
              "created": NOW, "source": {"id": ch_id, "object": "charge", "payment_intent": pi_id}}
        charge = {"id": ch_id, "created": NOW, "balance_transaction": bt, "billing_details": {"email": None},
                  "payment_method_details": {"card": {"brand": brand, "last4": last4}}}
        self.intents[pi_id] = {"id": pi_id, "status": "succeeded", "amount": amount, "amount_received": amount,
                               "currency": "usd", "created": NOW, "customer": customer, "payment_method": pm,
                               "metadata": metadata or {}, "latest_charge": charge}
        self.balance_txns.append(bt)
        return pi_id

    def handle(self, ns, method, *args, params=None, options=None):
        params = params or {}
        if ns == "customers" and method == "create":
            return {"id": self._id("cus"), **params}
        if ns == "checkout.sessions" and method == "create":
            sid = self._id("cs")
            self.sessions[sid] = {"id": sid, "url": f"https://checkout.stripe.test/{sid}", **params}
            return self.sessions[sid]
        if ns == "checkout.sessions" and method == "retrieve":
            return self.sessions[args[0]]
        if ns == "payment_intents" and method == "retrieve":
            return self.intents[args[0]]
        if ns == "payment_intents" and method == "create":
            return self.intents[self.add_intent(params["amount"], round(params["amount"] * 0.029 + 30),
                                                metadata=params["metadata"], customer=params["customer"])]
        if ns == "refunds" and method == "create":
            rid = self._id("re")
            self.refunds[rid] = {"id": rid, "amount": params["amount"], "currency": "usd", "status": "succeeded",
                                 "payment_intent": params["payment_intent"], "created": NOW + 86400}
            return self.refunds[rid]
        if ns == "refunds" and method == "retrieve":
            return self.refunds[args[0]]
        if ns == "payouts" and method == "retrieve":
            return self.payouts[args[0]]
        if ns == "balance_transactions" and method == "list":
            return {"data": list(self.balance_txns), "has_more": False}
        if ns == "balance" and method == "retrieve":
            return {"available": [{"amount": 0, "currency": "usd"}], "pending": []}
        raise AssertionError(f"unexpected call {ns}.{method}")


@pytest.fixture
def fake():
    f = FakeStripe()
    st.set_client_factory(lambda key: f)
    yield f
    st.set_client_factory(None)


@pytest.fixture
def cfg():
    return SimpleNamespace(stripe_secret_key="sk_test_abc", stripe_webhook_secret=WHSEC, stripe_publishable_key=None)


@pytest.fixture
def invoice(s, b):
    prefs.set_many(s, {"stripe_enabled": True})
    cust = b.customer("Harbor Bakery", email="pay@harbor.example.com")
    item = b.service()
    inv = tx.save(s, {"type": "invoice", "customer_id": cust.id, "date": "2026-01-01",
                      "lines": [{"item_id": item.id, "qty": "1000", "rate": "0.10", "taxable": False}]})
    assert inv.total_cents == 10000
    return inv


def _event(etype, obj, eid=None):
    return {"id": eid or f"evt_{etype.replace('.', '_')}_{obj.get('id')}", "type": etype, "livemode": False,
            "data": {"object": obj}}


def _signed(payload: bytes, secret=WHSEC, ts=None) -> str:
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def test_checkout_session_for_an_invoice(s, b, fake, cfg, invoice):
    url = st.create_checkout(s, cfg, [invoice], "https://books.example.com")
    assert url.startswith("https://checkout.stripe.test/")
    _, _, kwargs = next(c for c in fake.calls if c[0] == "checkout.sessions.create")
    p = kwargs["params"]
    assert p["mode"] == "payment" and p["payment_method_types"] == ["card", "us_bank_account"]
    assert p["line_items"][0]["price_data"]["unit_amount"] == 10000
    assert p["metadata"]["books_txn_ids"] == str(invoice.id)
    assert p["success_url"].startswith("https://books.example.com/p/") and "{CHECKOUT_SESSION_ID}" in p["success_url"]
    assert p["customer"].startswith("cus_") and invoice.customer.stripe_customer_id == p["customer"]
    assert "idempotency_key" in kwargs["options"]
    assert invoice.stripe_checkout_session_id.startswith("cs_")


def test_partial_payment_needs_the_setting(s, b, fake, cfg, invoice):
    with pytest.raises(ValidationError, match="Partial"):
        st.create_checkout(s, cfg, [invoice], "https://x", amount_cents=4000)
    prefs.set_many(s, {"stripe_allow_partial": True})
    st.create_checkout(s, cfg, [invoice], "https://x", amount_cents=4000)
    with pytest.raises(ValidationError):
        st.create_checkout(s, cfg, [invoice], "https://x", amount_cents=20000)


def test_paid_checkout_records_payment_and_fee_once(s, b, fake, cfg, invoice):
    pi = fake.add_intent(10000, 320, metadata={"books_txn_ids": str(invoice.id), "books_kind": "invoice"})
    session = {"id": "cs_1", "payment_status": "paid", "payment_intent": pi,
               "metadata": {"books_txn_ids": str(invoice.id)}}
    status, msg = st.process_event(s, cfg, _event("checkout.session.completed", session))
    assert (status, msg) == (200, "processed")
    assert invoice.balance_cents == 0
    assert b.balance("stripe_clearing") == 10000 - 320
    assert b.balance("merchant_fees") == 320
    pay = s.scalar(select(Transaction).where(Transaction.stripe_payment_intent_id == pi))
    assert pay.type == "payment" and pay.memo == "Paid online via Stripe (Visa ••4242)"
    # The same event again, and the payment_intent.succeeded that also arrives: nothing doubles.
    assert st.process_event(s, cfg, _event("checkout.session.completed", session)) == (200, "already processed")
    st.process_event(s, cfg, _event("payment_intent.succeeded", fake.intents[pi]))
    assert s.scalar(select(Transaction.id).where(Transaction.type == "payment").offset(1)) is None
    assert b.balance("stripe_clearing") == 9680
    b.assert_balanced()


def test_payout_moves_stripe_balance_to_the_bank(s, b, fake, cfg, invoice):
    pi = fake.add_intent(10000, 320, metadata={"books_txn_ids": str(invoice.id)})
    st.process_event(s, cfg, _event("payment_intent.succeeded", fake.intents[pi]))
    payout = {"id": "po_1", "status": "paid", "amount": 9680, "currency": "usd", "arrival_date": NOW + 2 * 86400}
    st.process_event(s, cfg, _event("payout.paid", payout))
    assert b.balance("stripe_clearing") == 0
    assert b.balance("Checking") == 9680
    st.process_event(s, cfg, _event("payout.paid", payout, eid="evt_redelivered"))
    assert b.balance("Checking") == 9680
    st.process_event(s, cfg, _event("payout.failed", dict(payout, status="failed")))
    assert b.balance("Checking") == 0 and b.balance("stripe_clearing") == 9680
    b.assert_balanced()


def test_refund_through_stripe_and_its_webhook(s, b, fake, cfg, invoice):
    pi = fake.add_intent(10000, 320, metadata={"books_txn_ids": str(invoice.id)})
    st.process_event(s, cfg, _event("payment_intent.succeeded", fake.intents[pi]))
    pay = s.scalar(select(Transaction).where(Transaction.type == "payment"))
    rr = st.refund(s, cfg, pay, 2500, user=None, reason="requested_by_customer")
    assert rr.type == "refund_receipt" and rr.total_cents == 2500
    assert b.balance("stripe_clearing") == 9680 - 2500
    with pytest.raises(ValidationError, match="left to refund"):
        st.refund(s, cfg, pay, 8000, user=None)
    refund_obj = fake.refunds[rr.stripe_object_id]
    st.process_event(s, cfg, _event("charge.refunded", {"id": "ch_x", "refunds": {"data": [refund_obj]}}))
    assert len(s.scalars(select(Transaction).where(Transaction.type == "refund_receipt")).all()) == 1
    b.assert_balanced()


def test_dispute_lost_then_won(s, b, fake, cfg, invoice):
    pi = fake.add_intent(10000, 320, metadata={"books_txn_ids": str(invoice.id)})
    st.process_event(s, cfg, _event("payment_intent.succeeded", fake.intents[pi]))
    dispute = {"id": "dp_1", "amount": 10000, "currency": "usd", "charge": "ch_x", "reason": "fraudulent",
               "created": NOW + 86400, "balance_transactions": [{"fee": 1500}], "status": "needs_response"}
    st.process_event(s, cfg, _event("charge.dispute.created", dispute))
    assert b.balance("stripe_clearing") == 9680 - 10000 - 1500
    assert b.balance("chargebacks") == 10000
    st.process_event(s, cfg, _event("charge.dispute.closed", dict(dispute, status="won")))
    assert b.balance("chargebacks") == 0
    b.assert_balanced()


def test_unknown_events_are_ignored_and_errors_kept_for_retry(s, b, fake, cfg, invoice):
    assert st.process_event(s, cfg, _event("customer.created", {"id": "cus_9"})) == (200, "ignored")
    status, _ = st.process_event(s, cfg, _event("payment_intent.succeeded",
                                                {"id": "pi_missing", "metadata": {"books_kind": "invoice"}}))
    assert status == 500
    rec = s.get(StripeEvent, "evt_payment_intent_succeeded_pi_missing")
    assert rec.status == "error" and rec.error


def test_sync_records_what_webhooks_missed(s, b, fake, cfg, invoice):
    fake.add_intent(10000, 320, metadata={"books_txn_ids": str(invoice.id)})
    fake.payouts["po_7"] = {"id": "po_7", "status": "paid", "amount": 9680, "currency": "usd", "arrival_date": NOW}
    fake.balance_txns.append({"id": "txn_po", "type": "payout", "amount": -9680, "fee": 0, "currency": "usd",
                              "created": NOW, "source": "po_7"})
    fake.balance_txns.append({"id": "txn_fee", "type": "stripe_fee", "amount": -1500, "fee": 0, "currency": "usd",
                              "created": NOW, "source": None, "description": "Radar for Fraud Teams"})
    counts = st.sync(s, cfg)
    assert counts["payments"] == 1 and counts["payouts"] == 1 and counts["fees"] == 1
    assert invoice.balance_cents == 0
    assert b.balance("stripe_clearing") == 9680 - 9680 - 1500
    again = st.sync(s, cfg)
    assert again["payments"] == again["payouts"] == again["fees"] == 0
    b.assert_balanced()


def test_autopay_charges_the_saved_card(s, b, fake, cfg, invoice):
    cust = invoice.customer
    cust.stripe_customer_id, cust.stripe_payment_method_id, cust.autopay = "cus_1", "pm_1", True
    pay = st.autopay(s, cfg, invoice)
    assert pay is not None and invoice.balance_cents == 0
    _, _, kwargs = next(c for c in fake.calls if c[0] == "payment_intents.create")
    assert kwargs["params"]["off_session"] is True and kwargs["params"]["confirm"] is True
    assert kwargs["options"]["idempotency_key"] == f"autopay-{invoice.id}-10000"
    assert st.autopay(s, cfg, invoice) is None  # nothing left to charge


def test_saving_a_card_at_checkout_turns_on_autopay(s, b, fake, cfg, invoice):
    pi = fake.add_intent(10000, 320, metadata={"books_txn_ids": str(invoice.id), "books_save_card": "1"},
                         brand="mastercard", last4="5555", pm="pm_saved")
    st.record_payment_intent(s, fake, pi)
    c = invoice.customer
    assert (c.stripe_payment_method_id, c.card_brand, c.card_last4, c.autopay) == ("pm_saved", "mastercard", "5555", True)


def test_zero_decimal_currency_conversion():
    assert st.to_minor(150000, "jpy") == 1500 and st.from_minor(1500, "JPY") == 150000
    assert st.to_minor(1234, "usd") == 1234


def test_signed_webhook_through_the_app(tmp_path, fake):
    from pps_tools.books.config import Config
    from pps_tools.books.services import setup
    from pps_tools.books.web.app import create_app

    app = create_app(Config(data_dir=tmp_path, testing=True, secret_key="k" * 32, stripe_secret_key="sk_test_1",
                            stripe_webhook_secret=WHSEC))
    from pps_tools.books.models import Customer
    from pps_tools.books.services.accounts import system_account_id

    s = app.extensions["books"]["session_factory"]()
    setup.create_company(s, "Hook Co", "a@example.com", "A", "password123")
    cust = Customer(display_name="Paying Customer", email="payer@example.com")
    s.add(cust)
    s.flush()
    inv = tx.save(s, {"type": "invoice", "customer_id": cust.id, "date": "2026-01-01",
                      "lines": [{"account_id": system_account_id(s, "services_income"), "amount": "50"}]})
    s.commit()
    pi = fake.add_intent(5000, 175, metadata={"books_txn_ids": str(inv.id)})
    payload = json.dumps(_event("payment_intent.succeeded", fake.intents[pi])).encode()
    c = app.test_client()
    bad = c.post("/stripe/webhook", data=payload, headers={"Stripe-Signature": _signed(payload, "whsec_wrong")})
    assert bad.status_code == 400
    stale = c.post("/stripe/webhook", data=payload, headers={"Stripe-Signature": _signed(payload, ts=NOW - 86400)})
    assert stale.status_code == 400  # outside Stripe's replay window
    ok = c.post("/stripe/webhook", data=payload, headers={"Stripe-Signature": _signed(payload)})
    assert ok.status_code == 200 and ok.get_json()["status"] == "processed"
    again = c.post("/stripe/webhook", data=payload, headers={"Stripe-Signature": _signed(payload)})
    assert again.get_json()["status"] == "already processed"
    s.close()
    s = app.extensions["books"]["session_factory"]()
    assert s.get(Transaction, inv.id).balance_cents == 0
    s.close()
