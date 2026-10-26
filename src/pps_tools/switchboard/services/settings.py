"""Organization-wide settings stored as JSON values in the ``settings`` table.

Every key has a default here, so callers can always ``get()`` without checking.
Modules add their own defaults with ``register_defaults()`` at import time.
"""

from __future__ import annotations

import copy
import threading

from pps_tools.switchboard import db

_lock = threading.Lock()
_cache: dict | None = None

DEFAULTS: dict = {
    "org.name": "Priority Print Service",
    "org.timezone": "America/Phoenix",
    "org.week_start": 0,                 # 0 = Sunday, 1 = Monday
    "org.accent_color": "#3b5bdb",
    "org.business_hours": {
        "mon": [["08:00", "17:00"]],
        "tue": [["08:00", "17:00"]],
        "wed": [["08:00", "17:00"]],
        "thu": [["08:00", "17:00"]],
        "fri": [["08:00", "17:00"]],
        "sat": [],
        "sun": [],
    },
    "org.holidays": [],                  # ['2026-12-25', ...]
    "inbox.undo_send_seconds": 8,
    "inbox.block_remote_images": False,
    "inbox.sla_first_response_minutes": 240,
    "inbox.auto_close_spam_days": 30,
}

# Keys that only admins may read (secrets, API keys).
PRIVATE_PREFIXES: list[str] = ["secret.", "ai.api_key", "integrations."]


def register_defaults(values: dict, private_prefixes: list[str] | None = None) -> None:
    DEFAULTS.update(values)
    if private_prefixes:
        PRIVATE_PREFIXES.extend(private_prefixes)


def _load() -> dict:
    global _cache
    with _lock:
        if _cache is None:
            _cache = {r["key"]: db.jload(r["value_json"]) for r in db.query("SELECT key, value_json FROM settings")}
        return _cache


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def get(key: str, default=None):
    stored = _load()
    if key in stored:
        return copy.deepcopy(stored[key])
    if key in DEFAULTS:
        return copy.deepcopy(DEFAULTS[key])
    return default


def set(key: str, value) -> None:  # noqa: A001 - mirrors get()
    db.execute(
        "INSERT INTO settings (key, value_json) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
        key,
        db.jdump(value),
    )
    db.after_commit(invalidate)
    invalidate()


def set_many(values: dict) -> None:
    with db.transaction():
        for key, value in values.items():
            set(key, value)


def is_private(key: str) -> bool:
    return any(key.startswith(p) for p in PRIVATE_PREFIXES)


def public() -> dict:
    """Everything a signed-in user may see (secrets removed)."""
    merged = copy.deepcopy(DEFAULTS)
    merged.update(copy.deepcopy(_load()))
    return {k: v for k, v in merged.items() if not is_private(k)}


def timezone():
    from pps_tools.switchboard.util import get_zone

    return get_zone(get("org.timezone"))
