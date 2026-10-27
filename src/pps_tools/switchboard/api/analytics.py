"""Reports API.

GET /api/analytics/inbox|team|jobs?start=YYYY-MM-DD&end=YYYY-MM-DD   (JSON)
    inbox also takes team_id and channel_id.
Add ?format=csv&table=<name> for a CSV of one table (see services.analytics.TABLES).
"""

from __future__ import annotations

from flask import Blueprint, Response, request

from pps_tools.switchboard.services import analytics
from pps_tools.switchboard.web import as_int, bad_request, current_user, not_found, ok, require

bp = Blueprint("analytics", __name__)

DEFAULT_TABLE = {"inbox": "daily", "team": "people", "jobs": "weekly"}


@bp.get("/api/analytics/<report>")
@require("analytics")
def get_report(report: str):
    if report not in analytics.TABLES:
        not_found("No such report")
    period = analytics.period_from_args(request.args.get("start"), request.args.get("end"))
    if report == "inbox":
        data = analytics.inbox_report(
            period,
            team_id=as_int(request.args.get("team_id"), "team_id"),
            channel_id=as_int(request.args.get("channel_id"), "channel_id"),
            user=current_user(),
        )
    elif report == "team":
        data = analytics.team_report(period)
    else:
        data = analytics.jobs_report(period)
    if (request.args.get("format") or "").lower() == "csv":
        table = request.args.get("table") or DEFAULT_TABLE[report]
        if table not in analytics.TABLES[report]:
            bad_request(f"Unknown table '{table}'. Choose one of: {', '.join(analytics.TABLES[report])}")
        filename = f"{report}-{table}-{period.start.isoformat()}-to-{period.end.isoformat()}.csv"
        return Response(
            analytics.to_csv(report, table, data),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
        )
    return ok(data)


def seed(ctx) -> None:
    from pps_tools.switchboard.demo.analytics import seed_history

    seed_history(ctx)
