"""Errors raised by the services layer and shown to the user as-is."""

from __future__ import annotations

from typing import Optional


class BooksError(Exception):
    """Base class; ``str(exc)`` is safe to show in the UI."""


class ValidationError(BooksError):
    def __init__(self, message: str, field: Optional[str] = None, errors: Optional[list[str]] = None):
        super().__init__(message)
        self.field = field
        self.errors = errors or [message]


class ClosedPeriodError(BooksError):
    """The change touches a date on or before the closing date."""


class NotFound(BooksError):
    pass


class PermissionDenied(BooksError):
    pass


class StripeNotConfigured(BooksError):
    pass
