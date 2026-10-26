"""Web app tests (demo mode, so no platform is contacted)."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from pps_tools.marketing.app import compact, create_app, money, objective_text, safe_next, safe_url
from pps_tools.marketing.config import MarketingSettings
from pps_tools.marketing.copywriter import Copywriter
from pps_tools.marketing.insights import Analyst

from .test_ai import GOOD_RSA, StubClient

PAGES = ["/", "/?range=7d", "/?range=mtd", "/?range=last_month", "/campaigns", "/publish", "/publish?tab=calendar",
         "/publish?tab=history", "/studio", "/insights", "/automation", "/automation?template=0", "/budgets", "/utm",
         "/connections", "/activity"]


@pytest.fixture
def app(tmp_path):
    settings = MarketingSettings(db_path=tmp_path / "m.db", demo="on")
    copy_stub = StubClient({"strategy": "Speed sells.", "formats": {"google_rsa": [GOOD_RSA]}})
    analyst_stub = StubClient({"headline": "Search carries the month", "summary": "s", "wins": [], "concerns": [],
                               "recommendations": [{"title": "Pause it", "detail": "d", "priority": "high", "platform": "google_ads",
                                                    "campaign_key": "google_ads:4825519306:20481", "action": "pause",
                                                    "change_pct": 0, "expected_impact": "x"}],
                               "budget_shifts": [], "watch_next": []})
    application = create_app(
        settings,
        copywriter=Copywriter(settings.brand_context, client=copy_stub),
        analyst=Analyst(settings.brand_context, client=analyst_stub),
    )
    application.config["TESTING"] = True
    application.extensions["stubs"] = (copy_stub, analyst_stub)
    return application


@pytest.fixture
def client(app):
    c = app.test_client()
    c.get("/")  # starts the session and its CSRF token
    return c


def token(client):
    with client.session_transaction() as sess:
        return sess["csrf_token"]


def post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json", headers={"X-CSRF-Token": token(client)})


def post_form(client, url, data, **kw):
    data = dict(data, csrf_token=token(client))
    return client.post(url, data=data, **kw)


@pytest.mark.parametrize("path", PAGES)
def test_every_page_renders(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, path
    assert b"Demo mode" in resp.data or path == "/connections"


def test_missing_pages_and_health(client):
    assert client.get("/nope").status_code == 404
    assert client.get("/healthz").get_json() == {"ok": True}


def test_posts_without_csrf_token_are_refused(client):
    resp = client.post("/api/campaigns/status", data="{}", content_type="application/json")
    assert resp.status_code == 400 and "session expired" in resp.get_json()["error"]
    assert client.post("/budgets", data={"budget_total": "10"}).status_code == 400


def test_password_protection(tmp_path):
    app = create_app(MarketingSettings(db_path=tmp_path / "m.db", demo="on", app_password="hunter2"))
    c = app.test_client()
    assert c.get("/").status_code == 302
    assert c.post("/api/campaigns/status", json={}).status_code == 401
    c.get("/login")
    with c.session_transaction() as sess:
        csrf = sess["csrf_token"]
    assert b"Wrong password" in c.post("/login", data={"password": "nope", "csrf_token": csrf}, follow_redirects=True).data
    resp = c.post("/login?next=//evil.example.com", data={"password": "hunter2", "csrf_token": csrf})
    assert resp.status_code == 302 and resp.headers["Location"] == "/"
    assert c.get("/").status_code == 200


def test_campaign_actions(client):
    resp = post_json(client, "/api/campaigns/status", {"key": "google_ads:4825519306:20481", "status": "PAUSED"})
    assert resp.get_json()["status"] == "PAUSED"
    resp = post_json(client, "/api/campaigns/budget", {"key": "google_ads:4825519306:20482", "amount": "55.5"})
    assert resp.get_json()["daily_budget"] == 55.5
    assert post_json(client, "/api/campaigns/budget", {"key": "google_ads:4825519306:20482", "amount": "lots"}).status_code == 400
    assert post_json(client, "/api/campaigns/status", {"key": "google_ads:1:2", "status": "PAUSED"}).status_code == 400
    activity = client.get("/activity").data.decode()
    assert "Paused “Search — Business Cards”" in activity and "55.50" in activity


def test_publish_now_schedule_draft_and_validation(client, app):
    hub = app.extensions["marketing_hub"]
    fb = next(t.key for t in hub.targets() if t.network == "facebook")
    pin = next(t.key for t in hub.targets() if t.network == "pinterest")

    resp = post_form(client, "/publish", {"body": "Hello", "targets": [fb], "mode": "now"}, follow_redirects=True)
    assert b"Published to 1 destination" in resp.data

    resp = post_form(client, "/publish", {"body": "Pin", "targets": [pin], "mode": "now"})
    assert resp.status_code == 200 and b"Pinterest needs an image URL" in resp.data

    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    resp = post_form(client, "/publish", {"body": "Later", "targets": [fb], "mode": "schedule", "scheduled_utc": when}, follow_redirects=True)
    assert b"Post scheduled" in resp.data
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert b"Pick a time in the future" in post_form(client, "/publish", {"body": "x", "targets": [fb], "mode": "schedule", "scheduled_utc": past}).data

    resp = post_form(client, "/publish", {"body": "", "mode": "draft"}, follow_redirects=True)
    assert b"Draft saved" in resp.data
    posts = hub.store.list_posts()
    assert sorted(p["status"] for p in posts) == ["draft", "published", "scheduled"]

    draft = next(p for p in posts if p["status"] == "draft")
    assert post_form(client, f"/posts/{draft['id']}/delete", {}).status_code == 302
    assert hub.store.get_post(draft["id"]) is None


def test_rules_save_and_run(client, app):
    resp = post_form(client, "/automation/rules", {"name": "High CPA", "metric": "cpa", "operator": ">", "threshold": "1",
                                                   "lookback_days": "7", "action": "pause", "enabled": "on"}, follow_redirects=True)
    assert b"Rule saved" in resp.data
    assert b"Look-back must be" in post_form(client, "/automation/rules", {"name": "x", "lookback_days": "5"}, follow_redirects=True).data
    dry = post_json(client, "/api/automation/run", {"dry_run": True}).get_json()
    assert dry["outcomes"] and {o["status"] for o in dry["outcomes"]} == {"would_apply"}
    real = post_json(client, "/api/automation/run", {"dry_run": False}).get_json()
    assert {o["status"] for o in real["outcomes"]} == {"applied"}
    again = post_json(client, "/api/automation/run", {"dry_run": False}).get_json()
    assert again["outcomes"] == []  # everything matching is now paused


def test_budgets_and_pacing(client):
    month = datetime.now().strftime("%Y-%m")
    post_form(client, "/budgets", {"month": month, "budget_total": "12,000", "budget_meta": "$3000", "budget_x": ""})
    page = client.get("/budgets").data.decode()
    assert "All platforms" in page and page.count('class="meter-row"') == 2


def test_utm_save_and_validation(client):
    resp = post_form(client, "/utm", {"url": "https://pps.com/a", "source": "google", "medium": "cpc", "campaign": "fall"}, follow_redirects=True)
    assert b"utm_source=google&amp;utm_medium=cpc&amp;utm_campaign=fall" in resp.data
    assert b"full web address" in post_form(client, "/utm", {"url": "pps.com", "source": "g", "medium": "m", "campaign": "c"}, follow_redirects=True).data


def test_demo_toggle_and_oauth_guards(client, monkeypatch):
    resp = post_form(client, "/connections/demo", {"mode": "off"}, follow_redirects=True)
    assert b"Showing live data" in resp.data
    resp = client.get("/oauth/meta/start", follow_redirects=True)
    assert b"META_APP_ID" in resp.data  # not configured yet
    monkeypatch.setenv("META_APP_ID", "app")
    monkeypatch.setenv("META_APP_SECRET", "secret")
    resp = client.get("/oauth/meta/start")
    assert resp.status_code == 302 and resp.headers["Location"].startswith("https://www.facebook.com/v26.0/dialog/oauth?")
    resp = client.get("/oauth/meta/callback?code=x&state=forged", follow_redirects=True)
    assert b"expired or was already used" in resp.data
    assert client.get("/oauth/myspace/start").status_code == 404


def test_export_csv(client):
    resp = client.get("/export.csv?range=7d")
    assert resp.mimetype == "text/csv"
    lines = resp.data.decode().splitlines()
    assert lines[0].startswith("date,platform,network") and len(lines) > 10


def test_studio_and_insights_use_claude(client, app):
    copy_stub, analyst_stub = app.extensions["stubs"]
    resp = post_json(client, "/api/studio/generate", {"product": "Business cards", "formats": ["google_rsa"], "variants": 2})
    data = resp.get_json()
    assert data["ok"] and data["result"]["strategy"] == "Speed sells."
    assert post_json(client, "/api/studio/generate", {"product": "", "formats": ["google_rsa"]}).status_code == 400
    saved = post_json(client, "/api/studio/save", {"brief": data["brief"], "result": data["result"]}).get_json()
    assert saved["ok"] and b"Business cards" in client.get("/studio").data

    report = post_json(client, "/api/insights", {"range": "30d"}).get_json()["report"]
    assert report["headline"] == "Search carries the month"
    rec = report["recommendations"][0]
    assert rec["applicable"] and rec["campaign_name"] == "Search — Business Cards"
    sent = json.loads(analyst_stub.requests[0]["messages"][0]["content"].split("Data (JSON):\n", 1)[1])
    assert sent["demo_data"] is True and sent["campaigns"]
    applied = post_json(client, "/api/insights/apply", rec).get_json()
    assert applied["ok"] and "Paused" in applied["message"]


def test_formatting_helpers():
    assert money(1234.5) == "$1,234" and money(12.5) == "$12.50" and money(None) == "—"
    assert money(5, "EUR") == "€5.00" and money(5, "SEK") == "SEK 5.00"
    assert compact(14504.78, "$") == "$14.5K" and compact(376) == "376" and compact(1_250_000) == "1.2M"
    assert objective_text("OUTCOME_SALES") == "Sales" and objective_text("PERFORMANCE_MAX") == "Performance Max"


@pytest.mark.parametrize("target,expected", [
    ("/campaigns?range=7d", "/campaigns?range=7d"), ("//evil.example.com", "/"), ("/\\evil.example.com", "/"),
    ("https://evil.example.com", "/"), ("", "/"), (None, "/"),
])
def test_login_only_redirects_to_local_paths(target, expected):
    assert safe_next(target) == expected


def test_only_https_links_are_rendered():
    assert safe_url("https://x.com/a") == "https://x.com/a"
    assert safe_url("javascript:alert(1)") is None and safe_url(None) is None
