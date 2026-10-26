"""Automation rules: "if a campaign's <metric> over the last N days is <op> X, then <action>".

Rules only ever look at ACTIVE campaigns, respect a minimum-spend guard so
they don't act on too little data, and have a per-campaign cooldown so a
rule can't fire again and again. Every run can be previewed as a dry run
first; real runs write to the activity log through the hub.
"""

from __future__ import annotations

import math
import operator
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Optional

from pps_tools.marketing.analytics import METRIC_LABELS, by_campaign
from pps_tools.marketing.http import PlatformAPIError
from pps_tools.marketing.models import ACTIVE, PAUSED, Totals

METRICS = ("spend", "cpa", "roas", "conversions", "conversion_value", "ctr", "cpc", "cpm", "clicks", "impressions")
# Thresholds for these are entered and shown in percent.
PERCENT_METRICS = {"ctr", "cvr"}
MONEY_METRICS = {"spend", "cpa", "cpc", "cpm", "conversion_value"}

OPERATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
ACTIONS = {
    "notify": "Log an alert",
    "pause": "Pause the campaign",
    "budget_up": "Raise daily budget by %",
    "budget_down": "Lower daily budget by %",
}
LOOKBACKS = (1, 3, 7, 14, 30)

DEFAULT_RULE = {
    "name": "",
    "enabled": True,
    "platform": "any",
    "name_contains": "",
    "metric": "cpa",
    "operator": ">",
    "threshold": 50.0,
    "lookback_days": 7,
    "min_spend": 0.0,
    "min_impressions": 0,
    "action": "notify",
    "action_value": 15.0,
    "cooldown_hours": 24,
}

TEMPLATES = [
    {
        "name": "Pause campaigns whose cost per conversion runs high",
        "metric": "cpa", "operator": ">", "threshold": 60, "lookback_days": 7,
        "min_spend": 75, "action": "pause", "cooldown_hours": 24,
    },
    {
        "name": "Alert when a campaign spends without converting",
        "metric": "conversions", "operator": "<", "threshold": 1, "lookback_days": 7,
        "min_spend": 100, "action": "notify", "cooldown_hours": 24,
    },
    {
        "name": "Scale winners: +15% budget when ROAS is above 4",
        "metric": "roas", "operator": ">", "threshold": 4, "lookback_days": 7,
        "min_spend": 50, "action": "budget_up", "action_value": 15, "cooldown_hours": 72,
    },
    {
        "name": "Alert on low click-through rate",
        "metric": "ctr", "operator": "<", "threshold": 0.5, "lookback_days": 14,
        "min_impressions": 2000, "action": "notify", "cooldown_hours": 72,
    },
    {
        "name": "Alert when a campaign spends over $150 in a day",
        "metric": "spend", "operator": ">", "threshold": 150, "lookback_days": 1,
        "action": "notify", "cooldown_hours": 20,
    },
]


class RuleError(ValueError):
    pass


def clean_rule(data: dict, platforms: list[str], max_budget_change_pct: float = 50.0) -> dict:
    """Validate user input into a rule dict (raises RuleError with a readable message)."""
    rule = dict(DEFAULT_RULE)
    rule.update({k: v for k, v in data.items() if k in DEFAULT_RULE and v is not None and v != ""})
    rule["name"] = str(rule["name"]).strip()[:120]
    if not rule["name"]:
        raise RuleError("Give the rule a name.")
    if rule["platform"] != "any" and rule["platform"] not in platforms:
        raise RuleError("Unknown platform.")
    if rule["metric"] not in METRICS:
        raise RuleError("Unknown metric.")
    if rule["operator"] not in OPERATORS:
        raise RuleError("Unknown comparison.")
    if rule["action"] not in ACTIONS:
        raise RuleError("Unknown action.")
    try:
        rule["threshold"] = float(rule["threshold"])
        rule["lookback_days"] = int(rule["lookback_days"])
        rule["min_spend"] = float(rule["min_spend"] or 0)
        rule["min_impressions"] = int(float(rule["min_impressions"] or 0))
        rule["action_value"] = float(rule["action_value"] or 0)
        rule["cooldown_hours"] = float(rule["cooldown_hours"] or 0)
    except (TypeError, ValueError) as exc:
        raise RuleError("Numbers in the rule must be numbers.") from exc
    if rule["lookback_days"] not in LOOKBACKS:
        raise RuleError(f"Look-back must be one of {', '.join(map(str, LOOKBACKS))} days.")
    if rule["action"] in ("budget_up", "budget_down"):
        if not 0 < rule["action_value"] <= max_budget_change_pct:
            raise RuleError(f"Budget change must be between 0 and {max_budget_change_pct:.0f}%.")
    if isinstance(rule["enabled"], str):
        rule["enabled"] = rule["enabled"].lower() in ("1", "true", "on", "yes")
    rule["name_contains"] = str(rule["name_contains"] or "").strip()
    return rule


def metric_value(totals: Totals, metric: str) -> Optional[float]:
    """The value a rule compares, in the units the user typed the threshold in."""
    if metric == "cpa" and totals.conversions == 0:
        # Spending with zero conversions is the worst cost per conversion of all.
        return math.inf if totals.spend > 0 else None
    value = totals.metric(metric)
    if value is None:
        return None
    return value * 100 if metric in PERCENT_METRICS else value


def describe(rule: dict) -> str:
    metric = METRIC_LABELS.get(rule["metric"], rule["metric"])
    th = rule["threshold"]
    if rule["metric"] in PERCENT_METRICS:
        th_text = f"{th:g}%"
    elif rule["metric"] in MONEY_METRICS:
        th_text = f"${th:,.2f}"
    else:
        th_text = f"{th:g}"
    window = "today" if rule["lookback_days"] == 1 else f"over the last {rule['lookback_days']} days"
    action = ACTIONS[rule["action"]].replace("%", f"{rule['action_value']:g}%")
    return f"If {metric} {window} is {rule['operator']} {th_text}, then {action.lower()}"


@dataclass
class RuleOutcome:
    rule_id: Optional[int]
    rule_name: str
    campaign_key: str
    campaign_name: str
    platform: str
    metric: str
    value: Optional[float]
    action: str
    status: str  # would_apply | applied | alerted | cooldown | failed | skipped
    message: str

    def to_dict(self) -> dict:
        data = asdict(self)
        if data["value"] is not None and math.isinf(data["value"]):
            data["value"] = None
            data["value_text"] = "no conversions"
        return data


def evaluate(
    hub,
    rules: list[dict],
    dry_run: bool = True,
    today: Optional[date] = None,
    now: Optional[float] = None,
) -> list[RuleOutcome]:
    today = today or date.today()
    now = now if now is not None else time.time()
    rules = [r for r in rules if r.get("enabled", True)]
    if not rules:
        return []

    campaigns, errors = hub.campaigns(refresh=not dry_run)
    if errors and not campaigns:
        raise PlatformAPIError("Rules", "; ".join(f"{k}: {v}" for k, v in errors.items()))
    active = [c for c in campaigns if c.status == ACTIVE]

    windows: dict[int, dict[str, Totals]] = {}
    outcomes: list[RuleOutcome] = []
    for rule in rules:
        days = int(rule["lookback_days"])
        if days not in windows:
            rows, _ = hub.metrics(today - timedelta(days=days - 1), today, refresh=not dry_run)
            windows[days] = by_campaign(rows)
        grouped = windows[days]
        compare = OPERATORS[rule["operator"]]
        needle = (rule.get("name_contains") or "").lower()

        for c in active:
            if rule["platform"] != "any" and c.platform != rule["platform"]:
                continue
            if needle and needle not in c.name.lower():
                continue
            totals = grouped.get(c.key, Totals())
            if totals.spend < float(rule.get("min_spend") or 0):
                continue
            if totals.impressions < int(rule.get("min_impressions") or 0):
                continue
            value = metric_value(totals, rule["metric"])
            if value is None or not compare(value, float(rule["threshold"])):
                continue
            outcomes.append(_act(hub, rule, c, value, dry_run, now))

        if not dry_run and rule.get("id") is not None:
            hub.store.mark_rule_run(rule["id"])
    return outcomes


def _act(hub, rule: dict, campaign, value: float, dry_run: bool, now: float) -> RuleOutcome:
    def outcome(status: str, message: str) -> RuleOutcome:
        return RuleOutcome(
            rule_id=rule.get("id"),
            rule_name=rule["name"],
            campaign_key=campaign.key,
            campaign_name=campaign.name,
            platform=campaign.platform,
            metric=rule["metric"],
            value=value,
            action=rule["action"],
            status=status,
            message=message,
        )

    rule_id = rule.get("id")
    cooldown = float(rule.get("cooldown_hours") or 0) * 3600
    if rule_id is not None and cooldown:
        last = hub.store.last_rule_fire(rule_id, campaign.key)
        if last is not None and now - last < cooldown:
            hours = (cooldown - (now - last)) / 3600
            return outcome("cooldown", f"Matched, but cooling down for another {hours:.0f}h.")

    action = rule["action"]
    pct = float(rule.get("action_value") or 0)
    new_budget = None
    if action in ("budget_up", "budget_down"):
        if not campaign.budget_editable or not campaign.daily_budget:
            return outcome("skipped", "Matched, but this campaign has no editable daily budget.")
        factor = 1 + pct / 100 if action == "budget_up" else 1 - pct / 100
        new_budget = round(campaign.daily_budget * factor, 2)

    if dry_run:
        plan = {
            "notify": "Would log an alert.",
            "pause": "Would pause this campaign.",
            "budget_up": f"Would raise the daily budget to {new_budget:,.2f}." if new_budget else "",
            "budget_down": f"Would lower the daily budget to {new_budget:,.2f}." if new_budget else "",
        }[action]
        return outcome("would_apply", plan)

    actor = f"rule: {rule['name']}"
    try:
        if action == "notify":
            hub.store.log(
                "rule.alert",
                f"Rule “{rule['name']}” matched “{campaign.name}” ({_fmt(rule['metric'], value)})",
                campaign.platform,
                {"rule_id": rule_id, "campaign": campaign.key, "metric": rule["metric"], "value": _json_value(value)},
            )
            result = outcome("alerted", "Alert logged.")
        elif action == "pause":
            hub.set_campaign_status(campaign.key, PAUSED, actor=actor)
            result = outcome("applied", "Campaign paused.")
        else:
            hub.set_campaign_budget(campaign.key, new_budget, actor=actor, enforce_cap=True)
            result = outcome("applied", f"Daily budget set to {new_budget:,.2f}.")
    except Exception as exc:  # report per campaign and keep going
        return outcome("failed", getattr(exc, "message", None) or str(exc))

    if rule_id is not None:
        hub.store.record_rule_fire(rule_id, campaign.key, now)
    return result


def _fmt(metric: str, value: float) -> str:
    label = METRIC_LABELS.get(metric, metric)
    if math.isinf(value):
        return f"{label}: no conversions"
    if metric in PERCENT_METRICS:
        return f"{label} {value:.2f}%"
    if metric in MONEY_METRICS:
        return f"{label} ${value:,.2f}"
    return f"{label} {value:,.2f}"


def _json_value(value: float) -> Optional[float]:
    return None if math.isinf(value) else round(value, 4)
