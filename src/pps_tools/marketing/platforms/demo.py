"""Sample data so the hub is useful before any platform is connected.

Every number is generated deterministically from (campaign, date), so the
same date range always shows the same figures and reloading the page
doesn't reshuffle anything. Pausing a campaign or changing its budget in
demo mode is remembered (in the settings table) and changes the numbers
from that day on, so the whole UI can be tried end to end.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from pps_tools.marketing.models import (
    ACTIVE,
    PAUSED,
    AdAccount,
    Campaign,
    MetricRow,
    PostContent,
    PublishResult,
    PublishTarget,
)
from pps_tools.marketing.platforms.base import Platform, daterange_days


@dataclass(frozen=True)
class DemoCampaign:
    campaign_id: str
    name: str
    objective: str
    daily_budget: float
    cpc: float
    ctr: float
    cvr: float
    order_value: float  # 0 for lead campaigns
    networks: tuple[tuple[str, float], ...] = ()
    paused_days_ago: Optional[int] = None


@dataclass(frozen=True)
class DemoAccount:
    account_id: str
    name: str
    # Monday..Sunday spend multipliers: B2B search dips at weekends, social rises.
    weekday: tuple[float, ...] = (1.05, 1.08, 1.06, 1.02, 0.95, 0.85, 0.82)
    campaigns: tuple[DemoCampaign, ...] = field(default_factory=tuple)


SOCIAL_WEEK = (0.94, 0.96, 0.98, 1.0, 1.04, 1.12, 1.1)

DEMO_ACCOUNTS: dict[str, DemoAccount] = {
    "google_ads": DemoAccount(
        "4825519306",
        "Priority Print Service",
        campaigns=(
            DemoCampaign("20481", "Search — Business Cards", "SEARCH", 60, 2.40, 0.062, 0.075, 85),
            DemoCampaign("20482", "Search — Brochures & Booklets", "SEARCH", 45, 3.10, 0.051, 0.058, 240),
            DemoCampaign("20483", "Performance Max — Online Print Shop", "PERFORMANCE_MAX", 80, 1.15, 0.018, 0.034, 160),
            DemoCampaign("20484", "Search — Same-Day Printing (Local)", "SEARCH", 35, 2.85, 0.071, 0.090, 110),
            DemoCampaign("20485", "Display — Remarketing", "DISPLAY", 15, 0.62, 0.006, 0.012, 140, paused_days_ago=12),
        ),
    ),
    "meta": DemoAccount(
        "act_1029384756",
        "Priority Print Service Ads",
        weekday=SOCIAL_WEEK,
        campaigns=(
            DemoCampaign(
                "120210000001", "Prospecting — Small Business Owners", "OUTCOME_SALES", 55, 1.05, 0.012, 0.021, 150,
                (("facebook", 0.55), ("instagram", 0.40), ("other", 0.05)),
            ),
            DemoCampaign(
                "120210000002", "Retargeting — Site Visitors 30d", "OUTCOME_SALES", 25, 0.85, 0.019, 0.048, 165,
                (("facebook", 0.50), ("instagram", 0.45), ("other", 0.05)),
            ),
            DemoCampaign(
                "120210000003", "Lead Gen — Bulk Print Quotes", "OUTCOME_LEADS", 30, 1.40, 0.011, 0.090, 0,
                (("facebook", 0.70), ("instagram", 0.27), ("other", 0.03)),
            ),
            DemoCampaign(
                "120210000004", "Reels — Custom Stickers", "OUTCOME_ENGAGEMENT", 20, 0.55, 0.009, 0.012, 45,
                (("facebook", 0.20), ("instagram", 0.75), ("other", 0.05)),
            ),
        ),
    ),
    "pinterest": DemoAccount(
        "549755885175",
        "Priority Print Service",
        weekday=SOCIAL_WEEK,
        campaigns=(
            DemoCampaign("626744128001", "Wedding Invitations — Inspiration", "CONSIDERATION", 20, 0.70, 0.006, 0.015, 210),
            DemoCampaign("626744128002", "Event Flyers & Posters — Consideration", "CONSIDERATION", 15, 0.55, 0.005, 0.012, 95),
        ),
    ),
    "x": DemoAccount(
        "18ce54d4x5t",
        "@PriorityPrint",
        campaigns=(
            DemoCampaign("8wku2", "Promoted Posts — Weekly Deals", "WEBSITE_CLICKS", 15, 0.75, 0.009, 0.008, 120),
            DemoCampaign("8wku3", "Followers — Local Businesses", "FOLLOWERS", 10, 0.95, 0.006, 0.003, 90),
        ),
    ),
    "linkedin": DemoAccount(
        "508812345",
        "Priority Print Service",
        campaigns=(
            DemoCampaign("613207301", "Sponsored Content — Marketing Managers", "WEBSITE_CONVERSION", 40, 6.80, 0.0055, 0.045, 620),
            DemoCampaign("613207302", "Lead Gen Forms — Corporate Print Programs", "LEAD_GENERATION", 35, 7.40, 0.0062, 0.110, 0),
        ),
    ),
    "tiktok": DemoAccount(
        "7012345678901234567",
        "Priority Print Service",
        weekday=SOCIAL_WEEK,
        campaigns=(
            DemoCampaign("1780000000001", "Spark Ads — Behind the Press", "TRAFFIC", 25, 0.48, 0.011, 0.009, 60),
            DemoCampaign("1780000000002", "In-Feed — Custom Stickers & Labels", "WEB_CONVERSIONS", 20, 0.52, 0.010, 0.014, 48),
        ),
    ),
    # Bing search: cheaper clicks than Google and an older, desk-bound B2B crowd.
    "microsoft_ads": DemoAccount(
        "180436527",
        "Priority Print Service",
        campaigns=(
            DemoCampaign("413052001", "Search — Business Cards", "SEARCH", 20, 1.65, 0.058, 0.070, 85),
            DemoCampaign("413052002", "Search — Brochures & Catalogs", "SEARCH", 15, 2.15, 0.047, 0.048, 200),
            DemoCampaign("413052003", "Performance Max — Online Print Shop", "PERFORMANCE_MAX", 15, 0.80, 0.016, 0.024, 140),
            DemoCampaign("413052004", "Audience — Remarketing on MSN & Outlook", "AUDIENCE", 8, 0.55, 0.005, 0.009, 120,
                         paused_days_ago=20),
        ),
    ),
}

DEMO_TARGETS: dict[str, list[PublishTarget]] = {
    "meta": [
        PublishTarget("meta", "facebook", "104857600", "Priority Print Service", "page"),
        PublishTarget("meta", "instagram", "17841400000000000", "@priorityprintservice", "instagram_account"),
    ],
    "pinterest": [
        PublishTarget("pinterest", "pinterest", "988776655443322110", "Print Inspiration", "board"),
        PublishTarget("pinterest", "pinterest", "988776655443322111", "Wedding Stationery Ideas", "board"),
    ],
    "x": [PublishTarget("x", "x", "1444555666777888999", "@PriorityPrint", "profile")],
    "linkedin": [PublishTarget("linkedin", "linkedin", "76543210", "Priority Print Service", "organization")],
}

DEMO_POST_URLS = {
    "facebook": "https://www.facebook.com/{target}/posts/{id}",
    "instagram": "https://www.instagram.com/p/{id}/",
    "pinterest": "https://www.pinterest.com/pin/{id}/",
    "x": "https://x.com/PriorityPrint/status/{id}",
    "linkedin": "https://www.linkedin.com/feed/update/urn:li:share:{id}/",
}


def _rng(*parts: object) -> random.Random:
    digest = hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


class DemoPlatform(Platform):
    """Stands in for a real connector, with the same name, networks and abilities."""

    def __init__(self, real: Platform):
        super().__init__(real.store, real.settings)
        self.key = real.key
        self.name = real.name
        self.short_name = real.short_name
        self.networks = real.networks
        self.supports_ads = real.supports_ads
        self.supports_publish = real.supports_publish
        self.demo = DEMO_ACCOUNTS.get(real.key)

    @property
    def configured(self) -> bool:
        return True

    @property
    def connected(self) -> bool:
        return True

    def token_warning(self) -> Optional[str]:
        return None

    # -- state the user changed while trying the demo ---------------------------

    def _override_key(self, campaign_id: str) -> str:
        return f"demo:campaign:{self.key}:{campaign_id}"

    def _overrides(self, campaign_id: str) -> dict:
        return self.store.get_setting(self._override_key(campaign_id), {}) or {}

    def _set_override(self, campaign_id: str, **changes) -> None:
        state = self._overrides(campaign_id)
        state.update(changes)
        self.store.set_setting(self._override_key(campaign_id), state)

    # -- ads ---------------------------------------------------------------------

    def accounts(self) -> list[AdAccount]:
        if not self.demo:
            return []
        return [
            AdAccount(
                platform=self.key,
                account_id=self.demo.account_id,
                name=self.demo.name,
                currency="USD",
                timezone="America/Phoenix",
                extra={"demo": True},
            )
        ]

    def discover_accounts(self) -> list[AdAccount]:
        return self.accounts()

    def _campaign_state(self, dc: DemoCampaign, today: date) -> tuple[str, Optional[str], float]:
        """(status, status-change date, current daily budget) for a demo campaign."""
        status, since = ACTIVE, None
        if dc.paused_days_ago is not None:
            status = PAUSED
            since = date.fromordinal(today.toordinal() - dc.paused_days_ago).isoformat()
        o = self._overrides(dc.campaign_id)
        if o.get("status"):
            status, since = o["status"], o.get("since")
        return status, since, float(o.get("daily_budget", dc.daily_budget))

    def list_campaigns(self, account: AdAccount) -> list[Campaign]:
        if not self.demo:
            return []
        today = date.today()
        out = []
        for dc in self.demo.campaigns:
            status, _, budget = self._campaign_state(dc, today)
            out.append(
                Campaign(
                    platform=self.key,
                    account_id=self.demo.account_id,
                    campaign_id=dc.campaign_id,
                    name=dc.name,
                    status=status,
                    raw_status=status,
                    objective=dc.objective,
                    daily_budget=budget,
                    currency="USD",
                    budget_editable=True,
                    extra={"demo": True},
                )
            )
        return out

    def fetch_metrics(self, account: AdAccount, start: date, end: date) -> list[MetricRow]:
        if not self.demo:
            return []
        today = date.today()
        end = min(end, today)
        rows: list[MetricRow] = []
        for dc in self.demo.campaigns:
            status, since, current_budget = self._campaign_state(dc, today)
            o = self._overrides(dc.campaign_id)
            budget_since = o.get("budget_since")
            for day in daterange_days(start, end):
                iso = day.isoformat()
                if status == PAUSED and since and iso >= since:
                    continue
                budget = current_budget if (budget_since and iso >= budget_since) else dc.daily_budget
                rows.extend(self._day_rows(dc, day, budget, today))
        return rows

    def _day_rows(self, dc: DemoCampaign, day: date, budget: float, today: date) -> list[MetricRow]:
        rng = _rng(self.key, dc.campaign_id, day.isoformat())
        wave = 1 + 0.12 * math.sin(day.toordinal() / 23 + len(dc.name))
        weekday = self.demo.weekday[day.weekday()]
        spend = budget * rng.uniform(0.82, 0.99) * weekday * wave
        if day == today:
            now = datetime.now()
            spend *= max(now.hour * 60 + now.minute, 30) / 1440
        cpc = dc.cpc * rng.uniform(0.85, 1.18)
        clicks = max(int(spend / cpc), 0)
        impressions = int(clicks / (dc.ctr * rng.uniform(0.85, 1.15))) if clicks else int(spend * 120)
        expected = clicks * dc.cvr * rng.uniform(0.7, 1.3)
        conversions = float(int(expected) + (1 if rng.random() < expected % 1 else 0))
        value = conversions * dc.order_value * rng.uniform(0.75, 1.3) if dc.order_value else 0.0
        splits = dc.networks or ((self.networks[0] if self.networks else self.key, 1.0),)
        rows = []
        for network, share in splits:
            rows.append(
                MetricRow(
                    platform=self.key,
                    network=network,
                    account_id=self.demo.account_id,
                    campaign_id=dc.campaign_id,
                    campaign_name=dc.name,
                    date=day.isoformat(),
                    impressions=int(impressions * share),
                    clicks=int(clicks * share),
                    spend=round(spend * share, 2),
                    conversions=round(conversions * share, 2),
                    conversion_value=round(value * share, 2),
                    currency="USD",
                )
            )
        return rows

    def set_status(self, campaign: Campaign, status: str) -> None:
        self._set_override(campaign.campaign_id, status=status, since=date.today().isoformat())

    def set_daily_budget(self, campaign: Campaign, amount: float) -> None:
        self._set_override(
            campaign.campaign_id, daily_budget=round(float(amount), 2), budget_since=date.today().isoformat()
        )

    # -- publishing ----------------------------------------------------------------

    def discover_targets(self) -> list[tuple[PublishTarget, Optional[dict]]]:
        return [(t, None) for t in DEMO_TARGETS.get(self.key, [])]

    def targets(self) -> list[PublishTarget]:
        return list(DEMO_TARGETS.get(self.key, []))

    def publish(self, target: PublishTarget, content: PostContent) -> PublishResult:
        post_id = str(_rng(target.key, content.text, datetime.now().isoformat()).randrange(10**15, 10**16))
        url = DEMO_POST_URLS.get(target.network, "").format(target=target.target_id, id=post_id) or None
        return PublishResult(ok=True, network=target.network, target_id=target.target_id, remote_id=post_id, url=url)
