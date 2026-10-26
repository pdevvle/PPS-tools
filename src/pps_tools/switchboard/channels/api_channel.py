"""API & form channels: anything that can POST JSON (your website, Zapier, a POS).

Inbound: POST /api/channels/<id>/messages (API token) or /hooks/form/<public_key>
(website forms). Outbound replies are POSTed to config.outbound_url when set, signed
with HMAC-SHA256 over the body using config.secret:

    X-Switchboard-Signature: sha256=<hex digest>

Without a reply URL, replies to someone who left an email address (a website form,
say) are emailed to them from the workspace's system email account, with a real
Message-ID so their answer threads back into the same conversation.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import requests

from pps_tools.switchboard import channels as registry
from pps_tools.switchboard import db
from pps_tools.switchboard.channels import Adapter, SendError, SendResult, register
from pps_tools.switchboard.util import norm_email, normalize_subject, now_iso, token

TIMEOUT = 15


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class ApiAdapter(Adapter):
    type = "api"
    label = "API & forms"

    def send(self, channel, message, attachments, ctx):
        cfg = db.jload(channel.get("config_json"), {}) or {}
        url = (cfg.get("outbound_url") or "").strip()
        if not url:
            return self._email_fallback(message, attachments, ctx)
        conv = ctx.get("conversation") or {}
        payload = {
            "event": "message.outbound",
            "sent_at": now_iso(),
            "channel": {"id": channel["id"], "name": channel["name"]},
            "conversation": {"id": conv.get("id"), "subject": conv.get("subject"), "thread_key": conv.get("thread_key")},
            "message": {
                "id": message["id"],
                "to": db.jload(message.get("to_json"), []),
                "subject": message.get("subject"),
                "body_text": message.get("body_text"),
                "body_html": message.get("body_html"),
                "author": (ctx.get("user") or {}).get("name"),
            },
        }
        body = json.dumps(payload, default=str).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "Switchboard"}
        if cfg.get("secret"):
            headers["X-Switchboard-Signature"] = sign(cfg["secret"], body)
        try:
            resp = requests.post(url, data=body, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise SendError(f"Couldn't reach {url}: {exc}", transient=True) from exc
        if resp.status_code >= 400:
            raise SendError(f"{url} answered {resp.status_code}", transient=resp.status_code >= 500)
        external = None
        try:
            external = (resp.json() or {}).get("id")
        except ValueError:
            pass
        return SendResult(external_id=str(external) if external else f"api-{token(9)}", status="sent")

    def _email_fallback(self, message, attachments, ctx):
        """Email the reply when every recipient is an email address and a system
        email account exists; otherwise the reply just stays in the conversation."""
        from pps_tools.switchboard.services import mailer

        recipients = db.jload(message.get("to_json"), []) or []
        if not recipients or not all(norm_email(p.get("handle")) for p in recipients):
            return SendResult(external_id=f"api-{token(9)}", status="sent")
        system = mailer.system_channel()
        if not system:
            raise SendError("Add an email account (Settings → Channels) to email replies to form submissions")
        conv = ctx.get("conversation") or {}
        subject = message.get("subject") or (f"Re: {normalize_subject(conv.get('subject'))}" if conv.get("subject") else None)
        domain = (system.get("address") or "switchboard.local").rsplit("@", 1)[-1]
        as_email = {**message, "subject": subject, "external_id": message.get("external_id") or f"<sb.{message['id']}.{token(9)}@{domain}>"}
        result = registry.adapter_for(system).send(system, as_email, attachments, ctx)
        return SendResult(external_id=as_email["external_id"], status=result.status, headers=result.headers)

    def test(self, cfg):
        url = (cfg.get("outbound_url") or "").strip()
        if not url:
            return True, "Ready — inbound messages can be posted to this channel"
        try:
            resp = requests.head(url, timeout=TIMEOUT, allow_redirects=True)
        except requests.RequestException as exc:
            return False, f"Couldn't reach {url}: {exc}"
        return True, f"{url} is reachable ({resp.status_code})"


register(ApiAdapter())
