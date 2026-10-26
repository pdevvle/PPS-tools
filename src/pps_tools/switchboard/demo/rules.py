"""Demo automation rules for the print shop."""

from __future__ import annotations

from pps_tools.switchboard import db
from pps_tools.switchboard.util import now_iso


def _label(name: str) -> int | None:
    row = db.one("SELECT id FROM labels WHERE name = ?", name)
    return row["id"] if row else None


def seed_rules(ctx) -> None:
    owner = ctx.uid("owner")
    office = ctx.teams.get("office")
    quote, rush = _label("Quote request"), _label("Rush")
    after_hours = db.one("SELECT id FROM canned_responses WHERE shortcut = 'afterhours'")
    stamp = now_iso()
    rules = [
        ("Label quote requests", True, "incoming", "any",
         [{"field": "subject", "op": "contains", "value": "quote, estimate, pricing"},
          {"field": "body", "op": "contains", "value": "quote, estimate, how much"}],
         [{"type": "add_label", "label_ids": [quote]}] if quote else []),
        ("Rush jobs", True, "incoming", "any",
         [{"field": "subject", "op": "contains", "value": "rush, asap, urgent"},
          {"field": "body", "op": "contains", "value": "rush, asap, by tomorrow"}],
         ([{"type": "add_label", "label_ids": [rush]}] if rush else []) + [{"type": "priority", "value": "high"}]),
        ("Texts go to Front Office", True, "new_conversation", "all",
         [{"field": "channel_type", "op": "is", "value": ["sms", "whatsapp"]}],
         [{"type": "move_team", "team_id": office}] if office else []),
        ("After-hours auto-reply", False, "new_conversation", "all",
         [{"field": "business_hours", "op": "is", "value": "outside"},
          {"field": "channel_type", "op": "is", "value": ["email", "api"]}],
         [{"type": "auto_reply", "response_id": after_hours["id"]}] if after_hours else []),
        ("Vendor mail skips the inbox", True, "incoming", "all",
         [{"field": "from", "op": "ends_with", "value": "@mohawkpaper.example"}],
         [{"type": "add_label", "label_ids": [_label("Vendor")]}] if _label("Vendor") else []),
    ]
    for position, (name, active, trigger, match, conditions, actions) in enumerate(rules, start=1):
        if not actions:
            continue
        db.insert("rules", {
            "name": name, "is_active": 1 if active else 0, "trigger": trigger, "match": match,
            "conditions_json": db.jdump(conditions), "actions_json": db.jdump(actions), "position": position,
            "run_count": ctx.rng.randint(3, 40) if active else 0,
            "last_run_at": ctx.ago(hours=ctx.rng.randint(1, 30)) if active else None,
            "created_by": owner, "created_at": stamp, "updated_at": stamp,
        })
