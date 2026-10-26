"""Feature modules, each an ``api/<name>.py`` file.

A module must define ``bp`` (a Flask Blueprint) and may define:

* ``bootstrap(user) -> dict``  — merged into ``GET /api/bootstrap`` (reference data the
  web app caches: labels, positions, job stages, ...).
* ``worker_tasks() -> list[worker.Task]`` — periodic background jobs.
* ``seed(ctx) -> None`` — demo data for ``pps switchboard seed`` (see seed.py).
* ``on_app(app) -> None`` — any extra app setup.
* ``on_setup(ctx) -> None`` — defaults for a brand-new workspace (ctx: owner_id, demo).
* ``badges(user) -> dict`` — counts for the left rail, e.g. {"chat": 3}.
* ``search(user, q, limit) -> list[dict]`` — command-palette results
  ({type, id, title, subtitle, url, icon, group}).

Order matters only for setup/seeding: later modules may use earlier modules' rows
(``on_setup`` runs for every module first, then each ``seed``).
"""

from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

MODULE_NAMES = [
    "core",       # bootstrap, users, teams, me, notifications, files, presence, events
    "auth",       # setup, login, invites, password reset
    "inbox",      # conversations, messages, comments, drafts, labels, responses
    "contacts",   # contacts, organizations, groups
    "channels",   # connected accounts: email, SMS, WhatsApp, chat widget, API
    "public",     # unauthenticated webhooks, chat widget API, forms, tracking
    "rules",      # automation rules
    "chat",       # team chat rooms and DMs
    "staffing",   # people, shifts, availability, time off, time clock
    "jobs",       # jobs, stages, resources, operations, schedule board
    "tasks",
    "calendar",
    "analytics",
    "ai",         # Claude-powered assists
    "admin",      # webhooks, API tokens, integrations, export
]


def load_modules() -> list[ModuleType]:
    """Import every module that exists. A module file that is missing is skipped (the
    app runs with whatever features are installed); a module that fails to import
    raises, so real bugs surface."""
    loaded = []
    for name in MODULE_NAMES:
        full = f"pps_tools.switchboard.api.{name}"
        if importlib.util.find_spec(full) is None:
            continue
        loaded.append(importlib.import_module(full))
    return loaded
