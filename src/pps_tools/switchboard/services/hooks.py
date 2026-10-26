"""In-process domain events, so modules react to each other without importing each
other: the rules engine listens for new messages, webhooks forward everything, the
jobs module listens for conversation merges...

    hooks.on("message.received", handler)      # handler(payload: dict)
    hooks.fire("message.received", {"message_id": 5, "conversation_id": 2})

Handlers run after the current transaction commits, one by one; a failing handler is
logged and skipped. Subscribe to "*" to receive (event, payload) for everything.

Events: message.received, message.queued, message.sent, message.failed,
conversation.created, conversation.assigned, conversation.unassigned,
conversation.closed, conversation.reopened, conversation.labeled,
conversation.merged, comment.created, plus module events (job.*, shift.*, ...).
"""

from __future__ import annotations

import logging
from typing import Callable

from pps_tools.switchboard import db

logger = logging.getLogger(__name__)

_handlers: dict[str, list[Callable]] = {}


def on(event: str, fn: Callable | None = None):
    """Register a handler; usable as a decorator."""

    def register(f: Callable) -> Callable:
        lst = _handlers.setdefault(event, [])
        if f not in lst:
            lst.append(f)
        return f

    return register(fn) if fn else register


def off(event: str, fn: Callable) -> None:
    if fn in _handlers.get(event, []):
        _handlers[event].remove(fn)


def _dispatch(event: str, payload: dict) -> None:
    for fn in list(_handlers.get(event, [])):
        try:
            fn(payload)
        except Exception:
            logger.exception("Hook %s failed for %s", getattr(fn, "__name__", fn), event)
    for fn in list(_handlers.get("*", [])):
        try:
            fn(event, payload)
        except Exception:
            logger.exception("Wildcard hook %s failed for %s", getattr(fn, "__name__", fn), event)


def fire(event: str, payload: dict | None = None) -> None:
    payload = dict(payload or {})
    db.after_commit(lambda: _dispatch(event, payload))
