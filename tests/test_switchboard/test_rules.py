"""Automation rules: CRUD/validation, triggers, conditions, actions, loop protection."""

from __future__ import annotations

import pytest

from pps_tools.switchboard import db
from pps_tools.switchboard.services import inbox, outbox, settings
from pps_tools.switchboard.services import rules as engine
from pps_tools.switchboard.services.inbox import Inbound
from pps_tools.switchboard.util import token

ALL_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@pytest.fixture
def ch(client):
    created = client.post("/api/channels", {"type": "email", "address": "orders@shop.test", "config": {"demo": True}},
                          expect=201)["channel"]
    return db.one("SELECT * FROM channels WHERE id = ?", created["id"])


def receive(ch, subject="Hello", body="Hi there", sender="ann@cust.test", name="Ann Lee", **kw):
    return inbox.deliver_inbound(Inbound(channel=ch, kind=ch["type"], from_handle=sender, from_name=name, subject=subject,
                                         body_text=body, external_id=kw.pop("external_id", f"<{token(6)}@x>"), **kw))


def label_id(client, name):
    return next(lbl["id"] for lbl in client.get("/api/labels")["items"] if lbl["name"] == name)


def make_rule(client, **data):
    payload = {"name": "Rule", "trigger": "incoming", "conditions": [], "actions": [], **data}
    return client.post("/api/rules", payload, expect=201)["rule"]


def labels_of(cid):
    return set(db.column("SELECT l.name FROM conversation_labels cl JOIN labels l ON l.id = cl.label_id WHERE cl.conversation_id = ?", cid))


# -- CRUD -------------------------------------------------------------------------------


def test_crud_validation_and_permissions(client, make_user):
    rush = label_id(client, "Rush")
    bad = [
        {"name": "x", "actions": []},
        {"name": "x", "actions": [{"type": "explode"}]},
        {"name": "x", "conditions": [{"field": "mood", "op": "is", "value": 1}], "actions": [{"type": "close"}]},
        {"name": "x", "conditions": [{"field": "subject", "op": "has", "value": "a"}], "actions": [{"type": "close"}]},
        {"name": "x", "conditions": [{"field": "subject", "op": "matches", "value": "(unclosed"}], "actions": [{"type": "close"}]},
        {"name": "x", "actions": [{"type": "webhook", "url": "ftp://nope"}]},
        {"name": "x", "actions": [{"type": "add_label", "label_ids": []}]},
        {"name": "", "actions": [{"type": "close"}]},
        {"name": "x", "trigger": "sometimes", "actions": [{"type": "close"}]},
    ]
    for payload in bad:
        client.post("/api/rules", payload, expect=400)
    rule = make_rule(client, name="Rush", conditions=[{"field": "subject", "op": "contains", "value": "rush"}],
                     actions=[{"type": "add_label", "label_ids": [rush]}, {"type": "priority", "value": "high"}])
    assert rule["is_active"] is True and rule["match"] == "all"
    listed = client.get("/api/rules")["items"]
    assert listed[0]["summary"] == ["Add label Rush", "Set priority to high"]
    client.patch(f"/api/rules/{rule['id']}", {"is_active": False, "name": "Rush jobs"})
    assert client.get(f"/api/rules/{rule['id']}")["rule"]["name"] == "Rush jobs"
    _, agent = make_user("agent")
    agent.get("/api/rules", expect=403)
    agent.post("/api/rules", {"name": "x", "actions": [{"type": "close"}]}, expect=403)
    client.delete(f"/api/rules/{rule['id']}")
    assert client.get("/api/rules")["items"] == []


def test_options_and_reorder(client):
    a = make_rule(client, name="A", actions=[{"type": "close"}])
    b = make_rule(client, name="B", actions=[{"type": "close"}])
    opts = client.get("/api/rules/options")
    assert "auto_reply" in opts["actions"] and "contains" in opts["fields"]["subject"]
    assert any(lbl["name"] == "Rush" for lbl in opts["labels"])
    res = client.post("/api/rules/reorder", {"ids": [b["id"], a["id"]]})
    assert [r["name"] for r in res["items"]] == ["B", "A"]


# -- triggers & conditions --------------------------------------------------------------


def test_incoming_rule_labels_and_sets_priority(client, ch):
    rush = label_id(client, "Rush")
    make_rule(client, name="Rush", match="any",
              conditions=[{"field": "subject", "op": "contains", "value": "rush, asap"},
                          {"field": "body", "op": "contains", "value": "by tomorrow"}],
              actions=[{"type": "add_label", "label_ids": [rush]}, {"type": "priority", "value": "high"}])
    hit = receive(ch, subject="ASAP banners")["conversation_id"]
    also = receive(ch, subject="Banners", body="need them by tomorrow", sender="b@x.test")["conversation_id"]
    miss = receive(ch, subject="Postcards", body="whenever", sender="c@x.test")["conversation_id"]
    assert labels_of(hit) == {"Rush"} and inbox.get(hit)["priority"] == "high"
    assert labels_of(also) == {"Rush"}
    assert labels_of(miss) == set() and inbox.get(miss)["priority"] == "normal"
    timeline = client.get(f"/api/conversations/{hit}")["timeline"]
    applied = [t for t in timeline if t["type"] == "event" and t["event"] == "rule_applied"]
    assert applied and applied[0]["data"]["name"] == "Rush" and applied[0]["data"]["actions"] == ["add_label", "priority"]
    assert client.get("/api/rules")["items"][0]["run_count"] == 2


def test_match_all_and_text_operators(client, ch):
    vendor = label_id(client, "Vendor")
    make_rule(client, conditions=[{"field": "from", "op": "ends_with", "value": "@mohawk.test"},
                                  {"field": "subject", "op": "not_contains", "value": "invoice"}],
              actions=[{"type": "add_label", "label_ids": [vendor]}])
    a = receive(ch, subject="New stock list", sender="steve@mohawk.test")["conversation_id"]
    b = receive(ch, subject="Invoice 42", sender="billing@mohawk.test")["conversation_id"]
    c = receive(ch, subject="New stock list", sender="steve@other.test")["conversation_id"]
    assert labels_of(a) == {"Vendor"} and labels_of(b) == set() and labels_of(c) == set()


def test_new_conversation_trigger_only_fires_once(client, ch):
    quote = label_id(client, "Quote request")
    make_rule(client, trigger="new_conversation", actions=[{"type": "add_label", "label_ids": [quote]}])
    first = receive(ch, external_id="<t1@x>")
    cid = first["conversation_id"]
    db.execute("DELETE FROM conversation_labels")
    receive(ch, subject="Re: Hello", in_reply_to="<t1@x>")
    assert labels_of(cid) == set()


def test_channel_type_condition_and_move_team(client, ch):
    office = client.get("/api/teams")["items"][0]
    sms = client.post("/api/channels", {"type": "sms", "address": "+16025550142", "config": {"demo": True}}, expect=201)["channel"]
    make_rule(client, conditions=[{"field": "channel_type", "op": "is", "value": ["sms"]}],
              actions=[{"type": "move_team", "team_id": office["id"]}])
    sms_row = db.one("SELECT * FROM channels WHERE id = ?", sms["id"])
    texted = inbox.deliver_inbound(Inbound(channel=sms_row, kind="sms", from_handle="+16025550100", body_text="hi",
                                           thread_key="+16025550100"))["conversation_id"]
    mailed = receive(ch)["conversation_id"]
    assert inbox.get(texted)["team_id"] == office["id"] and inbox.get(mailed)["team_id"] is None


def test_business_hours_condition(client, ch):
    rush = label_id(client, "Rush")
    make_rule(client, conditions=[{"field": "business_hours", "op": "is", "value": "outside"}],
              actions=[{"type": "add_label", "label_ids": [rush]}])
    settings.set("org.business_hours", {d: [["00:00", "24:00"]] for d in ALL_DAYS})
    inside = receive(ch, sender="a@x.test")["conversation_id"]
    settings.set("org.business_hours", {d: [] for d in ALL_DAYS})
    outside = receive(ch, sender="b@x.test")["conversation_id"]
    assert labels_of(inside) == set() and labels_of(outside) == {"Rush"}


def test_label_and_assigned_conditions(client, ch, owner):
    rush, quote = label_id(client, "Rush"), label_id(client, "Quote request")
    make_rule(client, name="first", actions=[{"type": "add_label", "label_ids": [quote]}],
              conditions=[{"field": "subject", "op": "contains", "value": "quote"}])
    make_rule(client, name="second", conditions=[{"field": "label", "op": "has", "value": [quote]},
                                                 {"field": "assigned", "op": "is", "value": False}],
              actions=[{"type": "add_label", "label_ids": [rush]}])
    cid = receive(ch, subject="Quote for flyers")["conversation_id"]
    assert labels_of(cid) == {"Quote request", "Rush"}  # later rules see earlier rules' changes


# -- actions --------------------------------------------------------------------------


def test_stop_processing(client, ch):
    rush, quote = label_id(client, "Rush"), label_id(client, "Quote request")
    make_rule(client, name="first", actions=[{"type": "add_label", "label_ids": [rush]}, {"type": "stop"}])
    make_rule(client, name="second", actions=[{"type": "add_label", "label_ids": [quote]}])
    cid = receive(ch)["conversation_id"]
    assert labels_of(cid) == {"Rush"}


def test_assign_round_robin_and_users(client, ch, make_user):
    a, _ = make_user("agent")
    b, _ = make_user("agent")
    team = client.post("/api/teams", {"name": "Desk", "member_ids": [a["id"], b["id"]]})["team"]
    make_rule(client, actions=[{"type": "assign", "mode": "round_robin", "team_id": team["id"]}])
    got = [inbox.assignees(receive(ch, subject=f"Job {i}", sender=f"c{i}@x.test")["conversation_id"]) for i in range(3)]
    assert got == [[a["id"]], [b["id"]], [a["id"]]]
    note = client.get("/api/notifications")  # the owner wasn't assigned
    assert all(n["type"] != "assigned" for n in note["items"])


def test_auto_reply_once_per_contact_and_never_to_automated_mail(client, ch, owner):
    settings.set("inbox.undo_send_seconds", 0)
    response = client.post("/api/responses", {"title": "Away", "subject": "We got your message",
                                              "body_html": "<p>Hi {{contact.first_name}}, we're closed.</p>"})["response"]
    make_rule(client, trigger="new_conversation", actions=[{"type": "auto_reply", "response_id": response["id"]}])
    cid = receive(ch, subject="Need cards", name="Lena Ortiz", sender="lena@cafe.test")["conversation_id"]
    replies = db.query("SELECT * FROM messages WHERE conversation_id = ? AND direction = 'out'", cid)
    assert len(replies) == 1
    reply = replies[0]
    assert reply["is_auto"] == 1 and reply["subject"] == "We got your message"
    assert "Hi Lena, we're closed." in reply["body_html"]
    assert db.jload(reply["to_json"]) == [{"name": "Lena Ortiz", "handle": "lena@cafe.test"}]
    # sending as the rule's creator doesn't make them follow the conversation
    assert inbox.user_state(cid, owner["id"])["following"] == 0
    outbox.process_outbox()
    # same contact, new conversation within a day: no second auto-reply
    other = receive(ch, subject="Another thing", sender="lena@cafe.test", name="Lena Ortiz")["conversation_id"]
    assert db.scalar("SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND direction = 'out'", other) == 0
    # automated mail (another auto-responder) never gets one
    bot = receive(ch, subject="Out of office", sender="ooo@vendor.test", is_auto=True)["conversation_id"]
    assert db.scalar("SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND direction = 'out'", bot) == 0
    runs = client.get(f"/api/rules/{client.get('/api/rules')['items'][0]['id']}/runs")["items"]
    assert runs[0]["actions"][0]["ok"] is False and "automated" in runs[0]["actions"][0]["detail"]


def test_outgoing_trigger_skips_auto_messages(client, ch):
    billing = label_id(client, "Billing")
    make_rule(client, trigger="outgoing", conditions=[{"field": "body", "op": "contains", "value": "invoice"}],
              actions=[{"type": "add_label", "label_ids": [billing]}])
    cid = receive(ch)["conversation_id"]
    d = client.post("/api/drafts", {"conversation_id": cid, "body_html": "<p>Your invoice is attached.</p>"})["draft"]
    client.post(f"/api/drafts/{d['id']}/send", {})
    assert labels_of(cid) == {"Billing"}


def test_comment_rule_does_not_loop(client, ch):
    make_rule(client, trigger="comment", conditions=[{"field": "body", "op": "contains", "value": "proof"}],
              actions=[{"type": "add_comment", "body_html": "<p>Remember: proofs need a signed approval.</p>"}])
    cid = receive(ch)["conversation_id"]
    client.post(f"/api/conversations/{cid}/comments", {"body": "<p>Sending the proof now</p>"})
    comments = [t for t in client.get(f"/api/conversations/{cid}")["timeline"] if t["type"] == "comment"]
    assert len(comments) == 2 and "signed approval" in comments[1]["body"]  # the rule's own comment didn't re-trigger it


def test_notify_snooze_forward_and_webhook(client, ch, make_user, monkeypatch):
    settings.set("inbox.undo_send_seconds", 0)
    casey, casey_client = make_user("manager", name="Casey")
    posted = []
    monkeypatch.setattr(engine.requests, "post", lambda url, json, timeout, headers: posted.append((url, json)))

    class InlineThread:
        def __init__(self, target, name=None, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(engine.threading, "Thread", InlineThread)
    make_rule(client, actions=[
        {"type": "notify", "user_ids": [casey["id"]], "note": "Big customer"},
        {"type": "forward", "to": "accounting@shop.test"},
        {"type": "webhook", "url": "https://hooks.test/in"},
        {"type": "snooze", "minutes": 120},
    ])
    cid = receive(ch, subject="Invoice question")["conversation_id"]
    assert casey_client.get("/api/notifications")["items"][0]["body"] == "Big customer"
    fwd = db.one("SELECT * FROM messages WHERE conversation_id = ? AND direction = 'out'", cid)
    assert db.jload(fwd["to_json"])[0]["handle"] == "accounting@shop.test" and fwd["subject"].startswith("Fwd: ")
    assert posted[0][0] == "https://hooks.test/in" and posted[0][1]["conversation"]["id"] == cid
    assert inbox.get(cid)["snoozed_until"] is not None


def test_rule_runs_once_per_message(client, ch):
    make_rule(client, actions=[{"type": "priority", "value": "urgent"}])
    msg = receive(ch)
    engine.on_message_received({"message_id": msg["id"], "conversation_id": msg["conversation_id"], "is_new_conversation": True})
    assert db.scalar("SELECT COUNT(*) FROM rule_runs") == 1


def test_spam_conversations_are_skipped(client, ch):
    make_rule(client, actions=[{"type": "priority", "value": "urgent"}])
    cid = receive(ch, is_spam=True)["conversation_id"]
    assert inbox.get(cid)["priority"] == "normal"


# -- dry runs & bulk ------------------------------------------------------------------


def test_dry_run_reports_conditions_and_actions(client, ch):
    rush = label_id(client, "Rush")
    rule = make_rule(client, is_active=False, conditions=[{"field": "subject", "op": "contains", "value": "rush"},
                                                         {"field": "has_attachment", "op": "is", "value": True}],
                     actions=[{"type": "add_label", "label_ids": [rush]}])
    cid = receive(ch, subject="RUSH order")["conversation_id"]
    res = client.post(f"/api/rules/{rule['id']}/test", {"conversation_id": cid})
    assert res["matched"] is False
    assert [c["matched"] for c in res["conditions"]] == [True, False]
    assert res["actions"] == ["Add label Rush"]
    assert labels_of(cid) == set()  # nothing changed
    client.post(f"/api/rules/{rule['id']}/test", {}, expect=400)


def test_apply_to_existing_conversations(client, ch):
    quote = label_id(client, "Quote request")
    old = receive(ch, subject="Quote for menus")["conversation_id"]
    other = receive(ch, subject="Thanks!", sender="z@x.test")["conversation_id"]
    rule = make_rule(client, conditions=[{"field": "subject", "op": "contains", "value": "quote"}],
                     actions=[{"type": "add_label", "label_ids": [quote]}, {"type": "auto_reply", "body_html": "<p>hi</p>"}])
    res = client.post(f"/api/rules/{rule['id']}/apply", {})
    assert res["applied"] == 1 and res["skipped_actions"] == ["auto_reply"]
    assert labels_of(old) == {"Quote request"} and labels_of(other) == set()
    assert db.scalar("SELECT COUNT(*) FROM messages WHERE direction = 'out'") == 0
    comment_rule = make_rule(client, trigger="comment", actions=[{"type": "close"}])
    client.post(f"/api/rules/{comment_rule['id']}/apply", {}, expect=400)


def test_demo_rules_are_valid(client, owner):
    from pps_tools.switchboard.demo.rules import seed_rules
    from pps_tools.switchboard.seed import SeedContext

    office = client.get("/api/teams")["items"][0]["id"]
    client.post("/api/responses", {"title": "After hours", "shortcut": "afterhours", "body_html": "<p>Closed</p>"})
    with db.transaction():
        seed_rules(SeedContext(users={"owner": owner["id"]}, teams={"office": office}))
    rules = db.query("SELECT * FROM rules ORDER BY position")
    assert [r["name"] for r in rules][:4] == ["Label quote requests", "Rush jobs", "Texts go to Front Office",
                                              "After-hours auto-reply"]
    for r in rules:
        for cond in db.jload(r["conditions_json"]):
            engine.validate_condition(cond)
        for action in db.jload(r["actions_json"]):
            engine.validate_action(action)
    assert {r["name"]: r["is_active"] for r in rules}["After-hours auto-reply"] == 0
