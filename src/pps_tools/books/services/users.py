"""Users, passwords and what each role may do."""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from pps_tools.books.db import utcnow
from pps_tools.books.models import ROLES, User
from pps_tools.books.services.errors import ValidationError

# Permission -> roles that have it.
PERMISSIONS: dict[str, set[str]] = {
    "sales.view": {"admin", "accountant", "standard", "sales", "viewer"},
    "sales.edit": {"admin", "accountant", "standard", "sales"},
    "purchases.view": {"admin", "accountant", "standard", "purchases", "viewer"},
    "purchases.edit": {"admin", "accountant", "standard", "purchases"},
    "banking.view": {"admin", "accountant", "standard", "viewer"},
    "banking.edit": {"admin", "accountant", "standard"},
    "accounting.view": {"admin", "accountant", "standard", "viewer"},
    "accounting.edit": {"admin", "accountant", "standard"},  # journal entries, chart of accounts
    "reconcile": {"admin", "accountant", "standard"},
    "reports.view": {"admin", "accountant", "standard", "reports", "viewer"},
    "lists.edit": {"admin", "accountant", "standard", "sales", "purchases"},
    "time.edit": {"admin", "accountant", "standard", "time", "sales"},
    "time.view": {"admin", "accountant", "standard", "time", "sales", "viewer"},
    "settings.edit": {"admin"},
    "users.manage": {"admin"},
    "close_books": {"admin", "accountant"},
    "audit.view": {"admin", "accountant"},
    "payments.refund": {"admin", "accountant", "standard"},
}

MIN_PASSWORD = 8
LOCK_AFTER = 8
LOCK_FOR = timedelta(minutes=15)


def can(user: Optional[User], permission: str) -> bool:
    if user is None or not user.active:
        return False
    return user.role in PERMISSIONS.get(permission, set())


def can_edit_type(user: Optional[User], txn_type: str) -> bool:
    from pps_tools.books.txn_types import TXN_TYPES

    section = TXN_TYPES[txn_type].section
    perm = {"sales": "sales.edit", "expenses": "purchases.edit", "banking": "banking.edit",
            "accounting": "accounting.edit", "inventory": "lists.edit", "tax": "accounting.edit"}[section]
    return can(user, perm)


def can_view_type(user: Optional[User], txn_type: str) -> bool:
    from pps_tools.books.txn_types import TXN_TYPES

    section = TXN_TYPES[txn_type].section
    perm = {"sales": "sales.view", "expenses": "purchases.view", "banking": "banking.view",
            "accounting": "accounting.view", "inventory": "sales.view", "tax": "accounting.view"}[section]
    return can(user, perm)


def _check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ValidationError(f"Passwords need at least {MIN_PASSWORD} characters.", "password")


def create_user(s: Session, email: str, name: str, password: str, role: str = "standard") -> User:
    email = (email or "").strip().lower()
    if "@" not in email:
        raise ValidationError("Enter a valid email address.", "email")
    if role not in ROLES:
        raise ValidationError("Choose a role.", "role")
    if s.scalar(select(User).where(func.lower(User.email) == email)):
        raise ValidationError("A user with that email already exists.", "email")
    _check_password(password)
    user = User(email=email, name=(name or email).strip(), role=role,
                password_hash=generate_password_hash(password))
    s.add(user)
    s.flush()
    return user


def set_password(user: User, password: str) -> None:
    _check_password(password)
    user.password_hash = generate_password_hash(password)


def authenticate(s: Session, email: str, password: str) -> Optional[User]:
    user = s.scalar(select(User).where(func.lower(User.email) == (email or "").strip().lower()))
    if user is None or not user.active:
        # Spend the same time hashing so a missing account isn't distinguishable.
        check_password_hash(generate_password_hash("x"), password or "")
        return None
    now = utcnow()
    if user.locked_until and user.locked_until > now:
        return None
    if not check_password_hash(user.password_hash, password or ""):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= LOCK_AFTER:
            user.locked_until = now + LOCK_FOR
            user.failed_logins = 0
        return None
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    return user


def admin_count(s: Session) -> int:
    return int(s.scalar(select(func.count(User.id)).where(User.role == "admin", User.active.is_(True))) or 0)
