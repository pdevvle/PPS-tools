"""Demo admin data: an example webhook (off) and a sidebar app."""

from __future__ import annotations

from pps_tools.switchboard import db
from pps_tools.switchboard.services import webhooks
from pps_tools.switchboard.util import now_iso


def seed_admin(ctx) -> None:
    stamp = now_iso()
    db.insert("webhooks", {
        "name": "Zapier — new customer messages",
        "url": "https://hooks.zapier.com/hooks/catch/000000/example/",
        "secret": webhooks.new_secret(),
        "events_json": db.jdump(["conversation.created", "message.received"]),
        "is_active": 0,
        "created_by": ctx.uid("owner"),
        "created_at": stamp,
    })
    db.insert("integrations", {
        "kind": "iframe",
        "name": "Customer map",
        "config_json": db.jdump({"url": "https://maps.google.com/maps?q={{contact.address}}&output=embed", "height": 240}),
        "is_active": 1,
        "position": 1,
        "created_at": stamp,
    })
