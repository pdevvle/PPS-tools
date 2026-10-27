"""Demo admin data: an example webhook (off), a sidebar app and some audit history."""

from __future__ import annotations

from pps_tools.switchboard import db
from pps_tools.switchboard.services import webhooks


def seed_admin(ctx) -> None:
    hook = db.insert("webhooks", {
        "name": "Zapier — new customer messages",
        "url": "https://hooks.zapier.com/hooks/catch/000000/example/",
        "secret": webhooks.new_secret(),
        "events_json": db.jdump(["conversation.created", "message.received"]),
        "is_active": 0,
        "created_by": ctx.uid("owner"),
        "created_at": ctx.ago(days=9, hours=3),
    })
    app = db.insert("integrations", {
        "kind": "iframe",
        "name": "Customer map",
        "config_json": db.jdump({"url": "https://maps.google.com/maps?q={{contact.address}}&output=embed", "height": 240}),
        "is_active": 1,
        "position": 1,
        "created_at": ctx.ago(days=21, hours=5),
    })
    history = [
        (40, "owner", "user.create", "user", ctx.uid("parttime"), {"email": "jamie@pps.demo", "role": "staff"}),
        (21, "owner", "integration.create", "integration", app, {"kind": "iframe"}),
        (16, "owner", "settings.update", None, None, {"inbox.sla_first_response_minutes": 240}),
        (9, "owner", "webhook.create", "webhook", hook, {"url": "https://hooks.zapier.com/hooks/catch/000000/example/"}),
        (8, "owner", "webhook.update", "webhook", hook, None),
        (6, "manager", "timesheets.approve", None, None, {"entries": 31}),
        (2, "manager", "timesheets.approve", None, None, {"entries": 28}),
    ]
    for days, who, action, entity_type, entity_id, data in history:
        db.insert("audit_log", {
            "user_id": ctx.uid(who), "action": action, "entity_type": entity_type, "entity_id": entity_id,
            "data_json": db.jdump(data) if data is not None else None, "ip": "192.168.1.24",
            "created_at": ctx.ago(days=days, hours=ctx.rng.randint(1, 6)),
        })
