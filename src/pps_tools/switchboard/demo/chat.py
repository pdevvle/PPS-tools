"""Demo team chat: #general and #production history, a thread, reactions, and DMs (one
sharing an inbox conversation)."""

from __future__ import annotations

from pps_tools.switchboard import db
from pps_tools.switchboard.services import search
from pps_tools.switchboard.util import html_to_text, now_iso


def _room(name):
    row = db.one("SELECT id FROM chat_rooms WHERE kind = 'channel' AND name = ?", name)
    return row["id"] if row else None


def _join(room_id, uid, read_at):
    db.execute("INSERT OR IGNORE INTO chat_members (room_id, user_id, joined_at, last_read_at) VALUES (?, ?, ?, ?)",
               room_id, uid, read_at, read_at)
    db.execute("UPDATE chat_members SET last_read_at = ?, left_at = NULL WHERE room_id = ? AND user_id = ?", read_at, room_id, uid)


def _say(room_id, uid, at, html, mentions=(), parent_id=None, conversation_id=None):
    mid = db.insert("chat_messages", {
        "room_id": room_id, "user_id": uid, "body": html, "mentions_json": db.jdump(list(mentions)),
        "parent_id": parent_id, "conversation_id": conversation_id, "created_at": at,
    })
    if parent_id:
        db.execute("UPDATE chat_messages SET reply_count = reply_count + 1, last_reply_at = ? WHERE id = ?", at, parent_id)
    else:
        db.execute("UPDATE chat_rooms SET last_message_at = MAX(COALESCE(last_message_at, ''), ?) WHERE id = ?", at, room_id)
    search.index("chat", mid, None, html_to_text(html), parent_id=room_id)
    return mid


def _react(mid, emoji, *uids):
    for uid in uids:
        db.execute("INSERT OR IGNORE INTO reactions (target_type, target_id, user_id, emoji, created_at) VALUES (?, ?, ?, ?, ?)",
                   "chat_message", mid, uid, emoji, now_iso())


def _mention(uid, name):
    return f'<span data-mention="{uid}">@{name}</span>'


def _dm(*uids):
    key = ",".join(str(i) for i in sorted(uids))
    stamp = now_iso()
    rid = db.insert("chat_rooms", {"kind": "dm", "dm_key": key, "is_private": 1, "created_by": uids[0], "created_at": stamp})
    for uid in uids:
        db.insert("chat_members", {"room_id": rid, "user_id": uid, "joined_at": stamp, "last_read_at": stamp})
    return rid


def seed_chat(ctx) -> None:
    u = ctx.uid
    general = _room("general")
    production = _room("production")
    if not general or not production:
        return
    everyone = ["owner", "manager", "frontdesk", "designer", "press", "bindery", "driver", "parttime"]
    start = ctx.ago(days=6)
    for key in everyone:
        _join(general, u(key), start)
    for key in ("owner", "manager", "designer", "press", "bindery", "parttime", "driver"):
        _join(production, u(key), start)

    welcome = _say(general, u("owner"), ctx.ago(days=5, hours=6),
                   "<p>Morning all! 👋 Customer email, texts and website chat now all land in the shared inbox, and "
                   "the schedule + jobs board live here too. Shout in here if anything looks off.</p>")
    _react(welcome, "🎉", u("manager"), u("frontdesk"), u("press"))
    _react(welcome, "👍", u("bindery"), u("driver"))
    q = _say(general, u("frontdesk"), ctx.ago(days=1, hours=5),
             "<p>Copperline Brewing asked about can labels. Has anyone here done shrink sleeves before?</p>")
    _say(general, u("manager"), ctx.ago(days=1, hours=4, minutes=50),
         "<p>We send sleeves out to Labelworx. I'll forward you their price list.</p>", parent_id=q)
    _say(general, u("frontdesk"), ctx.ago(days=1, hours=4, minutes=45), "<p>Perfect, thanks!</p>", parent_id=q)
    _say(general, u("designer"), ctx.ago(days=1, hours=2),
         "<p>The new proofing checklist is in the shared drive under <b>Prepress</b>. Please run every job through it "
         "before it goes to plate.</p>")
    folder = _say(general, u("bindery"), ctx.ago(hours=3),
                  "<p>Folder is back up after this morning's jam — it was a worn pickup roller. Spare is on order.</p>")
    _react(folder, "🙌", u("manager"), u("press"))

    _say(production, u("manager"), ctx.ago(hours=6),
         "<p><b>Today:</b> Press 1 runs the Saguaro cards (once Marcus approves), then the Desert Bloom menus. "
         "Press 2 is down Thursday 1–4pm for roller service.</p>")
    _say(production, u("press"), ctx.ago(hours=5, minutes=40),
         "<p>Blanket wash on Press 2 is done. I'll run the Arts Council covers first thing Friday.</p>")
    _say(production, u("manager"), ctx.ago(hours=2, minutes=10),
         f"<p>{_mention(u('bindery'), 'Taylor Brooks')} can you saddle-stitch the gala programs Friday afternoon?</p>",
         mentions=[u("bindery")])
    _say(production, u("bindery"), ctx.ago(hours=2), "<p>Yep — I'll set up the stitcher after lunch.</p>")
    _say(production, u("parttime"), ctx.ago(minutes=50), "<p>I can come in at 7 tomorrow to help stage paper.</p>")
    # Morgan hasn't caught up on #production yet
    db.execute("UPDATE chat_members SET last_read_at = ? WHERE room_id = ? AND user_id = ?", ctx.ago(hours=7), production, u("owner"))
    db.execute("UPDATE chat_members SET last_read_at = ? WHERE room_id = ? AND user_id = ?", now_iso(), general, u("owner"))

    convs = ctx.data.get("conversations") or {}
    dm = _dm(u("frontdesk"), u("designer"))
    _say(dm, u("frontdesk"), ctx.ago(hours=2, minutes=35), "<p>Can you look at this one? Lena's file needs bleed.</p>",
         conversation_id=convs.get("menus"))
    _say(dm, u("designer"), ctx.ago(hours=2, minutes=20), "<p>On it after lunch — I'll rebuild it from the InDesign file.</p>")
    db.execute("UPDATE chat_rooms SET last_message_at = ? WHERE id = ?", ctx.ago(hours=2, minutes=20), dm)

    dm2 = _dm(u("manager"), u("press"))
    _say(dm2, u("manager"), ctx.ago(days=1, hours=1), "<p>Could you cover Jamie's Saturday morning shift?</p>")
    _say(dm2, u("press"), ctx.ago(days=1), "<p>Sure, I can do 8–12.</p>")
    db.execute("UPDATE chat_rooms SET last_message_at = ? WHERE id = ?", ctx.ago(days=1), dm2)

    dm3 = _dm(u("owner"), u("manager"))
    _say(dm3, u("manager"), ctx.ago(minutes=25),
         "<p>Heads up: Mohawk's price increase hits Jan 1. Want me to lock a Q1 paper order this week?</p>")
    db.execute("UPDATE chat_rooms SET last_message_at = ? WHERE id = ?", ctx.ago(minutes=25), dm3)
    db.execute("UPDATE chat_members SET last_read_at = ? WHERE room_id = ? AND user_id = ?", ctx.ago(hours=1), dm3, u("owner"))
