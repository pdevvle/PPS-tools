"""Team chat: rooms & membership, privacy, DMs, mentions, unread counts, threads,
shared conversation cards, typing, attachments, search."""

from __future__ import annotations

import io

from pps_tools.switchboard import realtime
from tests.test_switchboard.test_inbox import make_channel, receive


def rooms(api):
    return {r["name"] or r["title"]: r for r in api.get("/api/chat/rooms")["items"]}


def say(api, room_id, html, **extra):
    return api.post(f"/api/chat/rooms/{room_id}/messages", {"body": html, **extra}, expect=201)["message"]


def test_default_rooms_and_auto_join(client, make_user):
    mine = rooms(client)
    assert "general" in mine and "production" not in mine
    _, newbie = make_user("staff")
    assert "general" in rooms(newbie)                     # auto-joined on first look
    browse = {r["name"]: r for r in newbie.get("/api/chat/rooms/browse")["items"]}
    assert browse["production"]["is_member"] is False
    newbie.post(f"/api/chat/rooms/{browse['production']['id']}/join")
    assert "production" in rooms(newbie)


def test_leaving_default_room_sticks(client, make_user):
    _, agent = make_user("agent")
    general = rooms(agent)["general"]
    agent.post(f"/api/chat/rooms/{general['id']}/leave")
    assert "general" not in rooms(agent)
    assert "general" not in rooms(agent)                  # not re-added


def test_channel_names_and_duplicates(client):
    r = client.post("/api/chat/rooms", {"name": "#Press Room!", "topic": "Ink talk"})["room"]
    assert r["name"] == "press-room"
    client.post("/api/chat/rooms", {"name": "press room"}, expect=409)
    client.post("/api/chat/rooms", {"name": "!!!"}, expect=400)


def test_private_room_privacy(client, owner, make_user):
    a, a_client = make_user("agent")
    _, b_client = make_user("agent")
    room = client.post("/api/chat/rooms", {"name": "managers", "is_private": True, "member_ids": [a["id"]]})["room"]
    say(client, room["id"], "<p>Raises next month</p>")
    assert a_client.get(f"/api/chat/rooms/{room['id']}/messages")["items"][0]["body"] == "<p>Raises next month</p>"
    b_client.get(f"/api/chat/rooms/{room['id']}", expect=404)
    b_client.get(f"/api/chat/rooms/{room['id']}/messages", expect=404)
    b_client.post(f"/api/chat/rooms/{room['id']}/messages", {"body": "<p>hi</p>"}, expect=404)
    assert "managers" not in {r["name"] for r in b_client.get("/api/chat/rooms/browse")["items"]}
    assert not [i for i in b_client.get("/api/search", query_string={"q": "raises"})["items"] if i["type"] == "chat_message"]


def test_public_room_readable_and_posting_joins(client, make_user):
    room = client.post("/api/chat/rooms", {"name": "random"})["room"]
    say(client, room["id"], "<p>Donuts in the break room</p>")
    _, agent = make_user("agent")
    assert agent.get(f"/api/chat/rooms/{room['id']}/messages")["items"][0]["body"].startswith("<p>Donuts")
    say(agent, room["id"], "<p>🍩 thanks</p>")
    assert "random" in rooms(agent)


def test_dm_get_or_create_is_idempotent_and_private(client, owner, make_user):
    a, a_client = make_user("agent")
    _, b_client = make_user("agent")
    r1 = client.post(f"/api/chat/dm/{a['id']}")["room"]
    r2 = a_client.get(f"/api/chat/dm/{owner['id']}")["room"]
    assert r1["id"] == r2["id"] and r1["kind"] == "dm"
    assert r1["title"] == a["name"] and r2["title"] == owner["name"]
    b_client.get(f"/api/chat/rooms/{r1['id']}/messages", expect=404)
    note_to_self = client.post(f"/api/chat/dm/{owner['id']}")["room"]
    assert note_to_self["title"].endswith("(you)")
    group = client.post("/api/chat/dms", {"user_ids": [a["id"]]}, expect=201)["room"]
    assert group["id"] == r1["id"]


def test_dm_notifies_unless_viewing(client, owner, make_user):
    a, a_client = make_user("agent")
    room = client.post(f"/api/chat/dm/{a['id']}")["room"]
    say(client, room["id"], "<p>Got a minute?</p>")
    note = a_client.get("/api/notifications")["items"][0]
    assert note["type"] == "chat" and note["link"].startswith(f"/chat/{room['id']}")
    a_client.post("/api/notifications/read", {})
    a_client.post("/api/presence", {"target": f"chat:{room['id']}"})
    say(client, room["id"], "<p>Never mind</p>")
    assert a_client.get("/api/notifications")["unread_count"] == 0


def test_mentions_notify_and_unread_counts(client, owner, make_user):
    a, a_client = make_user("agent")
    general = rooms(a_client)["general"]
    say(client, general["id"], f'<p>Hey <span data-mention="{a["id"]}">@x</span>, the van is back</p>')
    say(client, general["id"], "<p>Also: lunch Friday</p>")
    note = a_client.get("/api/notifications")["items"][0]
    assert note["type"] == "mention"
    r = rooms(a_client)["general"]
    assert r["unread"] == 2 and r["mentions"] == 1
    assert r["last_message"]["preview"] == "Also: lunch Friday"
    assert a_client.get("/api/badges")["badges"]["chat"] == 2
    assert rooms(client)["general"]["unread"] == 0          # your own messages don't count
    a_client.post(f"/api/chat/rooms/{general['id']}/read")
    assert rooms(a_client)["general"]["unread"] == 0
    assert a_client.get("/api/badges")["badges"]["chat"] == 0


def test_muted_rooms_dont_count_in_badge(client, owner, make_user):
    _, a_client = make_user("agent")
    general = rooms(a_client)["general"]
    a_client.post(f"/api/chat/rooms/{general['id']}/mute", {"muted": True})
    say(client, general["id"], "<p>Spam-ish chatter</p>")
    assert rooms(a_client)["general"]["unread"] == 1 and rooms(a_client)["general"]["muted"] is True
    assert a_client.get("/api/badges")["badges"]["chat"] == 0


def test_threads(client, owner, make_user):
    a, a_client = make_user("agent")
    general = rooms(a_client)["general"]
    parent = say(a_client, general["id"], "<p>Who has the folder key?</p>")
    reply = say(client, general["id"], "<p>Top drawer</p>", parent_id=parent["id"])
    say(client, general["id"], "<p>Left side</p>", parent_id=reply["id"])   # replies to replies join the thread
    thread = client.get(f"/api/chat/messages/{parent['id']}/thread")
    assert thread["parent"]["reply_count"] == 2 and len(thread["replies"]) == 2
    top = client.get(f"/api/chat/rooms/{general['id']}/messages")["items"]
    assert [m["id"] for m in top] == [parent["id"]]           # replies stay out of the main list
    assert top[0]["reply_user_ids"] == [owner["id"]]
    assert a_client.get("/api/notifications")["items"][0]["title"].startswith(f"{owner['name']} replied")


def test_edit_and_delete_own_only(client, owner, make_user):
    _, a_client = make_user("agent")
    general = rooms(client)["general"]
    m = say(client, general["id"], "<p>Typo</p>")
    a_client.patch(f"/api/chat/messages/{m['id']}", {"body": "<p>hijack</p>"}, expect=403)
    a_client.delete(f"/api/chat/messages/{m['id']}", expect=403)
    edited = client.patch(f"/api/chat/messages/{m['id']}", {"body": "<p>Fixed</p>"})["message"]
    assert edited["body"] == "<p>Fixed</p>" and edited["edited_at"]
    client.delete(f"/api/chat/messages/{m['id']}")
    item = client.get(f"/api/chat/rooms/{general['id']}/messages")["items"][-1]
    assert item["deleted"] is True and item["body"] == ""


def test_empty_and_sanitized_messages(client):
    general = rooms(client)["general"]
    client.post(f"/api/chat/rooms/{general['id']}/messages", {"body": "<p> </p>"}, expect=400)
    m = say(client, general["id"], '<p>hi<img src=x onerror=alert(1)><script>bad()</script></p>')
    assert "onerror" not in m["body"] and "<script" not in m["body"]


def test_shared_conversation_card_respects_visibility(client, owner, make_user):
    team = client.post("/api/teams", {"name": "Desk", "member_ids": [owner["id"]]})["team"]
    cid = receive(make_channel(team_id=team["id"]), subject="Menu reprint")["conversation_id"]
    _, outsider = make_user("agent")
    general = rooms(client)["general"]
    say(client, general["id"], "<p>Can someone look?</p>", conversation_id=cid)
    mine = client.get(f"/api/chat/rooms/{general['id']}/messages")["items"][-1]["conversation"]
    assert mine["subject"] == "Menu reprint" and mine["url"] == f"/inbox/c/{cid}"
    theirs = outsider.get(f"/api/chat/rooms/{general['id']}/messages")["items"][-1]["conversation"]
    assert theirs == {"id": cid, "restricted": True}
    outsider.post(f"/api/chat/rooms/{general['id']}/messages", {"body": "", "conversation_id": cid}, expect=404)


def test_typing_reaches_other_members(client, owner, make_user):
    a, _ = make_user("agent")
    room = client.post(f"/api/chat/dm/{a['id']}")["room"]
    sub = realtime.broker.subscribe(a["id"])
    try:
        while not sub.queue.empty():
            sub.queue.get_nowait()
        client.post(f"/api/chat/rooms/{room['id']}/typing")
        assert '"chat.typing"' in sub.queue.get_nowait()
    finally:
        realtime.broker.unsubscribe(sub)


def test_attachments_follow_room_privacy(client, owner, make_user):
    a, a_client = make_user("agent")
    _, b_client = make_user("agent")
    room = client.post(f"/api/chat/dm/{a['id']}")["room"]
    up = client.raw("post", "/api/files", data={"files": (io.BytesIO(b"proof"), "proof.pdf")}, content_type="multipart/form-data")
    att = up.get_json()["items"][0]
    m = say(client, room["id"], "", attachment_ids=[att["id"]])
    assert m["attachments"][0]["filename"] == "proof.pdf"
    assert a_client.raw("get", att["url"]).status_code == 200
    assert b_client.raw("get", att["url"]).status_code == 404


def test_reactions_show_on_messages(client, owner):
    general = rooms(client)["general"]
    m = say(client, general["id"], "<p>Shipped!</p>")
    client.post("/api/reactions", {"target_type": "chat_message", "target_id": m["id"], "emoji": "🎉"})
    item = client.get(f"/api/chat/rooms/{general['id']}/messages")["items"][-1]
    assert item["reactions"] == [{"emoji": "🎉", "user_ids": [owner["id"]]}]


def test_pagination(client):
    general = rooms(client)["general"]
    ids = [say(client, general["id"], f"<p>m{i}</p>")["id"] for i in range(7)]
    page = client.get(f"/api/chat/rooms/{general['id']}/messages?limit=3")
    assert [m["id"] for m in page["items"]] == ids[-3:] and page["has_more_before"]
    older = client.get(f"/api/chat/rooms/{general['id']}/messages?limit=3&before={ids[-3]}")
    assert [m["id"] for m in older["items"]] == ids[1:4]
    newer = client.get(f"/api/chat/rooms/{general['id']}/messages?after={ids[3]}")
    assert [m["id"] for m in newer["items"]] == ids[4:]
    around = client.get(f"/api/chat/rooms/{general['id']}/messages?around={ids[3]}&limit=4")
    assert ids[3] in [m["id"] for m in around["items"]]


def test_room_management(client, owner, make_user):
    a, a_client = make_user("agent")
    room = client.post("/api/chat/rooms", {"name": "estimating"})["room"]
    client.post(f"/api/chat/rooms/{room['id']}/members", {"user_ids": [a["id"]]})
    assert "estimating" in rooms(a_client)
    assert a_client.get("/api/notifications")["items"][0]["title"].endswith("#estimating")
    a_client.patch(f"/api/chat/rooms/{room['id']}", {"topic": "Quotes & specs"})
    a_client.patch(f"/api/chat/rooms/{room['id']}", {"name": "nope"}, expect=403)
    client.patch(f"/api/chat/rooms/{room['id']}", {"archived": True})
    assert "estimating" not in rooms(a_client)


def test_search_rooms_and_messages(client):
    general = rooms(client)["general"]
    say(client, general["id"], "<p>The laminator needs new film</p>")
    items = client.get("/api/search", query_string={"q": "laminator"})["items"]
    assert any(i["type"] == "chat_message" and i["url"].startswith(f"/chat/{general['id']}") for i in items)
    items = client.get("/api/search", query_string={"q": "gener"})["items"]
    assert any(i["type"] == "chat_room" for i in items)
