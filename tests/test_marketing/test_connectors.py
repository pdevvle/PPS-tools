"""Connector tests: each platform's API is mocked with `responses`, so these check
both how requests are built (URLs, auth, bodies) and how answers are parsed."""

import io
import json
import time
import zipfile
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
from responses import matchers

from pps_tools.marketing.http import PlatformAPIError
from pps_tools.marketing.models import ACTIVE, PAUSED, REMOVED, AdAccount, Campaign, PostContent, PublishTarget
from pps_tools.marketing.platforms.google_ads import CAMPAIGNS_QUERY, CLIENTS_QUERY, CUSTOMER_QUERY, GoogleAdsPlatform
from pps_tools.marketing.platforms.linkedin import LinkedInPlatform, escape_commentary
from pps_tools.marketing.platforms.meta import MetaPlatform, conversions_from
from pps_tools.marketing.platforms.microsoft_ads import MicrosoftAdsPlatform, earliest_today, read_report
from pps_tools.marketing.platforms.pinterest import PinterestPlatform
from pps_tools.marketing.platforms.tiktok import TikTokPlatform
from pps_tools.marketing.platforms.x import XPlatform

from .conftest import connect


def query(call) -> dict:
    return {k: v if len(v) > 1 else v[0] for k, v in parse_qs(urlsplit(call.request.url).query).items()}


def form(call) -> dict:
    return {k: v[0] for k, v in parse_qs(call.request.body).items()}


# -- Google Ads -------------------------------------------------------------------

G = "https://googleads.googleapis.com/v26"


@pytest.fixture
def google(settings, store, monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", "secret")
    connect(store, "google_ads", refresh_token="refresh-1")
    return GoogleAdsPlatform(store, settings)


class TestGoogleAds:
    @responses.activate
    def test_discovers_direct_and_manager_client_accounts(self, google):
        responses.get(f"{G}/customers:listAccessibleCustomers",
                      json={"resourceNames": ["customers/1112223333", "customers/9998887777"]})
        responses.post(f"{G}/customers/1112223333/googleAds:search", match=[matchers.json_params_matcher({"query": CUSTOMER_QUERY})],
                       json={"results": [{"customer": {"id": "1112223333", "descriptiveName": "PPS", "currencyCode": "USD",
                                                       "timeZone": "America/Phoenix", "manager": False}}]})
        responses.post(f"{G}/customers/9998887777/googleAds:search", match=[matchers.json_params_matcher({"query": CUSTOMER_QUERY})],
                       json={"results": [{"customer": {"id": "9998887777", "descriptiveName": "Agency MCC", "manager": True}}]})
        responses.post(f"{G}/customers/9998887777/googleAds:search", match=[matchers.json_params_matcher({"query": CLIENTS_QUERY})],
                       json={"results": [{"customerClient": {"id": "5554443333", "descriptiveName": "Client", "currencyCode": "CAD", "manager": False}},
                                         {"customerClient": {"id": "9998887777", "manager": True}}]})
        accounts = {a.account_id: a for a in google.discover_accounts()}
        assert set(accounts) == {"1112223333", "5554443333"}
        assert accounts["5554443333"].currency == "CAD"
        assert accounts["5554443333"].extra["login_customer_id"] == "9998887777"
        child_call = responses.calls[-1]
        assert child_call.request.headers["login-customer-id"] == "9998887777"
        # Developer tokens were retired in September 2026; none is sent.
        assert all("developer-token" not in c.request.headers for c in responses.calls)
        assert all(c.request.headers["Authorization"] == "Bearer token-123" for c in responses.calls)

    @responses.activate
    def test_campaign_budgets_and_shared_budget_protection(self, google):
        responses.post(f"{G}/customers/111/googleAds:search", match=[matchers.json_params_matcher({"query": CAMPAIGNS_QUERY})], json={"results": [
            {"campaign": {"id": "1", "name": "Search", "status": "ENABLED", "advertisingChannelType": "SEARCH"},
             "campaignBudget": {"resourceName": "customers/111/campaignBudgets/9", "amountMicros": "45000000", "period": "DAILY", "referenceCount": "1"}},
            {"campaign": {"id": "2", "name": "Shared", "status": "PAUSED"},
             "campaignBudget": {"resourceName": "customers/111/campaignBudgets/8", "amountMicros": "10000000", "explicitlyShared": True, "referenceCount": "3"}},
        ]})
        c1, c2 = google.list_campaigns(AdAccount("google_ads", "111", "A"))
        assert (c1.status, c1.daily_budget, c1.budget_editable) == (ACTIVE, 45.0, True)
        assert (c2.status, c2.budget_editable) == (PAUSED, False)

    @responses.activate
    def test_metrics_follow_page_tokens_and_convert_micros(self, google):
        page1 = {"results": [{"segments": {"date": "2026-10-01"}, "campaign": {"id": "1", "name": "Search"},
                              "metrics": {"impressions": "1200", "clicks": "85", "costMicros": "41230000", "conversions": 3.0, "conversionsValue": 450.5}}],
                 "nextPageToken": "page-2"}
        page2 = {"results": [{"segments": {"date": "2026-10-02"}, "campaign": {"id": "1", "name": "Search"}, "metrics": {"clicks": "1"}}]}
        responses.post(f"{G}/customers/111/googleAds:search", json=page1)
        responses.post(f"{G}/customers/111/googleAds:search", json=page2)
        rows = google.fetch_metrics(AdAccount("google_ads", "111", "A"), date(2026, 10, 1), date(2026, 10, 2))
        assert [r.date for r in rows] == ["2026-10-01", "2026-10-02"]
        assert rows[0].spend == pytest.approx(41.23) and rows[0].impressions == 1200 and rows[0].conversion_value == 450.5
        assert rows[1].spend == 0 and rows[1].impressions == 0
        assert json.loads(responses.calls[1].request.body)["pageToken"] == "page-2"
        assert "BETWEEN '2026-10-01' AND '2026-10-02'" in json.loads(responses.calls[0].request.body)["query"]

    @responses.activate
    def test_mutations(self, google, store):
        store.replace_accounts("google_ads", [AdAccount("google_ads", "111", "A", extra={"login_customer_id": "999"})])
        responses.post(f"{G}/customers/111/campaigns:mutate", json={"results": [{"resourceName": "customers/111/campaigns/1"}]})
        responses.post(f"{G}/customers/111/campaignBudgets:mutate", json={"results": [{}]})
        campaign = Campaign("google_ads", "111", "1", "Search", ACTIVE, daily_budget=45, budget_editable=True,
                            extra={"budget_resource": "customers/111/campaignBudgets/9"})
        google.set_status(campaign, PAUSED)
        google.set_daily_budget(campaign, 60.504)
        status_body = json.loads(responses.calls[0].request.body)
        assert status_body == {"operations": [{"updateMask": "status", "update": {"resourceName": "customers/111/campaigns/1", "status": "PAUSED"}}]}
        assert responses.calls[0].request.headers["login-customer-id"] == "999"
        budget_body = json.loads(responses.calls[1].request.body)
        assert budget_body["operations"][0] == {"updateMask": "amountMicros",
                                                 "update": {"resourceName": "customers/111/campaignBudgets/9", "amountMicros": "60500000"}}

    @responses.activate
    def test_refreshes_expired_token_first(self, google, store):
        connect(store, "google_ads", refresh_token="refresh-1", expires_at=time.time() - 10)
        responses.post("https://oauth2.googleapis.com/token", json={"access_token": "fresh", "expires_in": 3599})
        responses.get(f"{G}/customers:listAccessibleCustomers", json={"resourceNames": []})
        google.discover_accounts()
        assert form(responses.calls[0]) == {"client_id": "cid", "client_secret": "secret", "refresh_token": "refresh-1", "grant_type": "refresh_token"}
        assert responses.calls[1].request.headers["Authorization"] == "Bearer fresh"
        creds = store.get_connection("google_ads")["credentials"]
        assert creds["access_token"] == "fresh" and creds["refresh_token"] == "refresh-1"

    @responses.activate
    def test_ads_api_errors_are_readable(self, google):
        failure = {"error": {"code": 400, "message": "Request contains an invalid argument.", "status": "INVALID_ARGUMENT",
                             "details": [{"@type": "type.googleapis.com/google.ads.googleads.v26.errors.GoogleAdsFailure",
                                          "errors": [{"errorCode": {"campaignBudgetError": "NON_MULTIPLE_OF_MINIMUM_CURRENCY_UNIT"},
                                                      "message": "Budget must be a multiple of the minimum unit."}]}]}}
        responses.post(f"{G}/customers/111/campaigns:mutate", status=400, json=failure)
        with pytest.raises(PlatformAPIError) as exc:
            google.set_status(Campaign("google_ads", "111", "1", "S", ACTIVE), PAUSED)
        assert "campaignBudgetError: NON_MULTIPLE_OF_MINIMUM_CURRENCY_UNIT" in exc.value.message

    def test_authorization_url_requests_offline_access(self, google):
        url = google.authorization_url()
        q = parse_qs(urlsplit(url).query)
        assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
        assert q["scope"] == ["https://www.googleapis.com/auth/adwords"]
        assert q["redirect_uri"] == ["http://localhost:5050/oauth/google_ads/callback"]


# -- Meta ---------------------------------------------------------------------------

M = "https://graph.facebook.com/v26.0"


@pytest.fixture
def meta(settings, store, monkeypatch):
    monkeypatch.setenv("META_APP_ID", "app")
    monkeypatch.setenv("META_APP_SECRET", "shh")
    connect(store, "meta")
    return MetaPlatform(store, settings)


class TestMeta:
    @responses.activate
    def test_login_swaps_for_a_long_lived_token(self, meta, store):
        store.delete_connection("meta")
        state = store.create_oauth_state("meta")
        responses.get(f"{M}/oauth/access_token", match=[matchers.query_param_matcher(
            {"client_id": "app", "redirect_uri": "http://localhost:5050/oauth/meta/callback", "client_secret": "shh", "code": "abc"})],
            json={"access_token": "short", "expires_in": 3600})
        responses.get(f"{M}/oauth/access_token", match=[matchers.query_param_matcher(
            {"grant_type": "fb_exchange_token", "client_id": "app", "client_secret": "shh", "fb_exchange_token": "short"})],
            json={"access_token": "long", "expires_in": 5183944})
        responses.get(f"{M}/me", json={"id": "42", "name": "Pat"})
        meta.complete_authorization({"code": "abc", "state": state})
        conn = store.get_connection("meta")
        assert conn["credentials"]["access_token"] == "long"
        assert conn["profile"] == {"id": "42", "name": "Pat"}

    def test_bad_state_is_rejected(self, meta):
        with pytest.raises(PlatformAPIError, match="expired"):
            meta.complete_authorization({"code": "abc", "state": "forged"})
        with pytest.raises(PlatformAPIError, match="not granted"):
            meta.complete_authorization({"error": "access_denied", "error_description": "User denied"})

    @responses.activate
    def test_campaign_budgets_in_minor_units(self, meta):
        responses.get(f"{M}/act_1/campaigns", json={"data": [
            {"id": "11", "name": "CBO", "status": "ACTIVE", "effective_status": "ACTIVE", "daily_budget": "2500"},
            {"id": "12", "name": "ABO", "status": "PAUSED", "effective_status": "PAUSED"},
            {"id": "13", "name": "Gone", "status": "ARCHIVED"},
        ]})
        responses.get(f"{M}/act_2/campaigns", json={"data": [{"id": "21", "name": "Yen", "status": "ACTIVE", "daily_budget": "2500"}]})
        usd = meta.list_campaigns(AdAccount("meta", "act_1", "US", currency="USD"))
        assert (usd[0].daily_budget, usd[0].budget_editable) == (25.0, True)
        assert (usd[1].status, usd[1].budget_editable, usd[1].extra["budget_level"]) == (PAUSED, False, "ad_set")
        assert usd[2].status == REMOVED
        jpy = meta.list_campaigns(AdAccount("meta", "act_2", "JP", currency="JPY"))
        assert jpy[0].daily_budget == 2500.0

    def test_conversions_never_double_count_purchase_types(self):
        row = {"actions": [{"action_type": "omni_purchase", "value": "3"},
                           {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "3"},
                           {"action_type": "lead", "value": "2"},
                           {"action_type": "onsite_conversion.lead_grouped", "value": "1"},
                           {"action_type": "link_click", "value": "90"}],
               "action_values": [{"action_type": "omni_purchase", "value": "189.5"},
                                 {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "189.5"}]}
        assert conversions_from(row) == (5.0, 189.5)
        assert conversions_from({"actions": [{"action_type": "purchase", "value": "1"}]}) == (1.0, 0.0)

    @responses.activate
    def test_insights_split_by_placement_and_follow_paging(self, meta):
        next_url = f"{M}/act_1/insights?after=abc"
        responses.get(f"{M}/act_1/insights", match=[matchers.query_param_matcher({"after": "abc"})], json={"data": [
            {"campaign_id": "11", "campaign_name": "CBO", "spend": "5.00", "impressions": "50", "clicks": "1",
             "publisher_platform": "audience_network", "date_start": "2026-10-01"}]})
        responses.get(f"{M}/act_1/insights", json={"data": [
            {"campaign_id": "11", "campaign_name": "CBO", "spend": "41.27", "impressions": "5120", "clicks": "77",
             "actions": [{"action_type": "omni_purchase", "value": "3"}], "action_values": [{"action_type": "omni_purchase", "value": "189.5"}],
             "publisher_platform": "instagram", "date_start": "2026-10-01", "account_currency": "USD"}],
            "paging": {"next": next_url}})
        rows = meta.fetch_metrics(AdAccount("meta", "act_1", "US"), date(2026, 10, 1), date(2026, 10, 1))
        assert [(r.network, r.spend) for r in rows] == [("instagram", 41.27), ("other", 5.0)]
        assert rows[0].conversions == 3 and rows[0].conversion_value == 189.5
        first = query(responses.calls[0])
        assert first["breakdowns"] == "publisher_platform" and first["time_increment"] == "1" and first["level"] == "campaign"
        assert json.loads(first["time_range"]) == {"since": "2026-10-01", "until": "2026-10-01"}

    @responses.activate
    def test_status_and_budget_updates(self, meta):
        responses.post(f"{M}/11", json={"success": True})
        responses.post(f"{M}/11", json={"success": True})
        c = Campaign("meta", "act_1", "11", "CBO", ACTIVE, daily_budget=25, budget_editable=True, currency="USD")
        meta.set_status(c, PAUSED)
        meta.set_daily_budget(c, 30)
        assert form(responses.calls[0]) == {"status": "PAUSED", "access_token": "token-123"}
        assert form(responses.calls[1]) == {"daily_budget": "3000", "access_token": "token-123"}

    @responses.activate
    def test_pages_and_instagram_accounts_become_targets(self, meta, store):
        responses.get(f"{M}/me/accounts", json={"data": [
            {"id": "p1", "name": "PPS", "access_token": "page-token", "tasks": ["CREATE_CONTENT", "MANAGE"],
             "instagram_business_account": {"id": "ig1", "username": "pps"}},
            {"id": "p2", "name": "Read only", "access_token": "t2", "tasks": ["ANALYZE"]}]})
        store.replace_targets("meta", meta.discover_targets())
        targets = {(t.network, t.target_id): t for t in store.list_targets("meta")}
        assert set(targets) == {("facebook", "p1"), ("instagram", "ig1")}
        assert targets[("instagram", "ig1")].name == "@pps"
        assert store.target_secret("meta", "instagram", "ig1") == {"access_token": "page-token"}

    @responses.activate
    def test_publish_link_post_and_instagram_photo(self, meta, store):
        page = PublishTarget("meta", "facebook", "p1", "PPS", "page")
        ig = PublishTarget("meta", "instagram", "ig1", "@pps", "instagram_account")
        store.replace_targets("meta", [(page, {"access_token": "page-token"}), (ig, {"access_token": "page-token"})])
        meta.http.sleep = lambda s: None
        responses.post(f"{M}/p1/feed", json={"id": "p1_77"})
        responses.get(f"{M}/p1_77", json={"permalink_url": "https://www.facebook.com/p1/posts/77"})
        result = meta.publish(page, PostContent(text="Hello", link="https://pps.com"))
        assert result.ok and result.url == "https://www.facebook.com/p1/posts/77"
        assert form(responses.calls[0]) == {"message": "Hello", "link": "https://pps.com", "access_token": "page-token"}

        responses.post(f"{M}/ig1/media", json={"id": "container-1"})
        responses.get(f"{M}/container-1", json={"status_code": "IN_PROGRESS"})
        responses.get(f"{M}/container-1", json={"status_code": "FINISHED"})
        responses.post(f"{M}/ig1/media_publish", json={"id": "media-9"})
        responses.get(f"{M}/media-9", json={"permalink": "https://www.instagram.com/p/abc/"})
        result = meta.publish(ig, PostContent(text="Caption #print", image_url="https://pps.com/a.jpg"))
        assert result.url == "https://www.instagram.com/p/abc/" and result.remote_id == "media-9"
        media_call = next(c for c in responses.calls if c.request.url.startswith(f"{M}/ig1/media") and "publish" not in c.request.url)
        assert form(media_call)["image_url"] == "https://pps.com/a.jpg"
        publish_call = next(c for c in responses.calls if c.request.url.startswith(f"{M}/ig1/media_publish"))
        assert form(publish_call)["creation_id"] == "container-1"

    @responses.activate
    def test_expired_token_message(self, meta):
        responses.get(f"{M}/me/adaccounts", status=400, json={"error": {"message": "Session has expired", "type": "OAuthException", "code": 190, "error_subcode": 463}})
        with pytest.raises(PlatformAPIError, match="reconnect Meta"):
            meta.discover_accounts()


# -- Pinterest ------------------------------------------------------------------------

P = "https://api.pinterest.com/v5"


@pytest.fixture
def pinterest(settings, store, monkeypatch):
    monkeypatch.setenv("PINTEREST_APP_ID", "pid")
    monkeypatch.setenv("PINTEREST_APP_SECRET", "psecret")
    connect(store, "pinterest", refresh_token="pinr-1")
    return PinterestPlatform(store, settings)


class TestPinterest:
    @responses.activate
    def test_refresh_stores_the_new_refresh_token(self, pinterest, store):
        connect(store, "pinterest", refresh_token="pinr-1", expires_at=time.time() - 5)
        responses.post(f"{P}/oauth/token", json={"access_token": "pina-2", "refresh_token": "pinr-2", "expires_in": 2592000,
                                                 "refresh_token_expires_in": 5184000})
        responses.get(f"{P}/ad_accounts", json={"items": [{"id": "549", "name": "PPS", "currency": "USD"}], "bookmark": None})
        accounts = pinterest.discover_accounts()
        assert accounts[0].account_id == "549"
        assert responses.calls[0].request.headers["Authorization"].startswith("Basic ")
        creds = store.get_connection("pinterest")["credentials"]
        assert (creds["access_token"], creds["refresh_token"]) == ("pina-2", "pinr-2")

    @responses.activate
    def test_analytics_request_and_micro_currency(self, pinterest):
        responses.get(f"{P}/ad_accounts/549/campaigns", json={"items": [{"id": "1", "name": "Weddings", "status": "ACTIVE", "daily_spend_cap": 20000000}], "bookmark": None})
        responses.get(f"{P}/ad_accounts/549/campaigns/analytics", json=[
            {"CAMPAIGN_ID": "1", "DATE": "2026-10-20", "SPEND_IN_MICRO_DOLLAR": 12500000, "PAID_IMPRESSION": 4000,
             "CLICKTHROUGH_1": 30, "TOTAL_CONVERSIONS": 2, "TOTAL_CHECKOUT_VALUE_IN_MICRO_DOLLAR": 180000000}])
        start = date.today() - timedelta(days=200)  # clipped to Pinterest's 90-day window
        rows = pinterest.fetch_metrics(AdAccount("pinterest", "549", "PPS"), start, date.today())
        assert rows[0].spend == 12.5 and rows[0].conversion_value == 180.0 and rows[0].campaign_name == "Weddings"
        q = parse_qs(urlsplit(responses.calls[1].request.url).query)
        assert q["campaign_ids"] == ["1"] and q["granularity"] == ["DAY"]
        assert q["start_date"] == [(date.today() - timedelta(days=89)).isoformat()]
        assert "SPEND_IN_MICRO_DOLLAR" in q["columns"][0]

    @responses.activate
    def test_update_reports_item_exceptions(self, pinterest):
        responses.patch(f"{P}/ad_accounts/549/campaigns", json={"items": [{"data": None, "exceptions": [{"code": 2, "message": "Budget too low"}]}]})
        c = Campaign("pinterest", "549", "1", "W", ACTIVE, daily_budget=20, budget_editable=True)
        with pytest.raises(PlatformAPIError, match="Budget too low"):
            pinterest.set_daily_budget(c, 1)
        assert json.loads(responses.calls[0].request.body) == [{"id": "1", "daily_spend_cap": 1000000}]

    @responses.activate
    def test_publish_pin(self, pinterest):
        responses.post(f"{P}/pins", json={"id": "987"}, status=201)
        board = PublishTarget("pinterest", "pinterest", "b1", "Ideas", "board")
        result = pinterest.publish(board, PostContent(text="Desc", link="https://pps.com", image_url="https://pps.com/p.jpg", title="Title"))
        assert result.url == "https://www.pinterest.com/pin/987/"
        assert json.loads(responses.calls[0].request.body) == {
            "board_id": "b1", "description": "Desc", "title": "Title", "link": "https://pps.com",
            "media_source": {"source_type": "image_url", "url": "https://pps.com/p.jpg"}}


# -- X ----------------------------------------------------------------------------------

X_API = "https://api.x.com/2"
ADS = "https://ads-api.x.com/12"


@pytest.fixture
def x(settings, store, monkeypatch):
    monkeypatch.setenv("X_CLIENT_ID", "xid")
    monkeypatch.setenv("X_CLIENT_SECRET", "xsecret")
    for name in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"):
        monkeypatch.setenv(name, name.lower())
    store.save_connection("x", {"mode": "oauth2", "access_token": "x-token", "refresh_token": "xr", "expires_at": time.time() + 3600},
                          profile={"id": "77", "username": "PriorityPrint"})
    return XPlatform(store, settings)


class TestX:
    @responses.activate
    def test_oauth2_exchange_sends_pkce_verifier(self, x, store):
        url = x.authorization_url()
        q = parse_qs(urlsplit(url).query)
        assert q["code_challenge_method"] == ["S256"] and "offline.access" in q["scope"][0]
        responses.post("https://api.x.com/2/oauth2/token", json={"access_token": "new", "refresh_token": "r2", "expires_in": 7200})
        responses.get(f"{X_API}/users/me", json={"data": {"id": "77", "username": "PriorityPrint"}})
        x.complete_authorization({"code": "c", "state": q["state"][0]})
        sent = form(responses.calls[0])
        assert sent["grant_type"] == "authorization_code" and len(sent["code_verifier"]) >= 43
        assert store.get_connection("x")["credentials"]["mode"] == "oauth2"

    @responses.activate
    def test_post_with_image(self, x):
        responses.get("https://pps.com/card.jpg", body=b"\xff\xd8jpeg", content_type="image/jpeg")
        responses.post(f"{X_API}/media/upload", json={"data": {"id": "m-1", "media_key": "3_1"}})
        responses.post(f"{X_API}/tweets", json={"data": {"id": "1850", "text": "Hi"}}, status=201)
        target = PublishTarget("x", "x", "77", "@PriorityPrint", "profile")
        result = x.publish(target, PostContent(text="Hi", image_url="https://pps.com/card.jpg"))
        assert result.url == "https://x.com/PriorityPrint/status/1850"
        upload = responses.calls[1].request
        assert upload.headers["Authorization"] == "Bearer x-token" and b"tweet_image" in upload.body
        assert json.loads(responses.calls[2].request.body) == {"text": "Hi", "media": {"media_ids": ["m-1"]}}

    @responses.activate
    def test_ads_stats_parse_daily_arrays_in_account_time_zone(self, x):
        responses.get(f"{ADS}/accounts/acc1/campaigns", json={"data": [
            {"id": "c1", "name": "Deals", "entity_status": "ACTIVE", "daily_budget_amount_local_micro": 15000000, "currency": "USD"}]})
        responses.get(f"{ADS}/stats/accounts/acc1", json={"data": [{"id": "c1", "id_data": [{"segment": None, "metrics": {
            "impressions": [1000, 0], "clicks": [20, None], "billed_charge_local_micro": [5500000, None],
            "conversion_purchases": {"metric": [2, None], "sale_amount": [80000000, None]}}}]}]})
        acct = AdAccount("x", "acc1", "@pps", timezone="America/Los_Angeles")
        rows = x.fetch_metrics(acct, date(2026, 10, 19), date(2026, 10, 20))
        assert len(rows) == 1  # the empty second day is dropped
        r = rows[0]
        assert (r.date, r.impressions, r.clicks, r.spend, r.conversions, r.conversion_value) == ("2026-10-19", 1000, 20, 5.5, 2.0, 80.0)
        q = query(responses.calls[1])
        assert q["start_time"] == "2026-10-19T00:00:00-07:00" and q["end_time"] == "2026-10-21T00:00:00-07:00"
        assert q["granularity"] == "DAY" and q["entity"] == "CAMPAIGN"
        assert responses.calls[1].request.headers["Authorization"].startswith("OAuth ")

    @responses.activate
    def test_status_change_is_signed_put(self, x):
        responses.put(f"{ADS}/accounts/acc1/campaigns/c1", json={"data": {"id": "c1"}})
        x.set_status(Campaign("x", "acc1", "c1", "Deals", ACTIVE), PAUSED)
        call = responses.calls[0]
        assert query(call) == {"entity_status": "PAUSED"}
        assert 'oauth_consumer_key="x_api_key"' in call.request.headers["Authorization"]

    def test_ads_need_api_keys(self, x, monkeypatch):
        monkeypatch.delenv("X_API_KEY")
        assert x.discover_accounts() == []
        assert x.configured  # OAuth 2.0 is still set up for posting


# -- LinkedIn ------------------------------------------------------------------------------

LI = "https://api.linkedin.com/rest"


@pytest.fixture
def linkedin(settings, store, monkeypatch):
    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "lid")
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "lsecret")
    connect(store, "linkedin")
    return LinkedInPlatform(store, settings)


class TestLinkedIn:
    def test_commentary_escaping_keeps_hashtags(self):
        assert escape_commentary("Save 20% (today) #printing @pps # done") == "Save 20% \\(today\\) #printing \\@pps \\# done"

    @responses.activate
    def test_analytics_query_uses_restli_syntax(self, linkedin):
        responses.get(f"{LI}/adAccounts/123/adCampaigns", json={"elements": [{"id": 9, "name": "B2B", "status": "ACTIVE",
                                                                            "dailyBudget": {"amount": "18", "currencyCode": "USD"}}]})
        responses.get(f"{LI}/adAnalytics", json={"elements": [{
            "pivotValues": ["urn:li:sponsoredCampaign:9"], "dateRange": {"start": {"year": 2026, "month": 10, "day": 2}, "end": {"year": 2026, "month": 10, "day": 2}},
            "impressions": 165, "clicks": 11, "costInLocalCurrency": "19.91833", "externalWebsiteConversions": 1, "conversionValueInLocalCurrency": "250"}]})
        rows = linkedin.fetch_metrics(AdAccount("linkedin", "123", "PPS"), date(2026, 10, 1), date(2026, 10, 3))
        assert (rows[0].campaign_name, rows[0].date, rows[0].spend, rows[0].conversion_value) == ("B2B", "2026-10-02", pytest.approx(19.91833), 250.0)
        url = responses.calls[1].request.url
        assert "dateRange=(start:(year:2026,month:10,day:1),end:(year:2026,month:10,day:3))" in url
        assert "accounts=List(urn%3Ali%3AsponsoredAccount%3A123)" in url
        headers = responses.calls[1].request.headers
        assert headers["LinkedIn-Version"] == "202610" and headers["X-Restli-Protocol-Version"] == "2.0.0"

    @responses.activate
    def test_partial_update(self, linkedin):
        responses.post(f"{LI}/adAccounts/123/adCampaigns/9", status=204)
        linkedin.set_daily_budget(Campaign("linkedin", "123", "9", "B2B", ACTIVE, currency="USD"), 30)
        call = responses.calls[0]
        assert call.request.headers["X-RestLi-Method"] == "PARTIAL_UPDATE"
        assert json.loads(call.request.body) == {"patch": {"$set": {"dailyBudget": {"amount": "30.00", "currencyCode": "USD"}}}}

    @responses.activate
    def test_organization_post_with_link(self, linkedin):
        responses.post(f"{LI}/posts", status=201, headers={"x-restli-id": "urn:li:share:123"})
        org = PublishTarget("linkedin", "linkedin", "555", "PPS", "organization")
        result = linkedin.publish(org, PostContent(text="Hello (B2B)", link="https://pps.com", title="Corporate printing"))
        assert result.url == "https://www.linkedin.com/feed/update/urn:li:share:123/"
        body = json.loads(responses.calls[0].request.body)
        assert body["author"] == "urn:li:organization:555" and body["commentary"] == "Hello \\(B2B\\)"
        assert body["content"] == {"article": {"source": "https://pps.com", "title": "Corporate printing"}}
        assert body["lifecycleState"] == "PUBLISHED"

    @responses.activate
    def test_image_post_uploads_first(self, linkedin):
        responses.get("https://pps.com/a.png", body=b"png", content_type="image/png")
        responses.post(f"{LI}/images", json={"value": {"uploadUrl": "https://www.linkedin.com/dms-uploads/x", "image": "urn:li:image:C4E"}})
        responses.put("https://www.linkedin.com/dms-uploads/x", status=201)
        responses.post(f"{LI}/posts", status=201, headers={"x-restli-id": "urn:li:share:9"})
        linkedin.publish(PublishTarget("linkedin", "linkedin", "555", "PPS", "organization"),
                         PostContent(text="Look", image_url="https://pps.com/a.png"))
        init = json.loads(responses.calls[1].request.body)
        assert init == {"initializeUploadRequest": {"owner": "urn:li:organization:555"}}
        assert responses.calls[2].request.body == b"png"
        assert json.loads(responses.calls[3].request.body)["content"] == {"media": {"id": "urn:li:image:C4E"}}


# -- TikTok ---------------------------------------------------------------------------------

T = "https://business-api.tiktok.com/open_api/v1.3"


@pytest.fixture
def tiktok(settings, store, monkeypatch):
    monkeypatch.setenv("TIKTOK_APP_ID", "tid")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "tsecret")
    connect(store, "tiktok", advertiser_ids=["700"])
    return TikTokPlatform(store, settings)


class TestTikTok:
    @responses.activate
    def test_error_codes_raise_even_on_http_200(self, tiktok):
        responses.get(f"{T}/advertiser/info/", json={"code": 40105, "message": "Access token is invalid", "request_id": "r"})
        with pytest.raises(PlatformAPIError, match="reconnect TikTok"):
            tiktok.discover_accounts()

    @responses.activate
    def test_reports_are_chunked_to_30_days(self, tiktok):
        payload = {"code": 0, "message": "OK", "data": {"list": [{"dimensions": {"campaign_id": "1", "stat_time_day": "2026-10-01 00:00:00"},
                   "metrics": {"campaign_name": "Spark", "spend": "14.68", "impressions": "1079", "clicks": "12", "conversion": "2",
                               "total_complete_payment_rate": "55.5"}}], "page_info": {"page": 1, "total_page": 1}}}
        responses.get(f"{T}/report/integrated/get/", json=payload)
        responses.get(f"{T}/report/integrated/get/", json={"code": 0, "data": {"list": [], "page_info": {"page": 1, "total_page": 1}}})
        rows = tiktok.fetch_metrics(AdAccount("tiktok", "700", "PPS"), date(2026, 9, 1), date(2026, 10, 15))
        assert len(responses.calls) == 2
        first, second = query(responses.calls[0]), query(responses.calls[1])
        assert (first["start_date"], first["end_date"]) == ("2026-09-01", "2026-09-30")
        assert (second["start_date"], second["end_date"]) == ("2026-10-01", "2026-10-15")
        assert json.loads(first["dimensions"]) == ["campaign_id", "stat_time_day"]
        assert responses.calls[0].request.headers["Access-Token"] == "token-123"
        r = rows[0]
        assert (r.date, r.spend, r.impressions, r.conversions, r.conversion_value) == ("2026-10-01", 14.68, 1079, 2.0, 55.5)

    @responses.activate
    def test_campaign_budget_modes_and_updates(self, tiktok):
        responses.get(f"{T}/campaign/get/", json={"code": 0, "data": {"list": [
            {"campaign_id": "1", "campaign_name": "Daily", "operation_status": "ENABLE", "budget_mode": "BUDGET_MODE_DAY", "budget": 50.0},
            {"campaign_id": "2", "campaign_name": "Total", "operation_status": "DISABLE", "budget_mode": "BUDGET_MODE_TOTAL", "budget": 900.0}],
            "page_info": {"page": 1, "total_page": 1}}})
        responses.post(f"{T}/campaign/status/update/", json={"code": 0, "data": {}})
        daily, total = tiktok.list_campaigns(AdAccount("tiktok", "700", "PPS"))
        assert (daily.status, daily.daily_budget, daily.budget_editable) == (ACTIVE, 50.0, True)
        assert (total.status, total.lifetime_budget, total.budget_editable) == (PAUSED, 900.0, False)
        tiktok.set_status(daily, PAUSED)
        assert json.loads(responses.calls[1].request.body) == {"advertiser_id": "700", "campaign_ids": ["1"], "operation_status": "DISABLE"}


# -- Microsoft Advertising ----------------------------------------------------------------

MS_LOGIN = "https://login.microsoftonline.com/common/oauth2/v2.0"
MS_CUSTOMER = "https://clientcenter.api.bingads.microsoft.com/CustomerManagement/v13"
MS_CAMPAIGN = "https://campaign.api.bingads.microsoft.com/CampaignManagement/v13"
MS_REPORTING = "https://reporting.api.bingads.microsoft.com/Reporting/v13"
MS_DOWNLOAD = "https://bingadsappsstorageprod.blob.core.windows.net/download/report.zip?sig=abc"
MS_ACCOUNT = AdAccount("microsoft_ads", "180436527", "PPS", extra={"customer_id": "254321", "time_zone": "Arizona"})


def zipped_csv(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("180436527_report.csv", "﻿" + text)
    return buf.getvalue()


@pytest.fixture
def microsoft(settings, store, monkeypatch):
    monkeypatch.setenv("MICROSOFT_ADS_CLIENT_ID", "ms-client")
    monkeypatch.setenv("MICROSOFT_ADS_CLIENT_SECRET", "ms-secret")
    monkeypatch.setenv("MICROSOFT_ADS_DEVELOPER_TOKEN", "dev-token")
    connect(store, "microsoft_ads", refresh_token="ms-refresh")
    platform = MicrosoftAdsPlatform(store, settings)
    platform.http.sleep = lambda seconds: None
    return platform


class TestMicrosoftAds:
    @responses.activate
    def test_sign_in_uses_pkce_and_saves_the_user(self, microsoft, store):
        url = microsoft.authorization_url()
        assert url.startswith(f"{MS_LOGIN}/authorize?")
        q = parse_qs(urlsplit(url).query)
        assert q["scope"] == ["https://ads.microsoft.com/msads.manage offline_access"]
        assert q["code_challenge_method"] == ["S256"] and q["response_mode"] == ["query"]
        assert q["redirect_uri"] == ["http://localhost:5050/oauth/microsoft_ads/callback"]
        responses.post(f"{MS_LOGIN}/token", json={"token_type": "Bearer", "expires_in": 3600, "access_token": "ms-new",
                                                  "refresh_token": "ms-r2", "scope": "https://ads.microsoft.com/msads.manage"})
        responses.post(f"{MS_CUSTOMER}/User/Query", match=[matchers.json_params_matcher({"UserId": None})],
                       json={"User": {"Id": "9001", "UserName": "owner@pps.com", "Name": {"FirstName": "Pat", "LastName": "Printer"}},
                             "CustomerRoles": [{"RoleId": 41, "CustomerId": "254321"}]})
        microsoft.complete_authorization({"code": "auth-code", "state": q["state"][0]})
        sent = form(responses.calls[0])
        assert sent["grant_type"] == "authorization_code" and sent["client_secret"] == "ms-secret"
        assert sent["scope"] == "https://ads.microsoft.com/msads.manage offline_access" and len(sent["code_verifier"]) >= 43
        headers = responses.calls[1].request.headers
        assert headers["Authorization"] == "Bearer ms-new" and headers["DeveloperToken"] == "dev-token"
        assert "CustomerAccountId" not in headers
        conn = store.get_connection("microsoft_ads")
        assert conn["credentials"]["refresh_token"] == "ms-r2"
        assert conn["profile"] == {"user_id": "9001", "name": "Pat Printer"}

    @responses.activate
    def test_refresh_keeps_the_newest_refresh_token(self, microsoft, store):
        connect(store, "microsoft_ads", refresh_token="ms-refresh", expires_at=time.time() - 10)
        responses.post(f"{MS_LOGIN}/token", json={"access_token": "fresh", "refresh_token": "ms-refresh-2", "expires_in": 3600})
        assert microsoft.access_token() == "fresh"
        assert form(responses.calls[0])["grant_type"] == "refresh_token"
        assert store.get_connection("microsoft_ads")["credentials"]["refresh_token"] == "ms-refresh-2"

    @responses.activate
    def test_discovers_accounts_with_their_customer(self, microsoft):
        responses.post(f"{MS_CUSTOMER}/User/Query", json={"User": {"Id": "9001"}})
        responses.post(f"{MS_CUSTOMER}/Accounts/Search", json={"Accounts": [
            {"Id": "180436527", "Name": "Priority Print Service", "Number": "F149A2B7", "ParentCustomerId": "254321",
             "CurrencyCode": "USD", "TimeZone": "Arizona", "AccountLifeCycleStatus": "Active"},
            {"Id": "180436528", "Name": "Old shop", "ParentCustomerId": "254321", "CurrencyCode": "CAD",
             "AccountLifeCycleStatus": "Inactive"}]})
        accounts = {a.account_id: a for a in microsoft.discover_accounts()}
        body = json.loads(responses.calls[1].request.body)
        assert body == {"Predicates": [{"Field": "UserId", "Operator": "Equals", "Value": "9001"}], "PageInfo": {"Index": 0, "Size": 1000}}
        live, closed = accounts["180436527"], accounts["180436528"]
        assert (live.name, live.currency, live.enabled, live.extra["customer_id"]) == ("Priority Print Service", "USD", True, "254321")
        assert (closed.currency, closed.enabled) == ("CAD", False)

    @responses.activate
    def test_campaign_budgets_statuses_and_types(self, microsoft):
        responses.post(f"{MS_CAMPAIGN}/Campaigns/QueryByAccountId", json={"Campaigns": [
            {"Id": "1", "Name": "Search — Cards", "Status": "Active", "DailyBudget": 25.0, "BudgetType": "DailyBudgetStandard",
             "BudgetId": None, "CampaignType": "Search"},
            {"Id": "2", "Name": "Shared", "Status": "Paused", "DailyBudget": 40.0, "BudgetType": "DailyBudgetStandard",
             "BudgetId": "777", "CampaignType": "Search"},
            {"Id": "3", "Name": "PMax", "Status": "BudgetPaused", "DailyBudget": 30.0, "BudgetType": "DailyBudgetStandard",
             "CampaignType": "PerformanceMax"},
            {"Id": "4", "Name": "Audience", "Status": "BudgetAndManualPaused", "DailyBudget": 900.0,
             "BudgetType": "LifetimeBudgetStandard", "CampaignType": "Audience"},
            {"Id": "5", "Name": "Experiment", "Status": "Active", "DailyBudget": 25.0, "BudgetType": "DailyBudgetStandard",
             "ExperimentId": "55", "CampaignType": "Search"}]})
        search, shared, pmax, audience, experiment = microsoft.list_campaigns(MS_ACCOUNT)
        call = responses.calls[0].request
        assert json.loads(call.body) == {"AccountId": "180436527", "CampaignType": "Search, Shopping, Audience, PerformanceMax"}
        assert (call.headers["CustomerId"], call.headers["CustomerAccountId"]) == ("254321", "180436527")
        assert (search.status, search.daily_budget, search.budget_editable, search.objective) == (ACTIVE, 25.0, True, "SEARCH")
        assert (shared.status, shared.budget_editable, shared.extra["shared_budget"]) == (PAUSED, False, True)
        assert (pmax.status, pmax.raw_status, pmax.objective) == ("OTHER", "BudgetPaused", "PERFORMANCE_MAX")
        assert (audience.status, audience.daily_budget, audience.lifetime_budget, audience.budget_editable) == (PAUSED, None, 900.0, False)
        assert experiment.budget_editable is False

    @responses.activate
    def test_updates_are_puts_and_partial_errors_raise(self, microsoft, store):
        store.replace_accounts("microsoft_ads", [MS_ACCOUNT])
        responses.put(f"{MS_CAMPAIGN}/Campaigns", json={"PartialErrors": []})
        responses.put(f"{MS_CAMPAIGN}/Campaigns", json={"PartialErrors": [
            {"Code": 1100, "ErrorCode": "CampaignServiceInvalidBudgetAmount", "Index": 0, "Message": "The budget amount is not valid."}]})
        campaign = Campaign("microsoft_ads", "180436527", "1", "Search", ACTIVE, daily_budget=25, budget_editable=True)
        microsoft.set_status(campaign, PAUSED)
        call = responses.calls[0].request
        assert json.loads(call.body) == {"AccountId": "180436527", "Campaigns": [{"Id": "1", "Status": "Paused"}]}
        assert call.headers["CustomerId"] == "254321"  # looked up from the stored account
        with pytest.raises(PlatformAPIError, match=r"budget amount is not valid. \[CampaignServiceInvalidBudgetAmount\]"):
            microsoft.set_daily_budget(campaign, 30.456)
        assert json.loads(responses.calls[1].request.body)["Campaigns"] == [{"Id": "1", "DailyBudget": 30.46}]
        shared = Campaign("microsoft_ads", "180436527", "2", "Shared", ACTIVE, extra={"shared_budget": True})
        with pytest.raises(PlatformAPIError, match="shared budget"):
            microsoft.set_daily_budget(shared, 50)
        assert len(responses.calls) == 2

    @responses.activate
    def test_report_is_submitted_polled_downloaded_and_parsed(self, microsoft):
        csv_text = ('"TimePeriod","AccountId","CampaignId","CampaignName","Impressions","Clicks","Spend",'
                    '"ConversionsQualified","Revenue","CurrencyCode"\n'
                    '"2026-10-01","180436527","1","Search — Cards","1,204","71","118.42","5.50","1,240.00","USD"\n'
                    '"2026-10-02","180436527","1","Search — Cards","988","64","101.07","4","880.00","USD"\n')
        responses.post(f"{MS_REPORTING}/GenerateReport/Submit", json={"ReportRequestId": "30000001234_567"})
        responses.post(f"{MS_REPORTING}/GenerateReport/Poll", json={"ReportRequestStatus": {"Status": "Pending", "ReportDownloadUrl": None}})
        responses.post(f"{MS_REPORTING}/GenerateReport/Poll", json={"ReportRequestStatus": {"Status": "Success", "ReportDownloadUrl": MS_DOWNLOAD}})
        responses.get(MS_DOWNLOAD, body=zipped_csv(csv_text), content_type="application/zip")
        account = AdAccount("microsoft_ads", "180436527", "PPS", extra={"customer_id": "254321", "time_zone": "IslamabadKarachiTashkent"})
        rows = microsoft.fetch_metrics(account, date(2026, 10, 1), date(2026, 10, 2))
        request = json.loads(responses.calls[0].request.body)["ReportRequest"]
        assert request["Type"] == "CampaignPerformanceReportRequest" and request["Aggregation"] == "Daily"
        assert (request["Format"], request["FormatVersion"], request["ExcludeReportHeader"]) == ("Csv", "2.0", True)
        assert "ConversionsQualified" in request["Columns"] and request["Scope"] == {"AccountIds": ["180436527"]}
        assert request["Time"] == {"CustomDateRangeStart": {"Day": 1, "Month": 10, "Year": 2026},
                                   "CustomDateRangeEnd": {"Day": 2, "Month": 10, "Year": 2026},
                                   "ReportTimeZone": "IslandamabadKarachiTashkent"}  # the report list's spelling
        assert json.loads(responses.calls[1].request.body) == {"ReportRequestId": "30000001234_567"}
        assert "Authorization" not in responses.calls[3].request.headers  # the download link is pre-signed
        first = rows[0]
        assert (first.date, first.impressions, first.clicks, first.spend) == ("2026-10-01", 1204, 71, 118.42)
        assert (first.conversions, first.conversion_value, first.network, first.currency) == (5.5, 1240.0, "microsoft", "USD")
        assert rows[1].conversions == 4.0 and len(rows) == 2

    @responses.activate
    def test_report_without_data_and_failed_reports(self, microsoft):
        responses.post(f"{MS_REPORTING}/GenerateReport/Submit", json={"ReportRequestId": "r1"})
        responses.post(f"{MS_REPORTING}/GenerateReport/Poll", json={"ReportRequestStatus": {"Status": "Success", "ReportDownloadUrl": None}})
        assert microsoft.fetch_metrics(MS_ACCOUNT, date(2026, 10, 1), date(2026, 10, 2)) == []
        responses.post(f"{MS_REPORTING}/GenerateReport/Poll", json={"ReportRequestStatus": {"Status": "Error"}})
        with pytest.raises(PlatformAPIError, match="couldn't build"):
            microsoft.fetch_metrics(MS_ACCOUNT, date(2026, 10, 1), date(2026, 10, 2))

    @responses.activate
    def test_report_gives_up_after_waiting(self, microsoft):
        responses.post(f"{MS_REPORTING}/GenerateReport/Submit", json={"ReportRequestId": "r1"})
        responses.post(f"{MS_REPORTING}/GenerateReport/Poll", json={"ReportRequestStatus": {"Status": "Pending"}})
        with pytest.raises(PlatformAPIError, match="longer than usual"):
            microsoft.fetch_metrics(MS_ACCOUNT, date(2026, 10, 1), date(2026, 10, 2))

    @responses.activate
    def test_report_never_asks_for_days_that_have_not_started(self, microsoft):
        responses.post(f"{MS_REPORTING}/GenerateReport/Submit", json={"ReportRequestId": "r1"})
        responses.post(f"{MS_REPORTING}/GenerateReport/Poll", json={"ReportRequestStatus": {"Status": "Success"}})
        microsoft.fetch_metrics(MS_ACCOUNT, earliest_today() - timedelta(days=3), earliest_today() + timedelta(days=1))
        end = json.loads(responses.calls[0].request.body)["ReportRequest"]["Time"]["CustomDateRangeEnd"]
        assert date(end["Year"], end["Month"], end["Day"]) == earliest_today()
        tomorrow = earliest_today() + timedelta(days=1)
        assert microsoft.fetch_metrics(MS_ACCOUNT, tomorrow, tomorrow) == [] and len(responses.calls) == 2

    def test_read_report_accepts_plain_csv_and_empty_zips(self):
        assert read_report(b'"TimePeriod","Spend"\n"2026-10-01","3.50"\n') == [{"TimePeriod": "2026-10-01", "Spend": "3.50"}]
        buf = io.BytesIO()
        zipfile.ZipFile(buf, "w").close()
        assert read_report(buf.getvalue()) == []

    @responses.activate
    def test_errors_are_readable(self, microsoft):
        responses.post(f"{MS_CAMPAIGN}/Campaigns/QueryByAccountId", status=401, json={
            "TrackingId": "t", "Type": "AdApiFaultDetail",
            "Errors": [{"Code": 109, "Detail": None, "ErrorCode": "AuthenticationTokenExpired",
                        "Message": "Authentication token expired. Please renew it or obtain a new token."}]})
        with pytest.raises(PlatformAPIError) as exc:
            microsoft.list_campaigns(MS_ACCOUNT)
        assert exc.value.message.startswith("Authentication token expired. Please renew it or obtain a new token. [AuthenticationTokenExpired]")
        responses.post(f"{MS_CUSTOMER}/User/Query", json={"User": {"Id": "9001"}})
        responses.post(f"{MS_CUSTOMER}/Accounts/Search", status=400, json={"ApplicationFault": {
            "Type": "ApiFault", "OperationErrors": [{"Code": 106, "Details": None, "Message": "The user is not authorized to perform this action."}]}})
        with pytest.raises(PlatformAPIError, match="not authorized to perform this action"):
            microsoft.discover_accounts()
        responses.post(f"{MS_LOGIN}/token", status=400, json={
            "error": "invalid_grant", "error_description": "AADSTS70000: The provided grant has expired.\r\nTrace ID: 1\r\nCorrelation ID: 2"})
        with pytest.raises(PlatformAPIError) as exc:
            microsoft.refresh_tokens({"refresh_token": "old"})
        assert exc.value.message == "AADSTS70000: The provided grant has expired. (HTTP 400)"
