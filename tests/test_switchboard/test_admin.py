"""Admin: API tokens end to end, outgoing webhooks (signing, filtering, retry with
backoff), sidebar integrations (iframe templating, WooCommerce with masked secrets),
backup, JSON export, the audit log and admin-only access. No network: requests is faked."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
import requests

from pps_tools.switchboard import config, db
from pps_tools.switchboard.services import inbox, integrations, webhooks
from pps_tools.switchboard.services.inbox import Inbound
from pps_tools.switchboard.util import iso, now, now_iso, token


def add_channel(visibility="shared", owner_id=None):
    with db.transaction():
        cid = db.insert("channels", {
            "type": "email", "name": "Orders", "address": f"{token(4)}@shop.test", "visibility": visibility,
            "owner_user_id": owner_id, "config_json": "{}", "public_key": token(8), "created_at": now_iso(),
        })
    return db.one("SELECT * FROM channels WHERE id = ?", cid)


def receive(channel, sender="lena@cafe.test", name="Lena Ortiz", subject="Menu reprint"):
    msg = inbox.deliver_inbound(Inbound(channel=channel, kind="email", from_handle=sender, from_name=name, subject=subject,
                                        body_text="Hello", external_id=f"<{token(6)}@cafe.test>"))
    return msg["conversation_id"]


# -- API tokens -------------------------------------------------------------------------


def test_api_token_end_to_end(client, owner, anon):
    res = client.post("/api/admin/tokens", {"name": "Zapier"}, expect=201)
    raw, item = res["token"], res["item"]
    assert raw.startswith("sb_") and item["prefix"] == raw[:10] and item["user_id"] == owner["id"]
    assert db.scalar("SELECT COUNT(*) FROM api_tokens WHERE token_hash = ? OR prefix = ?", raw, raw) == 0  # only a hash is kept
    assert raw not in json.dumps(client.get("/api/admin/tokens"))

    bearer = {"Authorization": f"Bearer {raw}"}
    me = anon.c.get("/api/me", headers=bearer)  # no cookie, no CSRF header
    assert me.status_code == 200 and me.get_json()["me"]["id"] == owner["id"]
    made = anon.c.post("/api/admin/tokens", json={"name": "Made with a token"}, headers=bearer)
    assert made.status_code == 201  # token-authenticated writes don't need X-Requested-With
    listed = {t["id"]: t for t in client.get("/api/admin/tokens")["items"]}
    assert listed[item["id"]]["last_used_at"] is not None

    client.delete(f"/api/admin/tokens/{item['id']}")
    assert anon.c.get("/api/me", headers=bearer).status_code == 401
    assert anon.c.get("/api/me", headers={"Authorization": "Bearer sb_not-a-real-token"}).status_code == 401
    revoked = {t["id"]: t for t in client.get("/api/admin/tokens")["items"]}[item["id"]]
    assert revoked["revoked_at"] is not None
    client.post("/api/admin/tokens", {"name": "  "}, expect=400)


def test_tokens_stop_working_when_the_person_is_deactivated(client, make_user, anon):
    admin, admin_client = make_user("admin")
    raw = admin_client.post("/api/admin/tokens", {"name": "Script"}, expect=201)["token"]
    assert anon.c.get("/api/me", headers={"Authorization": f"Bearer {raw}"}).status_code == 200
    with db.transaction():
        db.execute("UPDATE users SET is_active = 0 WHERE id = ?", admin["id"])
    assert anon.c.get("/api/me", headers={"Authorization": f"Bearer {raw}"}).status_code == 401


# -- webhooks -----------------------------------------------------------------------------


@pytest.fixture
def outbound(monkeypatch):
    """Fake requests.post for webhook deliveries; set .status / .error to change the answer."""
    state = SimpleNamespace(calls=[], status=200, error=None)

    def fake_post(url, data=None, headers=None, timeout=None, allow_redirects=True, **kw):
        state.calls.append(SimpleNamespace(url=url, body=data, headers=headers, timeout=timeout, allow_redirects=allow_redirects))
        if state.error:
            raise state.error
        return SimpleNamespace(status_code=state.status)

    monkeypatch.setattr(webhooks.requests, "post", fake_post)
    return state


@pytest.fixture
def clock(monkeypatch):
    """Freeze the webhook module's clock; advance it with clock.advance(minutes=...)."""
    state = SimpleNamespace(t=now())

    def advance(**kw):
        state.t += timedelta(**kw)

    state.advance = advance
    monkeypatch.setattr(webhooks, "now", lambda: state.t)
    monkeypatch.setattr(webhooks, "now_iso", lambda: iso(state.t))
    return state


def add_webhook(client, events=("*",), url="https://hooks.example.test/sb", **extra):
    return client.post("/api/admin/webhooks", {"name": "Zap", "url": url, "events": list(events), **extra}, expect=201)["item"]


def test_webhook_delivery_is_signed_and_filtered(client, outbound):
    hook = add_webhook(client, events=["conversation.created"])
    assert hook["secret"].startswith("whsec_") and hook["is_active"] is True
    cid = receive(add_channel())  # fires conversation.created and message.received
    rows = db.query("SELECT * FROM webhook_deliveries")
    assert [r["event"] for r in rows] == ["conversation.created"]

    assert webhooks.process_deliveries() == 1
    call = outbound.calls[0]
    expected = "sha256=" + hmac.new(hook["secret"].encode(), call.body, hashlib.sha256).hexdigest()
    assert call.headers["X-Switchboard-Signature"] == expected
    assert call.headers["X-Switchboard-Event"] == "conversation.created"
    assert call.headers["X-Switchboard-Delivery"] == str(rows[0]["id"])
    assert call.headers["Content-Type"] == "application/json"
    assert call.allow_redirects is False and call.timeout == webhooks.TIMEOUT_SECONDS
    payload = json.loads(call.body)
    assert payload["id"] == rows[0]["id"] and payload["event"] == "conversation.created"
    assert payload["data"]["conversation_id"] == cid
    assert payload["data"]["conversation"]["url"] == f"{config.current().base_url}/inbox/c/{cid}"

    delivery = db.one("SELECT * FROM webhook_deliveries WHERE id = ?", rows[0]["id"])
    assert (delivery["status"], delivery["attempts"], delivery["response_code"]) == ("delivered", 1, 200)
    item = client.get("/api/admin/webhooks")["items"][0]
    assert item["last_status"] == 200 and item["last_error"] is None and item["pending"] == 0
    assert webhooks.process_deliveries() == 0  # nothing left to send


def test_event_patterns_and_paused_webhooks(client, outbound):
    assert webhooks.matches(["*"], "anything.at_all")
    assert webhooks.matches(["job.*"], "job.created") and not webhooks.matches(["job.*"], "jobs.created")
    assert not webhooks.matches(["message.received"], "message.sent")
    hook = add_webhook(client, events=["job.*"])
    assert webhooks.enqueue("job.created", {"job_id": None}) == 1
    assert webhooks.enqueue("conversation.closed", {"conversation_id": None}) == 0
    client.patch(f"/api/admin/webhooks/{hook['id']}", {"is_active": False})
    assert webhooks.enqueue("job.created", {"job_id": None}) == 0


def test_failed_deliveries_back_off_then_give_up(client, outbound, clock):
    hook = add_webhook(client)
    outbound.status = 500
    webhooks.enqueue("comment.created", {"conversation_id": None})
    did = db.scalar("SELECT id FROM webhook_deliveries")
    for attempt, wait in enumerate(webhooks.BACKOFF, start=1):
        assert webhooks.process_deliveries() == 1
        row = db.one("SELECT * FROM webhook_deliveries WHERE id = ?", did)
        assert (row["status"], row["attempts"], row["error"]) == ("pending", attempt, "HTTP 500")
        assert row["next_attempt_at"] == iso(clock.t + wait)
        assert webhooks.process_deliveries() == 0  # not due yet
        clock.advance(seconds=wait.total_seconds())
    assert webhooks.process_deliveries() == 1
    row = db.one("SELECT * FROM webhook_deliveries WHERE id = ?", did)
    assert (row["status"], row["attempts"], row["next_attempt_at"]) == ("failed", webhooks.MAX_ATTEMPTS, None)
    assert len(outbound.calls) == webhooks.MAX_ATTEMPTS
    # every attempt reused the same delivery id, so receivers can drop duplicates
    assert {c.headers["X-Switchboard-Delivery"] for c in outbound.calls} == {str(did)}

    outbound.status = 204
    retried = client.post(f"/api/admin/deliveries/{did}/retry")["delivery"]
    assert (retried["status"], retried["attempts"]) == ("pending", 0)
    assert webhooks.process_deliveries() == 1
    assert db.scalar("SELECT status FROM webhook_deliveries WHERE id = ?", did) == "delivered"
    listed = client.get(f"/api/admin/webhooks/{hook['id']}/deliveries")["items"]
    assert listed[0]["id"] == did and listed[0]["payload"]["event"] == "comment.created"


def test_connection_errors_and_the_test_button(client, outbound):
    hook = add_webhook(client)
    outbound.error = requests.ConnectionError("refused")
    res = client.post(f"/api/admin/webhooks/{hook['id']}/test")
    assert res["delivery"]["status"] == "pending" and res["delivery"]["error"] == "Couldn't connect: ConnectionError"
    assert res["item"]["last_error"] == "Couldn't connect: ConnectionError"
    outbound.error = requests.Timeout()
    assert client.post(f"/api/admin/webhooks/{hook['id']}/test")["delivery"]["error"].startswith("Timed out")
    outbound.error = None
    res = client.post(f"/api/admin/webhooks/{hook['id']}/test")
    assert res["delivery"]["status"] == "delivered" and res["delivery"]["event"] == "webhook.test"
    assert json.loads(outbound.calls[-1].body)["data"]["message"].startswith("Hello from Switchboard")


def test_webhook_validation_and_secret_rotation(client):
    client.post("/api/admin/webhooks", {"name": "Bad", "url": "ftp://example.test"}, expect=400)
    client.post("/api/admin/webhooks", {"name": "", "url": "https://example.test"}, expect=400)
    client.post("/api/admin/webhooks", {"name": "Bad", "url": "https://example.test", "events": "job.created"}, expect=400)
    hook = add_webhook(client, events=["job.created", "job.created", "message.sent"])
    assert hook["events"] == ["job.created", "message.sent"]
    rotated = client.post(f"/api/admin/webhooks/{hook['id']}/rotate-secret")["item"]
    assert rotated["secret"] != hook["secret"] and rotated["secret"].startswith("whsec_")
    events = client.get("/api/admin/webhooks")["events"]
    assert {"name": "message.received", "description": "A customer message arrived"} in events
    client.delete(f"/api/admin/webhooks/{hook['id']}")
    assert client.get("/api/admin/webhooks")["items"] == []


# -- sidebar integrations --------------------------------------------------------------------


def test_iframe_integration_fills_in_the_conversation(client, owner, make_user):
    cid = receive(add_channel())
    item = client.post("/api/admin/integrations", {"kind": "iframe", "name": "CRM", "config": {
        "url": "https://crm.example.test/find?email={{contact.email}}&n={{ contact.name }}", "height": 5000}}, expect=201)["item"]
    assert item["config"]["height"] == 1200  # clamped
    _, agent = make_user("agent")
    assert [i["id"] for i in agent.get("/api/integrations")["items"]] == [item["id"]]
    ctx = agent.get(f"/api/integrations/{item['id']}/context?conversation_id={cid}")
    assert ctx == {"kind": "iframe", "url": "https://crm.example.test/find?email=lena%40cafe.test&n=Lena%20Ortiz", "height": 1200}

    client.patch(f"/api/admin/integrations/{item['id']}", {"config": {"url": "https://maps.test/?q={{contact.phone}}"}})
    assert agent.get(f"/api/integrations/{item['id']}/context?conversation_id={cid}")["message"] == "Needs the phone for this contact."

    client.post("/api/admin/integrations", {"kind": "iframe", "name": "x", "config": {"url": "http://insecure.test"}}, expect=400)
    client.post("/api/admin/integrations", {"kind": "iframe", "name": "x", "config": {"url": "https://a.test/{{contact.ssn}}"}}, expect=400)
    client.post("/api/admin/integrations", {"kind": "zapier", "name": "x", "config": {}}, expect=400)

    private = receive(add_channel("personal", owner["id"]), sender="secret@x.test")
    agent.get(f"/api/integrations/{item['id']}/context?conversation_id={private}", expect=404)
    client.patch(f"/api/admin/integrations/{item['id']}", {"is_active": False})
    assert agent.get("/api/integrations")["items"] == []
    agent.get(f"/api/integrations/{item['id']}/context?conversation_id={cid}", expect=404)
    _, staff = make_user("staff")
    staff.get("/api/integrations", expect=403)


class FakeWoo:
    def __init__(self, status=200, orders=None):
        self.status, self.orders, self.calls = status, orders or [], []

    def __call__(self, url, params=None, auth=None, timeout=None, **kw):
        self.calls.append(SimpleNamespace(url=url, params=params, auth=auth, timeout=timeout))
        return SimpleNamespace(status_code=self.status, json=lambda: self.orders)


def test_woocommerce_masks_secrets_and_maps_orders(client, make_user, monkeypatch):
    integrations.clear_cache()
    woo = FakeWoo(orders=[
        {"id": 101, "number": "101", "status": "processing", "total": "45.00", "currency": "USD",
         "date_created_gmt": "2026-10-20T15:00:00", "billing": {"email": "LENA@cafe.test"},
         "line_items": [{"name": "Trifold menus", "quantity": 250}]},
        {"id": 102, "number": "102", "status": "completed", "total": "9.00", "currency": "USD",
         "date_created_gmt": "2026-10-19T15:00:00", "billing": {"email": "someone-else@cafe.test"}, "line_items": []},
    ])
    monkeypatch.setattr(integrations.requests, "get", woo)
    cid = receive(add_channel())
    item = client.post("/api/admin/integrations", {"kind": "woocommerce", "name": "Shop", "config": {
        "store_url": "https://shop.example.test/", "consumer_key": "ck_live_123", "consumer_secret": "cs_live_456"}}, expect=201)["item"]
    assert item["config"]["store_url"] == "https://shop.example.test"
    listing = json.dumps(client.get("/api/admin/integrations"), ensure_ascii=False)
    assert "ck_live_123" not in listing and "cs_live_456" not in listing
    assert item["config"]["consumer_key"] == integrations.MASK + "_123"  # just enough to recognize it
    _, agent = make_user("agent")
    public = agent.get("/api/integrations")["items"][0]
    assert public["config"] == {"store_url": "https://shop.example.test"}

    # saving the form with masked secrets keeps the stored ones
    client.patch(f"/api/admin/integrations/{item['id']}", {"config": {
        "store_url": "https://shop.example.test", "consumer_key": integrations.MASK, "consumer_secret": ""}})
    stored = db.jload(db.scalar("SELECT config_json FROM integrations WHERE id = ?", item["id"]))
    assert stored["consumer_key"] == "ck_live_123" and stored["consumer_secret"] == "cs_live_456"

    ctx = agent.get(f"/api/integrations/{item['id']}/context?conversation_id={cid}")
    assert [o["number"] for o in ctx["orders"]] == ["101"]  # only the exact billing email
    order = ctx["orders"][0]
    assert order["url"] == "https://shop.example.test/wp-admin/post.php?post=101&action=edit"
    assert order["date"] == "2026-10-20T15:00:00Z" and order["items"] == [{"name": "Trifold menus", "quantity": 250}]
    call = woo.calls[-1]
    assert call.url == "https://shop.example.test/wp-json/wc/v3/orders" and call.params["search"] == "lena@cafe.test"
    assert call.auth == ("ck_live_123", "cs_live_456")
    agent.get(f"/api/integrations/{item['id']}/context?conversation_id={cid}")
    assert len(woo.calls) == 1  # cached for a few minutes

    integrations.clear_cache()
    woo.status = 401
    ctx = agent.get(f"/api/integrations/{item['id']}/context?conversation_id={cid}")
    assert ctx["orders"] == [] and "rejected the API keys" in ctx["message"]
    assert client.post("/api/admin/integrations/test", {"id": item["id"], "config": {
        "store_url": "https://shop.example.test", "consumer_key": integrations.MASK, "consumer_secret": integrations.MASK}})["ok"] is False
    woo.status = 200
    assert client.post("/api/admin/integrations/test", {"id": item["id"], "config": {
        "store_url": "https://shop.example.test", "consumer_key": integrations.MASK, "consumer_secret": integrations.MASK}}) == {
        "ok": True, "message": "Connected to WooCommerce."}
    assert client.post("/api/admin/integrations/test", {"kind": "woocommerce", "config": {"store_url": "nope"}})["ok"] is False


# -- backup, export, audit ------------------------------------------------------------------


def test_backup_is_a_consistent_sqlite_copy(client):
    resp = client.raw("get", "/api/admin/backup")
    assert resp.status_code == 200
    assert resp.headers["Content-Disposition"].startswith('attachment; filename="switchboard-backup-')
    data = resp.get_data()
    resp.close()
    assert data.startswith(b"SQLite format 3\x00") and len(data) > 10_000
    assert not list(config.current().data_dir.glob("switchboard-backup-*.db"))  # temp copy removed
    assert db.scalar("SELECT action FROM audit_log ORDER BY id DESC LIMIT 1") == "data.backup"


def test_export_has_the_data_without_secrets(client, owner, outbound):
    cid = receive(add_channel())
    raw = client.post("/api/admin/tokens", {"name": "Export test"}, expect=201)["token"]
    hook = add_webhook(client)
    resp = client.raw("get", "/api/admin/export.json")
    assert resp.status_code == 200 and "switchboard-export-" in resp.headers["Content-Disposition"]
    text = resp.get_data(as_text=True)
    for secret in (raw, hook["secret"], "password_hash", "pin_hash", "feed_token", "public_token", "token_hash"):
        assert secret not in text
    data = json.loads(text)
    assert data["app"] == "Switchboard" and data["organization"]["timezone"] == "America/Phoenix"
    assert [p["email"] for p in data["people"]] == [owner["email"]]
    conv = next(c for c in data["conversations"] if c["id"] == cid)
    assert conv["messages"][0]["body_text"] == "Hello" and conv["messages"][0]["direction"] == "in"
    assert any(c["handles"] for c in data["contacts"])
    for key in ("jobs", "shifts", "time_entries", "time_off_requests", "tasks", "teams", "labels"):
        assert isinstance(data[key], list)


def test_audit_log_pages_newest_first(client):
    for n in range(3):
        client.post("/api/admin/tokens", {"name": f"T{n}"}, expect=201)
    first = client.get("/api/admin/audit?limit=2")
    assert [i["action"] for i in first["items"]] == ["api_token.create", "api_token.create"]
    assert first["items"][0]["data"] == {"name": "T2"} and first["items"][0]["user_name"] == "Olivia Owner"
    assert first["next"] == first["items"][-1]["id"]
    older = client.get(f"/api/admin/audit?limit=2&before={first['next']}")
    assert older["items"][0]["data"] == {"name": "T0"}
    assert all(i["id"] < first["next"] for i in older["items"])


@pytest.mark.parametrize("role", ["manager", "agent", "staff"])
def test_admin_endpoints_need_admin(client, make_user, role):
    _, other = make_user(role)
    for path in ("/api/admin/tokens", "/api/admin/webhooks", "/api/admin/integrations", "/api/admin/backup",
                 "/api/admin/export.json", "/api/admin/audit"):
        other.get(path, expect=403)
    other.post("/api/admin/tokens", {"name": "nope"}, expect=403)
    other.post("/api/admin/webhooks", {"name": "nope", "url": "https://x.test"}, expect=403)
    other.post("/api/admin/integrations", {"kind": "iframe", "name": "x", "config": {"url": "https://x.test"}}, expect=403)


def test_demo_seed_adds_examples(app):
    from pps_tools.switchboard.seed import seed_demo

    seed_demo()
    hooks = db.query("SELECT * FROM webhooks")
    assert hooks and not any(h["is_active"] for h in hooks)  # demo webhooks never fire
    assert db.scalar("SELECT COUNT(*) FROM webhook_deliveries") == 0
    apps = db.query("SELECT * FROM integrations WHERE is_active = 1")
    assert apps and all(db.jload(a["config_json"])["url"].startswith("https://") for a in apps if a["kind"] == "iframe")


def test_every_fired_event_is_offered_to_webhooks():
    """Each hooks.fire("...") in the code base must be listed so admins can subscribe to it."""
    import re
    from pathlib import Path

    import pps_tools.switchboard as package

    fired = set()
    for path in Path(package.__file__).parent.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for first_arg in re.findall(r"hooks\.fire\(\s*([^,]+),", text):  # may be `"a.b" if x else "a.c"`
            fired.update(re.findall(r'"([a-z_]+\.[a-z_]+)"', first_arg))
    catalog = {name for name, _ in webhooks.EVENT_CATALOG}
    assert fired, "no hooks found — the pattern is stale"
    assert fired <= catalog, f"add to webhooks.EVENT_CATALOG: {sorted(fired - catalog)}"
