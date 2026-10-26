"""Creating a new company: chart of accounts, terms, payment methods, admin."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from pps_tools.books.models import Company, PaymentMethod, Terms, User
from pps_tools.books.services import numbering, prefs, users
from pps_tools.books.services.accounts import install_chart
from pps_tools.books.services.errors import ValidationError

DEFAULT_TERMS = [
    ("Due on receipt", "days", 0, None, None),
    ("Net 15", "days", 15, None, None),
    ("Net 30", "days", 30, None, None),
    ("Net 60", "days", 60, None, None),
    ("1% 10 Net 30", "days", 30, Decimal("1"), 10),
    ("2% 10 Net 30", "days", 30, Decimal("2"), 10),
]

DEFAULT_PAYMENT_METHODS = [
    ("Cash", "cash"), ("Check", "check"), ("Credit card", "card"), ("ACH / bank transfer", "ach"),
    ("Wire", "ach"), ("Stripe", "card"), ("Zelle", "ach"), ("Other", "other"),
]

INDUSTRIES = {
    "print_shop": "Commercial printing",
    "general": "General small business",
}


def is_set_up(s: Session) -> bool:
    company = s.get(Company, 1)
    return bool(company and company.setup_complete)


def create_company(s: Session, name: str, admin_email: str, admin_name: str, admin_password: str,
                   industry: str = "general", entity_type: str = "llc", fiscal_year_start_month: int = 1,
                   accounting_method: str = "accrual", state: Optional[str] = None,
                   account_numbers: bool = True) -> Company:
    if is_set_up(s):
        raise ValidationError("This company is already set up.")
    if not (name or "").strip():
        raise ValidationError("Enter your company name.", "name")
    company = s.get(Company, 1) or Company(id=1)
    company.name = name.strip()
    company.industry = INDUSTRIES.get(industry, industry)
    company.entity_type = entity_type
    company.fiscal_year_start_month = int(fiscal_year_start_month or 1)
    company.accounting_method = accounting_method if accounting_method in ("accrual", "cash") else "accrual"
    company.state = state
    company.prefs = {}
    s.add(company)
    s.flush()

    install_chart(s, "print_shop" if industry == "print_shop" else "general", with_numbers=account_numbers)
    for tname, kind, days, disc, disc_days in DEFAULT_TERMS:
        if s.scalar(select(Terms.id).where(Terms.name == tname)) is None:
            s.add(Terms(name=tname, kind=kind, due_days=days, discount_pct=disc, discount_days=disc_days))
    for pname, kind in DEFAULT_PAYMENT_METHODS:
        if s.scalar(select(PaymentMethod.id).where(PaymentMethod.name == pname)) is None:
            s.add(PaymentMethod(name=pname, kind=kind))
    s.flush()
    net30 = s.scalar(select(Terms.id).where(Terms.name == "Net 30"))
    prefs.set_many(s, {"default_terms_id": net30, "default_bill_terms_id": net30})
    for key in ("invoice", "estimate", "sales_receipt", "credit_memo", "refund_receipt", "purchase_order"):
        numbering.peek(s, key)

    if not s.scalar(select(User.id).limit(1)):
        users.create_user(s, admin_email, admin_name, admin_password, role="admin")
    company.setup_complete = True
    s.flush()
    return company
