"""Fixtures: a fresh company in an in-memory database for every test."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from pps_tools.books.db import create_schema, make_engine, make_session_factory
from pps_tools.books.models import (Account, Customer, Item, LedgerEntry, TaxAgency, TaxRate, Terms,
                                    Vendor)
from pps_tools.books.services import setup
from pps_tools.books.services.accounts import system_account


@pytest.fixture
def s():
    engine = make_engine("sqlite://")
    create_schema(engine)
    session = make_session_factory(engine)()
    setup.create_company(session, "Test Print Co", "admin@example.com", "Admin", "password123",
                         industry="print_shop")
    session.commit()
    yield session
    session.close()
    engine.dispose()


class Books:
    """Helpers for building test data."""

    def __init__(self, s):
        self.s = s

    def acct(self, key_or_name: str) -> Account:
        acct = self.s.scalar(select(Account).where(Account.system_key == key_or_name))
        if acct is None:
            acct = self.s.scalar(select(Account).where(Account.name == key_or_name))
        if acct is None:
            raise KeyError(key_or_name)
        return acct

    def customer(self, name="Acme Corp", **kw) -> Customer:
        c = Customer(display_name=name, email=kw.pop("email", f"{name.split()[0].lower()}@example.com"), **kw)
        self.s.add(c)
        self.s.flush()
        return c

    def vendor(self, name="Paper Supply Co", **kw) -> Vendor:
        v = Vendor(display_name=name, **kw)
        self.s.add(v)
        self.s.flush()
        return v

    def service(self, name="Business Cards", price="0.10", income="Printing Services", taxable=True) -> Item:
        it = Item(name=name, type="service", sales_price=Decimal(price), taxable=taxable,
                  income_account_id=self.acct(income).id)
        self.s.add(it)
        self.s.flush()
        return it

    def inventory(self, name="Gloss Paper 100lb", price="2.00", cost="1.00") -> Item:
        it = Item(name=name, type="inventory", sales_price=Decimal(price), cost=Decimal(cost), taxable=True,
                  income_account_id=self.acct("sales_income").id,
                  expense_account_id=self.acct("cogs").id,
                  asset_account_id=self.acct("inventory_asset").id)
        self.s.add(it)
        self.s.flush()
        return it

    def tax_rate(self, name="State", rate="6.25", agency="State Dept of Revenue") -> TaxRate:
        ag = self.s.scalar(select(TaxAgency).where(TaxAgency.name == agency))
        if ag is None:
            ag = TaxAgency(name=agency)
            self.s.add(ag)
            self.s.flush()
        r = TaxRate(name=name, rate=Decimal(rate), agency_id=ag.id)
        self.s.add(r)
        self.s.flush()
        return r

    def terms(self, name="Net 30") -> Terms:
        return self.s.scalar(select(Terms).where(Terms.name == name))

    def balance(self, key_or_name: str, **filters) -> int:
        """Debit-positive ledger balance of an account."""
        acct = self.acct(key_or_name)
        q = select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).where(LedgerEntry.account_id == acct.id)
        for k, v in filters.items():
            q = q.where(getattr(LedgerEntry, k) == v)
        return int(self.s.scalar(q))

    def assert_balanced(self) -> None:
        total = self.s.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)))
        assert total == 0, f"ledger out of balance by {total}"


@pytest.fixture
def b(s):
    return Books(s)


@pytest.fixture
def checking(b):
    return b.acct("Checking")


@pytest.fixture
def system(s):
    return lambda key: system_account(s, key)
