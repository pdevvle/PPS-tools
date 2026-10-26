"""Demo workspace: realistic people, conversations, shifts and jobs for a print shop.

``pps switchboard seed`` builds it in an empty data directory. Each feature module
adds its own demo rows through a ``seed(ctx)`` function; this file creates the people
and teams they all share. Every demo account's password is ``DEMO_PASSWORD``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from pps_tools.switchboard import db
from pps_tools.switchboard.services import settings
from pps_tools.switchboard.util import UTC, get_zone, iso, now, now_iso, pick_color, token

DEMO_PASSWORD = "switchboard"
DEMO_DOMAIN = "pps.demo"

# key, name, role, title, color
PEOPLE = [
    ("owner", "Morgan Reyes", "owner", "Owner", "#3b5bdb"),
    ("manager", "Casey Nguyen", "manager", "Production Manager", "#7048e8"),
    ("frontdesk", "Sam Patel", "agent", "Customer Service", "#0c8599"),
    ("designer", "Jordan Lee", "agent", "Prepress & Design", "#c2255c"),
    ("press", "Alex Kim", "staff", "Press Operator", "#e8590c"),
    ("bindery", "Taylor Brooks", "staff", "Bindery & Finishing", "#2f9e44"),
    ("driver", "Riley Johnson", "staff", "Delivery Driver", "#f08c00"),
    ("parttime", "Jamie Ortiz", "staff", "Press Assistant (part-time)", "#1971c2"),
]


@dataclass
class SeedContext:
    users: dict[str, int] = field(default_factory=dict)       # key -> user id
    teams: dict[str, int] = field(default_factory=dict)
    data: dict = field(default_factory=dict)                   # modules share ids here
    rng: random.Random = field(default_factory=lambda: random.Random(1042))
    now: datetime = field(default_factory=now)

    @property
    def tz(self):
        return get_zone(settings.get("org.timezone"))

    def local(self, days: int = 0, hour: int = 9, minute: int = 0) -> datetime:
        """A wall-clock time in the org timezone, ``days`` from today."""
        today = self.now.astimezone(self.tz).date() + timedelta(days=days)
        return datetime(today.year, today.month, today.day, hour, minute, tzinfo=self.tz)

    def ago(self, **kwargs) -> str:
        return iso(self.now - timedelta(**kwargs))

    def ahead(self, **kwargs) -> str:
        return iso(self.now + timedelta(**kwargs))

    def uid(self, key: str) -> int:
        return self.users[key]


def seed_core(ctx: SeedContext) -> None:
    settings.set("org.name", "Priority Print Service")
    settings.set("org.timezone", "America/Phoenix")
    settings.set("demo.enabled", True)
    pw = generate_password_hash(DEMO_PASSWORD)
    stamp = now_iso()
    for key, name, role, title, color in PEOPLE:
        email = f"{name.split()[0].lower()}@{DEMO_DOMAIN}"
        ctx.users[key] = db.insert("users", {
            "email": email, "name": name, "password_hash": pw, "role": role, "title": title,
            "color": color or pick_color(email), "timezone": "America/Phoenix",
            "phone": f"+1602555{ctx.rng.randint(1000, 9999)}", "feed_token": token(),
            "pin_hash": generate_password_hash(str(1000 + len(ctx.users))),
            "created_at": iso(ctx.now - timedelta(days=200)), "updated_at": stamp,
        })
    office = ["owner", "manager", "frontdesk", "designer"]
    production = ["manager", "press", "bindery", "parttime", "designer"]
    for key, name, color, members in (
        ("office", "Front Office", "#0c8599", office),
        ("production", "Production", "#e8590c", production),
    ):
        ctx.teams[key] = db.insert("teams", {"name": name, "color": color, "created_at": stamp})
        for m in members:
            db.insert("team_members", {"team_id": ctx.teams[key], "user_id": ctx.users[m]})


def seed_demo() -> SeedContext:
    """Fill an empty database. Raises if anyone already exists."""
    from pps_tools.switchboard.modules import load_modules

    if db.scalar("SELECT COUNT(*) FROM users"):
        raise RuntimeError("This workspace already has people in it; use an empty data directory")
    ctx = SeedContext()
    modules = load_modules()
    with db.transaction():
        seed_core(ctx)
        setup_ctx = {"owner_id": ctx.users["owner"], "demo": True}
        for module in modules:
            if hasattr(module, "on_setup"):
                module.on_setup(setup_ctx)
        for module in modules:
            if hasattr(module, "seed"):
                module.seed(ctx)
    return ctx


__all__ = ["DEMO_PASSWORD", "SeedContext", "seed_demo", "UTC"]
