"""Unit tests for analytics, UTM links, pacing, OAuth helpers and the store."""

import base64
import hashlib
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from pps_tools.marketing import analytics as an
from pps_tools.marketing.models import AdAccount, MetricRow, PublishTarget, Totals
from pps_tools.marketing.oauth import oauth1_header, pkce_pair
from pps_tools.marketing.pacing import classify, compute_pacing
from pps_tools.marketing.store import DRAFT, PUBLISHING, SCHEDULED, utc_iso
from pps_tools.marketing.utm import UTMError, build_url, slug, tag_for_network


def row(day="2026-10-01", network="google", campaign="c1", **metrics):
    base = dict(impressions=1000, clicks=50, spend=100.0, conversions=5, conversion_value=400.0)
    base.update(metrics)
    return MetricRow(platform="google_ads", network=network, account_id="a1", campaign_id=campaign,
                     campaign_name=campaign.upper(), date=day, **base)


# -- analytics ------------------------------------------------------------------

class TestPeriods:
    today = date(2026, 10, 26)

    def test_last_n_days_end_yesterday(self):
        p = an.resolve_period("7d", today=self.today)
        assert (p.start, p.end, p.days) == (date(2026, 10, 19), date(2026, 10, 25), 7)

    def test_previous_period_is_same_length_and_adjacent(self):
        prev = an.resolve_period("30d", today=self.today).previous()
        assert prev.days == 30 and prev.end == date(2026, 9, 25)

    def test_month_to_date_includes_today(self):
        p = an.resolve_period("mtd", today=self.today)
        assert (p.start, p.end) == (date(2026, 10, 1), self.today)

    def test_last_month(self):
        p = an.resolve_period("last_month", today=date(2026, 3, 15))
        assert (p.start, p.end) == (date(2026, 2, 1), date(2026, 2, 28))

    def test_custom_range_is_ordered_and_capped_at_today(self):
        p = an.resolve_period(None, "2026-11-30", "2026-10-01", today=self.today)
        assert (p.start, p.end, p.preset) == (date(2026, 10, 1), self.today, "custom")

    def test_unknown_preset_falls_back_to_30_days(self):
        assert an.resolve_period("bogus", today=self.today).days == 30


class TestTotals:
    def test_derived_metrics(self):
        t = an.totals([row(), row(day="2026-10-02")])
        assert t.spend == 200 and t.clicks == 100
        assert t.ctr == pytest.approx(0.05)
        assert t.cpc == pytest.approx(2.0)
        assert t.cpa == pytest.approx(20.0)
        assert t.roas == pytest.approx(4.0)
        assert t.cpm == pytest.approx(100.0)

    def test_zero_denominators_are_none(self):
        t = Totals()
        assert (t.ctr, t.cpc, t.cpa, t.roas, t.cpm) == (None, None, None, None, None)

    def test_daily_fills_missing_days_with_zero(self):
        series = an.daily([row(day="2026-10-02", spend=50)], date(2026, 10, 1), date(2026, 10, 3))
        assert series["total"] == [0.0, 50.0, 0.0]

    def test_daily_ratio_metrics_computed_per_day_not_averaged(self):
        rows = [row(day="2026-10-01", spend=100, conversion_value=100), row(day="2026-10-01", spend=100, conversion_value=500)]
        assert an.daily(rows, date(2026, 10, 1), date(2026, 10, 1), "roas")["total"] == [3.0]

    def test_by_network_keeps_fixed_order(self):
        rows = [row(network="tiktok"), row(network="google"), row(network="instagram"), row(network="mystery")]
        assert [k for k, _ in an.by_network(rows)] == ["google", "instagram", "tiktok", "other"]

    def test_change_and_tone(self):
        assert an.change(110, 100) == pytest.approx(0.10)
        assert an.change(5, 0) is None
        assert an.delta_tone("roas", 0.2) == "good"
        assert an.delta_tone("cpa", 0.2) == "bad"
        assert an.delta_tone("cpa", -0.2) == "good"
        assert an.delta_tone("spend", 0.5) == "neutral"


# -- UTM ----------------------------------------------------------------------------

class TestUTM:
    def test_build_keeps_other_params_and_replaces_utms(self):
        url = build_url("https://pps.com/cards?ref=home&utm_source=old", "facebook", "paid_social", "fall-sale")
        assert url == "https://pps.com/cards?ref=home&utm_source=facebook&utm_medium=paid_social&utm_campaign=fall-sale"

    def test_optional_fields_and_fragment(self):
        url = build_url("https://pps.com/#top", "google", "cpc", "brand", term="business cards", content="ad a")
        assert url.endswith("utm_term=business+cards&utm_content=ad+a#top")

    @pytest.mark.parametrize("bad", ["pps.com", "ftp://pps.com", ""])
    def test_rejects_non_web_urls(self, bad):
        with pytest.raises(UTMError):
            build_url(bad, "google", "cpc", "x")

    def test_requires_source_medium_campaign(self):
        with pytest.raises(UTMError):
            build_url("https://pps.com", "", "cpc", "x")

    def test_slug_and_network_tagging(self):
        assert slug("Spring Sale — Business Cards!") == "spring-sale-business-cards"
        tagged = tag_for_network("https://pps.com", "instagram", "Fall Business Cards")
        assert "utm_source=instagram&utm_medium=social&utm_campaign=fall-business-cards" in tagged


# -- pacing --------------------------------------------------------------------------

class TestPacing:
    def test_classification_thresholds(self):
        assert classify(1000, 500, 1000) == "on_track"
        assert classify(1000, 500, 1100) == "over"
        assert classify(1000, 500, 1200) == "way_over"
        assert classify(1000, 500, 700) == "under"
        assert classify(1000, 1200, 900) == "way_over"  # already over budget
        assert classify(1000, 10, None) == "early"

    def test_projection_uses_finished_days_only(self):
        today = date(2026, 10, 11)  # 10 finished days in a 31-day month
        rows = compute_pacing({"google_ads": 3100}, {"google_ads": 1050}, {"google_ads": 1000},
                              {"google_ads": "Google Ads"}, today)
        assert len(rows) == 1
        r = rows[0]
        assert r.projected == pytest.approx(3100)
        assert r.status == "on_track"
        assert r.days_left == 21
        assert r.daily_allowance == pytest.approx((3100 - 1050) / 21)

    def test_total_row_sums_platforms_and_comes_first(self):
        rows = compute_pacing({"meta": 1000, "total": 3000}, {"meta": 100, "google_ads": 200},
                              {"meta": 90, "google_ads": 180}, {"total": "All", "google_ads": "G", "meta": "M"},
                              date(2026, 10, 11))
        assert [r.key for r in rows] == ["total", "meta"]
        assert rows[0].spent == 300


# -- OAuth helpers -------------------------------------------------------------------------

def test_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expected and 43 <= len(verifier) <= 128


def test_oauth1_signature_matches_published_example():
    """The worked example from X's "Creating a signature" documentation."""
    header = oauth1_header(
        "POST",
        "https://api.twitter.com/1.1/statuses/update.json",
        consumer_key="xvz1evFS4wEEPTGEFPHBog",
        consumer_secret="kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
        token="370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
        token_secret="LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
        params={"include_entities": "true"},
        form={"status": "Hello Ladies + Gentlemen, a signed OAuth request!"},
        nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
        timestamp="1318622958",
    )
    assert 'oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"' in header


# -- store ------------------------------------------------------------------------------

class TestStore:
    def test_connection_roundtrip_and_delete_cascades(self, store):
        store.save_connection("meta", {"access_token": "t"}, {"name": "Pat"})
        store.replace_accounts("meta", [AdAccount("meta", "act_1", "Main")])
        assert store.get_connection("meta")["profile"]["name"] == "Pat"
        assert store.connected_platforms() == ["meta"]
        store.delete_connection("meta")
        assert store.get_connection("meta") is None
        assert store.list_accounts("meta") == []

    def test_rediscovery_keeps_users_account_choices(self, store):
        store.replace_accounts("google_ads", [AdAccount("google_ads", "1", "A"), AdAccount("google_ads", "2", "B")])
        store.set_account_enabled("google_ads", "2", False)
        store.replace_accounts("google_ads", [AdAccount("google_ads", "1", "A"), AdAccount("google_ads", "2", "B renamed")])
        accounts = {a.account_id: a for a in store.list_accounts("google_ads")}
        assert accounts["2"].enabled is False and accounts["2"].name == "B renamed"
        assert [a.account_id for a in store.list_accounts(enabled_only=True)] == ["1"]

    def test_target_secrets_are_kept_separately(self, store):
        t = PublishTarget("meta", "facebook", "p1", "Page", "page")
        store.replace_targets("meta", [(t, {"access_token": "page-token"})])
        assert store.target_secret("meta", "facebook", "p1") == {"access_token": "page-token"}
        assert "page-token" not in str(store.list_targets("meta")[0].to_dict())

    def test_oauth_state_is_single_use_and_platform_bound(self, store):
        state = store.create_oauth_state("x", {"verifier": "v"})
        assert store.pop_oauth_state(state, "meta") is None  # wrong platform burns it
        state = store.create_oauth_state("x", {"verifier": "v"})
        assert store.pop_oauth_state(state, "x") == {"verifier": "v"}
        assert store.pop_oauth_state(state, "x") is None

    def test_oauth_state_expires(self, store, monkeypatch):
        state = store.create_oauth_state("x")
        monkeypatch.setattr(time, "time", lambda: 10**12)
        assert store.pop_oauth_state(state, "x") is None

    def test_post_claim_is_atomic(self, store):
        pid = store.create_post("hi", ["meta:facebook:1"], status=SCHEDULED, scheduled_at=utc_iso())
        assert store.claim_post(pid) is True
        assert store.claim_post(pid) is False
        assert store.get_post(pid)["status"] == PUBLISHING

    def test_due_posts_only_includes_past_scheduled(self, store):
        now = datetime.now(timezone.utc)
        due = store.create_post("due", [], status=SCHEDULED, scheduled_at=utc_iso(now - timedelta(minutes=1)))
        store.create_post("later", [], status=SCHEDULED, scheduled_at=utc_iso(now + timedelta(hours=1)))
        store.create_post("draft", [], status=DRAFT)
        assert store.due_post_ids(now) == [due]

    def test_published_posts_cannot_be_deleted(self, store):
        pid = store.create_post("x", [], status=DRAFT)
        store.update_post(pid, status="published")
        assert store.delete_post(pid) is False

    def test_rules_and_fires(self, store):
        rid = store.save_rule({"name": "r", "enabled": True, "metric": "cpa"})
        store.set_rule_enabled(rid, False)
        assert store.get_rule(rid)["enabled"] is False
        assert store.list_rules(enabled_only=True) == []
        store.record_rule_fire(rid, "k", 100.0)
        assert store.last_rule_fire(rid, "k") == 100.0
        store.delete_rule(rid)
        assert store.last_rule_fire(rid, "k") is None

    def test_budgets_set_and_clear(self, store):
        store.set_budget("2026-10", "meta", 500)
        store.set_budget("2026-10", "total", 1000)
        store.set_budget("2026-10", "meta", None)
        assert store.get_budgets("2026-10") == {"total": 1000}

    def test_cache_ttl(self, store, monkeypatch):
        store.cache_set("metrics:x:1", [1, 2])
        assert store.cache_get("metrics:x:1", 60) == [1, 2]
        real = time.time()
        monkeypatch.setattr(time, "time", lambda: real + 120)
        assert store.cache_get("metrics:x:1", 60) is None

    def test_secret_key_is_stable(self, store):
        assert store.secret_key() == store.secret_key()


def test_custom_range_in_the_future_never_runs_backwards():
    p = an.resolve_period(None, "2026-12-01", "2026-12-10", today=date(2026, 10, 26))
    assert p.start <= p.end == date(2026, 10, 26) and p.days == 1
