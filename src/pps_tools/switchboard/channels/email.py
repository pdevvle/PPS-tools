"""Email accounts: send with SMTP, receive with IMAP.

Config (channels.config_json): imap_host, imap_port (993), imap_ssl (true), imap_user,
imap_password, imap_folder ('INBOX'), smtp_host, smtp_port (587), smtp_security
('starttls' | 'ssl' | 'none'), smtp_user, smtp_password, from_name_mode ('user' |
'channel' | 'user_at_org'), initial_days (7), track_opens, append_sent, sent_folder,
inbound_secret (for the raw-MIME webhook), demo.

IMAP is read-only: the folder is opened with EXAMINE and messages fetched with
BODY.PEEK, so nothing is marked read on the server. Progress (UIDVALIDITY + last UID
per folder) lives in channels.sync_state_json.
"""

from __future__ import annotations

import imaplib
import logging
import smtplib
import socket
import ssl
import threading
import time
from datetime import timedelta
from urllib.parse import urlparse

from pps_tools.switchboard import config as config_mod
from pps_tools.switchboard import db
from pps_tools.switchboard.channels import Adapter, SendError, SendResult, mime, register
from pps_tools.switchboard.services import settings
from pps_tools.switchboard.util import now, now_iso

logger = logging.getLogger(__name__)

TIMEOUT = 30
FETCH_BATCH = 200

# Ready-made server settings offered in the UI.
PRESETS = {
    "gmail": {"label": "Gmail / Google Workspace", "imap_host": "imap.gmail.com", "imap_port": 993,
              "smtp_host": "smtp.gmail.com", "smtp_port": 587, "smtp_security": "starttls",
              "hint": "Turn on 2-Step Verification, then create an App Password at myaccount.google.com/apppasswords."},
    "outlook": {"label": "Outlook / Microsoft 365", "imap_host": "outlook.office365.com", "imap_port": 993,
                "smtp_host": "smtp.office365.com", "smtp_port": 587, "smtp_security": "starttls",
                "hint": "IMAP and authenticated SMTP must be enabled for the mailbox in the Microsoft 365 admin center."},
    "yahoo": {"label": "Yahoo Mail", "imap_host": "imap.mail.yahoo.com", "imap_port": 993,
              "smtp_host": "smtp.mail.yahoo.com", "smtp_port": 465, "smtp_security": "ssl",
              "hint": "Generate an app password under Account Security."},
    "icloud": {"label": "iCloud Mail", "imap_host": "imap.mail.me.com", "imap_port": 993,
               "smtp_host": "smtp.mail.me.com", "smtp_port": 587, "smtp_security": "starttls",
               "hint": "Use an app-specific password from appleid.apple.com."},
}


def _cfg(channel: dict) -> dict:
    return db.jload(channel.get("config_json"), {}) or {}


def is_public_base(base_url: str | None) -> bool:
    host = (urlparse(base_url or "").hostname or "").lower()
    return bool(host) and host not in ("localhost", "127.0.0.1", "0.0.0.0", "::1") and not host.endswith(".local")


def from_name_for(channel: dict, message: dict) -> str:
    cfg = _cfg(channel)
    mode = cfg.get("from_name_mode") or "user"
    person = message.get("from_name") or channel.get("name")
    if mode == "channel":
        return channel.get("name") or person or ""
    if mode == "user_at_org":
        return f"{(person or '').split(' ')[0]} at {settings.get('org.name')}".strip()
    return person or channel.get("name") or ""


# -- SMTP -----------------------------------------------------------------------------


def _smtp_connect(cfg: dict) -> smtplib.SMTP:
    host = cfg.get("smtp_host")
    if not host:
        raise SendError("No outgoing (SMTP) server is configured for this account")
    security = cfg.get("smtp_security") or "starttls"
    port = int(cfg.get("smtp_port") or (465 if security == "ssl" else 587))
    context = ssl.create_default_context()
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=TIMEOUT)
        server.ehlo()
        if security == "starttls":
            server.starttls(context=context)
            server.ehlo()
    user = cfg.get("smtp_user") or cfg.get("imap_user")
    password = cfg.get("smtp_password") or cfg.get("imap_password")
    if user and password:
        server.login(user, password)
    return server


def _smtp_send(cfg: dict, em, envelope_from: str, recipients: list[str]) -> None:
    try:
        server = _smtp_connect(cfg)
        try:
            refused = server.send_message(em, from_addr=envelope_from, to_addrs=recipients)
        finally:
            try:
                server.quit()
            except Exception:  # connection already gone
                pass
    except SendError:
        raise
    except smtplib.SMTPAuthenticationError as exc:
        raise SendError(f"The mail server rejected the login ({exc.smtp_code}). Check the username and password.") from exc
    except smtplib.SMTPRecipientsRefused as exc:
        codes = [code for code, _msg in exc.recipients.values()]
        transient = bool(codes) and all(400 <= c < 500 for c in codes)
        raise SendError("The mail server refused: " + ", ".join(exc.recipients), transient=transient) from exc
    except smtplib.SMTPResponseException as exc:
        text = exc.smtp_error.decode(errors="replace") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
        raise SendError(f"Mail server error {exc.smtp_code}: {text}", transient=400 <= exc.smtp_code < 500) from exc
    except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, socket.timeout, TimeoutError, OSError) as exc:
        raise SendError(f"Couldn't reach the mail server: {exc}", transient=True) from exc
    if refused:
        logger.warning("Some recipients were refused: %s", refused)


# -- IMAP -----------------------------------------------------------------------------


def _quote(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _imap_connect(cfg: dict) -> imaplib.IMAP4:
    host = cfg.get("imap_host")
    if not host:
        raise ValueError("No incoming (IMAP) server is configured")
    use_ssl = cfg.get("imap_ssl", True) is not False
    port = int(cfg.get("imap_port") or (993 if use_ssl else 143))
    if use_ssl:
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
    else:
        conn = imaplib.IMAP4(host, port, timeout=TIMEOUT)
        if "STARTTLS" in conn.capabilities:
            conn.starttls(ssl_context=ssl.create_default_context())
    conn.login(cfg.get("imap_user") or "", cfg.get("imap_password") or "")
    return conn


def _logout(conn) -> None:
    try:
        conn.logout()
    except Exception:  # already disconnected
        pass


def _append_sent(cfg: dict, raw: bytes) -> None:
    conn = _imap_connect(cfg)
    try:
        candidates = [cfg.get("sent_folder")] if cfg.get("sent_folder") else ["Sent", "Sent Items", "INBOX.Sent", "[Gmail]/Sent Mail"]
        for folder in candidates:
            typ, _ = conn.append(_quote(folder), "\\Seen", imaplib.Time2Internaldate(time.time()), raw)
            if typ == "OK":
                return
    finally:
        _logout(conn)


_sync_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def sync_lock(channel_id: int) -> threading.Lock:
    with _locks_guard:
        return _sync_locks.setdefault(channel_id, threading.Lock())


def _fetch_raw(conn, uid: int) -> bytes | None:
    typ, data = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
    if typ != "OK" or not data:
        return None
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
            return bytes(item[1])
    return None


def sync_channel(channel: dict) -> int:
    """Fetch new mail for one channel. Returns how many messages were delivered."""
    from pps_tools.switchboard.services import inbox

    cfg = _cfg(channel)
    folder = cfg.get("imap_folder") or "INBOX"
    state = db.jload(channel.get("sync_state_json"), {}) or {}
    fstate = dict(state.get(folder) or {})
    delivered = 0
    conn = _imap_connect(cfg)
    try:
        typ, _ = conn.select(_quote(folder), readonly=True)
        if typ != "OK":
            raise ValueError(f"Couldn't open the folder {folder!r}")
        _, uv = conn.response("UIDVALIDITY")
        uidvalidity = (uv[0].decode() if uv and uv[0] else "") if uv else ""
        if fstate.get("uidvalidity") != uidvalidity:
            fstate = {"uidvalidity": uidvalidity, "last_uid": None}
        last_uid = fstate.get("last_uid")
        if last_uid is None:
            days = int(cfg.get("initial_days") or 7)
            since = (now() - timedelta(days=days)).strftime("%d-%b-%Y")
            typ, data = conn.uid("SEARCH", None, "SINCE", since)
        else:
            typ, data = conn.uid("SEARCH", None, "UID", f"{int(last_uid) + 1}:*")
        uids = sorted({int(x) for x in (data[0] or b"").split()}) if typ == "OK" and data else []
        if last_uid is not None:
            uids = [u for u in uids if u > int(last_uid)]  # 'n:*' always returns the newest message
        for uid in uids[:FETCH_BATCH]:
            raw = _fetch_raw(conn, uid)
            if raw:
                inbound = mime.to_inbound(channel, raw, fallback_id=f"<imap-{channel['id']}-{uidvalidity}-{uid}@switchboard>")
                if inbox.deliver_inbound(inbound):
                    delivered += 1
            fstate["last_uid"] = uid
            state[folder] = fstate
            db.update("channels", channel["id"], {"sync_state_json": db.jdump(state)})
        if not uids and fstate.get("last_uid") is None:
            # Nothing in the window yet: remember where the mailbox ends so we only take new mail.
            typ, data = conn.uid("SEARCH", None, "ALL")
            existing = [int(x) for x in (data[0] or b"").split()] if typ == "OK" and data else []
            fstate["last_uid"] = max(existing) if existing else 0
            state[folder] = fstate
            db.update("channels", channel["id"], {"sync_state_json": db.jdump(state)})
    finally:
        _logout(conn)
    return delivered


def sync_and_record(channel_id: int) -> tuple[int, str | None]:
    """Sync if nobody else is syncing this channel; record the outcome on the row."""
    lock = sync_lock(channel_id)
    if not lock.acquire(blocking=False):
        return 0, "A sync is already running"
    try:
        channel = db.one("SELECT * FROM channels WHERE id = ?", channel_id)
        if not channel:
            return 0, "Channel not found"
        try:
            count = sync_channel(channel)
            db.update("channels", channel_id, {"last_sync_at": now_iso(), "sync_error": None})
            return count, None
        except Exception as exc:  # report on the channel; the worker keeps going
            logger.warning("IMAP sync failed for channel %s: %s", channel_id, exc)
            message = _friendly_error(exc)
            db.update("channels", channel_id, {"last_sync_at": now_iso(), "sync_error": message})
            return 0, message
    finally:
        lock.release()


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    if isinstance(exc, imaplib.IMAP4.error) and ("AUTH" in text.upper() or "LOGIN" in text.upper() or "credentials" in text.lower()):
        return f"The mail server rejected the login: {text}"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "Timed out talking to the mail server"
    if isinstance(exc, (socket.gaierror,)):
        return "Couldn't find that mail server — check the host name"
    if isinstance(exc, ssl.SSLError):
        return f"Secure connection failed: {text}"
    return text or exc.__class__.__name__


# -- adapter --------------------------------------------------------------------------


class EmailAdapter(Adapter):
    type = "email"
    label = "Email"

    def send(self, channel, message, attachments, ctx):
        cfg = _cfg(channel)
        base = ctx.get("base_url") or config_mod.current().base_url
        pixel = None
        if cfg.get("track_opens") and message.get("track_token") and is_public_base(base):
            pixel = f"{base}/t/o/{message['track_token']}.gif"
        em = mime.build(message, attachments, from_name=from_name_for(channel, message),
                        from_addr=channel["address"], reply_to=ctx.get("reply_to"), pixel_url=pixel)
        recipients = [p["handle"] for key in ("to_json", "cc_json", "bcc_json")
                      for p in (db.jload(message.get(key), []) or []) if p.get("handle")]
        if not recipients:
            raise SendError("No recipients")
        _smtp_send(cfg, em, channel["address"], recipients)
        if cfg.get("append_sent"):
            try:
                _append_sent(cfg, em.as_bytes())
            except Exception:  # the mail went out; a missing Sent copy isn't fatal
                logger.warning("Couldn't save a copy to Sent for channel %s", channel["id"], exc_info=True)
        return SendResult(external_id=message.get("external_id"), status="sent")

    def sync(self, channel):
        count, error = sync_and_record(channel["id"])
        if error:
            raise ValueError(error)
        return count

    def test(self, cfg):
        problems, done = [], []
        if cfg.get("imap_host"):
            try:
                conn = _imap_connect(cfg)
                try:
                    typ, _ = conn.select(_quote(cfg.get("imap_folder") or "INBOX"), readonly=True)
                    if typ != "OK":
                        problems.append(f"Signed in to IMAP, but couldn't open {cfg.get('imap_folder') or 'INBOX'}")
                    else:
                        done.append("receiving (IMAP)")
                finally:
                    _logout(conn)
            except Exception as exc:
                problems.append("IMAP: " + _friendly_error(exc))
        if cfg.get("smtp_host"):
            try:
                server = _smtp_connect(cfg)
                try:
                    server.noop()
                finally:
                    try:
                        server.quit()
                    except Exception:
                        pass
                done.append("sending (SMTP)")
            except smtplib.SMTPAuthenticationError as exc:
                problems.append(f"SMTP: the server rejected the login ({exc.smtp_code})")
            except Exception as exc:
                problems.append("SMTP: " + _friendly_error(exc))
        if not cfg.get("imap_host") and not cfg.get("smtp_host"):
            return False, "Add an IMAP server, an SMTP server, or both"
        if problems:
            return False, "; ".join(problems)
        return True, "Connected: " + " and ".join(done)

    def public_config(self, channel):
        cfg = _cfg(channel)
        return {"can_receive": bool(cfg.get("imap_host")), "can_send": bool(cfg.get("smtp_host")) or bool(cfg.get("demo"))}


def send_simple(channel: dict, to: str, subject: str, html: str, text: str | None = None) -> None:
    """Operational mail (invites, password resets) from this account."""
    cfg = _cfg(channel)
    if cfg.get("demo"):
        logger.info("Demo channel %s: not sending '%s' to %s", channel["id"], subject, to)
        return
    em = mime.simple(settings.get("org.name"), channel["address"], to, subject, html, text)
    _smtp_send(cfg, em, channel["address"], [to])


register(EmailAdapter())
