"""Switchboard: a shared team inbox with staffing and job scheduling.

Email, SMS, WhatsApp, website chat and API channels land in one collaborative inbox
(assignments, comments, shared drafts, labels, rules). The same app schedules people
(shifts, time off, time clock) and work (jobs, stages, operations on equipment).

Run it with ``pps switchboard run`` or ``python switchboard.py``.
"""

__all__ = ["create_app"]


def create_app(*args, **kwargs):
    from pps_tools.switchboard.app import create_app as _create_app

    return _create_app(*args, **kwargs)
