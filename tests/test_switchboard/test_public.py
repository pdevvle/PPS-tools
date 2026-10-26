"""Unauthenticated endpoints: Twilio webhooks, raw email hook, website forms, the chat
widget API and open tracking."""

from __future__ import annotations

import pytest

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.api import public as public_api
from pps_tools.switchboard.channels import twilio
from pps_tools.switchboard.services import inbox, outbox, settings


@pytest.fixture(autouse=True)
def _fresh_limits():
    for limiter in (public_api.session_limiter, public_api.chat_limiter, public_api.form_limiter):
        limiter.reset()


def channel_row(cid):
    return db.one("SELECT * FROM channels WHERE id = ?", cid)


# -- Twilio -----------------------------------------------------------------------------


@pytest.fixture
def sms(client):
    return client.post("/api/channels", {"type": "sms", "address": "+16025550142", "config": {
        "account_sid": "AC123", "auth_token": "secret-token", "validate_signature": True}}, expect=201)["channel"]


def signed_post(anon, path, params, auth_token="secret-token"):
    sig = twilio.signature("http://testserver" + path, list(params.items()), auth_token)
    return anon.raw("post", path, data=params, headers={"X-Twilio-Signature": sig})


def test_twilio_inbound_with_valid_signature(anon, sms):
    path = f"/hooks/twilio/{sms['public_key']}"
    params = {"From": "+16025550164", "To": "+16025550142", "Body": "Can you do 15 banners by Saturday?",
              "MessageSid": "SMabc", "NumMedia": "0"}
    resp = signed_post(anon, path, params)
    assert resp.status_code == 200 and b"<Response>" in resp.data and resp.mimetype == "text/xml"
    msg = db.one("SELECT * FROM messages WHERE external_id = 'SMabc'")
    conv = inbox.get(msg["conversation_id"])
    assert msg["kind"] == "sms" and msg["from_handle"] == "+16025550164" and conv["thread_key"] == "+16025550164"
    # a second text from the same number threads into the same conversation
    signed_post(anon, path, {**params, "MessageSid": "SMdef", "Body": "Logos coming tonight"})
    assert db.one("SELECT conversation_id FROM messages WHERE external_id = 'SMdef'")["conversation_id"] == conv["id"]
    # Twilio retries: same SID is ignored
    signed_post(anon, path, params)
    assert db.scalar("SELECT COUNT(*) FROM messages") == 2


def test_twilio_rejects_bad_signature(anon, sms):
    path = f"/hooks/twilio/{sms['public_key']}"
    resp = anon.raw("post", path, data={"From": "+16025550164", "Body": "hi"}, headers={"X-Twilio-Signature": "nope"})
    assert resp.status_code == 403
    assert anon.raw("post", path, data={"From": "+16025550164", "Body": "hi"}).status_code == 403
    assert db.scalar("SELECT COUNT(*) FROM messages") == 0
    assert anon.raw("post", "/hooks/twilio/unknown-key", data={}).status_code == 404


def test_twilio_signature_check_can_be_disabled_and_media_is_saved(client, anon, sms, monkeypatch):
    client.patch(f"/api/channels/{sms['id']}", {"config": {"validate_signature": False}})
    monkeypatch.setattr(twilio.requests, "get", lambda url, auth, timeout: type("R", (), {"status_code": 200, "content": b"\x89PNG"})())
    resp = anon.raw("post", f"/hooks/twilio/{sms['public_key']}", data={
        "From": "+16025550164", "Body": "", "MessageSid": "MM1", "NumMedia": "1",
        "MediaUrl0": "https://api.twilio.com/media/1", "MediaContentType0": "image/png"})
    assert resp.status_code == 200
    msg = db.one("SELECT * FROM messages WHERE external_id = 'MM1'")
    atts = db.query("SELECT * FROM attachments WHERE owner_type = 'message' AND owner_id = ?", msg["id"])
    assert atts[0]["filename"] == "media-1.png" and msg["body_text"] == "(media)"


def test_twilio_status_callbacks(client, anon, sms, owner):
    settings.set("inbox.undo_send_seconds", 0)
    with db.transaction():
        conv = inbox.create_conversation(None, channel_row(sms["id"]), thread_key="+16025550164")
        mid = db.insert("messages", {"conversation_id": conv["id"], "channel_id": sms["id"], "direction": "out", "kind": "sms",
                                     "body_text": "Ready!", "author_id": owner["id"], "status": "sent", "external_id": "SM9",
                                     "date": "2026-10-26T10:00:00.000Z", "created_at": "2026-10-26T10:00:00.000Z"})
    path = f"/hooks/twilio/{sms['public_key']}/status"
    assert signed_post(anon, path, {"MessageSid": "SM9", "MessageStatus": "delivered"}).status_code == 204
    assert db.one("SELECT status FROM messages WHERE id = ?", mid)["status"] == "delivered"
    signed_post(anon, path, {"MessageSid": "SM9", "MessageStatus": "sent"})  # late, out of order
    assert db.one("SELECT status FROM messages WHERE id = ?", mid)["status"] == "delivered"
    signed_post(anon, path, {"MessageSid": "SM9", "MessageStatus": "undelivered", "ErrorCode": "30003"})
    row = db.one("SELECT status, error FROM messages WHERE id = ?", mid)
    assert row["status"] == "failed" and "30003" in row["error"]
    assert client.get("/api/notifications")["items"][0]["title"].startswith("Text not delivered")


# -- raw email hook -------------------------------------------------------------------


RAW = (b"From: Ann <ann@cust.test>\r\nTo: orders@shop.test\r\nSubject: Flyers\r\nMessage-ID: <hook1@cust.test>\r\n"
       b"Content-Type: text/plain; charset=utf-8\r\n\r\n500 flyers please\r\n")


def test_email_hook(client, anon):
    ch = client.post("/api/channels", {"type": "email", "address": "orders@shop.test", "config": {"demo": True}}, expect=201)["channel"]
    stored = db.jload(channel_row(ch["id"])["config_json"])
    path = f"/hooks/email/{ch['public_key']}"
    assert anon.raw("post", path + "?secret=wrong", data=RAW, content_type="message/rfc822").status_code == 403
    res = anon.raw("post", f"{path}?secret={stored['inbound_secret']}", data=RAW, content_type="message/rfc822")
    assert res.status_code == 200 and res.get_json()["conversation_id"]
    again = anon.raw("post", f"{path}?secret={stored['inbound_secret']}", data={"email": RAW.decode()})
    assert again.get_json()["duplicate"] is True
    assert inbox.get(res.get_json()["conversation_id"])["subject"] == "Flyers"


# -- website forms --------------------------------------------------------------------


@pytest.fixture
def form_channel(client):
    return client.post("/api/channels", {"type": "api", "name": "Quote form"}, expect=201)["channel"]


def test_form_submission_becomes_a_conversation(anon, form_channel):
    path = f"/hooks/form/{form_channel['public_key']}"
    pre = anon.raw("options", path)
    assert pre.status_code == 204 and pre.headers["Access-Control-Allow-Origin"] == "*"
    resp = anon.raw("post", path, json={"your-name": "Renee Alvarez", "your-email": "renee@dental.test",
                                        "message": "2,500 appointment cards", "quantity": "2500", "_gotcha": ""})
    assert resp.status_code == 200 and resp.headers["Access-Control-Allow-Origin"] == "*"
    msg = db.one("SELECT * FROM messages")
    assert msg["from_handle"] == "renee@dental.test" and msg["from_name"] == "Renee Alvarez"
    assert "2,500 appointment cards" in msg["body_html"] and "Quantity" in msg["body_html"]
    assert inbox.get(msg["conversation_id"])["subject"] == "Website form: Renee Alvarez"


def test_form_honeypot_validation_and_redirect(anon, form_channel):
    path = f"/hooks/form/{form_channel['public_key']}"
    assert anon.raw("post", path, data={"email": "bot@x.test", "_gotcha": "spam"}).status_code == 200
    assert db.scalar("SELECT COUNT(*) FROM messages") == 0
    assert anon.raw("post", path, data={"email": "nope", "message": "x"}).status_code == 400
    assert anon.raw("post", path, data={}).status_code == 400
    resp = anon.raw("post", path, data={"name": "Al", "email": "al@x.test", "message": "hi",
                                        "_redirect": "https://shop.test/thanks"})
    assert resp.status_code == 303 and resp.headers["Location"] == "https://shop.test/thanks"


def test_form_rate_limit(anon, form_channel):
    path = f"/hooks/form/{form_channel['public_key']}"
    codes = [anon.raw("post", path, data={"email": f"p{i}@x.test", "message": "hi"}).status_code for i in range(12)]
    assert codes[:10] == [200] * 10 and codes[-1] == 429


# -- website chat ---------------------------------------------------------------------


@pytest.fixture
def chat(client):
    return client.post("/api/channels", {"type": "chat", "name": "Website chat", "address": "shop.test",
                                         "config": {"greeting": "Hi! Need a quote?", "color": "#e8590c"}}, expect=201)["channel"]


def test_widget_script_is_configured(client, anon, chat):
    resp = anon.raw("get", f"/widget/{chat['public_key']}.js")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200 and resp.mimetype == "application/javascript"
    assert "__SB_CONFIG__" not in body and '"greeting": "Hi! Need a quote?"' in body and "#e8590c" in body
    client.patch(f"/api/channels/{chat['id']}", {"is_active": False})
    assert "turned off" in anon.raw("get", f"/widget/{chat['public_key']}.js").get_data(as_text=True)


def test_chat_config_online_when_an_agent_is_connected(anon, chat, owner):
    settings.set("org.business_hours", {d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")})
    assert anon.get(f"/public/chat/{chat['public_key']}/config")["online"] is False
    sub = realtime.broker.subscribe(owner["id"])
    try:
        cfg = anon.get(f"/public/chat/{chat['public_key']}/config")
        assert cfg["online"] is True and cfg["agents"][0]["name"] == "Olivia"
    finally:
        realtime.broker.unsubscribe(sub)


def test_chat_round_trip(client, anon, chat, owner):
    settings.set("inbox.undo_send_seconds", 0)
    key = chat["public_key"]
    session = anon.post(f"/public/chat/{key}/session", {"name": "Ellie", "email": "ellie@cust.test",
                                                         "page_url": "https://shop.test/postcards"}, expect=201)
    tok = session["token"]
    sent = anon.post(f"/public/chat/{key}/messages", {"token": tok, "body": "What's your turnaround for postcards?"}, expect=201)
    cid = db.one("SELECT conversation_id FROM chat_visitors WHERE token = ?", tok)["conversation_id"]
    assert inbox.get(cid)["contact_id"] and sent["message"]["direction"] == "in"
    # the agent sees it, comments (private) and replies
    assert client.get(f"/api/conversations/{cid}")["conversation"]["channel"]["type"] == "chat"
    client.post(f"/api/conversations/{cid}/comments", {"body": "<p>internal note</p>"})
    d = client.post("/api/drafts", {"conversation_id": cid, "body_html": "<p>3 business days after proof!</p>"})["draft"]
    assert d["to"][0]["handle"] == tok
    client.post(f"/api/drafts/{d['id']}/send", {})
    before = anon.get(f"/public/chat/{key}/messages", query_string={"token": tok})["messages"]
    assert [m["direction"] for m in before] == ["in"]  # still in the outbox
    outbox.process_outbox()
    msgs = anon.get(f"/public/chat/{key}/messages", query_string={"token": tok})["messages"]
    assert [m["direction"] for m in msgs] == ["in", "out"]
    assert msgs[1]["text"] == "3 business days after proof!" and msgs[1]["author"]["name"] == "Olivia"
    assert all("internal note" not in m["text"] for m in msgs)
    newer = anon.get(f"/public/chat/{key}/messages", query_string={"token": tok, "after": msgs[0]["id"]})["messages"]
    assert [m["id"] for m in newer] == [msgs[1]["id"]]
    # the visitor keeps talking in the same conversation
    anon.post(f"/public/chat/{key}/messages", {"token": tok, "body": "Perfect, thanks"}, expect=201)
    assert inbox.get(cid)["message_count"] == 3


def test_chat_agent_typing_and_unknown_visitor(client, anon, chat, owner):
    key = chat["public_key"]
    tok = anon.post(f"/public/chat/{key}/session", {"name": "Sam"}, expect=201)["token"]
    anon.post(f"/public/chat/{key}/messages", {"token": tok, "body": "hello"}, expect=201)
    cid = db.one("SELECT conversation_id FROM chat_visitors WHERE token = ?", tok)["conversation_id"]
    client.post("/api/presence", {"target": f"conversation:{cid}", "state": "composing"})
    assert anon.get(f"/public/chat/{key}/messages", query_string={"token": tok})["agent_typing"] is True
    resp = anon.raw("get", f"/public/chat/{key}/messages", query_string={"token": "bogus"})
    assert resp.status_code == 404 and resp.get_json()["error"]["code"] == "unknown_visitor"
    assert resp.headers["Access-Control-Allow-Origin"] == "*"  # the widget can read errors cross-origin
    other = client.post("/api/channels", {"type": "chat", "name": "Other site"}, expect=201)["channel"]
    anon.get(f"/public/chat/{other['public_key']}/messages", query_string={"token": tok}, expect=404)
    anon.post(f"/public/chat/{key}/messages", {"token": tok, "body": "   "}, expect=400)


def test_chat_requires_email_when_configured(client, anon, chat):
    client.patch(f"/api/channels/{chat['id']}", {"config": {"require_email": True}})
    key = chat["public_key"]
    assert anon.post(f"/public/chat/{key}/session", {"name": "x"}, expect=400)["error"]["code"] == "email_required"
    tok = anon.post(f"/public/chat/{key}/session", {"name": "x", "email": "x@cust.test"}, expect=201)["token"]
    # resuming a session returns the same token
    assert anon.post(f"/public/chat/{key}/session", {"token": tok}, expect=200)["token"] == tok


# -- open tracking --------------------------------------------------------------------


def test_open_pixel_marks_message_opened_once(client, anon, owner):
    ch = client.post("/api/channels", {"type": "email", "address": "orders@shop.test", "config": {"demo": True}}, expect=201)["channel"]
    with db.transaction():
        conv = inbox.create_conversation("Proof", channel_row(ch["id"]))
        mid = db.insert("messages", {"conversation_id": conv["id"], "channel_id": ch["id"], "direction": "out", "kind": "email",
                                     "status": "sent", "track_token": "tracktok", "author_id": owner["id"],
                                     "date": "2026-10-26T10:00:00.000Z", "created_at": "2026-10-26T10:00:00.000Z"})
    resp = anon.raw("get", "/t/o/tracktok.gif")
    assert resp.status_code == 200 and resp.mimetype == "image/gif" and resp.headers["Cache-Control"].startswith("no-store")
    first = db.one("SELECT opened_at FROM messages WHERE id = ?", mid)["opened_at"]
    assert first
    anon.raw("get", "/t/o/tracktok.gif")
    assert db.one("SELECT opened_at FROM messages WHERE id = ?", mid)["opened_at"] == first
    assert anon.raw("get", "/t/o/unknown.gif").status_code == 200
