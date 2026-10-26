"""Text messages (SMS/MMS) and WhatsApp through Twilio.

Config: account_sid, auth_token, from_number (defaults to the channel address) or
messaging_service_sid, validate_signature (true), demo.

Twilio calls us at /hooks/twilio/<public_key> for inbound messages and at
/hooks/twilio/<public_key>/status for delivery receipts (see api/public.py).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging

import requests

from pps_tools.switchboard import db
from pps_tools.switchboard.channels import Adapter, SendError, SendResult, register
from pps_tools.switchboard.channels.email import is_public_base
from pps_tools.switchboard.services import files
from pps_tools.switchboard.util import norm_phone

logger = logging.getLogger(__name__)

API_BASE = "https://api.twilio.com/2010-04-01"
TIMEOUT = 20


def _cfg(channel: dict) -> dict:
    return db.jload(channel.get("config_json"), {}) or {}


def signature(url: str, params: list[tuple[str, str]], auth_token: str) -> str:
    """Twilio's X-Twilio-Signature: base64(HMAC-SHA1(url + sorted key/value pairs))."""
    payload = url + "".join(k + v for k, v in sorted(params, key=lambda kv: (kv[0], kv[1])))
    digest = hmac.new(auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def valid_signature(url: str, params: list[tuple[str, str]], auth_token: str, provided: str | None) -> bool:
    if not provided or not auth_token:
        return False
    return hmac.compare_digest(signature(url, params, auth_token), provided)


def address(kind: str, number: str) -> str:
    number = norm_phone(number) or number
    return f"whatsapp:{number}" if kind == "whatsapp" else number


def download_media(cfg: dict, url: str) -> bytes | None:
    try:
        resp = requests.get(url, auth=(cfg.get("account_sid") or "", cfg.get("auth_token") or ""), timeout=TIMEOUT)
        if resp.status_code == 200:
            return resp.content
        logger.warning("Twilio media download failed: %s %s", resp.status_code, url)
    except requests.RequestException as exc:
        logger.warning("Twilio media download failed: %s", exc)
    return None


STATUS_MAP = {
    "queued": "sent", "accepted": "sent", "sending": "sent", "sent": "sent", "delivered": "delivered",
    "read": "read", "undelivered": "failed", "failed": "failed",
}


class TwilioAdapter(Adapter):
    def __init__(self, kind: str):
        self.type = kind
        self.label = "WhatsApp" if kind == "whatsapp" else "SMS"

    def send(self, channel, message, attachments, ctx):
        cfg = _cfg(channel)
        sid, auth = cfg.get("account_sid"), cfg.get("auth_token")
        if not sid or not auth:
            raise SendError("Twilio isn't set up for this channel (missing Account SID or Auth Token)")
        recipients = db.jload(message.get("to_json"), []) or []
        if not recipients or not recipients[0].get("handle"):
            raise SendError("No phone number to send to")
        data: list[tuple[str, str]] = [("To", address(self.type, recipients[0]["handle"])),
                                       ("Body", (message.get("body_text") or "").strip())]
        if cfg.get("messaging_service_sid") and self.type == "sms":
            data.append(("MessagingServiceSid", cfg["messaging_service_sid"]))
        else:
            data.append(("From", address(self.type, cfg.get("from_number") or channel.get("address") or "")))
        base = ctx.get("base_url") or ""
        if is_public_base(base):
            data.append(("StatusCallback", f"{base}/hooks/twilio/{channel['public_key']}/status"))
            for att in attachments[:10]:
                data.append(("MediaUrl", files.public_url(att, absolute=True)))
        try:
            resp = requests.post(f"{API_BASE}/Accounts/{sid}/Messages.json", data=data, auth=(sid, auth), timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise SendError(f"Couldn't reach Twilio: {exc}", transient=True) from exc
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if resp.status_code >= 400:
            detail = payload.get("message") or resp.text[:200]
            transient = resp.status_code >= 500 or resp.status_code == 429
            raise SendError(f"Twilio error {payload.get('code') or resp.status_code}: {detail}", transient=transient)
        return SendResult(external_id=payload.get("sid"), status=STATUS_MAP.get(payload.get("status"), "sent"))

    def test(self, cfg):
        sid, auth = cfg.get("account_sid"), cfg.get("auth_token")
        if not sid or not auth:
            return False, "Enter your Account SID and Auth Token"
        try:
            resp = requests.get(f"{API_BASE}/Accounts/{sid}.json", auth=(sid, auth), timeout=TIMEOUT)
        except requests.RequestException as exc:
            return False, f"Couldn't reach Twilio: {exc}"
        if resp.status_code == 200:
            name = (resp.json() or {}).get("friendly_name") or sid
            return True, f"Connected to Twilio account “{name}”"
        if resp.status_code in (401, 403):
            return False, "Twilio rejected the Account SID / Auth Token"
        return False, f"Twilio answered {resp.status_code}"


register(TwilioAdapter("sms"))
register(TwilioAdapter("whatsapp"))
