"""Closing the books: nothing dated on or before the closing date changes
without the closing password (or, if none is set, an explicit confirmation)."""

from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from pps_tools.books.models import Company, User
from pps_tools.books.services.errors import ClosedPeriodError


def closing_date(s: Session) -> Optional[date]:
    company = s.get(Company, 1)
    return company.closing_date if company else None


def guard(s: Session, dates: Iterable[Optional[date]], user: Optional[User] = None,
          password: Optional[str] = None) -> None:
    """Raise unless the change may touch a closed period.

    ``password`` is the closing password when one is set; when none is set,
    any non-None value (the UI sends "") means the user saw the warning.
    """
    closed = closing_date(s)
    if closed is None:
        return
    if not any(d is not None and d <= closed for d in dates):
        return
    company = s.get(Company, 1)
    if company.closing_password_hash:
        if password and check_password_hash(company.closing_password_hash, password):
            return
        raise ClosedPeriodError(
            f"The books are closed through {closed:%m/%d/%Y}. Enter the closing password to save this change.")
    if password is not None:
        return
    raise ClosedPeriodError(
        f"The books are closed through {closed:%m/%d/%Y}. Confirm that you want to change a closed period.")


def set_closing(s: Session, when: Optional[date], password: Optional[str] = None) -> None:
    company = s.get(Company, 1)
    company.closing_date = when
    if password is not None:
        company.closing_password_hash = generate_password_hash(password) if password else None
