"""Website chat. Replies are stored and picked up by the visitor's widget (it polls), so
sending is instant. If a visitor left an email address and has closed the page, the
worker emails them the replies they missed (config: email_fallback, default on).

Config: greeting, color, require_email, offline_message, email_fallback, demo.
"""

from __future__ import annotations

import html as htmllib
import logging
from datetime import timedelta

from pps_tools.switchboard import db
from pps_tools.switchboard.channels import Adapter, SendResult, register
from pps_tools.switchboard.services import mailer, settings
from pps_tools.switchboard.util import iso, now, token

logger = logging.getLogger(__name__)

AWAY_MINUTES = 10

DEFAULTS = {
    "greeting": "Hi! 👋 Questions about an order or a quote? We usually reply in a few minutes.",
    "color": "#3b5bdb",
    "require_email": False,
    "offline_message": "We're away right now — leave a message with your email and we'll get back to you.",
    "email_fallback": True,
}


def chat_config(channel: dict) -> dict:
    cfg = db.jload(channel.get("config_json"), {}) or {}
    return {key: cfg.get(key, default) for key, default in DEFAULTS.items()}


class ChatAdapter(Adapter):
    type = "chat"
    label = "Website chat"

    def send(self, channel, message, attachments, ctx):
        return SendResult(external_id=f"chat-{token(9)}", status="sent")


def email_missed_replies() -> int:
    """Email chat replies to visitors who have left the page (worker task)."""
    cutoff = iso(now() - timedelta(minutes=AWAY_MINUTES))
    rows = db.query(
        "SELECT v.*, ch.config_json AS channel_config, ch.name AS channel_name FROM chat_visitors v "
        "JOIN channels ch ON ch.id = v.channel_id "
        "WHERE v.email IS NOT NULL AND v.email != '' AND v.conversation_id IS NOT NULL AND ch.is_active = 1 "
        "AND (v.last_seen_at IS NULL OR v.last_seen_at < ?)",
        cutoff,
    )
    batch_cutoff = iso(now() - timedelta(minutes=2))  # let a burst of replies go out as one email
    sent = 0
    for visitor in rows:
        cfg = db.jload(visitor["channel_config"], {}) or {}
        if cfg.get("email_fallback", True) is False:
            continue
        # Replies sent after the visitor last had the widget open, i.e. never seen.
        missed = db.query(
            "SELECT * FROM messages WHERE conversation_id = ? AND channel_id = ? AND direction = 'out' "
            "AND status IN ('sent', 'delivered', 'read') AND id > ? AND sent_at IS NOT NULL "
            "AND sent_at < ? AND sent_at > ? ORDER BY id",
            visitor["conversation_id"], visitor["channel_id"], visitor["emailed_up_to"] or 0, batch_cutoff,
            visitor["last_seen_at"] or "",
        )
        if not missed:
            continue
        org = settings.get("org.name")
        items = "".join(
            f"<p><b>{htmllib.escape(m['from_name'] or org)}:</b><br>{m['body_html'] or htmllib.escape(m['body_text'] or '')}</p>"
            for m in missed
        )
        link = visitor["page_url"] or ""
        footer = f'<p><a href="{htmllib.escape(link)}">Continue the chat</a> or simply reply to this email.</p>' if link else ""
        html = f"<p>Hi {htmllib.escape((visitor['name'] or '').split(' ')[0] or 'there')},</p><p>You have new replies from {htmllib.escape(org)}:</p>{items}{footer}"
        try:
            if mailer.send_system_email(visitor["email"], f"New reply from {org}", html):
                sent += 1
        except Exception:  # never let one visitor block the rest
            logger.exception("Chat fallback email failed for visitor %s", visitor["id"])
        db.update("chat_visitors", visitor["id"], {"emailed_up_to": missed[-1]["id"]})
    return sent


register(ChatAdapter())
