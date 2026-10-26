"""The hub ties the connectors, the store and demo mode together.

Every feature (dashboard, campaigns table, rules engine, AI insights, the
CLI) goes through `MarketingHub`, so caching, demo mode, error isolation
and the activity log behave the same everywhere. One platform failing
never takes the dashboard down: its error is reported next to the data
the other platforms returned.
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Callable, Iterable, Optional

import requests

from pps_tools.marketing.config import MarketingSettings
from pps_tools.marketing.http import NotConnectedError, PlatformAPIError
from pps_tools.marketing.models import (
    ACTIVE,
    PAUSED,
    AdAccount,
    Campaign,
    MetricRow,
    PostContent,
    PublishResult,
    PublishTarget,
    network_for,
    split_campaign_key,
)
from pps_tools.marketing.platforms import default_platform_classes
from pps_tools.marketing.platforms.base import Platform
from pps_tools.marketing.platforms.demo import DemoPlatform
from pps_tools.marketing.store import Store

logger = logging.getLogger(__name__)

CAMPAIGN_CACHE_SECONDS = 5 * 60
HISTORY_CACHE_SECONDS = 6 * 60 * 60


class HubError(RuntimeError):
    pass


class MarketingHub:
    def __init__(
        self,
        store: Store,
        settings: MarketingSettings,
        platform_classes: Optional[Iterable[type[Platform]]] = None,
        session_factory: Optional[Callable[[], requests.Session]] = None,
        max_workers: int = 6,
    ):
        self.store = store
        self.settings = settings
        self.max_workers = max_workers
        self.platforms: dict[str, Platform] = {}
        for cls in platform_classes or default_platform_classes():
            session = session_factory() if session_factory else None
            self.platforms[cls.key] = cls(store, settings, session=session)
        self.demos: dict[str, DemoPlatform] = {k: DemoPlatform(p) for k, p in self.platforms.items()}

    # -- demo mode ------------------------------------------------------------

    def demo_setting(self) -> str:
        mode = self.store.get_setting("demo_mode") or self.settings.demo or "auto"
        return mode if mode in ("auto", "on", "off") else "auto"

    def set_demo_setting(self, mode: str) -> None:
        if mode not in ("auto", "on", "off"):
            raise HubError(f"Unknown demo mode {mode!r}")
        self.store.set_setting("demo_mode", mode)
        self.store.cache_clear()

    def demo_active(self) -> bool:
        mode = self.demo_setting()
        if mode == "on":
            return True
        if mode == "off":
            return False
        return not self.store.connected_platforms()

    # -- sources --------------------------------------------------------------

    def platform(self, key: str) -> Platform:
        if key not in self.platforms:
            raise HubError(f"Unknown platform {key!r}")
        return self.platforms[key]

    def source(self, key: str) -> Platform:
        """The connector that serves data right now: the demo twin or the real one."""
        self.platform(key)
        return self.demos[key] if self.demo_active() else self.platforms[key]

    def sources(self) -> list[Platform]:
        if self.demo_active():
            return list(self.demos.values())
        return [p for p in self.platforms.values() if p.connected]

    def accounts(self) -> list[AdAccount]:
        if self.demo_active():
            return [a for d in self.demos.values() if d.supports_ads for a in d.accounts()]
        connected = {p.key for p in self.sources() if p.supports_ads}
        return [a for a in self.store.list_accounts(enabled_only=True) if a.platform in connected]

    def targets(self, enabled_only: bool = True) -> list[PublishTarget]:
        if self.demo_active():
            return [t for d in self.demos.values() if d.supports_publish for t in d.targets()]
        connected = {p.key for p in self.sources() if p.supports_publish}
        return [t for t in self.store.list_targets(enabled_only=enabled_only) if t.platform in connected]

    # -- reading --------------------------------------------------------------

    def _gather(
        self, jobs: list[tuple[AdAccount, Callable[[], list]]]
    ) -> tuple[list, dict[str, str], set[tuple[str, str]]]:
        """Run one job per account in parallel: (results, errors by label, failed (platform, account) pairs)."""
        results: list = []
        errors: dict[str, str] = {}
        failed: set[tuple[str, str]] = set()
        if not jobs:
            return results, errors, failed
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(jobs))) as pool:
            futures = [(acct, pool.submit(fn)) for acct, fn in jobs]
            for acct, fut in futures:
                name = f"{self.platforms[acct.platform].name} ({acct.name})"
                try:
                    results.extend(fut.result())
                    continue
                except (PlatformAPIError, NotConnectedError) as exc:
                    errors[name] = getattr(exc, "message", None) or str(exc)
                except Exception as exc:  # one broken platform must not break the page
                    logger.exception("%s failed", name)
                    errors[name] = f"Unexpected error: {exc}"
                failed.add((acct.platform, acct.account_id))
        return results, errors, failed

    def campaigns(self, refresh: bool = False) -> tuple[list[Campaign], dict[str, str]]:
        demo = self.demo_active()

        def job(acct: AdAccount) -> Callable[[], list]:
            def run() -> list[Campaign]:
                key = f"campaigns:{acct.platform}:{acct.account_id}"
                if not demo and not refresh:
                    cached = self.store.cache_get(key, CAMPAIGN_CACHE_SECONDS)
                    if cached is not None:
                        return [Campaign.from_dict(c) for c in cached]
                found = self.source(acct.platform).list_campaigns(acct)
                if not demo:
                    self.store.cache_set(key, [c.to_dict() for c in found])
                return found

            return run

        results, errors, _ = self._gather([(a, job(a)) for a in self.accounts()])
        return results, errors

    def metrics(self, start: date, end: date, refresh: bool = False) -> tuple[list[MetricRow], dict[str, str]]:
        rows, errors, _ = self.metrics_detail(start, end, refresh)
        return rows, errors

    def metrics_detail(
        self, start: date, end: date, refresh: bool = False
    ) -> tuple[list[MetricRow], dict[str, str], set[tuple[str, str]]]:
        """Like metrics(), plus the (platform, account) pairs whose numbers couldn't be read.

        Anything that acts on metrics (the rules engine) must skip those accounts:
        a failed fetch is not the same as zero spend.
        """
        demo = self.demo_active()
        # Recent days are still being attributed, so they are re-fetched sooner.
        ttl = self.settings.cache_minutes * 60
        if end < date.today() - timedelta(days=3):
            ttl = HISTORY_CACHE_SECONDS

        def job(acct: AdAccount) -> Callable[[], list]:
            def run() -> list[MetricRow]:
                key = f"metrics:{acct.platform}:{acct.account_id}:{start}:{end}"
                if not demo and not refresh:
                    cached = self.store.cache_get(key, ttl)
                    if cached is not None:
                        return [MetricRow.from_dict(r) for r in cached]
                rows = self.source(acct.platform).fetch_metrics(acct, start, end)
                if not demo:
                    self.store.cache_set(key, [r.to_dict() for r in rows])
                return rows

            return run

        return self._gather([(a, job(a)) for a in self.accounts()])

    def find_campaign(self, key: str) -> Campaign:
        platform, account_id, campaign_id = split_campaign_key(key)
        acct = next(
            (a for a in self.accounts() if a.platform == platform and a.account_id == account_id), None
        )
        if acct is None:
            raise HubError("That ad account isn't connected (or is switched off on the Connections page).")
        source = self.source(platform)
        for c in source.list_campaigns(acct):
            if c.campaign_id == campaign_id:
                return c
        raise HubError("Campaign not found — it may have been removed on the platform.")

    # -- changing campaigns ----------------------------------------------------

    def _after_change(self, campaign: Campaign) -> None:
        self.store.cache_clear(f"campaigns:{campaign.platform}:")

    def set_campaign_status(self, key: str, status: str, actor: str = "you") -> Campaign:
        if status not in (ACTIVE, PAUSED):
            raise HubError("Status must be ACTIVE or PAUSED.")
        campaign = self.find_campaign(key)
        source = self.source(campaign.platform)
        verb = "Paused" if status == PAUSED else "Enabled"
        summary = f"{verb} “{campaign.name}” on {source.name}"
        detail = {"campaign": key, "from": campaign.status, "to": status, "actor": actor, "demo": self.demo_active()}
        try:
            source.set_status(campaign, status)
        except PlatformAPIError as exc:
            self.store.log("campaign.status", f"Couldn't change status of “{campaign.name}”: {exc.message}",
                           campaign.platform, detail, ok=False)
            raise
        self.store.log("campaign.status", self._demo_prefix() + summary, campaign.platform, detail)
        self._after_change(campaign)
        campaign.status = status
        return campaign

    def set_campaign_budget(
        self, key: str, amount: float, actor: str = "you", enforce_cap: bool = False
    ) -> Campaign:
        if amount is None or not math.isfinite(amount) or amount <= 0:
            raise HubError("Budget must be a number greater than zero.")
        campaign = self.find_campaign(key)
        source = self.source(campaign.platform)
        if not campaign.budget_editable or campaign.daily_budget is None:
            raise HubError(
                f"“{campaign.name}” doesn't have a campaign-level daily budget the hub can edit "
                "(it may use ad-set, shared or lifetime budgets). Change it in the platform's own UI."
            )
        old = campaign.daily_budget
        if enforce_cap and old:
            cap = self.settings.max_budget_change_pct / 100
            low, high = old * (1 - cap), old * (1 + cap)
            if not (low - 0.005 <= amount <= high + 0.005):
                raise HubError(
                    f"Refusing to move the budget more than {self.settings.max_budget_change_pct:.0f}% "
                    f"in one step (from {old:.2f} to {amount:.2f})."
                )
        amount = round(float(amount), 2)
        detail = {"campaign": key, "from": old, "to": amount, "actor": actor, "demo": self.demo_active()}
        try:
            source.set_daily_budget(campaign, amount)
        except PlatformAPIError as exc:
            self.store.log("campaign.budget", f"Couldn't change budget of “{campaign.name}”: {exc.message}",
                           campaign.platform, detail, ok=False)
            raise
        self.store.log(
            "campaign.budget",
            self._demo_prefix()
            + f"Changed daily budget of “{campaign.name}” on {source.name} "
            f"from {old:,.2f} to {amount:,.2f} {campaign.currency}",
            campaign.platform,
            detail,
        )
        self._after_change(campaign)
        campaign.daily_budget = amount
        return campaign

    # -- publishing --------------------------------------------------------------

    def publish_to(self, target: PublishTarget, content: PostContent) -> PublishResult:
        source = self.source(target.platform)
        label = f"{network_for(target.network).label} · {target.name}"
        try:
            result = source.publish(target, content)
        except (PlatformAPIError, NotConnectedError) as exc:
            result = PublishResult(
                ok=False, network=target.network, target_id=target.target_id,
                error=getattr(exc, "message", None) or str(exc),
            )
        except Exception as exc:  # report it on the post instead of losing the whole batch
            logger.exception("Publishing to %s failed", label)
            result = PublishResult(ok=False, network=target.network, target_id=target.target_id, error=str(exc))
        if result.ok:
            self.store.log("post.publish", self._demo_prefix() + f"Published to {label}", target.platform,
                           {"url": result.url, "id": result.remote_id, "demo": self.demo_active()})
        else:
            self.store.log("post.publish", f"Publishing to {label} failed: {result.error}", target.platform,
                           {"error": result.error}, ok=False)
        return result

    def _demo_prefix(self) -> str:
        return "[demo] " if self.demo_active() else ""
