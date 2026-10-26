"""API & form channels: anything that can POST JSON (your website, Zapier, a POS).

Inbound: POST /api/channels/<id>/messages (API token) or /hooks/form/<public_key>
(website forms). Outbound replies are POSTed to config.outbound_url when set, signed
with HMAC-SHA256 over the body using config.secret:

    X-Switchboard-Signature: sha256=<hex digest>
"""

from __future__ import annotations

import hashlib
import hmac
import json

import requests

from pps_tools.switchboard import db
from pps_tools.switchboard.channels import Adapter, SendError, SendResult, register
from pps_tools.switchboard.util import now_iso, token

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
            return SendResult(external_id=f"api-{token(9)}", status="sent")
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
