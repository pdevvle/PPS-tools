"""Demo inbox: a week of a print shop's email, texts and website chats."""

from __future__ import annotations

from datetime import timedelta

from pps_tools.switchboard import db
from pps_tools.switchboard.services import files, inbox
from pps_tools.switchboard.services.inbox import Inbound
from pps_tools.switchboard.util import html_to_text, iso, now_iso, snippet, text_to_html, token


def _channel(name, type_, address, team_id=None, visibility="shared", owner=None, signature=None):
    return db.insert("channels", {
        "type": type_, "name": name, "address": address, "visibility": visibility, "owner_user_id": owner,
        "team_id": team_id, "config_json": db.jdump({"demo": True}), "signature_html": signature,
        "public_key": token(16), "created_at": now_iso(), "updated_at": now_iso(),
    })


def _ch(cid):
    return db.one("SELECT * FROM channels WHERE id = ?", cid)


def _inbound(channel_id, at, from_handle, from_name, body, subject=None, kind="email", thread_key=None,
             conversation_id=None, attachments=(), references=None):
    msg = inbox.deliver_inbound(Inbound(
        channel=_ch(channel_id), kind=kind, from_handle=from_handle, from_name=from_name, subject=subject,
        body_text=body, to=[{"name": None, "handle": _ch(channel_id)["address"]}], thread_key=thread_key,
        conversation_id=conversation_id, references=references or [], external_id=f"<demo-{token(8)}@mail.test>",
        attachments=[{"filename": n, "content_type": t, "data": d} for n, t, d in attachments],
    ))
    db.execute("UPDATE messages SET date = ?, created_at = ? WHERE id = ?", at, at, msg["id"])
    db.execute("UPDATE notifications SET created_at = ? WHERE entity_type = 'conversation' AND entity_id = ? "
               "AND created_at > ?", at, msg["conversation_id"], at)
    return msg


def _outbound(conv_id, channel_id, author, at, body_html, to, subject=None, status="sent", scheduled_at=None):
    ch = _ch(channel_id)
    text = html_to_text(body_html)
    mid = db.insert("messages", {
        "conversation_id": conv_id, "channel_id": channel_id, "direction": "out", "kind": ch["type"],
        "from_name": db.one("SELECT name FROM users WHERE id = ?", author)["name"], "from_handle": ch["address"],
        "to_json": db.jdump(to), "subject": subject if ch["type"] == "email" else None,
        "body_text": text, "body_html": body_html if ch["type"] in ("email", "chat") else None,
        "snippet": snippet(text, 200), "author_id": author, "status": status,
        "scheduled_at": scheduled_at, "sent_at": at if status == "sent" else None,
        "external_id": f"<sb.demo.{token(8)}@pps.demo>", "date": scheduled_at or at, "created_at": at,
        "track_token": token(10),
    })
    inbox.set_user_state(conv_id, author, following=1, last_read_at=at)
    return mid


def _comment(conv_id, author, at, body_html, mentions=()):
    db.insert("comments", {
        "conversation_id": conv_id, "user_id": author, "body": body_html, "mentions_json": db.jdump(list(mentions)),
        "created_at": at,
    })
    inbox.set_user_state(conv_id, author, following=1, last_read_at=at)
    for uid in mentions:
        inbox.set_user_state(conv_id, uid, following=1, in_inbox=1)


def _mention(uid, name):
    return f'<span data-mention="{uid}">@{name}</span>'


def _finish(conv_id, read_by=(), first_response=None):
    inbox.recompute(conv_id)
    conv = inbox.get(conv_id)
    if first_response:
        db.update("conversations", conv_id, {"first_response_at": first_response})
    for uid in read_by:
        inbox.set_user_state(conv_id, uid, last_read_at=conv["last_activity_at"])
    return conv


def _label(name):
    return db.one("SELECT id FROM labels WHERE name = ?", name)["id"]


def _labels(conv_id, names, by):
    for n in names:
        db.execute("INSERT OR IGNORE INTO conversation_labels (conversation_id, label_id, added_by, added_at) VALUES (?, ?, ?, ?)",
                   conv_id, _label(n), by, now_iso())


def _assign(conv_id, uid, by, at):
    db.execute("INSERT OR IGNORE INTO conversation_assignees (conversation_id, user_id, assigned_by, assigned_at) VALUES (?, ?, ?, ?)",
               conv_id, uid, by, at)
    inbox.set_user_state(conv_id, uid, following=1, in_inbox=1)
    db.insert("conversation_events", {"conversation_id": conv_id, "user_id": by, "type": "assigned",
                                      "data_json": db.jdump({"user_ids": [uid]}), "created_at": at})


def _org(name, domain, phone=None, address=None):
    return db.insert("organizations", {"name": name, "domain": domain, "phone": phone, "address": address,
                                       "created_at": now_iso(), "updated_at": now_iso()})


PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def seed_inbox(ctx) -> None:
    u = ctx.uid
    office, production = ctx.teams["office"], ctx.teams["production"]
    sig = "<p>{{user.name}}<br>{{user.title}} · {{org.name}}<br>(602) 555-0142 · priorityprint.example</p>"
    orders = _channel("Orders", "email", "orders@pps.demo", team_id=office, signature=sig)
    personal = _channel("Morgan's mail", "email", "morgan@pps.demo", visibility="personal", owner=u("owner"), signature=sig)
    sms = _channel("Shop text line", "sms", "+16025550142", team_id=office)
    chat = _channel("Website chat", "chat", "priorityprint.example", team_id=office)
    _channel("WhatsApp", "whatsapp", "+16025550199", team_id=office)
    ctx.data["channels"] = {"orders": orders, "personal": personal, "sms": sms, "chat": chat}

    _org("Desert Bloom Café", "desertbloomcafe.example", "(480) 555-0110", "214 E Roosevelt St, Phoenix, AZ")
    _org("Saguaro Realty Group", "saguarorealty.example", "(602) 555-0188", "4400 N Scottsdale Rd, Scottsdale, AZ")
    _org("Phoenix Arts Council", "phxarts.example", "(602) 555-0123")
    _org("Copperline Brewing", "copperlinebrewing.example", "(623) 555-0177")
    _org("Mohawk Paper", "mohawkpaper.example")

    # 1. Quote request, assigned to Sam, with an internal discussion.
    t0 = ctx.ago(hours=3, minutes=10)
    m = _inbound(orders, t0, "lena@desertbloomcafe.example", "Lena Ortiz",
                 "Hi there!\n\nWe're refreshing our menus for the fall. Could you quote 200 trifold menus, "
                 "11x17 folded to letter size, 100lb gloss text, full color both sides? We'd love them by the 10th.\n\n"
                 "I've attached last season's file for reference.\n\nThanks!\nLena Ortiz\nDesert Bloom Café",
                 subject="Menu reprint — 200 trifold menus", attachments=[("fall-menu-2025.pdf", "application/pdf", PDF)])
    c1 = m["conversation_id"]
    _assign(c1, u("frontdesk"), u("owner"), ctx.ago(hours=3))
    _labels(c1, ["Quote request"], u("frontdesk"))
    _comment(c1, u("frontdesk"), ctx.ago(hours=2, minutes=40),
             f"<p>{_mention(u('designer'), 'Jordan Lee')} can you check whether last year's file is press-ready? "
             f"The fold marks looked off to me.</p>", mentions=[u("designer")])
    _comment(c1, u("designer"), ctx.ago(hours=2, minutes=15),
             "<p>Bleed is only 1/16\" — I'll need to rebuild it. Budget 45 min of prepress.</p>")
    _finish(c1, read_by=[u("frontdesk")])

    # 2. Business cards with a sent proof; waiting on approval; shared draft by Jordan.
    t = ctx.ago(days=1, hours=4)
    m = _inbound(orders, t, "marcus@saguarorealty.example", "Marcus Hale",
                 "Morning,\n\nWe have three new agents starting Monday. Same card layout as before, details below:\n\n"
                 "- Ana Ruiz, Realtor, (602) 555-0131\n- Ben Cho, Realtor, (602) 555-0132\n- Kayla Moss, Office Manager, (602) 555-0133\n\n"
                 "500 each please. Can we see a proof first?\n\nMarcus",
                 subject="Business cards for 3 new agents")
    c2 = m["conversation_id"]
    _assign(c2, u("designer"), u("frontdesk"), ctx.ago(days=1, hours=3))
    _labels(c2, ["Order", "Proof"], u("designer"))
    sent = ctx.ago(days=1, hours=1)
    _outbound(c2, orders, u("designer"), sent,
              "<p>Hi Marcus,</p><p>Proofs for all three agents are attached. Please check names, titles and phone "
              "numbers carefully — reply “approved” and we'll print today.</p><p>Jordan</p>",
              [{"name": "Marcus Hale", "handle": "marcus@saguarorealty.example"}], subject="Re: Business cards for 3 new agents")
    last = db.one("SELECT id FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1", c2)["id"]
    files.save_bytes(PDF, "saguaro-cards-proof-v1.pdf", "application/pdf", u("designer"), owner_type="message", owner_id=last)
    db.insert("reminders", {"conversation_id": c2, "user_id": u("designer"), "remind_at": ctx.ahead(hours=20),
                            "condition": "no_reply", "note": "Chase proof approval", "created_at": sent})
    db.insert("drafts", {
        "conversation_id": c2, "channel_id": orders, "mode": "reply", "to_json": db.jdump([{"name": "Marcus Hale", "handle": "marcus@saguarorealty.example"}]),
        "subject": "Re: Business cards for 3 new agents", "body_html": "<p>Hi Marcus — just checking whether the proofs look good?</p>",
        "created_by": u("designer"), "updated_by": u("designer"), "created_at": ctx.ago(minutes=40), "updated_at": ctx.ago(minutes=40),
    })
    _finish(c2, read_by=[u("designer")], first_response=sent)

    # 3. Rush banners by text, unassigned in the team inbox.
    m = _inbound(sms, ctx.ago(minutes=48), "+16025550164", "Dana Price",
                 "Hi! This is Coach Dana from Valley Little League. Any chance you can do 15 vinyl banners (3x6) for opening day this Saturday?",
                 kind="sms", thread_key="+16025550164")
    c3 = m["conversation_id"]
    _inbound(sms, ctx.ago(minutes=46), "+16025550164", "Dana Price", "Sponsors' logos are ready, I can email them tonight.",
             kind="sms", thread_key="+16025550164")
    _labels(c3, ["Rush", "Quote request"], u("owner"))
    db.update("conversations", c3, {"priority": "urgent"})
    _finish(c3)

    # 4. Website chat, answered and closed.
    visitor = token(16)
    m = _inbound(chat, ctx.ago(days=1, hours=6), None, "Ellie", "Hi! What's your usual turnaround for 1,000 postcards?",
                 kind="chat", thread_key=visitor)
    c4 = m["conversation_id"]
    db.insert("chat_visitors", {"channel_id": chat, "token": visitor, "name": "Ellie", "conversation_id": c4,
                                "page_url": "https://priorityprint.example/postcards", "created_at": ctx.ago(days=1, hours=6)})
    r = ctx.ago(days=1, hours=5, minutes=57)
    _outbound(c4, chat, u("frontdesk"), r, "<p>Hi Ellie! Standard is 3 business days after proof approval, or next day for a rush fee.</p>",
              [{"name": "Ellie", "handle": visitor}])
    _inbound(chat, ctx.ago(days=1, hours=5, minutes=55), None, "Ellie", "Perfect, thank you!", kind="chat", thread_key=visitor,
             conversation_id=c4)
    _finish(c4, read_by=[u("frontdesk")], first_response=r)
    db.update("conversations", c4, {"status": "closed", "closed_at": ctx.ago(days=1, hours=5), "closed_by": u("frontdesk")})
    db.execute("UPDATE conversation_users SET in_inbox = 0 WHERE conversation_id = ?", c4)

    # 5. Program booklets, snoozed until tomorrow.
    m = _inbound(orders, ctx.ago(days=2, hours=2), "priya@phxarts.example", "Priya Raman",
                 "Hello,\n\nWe need 500 program booklets for the Fall Gala: 16 pages + cover, 5.5x8.5, saddle stitched. "
                 "Our designer will send final files Thursday. Could you hold press time for Friday?\n\nBest,\nPriya",
                 subject="Fall Gala programs — 500 booklets")
    c5 = m["conversation_id"]
    r5 = ctx.ago(days=2, hours=1)
    _outbound(c5, orders, u("manager"), r5, "<p>Hi Priya, Friday is held for you on Press 1. We'll confirm as soon as files arrive.</p>",
              [{"name": "Priya Raman", "handle": "priya@phxarts.example"}], subject="Re: Fall Gala programs — 500 booklets")
    _assign(c5, u("manager"), u("manager"), ctx.ago(days=2, hours=1))
    _labels(c5, ["Order"], u("manager"))
    _finish(c5, read_by=[u("manager")], first_response=r5)
    db.update("conversations", c5, {"snoozed_until": iso(ctx.local(days=1, hour=8)), "snoozed_by": u("manager")})

    # 6. New brewery inquiry, unassigned.
    m = _inbound(orders, ctx.ago(minutes=22), "tom@copperlinebrewing.example", "Tom Becker",
                 "Hey folks — do you print can labels or shrink sleeves? We're launching a seasonal IPA and need ~3,000 labels.",
                 subject="Labels for a seasonal release?")
    _finish(m["conversation_id"])

    # 7. Wedding invitations, closed last week.
    m = _inbound(orders, ctx.ago(days=8), "grace.kim@mail.example", "Grace Kim",
                 "Hi! I picked up our wedding invitations today and they're beautiful. Thank you so much!",
                 subject="Thank you!")
    c7 = m["conversation_id"]
    _outbound(c7, orders, u("frontdesk"), ctx.ago(days=7, hours=23), "<p>Congratulations, Grace! It was a pleasure. 💐</p>",
              [{"name": "Grace Kim", "handle": "grace.kim@mail.example"}], subject="Re: Thank you!")
    _finish(c7, read_by=[u("frontdesk")])
    db.update("conversations", c7, {"status": "closed", "closed_at": ctx.ago(days=7, hours=22), "closed_by": u("frontdesk")})
    db.execute("UPDATE conversation_users SET in_inbox = 0 WHERE conversation_id = ?", c7)

    # 8. Vendor notice in Morgan's personal mail.
    m = _inbound(personal, ctx.ago(hours=20), "steve.alvarez@mohawkpaper.example", "Steve Alvarez",
                 "Hi Morgan,\n\nHeads up that coated text and cover stocks go up 6% on January 1. Happy to lock current "
                 "pricing on a Q1 order placed before Dec 15.\n\nSteve Alvarez\nMohawk Paper",
                 subject="Q1 price change — coated stocks")
    _labels(m["conversation_id"], ["Vendor", "Billing"], u("owner"))
    _finish(m["conversation_id"])

    # 9. Internal discussion in Production.
    conv = inbox.create_conversation("Press 2 maintenance window", None, created_by=u("manager"), team_id=production)
    c9 = conv["id"]
    _comment(c9, u("manager"), ctx.ago(hours=26),
             f"<p>The roller service tech can come Thursday 1–4pm. {_mention(u('press'), 'Alex Kim')} does that clash with the Saguaro cards?</p>",
             mentions=[u("press")])
    _comment(c9, u("press"), ctx.ago(hours=25, minutes=30), "<p>Cards run on Press 1, we're fine. I'll stage the blankets Wednesday night.</p>")
    db.insert("conversation_events", {"conversation_id": c9, "user_id": u("manager"), "type": "discussion_started",
                                      "data_json": "{}", "created_at": ctx.ago(hours=26, minutes=1)})
    db.update("conversations", c9, {"created_at": ctx.ago(hours=26, minutes=1)})
    _finish(c9, read_by=[u("manager"), u("press")])

    # 10. Spam.
    m = _inbound(orders, ctx.ago(hours=9), "growth@seo-rocket.example", "SEO Rocket",
                 "Your website is losing 80% of its traffic!!! Reply now for a FREE audit.", subject="Rank #1 on Google GUARANTEED")
    db.update("conversations", m["conversation_id"], {"is_spam": 1})
    db.execute("UPDATE conversation_users SET in_inbox = 0 WHERE conversation_id = ?", m["conversation_id"])

    # 11. Send-later follow-up from Sam to Lena.
    _outbound(c1, orders, u("frontdesk"), ctx.ago(minutes=30),
              "<p>Hi Lena, quick update: we're rebuilding your menu file with proper bleed and will send a quote and proof "
              "first thing tomorrow.</p>",
              [{"name": "Lena Ortiz", "handle": "lena@desertbloomcafe.example"}], subject="Re: Menu reprint — 200 trifold menus",
              status="scheduled", scheduled_at=iso(ctx.local(days=1, hour=9)))
    _finish(c1, read_by=[u("frontdesk")])

    # Canned responses.
    stamp = now_iso()
    for title, shortcut, subject, html_body in [
        ("Quote received", "quote", None,
         "<p>Hi {{contact.first_name}},</p><p>Thanks for reaching out! We've got your request and will send a quote "
         "within one business day.</p><p>{{user.first_name}}</p>"),
        ("Proof ready", "proof", "Your proof is ready",
         "<p>Hi {{contact.first_name}},</p><p>Your proof is attached. Please check spelling, phone numbers and colors, "
         "then reply <b>approved</b> and we'll get it on press.</p><p>{{user.first_name}}</p>"),
        ("Ready for pickup", "pickup", "Your order is ready",
         "<p>Hi {{contact.first_name}}, good news — your order is ready for pickup at {{org.name}}, "
         "Mon–Fri 8am–5pm.</p>"),
        ("Turnaround times", "turnaround", None,
         "<p>Standard turnaround is 3 business days after proof approval. Next-day rush is available on most products "
         "for a 25% fee.</p>"),
        ("After-hours auto-reply", "afterhours", "We got your message",
         "<p>Thanks for contacting {{org.name}}! We're closed right now and will reply first thing next business day.</p>"),
    ]:
        db.insert("canned_responses", {"title": title, "shortcut": shortcut, "subject": subject, "body_html": html_body,
                                       "visibility": "shared", "owner_user_id": u("owner"), "created_at": stamp,
                                       "updated_at": stamp})
    ctx.data["conversations"] = {"menus": c1, "cards": c2, "banners": c3, "postcards": c4, "programs": c5}
