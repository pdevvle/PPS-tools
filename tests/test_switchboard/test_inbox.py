"""Team inbox: delivery & threading, visibility, per-person state, actions, comments,
drafts and sending, search, counts."""

from __future__ import annotations

from datetime import timedelta

import pytest

from pps_tools.switchboard import db
from pps_tools.switchboard.services import inbox, outbox, settings
from pps_tools.switchboard.services.inbox import Inbound
from pps_tools.switchboard.util import iso, now, now_iso, token


def make_channel(type_="email", address="orders@shop.test", team_id=None, visibility="shared", owner=None, demo=True):
    with db.transaction():
        cid = db.insert("channels", {
            "type": type_, "name": f"{type_} {address}", "address": address, "visibility": visibility,
            "owner_user_id": owner, "team_id": team_id, "config_json": db.jdump({"demo": demo}),
            "public_key": token(8), "created_at": now_iso(),
        })
    return db.one("SELECT * FROM channels WHERE id = ?", cid)


def receive(channel, body="Hello", subject="Quote please", sender="ann@cust.test", name="Ann Customer", **kw):
    kind = kw.pop("kind", channel["type"])
    return inbox.deliver_inbound(Inbound(channel=channel, kind=kind, from_handle=sender, from_name=name,
                                         subject=subject, body_text=body,
                                         external_id=kw.pop("external_id", f"<{token(6)}@cust.test>"), **kw))


@pytest.fixture
def team(client, owner):
    res = client.post("/api/teams", {"name": "Desk", "member_ids": [owner["id"]]})
    return res["team"]


def test_inbound_creates_conversation_in_team_inbox(client, owner, team):
    ch = make_channel(team_id=team["id"])
    msg = receive(ch)
    cid = msg["conversation_id"]
    items = client.get(f"/api/conversations?mailbox=team:{team['id']}")["items"]
    assert [c["id"] for c in items] == [cid]
    item = items[0]
    assert item["subject"] == "Quote please"
    assert item["contact"]["display_name"] == "Ann Customer"
    assert item["unread"] is True and item["awaiting_reply"] is True
    # team conversations stay out of personal inboxes unless the team delivers to members
    assert client.get("/api/conversations?mailbox=inbox")["items"] == []
    assert client.get("/api/counts")["teams"][str(team["id"])] == {"open": 1, "unassigned": 1}


def test_shared_channel_without_team_goes_to_everyones_inbox(client, owner, make_user):
    ch = make_channel()
    agent, agent_client = make_user("agent")
    receive(ch)
    assert len(client.get("/api/conversations?mailbox=inbox")["items"]) == 1
    assert len(agent_client.get("/api/conversations?mailbox=inbox")["items"]) == 1


def test_email_threading_by_headers_and_subject(client, team):
    ch = make_channel(team_id=team["id"])
    first = receive(ch, external_id="<first@cust.test>")
    reply = receive(ch, body="Any update?", subject="Re: Quote please", external_id="<second@cust.test>",
                    in_reply_to="<first@cust.test>")
    assert reply["conversation_id"] == first["conversation_id"]
    # no headers, same sender + normalized subject within a week -> same thread
    third = receive(ch, body="Hello again", subject="RE: Fwd: quote please")
    assert third["conversation_id"] == first["conversation_id"]
    # a different subject starts a new conversation
    other = receive(ch, subject="Totally different")
    assert other["conversation_id"] != first["conversation_id"]


def test_duplicate_external_id_is_ignored(team):
    ch = make_channel(team_id=team["id"])
    assert receive(ch, external_id="<same@x>") is not None
    assert receive(ch, external_id="<same@x>") is None


def test_sms_threads_by_number(team):
    ch = make_channel("sms", "+16025550142", team_id=team["id"])
    a = receive(ch, body="hi", subject=None, sender="+16025550100", name=None, kind="sms", thread_key="+16025550100")
    b = receive(ch, body="again", subject=None, sender="+16025550100", name=None, kind="sms", thread_key="+16025550100")
    c = receive(ch, body="other", subject=None, sender="+16025550111", name=None, kind="sms", thread_key="+16025550111")
    assert a["conversation_id"] == b["conversation_id"] != c["conversation_id"]


def test_personal_channel_is_private(client, owner, make_user):
    ch = make_channel(address="me@shop.test", visibility="personal", owner=owner["id"])
    msg = receive(ch)
    _, other = make_user("agent")
    other.get(f"/api/conversations/{msg['conversation_id']}", expect=404)
    assert client.get(f"/api/conversations/{msg['conversation_id']}")["conversation"]["in_inbox"] is True


def test_staff_cannot_see_team_inbox(team, make_user):
    ch = make_channel(team_id=team["id"])
    msg = receive(ch)
    _, staff = make_user("staff")
    staff.get(f"/api/conversations/{msg['conversation_id']}", expect=404)


def test_assign_notifies_and_lands_in_their_inbox(client, owner, team, make_user):
    agent, agent_client = make_user("agent", team_ids=[team["id"]])
    cid = receive(make_channel(team_id=team["id"]))["conversation_id"]
    client.post("/api/conversations/actions", {"ids": [cid], "action": "assign", "user_ids": [agent["id"]]})
    mine = agent_client.get("/api/conversations?mailbox=assigned")["items"]
    assert [c["id"] for c in mine] == [cid]
    assert agent_client.get("/api/conversations?mailbox=inbox")["items"][0]["id"] == cid
    notes = agent_client.get("/api/notifications")["items"]
    assert notes[0]["type"] == "assigned" and notes[0]["link"] == f"/inbox/c/{cid}"
    detail = client.get(f"/api/conversations/{cid}")
    assert any(t["type"] == "event" and t["event"] == "assigned" for t in detail["timeline"])


def test_round_robin_auto_assignment(client, owner, make_user):
    a, _ = make_user("agent")
    b, _ = make_user("agent")
    team = client.post("/api/teams", {"name": "RR", "member_ids": [a["id"], b["id"]], "assignment_mode": "round_robin"})["team"]
    ch = make_channel(team_id=team["id"])
    got = []
    for i in range(4):
        cid = receive(ch, subject=f"Job {i}", sender=f"c{i}@x.test")["conversation_id"]
        got.append(inbox.assignees(cid)[0])
    assert got == [a["id"], b["id"], a["id"], b["id"]]


def test_close_reopen_and_new_message_reopens(client, owner, team):
    ch = make_channel(team_id=team["id"])
    cid = receive(ch, external_id="<a@x>")["conversation_id"]
    client.post("/api/conversations/actions", {"ids": [cid], "action": "assign", "user_ids": [owner["id"]]})
    client.post("/api/conversations/actions", {"ids": [cid], "action": "close"})
    assert client.get("/api/conversations?mailbox=inbox")["items"] == []
    assert [c["id"] for c in client.get("/api/conversations?mailbox=closed")["items"]] == [cid]
    receive(ch, subject="Re: Quote please", in_reply_to="<a@x>")
    conv = client.get(f"/api/conversations/{cid}")["conversation"]
    assert conv["status"] == "open" and conv["in_inbox"] is True  # assignee gets it back


def test_star_read_unread_archive(client, owner):
    cid = receive(make_channel())["conversation_id"]
    client.post("/api/conversations/actions", {"ids": [cid], "action": "star"})
    assert client.get("/api/conversations?mailbox=starred")["items"][0]["id"] == cid
    client.post(f"/api/conversations/{cid}/read")
    assert client.get("/api/conversations?mailbox=inbox")["items"][0]["unread"] is False
    client.post("/api/conversations/actions", {"ids": [cid], "action": "unread"})
    assert client.get("/api/counts")["inbox_unread"] == 1
    client.post("/api/conversations/actions", {"ids": [cid], "action": "archive"})
    assert client.get("/api/conversations?mailbox=inbox")["items"] == []
    assert client.get(f"/api/conversations/{cid}")["conversation"]["status"] == "open"


def test_snooze_and_wake(client, owner):
    cid = receive(make_channel())["conversation_id"]
    client.post("/api/conversations/actions", {"ids": [cid], "action": "snooze", "until": iso(now() + timedelta(hours=1))})
    assert client.get("/api/conversations?mailbox=inbox")["items"] == []
    assert client.get("/api/conversations?mailbox=snoozed")["items"][0]["id"] == cid
    with db.transaction():
        db.update("conversations", cid, {"snoozed_until": iso(now() - timedelta(minutes=1))})
    assert inbox.wake_snoozed() == 1
    assert client.get("/api/conversations?mailbox=inbox")["items"][0]["id"] == cid
    assert client.get("/api/notifications")["items"][0]["type"] == "snooze"


def test_snooze_rejects_past(client):
    cid = receive(make_channel())["conversation_id"]
    client.post("/api/conversations/actions", {"ids": [cid], "action": "snooze", "until": iso(now() - timedelta(hours=1))},
                expect=400)


def test_spam_and_block_sender(client):
    ch = make_channel()
    cid = receive(ch, sender="bad@spam.test")["conversation_id"]
    client.post("/api/conversations/actions", {"ids": [cid], "action": "spam", "block": True})
    assert client.get("/api/conversations?mailbox=spam")["items"][0]["id"] == cid
    later = receive(ch, sender="bad@spam.test", subject="More spam")
    assert inbox.get(later["conversation_id"])["is_spam"] == 1


def test_trash_restore_delete_forever(client):
    cid = receive(make_channel())["conversation_id"]
    client.post("/api/conversations/actions", {"ids": [cid], "action": "delete_forever"}, expect=400)
    client.post("/api/conversations/actions", {"ids": [cid], "action": "trash"})
    assert client.get("/api/conversations?mailbox=trash")["items"][0]["id"] == cid
    client.post("/api/conversations/actions", {"ids": [cid], "action": "restore"})
    assert client.get("/api/conversations?mailbox=trash")["items"] == []
    client.post("/api/conversations/actions", {"ids": [cid], "action": "trash"})
    client.post("/api/conversations/actions", {"ids": [cid], "action": "delete_forever"})
    client.get(f"/api/conversations/{cid}", expect=404)


def test_labels_and_label_mailbox(client):
    cid = receive(make_channel())["conversation_id"]
    label = client.post("/api/labels", {"name": "Wholesale", "color": "#123456"})["label"]
    client.post("/api/conversations/actions", {"ids": [cid], "action": "label", "add": [label["id"]]})
    assert client.get(f"/api/conversations?mailbox=label:{label['id']}")["items"][0]["label_ids"] == [label["id"]]
    assert client.get("/api/counts")["labels"][str(label["id"])] == 1


def test_personal_labels_are_private(client, make_user):
    _, other = make_user("agent")
    mine = other.post("/api/labels", {"name": "Mine", "visibility": "personal"})["label"]
    assert all(lbl["id"] != mine["id"] for lbl in client.get("/api/labels")["items"])


def test_comment_mentions_notify_and_follow(client, owner, team, make_user):
    agent, agent_client = make_user("agent")
    cid = receive(make_channel(team_id=team["id"]))["conversation_id"]
    html = f'<p>Can you take this <span data-mention="{agent["id"]}">@x</span>? <script>alert(1)</script></p>'
    comment = client.post(f"/api/conversations/{cid}/comments", {"body": html})["comment"]
    assert "<script" not in comment["body"]
    note = agent_client.get("/api/notifications")["items"][0]
    assert note["type"] == "mention"
    # mentioned agent (not on the team) can now open it and has it in their inbox
    assert agent_client.get(f"/api/conversations/{cid}")["conversation"]["in_inbox"] is True


def test_staff_mentioned_in_internal_discussion_can_read_it(client, make_user):
    staff, staff_client = make_user("staff")
    conv = client.post("/api/conversations", {"subject": "Press 2", "user_ids": [staff["id"]],
                                              "body": "<p>Thursday works?</p>"})["conversation"]
    detail = staff_client.get(f"/api/conversations/{conv['id']}")
    assert [t["type"] for t in detail["timeline"] if t["type"] == "comment"] == ["comment"]


def test_edit_and_delete_own_comment_only(client, owner, make_user):
    cid = receive(make_channel())["conversation_id"]
    comment = client.post(f"/api/conversations/{cid}/comments", {"body": "<p>first</p>"})["comment"]
    _, other = make_user("agent")
    other.patch(f"/api/comments/{comment['id']}", {"body": "<p>hijack</p>"}, expect=403)
    client.patch(f"/api/comments/{comment['id']}", {"body": "<p>edited</p>"})
    client.delete(f"/api/comments/{comment['id']}")
    timeline = client.get(f"/api/conversations/{cid}")["timeline"]
    assert not [t for t in timeline if t["type"] == "comment"]


def test_reply_draft_send_undo_and_outbox(client, owner):
    settings.set("inbox.undo_send_seconds", 30)
    ch = make_channel()
    cid = receive(ch, external_id="<orig@cust.test>")["conversation_id"]
    draft = client.post("/api/drafts", {"conversation_id": cid, "mode": "reply", "body_html": "<p>Sure thing!</p>"})["draft"]
    assert draft["to"] == [{"name": "Ann Customer", "handle": "ann@cust.test"}]
    assert draft["subject"] == "Re: Quote please"
    sent = client.post(f"/api/drafts/{draft['id']}/send", {})
    assert sent["status"] == "scheduled"
    # undo
    restored = client.post(f"/api/messages/{sent['message_id']}/cancel")["draft"]
    assert restored["conversation_id"] == cid and "Sure thing" in restored["body_html"]
    sent = client.post(f"/api/drafts/{restored['id']}/send", {})
    # not due yet
    assert outbox.process_outbox() == 0
    with db.transaction():
        db.update("messages", sent["message_id"], {"scheduled_at": iso(now() - timedelta(seconds=1))})
    assert outbox.process_outbox() == 1
    msg = db.one("SELECT * FROM messages WHERE id = ?", sent["message_id"])
    assert msg["status"] == "sent" and msg["in_reply_to"] == "<orig@cust.test>"
    assert msg["external_id"].startswith("<sb.")
    conv = inbox.get(cid)
    assert conv["first_response_at"] and conv["last_outbound_at"]
    client.post(f"/api/messages/{sent['message_id']}/cancel", expect=400)


def test_new_conversation_compose_and_send_later(client, owner):
    ch = make_channel()
    draft = client.post("/api/drafts", {"mode": "new", "channel_id": ch["id"], "to": "Bob <bob@x.test>",
                                        "subject": "Your order", "body_html": "<p>Ready!</p>"})["draft"]
    when = iso(now() + timedelta(days=1))
    sent = client.post(f"/api/drafts/{draft['id']}/send", {"send_at": when})
    assert client.get("/api/conversations?mailbox=scheduled")["items"][0]["id"] == sent["conversation_id"]
    # cancelling a brand-new conversation's only message removes the conversation
    restored = client.post(f"/api/messages/{sent['message_id']}/cancel")["draft"]
    assert restored["conversation_id"] is None
    client.get(f"/api/conversations/{sent['conversation_id']}", expect=404)
    assert client.get("/api/drafts")["items"][0]["id"] == restored["id"]


def test_send_validation(client):
    ch = make_channel()
    d = client.post("/api/drafts", {"mode": "new", "channel_id": ch["id"], "to": "not-an-email", "body_html": "<p>x</p>"})["draft"]
    assert client.post(f"/api/drafts/{d['id']}/send", {}, expect=400)["error"]["code"] in ("invalid_recipient", "no_recipients")
    d2 = client.post("/api/drafts", {"mode": "new", "channel_id": ch["id"], "to": "a@b.test", "body_html": "<p></p>"})["draft"]
    assert client.post(f"/api/drafts/{d2['id']}/send", {}, expect=400)["error"]["code"] == "empty"


def test_shared_draft_coediting(client, owner, team, make_user):
    agent, agent_client = make_user("agent", team_ids=[team["id"]])
    cid = receive(make_channel(team_id=team["id"]))["conversation_id"]
    d = client.post("/api/drafts", {"conversation_id": cid, "body_html": "<p>v1</p>"})["draft"]
    edited = agent_client.patch(f"/api/drafts/{d['id']}", {"body_html": "<p>v2 by agent</p>"})["draft"]
    assert edited["version"] == 2 and edited["updated_by"] == agent["id"]
    assert agent_client.get(f"/api/conversations/{cid}")["drafts"][0]["body_html"] == "<p>v2 by agent</p>"
    private = client.post("/api/drafts", {"conversation_id": cid, "body_html": "<p>secret</p>", "is_shared": False})["draft"]
    agent_client.patch(f"/api/drafts/{private['id']}", {"body_html": "x"}, expect=404)


def test_failed_send_notifies_author(client, owner, monkeypatch):
    from pps_tools.switchboard import channels
    from pps_tools.switchboard.channels import SendError

    ch = make_channel(demo=False)

    class Broken(channels.Adapter):
        type = "email"

        def send(self, channel, message, attachments, ctx):
            raise SendError("SMTP said no")

    monkeypatch.setitem(channels.ADAPTERS, "email", Broken())
    settings.set("inbox.undo_send_seconds", 0)
    d = client.post("/api/drafts", {"mode": "new", "channel_id": ch["id"], "to": "x@y.test", "subject": "s",
                                    "body_html": "<p>x</p>"})["draft"]
    sent = client.post(f"/api/drafts/{d['id']}/send", {})
    outbox.process_outbox()
    assert db.one("SELECT status, error FROM messages WHERE id = ?", sent["message_id"]) == {"status": "failed", "error": "SMTP said no"}
    assert client.get("/api/notifications")["items"][0]["title"].startswith("Couldn't send")
    client.post(f"/api/messages/{sent['message_id']}/retry")


def test_merge(client):
    ch = make_channel()
    a = receive(ch, subject="Part one", sender="m@x.test")["conversation_id"]
    b = receive(ch, subject="Part two", sender="n@x.test")["conversation_id"]
    client.post(f"/api/conversations/{b}/comments", {"body": "<p>note</p>"})
    client.post("/api/conversations/actions", {"ids": [b], "action": "merge", "target_id": a})
    detail = client.get(f"/api/conversations/{a}")
    assert detail["conversation"]["message_count"] == 2
    assert len([t for t in detail["timeline"] if t["type"] == "comment"]) == 1
    assert all(c["id"] != b for c in client.get("/api/conversations?mailbox=all")["items"])


def test_reminder_no_reply(client, owner):
    ch = make_channel()
    cid = receive(ch, external_id="<r1@x>")["conversation_id"]
    client.post("/api/conversations/actions", {"ids": [cid], "action": "archive"})
    client.post(f"/api/conversations/{cid}/reminders", {"remind_at": iso(now() + timedelta(hours=1)), "condition": "no_reply"})
    with db.transaction():
        db.execute("UPDATE reminders SET remind_at = ?", iso(now() - timedelta(minutes=1)))
    assert inbox.process_reminders() == 1
    assert client.get("/api/conversations?mailbox=inbox")["items"][0]["id"] == cid
    # with a reply in between, a no_reply reminder stays quiet
    client.post(f"/api/conversations/{cid}/reminders", {"remind_at": iso(now() + timedelta(hours=1)), "condition": "no_reply"})
    with db.transaction():
        db.execute("UPDATE reminders SET created_at = ? WHERE done_at IS NULL", iso(now() - timedelta(hours=2)))
    receive(ch, subject="Re: Quote please", in_reply_to="<r1@x>")
    with db.transaction():
        db.execute("UPDATE reminders SET remind_at = ? WHERE done_at IS NULL", iso(now() - timedelta(minutes=1)))
    assert inbox.process_reminders() == 0


def test_search_operators_and_text(client, owner):
    ch = make_channel()
    a = receive(ch, subject="Banner order", body="Need vinyl banners for the fair", sender="dana@league.test", name="Dana")["conversation_id"]
    b = receive(ch, subject="Postcards", body="1000 postcards matte", sender="eli@shop.test", name="Eli")["conversation_id"]
    label = client.post("/api/labels", {"name": "Rush"})["label"]
    client.post("/api/conversations/actions", {"ids": [b], "action": "label", "add": [label["id"]]})

    def ids(q):
        return [c["id"] for c in client.get("/api/conversations", query_string={"q": q, "mailbox": "inbox"})["items"]]

    assert ids("vinyl") == [a]
    assert ids("postcar") == [b]                     # prefix match
    assert ids("from:dana") == [a]
    assert ids("label:rush") == [b]
    assert ids("is:unassigned matte") == [b]
    assert ids('subject:"Banner order"') == [a]
    assert set(ids("is:open")) == {a, b}
    assert ids("nothingmatches") == []


def test_canned_response_render(client, owner):
    cid = receive(make_channel(), name="Lena Ortiz")["conversation_id"]
    resp = client.post("/api/responses", {"title": "Hi", "shortcut": "/hi", "body_html": "<p>Hi {{contact.first_name}}, I'm {{user.first_name}} <script>x</script></p>"})["response"]
    assert resp["shortcut"] == "hi"
    out = client.post(f"/api/responses/{resp['id']}/render", {"conversation_id": cid})
    assert out["body_html"] == "<p>Hi Lena, I'm Olivia </p>"
    assert client.get("/api/responses", query_string={"q": "hi"})["items"][0]["usage_count"] == 1


def test_bootstrap_includes_labels_and_channels(client):
    make_channel()
    boot = client.get("/api/bootstrap")
    assert {lbl["name"] for lbl in boot["labels"]} >= {"Quote request", "Rush"}
    assert boot["channels"][0]["address"] == "orders@shop.test"
    assert "config_json" not in boot["channels"][0]


def test_global_search_finds_conversation(client):
    receive(make_channel(), subject="Wedding invitations", body="We loved them")
    items = client.get("/api/search", query_string={"q": "wedding"})["items"]
    assert items and items[0]["type"] == "conversation" and items[0]["url"].startswith("/inbox/c/")


def test_badges_count_unread_inbox(client):
    receive(make_channel())
    assert client.get("/api/badges")["badges"]["inbox"] == 1


def test_team_conversations_hidden_from_non_members(client, owner, make_user):
    team = client.post("/api/teams", {"name": "Production", "member_ids": [owner["id"]]})["team"]
    ch = make_channel(team_id=team["id"])
    cid = receive(ch)["conversation_id"]
    outsider, outsider_client = make_user("agent")
    outsider_client.get(f"/api/conversations/{cid}", expect=404)
    outsider_client.post("/api/conversations/actions", {"ids": [cid], "action": "close"}, expect=404)
    assert outsider_client.get("/api/conversations?mailbox=all")["items"] == []
    # admins see every team
    _, admin_client = make_user("admin")
    assert admin_client.get(f"/api/conversations/{cid}")["conversation"]["id"] == cid


def test_reply_all_excludes_our_own_addresses(client):
    ch = make_channel(address="orders@shop.test")
    make_channel(address="billing@shop.test")
    msg = inbox.deliver_inbound(Inbound(
        channel=ch, kind="email", from_handle="ann@cust.test", from_name="Ann", subject="Order",
        body_text="hi", to=[{"name": None, "handle": "orders@shop.test"}],
        cc=[{"name": "Bob", "handle": "bob@cust.test"}, {"name": None, "handle": "billing@shop.test"}],
        external_id="<ra@x>",
    ))
    d = client.post("/api/drafts", {"conversation_id": msg["conversation_id"], "mode": "reply_all"})["draft"]
    assert [p["handle"] for p in d["to"]] == ["ann@cust.test"]
    assert [p["handle"] for p in d["cc"]] == ["bob@cust.test"]


def test_reply_uses_reply_to_header(client):
    ch = make_channel()
    msg = inbox.deliver_inbound(Inbound(channel=ch, kind="email", from_handle="noreply@shop.example",
                                        reply_to="Help <help@shop.example>", subject="Order", body_text="x",
                                        external_id="<rt@x>"))
    d = client.post("/api/drafts", {"conversation_id": msg["conversation_id"]})["draft"]
    assert d["to"] == [{"name": "Help", "handle": "help@shop.example"}]


def test_forward_copies_attachments_and_quotes(client):
    ch = make_channel()
    msg = inbox.deliver_inbound(Inbound(channel=ch, kind="email", from_handle="ann@cust.test", subject="Art",
                                        body_text="see file", external_id="<fw@x>",
                                        attachments=[{"filename": "logo.pdf", "content_type": "application/pdf", "data": b"%PDF"}]))
    d = client.post("/api/drafts", {"conversation_id": msg["conversation_id"], "mode": "forward",
                                    "reply_to_message_id": msg["id"]})["draft"]
    assert d["subject"] == "Fwd: Art"
    assert d["to"] == []
    assert "Forwarded message" in d["body_html"]
    assert [a["filename"] for a in d["attachments"]] == ["logo.pdf"]


def test_drafts_mailbox_and_new_drafts(client):
    ch = make_channel()
    cid = receive(ch)["conversation_id"]
    client.post("/api/drafts", {"conversation_id": cid, "body_html": "<p>wip</p>"})
    client.post("/api/drafts", {"mode": "new", "channel_id": ch["id"], "to": "z@z.test", "body_html": "<p>new</p>"})
    assert [c["id"] for c in client.get("/api/conversations?mailbox=drafts")["items"]] == [cid]
    assert len(client.get("/api/drafts")["items"]) == 1
    assert client.get("/api/counts")["drafts"] == 2


def test_contact_history(client):
    ch = make_channel()
    a = receive(ch, subject="First order", sender="repeat@cust.test")["conversation_id"]
    b = receive(ch, subject="Second order", sender="repeat@cust.test")["conversation_id"]
    hist = client.get(f"/api/conversations/{b}/history")["items"]
    assert [c["id"] for c in hist] == [a]


def test_cannot_send_from_someone_elses_personal_channel(client, owner, make_user):
    agent, agent_client = make_user("agent")
    ch = make_channel(address="olivia@shop.test", visibility="personal", owner=owner["id"])
    agent_client.post("/api/drafts", {"mode": "new", "channel_id": ch["id"], "to": "x@y.test"}, expect=403)


def test_internal_discussion_lifecycle(client, make_user):
    agent, agent_client = make_user("agent")
    conv = client.post("/api/conversations", {"subject": "Plan the gala job", "user_ids": [agent["id"]],
                                              "body": "<p>Thoughts?</p>"})["conversation"]
    assert conv["channel"] is None
    assert agent_client.get("/api/conversations?mailbox=inbox")["items"][0]["id"] == conv["id"]
    client.post("/api/conversations/actions", {"ids": [conv["id"]], "action": "close"})
    assert agent_client.get("/api/conversations?mailbox=inbox")["items"] == []


def test_label_counts_ignore_closed_and_respect_privacy(client, make_user):
    ch = make_channel()
    a = receive(ch, subject="Open one", sender="a@x.test")["conversation_id"]
    b = receive(ch, subject="Closed one", sender="b@x.test")["conversation_id"]
    label = client.post("/api/labels", {"name": "Wholesale"})["label"]
    client.post("/api/conversations/actions", {"ids": [a, b], "action": "label", "add": [label["id"]]})
    client.post("/api/conversations/actions", {"ids": [b], "action": "close"})
    assert client.get("/api/counts")["labels"][str(label["id"])] == 1
    assert len(client.get(f"/api/conversations?mailbox=label:{label['id']}&include_closed=1")["items"]) == 2
    _, other = make_user("agent")
    mine = other.post("/api/labels", {"name": "Secret", "visibility": "personal"})["label"]
    other.post("/api/conversations/actions", {"ids": [a], "action": "label", "add": [mine["id"]]})
    assert mine["id"] not in client.get(f"/api/conversations/{a}")["conversation"]["label_ids"]


def test_parse_address_list_handles_phones_and_quoted_names():
    from pps_tools.switchboard.util import parse_address_list

    assert parse_address_list("(602) 555-0100") == [{"name": None, "handle": "(602) 555-0100"}]
    assert parse_address_list('"Lee, Jo" <jo@z.test>; ann@x.test') == [
        {"name": "Lee, Jo", "handle": "jo@z.test"}, {"name": None, "handle": "ann@x.test"},
    ]
