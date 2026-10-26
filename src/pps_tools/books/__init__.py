"""PPS Books — double-entry bookkeeping with Stripe payments.

Layout:

    models/     SQLAlchemy tables (ledger, lists, banking, planning, settings)
    services/   business logic, no Flask: posting, inventory, tax, reports, Stripe...
    web/        Flask blueprints and the JSON API
    templates/, static/   the web UI

Run it with ``pps books serve`` (see ``pps books --help``).
"""

__version__ = "1.0.0"
