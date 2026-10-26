"""Outgoing webhooks: every domain event (see services.hooks) is offered to the active
webhooks subscribed to it, queued in ``webhook_deliveries`` and POSTed by the worker.

Each request carries:
  X-Switchboard-Event: message.received
  X-Switchboard-Delivery: <delivery id>
  X-Switchboard-Signature: sha256=<hex HMAC-SHA256 of the raw body, keyed with the secret>
Body: {"id", "event", "data", "occurred_at", "sent_at"}.

A delivery succeeds on any 2xx. Failures retry after 1 min, 5 min, 30 min and 2 h, then
the delivery is marked failed. Redirects are not followed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import timedelta
from urllib.parse import urlparse

import requests

from pps_tools.switchboard import config, db
from pps_tools.switchboard.util import iso, now, now_iso, token

logger = logging.getLogger(__name__)

BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2))
MAX_ATTEMPTS = len(BACKOFF) + 1
TIMEOUT_SECONDS = 10
LEASE = timedelta(minutes=2)       # a claimed delivery isn't picked up again for this long
KEEP_DAYS = 30

# Shown in the webhook editor; any other event name (or a 'prefix.*' pattern) also works.
EVENT_CATALOG = [
    ("message.received", "A customer message arrived"),
    ("message.queued", "A teammate sent a reply (before the undo window ends)"),
    ("message.sent", "A message left Switchboard"),
    ("message.failed", "A message couldn't be sent"),
    ("conversation.created", "A conversation started"),
    ("conversation.assigned", "Someone was assigned a conversation"),
    ("conversation.unassigned", "Someone was unassigned"),
    ("conversation.closed", "A conversation was closed"),
    ("conversation.reopened", "A conversation was reopened"),
    ("conversation.labeled", "Labels were added to a conversation"),
    ("conversation.merged", "Two conversations were merged"),
    ("comment.created", "A teammate commented on a conversation"),
    ("job.created", "A job was created"),
    ("job.stage_changed", "A job moved to another stage"),
    ("job.completed", "A job reached a done stage"),
    ("shift.published", "Shifts were published"),
    ("timeoff.requested", "Someone requested time off"),
    ("timeoff.decided", "A time-off request was approved or denied"),
    ("timeclock.punch", "Someone clocked in or out"),
]


def new_secret() -> str:
    return "whsec_" + token(24)


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def valid_url(url: str | None) -> bool:
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def matches(patterns: list[str], event: str) -> bool:
    for p in patterns or []:
        p = (p or "").strip()
        if p == "*" or p == event:
            return True
        if p.endswith(".*") and event.startswith(p[:-1]):
            return True
    return False


def serialize(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "url": row["url"],
        "secret": row["secret"],
        "events": db.jload(row["events_json"], ["*"]),
        "is_active": bool(row["is_active"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "last_delivery_at": row["last_delivery_at"],
        "last_status": row["last_status"],
        "last_error": row["last_error"],
    }


def serialize_delivery(row: dict) -> dict:
    payload = db.jload(row["payload_json"], {}) or {}
    return {
        "id": row["id"],
        "webhook_id": row["webhook_id"],
        "event": row["event"],
        "status": row["status"],
        "attempts": row["attempts"],
        "next_attempt_at": row["next_attempt_at"] if row["status"] == "pending" else None,
        "response_code": row["response_code"],
        "error": row["error"],
        "created_at": row["created_at"],
        "payload": payload,
    }


# -- payloads -----------------------------------------------------------------------


def _enrich(data: dict) -> dict:
    """Add cheap context so receivers don't have to call back for the basics."""
    out = dict(data)
    base = config.current().base_url
    # conversation.merged carries source_id/target_id; the target is the one that lives on
    cid = data.get("conversation_id") or (data.get("target_id") if "source_id" in data else None)
    if cid:
        conv = db.one("SELECT id, subject, status, priority, team_id, channel_id, contact_id FROM conversations WHERE id = ?", cid)
        if conv:
            conv["url"] = f"{base}/inbox/c/{conv['id']}"
            out["conversation"] = conv
    if data.get("message_id"):
        msg = db.one(
            "SELECT id, direction, kind, from_name, from_handle, subject, snippet, status, channel_id FROM messages WHERE id = ?",
            data["message_id"],
        )
        if msg:
            out["message"] = msg
    if data.get("job_id"):
        job = db.one("SELECT id, number, title, stage_id, priority, due_at FROM jobs WHERE id = ?", data["job_id"])
        if job:
            job["url"] = f"{base}/jobs/{job['id']}"
            out["job"] = job
    return out


def enqueue(event: str, data: dict) -> int:
    """Queue this event for every active webhook subscribed to it. Returns the count."""
    hooks = [w for w in db.query("SELECT * FROM webhooks WHERE is_active = 1")
             if matches(db.jload(w["events_json"], ["*"]), event)]
    if not hooks:
        return 0
    payload = db.jdump({"event": event, "data": _enrich(data), "occurred_at": now_iso()})
    stamp = now_iso()
    with db.transaction():
        for w in hooks:
            db.insert("webhook_deliveries", {
                "webhook_id": w["id"], "event": event, "payload_json": payload, "status": "pending",
                "attempts": 0, "next_attempt_at": stamp, "created_at": stamp,
            })
    return len(hooks)


def on_event(event: str, payload: dict) -> None:
    """services.hooks wildcard handler."""
    enqueue(event, payload)


# -- sending ------------------------------------------------------------------------


def _claim(delivery_id: int) -> bool:
    """Lease a due delivery so a concurrent sender skips it."""
    lease_until = iso(now() + LEASE)
    return bool(db.execute(
        "UPDATE webhook_deliveries SET next_attempt_at = ? WHERE id = ? AND status = 'pending' AND next_attempt_at <= ?",
        lease_until, delivery_id, now_iso(),
    ).rowcount)


def attempt(delivery_id: int) -> dict:
    """POST one delivery and record the outcome. Returns the updated delivery."""
    row = db.one("SELECT * FROM webhook_deliveries WHERE id = ?", delivery_id)
    hook = db.one("SELECT * FROM webhooks WHERE id = ?", row["webhook_id"]) if row else None
    if not row or not hook:
        return row
    payload = db.jload(row["payload_json"], {}) or {}
    body = json.dumps({
        "id": row["id"], "event": row["event"], "data": payload.get("data") or {},
        "occurred_at": payload.get("occurred_at") or row["created_at"], "sent_at": now_iso(),
    }, separators=(",", ":"), default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Switchboard-Webhooks/1.0",
        "X-Switchboard-Event": row["event"],
        "X-Switchboard-Delivery": str(row["id"]),
        "X-Switchboard-Signature": sign(hook["secret"], body),
    }
    code = None
    error = None
    try:
        resp = requests.post(hook["url"], data=body, headers=headers, timeout=TIMEOUT_SECONDS, allow_redirects=False)
        code = resp.status_code
        if not 200 <= code < 300:
            error = f"HTTP {code}"
    except requests.Timeout:
        error = f"Timed out after {TIMEOUT_SECONDS}s"
    except requests.RequestException as exc:
        error = f"Couldn't connect: {exc.__class__.__name__}"
    attempts = row["attempts"] + 1
    stamp = now_iso()
    with db.transaction():
        if error is None:
            db.update("webhook_deliveries", row["id"], {
                "status": "delivered", "attempts": attempts, "response_code": code, "error": None, "next_attempt_at": None,
            })
        elif attempts < MAX_ATTEMPTS:
            db.update("webhook_deliveries", row["id"], {
                "status": "pending", "attempts": attempts, "response_code": code, "error": error,
                "next_attempt_at": iso(now() + BACKOFF[attempts - 1]),
            })
        else:
            db.update("webhook_deliveries", row["id"], {
                "status": "failed", "attempts": attempts, "response_code": code, "error": error, "next_attempt_at": None,
            })
        db.update("webhooks", hook["id"], {"last_delivery_at": stamp, "last_status": code, "last_error": error})
    return db.one("SELECT * FROM webhook_deliveries WHERE id = ?", row["id"])


def process_deliveries(limit: int = 20) -> int:
    """Worker task: send whatever is due. Returns how many were attempted."""
    due = db.column(
        "SELECT id FROM webhook_deliveries WHERE status = 'pending' AND next_attempt_at <= ? "
        "ORDER BY next_attempt_at, id LIMIT ?",
        now_iso(), limit,
    )
    sent = 0
    for delivery_id in due:
        if _claim(delivery_id):
            attempt(delivery_id)
            sent += 1
    return sent


def send_test(webhook_id: int) -> dict:
    """Queue a 'webhook.test' delivery for one webhook and send it right away."""
    stamp = now_iso()
    payload = db.jdump({"event": "webhook.test", "data": {"message": "Hello from Switchboard 👋"}, "occurred_at": stamp})
    delivery_id = db.insert("webhook_deliveries", {
        "webhook_id": webhook_id, "event": "webhook.test", "payload_json": payload, "status": "pending",
        "attempts": 0, "next_attempt_at": iso(now() + LEASE), "created_at": stamp,
    })
    return attempt(delivery_id)


def retry(delivery_id: int) -> dict:
    with db.transaction():
        db.update("webhook_deliveries", delivery_id, {"status": "pending", "attempts": 0, "next_attempt_at": now_iso(),
                                                       "error": None})
    return db.one("SELECT * FROM webhook_deliveries WHERE id = ?", delivery_id)


def cleanup() -> int:
    cutoff = iso(now() - timedelta(days=KEEP_DAYS))
    return db.execute("DELETE FROM webhook_deliveries WHERE status != 'pending' AND created_at < ?", cutoff).rowcount
