"""Reading the inbox: mailbox lists, search with operators, the conversation timeline,
and sidebar counts.

Mailboxes: inbox, assigned, starred, snoozed, drafts, scheduled, sent, all, closed,
spam, trash, team:<id>[:unassigned|:assigned|:closed|:all], label:<id>.

Search operators (combine freely with plain words):
  from:ann  to:orders@  subject:proof  label:rush  assignee:me|none|jordan
  is:open|closed|unread|starred|snoozed|assigned|unassigned|awaiting
  has:attachment|draft|comments  channel:sms|email|chat|<name>  team:<name>
  contact:<name or email>  before:2026-10-01  after:2026-09-01  in:all|trash|spam|sent
"""

from __future__ import annotations

import re
import shlex

from pps_tools.switchboard import db, realtime
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import files, inbox, reactions, search, settings
from pps_tools.switchboard.services.outbox import serialize_draft
from pps_tools.switchboard.util import iso, now, now_iso, parse_date, parse_iso
from pps_tools.switchboard.web import bad_request

LIVE = "c.deleted_at IS NULL AND c.is_spam = 0 AND c.merged_into_id IS NULL"
UNSNOOZED = "(c.snoozed_until IS NULL OR c.snoozed_until <= ?)"

OPERATORS = {"from", "to", "subject", "label", "assignee", "is", "has", "channel", "team", "contact",
             "before", "after", "in"}


def parse_query(q: str | None) -> tuple[str, list[tuple[str, str]]]:
    """'from:ann is:open quote' -> ('quote', [('from', 'ann'), ('is', 'open')])."""
    if not q:
        return "", []
    try:
        tokens = shlex.split(q)
    except ValueError:
        tokens = q.split()
    words, ops = [], []
    for tok in tokens:
        m = re.match(r"^(\w+):(.+)$", tok)
        if m and m.group(1).lower() in OPERATORS:
            ops.append((m.group(1).lower(), m.group(2).strip()))
        else:
            words.append(tok)
    return " ".join(words), ops


def _mailbox_where(user: dict, mailbox: str, include_closed: bool) -> tuple[list[str], list, bool]:
    """WHERE parts for a mailbox. The bool says whether a conversation_users join is needed."""
    uid = user["id"]
    stamp = now_iso()
    where: list[str] = []
    params: list = []
    if mailbox == "inbox":
        where += ["cu.in_inbox = 1", LIVE, UNSNOOZED]
        params.append(stamp)
    elif mailbox == "assigned":
        where += ["EXISTS (SELECT 1 FROM conversation_assignees a WHERE a.conversation_id = c.id AND a.user_id = ?)",
                  "c.status = 'open'", LIVE, UNSNOOZED]
        params += [uid, stamp]
    elif mailbox == "starred":
        where += ["cu.starred = 1", "c.deleted_at IS NULL", "c.merged_into_id IS NULL"]
    elif mailbox == "snoozed":
        where += ["c.snoozed_until > ?", LIVE]
        params.append(stamp)
    elif mailbox == "drafts":
        where += ["EXISTS (SELECT 1 FROM drafts d WHERE d.conversation_id = c.id AND (d.created_by = ? OR d.updated_by = ?))",
                  "c.deleted_at IS NULL"]
        params += [uid, uid]
    elif mailbox == "scheduled":
        where += ["EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id AND m.status = 'scheduled' AND m.author_id = ?)"]
        params.append(uid)
    elif mailbox == "sent":
        where += ["EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id AND m.direction = 'out' AND m.author_id = ?)",
                  "c.deleted_at IS NULL", "c.merged_into_id IS NULL"]
        params.append(uid)
    elif mailbox == "all":
        where.append(LIVE)
    elif mailbox == "closed":
        where += ["c.status = 'closed'", LIVE]
    elif mailbox == "spam":
        where += ["c.is_spam = 1", "c.deleted_at IS NULL"]
    elif mailbox == "trash":
        where += ["c.deleted_at IS NOT NULL", "c.merged_into_id IS NULL"]
    elif mailbox.startswith("team:"):
        parts = mailbox.split(":")
        try:
            team_id = int(parts[1])
        except (IndexError, ValueError):
            bad_request("Unknown team")
        sub = parts[2] if len(parts) > 2 else "open"
        where += ["c.team_id = ?", LIVE]
        params.append(team_id)
        if sub == "closed":
            where.append("c.status = 'closed'")
        elif sub != "all":
            where += ["c.status = 'open'", UNSNOOZED]
            params.append(stamp)
            if sub == "unassigned":
                where.append("NOT EXISTS (SELECT 1 FROM conversation_assignees a WHERE a.conversation_id = c.id)")
            elif sub == "assigned":
                where.append("EXISTS (SELECT 1 FROM conversation_assignees a WHERE a.conversation_id = c.id)")
    elif mailbox.startswith("label:"):
        try:
            label_id = int(mailbox.split(":")[1])
        except (IndexError, ValueError):
            bad_request("Unknown label")
        where += ["EXISTS (SELECT 1 FROM conversation_labels cl WHERE cl.conversation_id = c.id AND cl.label_id = ?)", LIVE]
        params.append(label_id)
        if not include_closed:
            where.append("c.status = 'open'")
    else:
        bad_request(f"Unknown mailbox '{mailbox}'")
    return where, params, True


def _apply_ops(user: dict, ops: list[tuple[str, str]], where: list, params: list) -> str | None:
    """Translate search operators to SQL. Returns a mailbox override from in:..."""
    override = None
    uid = user["id"]
    for op, value in ops:
        v = value.lower()
        like = f"%{value}%"
        if op == "from":
            if v == "me":
                where.append("EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id AND m.author_id = ?)")
                params.append(uid)
            else:
                where.append("EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id AND m.direction = 'in' "
                             "AND (m.from_handle LIKE ? OR m.from_name LIKE ?))")
                params += [like, like]
        elif op == "to":
            where.append("EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id AND (m.to_json LIKE ? OR m.cc_json LIKE ?))")
            params += [like, like]
        elif op == "subject":
            where.append("c.subject LIKE ?")
            params.append(like)
        elif op == "label":
            where.append("EXISTS (SELECT 1 FROM conversation_labels cl JOIN labels l ON l.id = cl.label_id "
                         "WHERE cl.conversation_id = c.id AND l.name LIKE ? "
                         "AND (l.visibility = 'shared' OR l.owner_user_id = ?))")
            params += [value, uid]
        elif op == "assignee":
            if v in ("none", "nobody", "unassigned"):
                where.append("NOT EXISTS (SELECT 1 FROM conversation_assignees a WHERE a.conversation_id = c.id)")
            elif v == "me":
                where.append("EXISTS (SELECT 1 FROM conversation_assignees a WHERE a.conversation_id = c.id AND a.user_id = ?)")
                params.append(uid)
            else:
                where.append("EXISTS (SELECT 1 FROM conversation_assignees a JOIN users u ON u.id = a.user_id "
                             "WHERE a.conversation_id = c.id AND (u.name LIKE ? OR u.email LIKE ?))")
                params += [like, like]
        elif op == "is":
            mapping = {
                "open": "c.status = 'open'",
                "closed": "c.status = 'closed'",
                "starred": "cu.starred = 1",
                "unread": "(cu.last_read_at IS NULL OR cu.last_read_at < c.last_activity_at)",
                "read": "(cu.last_read_at IS NOT NULL AND cu.last_read_at >= c.last_activity_at)",
                "assigned": "EXISTS (SELECT 1 FROM conversation_assignees a WHERE a.conversation_id = c.id)",
                "unassigned": "NOT EXISTS (SELECT 1 FROM conversation_assignees a WHERE a.conversation_id = c.id)",
                "awaiting": "(c.last_inbound_at IS NOT NULL AND (c.last_outbound_at IS NULL OR c.last_outbound_at < c.last_inbound_at))",
            }
            if v == "snoozed":
                where.append("c.snoozed_until > ?")
                params.append(now_iso())
            elif v in ("spam", "trash"):
                override = v
            elif v in mapping:
                where.append(mapping[v])
        elif op == "has":
            if v.startswith("attach"):
                where.append("EXISTS (SELECT 1 FROM messages m JOIN attachments a ON a.owner_type = 'message' AND a.owner_id = m.id "
                             "WHERE m.conversation_id = c.id AND a.is_inline = 0)")
            elif v == "draft":
                where.append("EXISTS (SELECT 1 FROM drafts d WHERE d.conversation_id = c.id)")
            elif v.startswith("comment"):
                where.append("c.comment_count > 0")
        elif op == "channel":
            where.append("c.channel_id IN (SELECT id FROM channels WHERE type = ? OR name LIKE ? OR address LIKE ?)")
            params += [v, like, like]
        elif op == "team":
            where.append("c.team_id IN (SELECT id FROM teams WHERE name LIKE ?)")
            params.append(like)
        elif op == "contact":
            where.append("c.contact_id IN (SELECT contact_id FROM contact_handles WHERE value LIKE ? "
                         "UNION SELECT id FROM contacts WHERE name LIKE ?)")
            params += [like, like]
        elif op in ("before", "after"):
            d = parse_date(value)
            if d:
                where.append("c.last_activity_at < ?" if op == "before" else "c.last_activity_at >= ?")
                params.append(d.isoformat())
        elif op == "in":
            override = v
    return override


def _text_conversation_ids(text: str) -> list[int]:
    ids = search.parent_ids(["message", "comment", "conversation"], text, limit=3000)
    contact_ids = [r["ref_id"] for r in search.search(["contact"], text, 200)]
    if contact_ids:
        ids += db.column(f"SELECT id FROM conversations WHERE contact_id IN ({db.placeholders(contact_ids)})", contact_ids)
    return list(dict.fromkeys(ids))


def list_conversations(user: dict, mailbox: str = "inbox", q: str | None = None, cursor: str | None = None,
                       limit: int = 50, include_closed: bool = False) -> dict:
    text, ops = parse_query(q)
    clause, vparams = inbox.visibility_clause(user)
    where: list[str] = [clause]
    params: list = list(vparams)
    if q:
        override = _apply_ops(user, ops, where, params)
        scope = override or ("all" if mailbox in ("inbox", "assigned") else mailbox)
        if scope in ("all", "open"):
            where.append("c.deleted_at IS NULL AND c.merged_into_id IS NULL AND c.is_spam = 0")
        else:
            mw, mp, _ = _mailbox_where(user, scope, True)
            where += mw
            params += mp
        if text:
            ids = _text_conversation_ids(text)
            if not ids:
                return {"items": [], "next": None}
            where.append(f"c.id IN ({db.placeholders(ids)})")
            params += ids
    else:
        mw, mp, _ = _mailbox_where(user, mailbox, include_closed)
        where += mw
        params += mp
    if cursor:
        try:
            at, cid = cursor.rsplit("|", 1)
            where.append("(c.last_activity_at < ? OR (c.last_activity_at = ? AND c.id < ?))")
            params += [at, at, int(cid)]
        except ValueError:
            bad_request("Bad cursor")
    sql = (
        "SELECT c.*, cu.in_inbox AS my_in_inbox, cu.starred AS my_starred, cu.last_read_at AS my_last_read_at, "
        "cu.following AS my_following FROM conversations c "
        "LEFT JOIN conversation_users cu ON cu.conversation_id = c.id AND cu.user_id = ? "
        f"WHERE {' AND '.join(where)} ORDER BY c.last_activity_at DESC, c.id DESC LIMIT ?"
    )
    rows = db.query(sql, [user["id"], *params, limit + 1])
    more = len(rows) > limit
    rows = rows[:limit]
    items = summaries(user, rows)
    nxt = f"{rows[-1]['last_activity_at']}|{rows[-1]['id']}" if more and rows else None
    return {"items": items, "next": nxt}


def _channel_index() -> dict[int, dict]:
    return {c["id"]: {"id": c["id"], "type": c["type"], "name": c["name"], "address": c["address"]}
            for c in db.query("SELECT id, type, name, address FROM channels")}


def summaries(user: dict, rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    ph = db.placeholders(ids)
    assignee_map: dict[int, list[int]] = {}
    for a in db.query(f"SELECT conversation_id, user_id FROM conversation_assignees WHERE conversation_id IN ({ph}) ORDER BY assigned_at", ids):
        assignee_map.setdefault(a["conversation_id"], []).append(a["user_id"])
    label_map: dict[int, list[int]] = {}
    for lrow in db.query(
        f"SELECT cl.conversation_id, cl.label_id FROM conversation_labels cl JOIN labels l ON l.id = cl.label_id "
        f"WHERE cl.conversation_id IN ({ph}) AND (l.visibility = 'shared' OR l.owner_user_id = ?) ORDER BY l.position, l.name",
        [*ids, user["id"]],
    ):
        label_map.setdefault(lrow["conversation_id"], []).append(lrow["label_id"])
    attach = set(db.column(
        f"SELECT DISTINCT m.conversation_id FROM messages m JOIN attachments a ON a.owner_type = 'message' AND a.owner_id = m.id "
        f"WHERE m.conversation_id IN ({ph}) AND a.is_inline = 0", ids,
    ))
    drafts: dict[int, int] = {r["conversation_id"]: r["n"] for r in db.query(
        f"SELECT conversation_id, COUNT(*) AS n FROM drafts WHERE conversation_id IN ({ph}) "
        f"AND (is_shared = 1 OR created_by = ?) GROUP BY conversation_id", [*ids, user["id"]],
    )}
    scheduled: dict[int, int] = {r["conversation_id"]: r["n"] for r in db.query(
        f"SELECT conversation_id, COUNT(*) AS n FROM messages WHERE conversation_id IN ({ph}) AND status = 'scheduled' "
        f"GROUP BY conversation_id", ids,
    )}
    failed = set(db.column(f"SELECT DISTINCT conversation_id FROM messages WHERE conversation_id IN ({ph}) AND status = 'failed'", ids))
    contact_ids = sorted({r["contact_id"] for r in rows if r["contact_id"]})
    contact_map = {c["id"]: c for c in db.query(
        f"SELECT * FROM contacts WHERE id IN ({db.placeholders(contact_ids)})", contact_ids)} if contact_ids else {}
    channels = _channel_index()
    sla_minutes = settings.get("inbox.sla_first_response_minutes") or 0
    current = now()
    out = []
    for r in rows:
        contact = contact_map.get(r["contact_id"])
        last_read = r.get("my_last_read_at")
        awaiting = bool(r["last_inbound_at"] and (not r["last_outbound_at"] or r["last_outbound_at"] < r["last_inbound_at"]))
        overdue = False
        if awaiting and sla_minutes and r["status"] == "open":
            overdue = (current - parse_iso(r["last_inbound_at"])).total_seconds() > sla_minutes * 60
        out.append({
            "id": r["id"],
            "subject": r["subject"],
            "preview": r["preview"],
            "status": r["status"],
            "priority": r["priority"],
            "channel": channels.get(r["channel_id"]),
            "team_id": r["team_id"],
            "contact": {
                "id": contact["id"], "name": contact["name"],
                "display_name": contacts_svc.display_name(contact), "email": contact["email"], "phone": contact["phone"],
            } if contact else None,
            "message_count": r["message_count"],
            "comment_count": r["comment_count"],
            "last_activity_at": r["last_activity_at"],
            "last_message_at": r["last_message_at"],
            "created_at": r["created_at"],
            "assignee_ids": assignee_map.get(r["id"], []),
            "label_ids": label_map.get(r["id"], []),
            "unread": not last_read or last_read < r["last_activity_at"],
            "starred": bool(r.get("my_starred")),
            "in_inbox": bool(r.get("my_in_inbox")),
            "following": bool(r.get("my_following")),
            "snoozed_until": r["snoozed_until"] if r["snoozed_until"] and r["snoozed_until"] > now_iso() else None,
            "is_spam": bool(r["is_spam"]),
            "deleted_at": r["deleted_at"],
            "has_attachments": r["id"] in attach,
            "draft_count": drafts.get(r["id"], 0),
            "scheduled_count": scheduled.get(r["id"], 0),
            "has_failed": r["id"] in failed,
            "awaiting_reply": awaiting,
            "overdue": overdue,
        })
    return out


def _serialize_message(m: dict, atts: list[dict]) -> dict:
    return {
        "type": "message",
        "id": m["id"],
        "at": m["date"],
        "direction": m["direction"],
        "kind": m["kind"],
        "channel_id": m["channel_id"],
        "from_name": m["from_name"],
        "from_handle": m["from_handle"],
        "to": db.jload(m["to_json"], []),
        "cc": db.jload(m["cc_json"], []),
        "bcc": db.jload(m["bcc_json"], []) if m["direction"] == "out" else [],
        "reply_to": m["reply_to"],
        "subject": m["subject"],
        "body_html": m["body_html"],
        "body_text": m["body_text"],
        "snippet": m["snippet"],
        "author_id": m["author_id"],
        "contact_id": m["contact_id"],
        "status": m["status"],
        "scheduled_at": m["scheduled_at"],
        "sent_at": m["sent_at"],
        "opened_at": m["opened_at"],
        "error": m["error"],
        "is_auto": bool(m["is_auto"]),
        "has_raw": bool(m["raw_key"]),
        "attachments": [files.serialize(a) for a in atts],
    }


def detail(user: dict, cid: int) -> dict:
    conv = inbox.get_for(user, cid)
    row = db.one(
        "SELECT c.*, cu.in_inbox AS my_in_inbox, cu.starred AS my_starred, cu.last_read_at AS my_last_read_at, "
        "cu.following AS my_following FROM conversations c LEFT JOIN conversation_users cu "
        "ON cu.conversation_id = c.id AND cu.user_id = ? WHERE c.id = ?",
        user["id"], cid,
    )
    summary = summaries(user, [row])[0]
    messages = db.query("SELECT * FROM messages WHERE conversation_id = ? AND status != 'cancelled' ORDER BY date, id", cid)
    msg_atts = files.for_owners("message", [m["id"] for m in messages])
    comments = db.query("SELECT * FROM comments WHERE conversation_id = ? AND deleted_at IS NULL ORDER BY created_at, id", cid)
    comment_atts = files.for_owners("comment", [c["id"] for c in comments])
    comment_reacts = reactions.for_targets("comment", [c["id"] for c in comments])
    events = db.query("SELECT * FROM conversation_events WHERE conversation_id = ? ORDER BY created_at, id", cid)
    timeline = [_serialize_message(m, msg_atts.get(m["id"], [])) for m in messages]
    timeline += [{
        "type": "comment", "id": c["id"], "at": c["created_at"], "user_id": c["user_id"], "body": c["body"],
        "edited_at": c["edited_at"], "attachments": [files.serialize(a) for a in comment_atts.get(c["id"], [])],
        "reactions": comment_reacts.get(c["id"], []),
    } for c in comments]
    timeline += [{
        "type": "event", "id": e["id"], "at": e["created_at"], "user_id": e["user_id"], "event": e["type"],
        "data": db.jload(e["data_json"], {}),
    } for e in events]
    order = {"message": 0, "comment": 1, "event": 2}
    timeline.sort(key=lambda t: (t["at"], order[t["type"]], t["id"]))
    drafts = db.query("SELECT * FROM drafts WHERE conversation_id = ? AND (is_shared = 1 OR created_by = ?) ORDER BY id",
                      cid, user["id"])
    contact = contacts_svc.get(conv["contact_id"])
    contact_out = contacts_svc.summary(contact)
    if contact_out:
        contact_out["handles"] = contacts_svc.handles(contact["id"])
        contact_out["notes"] = contact.get("notes")
    reminders = db.query("SELECT * FROM reminders WHERE conversation_id = ? AND user_id = ? AND done_at IS NULL ORDER BY remind_at",
                         cid, user["id"])
    summary.update({
        "followers": inbox.followers(cid),
        "created_by": conv["created_by"],
        "closed_by": conv["closed_by"],
        "closed_at": conv["closed_at"],
        "snoozed_by": conv["snoozed_by"],
        "merged_into_id": conv["merged_into_id"],
        "first_response_at": conv["first_response_at"],
        "last_inbound_at": conv["last_inbound_at"],
        "last_outbound_at": conv["last_outbound_at"],
        "thread_key": conv["thread_key"],
    })
    return {
        "conversation": summary,
        "timeline": timeline,
        "drafts": [serialize_draft(d) for d in drafts],
        "contact": contact_out,
        "reminders": reminders,
        "viewers": realtime.presence.viewers(f"conversation:{cid}"),
    }


def counts(user: dict) -> dict:
    uid = user["id"]
    clause, vparams = inbox.visibility_clause(user)
    stamp = now_iso()
    base = (f"FROM conversations c LEFT JOIN conversation_users cu ON cu.conversation_id = c.id AND cu.user_id = ? "
            f"WHERE {clause} AND ")
    inbox_row = db.one(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN cu.last_read_at IS NULL OR cu.last_read_at < c.last_activity_at THEN 1 ELSE 0 END) AS unread "
        + base + f"cu.in_inbox = 1 AND {LIVE} AND {UNSNOOZED}",
        [uid, *vparams, stamp],
    )
    assigned = db.one(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN cu.last_read_at IS NULL OR cu.last_read_at < c.last_activity_at THEN 1 ELSE 0 END) AS unread "
        + base + "EXISTS (SELECT 1 FROM conversation_assignees a WHERE a.conversation_id = c.id AND a.user_id = ?) "
        f"AND c.status = 'open' AND {LIVE} AND {UNSNOOZED}",
        [uid, *vparams, uid, stamp],
    )
    drafts = db.scalar("SELECT COUNT(*) FROM drafts WHERE created_by = ?", uid)
    scheduled = db.scalar("SELECT COUNT(*) FROM messages WHERE author_id = ? AND status = 'scheduled'", uid)
    team_rows = db.query(
        "SELECT c.team_id, COUNT(*) AS open, "
        "SUM(CASE WHEN NOT EXISTS (SELECT 1 FROM conversation_assignees a WHERE a.conversation_id = c.id) THEN 1 ELSE 0 END) AS unassigned "
        + base + f"c.team_id IS NOT NULL AND c.status = 'open' AND {LIVE} AND {UNSNOOZED} GROUP BY c.team_id",
        [uid, *vparams, stamp],
    )
    label_rows = db.query(
        "SELECT cl.label_id, COUNT(*) AS open FROM conversation_labels cl JOIN conversations c ON c.id = cl.conversation_id "
        f"WHERE {clause} AND c.status = 'open' AND {LIVE} GROUP BY cl.label_id",
        vparams,
    )
    return {
        "inbox": inbox_row["total"] or 0,
        "inbox_unread": inbox_row["unread"] or 0,
        "assigned": assigned["total"] or 0,
        "assigned_unread": assigned["unread"] or 0,
        "drafts": drafts,
        "scheduled": scheduled,
        "teams": {str(r["team_id"]): {"open": r["open"], "unassigned": r["unassigned"] or 0} for r in team_rows},
        "labels": {str(r["label_id"]): r["open"] for r in label_rows},
    }


def new_drafts(user: dict) -> list[dict]:
    """Compose drafts that don't belong to a conversation yet."""
    rows = db.query("SELECT * FROM drafts WHERE conversation_id IS NULL AND created_by = ? ORDER BY updated_at DESC", user["id"])
    return [serialize_draft(d) for d in rows]


def contact_history(user: dict, contact_id: int, exclude: int | None = None, limit: int = 10) -> list[dict]:
    clause, vparams = inbox.visibility_clause(user)
    rows = db.query(
        "SELECT c.*, cu.in_inbox AS my_in_inbox, cu.starred AS my_starred, cu.last_read_at AS my_last_read_at, "
        "cu.following AS my_following FROM conversations c LEFT JOIN conversation_users cu "
        f"ON cu.conversation_id = c.id AND cu.user_id = ? WHERE c.contact_id = ? AND c.id != ? AND {clause} "
        "AND c.deleted_at IS NULL AND c.merged_into_id IS NULL ORDER BY c.last_activity_at DESC LIMIT ?",
        [user["id"], contact_id, exclude or 0, *vparams, limit],
    )
    return summaries(user, rows)


__all__ = ["list_conversations", "detail", "counts", "parse_query", "summaries", "iso"]
