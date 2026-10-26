"""AI performance review: Claude reads the cross-platform numbers and says what to do.

The snapshot sent to Claude is built from the same data the dashboard
shows. Recommendations that name a campaign are checked against the real
campaign list, and pause / budget suggestions can be applied with one
click — through the hub, with the same budget-change cap the rules use.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from pps_tools.marketing import analytics as an
from pps_tools.marketing.ai import AIError, default_client, structured_request
from pps_tools.marketing.models import ACTIVE, PAUSED, network_for
from pps_tools.marketing.pacing import pacing_for

ACTIONS = ("pause", "enable", "increase_budget", "decrease_budget", "new_creative", "targeting", "other")
MAX_CAMPAIGNS = 40

SYSTEM_TEMPLATE = """You are a performance-marketing analyst reviewing a small business's paid advertising across Google Ads, Meta (Facebook and Instagram), Pinterest, X, LinkedIn and TikTok.

About the business:
{brand}

How to work:
- Ground every statement in the numbers provided. Quote the figures that matter (spend, conversions, CPA, ROAS, CTR) and compare against the previous period.
- Platforms report conversions differently (attribution windows, view-through), so compare each channel with its own history before comparing channels with each other, and say so when it matters.
- Treat small numbers with care: under roughly 10 conversions or $100 of spend, call the result directional rather than conclusive.
- Recommendations must be specific and doable this week. Each names one platform and, where it is about a single campaign, that campaign's exact "key" from the data (otherwise leave campaign_key empty).
- Use action "pause", "enable", "increase_budget" or "decrease_budget" only for one named campaign; for budget changes give change_pct between 5 and {cap}. Use "new_creative", "targeting" or "other" for everything else, with change_pct 0.
- budget_shifts move monthly money between platforms (platform keys from the data) when the evidence supports it; leave the list empty otherwise.
- Write plainly for a busy owner: short sentences, no jargon without a quick explanation."""


def build_snapshot(hub, period: an.Period) -> dict:
    """Everything Claude needs, in a compact JSON-able form."""
    current_rows, errors = hub.metrics(period.start, period.end)
    previous = period.previous()
    previous_rows, _ = hub.metrics(previous.start, previous.end)
    campaigns, campaign_errors = hub.campaigns()
    errors.update(campaign_errors)

    def compact(t) -> dict:
        d = t.to_dict()
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}

    prev_by_campaign = an.by_campaign(previous_rows)
    cur_by_campaign = an.by_campaign(current_rows)
    rows = []
    for c in campaigns:
        cur = cur_by_campaign.get(c.key)
        if cur is None and c.status != ACTIVE:
            continue
        prev = prev_by_campaign.get(c.key)
        rows.append(
            {
                "key": c.key,
                "platform": c.platform,
                "name": c.name,
                "status": c.status,
                "objective": c.objective,
                "daily_budget": c.daily_budget,
                "budget_editable": c.budget_editable,
                "current": compact(cur) if cur else None,
                "previous": compact(prev) if prev else None,
            }
        )
    rows.sort(key=lambda r: -((r["current"] or {}).get("spend") or 0))

    labels = {k: p.name for k, p in hub.platforms.items()}
    previous_by_platform = an.by_platform(previous_rows)

    return {
        "period": {"start": period.start.isoformat(), "end": period.end.isoformat(), "label": period.label},
        "previous_period": {"start": previous.start.isoformat(), "end": previous.end.isoformat()},
        "currencies": an.currencies(current_rows),
        "totals": {"current": compact(an.totals(current_rows)), "previous": compact(an.totals(previous_rows))},
        "by_platform": {
            k: {"label": labels.get(k, k), "current": compact(v), "previous": compact(previous_by_platform.get(k) or an.Totals())}
            for k, v in an.by_platform(current_rows).items()
        },
        "by_network": {network_for(k).label: compact(v) for k, v in an.by_network(current_rows)},
        "campaigns": rows[:MAX_CAMPAIGNS],
        "budget_pacing": [p.to_dict() for p in pacing_for(hub)],
        "data_problems": errors,
        "demo_data": hub.demo_active(),
    }


SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "wins": {"type": "array", "items": {"type": "string"}},
        "concerns": {"type": "array", "items": {"type": "string"}},
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "platform": {"type": "string"},
                    "campaign_key": {"type": "string"},
                    "action": {"type": "string", "enum": list(ACTIONS)},
                    "change_pct": {"type": "number"},
                    "expected_impact": {"type": "string"},
                },
                "required": ["title", "detail", "priority", "platform", "campaign_key", "action", "change_pct", "expected_impact"],
                "additionalProperties": False,
            },
        },
        "budget_shifts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from_platform": {"type": "string"},
                    "to_platform": {"type": "string"},
                    "monthly_amount": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": ["from_platform", "to_platform", "monthly_amount", "rationale"],
                "additionalProperties": False,
            },
        },
        "watch_next": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "summary", "wins", "concerns", "recommendations", "budget_shifts", "watch_next"],
    "additionalProperties": False,
}


class Analyst:
    def __init__(
        self,
        brand_context: str,
        model: str = "claude-opus-5-5",
        client: Any = None,
        effort: str = "high",
        max_budget_change_pct: float = 50.0,
    ):
        self.brand_context = brand_context
        self.model = model
        self.effort = effort
        self.cap = max_budget_change_pct
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = default_client()
        return self._client

    def analyze(self, snapshot: dict, question: str = "") -> dict:
        if not snapshot.get("campaigns") and not (snapshot.get("totals") or {}).get("current", {}).get("spend"):
            raise AIError("There's no ad data in this date range to analyze yet.")
        user = "Review this advertising data and tell me what to do next.\n\n"
        if question.strip():
            user += f"I especially want to know: {question.strip()[:1000]}\n\n"
        user += "Data (JSON):\n" + json.dumps(snapshot, ensure_ascii=False, default=str)
        report = structured_request(
            self.client,
            model=self.model,
            system=SYSTEM_TEMPLATE.format(brand=self.brand_context, cap=int(self.cap)),
            user=user,
            schema=SCHEMA,
            effort=self.effort,
        )
        return self.vet(report, snapshot)

    def vet(self, report: dict, snapshot: dict) -> dict:
        """Drop campaign actions that don't line up with real campaigns or safe limits."""
        campaigns = {c["key"]: c for c in snapshot.get("campaigns", [])}
        for rec in report.get("recommendations", []):
            rec["applicable"] = False
            campaign = campaigns.get(rec.get("campaign_key") or "")
            if campaign is None:
                rec["campaign_key"] = ""
                if rec.get("action") in ("pause", "enable", "increase_budget", "decrease_budget"):
                    rec["action"] = "other"
                continue
            rec["campaign_name"] = campaign["name"]
            action = rec.get("action")
            if action == "pause" and campaign["status"] == ACTIVE:
                rec["applicable"] = True
            elif action == "enable" and campaign["status"] == PAUSED:
                rec["applicable"] = True
            elif action in ("increase_budget", "decrease_budget") and campaign.get("budget_editable") and campaign.get("daily_budget"):
                pct = max(1.0, min(abs(float(rec.get("change_pct") or 0)), self.cap))
                factor = 1 + pct / 100 if action == "increase_budget" else 1 - pct / 100
                rec["change_pct"] = pct
                rec["current_budget"] = campaign["daily_budget"]
                rec["new_budget"] = round(campaign["daily_budget"] * factor, 2)
                rec["applicable"] = True
        return report


def apply_recommendation(hub, rec: dict) -> str:
    """Carry out a vetted recommendation; returns a short confirmation."""
    key = rec.get("campaign_key")
    action = rec.get("action")
    if not key:
        raise AIError("This recommendation isn't tied to a campaign.")
    if action == "pause":
        c = hub.set_campaign_status(key, PAUSED, actor="AI insights")
        return f"Paused “{c.name}”."
    if action == "enable":
        c = hub.set_campaign_status(key, ACTIVE, actor="AI insights")
        return f"Enabled “{c.name}”."
    if action in ("increase_budget", "decrease_budget"):
        new_budget: Optional[float] = rec.get("new_budget")
        if not new_budget:
            raise AIError("No budget amount to apply.")
        c = hub.set_campaign_budget(key, float(new_budget), actor="AI insights", enforce_cap=True)
        return f"Daily budget of “{c.name}” set to {c.daily_budget:,.2f}."
    raise AIError("That recommendation can't be applied automatically.")
