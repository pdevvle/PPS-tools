"""Channel adapters: how each kind of connected account sends (and, for pull-based
sources like IMAP, fetches) messages.

    from pps_tools.switchboard import channels
    channels.register(EmailAdapter())
    result = channels.adapter_for(channel).send(channel, message, attachments, ctx)

Inbound messages from every channel end up in ``services.inbox.deliver_inbound``.
Channels whose config has ``"demo": true`` never touch the network: sends succeed
locally (used by the demo workspace and tests).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pps_tools.switchboard.util import token


@dataclass
class SendResult:
    external_id: str | None = None
    status: str = "sent"                  # 'sent' or 'delivered'
    headers: dict = field(default_factory=dict)


class SendError(Exception):
    """A send failed. ``transient`` failures are retried with backoff."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class Adapter:
    type: str = ""
    label: str = ""

    def send(self, channel: dict, message: dict, attachments: list[dict], ctx: dict) -> SendResult:
        """Deliver an outbound message. ``ctx`` holds the conversation, the message
        being replied to (``reply_to``) and the author (``user``)."""
        raise NotImplementedError

    def sync(self, channel: dict) -> int:
        """Pull new inbound messages (IMAP). Returns how many were delivered."""
        return 0

    def test(self, config: dict) -> tuple[bool, str]:
        """Check credentials before saving a channel."""
        return True, "OK"

    def public_config(self, channel: dict) -> dict:
        """Settings the web app may show (never secrets)."""
        return {}


class LocalAdapter(Adapter):
    """Marks messages as sent without contacting anyone (demo channels, website chat,
    and channel types whose integration isn't installed)."""

    type = "local"

    def send(self, channel, message, attachments, ctx):
        return SendResult(external_id=f"local-{token(9)}")


ADAPTERS: dict[str, Adapter] = {}
_local = LocalAdapter()


def register(adapter: Adapter) -> Adapter:
    ADAPTERS[adapter.type] = adapter
    return adapter


def adapter_for(channel: dict | None) -> Adapter:
    if not channel:
        return _local
    from pps_tools.switchboard.db import jload

    config = jload(channel.get("config_json"), {}) or {}
    if config.get("demo"):
        return _local
    return ADAPTERS.get(channel["type"], _local)
