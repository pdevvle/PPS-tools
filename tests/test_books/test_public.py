"""What customers see without signing in: invoice links, paying through Stripe
Checkout, estimates, the portal and statements."""

from __future__ import annotations

import re
from datetime import date

import pytest
from sqlalchemy import select

from pps_tools.books.config import Config
from pps_tools.books.models import Customer, EmailMessage, Transaction
from pps_tools.books.services import prefs, setup, statements
from pps_tools.books.services import stripe_service as st
from pps_tools.books.services import transactions as tx
from pps_tools.books.services.accounts import system_account_id
from pps_tools.books.web.app import create_app
from tests.test_books.test_stripe import WHSEC, FakeStripe


@pytest.fixture
def fake():
    f = FakeStripe()
    st.set_client_factory(lambda key: f)
    yield f
    st.set_client_factory(None)


@pytest.fixture
def app(tmp_path, fake):
    app = create_app(Config(data_dir=tmp_path, testing=True, secret_key="p" * 32, stripe_secret_key="sk_test_1",
                            stripe_webhook_secret=WHSEC, base_url="https://books.example.com"))
    s = app.extensions["books"]["session_factory"]()
    setup.create_company(s, "Riverbend Print Co.", "owner@example.com", "Owner", "password123")
    from pps_tools.books.models import Company

    s.get(Company, 1).email = "owner@example.com"
    prefs.set_many(s, {"stripe_enabled": True, "stripe_allow_partial": True})
    cust = Customer(display_name="Harbor Bakery", email="pay@harbor.example.com", taxable=True)
    s.add(cust)
    s.flush()
    income = system_account_id(s, "services_income")
    inv = tx.save(s, {"type": "invoice", "customer_id": cust.id, "date": "2026-01-02", "due_date": "2026-02-01",
                      "lines": [{"account_id": income, "amount": "120", "description": "Menus"}]})
    est = tx.save(s, {"type": "estimate", "customer_id": cust.id, "date": "2026-01-03",
                      "lines": [{"account_id": income, "amount": "300", "description": "Banners"}]})
    tx.ensure_token(inv)
    tx.ensure_token(est)
    stmt = statements.create(s, cust, "open_item", date(2026, 1, 31), None, None)
    s.commit()
    app.ids = {"inv": inv.id, "est": est.id, "cust": cust.id, "inv_token": inv.public_token,
               "est_token": est.public_token, "portal": cust.portal_token, "stmt": stmt.public_token}
    s.close()
    return app


def _csrf_from(page) -> str:
    return re.search(rb'name="_csrf" value="([^"]+)"', page.data).group(1).decode()


def _db(app):
    return app.extensions["books"]["session_factory"]()


def test_customer_pays_an_invoice_through_checkout(app, fake):
    c = app.test_client()
    ids = app.ids
    page = c.get(f"/p/{ids['inv_token']}")
    assert page.status_code == 200 and b"$120.00" in page.data and b"Pay" in page.data
    r = c.post(f"/p/{ids['inv_token']}/pay", data={"_csrf": _csrf_from(page), "amount": "", "save_card": "1"})
    assert r.status_code == 303 and r.headers["Location"].startswith("https://checkout.stripe.test/cs_")
    session_id = r.headers["Location"].rsplit("/", 1)[1]
    params = fake.sessions[session_id]
    assert params["success_url"].startswith(f"https://books.example.com/p/{ids['inv_token']}/paid")
    assert params["payment_intent_data"]["setup_future_usage"] == "off_session"
    # The customer pays; Stripe redirects back before the webhook arrives.
    pi = fake.add_intent(12000, 378, metadata=params["metadata"])
    fake.sessions[session_id].update(payment_status="paid", payment_intent=pi)
    done = c.get(f"/p/{ids['inv_token']}/paid?session_id={session_id}")
    assert done.status_code == 200
    s = _db(app)
    assert s.get(Transaction, ids["inv"]).balance_cents == 0
    assert s.get(Customer, ids["cust"]).autopay  # the card was saved for next time
    s.close()
    # Then the webhook for the same checkout: recorded once, not twice.
    status, msg = st.process_event(_db(app), app.extensions["books"]["config"],
                                   {"id": "evt_cs", "type": "checkout.session.completed",
                                    "data": {"object": dict(fake.sessions[session_id])}})
    assert status == 200 and msg in ("processed", "already processed")
    s = _db(app)
    assert len(s.scalars(select(Transaction).where(Transaction.type == "payment")).all()) == 1
    s.close()


def test_partial_payment_amount_and_closed_invoice(app, fake):
    c = app.test_client()
    tok = app.ids["inv_token"]
    page = c.get(f"/p/{tok}")
    r = c.post(f"/p/{tok}/pay", data={"_csrf": _csrf_from(page), "amount": "50.00"})
    session = fake.sessions[r.headers["Location"].rsplit("/", 1)[1]]
    assert session["line_items"][0]["price_data"]["unit_amount"] == 5000
    s = _db(app)
    inv = s.get(Transaction, app.ids["inv"])
    tx.void(s, inv)
    s.commit()
    s.close()
    r = c.post(f"/p/{tok}/pay", data={"_csrf": _csrf_from(page)})
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/p/{tok}")  # can't pay a voided invoice


def test_pay_form_needs_its_csrf_token(app):
    c = app.test_client()
    c.get(f"/p/{app.ids['inv_token']}")
    assert c.post(f"/p/{app.ids['inv_token']}/pay", data={}).status_code == 400


def test_estimate_accepted_online_notifies_the_company(app):
    c = app.test_client()
    tok = app.ids["est_token"]
    page = c.get(f"/p/{tok}")
    assert page.status_code == 200 and b"Accept" in page.data
    r = c.post(f"/p/{tok}/accept", data={"_csrf": _csrf_from(page), "name": "Dana Whitfield"})
    assert r.status_code == 302
    s = _db(app)
    est = s.get(Transaction, app.ids["est"])
    assert est.status == "accepted" and est.accepted_by == "Dana Whitfield"
    note = s.scalar(select(EmailMessage).where(EmailMessage.to_addr == "owner@example.com"))
    assert "accepted estimate" in note.subject
    s.close()


def test_portal_lists_open_invoices_and_pays_several(app, fake):
    c = app.test_client()
    page = c.get(f"/portal/{app.ids['portal']}")
    assert page.status_code == 200 and b"Harbor Bakery" in page.data and b"$120.00" in page.data
    r = c.post(f"/portal/{app.ids['portal']}/pay", data={"_csrf": _csrf_from(page),
                                                          "invoice_ids": [str(app.ids["inv"])]})
    assert r.status_code == 303
    assert c.get("/portal/not-a-real-token").status_code == 404


def test_statement_link_is_a_pdf(app):
    c = app.test_client()
    r = c.get(f"/s/{app.ids['stmt']}")
    assert r.status_code == 200 and r.data[:5] == b"%PDF-"
    assert c.get(f"/p/{app.ids['inv_token']}/pdf").data[:5] == b"%PDF-"


def test_unknown_or_internal_documents_are_not_public(app):
    c = app.test_client()
    assert c.get("/p/nope").status_code == 404
    s = _db(app)
    je = tx.save(s, {"type": "journal_entry", "date": "2026-01-05", "lines": [
        {"account_id": system_account_id(s, "uncategorized_expense"), "debit_cents": 100},
        {"account_id": system_account_id(s, "opening_balance_equity"), "credit_cents": 100}]})
    tok = tx.ensure_token(je)
    s.commit()
    s.close()
    assert c.get(f"/p/{tok}").status_code == 404
