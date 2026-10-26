"""Mileage: the standard mileage rate in effect on a date."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from pps_tools.books.services import prefs
from pps_tools.books.services.dates import parse_date


def rates(s: Session) -> list[tuple[date, Decimal]]:
    out = []
    for when, rate in prefs.get(s, "mileage_rates") or []:
        try:
            out.append((parse_date(when), Decimal(str(rate))))
        except (ValueError, ArithmeticError):
            continue
    return sorted(out)


def rate_on(s: Session, when: date) -> Optional[Decimal]:
    current = None
    for effective, rate in rates(s):
        if effective <= when:
            current = rate
    return current
