"""Aggregation over normalized metric rows: totals, breakdowns, daily series."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Iterable, Optional

from pps_tools.marketing.models import NETWORKS, MetricRow, Totals

# Metrics where a smaller number is the good direction.
LOWER_IS_BETTER = {"cpa", "cpc", "cpm"}
# Metrics with no inherent good direction (more spend isn't good or bad by itself).
NEUTRAL = {"spend", "impressions"}

METRIC_LABELS = {
    "spend": "Spend",
    "conversion_value": "Revenue",
    "roas": "ROAS",
    "conversions": "Conversions",
    "cpa": "Cost / conversion",
    "ctr": "CTR",
    "cpc": "CPC",
    "cpm": "CPM",
    "clicks": "Clicks",
    "impressions": "Impressions",
    "cvr": "Conversion rate",
}

PRESETS = {
    "7d": "Last 7 days",
    "14d": "Last 14 days",
    "30d": "Last 30 days",
    "90d": "Last 90 days",
    "mtd": "Month to date",
    "last_month": "Last month",
}


@dataclass
class Period:
    start: date
    end: date
    label: str
    preset: str = "custom"

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous(self) -> "Period":
        """The same number of days immediately before this period."""
        end = self.start - timedelta(days=1)
        return Period(end - timedelta(days=self.days - 1), end, "Previous period")


def resolve_period(
    preset: Optional[str], start: Optional[str] = None, end: Optional[str] = None, today: Optional[date] = None
) -> Period:
    """Turn a preset name (or explicit dates) into a concrete date range.

    "Last N days" ends yesterday, like the ad platforms' own UIs, so today's
    half-finished numbers don't drag the comparison down.
    """
    today = today or date.today()
    if start and end:
        try:
            s, e = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError:
            s = e = None
        if s and e:
            s, e = sorted((s, e))
            e = min(e, today)
            s = min(s, e)
            return Period(s, e, f"{s:%b} {s.day} – {e:%b} {e.day}, {e.year}", "custom")
    preset = preset if preset in PRESETS else "30d"
    if preset == "mtd":
        return Period(today.replace(day=1), today, PRESETS[preset], preset)
    if preset != "last_month":
        n = int(preset.rstrip("d"))
        e = today - timedelta(days=1)
        return Period(e - timedelta(days=n - 1), e, PRESETS[preset], preset)
    first_this = today.replace(day=1)
    e = first_this - timedelta(days=1)
    return Period(e.replace(day=1), e, PRESETS[preset], preset)


def totals(rows: Iterable[MetricRow]) -> Totals:
    t = Totals()
    for r in rows:
        t.add(r)
    return t


def group(rows: Iterable[MetricRow], key: Callable[[MetricRow], str]) -> dict[str, Totals]:
    out: dict[str, Totals] = defaultdict(Totals)
    for r in rows:
        out[key(r)].add(r)
    return dict(out)


def by_network(rows: Iterable[MetricRow]) -> list[tuple[str, Totals]]:
    """Totals per network, in the fixed network order (never re-sorted by value)."""
    grouped = group(rows, lambda r: r.network if r.network in NETWORKS else "other")
    order = list(NETWORKS)
    return sorted(grouped.items(), key=lambda kv: order.index(kv[0]))


def by_platform(rows: Iterable[MetricRow]) -> dict[str, Totals]:
    return group(rows, lambda r: r.platform)


def by_campaign(rows: Iterable[MetricRow]) -> dict[str, Totals]:
    return group(rows, lambda r: r.campaign_key)


def days_between(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def daily(
    rows: Iterable[MetricRow],
    start: date,
    end: date,
    metric: str = "spend",
    key: Optional[Callable[[MetricRow], str]] = None,
) -> dict[str, list[float]]:
    """{series: [value per day]} with every day present (missing days are 0).

    With `key=None` there is a single "total" series. Ratio metrics (ROAS, CTR, ...)
    are computed per day from the summed parts, never averaged.
    """
    dates = days_between(start, end)
    index = {d: i for i, d in enumerate(dates)}
    buckets: dict[str, list[Totals]] = defaultdict(lambda: [Totals() for _ in dates])
    for r in rows:
        i = index.get(r.date)
        if i is None:
            continue
        buckets[key(r) if key else "total"][i].add(r)
    out = {}
    for series, days in buckets.items():
        out[series] = [round(t.metric(metric) or 0.0, 4) for t in days]
    if not out and key is None:
        out["total"] = [0.0 for _ in dates]
    return out


def change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """Fractional change (0.12 = +12%); None when there's nothing to compare against."""
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous)


def delta_tone(metric: str, delta: Optional[float]) -> str:
    """'good' | 'bad' | 'neutral' for coloring a delta."""
    if delta is None or abs(delta) < 0.005 or metric in NEUTRAL:
        return "neutral"
    up = delta > 0
    good = (not up) if metric in LOWER_IS_BETTER else up
    return "good" if good else "bad"


def currencies(rows: Iterable[MetricRow]) -> list[str]:
    return sorted({r.currency for r in rows if r.currency})
