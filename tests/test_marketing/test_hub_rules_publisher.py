"""Hub, demo mode, automation rules and the publisher, driven by a fake platform."""

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from pps_tools.marketing import rules as rules_mod
from pps_tools.marketing import store as st
from pps_tools.marketing.http import PlatformAPIError
from pps_tools.marketing.hub import HubError, MarketingHub
from pps_tools.marketing.models import (
    ACTIVE,
    PAUSED,
    AdAccount,
    Campaign,
    MetricRow,
    PostContent,
    PublishResult,
    PublishTarget,
    Totals,
)
from pps_tools.marketing.platforms.base import Platform
from pps_tools.marketing.publisher import content_for, problems_for, publish_due, publish_post, x_length

from .conftest import connect


class FakePlatform(Platform):
    key = "fake"
    name = "Fake Ads"
    short_name = "Fake"
    networks = ("google",)
    supports_publish = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.calls = []
        self.fail_networks = set()
        self.campaigns = [
            Campaign("fake", "acct", "c1", "Search — Cards", ACTIVE, daily_budget=50.0, budget_editable=True),
            Campaign("fake", "acct", "c2", "Display — Retargeting", ACTIVE, daily_budget=20.0, budget_editable=False),
            Campaign("fake", "acct", "c3", "Old campaign", PAUSED, daily_budget=10.0, budget_editable=True),
        ]
        self.rows = []

    def list_campaigns(self, account):
        return [Campaign(**{**c.__dict__}) for c in self.campaigns]

    def fetch_metrics(self, account, start, end):
        self.calls.append(("metrics", start, end))
        return [r for r in self.rows if start.isoformat() <= r.date <= end.isoformat()]

    def set_status(self, campaign, status):
        self.calls.append(("status", campaign.campaign_id, status))
        for c in self.campaigns:
            if c.campaign_id == campaign.campaign_id:
                c.status = status

    def set_daily_budget(self, campaign, amount):
        self.calls.append(("budget", campaign.campaign_id, amount))

    def publish(self, target, content):
        if target.network in self.fail_networks:
            raise PlatformAPIError(self.name, "rejected")
        self.calls.append(("publish", target.network, content.text, content.link))
        return PublishResult(True, target.network, target.target_id, remote_id="p1", url=f"https://example.com/{target.network}")


class BrokenPlatform(Platform):
    key = "broken"
    name = "Broken Ads"
    networks = ("tiktok",)

    def list_campaigns(self, account):
        raise PlatformAPIError(self.name, "token expired")

    def fetch_metrics(self, account, start, end):
        raise PlatformAPIError(self.name, "token expired")


def metric(day, campaign="c1", **kw):
    base = dict(impressions=2000, clicks=100, spend=100.0, conversions=2.0, conversion_value=150.0)
    base.update(kw)
    return MetricRow("fake", "google", "acct", campaign, campaign, day.isoformat(), **base)


@pytest.fixture
def hub(settings, store):
    h = MarketingHub(store, settings, platform_classes=[FakePlatform, BrokenPlatform])
    for key in ("fake", "broken"):
        connect(store, key)
        store.replace_accounts(key, [AdAccount(key, "acct", f"{key} account")])
    return h


@pytest.fixture
def fake(hub):
    return hub.platforms["fake"]


# -- hub ------------------------------------------------------------------------------

class TestHub:
    def test_one_broken_platform_does_not_hide_the_others(self, hub, fake):
        fake.rows = [metric(date.today())]
        rows, errors = hub.metrics(date.today(), date.today())
        assert len(rows) == 1
        assert list(errors) == ["Broken Ads (broken account)"]
        assert "token expired" in errors["Broken Ads (broken account)"]

    def test_metrics_are_cached_until_refresh(self, hub, fake):
        fake.rows = [metric(date.today())]
        hub.metrics(date.today(), date.today())
        hub.metrics(date.today(), date.today())
        assert len([c for c in fake.calls if c[0] == "metrics"]) == 1
        hub.metrics(date.today(), date.today(), refresh=True)
        assert len([c for c in fake.calls if c[0] == "metrics"]) == 2

    def test_disabled_accounts_are_skipped(self, hub, store):
        store.set_account_enabled("broken", "acct", False)
        _, errors = hub.metrics(date.today(), date.today())
        assert errors == {}

    def test_status_change_is_logged(self, hub, fake, store):
        hub.set_campaign_status("fake:acct:c1", PAUSED)
        assert ("status", "c1", PAUSED) in fake.calls
        entry = store.list_activity()[0]
        assert entry["kind"] == "campaign.status" and "Paused “Search — Cards”" in entry["summary"]

    def test_budget_change_respects_editability_and_cap(self, hub, fake):
        with pytest.raises(HubError, match="doesn't have a campaign-level daily budget"):
            hub.set_campaign_budget("fake:acct:c2", 30)
        with pytest.raises(HubError, match="more than 50%"):
            hub.set_campaign_budget("fake:acct:c1", 80, enforce_cap=True)
        hub.set_campaign_budget("fake:acct:c1", 80)  # people may make big moves themselves
        assert ("budget", "c1", 80.0) in fake.calls

    def test_unknown_campaign(self, hub):
        with pytest.raises(HubError):
            hub.set_campaign_status("fake:acct:nope", PAUSED)
        with pytest.raises(HubError):
            hub.set_campaign_status("fake:acct:c1", "DELETED")

    def test_demo_mode_auto_on_off(self, settings, store):
        h = MarketingHub(store, settings, platform_classes=[FakePlatform])
        h.set_demo_setting("auto")
        assert h.demo_active() is True  # nothing connected yet
        connect(store, "fake")
        assert h.demo_active() is False
        h.set_demo_setting("on")
        assert h.demo_active() is True
        with pytest.raises(HubError):
            h.set_demo_setting("sometimes")


class TestDemoData:
    @pytest.fixture
    def demo_hub(self, settings, store):
        from pps_tools.marketing.platforms import default_platform_classes

        h = MarketingHub(store, settings, platform_classes=default_platform_classes())
        h.set_demo_setting("on")
        return h

    def test_numbers_are_stable_between_calls(self, demo_hub):
        start, end = date.today() - timedelta(days=10), date.today() - timedelta(days=1)
        a, _ = demo_hub.metrics(start, end)
        b, _ = demo_hub.metrics(start, end)
        assert [r.to_dict() for r in a] == [r.to_dict() for r in b]
        assert {r.network for r in a} >= {"google", "facebook", "instagram", "pinterest", "x", "linkedin", "tiktok"}

    def test_pausing_in_demo_stops_spend_from_today(self, demo_hub):
        key = "google_ads:4825519306:20481"
        demo_hub.set_campaign_status(key, PAUSED)
        today_rows, _ = demo_hub.metrics(date.today(), date.today())
        assert not [r for r in today_rows if r.campaign_key == key]
        past, _ = demo_hub.metrics(date.today() - timedelta(days=3), date.today() - timedelta(days=1))
        assert [r for r in past if r.campaign_key == key]
        assert demo_hub.find_campaign(key).status == PAUSED

    def test_demo_publishing_is_simulated(self, demo_hub):
        target = demo_hub.targets()[0]
        result = demo_hub.publish_to(target, PostContent(text="hello"))
        assert result.ok and result.url
        assert demo_hub.store.list_activity()[0]["summary"].startswith("[demo]")


# -- rules ----------------------------------------------------------------------------

class TestRules:
    def test_clean_rule_validates(self):
        ok = rules_mod.clean_rule({"name": " CPA guard ", "metric": "cpa", "threshold": "40", "lookback_days": "7"}, ["fake"])
        assert ok["name"] == "CPA guard" and ok["threshold"] == 40.0
        for bad in ({"name": ""}, {"name": "x", "metric": "nope"}, {"name": "x", "lookback_days": 5},
                    {"name": "x", "action": "budget_up", "action_value": 90}, {"name": "x", "platform": "myspace"},
                    {"name": "x", "threshold": "lots"}):
            with pytest.raises(rules_mod.RuleError):
                rules_mod.clean_rule(bad, ["fake"])

    def test_cpa_without_conversions_counts_as_infinite(self):
        assert math.isinf(rules_mod.metric_value(Totals(spend=50), "cpa"))
        assert rules_mod.metric_value(Totals(), "cpa") is None
        assert rules_mod.metric_value(Totals(impressions=1000, clicks=5), "ctr") == pytest.approx(0.5)

    def test_describe(self):
        rule = rules_mod.clean_rule(dict(rules_mod.TEMPLATES[0]), [])
        assert rules_mod.describe(rule) == "If Cost / conversion over the last 7 days is > $60.00, then pause the campaign"

    def _rule(self, store, **kw):
        data = rules_mod.clean_rule({"name": "r", **kw}, ["fake", "broken"])
        data["id"] = store.save_rule(data)
        return data

    def test_dry_run_changes_nothing(self, hub, fake, store):
        fake.rows = [metric(date.today(), conversions=0, spend=120)]
        rule = self._rule(store, metric="cpa", operator=">", threshold=50, lookback_days=7, action="pause", platform="fake")
        outcomes = rules_mod.evaluate(hub, [rule], dry_run=True)
        assert [(o.campaign_key, o.status) for o in outcomes] == [("fake:acct:c1", "would_apply")]
        assert not [c for c in fake.calls if c[0] == "status"]

    def test_pause_applies_once_then_cools_down(self, hub, fake, store):
        fake.rows = [metric(date.today(), conversions=0, spend=120)]
        rule = self._rule(store, metric="cpa", operator=">", threshold=50, lookback_days=7, action="pause", platform="fake")
        first = rules_mod.evaluate(hub, [rule], dry_run=False)
        assert first[0].status == "applied" and ("status", "c1", PAUSED) in fake.calls
        fake.campaigns[0].status = ACTIVE  # someone turned it back on
        hub.store.cache_clear()
        second = rules_mod.evaluate(hub, [rule], dry_run=False)
        assert second[0].status == "cooldown"

    def test_min_spend_guard_and_paused_campaigns_are_ignored(self, hub, fake, store):
        fake.rows = [metric(date.today(), campaign="c1", spend=10, conversions=0),
                     metric(date.today(), campaign="c3", spend=500, conversions=0)]
        rule = self._rule(store, metric="cpa", operator=">", threshold=1, min_spend=50, action="notify")
        assert rules_mod.evaluate(hub, [rule], dry_run=True) == []

    def test_budget_rule_skips_campaigns_without_editable_budget(self, hub, fake, store):
        fake.rows = [metric(date.today(), campaign="c1", conversion_value=900), metric(date.today(), campaign="c2", conversion_value=900)]
        rule = self._rule(store, metric="roas", operator=">", threshold=4, action="budget_up", action_value=20)
        outcomes = {o.campaign_key: o for o in rules_mod.evaluate(hub, [rule], dry_run=False)}
        assert outcomes["fake:acct:c1"].status == "applied"
        assert ("budget", "c1", 60.0) in fake.calls
        assert outcomes["fake:acct:c2"].status == "skipped"

    def test_notify_logs_an_alert(self, hub, fake, store):
        fake.rows = [metric(date.today(), impressions=10000, clicks=10)]
        rule = self._rule(store, metric="ctr", operator="<", threshold=0.5, action="notify", platform="fake")
        outcomes = rules_mod.evaluate(hub, [rule], dry_run=False)
        assert outcomes[0].status == "alerted"
        assert any(a["kind"] == "rule.alert" for a in store.list_activity())
        assert store.get_rule(rule["id"])["last_run_at"]


# -- publisher ---------------------------------------------------------------------------

class TestPublisher:
    def test_x_length_counts_links_and_wide_characters(self):
        assert x_length("hello") == 5
        assert x_length("see https://example.com/a/very/long/path?with=params") == 4 + 23
        assert x_length("🎉") == 2
        assert x_length("名前") == 4

    def test_content_per_network(self):
        post = {"body": "Main text", "link": "https://pps.com/cards", "image_url": None, "title": None,
                "overrides": {"x": "Short for X"}, "utm_campaign": "Fall Sale"}
        x = content_for(post, "x")
        assert x.text.startswith("Short for X") and "utm_source=x" in x.text
        fb = content_for(post, "facebook")
        assert fb.text == "Main text" and "utm_source=facebook&utm_medium=social&utm_campaign=fall-sale" in fb.link
        assert content_for(post, "instagram").link is None  # links aren't clickable there

    def test_problems_per_network(self):
        post = {"body": "x" * 300, "link": "https://pps.com", "image_url": None, "title": None, "overrides": {}}
        ig = problems_for(post, PublishTarget("meta", "instagram", "1", "IG", "instagram_account"))
        assert any("needs an image" in p for p in ig)
        x = problems_for(post, PublishTarget("x", "x", "1", "@me", "profile"))
        assert any("limit is 280" in p for p in x)
        li = problems_for(post, PublishTarget("linkedin", "linkedin", "1", "Org", "organization"))
        assert any("need a title" in p for p in li)
        post["image_url"] = "http://insecure.example.com/a.jpg"
        assert any("https://" in p for p in problems_for(post, PublishTarget("pinterest", "pinterest", "1", "B", "board")))

    @pytest.fixture
    def targets(self, store):
        store.replace_targets("fake", [(PublishTarget("fake", "facebook", "p1", "Page", "page"), None),
                                       (PublishTarget("fake", "x", "u1", "@me", "profile"), None)])
        return ["fake:facebook:p1", "fake:x:u1"]

    def test_publish_records_results_and_partial_status(self, hub, fake, store, targets):
        fake.fail_networks = {"x"}
        pid = store.create_post("Hello", targets, status=st.DRAFT)
        post = publish_post(hub, pid)
        assert post["status"] == st.PARTIAL
        assert post["results"]["fake:facebook:p1"]["ok"] is True
        assert post["results"]["fake:x:u1"]["error"].endswith("rejected")
        # Retrying only re-sends the destination that failed.
        fake.fail_networks = set()
        fake.calls.clear()
        post = publish_post(hub, pid, retry_failed=True)
        assert post["status"] == st.PUBLISHED
        assert [c[1] for c in fake.calls if c[0] == "publish"] == ["x"]

    def test_publish_due_sends_only_due_posts_once(self, hub, fake, store, targets):
        now = datetime.now(timezone.utc)
        due = store.create_post("Due", targets[:1], status=st.SCHEDULED, scheduled_at=st.utc_iso(now - timedelta(minutes=5)))
        store.create_post("Later", targets[:1], status=st.SCHEDULED, scheduled_at=st.utc_iso(now + timedelta(hours=2)))
        assert publish_due(hub) == [due]
        assert publish_due(hub) == []
        assert store.get_post(due)["status"] == st.PUBLISHED

    def test_disconnected_destination_is_reported(self, hub, store):
        pid = store.create_post("Hello", ["fake:facebook:gone"], status=st.DRAFT)
        post = publish_post(hub, pid)
        assert post["status"] == st.FAILED
        assert "no longer connected" in post["results"]["fake:facebook:gone"]["error"]
