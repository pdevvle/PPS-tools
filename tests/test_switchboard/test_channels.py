"""Channels: settings API, email (IMAP sync + SMTP send), Twilio, API channels, chat fallback.
All network is faked."""

from __future__ import annotations

import smtplib
from datetime import timedelta
from email import message_from_bytes, policy

import pytest

from pps_tools.switchboard import db
from pps_tools.switchboard.channels import api_channel, chat as chat_channel, mime
from pps_tools.switchboard.channels import email as email_channel
from pps_tools.switchboard.channels import twilio
from pps_tools.switchboard.services import inbox, mailer, outbox, settings
from pps_tools.switchboard.util import iso, now, now_iso

MASK = "••••••"


def raw_email(subject="Quote please", body="Hello there", sender="Ann Lee <ann@cust.test>", msgid="<m1@cust.test>",
              extra_headers="", in_reply_to=None, to="orders@shop.test"):
    lines = [
        f"From: {sender}", f"To: {to}", f"Subject: {subject}", f"Message-ID: {msgid}",
        "Date: Mon, 26 Oct 2026 10:00:00 -0700", "MIME-Version: 1.0",
    ]
    if in_reply_to:
        lines += [f"In-Reply-To: {in_reply_to}", f"References: {in_reply_to}"]
    if extra_headers:
        lines.append(extra_headers)
    lines += ["Content-Type: text/plain; charset=utf-8", "", body]
    return "\r\n".join(lines).encode()


def make_email_channel(client, **config):
    cfg = {"imap_host": "imap.shop.test", "imap_user": "orders@shop.test", "imap_password": "imap-secret",
           "smtp_host": "smtp.shop.test", "smtp_user": "orders@shop.test", "smtp_password": "smtp-secret", **config}
    return client.post("/api/channels", {"type": "email", "name": "Orders", "address": "orders@shop.test",
                                         "config": cfg}, expect=201)["channel"]


# -- settings API -----------------------------------------------------------------------


def test_create_masks_secrets_and_keeps_them(client):
    ch = make_email_channel(client)
    assert ch["config"]["imap_password"] == MASK and ch["config"]["smtp_password"] == MASK
    assert "inbound_secret" not in ch["config"]
    assert ch["connect"]["inbound_hook"].startswith("http://testserver/hooks/email/")
    stored = db.jload(db.one("SELECT config_json FROM channels WHERE id = ?", ch["id"])["config_json"])
    assert stored["imap_password"] == "imap-secret" and stored["inbound_secret"]
    # saving the mask back (or an empty field) keeps the secret; a new value replaces it
    client.patch(f"/api/channels/{ch['id']}", {"config": {"imap_password": MASK, "smtp_password": "", "imap_folder": "Orders"}})
    stored = db.jload(db.one("SELECT config_json FROM channels WHERE id = ?", ch["id"])["config_json"])
    assert stored["imap_password"] == "imap-secret" and stored["smtp_password"] == "smtp-secret"
    assert stored["imap_folder"] == "Orders"
    client.patch(f"/api/channels/{ch['id']}", {"config": {"imap_password": "new-pass"}})
    stored = db.jload(db.one("SELECT config_json FROM channels WHERE id = ?", ch["id"])["config_json"])
    assert stored["imap_password"] == "new-pass"


def test_validation_and_permissions(client, make_user):
    client.post("/api/channels", {"type": "fax"}, expect=400)
    client.post("/api/channels", {"type": "email", "address": "not-an-email"}, expect=400)
    client.post("/api/channels", {"type": "sms", "address": "+16025550142"}, expect=400)  # no Twilio credentials
    client.post("/api/channels", {"type": "sms", "address": "12"}, expect=400)
    ch = client.post("/api/channels", {"type": "sms", "address": "(602) 555-0142", "config": {"demo": True}}, expect=201)["channel"]
    assert ch["address"] == "+16025550142"
    assert ch["connect"]["twilio_inbound"].endswith(f"/hooks/twilio/{ch['public_key']}")
    _, agent = make_user("agent")
    agent.get("/api/channels", expect=403)
    agent.post("/api/channels", {"type": "chat", "name": "x"}, expect=403)


def test_channel_shows_up_in_bootstrap_and_delete_keeps_conversations(client):
    ch = client.post("/api/channels", {"type": "chat", "name": "Website chat", "address": "shop.test"}, expect=201)["channel"]
    assert any(c["id"] == ch["id"] for c in client.get("/api/bootstrap")["channels"])
    msg = inbox.deliver_inbound(inbox.Inbound(channel=db.one("SELECT * FROM channels WHERE id = ?", ch["id"]), kind="chat",
                                              from_name="Visitor", body_text="hi", thread_key="tok1"))
    client.delete(f"/api/channels/{ch['id']}")
    assert inbox.get(msg["conversation_id"])["channel_id"] is None
    client.get(f"/api/channels/{ch['id']}", expect=404)


def test_rotate_key_and_personal_visibility(client, owner):
    ch = client.post("/api/channels", {"type": "email", "address": "me@shop.test", "visibility": "personal",
                                       "config": {"demo": True}}, expect=201)["channel"]
    assert ch["visibility"] == "personal" and ch["owner_user_id"] == owner["id"] and ch["team_id"] is None
    rotated = client.post(f"/api/channels/{ch['id']}/rotate-key")["channel"]
    assert rotated["public_key"] != ch["public_key"]


def test_connection_test_endpoint(client, monkeypatch):
    class FakeConn:
        def select(self, folder, readonly=False):
            return "OK", [b"1"]

        def logout(self):
            pass

    class FakeSMTP:
        def noop(self):
            return 250, b"ok"

        def quit(self):
            pass

    monkeypatch.setattr(email_channel, "_imap_connect", lambda cfg: FakeConn())
    monkeypatch.setattr(email_channel, "_smtp_connect", lambda cfg: FakeSMTP())
    res = client.post("/api/channels/test", {"type": "email", "config": {"imap_host": "i", "smtp_host": "s"}})
    assert res["ok"] is True and "IMAP" in res["message"] and "SMTP" in res["message"]

    def refuse(cfg):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(email_channel, "_smtp_connect", refuse)
    res = client.post("/api/channels/test", {"type": "email", "config": {"imap_host": "i", "smtp_host": "s"}})
    assert res["ok"] is False and "SMTP" in res["message"]
    demo = client.post("/api/channels/test", {"type": "email", "config": {"demo": True}})
    assert demo["ok"] is True


# -- MIME parsing ---------------------------------------------------------------------


def test_parse_multipart_with_inline_image_attachment_and_charset():
    raw = (
        b"From: =?utf-8?q?Jos=C3=A9?= <jose@cust.test>\r\nTo: orders@shop.test\r\nSubject: Logo files\r\n"
        b"Message-ID: <abc@cust.test>\r\nIn-Reply-To: <prev@shop.test>\r\nReferences: <a@x> <prev@shop.test>\r\n"
        b"MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=XX\r\n\r\n"
        b"--XX\r\nContent-Type: multipart/related; boundary=YY\r\n\r\n"
        b"--YY\r\nContent-Type: text/html; charset=iso-8859-1\r\n\r\n<p>Caf\xe9 logo: <img src=\"cid:logo1\"></p>\r\n"
        b"--YY\r\nContent-Type: image/png\r\nContent-ID: <logo1>\r\nContent-Transfer-Encoding: base64\r\n\r\niVBORw0KGgo=\r\n"
        b"--YY--\r\n"
        b"--XX\r\nContent-Type: application/pdf; name=\"art.pdf\"\r\nContent-Disposition: attachment; filename=\"art.pdf\"\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\nJVBERi0xLjQ=\r\n--XX--\r\n"
    )
    out = mime.parse(raw)
    assert out["from_name"] == "José" and out["from_handle"] == "jose@cust.test"
    assert "Café logo" in out["body_html"] and "Café logo" in out["body_text"]
    assert out["external_id"] == "<abc@cust.test>" and out["in_reply_to"] == "<prev@shop.test>"
    assert out["references"] == ["<a@x>", "<prev@shop.test>"]
    names = {a["filename"]: a for a in out["attachments"]}
    assert names["art.pdf"]["inline"] is False and names["art.pdf"]["data"].startswith(b"%PDF")
    inline = [a for a in out["attachments"] if a["inline"]]
    assert inline and inline[0]["content_id"] == "logo1"
    assert out["is_auto"] is False


@pytest.mark.parametrize("header", ["Auto-Submitted: auto-replied", "Precedence: bulk", "List-Id: <news.example>",
                                    "X-Autoreply: yes"])
def test_parse_flags_automated_mail(header):
    assert mime.parse(raw_email(extra_headers=header))["is_auto"] is True


def test_parse_flags_spam():
    assert mime.parse(raw_email(extra_headers="X-Spam-Flag: YES"))["is_spam"] is True


# -- IMAP sync ------------------------------------------------------------------------


class FakeIMAP:
    def __init__(self, mailbox: dict, uidvalidity="7"):
        self.mailbox = mailbox
        self.uidvalidity = uidvalidity
        self.selected = None
        self.fetched = []

    def select(self, folder, readonly=False):
        assert readonly, "IMAP must be opened read-only"
        self.selected = folder
        return "OK", [str(len(self.mailbox)).encode()]

    def response(self, code):
        return code, [self.uidvalidity.encode()]

    def uid(self, command, *args):
        uids = sorted(self.mailbox)
        if command == "SEARCH":
            if args[1] == "UID":
                start = int(args[2].split(":")[0])
                hits = [u for u in uids if u >= start] or uids[-1:]  # IMAP: n:* always includes the newest
            else:
                hits = uids
            return "OK", [b" ".join(str(u).encode() for u in hits)]
        if command == "FETCH":
            assert "PEEK" in args[1], "fetch must not mark messages read"
            uid = int(args[0])
            self.fetched.append(uid)
            return "OK", [(f"1 (UID {uid} BODY[] {{1}}".encode(), self.mailbox[uid]), b")"]
        raise AssertionError(command)

    def logout(self):
        pass


def test_imap_sync_delivers_threads_and_resumes(client, monkeypatch):
    ch = make_email_channel(client)
    mailbox = {
        101: raw_email(subject="Banner quote", msgid="<q1@cust.test>"),
        102: raw_email(subject="Business cards", msgid="<q2@cust.test>", sender="Bob <bob@cust.test>"),
    }
    fake = FakeIMAP(mailbox)
    monkeypatch.setattr(email_channel, "_imap_connect", lambda cfg: fake)
    res = client.post(f"/api/channels/{ch['id']}/sync")
    assert res["fetched"] == 2 and res["error"] is None
    assert fake.selected == '"INBOX"'
    # nothing new: nothing fetched again
    fake.fetched.clear()
    assert client.post(f"/api/channels/{ch['id']}/sync")["fetched"] == 0
    assert fake.fetched == []
    # a reply arrives and threads into the first conversation
    mailbox[103] = raw_email(subject="Re: Banner quote", msgid="<q3@cust.test>", in_reply_to="<q1@cust.test>")
    assert client.post(f"/api/channels/{ch['id']}/sync")["fetched"] == 1
    first = db.one("SELECT conversation_id FROM messages WHERE external_id = '<q1@cust.test>'")["conversation_id"]
    reply = db.one("SELECT conversation_id FROM messages WHERE external_id = '<q3@cust.test>'")["conversation_id"]
    assert first == reply
    state = db.jload(db.one("SELECT sync_state_json FROM channels WHERE id = ?", ch["id"])["sync_state_json"])
    assert state["INBOX"] == {"uidvalidity": "7", "last_uid": 103}
    # UIDVALIDITY changed: refetch the window, but Message-IDs prevent duplicates
    fake.uidvalidity = "8"
    assert client.post(f"/api/channels/{ch['id']}/sync")["fetched"] == 0
    assert db.scalar("SELECT COUNT(*) FROM messages") == 3


def test_imap_sync_error_is_recorded(client, monkeypatch):
    ch = make_email_channel(client)

    def broken(cfg):
        raise OSError("connection refused")

    monkeypatch.setattr(email_channel, "_imap_connect", broken)
    res = client.post(f"/api/channels/{ch['id']}/sync")
    assert res["fetched"] == 0 and "connection refused" in res["error"]
    listed = client.get("/api/channels")["items"][0]
    assert "connection refused" in listed["sync_error"]


def test_worker_kicks_only_due_real_mailboxes(client, monkeypatch):
    from pps_tools.switchboard.api import channels as channels_api

    real = make_email_channel(client)
    make_email_channel(client, demo=True)
    client.post("/api/channels", {"type": "email", "address": "noimap@shop.test", "config": {"smtp_host": "s"}}, expect=201)
    started = []

    class InlineThread:
        def __init__(self, target, args, name, daemon):
            self.target, self.args = target, args

        def start(self):
            started.append(self.args[0])

    monkeypatch.setattr(channels_api.threading, "Thread", InlineThread)
    channels_api._last_kick.clear()
    assert channels_api.kick_mail_sync() == 1
    assert started == [real["id"]]
    assert channels_api.kick_mail_sync() == 0  # not due again yet


# -- SMTP send --------------------------------------------------------------------------


class FakeSMTP:
    sent: list = []
    fail_with: Exception | None = None

    def __init__(self, host, port, timeout=None, **kw):
        self.host, self.port = host, port

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        self.user = user

    def send_message(self, msg, from_addr=None, to_addrs=None):
        if FakeSMTP.fail_with:
            raise FakeSMTP.fail_with
        FakeSMTP.sent.append((from_addr, list(to_addrs), msg.as_bytes()))
        return {}

    def noop(self):
        return 250, b""

    def quit(self):
        pass


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent = []
    FakeSMTP.fail_with = None
    monkeypatch.setattr(email_channel.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_channel.smtplib, "SMTP_SSL", FakeSMTP)
    settings.set("inbox.undo_send_seconds", 0)
    return FakeSMTP


def _deliver(ch, raw):
    return inbox.deliver_inbound(mime.to_inbound(db.one("SELECT * FROM channels WHERE id = ?", ch["id"]), raw))


def test_reply_goes_out_as_threaded_mime_with_quote(client, smtp):
    ch = make_email_channel(client, track_opens=True)
    first = _deliver(ch, raw_email(subject="Menu reprint", body="Can you quote 200 menus?", msgid="<orig@cust.test>"))
    resp = client.raw("post", "/api/files", data={"files": (__import__("io").BytesIO(b"%PDF-1.4 quote"), "quote.pdf")},
                      content_type="multipart/form-data")
    att = resp.get_json()["items"][0]
    draft = client.post("/api/drafts", {"conversation_id": first["conversation_id"], "body_html": "<p>Sure — quote attached.</p>",
                                        "bcc": "boss@shop.test", "attachment_ids": [att["id"]]})["draft"]
    client.post(f"/api/drafts/{draft['id']}/send", {})
    assert outbox.process_outbox() == 1
    (envelope_from, recipients, raw) = smtp.sent[0]
    assert envelope_from == "orders@shop.test"
    assert set(recipients) == {"ann@cust.test", "boss@shop.test"}
    msg = message_from_bytes(raw, policy=policy.default)
    assert msg["Subject"] == "Re: Menu reprint"
    assert msg["In-Reply-To"] == "<orig@cust.test>" and "<orig@cust.test>" in msg["References"]
    assert "Bcc" not in msg and msg["From"].addresses[0].display_name == "Olivia Owner"
    sent = db.one("SELECT * FROM messages WHERE direction = 'out'")
    assert msg["Message-ID"] == sent["external_id"] and sent["status"] == "sent"
    text = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    assert "Sure — quote attached." in text and "> Can you quote 200 menus?" in text
    assert "wrote:" in html and "<blockquote" in html
    assert f"/t/o/{sent['track_token']}.gif" in html
    assert [p.get_filename() for p in msg.iter_attachments()] == ["quote.pdf"]


def test_from_name_mode_channel(client, smtp):
    ch = make_email_channel(client, from_name_mode="channel")
    first = _deliver(ch, raw_email())
    d = client.post("/api/drafts", {"conversation_id": first["conversation_id"], "body_html": "<p>hi</p>"})["draft"]
    client.post(f"/api/drafts/{d['id']}/send", {})
    outbox.process_outbox()
    msg = message_from_bytes(smtp.sent[0][2], policy=policy.default)
    assert msg["From"].addresses[0].display_name == "Orders"


@pytest.mark.parametrize("error,status,attempts", [
    (smtplib.SMTPAuthenticationError(535, b"no"), "failed", 1),
    (smtplib.SMTPServerDisconnected("gone"), "scheduled", 1),
    (smtplib.SMTPResponseException(451, b"try later"), "scheduled", 1),
    (smtplib.SMTPResponseException(550, b"mailbox unavailable"), "failed", 1),
])
def test_smtp_errors_are_classified(client, smtp, error, status, attempts):
    ch = make_email_channel(client)
    first = _deliver(ch, raw_email())
    d = client.post("/api/drafts", {"conversation_id": first["conversation_id"], "body_html": "<p>hi</p>"})["draft"]
    sent = client.post(f"/api/drafts/{d['id']}/send", {})
    smtp.fail_with = error
    outbox.process_outbox()
    row = db.one("SELECT status, attempts, error FROM messages WHERE id = ?", sent["message_id"])
    assert row["status"] == status and row["attempts"] == attempts and row["error"]


def test_system_email_uses_send_simple(client, smtp):
    make_email_channel(client)
    assert mailer.send_system_email("new@person.test", "You're invited", "<p>Join us</p>") is True
    from_addr, rcpt, raw = smtp.sent[0]
    msg = message_from_bytes(raw, policy=policy.default)
    assert rcpt == ["new@person.test"] and msg["Subject"] == "You're invited" and msg["Auto-Submitted"] == "auto-generated"


# -- Twilio -----------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)
        self.content = b"img"

    def json(self):
        return self._payload


def make_sms_channel(client, type_="sms"):
    return client.post("/api/channels", {"type": type_, "address": "+16025550142", "config": {
        "account_sid": "AC123", "auth_token": "tok", "validate_signature": True}}, expect=201)["channel"]


def test_twilio_send(client, monkeypatch):
    settings.set("inbox.undo_send_seconds", 0)
    ch = make_sms_channel(client)
    posted = []
    monkeypatch.setattr(twilio.requests, "post", lambda url, data, auth, timeout: posted.append((url, data, auth))
                        or FakeResponse(201, {"sid": "SM1", "status": "queued"}))
    d = client.post("/api/drafts", {"mode": "new", "channel_id": ch["id"], "to": [{"handle": "(602) 555-0100"}],
                                    "body_html": "<p>Your banners are ready!</p>"})["draft"]
    sent = client.post(f"/api/drafts/{d['id']}/send", {})
    outbox.process_outbox()
    url, data, auth = posted[0]
    fields = dict(data)
    assert url.endswith("/Accounts/AC123/Messages.json") and auth == ("AC123", "tok")
    assert fields["To"] == "+16025550100" and fields["From"] == "+16025550142"
    assert fields["Body"] == "Your banners are ready!"
    assert fields["StatusCallback"].endswith(f"/hooks/twilio/{ch['public_key']}/status")
    row = db.one("SELECT status, external_id FROM messages WHERE id = ?", sent["message_id"])
    assert row == {"status": "sent", "external_id": "SM1"}


def test_whatsapp_prefix_and_errors(client, monkeypatch):
    settings.set("inbox.undo_send_seconds", 0)
    ch = make_sms_channel(client, "whatsapp")
    responses = [FakeResponse(503, {"message": "busy"}), FakeResponse(400, {"code": 21211, "message": "Invalid 'To'"})]
    calls = []

    def post(url, data, auth, timeout):
        calls.append(dict(data))
        return responses.pop(0)

    monkeypatch.setattr(twilio.requests, "post", post)
    d = client.post("/api/drafts", {"mode": "new", "channel_id": ch["id"], "to": "+16025550100", "body_html": "<p>hi</p>"})["draft"]
    sent = client.post(f"/api/drafts/{d['id']}/send", {})
    outbox.process_outbox()
    assert calls[0]["To"] == "whatsapp:+16025550100" and calls[0]["From"] == "whatsapp:+16025550142"
    assert db.one("SELECT status FROM messages WHERE id = ?", sent["message_id"])["status"] == "scheduled"  # 503: retry
    with db.transaction():
        db.update("messages", sent["message_id"], {"scheduled_at": now_iso()})
    outbox.process_outbox()
    row = db.one("SELECT status, error FROM messages WHERE id = ?", sent["message_id"])
    assert row["status"] == "failed" and "21211" in row["error"]


def test_twilio_connection_test(client, monkeypatch):
    monkeypatch.setattr(twilio.requests, "get", lambda url, auth, timeout: FakeResponse(200, {"friendly_name": "PPS"}))
    res = client.post("/api/channels/test", {"type": "sms", "config": {"account_sid": "AC1", "auth_token": "t"}})
    assert res == {"ok": True, "message": "Connected to Twilio account “PPS”"}
    monkeypatch.setattr(twilio.requests, "get", lambda url, auth, timeout: FakeResponse(401, {}))
    assert client.post("/api/channels/test", {"type": "sms", "config": {"account_sid": "AC1", "auth_token": "t"}})["ok"] is False


# -- API channels -----------------------------------------------------------------------


def test_inject_message_into_api_channel(client, make_user):
    ch = client.post("/api/channels", {"type": "api", "name": "POS"}, expect=201)["channel"]
    assert ch["connect"]["secret"] and ch["connect"]["form_endpoint"].endswith(ch["public_key"])
    payload = {"from": {"name": "Ann Lee", "handle": "ann@cust.test"}, "subject": "Reorder", "body_text": "Same as last time",
               "external_id": "pos-77"}
    res = client.post(f"/api/channels/{ch['id']}/messages", payload, expect=201)
    conv = inbox.get(res["conversation_id"])
    assert conv["subject"] == "Reorder"
    assert client.post(f"/api/channels/{ch['id']}/messages", payload)["duplicate"] is True
    email = make_email_channel(client)
    client.post(f"/api/channels/{email['id']}/messages", payload, expect=400)
    _, staff = make_user("staff")
    staff.post(f"/api/channels/{ch['id']}/messages", payload, expect=403)


def test_api_channel_posts_replies_signed(client, monkeypatch):
    settings.set("inbox.undo_send_seconds", 0)
    ch = client.post("/api/channels", {"type": "api", "name": "POS", "config": {"outbound_url": "https://pos.test/hook"}},
                     expect=201)["channel"]
    secret = ch["connect"]["secret"]
    res = client.post(f"/api/channels/{ch['id']}/messages", {"from": {"handle": "ann@cust.test"}, "body_text": "hi"}, expect=201)
    posted = []
    monkeypatch.setattr(api_channel.requests, "post", lambda url, data, headers, timeout: posted.append((url, data, headers))
                        or FakeResponse(200, {"id": "ext-9"}))
    d = client.post("/api/drafts", {"conversation_id": res["conversation_id"], "body_html": "<p>Done!</p>"})["draft"]
    client.post(f"/api/drafts/{d['id']}/send", {})
    outbox.process_outbox()
    url, body, headers = posted[0]
    assert url == "https://pos.test/hook"
    assert headers["X-Switchboard-Signature"] == api_channel.sign(secret, body)
    assert db.one("SELECT external_id FROM messages WHERE direction = 'out'")["external_id"] == "ext-9"


# -- chat fallback email ---------------------------------------------------------------


def test_missed_chat_replies_are_emailed_once(client, owner, monkeypatch):
    ch = client.post("/api/channels", {"type": "chat", "name": "Website chat"}, expect=201)["channel"]
    row = db.one("SELECT * FROM channels WHERE id = ?", ch["id"])
    msg = inbox.deliver_inbound(inbox.Inbound(channel=row, kind="chat", from_name="Ellie", body_text="Turnaround?",
                                              thread_key="vtok"))
    cid = msg["conversation_id"]
    long_ago = iso(now() - timedelta(minutes=30))
    with db.transaction():
        db.insert("chat_visitors", {"channel_id": ch["id"], "token": "vtok", "name": "Ellie Park", "email": "ellie@cust.test",
                                    "conversation_id": cid, "created_at": long_ago, "last_seen_at": long_ago})
        db.insert("messages", {"conversation_id": cid, "channel_id": ch["id"], "direction": "out", "kind": "chat",
                               "from_name": "Olivia Owner", "body_text": "3 business days!", "body_html": "<p>3 business days!</p>",
                               "author_id": owner["id"], "status": "sent", "sent_at": iso(now() - timedelta(minutes=12)),
                               "date": iso(now() - timedelta(minutes=12)), "created_at": iso(now() - timedelta(minutes=12))})
    sent = []
    monkeypatch.setattr(mailer, "send_system_email", lambda to, subject, html, text=None: sent.append((to, subject, html)) or True)
    assert chat_channel.email_missed_replies() == 1
    assert sent[0][0] == "ellie@cust.test" and "3 business days!" in sent[0][2]
    assert chat_channel.email_missed_replies() == 0
