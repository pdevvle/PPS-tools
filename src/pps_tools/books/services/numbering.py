"""Document numbers: invoices from 1001, checks per bank account, etc."""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from pps_tools.books.models import Account, NumberSequence

DEFAULT_START = {
    "invoice": 1001,
    "estimate": 1001,
    "sales_receipt": 1001,
    "credit_memo": 1001,
    "refund_receipt": 1001,
    "purchase_order": 1001,
    "journal_entry": 1,
    "inventory_adjustment": 1,
}

_TRAILING_INT = re.compile(r"^(.*?)(\d+)$")


def _seq(s: Session, key: str) -> NumberSequence:
    seq = s.scalar(select(NumberSequence).where(NumberSequence.key == key))
    if seq is None:
        seq = NumberSequence(key=key, prefix="", next_value=DEFAULT_START.get(key, 1001))
        s.add(seq)
        s.flush()
    return seq


def peek(s: Session, key: str) -> str:
    seq = _seq(s, key)
    return f"{seq.prefix}{seq.next_value}"


def take(s: Session, key: str) -> str:
    seq = _seq(s, key)
    value = f"{seq.prefix}{seq.next_value}"
    seq.next_value += 1
    return value


def note_used(s: Session, key: str, number: Optional[str]) -> None:
    """A number typed by hand moves the sequence past it (as QBO does)."""
    if not number:
        return
    seq = _seq(s, key)
    m = _TRAILING_INT.match(number.strip())
    if not m or m.group(1) != seq.prefix:
        return
    used = int(m.group(2))
    if used >= seq.next_value:
        seq.next_value = used + 1


def set_next(s: Session, key: str, next_value: int, prefix: Optional[str] = None) -> None:
    seq = _seq(s, key)
    seq.next_value = int(next_value)
    if prefix is not None:
        seq.prefix = prefix


def next_check_number(s: Session, account: Account) -> str:
    return str(account.next_check_number or 1001)


def take_check_number(s: Session, account: Account) -> str:
    value = account.next_check_number or 1001
    account.next_check_number = value + 1
    return str(value)


def note_check_number(account: Account, number: Optional[str]) -> None:
    if number and number.strip().isdigit():
        used = int(number.strip())
        if used >= (account.next_check_number or 0):
            account.next_check_number = used + 1
