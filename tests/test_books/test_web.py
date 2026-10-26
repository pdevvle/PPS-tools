"""The web app against the demo company: every page renders, forms post."""

from __future__ import annotations

import re
from datetime import date

import pytest
from sqlalchemy import select

from pps_tools.books.config import Config
from pps_tools.books.models import (Account, Attachment, BankFeedItem, BankRule, Budget, Customer, EmailMessage,
                                    Employee, Item, MileageTrip, Reconciliation, RecurringTemplate, SavedReport,
                                    TimeActivity, Transaction, User, Vendor)
from pps_tools.books.services import demo
from pps_tools.books.services.reports import REGISTRY
from pps_tools.books.txn_types import TXN_TYPES
from pps_tools.books.web.app import create_app

PASSWORD = "demo-password-1"


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    data = tmp_path_factory.mktemp("books")
    app = create_app(Config(data_dir=data, testing=True, secret_key="test-secret-" + "x" * 20))
    with app.app_context():
        s = app.extensions["books"]["session_factory"]()
        demo.build(s, PASSWORD, today=date.today())
        s.commit()
        s.close()
    return app


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    page = c.get("/login")
    assert page.status_code == 200
    r = c.post("/login", data={"email": demo.DEMO_EMAIL, "password": PASSWORD, "_csrf": _csrf(c)})
    assert r.status_code == 302, r.data[:500]
    return c


def _csrf(c) -> str:
    with c.session_transaction() as sess:
        if "_csrf" not in sess:
            import secrets

            sess["_csrf"] = secrets.token_urlsafe(32)
        return sess["_csrf"]


def _db(app):
    return app.extensions["books"]["session_factory"]()


def _arg_values(app) -> dict[str, list]:
    s = _db(app)
    first = lambda model: [x for x in s.scalars(select(model.id).limit(1))]  # noqa: E731
    txn_ids = []
    for t in TXN_TYPES:
        tid = s.scalar(select(Transaction.id).where(Transaction.type == t).limit(1))
        if tid:
            txn_ids.append(tid)
    out = {
        "txn_id": txn_ids, "slug": [t.slug for t in TXN_TYPES.values()], "key": list(REGISTRY),
        "item_id": first(Item), "cid": first(Customer), "vid": first(Vendor), "eid": first(Employee),
        "account_id": [a for a in s.scalars(select(Account.id).where(Account.type.in_(("bank", "expense", "income"))).limit(3))],
        "kind": ["terms", "payment-methods", "classes", "locations", "tags", "vehicles"],
        "rule_id": first(BankRule), "rec_id": first(Reconciliation), "tpl_id": first(RecurringTemplate),
        "budget_id": first(Budget), "pid": [c for c in s.scalars(select(Customer.id).where(Customer.is_project.is_(True)))],
        "ta_id": first(TimeActivity), "trip_id": first(MileageTrip), "att_id": first(Attachment),
        "msg_id": first(EmailMessage), "uid": first(User), "saved_id": first(SavedReport),
        "what": ["zip", "backup"], "entry_id": [], "cid_portal": [],
    }
    from pps_tools.books.models import AuditLog

    out["entry_id"] = first(AuditLog)
    s.close()
    return out


SKIP = {
    "auth.setup", "auth.logout", "static", "settings.qbo_callback", "settings.import_map", "public.doc",
    "public.paid", "public.portal", "public.pay", "public.statement", "attachments.download",
}


def test_every_page_renders(app, client):
    values = _arg_values(app)
    failures = []
    visited = 0
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods or rule.endpoint in SKIP or rule.endpoint.startswith("api.") \
                or rule.endpoint.startswith("public."):
            continue
        args = list(rule.arguments)
        combos = [{}]
        for a in args:
            vals = values.get(a)
            if not vals:
                combos = []
                break
            if a in ("key", "slug", "txn_id", "kind"):
                combos = [dict(c, **{a: v}) for c in combos for v in vals]
            else:
                combos = [dict(c, **{a: vals[0]}) for c in combos]
        for combo in combos:
            with app.test_request_context():
                from flask import url_for

                try:
                    url = url_for(rule.endpoint, **combo)
                except Exception as exc:  # pragma: no cover
                    failures.append((rule.endpoint, combo, f"url_for: {exc}"))
                    continue
            r = client.get(url)
            visited += 1
            if r.status_code >= 500 or (r.status_code >= 400 and r.status_code != 404):
                failures.append((url, r.status_code, _error_text(r)))
    assert visited > 150
    assert not failures, "\n".join(map(str, failures[:40]))


def _error_text(r) -> str:
    text = r.get_data(as_text=True)
    m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S)
    return (m.group(1).strip() if m else text[:300]).replace("\n", " ")


def test_new_transaction_forms_render_for_every_type(client):
    for info in TXN_TYPES.values():
        r = client.get(f"/t/{info.slug}/new")
        assert r.status_code == 200, (info.slug, r.status_code)


def test_new_invoice_for_a_customer_offers_unbilled_time(app, client):
    s = _db(app)
    cid = s.scalar(select(TimeActivity.customer_id).where(TimeActivity.billable.is_(True),
                                                          TimeActivity.billed_txn_id.is_(None)).limit(1))
    s.close()
    assert cid, "the demo company has unbilled time"
    r = client.get(f"/t/invoices/new?customer_id={cid}")
    assert r.status_code == 200, _error_text(r)
    assert b"Add billable charges" in r.data and b"data-billable=" in r.data


def test_create_invoice_through_the_form(app, client):
    s = _db(app)
    cust = s.scalar(select(Customer).where(Customer.is_project.is_(False)).limit(1))
    item = s.scalar(select(Item).where(Item.type == "service").limit(1))
    s.close()
    r = client.post("/t/invoices/new", data={
        "_csrf": _csrf(client), "next_action": "save", "customer_id": cust.id, "date": date.today().isoformat(),
        "has_lines": "1", "l-0-pos": "0", "l-0-kind": "item", "l-0-item_id": item.id, "l-0-qty": "3",
        "l-0-rate": "10.00", "l-0-taxable": "1"})
    assert r.status_code == 302, _error_text(r)
    page = client.get(r.headers["Location"])
    assert page.status_code == 200
    assert b"$30.00" in page.data


def test_csrf_is_required(client):
    r = client.post("/t/invoices/new", data={"customer_id": "1"})
    assert r.status_code == 400


def test_api_with_token(app, client):
    r = client.post("/settings/api", data={"_csrf": _csrf(client), "name": "test"})
    assert r.status_code == 200
    token = re.search(rb"pbk_[A-Za-z0-9_-]+", r.data).group(0).decode()
    api = app.test_client()
    assert api.get("/api/v1/company").status_code == 401
    h = {"Authorization": f"Bearer {token}"}
    assert api.get("/api/v1/company", headers=h).get_json()["name"] == "Riverbend Print Co."
    customers = api.get("/api/v1/customers", headers=h).get_json()
    assert customers["total"] >= 8
    cust_id = customers["data"][0]["id"]
    made = api.post("/api/v1/customers", headers=h, json={"display_name": "API Customer", "email": "api@example.com"})
    assert made.status_code == 201, made.get_json()
    dup = api.post("/api/v1/customers", headers=h, json={"display_name": "API Customer"})
    assert dup.status_code == 409
    s = _db(app)
    acct = s.scalar(select(Account).where(Account.name == "Printing Services"))
    s.close()
    inv = api.post("/api/v1/transactions", headers=h, json={
        "type": "invoice", "customer_id": cust_id, "lines": [{"account_id": acct.id, "amount": "125.00",
                                                             "description": "From the API"}]})
    assert inv.status_code == 201, inv.get_json()
    body = inv.get_json()
    assert body["subtotal_cents"] == 12500
    got = api.get(f"/api/v1/transactions/{body['id']}", headers=h).get_json()
    assert got["lines"][0]["description"] == "From the API"
    bad = api.post("/api/v1/transactions", headers=h, json={"type": "invoice", "lines": []})
    assert bad.status_code == 422
    rep = api.get("/api/v1/reports/profit_and_loss?preset=this_year", headers=h).get_json()
    assert rep["columns"] and rep["rows"]
    assert api.delete(f"/api/v1/transactions/{body['id']}", headers=h).status_code == 204


def test_search_finds_customers_and_amounts(client):
    r = client.get("/search?q=Harbor")
    assert r.status_code == 200 and b"Harbor Street Bakery" in r.data


def test_exports_download(client):
    z = client.get("/settings/export/zip")
    assert z.status_code == 200 and z.data[:2] == b"PK"
    import io
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(z.data)).namelist()
    assert "transactions.csv" in names and "api_tokens.csv" not in names
    users_csv = zipfile.ZipFile(io.BytesIO(z.data)).read("users.csv").decode()
    assert "password_hash" not in users_csv
    b = client.get("/settings/export/backup")
    assert b.status_code == 200 and b.data[:15] == b"SQLite format 3"


def test_feed_page_shows_imported_lines(app, client):
    s = _db(app)
    acct = s.scalar(select(BankFeedItem.account_id).limit(1))
    s.close()
    r = client.get(f"/banking?account_id={acct}")
    assert r.status_code == 200
    assert b"FUEL STOP" in r.data
