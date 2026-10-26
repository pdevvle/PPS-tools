"""Stripe: online invoice payments, fees, payouts, refunds, disputes and autopay.

Money flows through a bank-type account, **Stripe Balance**, that mirrors
your Stripe balance:

* A customer pays an invoice  -> Payment into Stripe Balance (applied to the invoice)
* Stripe keeps its fee        -> Expense from Stripe Balance to Merchant Processing Fees
* Stripe pays out to the bank -> Transfer from Stripe Balance to your bank account
* A refund or a dispute       -> Refund receipt / chargeback expense out of Stripe Balance

When the bank feed brings in the payout deposit, it matches the transfer.
Every Stripe object is recorded at most once (``Transaction.stripe_object_id``
is unique), so webhooks delivered twice, the success-page fallback and the
manual sync can all run without double counting.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from pps_tools.books.db import utcnow
from pps_tools.books.models import (Account, Company, Customer, PaymentMethod, StripeEvent, Transaction, User,
                                    Vendor)
from pps_tools.books.money import fmt
from pps_tools.books.services import prefs
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.accounts import system_account, system_account_id
from pps_tools.books.services.errors import StripeNotConfigured, ValidationError

log = logging.getLogger(__name__)

ZERO_DECIMAL = {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "ugx", "vnd", "vuv", "xaf",
                "xof", "xpf"}


# -- configuration & client --------------------------------------------------------------------


@dataclass
class StripeSettings:
    secret_key: Optional[str]
    webhook_secret: Optional[str]
    publishable_key: Optional[str]

    @property
    def configured(self) -> bool:
        return bool(self.secret_key)

    @property
    def test_mode(self) -> bool:
        return bool(self.secret_key and "_test_" in self.secret_key)


def settings(s: Session, config=None) -> StripeSettings:
    """Keys from the environment first, then from Settings → Payments."""
    stored = prefs.get(s, "stripe_keys") or {}
    return StripeSettings(
        secret_key=(getattr(config, "stripe_secret_key", None) or stored.get("secret_key") or None),
        webhook_secret=(getattr(config, "stripe_webhook_secret", None) or stored.get("webhook_secret") or None),
        publishable_key=(getattr(config, "stripe_publishable_key", None) or stored.get("publishable_key") or None),
    )


def enabled(s: Session, config=None) -> bool:
    return settings(s, config).configured and bool(prefs.get(s, "stripe_enabled"))


_client_factory = None


def set_client_factory(factory) -> None:
    """Tests swap in a fake Stripe client here."""
    global _client_factory
    _client_factory = factory


def client(s: Session, config=None):
    st = settings(s, config)
    if not st.secret_key:
        raise StripeNotConfigured("Connect Stripe first: add your secret key in Settings → Payments.")
    if _client_factory is not None:
        return _client_factory(st.secret_key)
    import stripe

    return stripe.StripeClient(st.secret_key, max_network_retries=2)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Read a field from a Stripe object or a plain dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except (KeyError, TypeError, AttributeError):
        return getattr(obj, key, default)


def to_minor(cents: int, currency: str) -> int:
    return cents // 100 if currency.lower() in ZERO_DECIMAL else cents


def from_minor(amount: int, currency: str) -> int:
    return amount * 100 if currency.lower() in ZERO_DECIMAL else amount


def _date(ts: Optional[int], s: Optional[Session] = None) -> date:
    """A Stripe timestamp as a date in the company's time zone."""
    if not ts:
        return date.today()
    moment = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    tz_name = None
    if s is not None:
        company = s.get(Company, 1)
        tz_name = company.timezone if company else None
    try:
        from zoneinfo import ZoneInfo

        return moment.astimezone(ZoneInfo(tz_name)).date() if tz_name else moment.astimezone().date()
    except Exception:  # unknown zone name
        return moment.astimezone().date()


# -- helpers for the books side ----------------------------------------------------------------


def clearing(s: Session) -> Account:
    return system_account(s, "stripe_clearing")


def stripe_vendor(s: Session) -> Vendor:
    v = s.scalar(select(Vendor).where(Vendor.display_name == "Stripe"))
    if v is None:
        v = Vendor(display_name="Stripe", company_name="Stripe, Inc.", website="https://stripe.com")
        s.add(v)
        s.flush()
    return v


def stripe_method(s: Session) -> PaymentMethod:
    pm = s.scalar(select(PaymentMethod).where(PaymentMethod.name == "Stripe"))
    if pm is None:
        pm = PaymentMethod(name="Stripe", kind="card")
        s.add(pm)
        s.flush()
    return pm


def already(s: Session, object_id: str) -> Optional[Transaction]:
    return s.scalar(select(Transaction).where(Transaction.stripe_object_id == object_id))


def fee_account_id(s: Session) -> int:
    key = prefs.get(s, "stripe_fee_account") or "merchant_fees"
    if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
        return int(key)
    return system_account_id(s, key)


def payout_account(s: Session) -> Optional[Account]:
    acct_id = prefs.get(s, "stripe_payout_account_id")
    if acct_id:
        acct = s.get(Account, int(acct_id))
        if acct is not None:
            return acct
    return s.scalars(select(Account).where(Account.type == "bank", Account.active.is_(True),
                                           Account.system_key.is_(None)).order_by(Account.number, Account.id)).first()


def ensure_customer(s: Session, cli, customer: Customer) -> str:
    if customer.stripe_customer_id:
        return customer.stripe_customer_id
    params = {"name": customer.display_name, "metadata": {"books_customer_id": str(customer.id)}}
    if customer.email:
        params["email"] = customer.email.split(",")[0].strip()
    if customer.phone:
        params["phone"] = customer.phone
    sc = cli.v1.customers.create(params=params)
    customer.stripe_customer_id = _get(sc, "id")
    return customer.stripe_customer_id


# -- checkout for invoices ---------------------------------------------------------------------


def create_checkout(s: Session, config, invoices: list[Transaction], base_url: str, amount_cents: Optional[int] = None,
                    save_card: bool = False, return_token: Optional[str] = None) -> str:
    """A Stripe Checkout Session paying one or more invoices. Returns its URL."""
    if not invoices:
        raise ValidationError("Nothing to pay.")
    cli = client(s, config)
    company = s.get(Company, 1)
    customer = invoices[0].customer
    if any(inv.customer_id != customer.id for inv in invoices):
        raise ValidationError("Invoices for different customers can't be paid together.")
    open_total = sum(inv.balance_cents for inv in invoices)
    if open_total <= 0:
        raise ValidationError("These invoices are already paid.")
    amount = open_total if amount_cents is None else amount_cents
    if amount <= 0 or amount > open_total:
        raise ValidationError(f"Enter an amount up to {fmt(open_total)}.")
    if amount != open_total and not prefs.get(s, "stripe_allow_partial"):
        raise ValidationError("Partial payments aren't turned on.")
    currency = (company.home_currency or "USD").lower()
    methods = []
    if all(inv.allow_online_card for inv in invoices) and prefs.get(s, "stripe_card"):
        methods.append("card")
    if all(inv.allow_online_ach for inv in invoices) and prefs.get(s, "stripe_ach") and currency == "usd":
        methods.append("us_bank_account")
    if not methods:
        raise ValidationError("Online payment isn't available for this invoice.")
    numbers = ", ".join(inv.number or str(inv.id) for inv in invoices)
    token = return_token or tx.ensure_token(invoices[0])
    meta = {"books_txn_ids": ",".join(str(inv.id) for inv in invoices), "books_kind": "invoice",
            "books_customer_id": str(customer.id)}
    if len(invoices) == 1 and amount == open_total:
        line_items = [{"price_data": {"currency": currency, "unit_amount": to_minor(amount, currency),
                                      "product_data": {"name": f"Invoice {numbers}",
                                                       "description": company.name}}, "quantity": 1}]
    elif amount == open_total:
        line_items = [{"price_data": {"currency": currency, "unit_amount": to_minor(inv.balance_cents, currency),
                                      "product_data": {"name": f"Invoice {inv.number or inv.id}"}}, "quantity": 1}
                      for inv in invoices]
    else:
        line_items = [{"price_data": {"currency": currency, "unit_amount": to_minor(amount, currency),
                                      "product_data": {"name": f"Payment toward invoice {numbers}",
                                                       "description": company.name}}, "quantity": 1}]
    pi_data: dict[str, Any] = {"metadata": meta, "description": f"{company.name}: invoice {numbers}"}
    descriptor = prefs.get(s, "stripe_statement_descriptor")
    if descriptor:
        pi_data["statement_descriptor_suffix"] = str(descriptor)[:22]
    params: dict[str, Any] = {
        "mode": "payment",
        "line_items": line_items,
        "payment_method_types": methods,
        "success_url": f"{base_url}/p/{token}/paid?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base_url}/p/{token}",
        "client_reference_id": f"books-{invoices[0].id}",
        "metadata": meta,
        "payment_intent_data": pi_data,
    }
    params["customer"] = ensure_customer(s, cli, customer)
    if save_card and prefs.get(s, "stripe_save_cards"):
        pi_data["setup_future_usage"] = "off_session"
        meta["books_save_card"] = "1"
    session = cli.v1.checkout.sessions.create(params=params,
                                              options={"idempotency_key": f"checkout-{meta['books_txn_ids']}-{amount}-"
                                                                          f"{utcnow():%Y%m%d%H%M}"})
    for inv in invoices:
        inv.stripe_checkout_session_id = _get(session, "id")
    return _get(session, "url")


# -- recording money that moved in Stripe -------------------------------------------------------


def _charge_details(cli, pi_id: str) -> dict:
    """Charge id, fee, net and card details for a PaymentIntent."""
    pi = cli.v1.payment_intents.retrieve(pi_id, params={"expand": ["latest_charge.balance_transaction"]})
    charge = _get(pi, "latest_charge")
    if isinstance(charge, str):
        charge = cli.v1.charges.retrieve(charge, params={"expand": ["balance_transaction"]})
    bt = _get(charge, "balance_transaction")
    if isinstance(bt, str):
        bt = cli.v1.balance_transactions.retrieve(bt)
    pm_details = _get(charge, "payment_method_details") or {}
    card = _get(pm_details, "card") or {}
    bank = _get(pm_details, "us_bank_account") or {}
    return {
        "pi": pi, "charge": charge, "charge_id": _get(charge, "id"),
        "balance_txn_id": _get(bt, "id"), "fee": _get(bt, "fee") or 0, "net": _get(bt, "net"),
        "settled_amount": _get(bt, "amount"), "settled_currency": _get(bt, "currency"),
        "created": _get(charge, "created") or _get(pi, "created"),
        "brand": _get(card, "brand") or ("ACH" if bank else None),
        "last4": _get(card, "last4") or _get(bank, "last4"),
        "payment_method": _get(pi, "payment_method"),
        "customer": _get(pi, "customer"),
        "metadata": dict(_get(pi, "metadata") or {}),
        "amount": _get(pi, "amount_received") or _get(pi, "amount"),
        "currency": _get(pi, "currency") or "usd",
        "status": _get(pi, "status"),
    }


def record_payment_intent(s: Session, cli, pi_id: str, user: Optional[User] = None,
                          metadata: Optional[dict] = None) -> Optional[Transaction]:
    """Record a succeeded PaymentIntent as a customer payment (+ the Stripe fee)."""
    existing = already(s, pi_id)
    if existing is not None:
        return existing
    d = _charge_details(cli, pi_id)
    if d["status"] not in ("succeeded",):
        return None
    meta = {**d["metadata"], **(metadata or {})}
    ids = [int(x) for x in (meta.get("books_txn_ids") or meta.get("books_txn_id") or "").split(",") if x.strip().isdigit()]
    invoices = [t for t in (s.get(Transaction, i) for i in ids) if t is not None and t.type == "invoice"]
    customer = None
    if invoices:
        customer = invoices[0].customer
    elif meta.get("books_customer_id", "").isdigit():
        customer = s.get(Customer, int(meta["books_customer_id"]))
    if customer is None and d["customer"]:
        customer = s.scalar(select(Customer).where(Customer.stripe_customer_id == d["customer"]))
    amount = from_minor(int(d["amount"] or 0), d["currency"])
    company = s.get(Company, 1)
    if d["settled_currency"] and d["settled_currency"].upper() == (company.home_currency or "USD").upper() \
            and d["settled_amount"] is not None and d["currency"].upper() != (company.home_currency or "USD").upper():
        amount = int(d["settled_amount"])  # charged in another currency, settled in ours
    when = _date(d["created"], s)
    clearing_acct = clearing(s)
    if customer is None:
        # A charge made outside the books (Payment Link, Dashboard): book it as an uncategorized sale.
        customer = _customer_for_unknown(s, cli, d)
    apps = []
    remaining = amount
    for inv in invoices:
        if inv.voided or inv.balance_cents <= 0:
            continue
        use = min(inv.balance_cents, remaining)
        if use > 0:
            apps.append({"txn_id": inv.id, "amount_cents": use})
            remaining -= use
    card = f"{(d['brand'] or 'card').title()} ••{d['last4']}" if d["last4"] else "Stripe"
    payment = tx.save(s, {
        "type": "payment", "customer_id": customer.id, "date": when.isoformat(), "account_id": clearing_acct.id,
        "amount_cents": amount, "payment_method_id": stripe_method(s).id, "ref_no": d["charge_id"] or pi_id,
        "memo": f"Paid online via Stripe ({card})", "applications": apps,
        "stripe_payment_intent_id": pi_id, "stripe_charge_id": d["charge_id"], "stripe_object_id": pi_id,
        "stripe_fee_cents": d["fee"], "needs_review": not invoices,
    }, user=user, source="stripe")
    if d["fee"]:
        record_fee(s, d["balance_txn_id"] or pi_id, int(d["fee"]), when, f"Stripe fee on {card} payment {d['charge_id']}",
                   user, customer_id=customer.id)
    if meta.get("books_save_card") == "1" and d["payment_method"] and d["brand"] and d["brand"] != "ACH":
        customer.stripe_payment_method_id = d["payment_method"] if isinstance(d["payment_method"], str) else \
            _get(d["payment_method"], "id")
        customer.card_brand = d["brand"]
        customer.card_last4 = d["last4"]
        customer.autopay = True
    for inv in invoices:
        if inv.viewed_at is None:
            inv.viewed_at = utcnow()
    return payment


def _customer_for_unknown(s: Session, cli, d: dict) -> Customer:
    email = None
    name = None
    charge = d["charge"]
    billing = _get(charge, "billing_details") or {}
    email = _get(billing, "email")
    name = _get(billing, "name")
    if d["customer"]:
        try:
            sc = cli.v1.customers.retrieve(d["customer"])
            email = email or _get(sc, "email")
            name = name or _get(sc, "name")
        except Exception:  # pragma: no cover - network
            pass
    if email:
        c = s.scalar(select(Customer).where(Customer.email == email))
        if c is not None:
            return c
    display = name or email or "Stripe customer"
    c = s.scalar(select(Customer).where(Customer.display_name == display))
    if c is None:
        c = Customer(display_name=display, email=email, stripe_customer_id=d["customer"])
        s.add(c)
        s.flush()
    return c


def record_fee(s: Session, object_id: str, fee_cents: int, when: date, memo: str, user: Optional[User] = None,
               customer_id: Optional[int] = None) -> Optional[Transaction]:
    key = f"fee:{object_id}"
    if already(s, key) is not None or not fee_cents:
        return already(s, key)
    sign_lines = [{"kind": "account", "account_id": fee_account_id(s), "amount_cents": abs(fee_cents), "description": memo}]
    ttype = "expense" if fee_cents > 0 else "deposit"
    if ttype == "expense":
        data = {"type": "expense", "payee": f"vendor:{stripe_vendor(s).id}", "date": when.isoformat(),
                "account_id": clearing(s).id, "memo": memo, "lines": sign_lines, "stripe_object_id": key,
                "allow_duplicate": True}
    else:  # a fee refund
        data = {"type": "deposit", "date": when.isoformat(), "account_id": clearing(s).id, "memo": memo,
                "deposits": [], "lines": sign_lines, "stripe_object_id": key}
    return tx.save(s, data, user=user, source="stripe")


def record_payout(s: Session, payout: dict, user: Optional[User] = None) -> Optional[Transaction]:
    pid = _get(payout, "id")
    if already(s, pid) is not None:
        return already(s, pid)
    status = _get(payout, "status")
    if status not in ("paid", "in_transit", "pending"):
        return None
    bank = payout_account(s)
    if bank is None:
        raise ValidationError("Choose the bank account Stripe pays out to in Settings → Payments.")
    amount = from_minor(int(_get(payout, "amount") or 0), _get(payout, "currency") or "usd")
    when = _date(_get(payout, "arrival_date") or _get(payout, "created"), s)
    if amount < 0:  # Stripe debited the bank (negative balance top-up)
        data = {"type": "transfer", "account_id": bank.id, "to_account_id": clearing(s).id, "amount_cents": -amount}
    else:
        data = {"type": "transfer", "account_id": clearing(s).id, "to_account_id": bank.id, "amount_cents": amount}
    data.update({"date": when.isoformat(), "memo": f"Stripe payout {pid}", "stripe_object_id": pid})
    return tx.save(s, data, user=user, source="stripe")


def payout_failed(s: Session, payout: dict, user: Optional[User] = None) -> None:
    t = already(s, _get(payout, "id"))
    if t is not None and not t.voided:
        tx.void(s, t, user=user, closing_password="")


def record_refund(s: Session, cli, refund: dict, user: Optional[User] = None,
                  payment: Optional[Transaction] = None, lines: Optional[list[dict]] = None) -> Optional[Transaction]:
    rid = _get(refund, "id")
    if already(s, rid) is not None:
        return already(s, rid)
    status = _get(refund, "status")
    if status in ("failed", "canceled"):
        return None
    amount = from_minor(int(_get(refund, "amount") or 0), _get(refund, "currency") or "usd")
    pi_id = _get(refund, "payment_intent")
    if payment is None and pi_id:
        payment = s.scalar(select(Transaction).where(Transaction.stripe_payment_intent_id == pi_id,
                                                     Transaction.type == "payment"))
    customer_id = payment.customer_id if payment is not None else stripe_unknown_customer(s).id
    when = _date(_get(refund, "created"), s)
    lines = lines or [{"kind": "item", "account_id": system_account_id(s, "refunds_given"),
                       "description": f"Refund of Stripe payment {payment.ref_no if payment else pi_id or ''}".strip(),
                       "amount_cents": amount, "taxable": False}]
    rr = tx.save(s, {"type": "refund_receipt", "customer_id": customer_id, "date": when.isoformat(),
                     "account_id": clearing(s).id, "payment_method_id": stripe_method(s).id, "ref_no": rid,
                     "memo": f"Stripe refund {rid}", "lines": lines, "stripe_object_id": rid,
                     "stripe_payment_intent_id": pi_id, "needs_review": payment is None, "message": ""},
                 user=user, source="stripe")
    return rr


def stripe_unknown_customer(s: Session) -> Customer:
    c = s.scalar(select(Customer).where(Customer.display_name == "Stripe customer"))
    if c is None:
        c = Customer(display_name="Stripe customer")
        s.add(c)
        s.flush()
    return c


def record_dispute(s: Session, dispute: dict, user: Optional[User] = None) -> Optional[Transaction]:
    """Money Stripe pulled back for a chargeback, as an expense from Stripe Balance."""
    did = _get(dispute, "id")
    key = f"dispute:{did}"
    if already(s, key) is not None:
        return already(s, key)
    amount = from_minor(int(_get(dispute, "amount") or 0), _get(dispute, "currency") or "usd")
    when = _date(_get(dispute, "created"), s)
    fee = 0
    for bt in _get(dispute, "balance_transactions") or []:
        fee += int(_get(bt, "fee") or 0)
    lines = [{"kind": "account", "account_id": system_account_id(s, "chargebacks"), "amount_cents": amount,
              "description": f"Disputed charge {_get(dispute, 'charge')} ({_get(dispute, 'reason') or 'no reason'})"}]
    if fee:
        lines.append({"kind": "account", "account_id": fee_account_id(s), "amount_cents": fee,
                      "description": "Stripe dispute fee"})
    return tx.save(s, {"type": "expense", "payee": f"vendor:{stripe_vendor(s).id}", "date": when.isoformat(),
                       "account_id": clearing(s).id, "memo": f"Stripe dispute {did}", "lines": lines,
                       "stripe_object_id": key, "needs_review": True, "allow_duplicate": True},
                   user=user, source="stripe")


def dispute_closed(s: Session, dispute: dict, user: Optional[User] = None) -> Optional[Transaction]:
    """A won dispute puts the money back."""
    if _get(dispute, "status") != "won":
        return None
    did = _get(dispute, "id")
    key = f"dispute-won:{did}"
    if already(s, key) is not None:
        return already(s, key)
    amount = from_minor(int(_get(dispute, "amount") or 0), _get(dispute, "currency") or "usd")
    return tx.save(s, {"type": "deposit", "date": date.today().isoformat(), "account_id": clearing(s).id,
                       "memo": f"Stripe dispute {did} won", "deposits": [], "stripe_object_id": key,
                       "lines": [{"account_id": system_account_id(s, "chargebacks"), "amount_cents": amount,
                                  "description": "Dispute reversed in your favor"}]}, user=user, source="stripe")


# -- webhooks ---------------------------------------------------------------------------------


def handle_webhook(s: Session, config, payload: bytes, sig_header: Optional[str]) -> tuple[int, str]:
    st = settings(s, config)
    if not st.webhook_secret:
        return 400, "webhook secret not configured"
    import stripe

    try:
        stripe.Webhook.construct_event(payload, sig_header, st.webhook_secret)
    except (ValueError, stripe.SignatureVerificationError):
        return 400, "invalid signature"
    event = json.loads(payload)
    return process_event(s, config, event)


def process_event(s: Session, config, event: dict) -> tuple[int, str]:
    eid = event.get("id")
    seen = s.get(StripeEvent, eid) if eid else None
    if seen is not None and seen.status in ("processed", "ignored"):
        return 200, "already processed"
    rec = seen or StripeEvent(id=eid or f"evt_local_{utcnow().timestamp()}", type=event.get("type", ""),
                              livemode=bool(event.get("livemode")), payload=event)
    if seen is None:
        s.add(rec)
    obj = (event.get("data") or {}).get("object") or {}
    etype = event.get("type", "")
    try:
        with s.begin_nested():
            txn = None
            cli = client(s, config)
            if etype in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
                if obj.get("payment_status") == "paid" and obj.get("payment_intent"):
                    txn = record_payment_intent(s, cli, obj["payment_intent"], metadata=obj.get("metadata"))
                else:
                    rec.status = "ignored"
            elif etype == "payment_intent.succeeded":
                if (obj.get("metadata") or {}).get("books_txn_ids") or (obj.get("metadata") or {}).get("books_kind"):
                    txn = record_payment_intent(s, cli, obj["id"])
                else:
                    rec.status = "ignored"  # charges made elsewhere arrive through the sync
            elif etype == "charge.refunded":
                for refund in ((obj.get("refunds") or {}).get("data") or []):
                    txn = record_refund(s, cli, refund) or txn
            elif etype in ("refund.created", "refund.updated", "charge.refund.updated"):
                if obj.get("status") == "succeeded":
                    txn = record_refund(s, cli, obj)
            elif etype == "charge.dispute.created":
                txn = record_dispute(s, obj)
            elif etype == "charge.dispute.closed":
                txn = dispute_closed(s, obj)
            elif etype == "payout.paid":
                txn = record_payout(s, obj)
            elif etype == "payout.failed":
                payout_failed(s, obj)
            else:
                rec.status = "ignored"
            if rec.status != "ignored":
                rec.status = "processed"
            rec.txn_id = txn.id if txn is not None else None
            rec.error = None
    except Exception as exc:  # recorded and retried by Stripe
        log.exception("Stripe event %s failed", eid)
        rec.status = "error"
        rec.error = str(exc)[:2000]
        return 500, "error"
    return 200, rec.status


# -- sync (catch up with everything Stripe saw) ------------------------------------------------


def sync(s: Session, config, since: Optional[int] = None, user: Optional[User] = None, limit: int = 500) -> dict:
    """Walk Stripe balance transactions and record anything the books are missing."""
    cli = client(s, config)
    params: dict[str, Any] = {"limit": 100, "expand": ["data.source"]}
    if since:
        params["created"] = {"gte": int(since)}
    counts = {"payments": 0, "fees": 0, "refunds": 0, "payouts": 0, "adjustments": 0, "skipped": 0}
    seen = 0
    page = cli.v1.balance_transactions.list(params=params)
    while True:
        for bt in _get(page, "data") or []:
            seen += 1
            kind = _get(bt, "type")
            src = _get(bt, "source")
            src_id = src if isinstance(src, str) else _get(src, "id")
            when = _date(_get(bt, "created"), s)
            with s.begin_nested():
                if kind in ("charge", "payment"):
                    pi = _get(src, "payment_intent") if not isinstance(src, str) else None
                    if pi and already(s, pi) is None:
                        record_payment_intent(s, cli, pi, user=user)
                        counts["payments"] += 1
                    elif not pi and already(s, src_id) is None:
                        counts["skipped"] += 1
                    elif _get(bt, "fee") and already(s, f"fee:{_get(bt, 'id')}") is None:
                        record_fee(s, _get(bt, "id"), int(_get(bt, "fee")), when, f"Stripe fee {_get(bt, 'id')}", user)
                        counts["fees"] += 1
                elif kind in ("refund", "payment_refund"):
                    if src_id and already(s, src_id) is None:
                        refund = src if not isinstance(src, str) else cli.v1.refunds.retrieve(src_id)
                        if record_refund(s, cli, refund, user=user):
                            counts["refunds"] += 1
                elif kind == "payout":
                    if src_id and already(s, src_id) is None:
                        payout = src if not isinstance(src, str) else cli.v1.payouts.retrieve(src_id)
                        if record_payout(s, payout, user=user):
                            counts["payouts"] += 1
                elif kind in ("stripe_fee", "application_fee", "stripe_fx_fee", "tax_fee", "reserve_transaction",
                              "adjustment", "network_cost"):
                    amount = -int(_get(bt, "amount") or 0)  # fees reduce the balance
                    key = _get(bt, "id")
                    if already(s, f"fee:{key}") is None and amount:
                        record_fee(s, key, amount, when, _get(bt, "description") or f"Stripe {kind.replace('_', ' ')}",
                                   user)
                        counts["adjustments" if kind == "adjustment" else "fees"] += 1
        if not _get(page, "has_more") or seen >= limit:
            break
        last = (_get(page, "data") or [])[-1]
        params["starting_after"] = _get(last, "id")
        page = cli.v1.balance_transactions.list(params=params)
    prefs.set_many(s, {"stripe_last_sync": int(utcnow().replace(tzinfo=timezone.utc).timestamp())})
    return counts


def balance(s: Session, config) -> Optional[int]:
    """Stripe's available + pending balance in the home currency (cents)."""
    cli = client(s, config)
    bal = cli.v1.balance.retrieve()
    company = s.get(Company, 1)
    cur = (company.home_currency or "USD").lower()
    total = 0
    for bucket in ("available", "pending"):
        for entry in _get(bal, bucket) or []:
            if (_get(entry, "currency") or "").lower() == cur:
                total += from_minor(int(_get(entry, "amount") or 0), cur)
    return total


# -- refunds and autopay -------------------------------------------------------------------------


def refund(s: Session, config, payment: Transaction, amount_cents: int, user: Optional[User],
           reason: Optional[str] = None) -> Transaction:
    if payment.type != "payment" or not payment.stripe_payment_intent_id:
        raise ValidationError("Only Stripe payments can be refunded through Stripe.")
    if amount_cents <= 0 or amount_cents > payment.total_cents:
        raise ValidationError(f"Refund between $0.01 and {fmt(payment.total_cents)}.")
    refunded = sum(t.total_cents for t in s.scalars(select(Transaction).where(
        Transaction.type == "refund_receipt", Transaction.stripe_payment_intent_id == payment.stripe_payment_intent_id,
        Transaction.voided.is_(False))))
    if refunded + amount_cents > payment.total_cents:
        raise ValidationError(f"Only {fmt(payment.total_cents - refunded)} of this payment is left to refund.")
    cli = client(s, config)
    company = s.get(Company, 1)
    params: dict[str, Any] = {"payment_intent": payment.stripe_payment_intent_id,
                              "amount": to_minor(amount_cents, company.home_currency or "usd"),
                              "metadata": {"books_payment_id": str(payment.id)}}
    if reason in ("duplicate", "fraudulent", "requested_by_customer"):
        params["reason"] = reason
    re_obj = cli.v1.refunds.create(params=params,
                                   options={"idempotency_key": f"refund-{payment.id}-{refunded}-{amount_cents}"})
    rr = record_refund(s, cli, {"id": _get(re_obj, "id"), "amount": _get(re_obj, "amount"),
                                "currency": _get(re_obj, "currency"), "status": _get(re_obj, "status"),
                                "payment_intent": payment.stripe_payment_intent_id, "created": _get(re_obj, "created")},
                       user=user, payment=payment)
    if rr is None:
        raise ValidationError("Stripe didn't accept the refund.")
    return rr


def autopay(s: Session, config, invoice: Transaction, user: Optional[User] = None) -> Optional[Transaction]:
    """Charge the customer's saved card for an invoice (recurring autopay)."""
    c = invoice.customer
    if not (c and c.autopay and c.stripe_customer_id and c.stripe_payment_method_id) or invoice.balance_cents <= 0:
        return None
    cli = client(s, config)
    company = s.get(Company, 1)
    cur = (company.home_currency or "USD").lower()
    pi = cli.v1.payment_intents.create(params={
        "amount": to_minor(invoice.balance_cents, cur), "currency": cur, "customer": c.stripe_customer_id,
        "payment_method": c.stripe_payment_method_id, "off_session": True, "confirm": True,
        "description": f"{company.name}: invoice {invoice.number}",
        "metadata": {"books_txn_ids": str(invoice.id), "books_kind": "invoice", "books_autopay": "1"},
    }, options={"idempotency_key": f"autopay-{invoice.id}-{invoice.balance_cents}"})
    if _get(pi, "status") == "succeeded":
        return record_payment_intent(s, cli, _get(pi, "id"), user=user)
    return None


def finish_checkout(s: Session, config, session_id: str) -> Optional[Transaction]:
    """Success-page fallback: record the payment without waiting for the webhook."""
    cli = client(s, config)
    cs = cli.v1.checkout.sessions.retrieve(session_id)
    if _get(cs, "payment_status") == "paid" and _get(cs, "payment_intent"):
        return record_payment_intent(s, cli, _get(cs, "payment_intent"), metadata=dict(_get(cs, "metadata") or {}))
    return None
