"""Automation rules: when something happens in the inbox, check conditions, then act.

Triggers
  incoming          every inbound message (hook message.received)
  new_conversation  inbound messages that start a conversation
  outgoing          a teammate sends a message (hook message.queued; automated ones skipped)
  comment           a teammate comments (hook comment.created)

A rule has conditions {field, op, value} combined with match 'all' | 'any', and
an ordered list of actions {type, ...params}. Rules run in ``position`` order; a rule
with stop_processing (or a 'stop' action) ends the run.

Rules never trigger other rules: actions taken while rules run (a comment, an
auto-reply) don't start another round. Each rule runs at most once per message, and
auto-replies go out at most once per contact per rule per 24 hours, never to automated
mail or to our own addresses.
"""

from __future__ import annotations

import html as htmllib
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import requests

from pps_tools.switchboard import db
from pps_tools.switchboard.services import contacts as contacts_svc
from pps_tools.switchboard.services import files, hooks, inbox, notify, outbox, settings
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.services.sanitize import sanitize
from pps_tools.switchboard.util import (
    html_to_text, iso, norm_email, now, now_iso, parse_address_list, snippet,
)
from pps_tools.switchboard.web import ApiError, bad_request

logger = logging.getLogger(__name__)

TRIGGERS = {
    "incoming": "A message comes in",
    "new_conversation": "A new conversation starts",
    "outgoing": "A teammate sends a message",
    "comment": "A teammate comments",
}

TEXT_OPS = ("contains", "not_contains", "equals", "starts_with", "ends_with", "matches")
FIELD_OPS: dict[str, tuple[str, ...]] = {
    "from": TEXT_OPS,
    "to": TEXT_OPS,
    "cc": TEXT_OPS,
    "subject": TEXT_OPS,
    "body": TEXT_OPS,
    "channel": ("is", "is_not"),
    "channel_type": ("is", "is_not"),
    "has_attachment": ("is",),
    "is_reply": ("is",),
    "label": ("has", "lacks"),
    "assigned": ("is",),
    "team": ("is", "is_not"),
    "contact_group": ("in", "not_in"),
    "business_hours": ("is",),
    "weekday": ("is", "is_not"),
    "priority": ("is", "is_not"),
}

ACTION_TYPES = (
    "assign", "unassign", "add_label", "remove_label", "move_team", "close", "reopen", "snooze", "priority",
    "spam", "trash", "auto_reply", "add_comment", "forward", "notify", "webhook", "stop",
)
# Safe to replay on existing conversations ("Apply to existing").
BULK_SAFE = {"assign", "unassign", "add_label", "remove_label", "move_team", "close", "snooze", "priority", "spam", "trash"}

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
AUTO_REPLY_WINDOW = timedelta(hours=24)
WEBHOOK_TIMEOUT = 10

_state = threading.local()


# -- validation -----------------------------------------------------------------------


def _ids(value) -> list[int]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        value = [value]
    out = []
    for v in value:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            bad_request(f"'{v}' isn't a valid id", code="validation")
    return out


def validate_condition(c: dict) -> dict:
    if not isinstance(c, dict):
        bad_request("Each condition must be an object", code="validation")
    fld, op, value = c.get("field"), c.get("op"), c.get("value")
    if fld not in FIELD_OPS:
        bad_request(f"Unknown condition field '{fld}'", code="validation")
    if op not in FIELD_OPS[fld]:
        bad_request(f"'{op}' doesn't work with '{fld}'", code="validation")
    if fld in ("from", "to", "cc", "subject", "body"):
        if op == "matches":
            try:
                re.compile(str(value or ""))
            except re.error as exc:
                bad_request(f"Invalid pattern: {exc}", code="validation")
        if not str(value or "").strip() and not isinstance(value, list):
            bad_request(f"Enter text to match for '{fld}'", code="validation")
    elif fld in ("channel", "label", "contact_group"):
        value = _ids(value)
        if not value:
            bad_request(f"Choose a value for '{fld}'", code="validation")
    elif fld == "team":
        value = None if value in (None, "", "none") else _ids(value)
    elif fld in ("has_attachment", "is_reply", "assigned"):
        value = value in (True, "true", "yes", 1, "1")
    elif fld == "business_hours":
        if value not in ("inside", "outside"):
            bad_request("business_hours must be 'inside' or 'outside'", code="validation")
    elif fld == "weekday":
        days = value if isinstance(value, list) else [value]
        if not days or any(d not in DAY_KEYS for d in days):
            bad_request("weekday values are mon…sun", code="validation")
        value = days
    elif fld == "channel_type":
        types = value if isinstance(value, list) else [value]
        if not types or any(t not in ("email", "sms", "whatsapp", "chat", "api") for t in types):
            bad_request("Unknown channel type", code="validation")
        value = types
    elif fld == "priority":
        vals = value if isinstance(value, list) else [value]
        if any(v not in ("low", "normal", "high", "urgent") for v in vals):
            bad_request("Unknown priority", code="validation")
        value = vals
    return {"field": fld, "op": op, "value": value}


def validate_action(a: dict) -> dict:
    if not isinstance(a, dict) or a.get("type") not in ACTION_TYPES:
        bad_request(f"Unknown action '{(a or {}).get('type') if isinstance(a, dict) else a}'", code="validation")
    t = a["type"]
    out = {"type": t}
    if t == "assign":
        mode = a.get("mode") or "users"
        if mode not in ("users", "round_robin", "load_balanced", "on_shift"):
            bad_request("Unknown assignment mode", code="validation")
        out["mode"] = mode
        if mode == "users":
            out["user_ids"] = _ids(a.get("user_ids"))
            if not out["user_ids"]:
                bad_request("Pick who to assign", code="validation")
        else:
            out["team_id"] = (_ids(a.get("team_id")) or [None])[0]
    elif t in ("add_label", "remove_label"):
        out["label_ids"] = _ids(a.get("label_ids"))
        if not out["label_ids"]:
            bad_request("Pick at least one label", code="validation")
    elif t == "move_team":
        out["team_id"] = (_ids(a.get("team_id")) or [None])[0]
    elif t == "snooze":
        try:
            minutes = int(a.get("minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0
        if minutes <= 0:
            bad_request("Snooze for at least a minute", code="validation")
        out["minutes"] = minutes
    elif t == "priority":
        if a.get("value") not in ("low", "normal", "high", "urgent"):
            bad_request("Unknown priority", code="validation")
        out["value"] = a["value"]
    elif t == "auto_reply":
        if a.get("response_id"):
            out["response_id"] = _ids(a["response_id"])[0]
        elif (a.get("body_html") or "").strip():
            out["body_html"] = sanitize(a["body_html"], "basic")
            out["subject"] = (a.get("subject") or "").strip() or None
        else:
            bad_request("Choose a canned response or write the reply", code="validation")
    elif t == "add_comment":
        body = sanitize(a.get("body_html") or "", "basic")
        if not html_to_text(body).strip():
            bad_request("Write the comment", code="validation")
        out["body_html"] = body
    elif t == "forward":
        recipients = parse_address_list(a.get("to"))
        if not recipients or not all(norm_email(p["handle"]) for p in recipients):
            bad_request("Enter a valid email address to forward to", code="validation")
        out["to"] = ", ".join(p["handle"] for p in recipients)
    elif t == "notify":
        out["user_ids"] = _ids(a.get("user_ids"))
        if not out["user_ids"]:
            bad_request("Pick who to notify", code="validation")
        out["note"] = (a.get("note") or "").strip()[:300] or None
    elif t == "webhook":
        url = (a.get("url") or "").strip()
        if not re.match(r"^https?://", url):
            bad_request("The webhook URL must start with http:// or https://", code="validation")
        out["url"] = url
    return out


def normalize(data: dict, partial: bool = False) -> dict:
    """Request body -> column values for the rules table."""
    out: dict = {}
    if "name" in data or not partial:
        name = (data.get("name") or "").strip()
        if not name:
            bad_request("Give the rule a name", code="validation")
        out["name"] = name[:120]
    if "trigger" in data or not partial:
        trigger = data.get("trigger") or "incoming"
        if trigger not in TRIGGERS:
            bad_request("Unknown trigger", code="validation")
        out["trigger"] = trigger
    if "match" in data:
        if data["match"] not in ("all", "any"):
            bad_request("match must be 'all' or 'any'", code="validation")
        out["match"] = data["match"]
    if "conditions" in data or not partial:
        conds = data.get("conditions") or []
        if not isinstance(conds, list):
            bad_request("conditions must be a list", code="validation")
        out["conditions_json"] = db.jdump([validate_condition(c) for c in conds])
    if "actions" in data or not partial:
        acts = data.get("actions") or []
        if not isinstance(acts, list) or not acts:
            bad_request("Add at least one action", code="validation")
        out["actions_json"] = db.jdump([validate_action(a) for a in acts])
    if "is_active" in data:
        out["is_active"] = 1 if data["is_active"] in (True, 1, "1", "true") else 0
    if "stop_processing" in data:
        out["stop_processing"] = 1 if data["stop_processing"] in (True, 1, "1", "true") else 0
    return out


def serialize(rule: dict) -> dict:
    return {
        "id": rule["id"],
        "name": rule["name"],
        "is_active": bool(rule["is_active"]),
        "trigger": rule["trigger"],
        "match": rule["match"],
        "conditions": db.jload(rule["conditions_json"], []),
        "actions": db.jload(rule["actions_json"], []),
        "stop_processing": bool(rule["stop_processing"]),
        "position": rule["position"],
        "run_count": rule["run_count"],
        "last_run_at": rule["last_run_at"],
        "created_by": rule["created_by"],
        "created_at": rule["created_at"],
        "updated_at": rule["updated_at"],
    }


# -- context --------------------------------------------------------------------------


@dataclass
class Context:
    trigger: str
    conversation: dict
    message: dict | None = None
    comment: dict | None = None
    is_new: bool = False
    at: datetime = field(default_factory=now)
    _cache: dict = field(default_factory=dict)

    @property
    def cid(self) -> int:
        return self.conversation["id"]

    @property
    def channel(self) -> dict | None:
        if "channel" not in self._cache:
            cid = (self.message or {}).get("channel_id") or self.conversation.get("channel_id")
            self._cache["channel"] = db.one("SELECT * FROM channels WHERE id = ?", cid) if cid else None
        return self._cache["channel"]

    @property
    def contact(self) -> dict | None:
        if "contact" not in self._cache:
            contact_id = (self.message or {}).get("contact_id") or self.conversation.get("contact_id")
            self._cache["contact"] = contacts_svc.get(contact_id)
        return self._cache["contact"]

    @property
    def labels(self) -> set[int]:
        if "labels" not in self._cache:
            self._cache["labels"] = set(db.column("SELECT label_id FROM conversation_labels WHERE conversation_id = ?", self.cid))
        return self._cache["labels"]

    @property
    def assignees(self) -> list[int]:
        return inbox.assignees(self.cid)

    @property
    def groups(self) -> set[int]:
        if "groups" not in self._cache:
            contact = self.contact
            self._cache["groups"] = set(db.column(
                "SELECT group_id FROM contact_group_members WHERE contact_id = ?", contact["id"])) if contact else set()
        return self._cache["groups"]

    def texts(self, fld: str) -> list[str]:
        m = self.message
        if fld == "from":
            if m:
                return [x for x in (m.get("from_handle"), m.get("from_name")) if x]
            if self.comment:
                author = users_svc.get(self.comment.get("user_id"))
                return [x for x in ((author or {}).get("email"), (author or {}).get("name")) if x]
            return []
        if fld in ("to", "cc"):
            people = db.jload((m or {}).get(f"{fld}_json"), []) or []
            return [x for p in people for x in (p.get("handle"), p.get("name")) if x]
        if fld == "subject":
            return [x for x in ((m or {}).get("subject"), self.conversation.get("subject")) if x]
        if fld == "body":
            if self.comment:
                return [html_to_text(self.comment.get("body"))]
            return [((m or {}).get("body_text") or "")[:20000]]
        return []

    def has_attachment(self) -> bool:
        if not self.message:
            return False
        return bool(db.one("SELECT 1 AS x FROM attachments WHERE owner_type = 'message' AND owner_id = ? AND is_inline = 0",
                           self.message["id"]))


def build_context(trigger: str, conversation_id: int, message_id: int | None = None,
                  comment_id: int | None = None, is_new: bool = False) -> Context | None:
    conv = inbox.get(conversation_id)
    if not conv:
        return None
    message = db.one("SELECT * FROM messages WHERE id = ?", message_id) if message_id else None
    comment = db.one("SELECT * FROM comments WHERE id = ?", comment_id) if comment_id else None
    return Context(trigger=trigger, conversation=conv, message=message, comment=comment, is_new=is_new)


# -- conditions -----------------------------------------------------------------------


def in_business_hours(at: datetime | None = None) -> bool:
    local = (at or now()).astimezone(settings.timezone())
    if local.date().isoformat() in (settings.get("org.holidays") or []):
        return False
    ranges = (settings.get("org.business_hours") or {}).get(DAY_KEYS[local.weekday()], []) or []
    hhmm = local.strftime("%H:%M")
    return any(start <= hhmm < end for start, end in ranges)


def _keywords(value) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"[,\n]", str(value or ""))
    return [str(i).strip().lower() for i in items if str(i).strip()]


def _text_match(op: str, candidates: list[str], value) -> bool:
    texts = [c.lower() for c in candidates if c]
    if op == "matches":
        try:
            pattern = re.compile(str(value), re.I)
        except re.error:
            return False
        return any(pattern.search(t) for t in texts)
    words = _keywords(value)
    if not words:
        return False
    if op == "contains":
        return any(w in t for w in words for t in texts)
    if op == "not_contains":
        return not any(w in t for w in words for t in texts)
    if op == "equals":
        return any(w == t.strip() for w in words for t in texts)
    if op == "starts_with":
        return any(t.startswith(w) for w in words for t in texts)
    if op == "ends_with":
        return any(t.endswith(w) for w in words for t in texts)
    return False


def condition_matches(cond: dict, ctx: Context) -> bool:
    fld, op, value = cond["field"], cond["op"], cond.get("value")
    if fld in ("from", "to", "cc", "subject", "body"):
        return _text_match(op, ctx.texts(fld), value)
    if fld == "channel":
        hit = ((ctx.channel or {}).get("id")) in set(_ids(value))
        return hit if op == "is" else not hit
    if fld == "channel_type":
        types = value if isinstance(value, list) else [value]
        hit = (ctx.channel or {}).get("type") in types
        return hit if op == "is" else not hit
    if fld == "has_attachment":
        return ctx.has_attachment() == bool(value)
    if fld == "is_reply":
        is_reply = not ctx.is_new if ctx.message else True
        return is_reply == bool(value)
    if fld == "label":
        hit = bool(ctx.labels & set(_ids(value)))
        return hit if op == "has" else not hit
    if fld == "assigned":
        return bool(ctx.assignees) == bool(value)
    if fld == "team":
        team = ctx.conversation.get("team_id")
        hit = (team is None) if not value else team in set(_ids(value))
        return hit if op == "is" else not hit
    if fld == "contact_group":
        hit = bool(ctx.groups & set(_ids(value)))
        return hit if op == "in" else not hit
    if fld == "business_hours":
        inside = in_business_hours(ctx.at)
        return inside if value == "inside" else not inside
    if fld == "weekday":
        day = DAY_KEYS[ctx.at.astimezone(settings.timezone()).weekday()]
        hit = day in (value if isinstance(value, list) else [value])
        return hit if op == "is" else not hit
    if fld == "priority":
        hit = ctx.conversation.get("priority") in (value if isinstance(value, list) else [value])
        return hit if op == "is" else not hit
    return False


def evaluate(rule: dict, ctx: Context) -> tuple[bool, list[dict]]:
    conditions = db.jload(rule["conditions_json"], []) or []
    results = [{**c, "matched": condition_matches(c, ctx)} for c in conditions]
    if not results:
        return True, results
    if rule["match"] == "any":
        return any(r["matched"] for r in results), results
    return all(r["matched"] for r in results), results


# -- actions --------------------------------------------------------------------------


def _author(rule: dict) -> dict | None:
    """Who automated messages and comments are sent as: the rule's creator, else an owner."""
    user = users_svc.get(rule.get("created_by"))
    if user and user["is_active"]:
        return user
    return db.one("SELECT * FROM users WHERE is_active = 1 AND role IN ('owner', 'admin') ORDER BY role = 'owner' DESC, id LIMIT 1")


def _restore_state(cid: int, uid: int, before: dict) -> None:
    """Sending as someone makes them follow and mark read; automation shouldn't."""
    inbox.set_user_state(cid, uid, following=before.get("following", 0), in_inbox=before.get("in_inbox", 0),
                         last_read_at=before.get("last_read_at"))


def _reply_handle(ctx: Context) -> tuple[str | None, str | None]:
    m = ctx.message or {}
    ch_type = (ctx.channel or {}).get("type")
    if ch_type == "chat":
        return ctx.conversation.get("thread_key"), m.get("from_name")
    if ch_type == "email":
        return (m.get("reply_to") or m.get("from_handle")), m.get("from_name")
    return m.get("from_handle"), m.get("from_name")


def _render(rule_action: dict, author: dict, conv: dict) -> tuple[str | None, str]:
    from pps_tools.switchboard.api.inbox import render_response

    if rule_action.get("response_id"):
        row = db.one("SELECT * FROM canned_responses WHERE id = ?", rule_action["response_id"])
        if not row:
            raise ValueError("The canned response no longer exists")
        out = render_response(row, author, conv)
        db.execute("UPDATE canned_responses SET usage_count = usage_count + 1 WHERE id = ?", row["id"])
    else:
        out = render_response({"subject": rule_action.get("subject"), "body_html": rule_action.get("body_html") or ""},
                              author, conv)
    return out["subject"], out["body_html"]


def _auto_reply(rule: dict, action: dict, ctx: Context) -> str:
    m = ctx.message
    if ctx.trigger not in ("incoming", "new_conversation") or not m or m["direction"] != "in":
        return "skipped: only replies to incoming messages"
    if m["is_auto"]:
        return "skipped: the message was automated (auto-reply, newsletter or bounce)"
    handle, name = _reply_handle(ctx)
    if not handle:
        return "skipped: no address to reply to"
    if handle.lower() in outbox.own_addresses():
        return "skipped: won't auto-reply to our own address"
    contact_id = m.get("contact_id") or ctx.conversation.get("contact_id")
    if contact_id and db.one(
        "SELECT 1 AS x FROM rule_runs WHERE rule_id = ? AND contact_id = ? AND auto_replied = 1 AND created_at >= ?",
        rule["id"], contact_id, iso(now() - AUTO_REPLY_WINDOW),
    ):
        return "skipped: already auto-replied to this contact in the last 24 hours"
    author = _author(rule)
    if not author or not ctx.channel:
        return "skipped: nobody to send as"
    subject, body = _render(action, author, ctx.conversation)
    with db.transaction():
        before = inbox.user_state(ctx.cid, author["id"])
        msg = outbox.send_new(author, ctx.channel["id"], [{"name": name, "handle": handle}], subject, body,
                              conversation_id=ctx.cid, is_auto=True)
        db.update("messages", msg["id"], {"is_auto": 1})
        _restore_state(ctx.cid, author["id"], before)
    ctx._cache["auto_replied"] = True
    return f"replied to {handle}"


def _forward(rule: dict, action: dict, ctx: Context) -> str:
    author = _author(rule)
    if not author:
        return "skipped: nobody to send as"
    channel = ctx.channel if (ctx.channel or {}).get("type") == "email" else None
    if not channel or not outbox.can_send_from(author, channel):
        channel = next((c for c in outbox.sendable_channels(author) if c["type"] == "email"), None)
    if not channel:
        return "skipped: no email account to forward from"
    m = ctx.message or {}
    subject = "Fwd: " + (m.get("subject") or ctx.conversation.get("subject") or "message")
    original = m.get("body_html") or htmllib.escape(m.get("body_text") or "").replace("\n", "<br>")
    body = (
        "<p>---------- Forwarded message ----------<br>"
        f"From: {htmllib.escape(m.get('from_name') or '')} &lt;{htmllib.escape(m.get('from_handle') or '')}&gt;<br>"
        f"Subject: {htmllib.escape(m.get('subject') or '')}</p>{original}"
    )
    attachment_ids = []
    if m.get("id"):
        for att in files.for_owner("message", m["id"]):
            if not att["is_inline"]:
                copy = files.save_bytes(files.read_bytes(att), att["filename"], att["content_type"], author["id"])
                attachment_ids.append(copy["id"])
    with db.transaction():
        before = inbox.user_state(ctx.cid, author["id"])
        msg = outbox.send_new(author, channel["id"], action["to"], subject, body, conversation_id=ctx.cid,
                              attachment_ids=attachment_ids, is_auto=True)
        db.update("messages", msg["id"], {"is_auto": 1})
        _restore_state(ctx.cid, author["id"], before)
    return f"forwarded to {action['to']}"


def _webhook(rule: dict, action: dict, ctx: Context) -> str:
    m = ctx.message or {}
    payload = {
        "event": "rule.matched",
        "rule": {"id": rule["id"], "name": rule["name"]},
        "trigger": ctx.trigger,
        "conversation": {"id": ctx.cid, "subject": ctx.conversation.get("subject"), "status": ctx.conversation.get("status"),
                         "url": f"/inbox/c/{ctx.cid}"},
        "message": {"id": m.get("id"), "from": m.get("from_handle"), "from_name": m.get("from_name"),
                    "subject": m.get("subject"), "snippet": m.get("snippet")} if m else None,
        "contact": contacts_svc.summary(ctx.contact),
        "at": now_iso(),
    }

    def post():
        try:
            requests.post(action["url"], json=payload, timeout=WEBHOOK_TIMEOUT, headers={"User-Agent": "Switchboard"})
        except requests.RequestException as exc:
            logger.warning("Rule webhook to %s failed: %s", action["url"], exc)

    threading.Thread(target=post, name="rule-webhook", daemon=True).start()
    return f"posted to {action['url']}"


def run_action(rule: dict, action: dict, ctx: Context) -> str:
    t = action["type"]
    cid = ctx.cid
    if t == "assign":
        with db.transaction():
            if action.get("mode", "users") == "users":
                added, _ = inbox.assign(cid, action.get("user_ids") or [], by=None, mode="add")
            else:
                team_id = action.get("team_id") or ctx.conversation.get("team_id")
                if not team_id:
                    return "skipped: the conversation has no team"
                uid = inbox.pick_assignee(team_id, action["mode"])
                if not uid:
                    return "skipped: nobody available"
                added, _ = inbox.assign(cid, [uid], by=None, mode="add")
            inbox.touch(cid, "assigned")
        return "assigned " + (", ".join(users_svc.name_of(u) for u in added) or "(no change)")
    if t == "unassign":
        with db.transaction():
            inbox.assign(cid, [], by=None, mode="set")
            inbox.touch(cid, "assigned")
        return "unassigned"
    if t in ("add_label", "remove_label"):
        ids = action.get("label_ids") or []
        with db.transaction():
            inbox.set_labels(None, cid, ids if t == "add_label" else [], ids if t == "remove_label" else [])
            inbox.touch(cid, "label")
        ctx._cache.pop("labels", None)
        return ("added" if t == "add_label" else "removed") + " labels"
    if t == "move_team":
        inbox.system_action(cid, "team", {"team_id": action.get("team_id")})
        return "moved"
    if t in ("close", "reopen", "spam", "trash"):
        inbox.system_action(cid, t, {})
        return t
    if t == "snooze":
        inbox.system_action(cid, "snooze", {"until": iso(now() + timedelta(minutes=action["minutes"]))})
        return f"snoozed {action['minutes']} min"
    if t == "priority":
        inbox.system_action(cid, "priority", {"value": action["value"]})
        return f"priority {action['value']}"
    if t == "auto_reply":
        return _auto_reply(rule, action, ctx)
    if t == "forward":
        return _forward(rule, action, ctx)
    if t == "add_comment":
        author = _author(rule)
        if not author:
            return "skipped: nobody to comment as"
        body = f"<p><b>⚡ {htmllib.escape(rule['name'])}</b></p>" + action["body_html"]
        before = inbox.user_state(cid, author["id"])
        inbox.add_comment(author, cid, body)
        with db.transaction():
            _restore_state(cid, author["id"], before)
        return "commented"
    if t == "notify":
        title = inbox.title_of(ctx.conversation)
        with db.transaction():
            notify.notify(action["user_ids"], "system", f"{rule['name']}: {title}",
                          body=action.get("note") or ctx.conversation.get("preview"), link=inbox.link(cid),
                          entity_type="conversation", entity_id=cid)
        return "notified"
    if t == "webhook":
        return _webhook(rule, action, ctx)
    if t == "stop":
        return "stopped"
    return "skipped: unknown action"


def execute(rule: dict, ctx: Context, allowed: set[str] | None = None) -> tuple[list[dict], bool]:
    """Run a matched rule's actions. Returns (results, stop_further_rules)."""
    results = []
    stop = bool(rule["stop_processing"])
    for action in db.jload(rule["actions_json"], []) or []:
        if allowed is not None and action["type"] not in allowed:
            continue
        try:
            detail = run_action(rule, action, ctx)
            results.append({"type": action["type"], "ok": not detail.startswith("skipped"), "detail": detail})
        except ApiError as exc:
            results.append({"type": action["type"], "ok": False, "detail": exc.message})
        except Exception as exc:  # one broken action mustn't stop the others
            logger.exception("Rule %s action %s failed", rule["id"], action["type"])
            results.append({"type": action["type"], "ok": False, "detail": str(exc)})
        if action["type"] == "stop":
            stop = True
            break
    return results, stop


def _record(rule: dict, ctx: Context, results: list[dict]) -> None:
    stamp = now_iso()
    with db.transaction():
        db.insert("rule_runs", {
            "rule_id": rule["id"], "trigger": ctx.trigger, "conversation_id": ctx.cid,
            "message_id": (ctx.message or {}).get("id"), "comment_id": (ctx.comment or {}).get("id"),
            "contact_id": (ctx.contact or {}).get("id"), "actions_json": db.jdump(results),
            "auto_replied": 1 if ctx._cache.pop("auto_replied", False) else 0, "created_at": stamp,
        })
        db.execute("UPDATE rules SET run_count = run_count + 1, last_run_at = ? WHERE id = ?", stamp, rule["id"])
        inbox.add_event(ctx.cid, "rule_applied", None, {
            "rule_id": rule["id"], "name": rule["name"],
            "actions": [r["type"] for r in results if r["ok"]],
        })
        inbox.touch(ctx.cid, "rule")


def _already_ran(rule: dict, ctx: Context) -> bool:
    if ctx.message:
        return db.one("SELECT 1 AS x FROM rule_runs WHERE rule_id = ? AND message_id = ?", rule["id"], ctx.message["id"]) is not None
    if ctx.comment:
        return db.one("SELECT 1 AS x FROM rule_runs WHERE rule_id = ? AND comment_id = ?", rule["id"], ctx.comment["id"]) is not None
    return False


def run(ctx: Context) -> list[int]:
    """Evaluate and apply every active rule for this event. Returns ids of rules that ran."""
    if getattr(_state, "running", False):
        return []
    if ctx.conversation.get("is_spam") or ctx.conversation.get("deleted_at"):
        return []
    triggers = [ctx.trigger]
    if ctx.trigger == "incoming" and ctx.is_new:
        triggers.append("new_conversation")
    rules = db.query(
        f"SELECT * FROM rules WHERE is_active = 1 AND trigger IN ({db.placeholders(triggers)}) ORDER BY position, id",
        triggers,
    )
    ran = []
    _state.running = True
    try:
        for rule in rules:
            if _already_ran(rule, ctx):
                continue
            matched, _ = evaluate(rule, ctx)
            if not matched:
                continue
            results, stop = execute(rule, ctx)
            _record(rule, ctx, results)
            ran.append(rule["id"])
            ctx.conversation = inbox.get(ctx.cid) or ctx.conversation
            if stop:
                break
    finally:
        _state.running = False
    return ran


# -- hooks ----------------------------------------------------------------------------


def on_message_received(payload: dict) -> None:
    ctx = build_context("incoming", payload["conversation_id"], message_id=payload["message_id"],
                        is_new=bool(payload.get("is_new_conversation")))
    if ctx:
        run(ctx)


def on_message_queued(payload: dict) -> None:
    msg = db.one("SELECT is_auto FROM messages WHERE id = ?", payload["message_id"])
    if not msg or msg["is_auto"]:
        return
    ctx = build_context("outgoing", payload["conversation_id"], message_id=payload["message_id"],
                        is_new=bool(payload.get("is_new_conversation")))
    if ctx:
        run(ctx)


def on_comment_created(payload: dict) -> None:
    ctx = build_context("comment", payload["conversation_id"], comment_id=payload["comment_id"])
    if ctx:
        run(ctx)


def register_hooks() -> None:
    hooks.on("message.received", on_message_received)
    hooks.on("message.queued", on_message_queued)
    hooks.on("comment.created", on_comment_created)


# -- previews -------------------------------------------------------------------------


def _label_names(ids) -> str:
    rows = db.query(f"SELECT name FROM labels WHERE id IN ({db.placeholders(ids)})", list(ids)) if ids else []
    return ", ".join(r["name"] for r in rows) or "(deleted label)"


def _team_name(tid) -> str:
    row = db.one("SELECT name FROM teams WHERE id = ?", tid) if tid else None
    return row["name"] if row else "no team"


def describe_action(action: dict) -> str:
    t = action["type"]
    if t == "assign":
        mode = action.get("mode", "users")
        if mode == "users":
            return "Assign to " + ", ".join(users_svc.name_of(u) for u in action.get("user_ids") or [])
        how = {"round_robin": "round robin", "load_balanced": "least busy", "on_shift": "whoever is on shift"}[mode]
        return f"Assign {how} in {_team_name(action.get('team_id')) if action.get('team_id') else 'its team'}"
    if t == "unassign":
        return "Remove assignees"
    if t == "add_label":
        return "Add label " + _label_names(action.get("label_ids") or [])
    if t == "remove_label":
        return "Remove label " + _label_names(action.get("label_ids") or [])
    if t == "move_team":
        return "Move to " + _team_name(action.get("team_id"))
    if t == "snooze":
        minutes = action.get("minutes") or 0
        return f"Snooze for {minutes // 60} h" if minutes % 60 == 0 and minutes >= 60 else f"Snooze for {minutes} min"
    if t == "priority":
        return f"Set priority to {action.get('value')}"
    if t == "auto_reply":
        if action.get("response_id"):
            row = db.one("SELECT title FROM canned_responses WHERE id = ?", action["response_id"])
            return f"Auto-reply with “{row['title'] if row else 'deleted response'}”"
        return "Auto-reply: " + snippet(html_to_text(action.get("body_html")), 60)
    if t == "add_comment":
        return "Comment: " + snippet(html_to_text(action.get("body_html")), 60)
    if t == "forward":
        return f"Forward to {action.get('to')}"
    if t == "notify":
        return "Notify " + ", ".join(users_svc.name_of(u) for u in action.get("user_ids") or [])
    if t == "webhook":
        return f"POST to {action.get('url')}"
    return {"close": "Close", "reopen": "Reopen", "spam": "Mark as spam", "trash": "Move to trash",
            "stop": "Stop processing more rules"}.get(t, t)


def dry_run(rule: dict, conversation_id: int) -> dict:
    """What the rule would do on this conversation's latest message (nothing changes)."""
    conv = inbox.get(conversation_id)
    if not conv:
        bad_request("Conversation not found")
    direction = "out" if rule["trigger"] == "outgoing" else "in"
    message = db.one(
        "SELECT * FROM messages WHERE conversation_id = ? AND direction = ? AND status != 'cancelled' "
        "ORDER BY date DESC, id DESC LIMIT 1", conversation_id, direction,
    )
    comment = None
    if rule["trigger"] == "comment":
        comment = db.one("SELECT * FROM comments WHERE conversation_id = ? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
                         conversation_id)
        message = None
    is_new = bool(message) and db.scalar(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND id < ?", conversation_id, message["id"]) == 0
    ctx = Context(trigger=rule["trigger"], conversation=conv, message=message, comment=comment, is_new=is_new)
    matched, results = evaluate(rule, ctx)
    if rule["trigger"] == "new_conversation" and not is_new:
        matched = False
    return {
        "matched": matched,
        "message_id": (message or {}).get("id"),
        "comment_id": (comment or {}).get("id"),
        "conditions": results,
        "actions": [describe_action(a) for a in db.jload(rule["actions_json"], []) or []],
        "note": None if (message or comment) else "This conversation has nothing for this trigger to look at.",
    }


def apply_to_existing(rule: dict, limit: int = 200) -> dict:
    """Replay a rule's safe actions (labels, assignment, team, status) on open
    conversations whose latest inbound message matches."""
    convs = db.query(
        "SELECT * FROM conversations WHERE status = 'open' AND deleted_at IS NULL AND is_spam = 0 "
        "AND merged_into_id IS NULL ORDER BY last_activity_at DESC LIMIT ?", limit,
    )
    applied = 0
    skipped_actions = sorted({a["type"] for a in db.jload(rule["actions_json"], []) or []} - BULK_SAFE)
    _state.running = True
    try:
        for conv in convs:
            message = db.one(
                "SELECT * FROM messages WHERE conversation_id = ? AND direction = 'in' ORDER BY date DESC, id DESC LIMIT 1",
                conv["id"],
            )
            if not message:
                continue
            ctx = Context(trigger="incoming", conversation=conv, message=message, is_new=False)
            matched, _ = evaluate(rule, ctx)
            if not matched:
                continue
            results, _ = execute(rule, ctx, allowed=BULK_SAFE)
            if results:
                _record(rule, ctx, results)
                applied += 1
    finally:
        _state.running = False
    return {"applied": applied, "checked": len(convs), "skipped_actions": skipped_actions}
