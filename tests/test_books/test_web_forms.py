"""Form posts on the planning, lists, tax, time, project and import pages."""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from pps_tools.books.config import Config
from pps_tools.books.models import (Budget, Customer, Employee, Item, MileageTrip, RecurringTemplate, TaxRate, Terms,
                                    TimeActivity, Transaction)
from pps_tools.books.services import demo
from pps_tools.books.web.app import create_app
from tests.test_books.test_web import PASSWORD, _csrf, _error_text


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    app = create_app(Config(data_dir=tmp_path_factory.mktemp("forms"), testing=True, secret_key="f" * 32))
    s = app.extensions["books"]["session_factory"]()
    demo.build(s, PASSWORD, today=date.today())
    s.commit()
    s.close()
    return app


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    c.get("/login")
    r = c.post("/login", data={"email": demo.DEMO_EMAIL, "password": PASSWORD, "_csrf": _csrf(c)})
    assert r.status_code == 302
    return c


@pytest.fixture
def db(app):
    """db() is a fresh session, so reads after a POST see what it committed."""
    opened = []

    def fresh():
        opened.append(app.extensions["books"]["session_factory"]())
        return opened[-1]

    yield fresh
    for s in opened:
        s.close()


def _post(client, url, data, ok=(302,)):
    r = client.post(url, data={"_csrf": _csrf(client), **data})
    assert r.status_code in ok, f"{url} -> {r.status_code}: {_error_text(r)}"
    return r


def test_recurring_template_from_the_form(client, db):
    cust = db().scalar(select(Customer).where(Customer.is_project.is_(False)).limit(1))
    item = db().scalar(select(Item).where(Item.type == "service").limit(1))
    page = client.get("/recurring/new?type=invoice")
    assert page.status_code == 200 and b"schedule-panel" in page.data
    start = (date.today() + timedelta(days=3)).isoformat()
    _post(client, "/recurring/new?type=invoice", {
        "tpl_name": "Quarterly posters", "tpl_mode": "scheduled", "tpl_interval": "monthly", "tpl_every": "3",
        "tpl_day_of_month": "15", "tpl_start_date": start, "tpl_end": "count", "tpl_max_occurrences": "4",
        "tpl_days_in_advance": "2", "tpl_auto_send": "1", "customer_id": cust.id, "date": start,
        "has_lines": "1", "l-0-pos": "0", "l-0-kind": "item", "l-0-item_id": item.id, "l-0-qty": "10", "l-0-rate": "18"})
    tpl = db().scalar(select(RecurringTemplate).where(RecurringTemplate.name == "Quarterly posters"))
    assert (tpl.every, tpl.day_of_month, tpl.max_occurrences, tpl.auto_send) == (3, 15, 4, True)
    assert tpl.next_date.isoformat() == start and tpl.amount_cents == 18000
    assert "date" not in tpl.payload and tpl.payload["customer_id"] in (cust.id, str(cust.id))
    # A bad schedule re-shows what was typed instead of saving.
    r = client.post(f"/recurring/{tpl.id}", data={"_csrf": _csrf(client), "tpl_name": "", "tpl_has_active": "1",
                                                  "customer_id": cust.id, "date": start})
    assert r.status_code == 422 and b"Name the template" in r.data
    # Use opens a filled-in invoice; create-now makes one and moves the schedule.
    use = client.get(f"/recurring/{tpl.id}/use")
    assert use.status_code == 302 and "from_template" in use.headers["Location"]
    assert client.get(use.headers["Location"]).status_code == 200
    _post(client, f"/recurring/{tpl.id}/create-now", {})
    made = db().scalar(select(Transaction).where(Transaction.recurring_template_id == tpl.id))
    assert made is not None and made.total_cents >= 18000
    assert db().get(RecurringTemplate, tpl.id).occurrences == 1
    _post(client, f"/recurring/{tpl.id}/toggle", {})
    _post(client, f"/recurring/{tpl.id}/duplicate", {})
    assert db().scalar(select(RecurringTemplate).where(RecurringTemplate.name == "Quarterly posters (copy)")) is not None


def test_make_recurring_from_an_existing_invoice(client, db):
    inv = db().scalar(select(Transaction).where(Transaction.type == "invoice").limit(1))
    page = client.get(f"/recurring/new?from_txn={inv.id}")
    assert page.status_code == 200 and b"Template name" in page.data


def test_lists_add_edit_and_delete(client, db):
    _post(client, "/lists/terms", {"name": "Net 45", "kind": "days", "due_days": "45"})
    t = db().scalar(select(Terms).where(Terms.name == "Net 45"))
    assert t.due_days == 45 and t.active
    r = client.post("/lists/terms", data={"_csrf": _csrf(client), "name": "Net 45", "kind": "days", "due_days": "45"})
    assert r.status_code == 422
    _post(client, "/lists/classes", {"name": "Commercial"})
    _post(client, "/lists/classes", {"name": "Banners"})
    from pps_tools.books.models import TrackingClass

    parent = db().scalar(select(TrackingClass).where(TrackingClass.name == "Commercial"))
    child = db().scalar(select(TrackingClass).where(TrackingClass.name == "Banners"))
    _post(client, "/lists/classes", {"id": child.id, "name": "Banners", "parent_id": parent.id, "active": "1"})
    assert db().get(TrackingClass, child.id).full_name == "Commercial:Banners"
    r = client.post("/lists/classes", data={"_csrf": _csrf(client), "id": parent.id, "name": "Commercial",
                                            "parent_id": child.id, "active": "1"})
    assert r.status_code == 422  # a loop of parents
    _post(client, f"/lists/terms/{t.id}/delete", {})
    assert db().scalar(select(Terms).where(Terms.name == "Net 45")) is None


def test_tax_rates_and_combined_rates(client, db):
    from pps_tools.books.models import TaxAgency

    _post(client, "/taxes/rates", {"what": "agency", "name": "City Treasurer", "filing_frequency": "annually"})
    ag = db().scalar(select(TaxAgency).where(TaxAgency.name == "City Treasurer"))
    _post(client, "/taxes/rates", {"what": "rate", "kind": "single", "name": "City 0.5%", "rate": "0.5", "agency_id": ag.id})
    city = db().scalar(select(TaxRate).where(TaxRate.name == "City 0.5%"))
    state = db().scalar(select(TaxRate).where(TaxRate.name == "State 6%"))
    r = client.post("/taxes/rates", data={"_csrf": _csrf(client), "what": "rate", "kind": "combined",
                                          "name": "City + State", "component_ids": [str(city.id)]})
    assert r.status_code == 422  # needs two components
    client.post("/taxes/rates", data={"_csrf": _csrf(client), "what": "rate", "kind": "combined", "name": "City + State",
                                      "component_ids": [str(city.id), str(state.id)]})
    combo = db().scalar(select(TaxRate).where(TaxRate.name == "City + State"))
    assert combo.is_combined and combo.effective_rate == 6.5
    # A rate already charged on sales can't be changed in place.
    r = client.post("/taxes/rates", data={"_csrf": _csrf(client), "what": "rate", "kind": "single", "id": state.id,
                                          "name": "State 6%", "rate": "6.25", "agency_id": state.agency_id})
    assert r.status_code == 422 and b"inactive" in r.data
    assert client.get("/taxes/1099.csv").status_code == 200


def test_budget_grid_saves_and_totals(client, db):
    _post(client, "/budgets", {"name": "Lean plan", "fiscal_year": str(date.today().year), "subdivide_by": "none",
                               "prefill": "blank"})
    budget = db().scalar(select(Budget).where(Budget.name == "Lean plan"))
    from pps_tools.books.models import Account

    rent = db().scalar(select(Account).where(Account.name == "Rent & Lease"))
    form = {"name": "Lean plan", "active": "1", **{f"b-{rent.id}-{p}": "2,400.00" for p in range(1, 13)}}
    _post(client, f"/budgets/{budget.id}", form)
    assert sum(bl.amount_cents for bl in db().get(Budget, budget.id).lines) == 12 * 240000
    r = client.post(f"/budgets/{budget.id}", data={"_csrf": _csrf(client), f"b-{rent.id}-1": "lots"})
    assert r.status_code == 302  # flashed error, nothing saved
    assert sum(bl.amount_cents for bl in db().get(Budget, budget.id).lines) == 12 * 240000
    page = client.get(f"/reports/budget_vs_actuals?budget_id={budget.id}")
    assert page.status_code == 200 and b"Rent" in page.data


def test_time_entry_timesheet_and_mileage(client, db):
    emp = db().scalar(select(Employee).limit(1))
    cust = db().scalar(select(Customer).where(Customer.is_project.is_(False)).limit(1))
    today = date.today().isoformat()
    _post(client, "/time/new", {"worker": f"employee:{emp.id}", "date": today, "customer_id": cust.id, "mode": "range",
                                "start_time": "09:00", "end_time": "12:15", "break": "0:15", "billable": "1",
                                "hourly_rate": "", "description": "Proof revisions"})
    ta = db().scalar(select(TimeActivity).where(TimeActivity.description == "Proof revisions"))
    assert ta.minutes == 180 and ta.hourly_rate == emp.billable_rate
    r = client.post("/time/new", data={"_csrf": _csrf(client), "worker": f"employee:{emp.id}", "date": today,
                                       "mode": "duration", "duration": "1:30", "billable": "1"})
    assert r.status_code == 422 and b"needs a customer" in r.data
    week = date.today() - timedelta(days=date.today().weekday())
    _post(client, "/time/timesheet", {"worker": f"employee:{emp.id}", "week": week.isoformat(),
                                      "r-0-pos": "0", "r-0-customer_id": str(cust.id), "r-0-description": "Press checks",
                                      "r-0-d0": "2", "r-0-d1": "1:30", "r-0-d2": "45m"})
    rows = db().scalars(select(TimeActivity).where(TimeActivity.description == "Press checks")).all()
    assert sorted(r.minutes for r in rows) == [45, 90, 120]
    _post(client, "/mileage/new", {"date": today, "miles": "12.4", "round_trip": "1", "purpose": "business",
                                   "start_location": "Shop", "end_location": "Client", "notes": "Proofs"})
    trip = db().scalar(select(MileageTrip).where(MileageTrip.notes == "Proofs"))
    assert str(trip.miles) == "24.8"
    page = client.get("/mileage")
    assert page.status_code == 200
    csv_out = client.get(f"/mileage/summary.csv?year={date.today().year}")
    assert b"Deduction" in csv_out.data


def test_project_create_and_update(client, db):
    cust = db().scalar(select(Customer).where(Customer.display_name == "Northside Dental Group"))
    r = _post(client, "/projects", {"name": "Northside: Fall Mailer", "customer_id": cust.id,
                                    "project_start": date.today().isoformat()})
    project = db().scalar(select(Customer).where(Customer.display_name == "Northside: Fall Mailer"))
    assert project.is_project and project.parent_id == cust.id and r.headers["Location"].endswith(f"/projects/{project.id}")
    _post(client, f"/projects/{project.id}", {"name": "Northside: Fall Mailer", "project_status": "completed",
                                              "project_start": "", "project_end": ""})
    assert db().get(Customer, project.id).project_status == "completed"


def test_csv_import_wizard(client, db):
    csv_text = "Vendor Name,Email,1099\nRiver Ink Co,ap@riverink.example.com,no\nCasey Freelance,casey@example.com,yes\n"
    r = client.post("/settings/import", data={"_csrf": _csrf(client), "kind": "vendors",
                                              "file": (__import__("io").BytesIO(csv_text.encode()), "vendors.csv")},
                    content_type="multipart/form-data")
    assert r.status_code == 302 and "/settings/import/map" in r.headers["Location"]
    page = client.get(r.headers["Location"])
    assert page.status_code == 200 and b"River Ink Co" in page.data
    token = re.search(r"token=([\w-]+)", r.headers["Location"]).group(1)
    done = client.post("/settings/import/map", data={"_csrf": _csrf(client), "kind": "vendors", "token": token,
                                                     "map_display_name": "0", "map_email": "1", "map_track_1099": "2"})
    assert done.status_code == 200 and b"Added" in done.data
    from pps_tools.books.models import Vendor

    casey = db().scalar(select(Vendor).where(Vendor.display_name == "Casey Freelance"))
    assert casey.track_1099 and casey.email == "casey@example.com"
