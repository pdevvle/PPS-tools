"""Monthly budget pacing: are we on course to spend what we planned?"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Optional

from pps_tools.marketing.analytics import by_platform

STATUS_LABELS = {
    "on_track": "On track",
    "under": "Underpacing",
    "over": "Overpacing",
    "way_over": "Well over budget",
    "early": "Too early to tell",
}

# Meter fill tone per status (status palette, always shown with a label).
STATUS_TONES = {
    "on_track": "good",
    "under": "warning",
    "over": "serious",
    "way_over": "critical",
    "early": "neutral",
}


@dataclass
class PacingRow:
    key: str
    label: str
    budget: float
    spent: float
    projected: Optional[float]
    expected_to_date: float
    days_left: int
    status: str

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def tone(self) -> str:
        return STATUS_TONES[self.status]

    @property
    def remaining(self) -> float:
        return max(self.budget - self.spent, 0.0)

    @property
    def daily_allowance(self) -> Optional[float]:
        """What can be spent per remaining day (including today) to land on budget."""
        return self.remaining / self.days_left if self.days_left else None

    @property
    def used_pct(self) -> float:
        return self.spent / self.budget if self.budget else 0.0

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "budget": self.budget,
            "spent": round(self.spent, 2),
            "projected": round(self.projected, 2) if self.projected is not None else None,
            "expected_to_date": round(self.expected_to_date, 2),
            "remaining": round(self.remaining, 2),
            "daily_allowance": round(self.daily_allowance, 2) if self.daily_allowance is not None else None,
            "days_left": self.days_left,
            "status": self.status,
            "status_label": self.status_label,
            "tone": self.tone,
        }


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def classify(budget: float, spent_mtd: float, projected: Optional[float]) -> str:
    if spent_mtd > budget:
        return "way_over"
    if projected is None:
        return "early"
    ratio = projected / budget
    if ratio > 1.15:
        return "way_over"
    if ratio > 1.05:
        return "over"
    if ratio < 0.85:
        return "under"
    return "on_track"


def pacing_row(
    key: str, label: str, budget: float, spent_mtd: float, spent_before_today: float, today: date
) -> PacingRow:
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    complete_days = today.day - 1
    projected = None
    if complete_days >= 2:
        # Project from finished days only; today's partial spend would skew it low.
        projected = spent_before_today / complete_days * days_in_month
    return PacingRow(
        key=key,
        label=label,
        budget=budget,
        spent=spent_mtd,
        projected=projected,
        expected_to_date=budget * complete_days / days_in_month,
        days_left=days_in_month - today.day + 1,
        status=classify(budget, spent_mtd, projected),
    )


def compute_pacing(
    budgets: dict[str, float],
    spend_mtd: dict[str, float],
    spend_before_today: dict[str, float],
    labels: dict[str, str],
    today: Optional[date] = None,
) -> list[PacingRow]:
    """One row per budgeted platform, plus a "total" row when a total budget is set."""
    today = today or date.today()
    rows = []
    for key, budget in budgets.items():
        if budget <= 0:
            continue
        if key == "total":
            spent, before = sum(spend_mtd.values()), sum(spend_before_today.values())
        else:
            spent, before = spend_mtd.get(key, 0.0), spend_before_today.get(key, 0.0)
        rows.append(pacing_row(key, labels.get(key, key), budget, spent, before, today))
    rows.sort(key=lambda r: (r.key != "total", list(labels).index(r.key) if r.key in labels else 99))
    return rows


def pacing_for(hub, today: Optional[date] = None) -> list[PacingRow]:
    """Pacing for this month's budgets, from the hub's month-to-date spend."""
    today = today or date.today()
    budgets = hub.store.get_budgets(month_key(today))
    if not budgets:
        return []
    rows, _ = hub.metrics(today.replace(day=1), today)
    spend_mtd = {p: t.spend for p, t in by_platform(rows).items()}
    before = {p: t.spend for p, t in by_platform(r for r in rows if r.date < today.isoformat()).items()}
    labels = {k: p.name for k, p in hub.platforms.items()}
    labels["total"] = "All platforms"
    return compute_pacing(budgets, spend_mtd, before, labels, today)
