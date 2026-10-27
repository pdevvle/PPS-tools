"""Operational email (invites, password resets, schedule notices) sent through one of
the workspace's connected email channels.

Which channel: the ``mail.system_channel_id`` setting, else the first active shared
email channel. Returns False when nothing can send, so callers can fall back to
showing a copyable link.
"""

from __future__ import annotations

import logging

from pps_tools.switchboard import db
from pps_tools.switchboard.services import settings

logger = logging.getLogger(__name__)

settings.register_defaults({"mail.system_channel_id": None})


def system_channel() -> dict | None:
    cid = settings.get("mail.system_channel_id")
    if cid:
        row = db.one("SELECT * FROM channels WHERE id = ? AND type = 'email' AND is_active = 1", cid)
        if row:
            return row
    return db.one(
        "SELECT * FROM channels WHERE type = 'email' AND is_active = 1 AND visibility = 'shared' ORDER BY id LIMIT 1"
    )


def can_send() -> bool:
    return system_channel() is not None


def send_system_email(to: str, subject: str, html: str, text: str | None = None) -> bool:
    channel = system_channel()
    if channel is None:
        return False
    try:
        from pps_tools.switchboard.channels import email as email_channel
    except ImportError:  # pragma: no cover - channels module not installed
        return False
    try:
        email_channel.send_simple(channel, to, subject, html, text)
        return True
    except Exception:
        logger.exception("System email to %s failed", to)
        return False
