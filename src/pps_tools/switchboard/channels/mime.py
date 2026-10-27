"""RFC 5322 / MIME in and out.

``parse(raw)`` turns a raw email into the fields of ``services.inbox.Inbound``;
``build(...)`` turns an outbound message row into an ``EmailMessage`` ready for SMTP.
"""

from __future__ import annotations

import html as htmllib
import mimetypes
import re
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import formatdate, getaddresses, parsedate_to_datetime

from pps_tools.switchboard.util import html_to_text, iso, parse_iso

_MSGID_RE = re.compile(r"<[^<>\s]+>")
KEPT_HEADERS = ("Return-Path", "Auto-Submitted", "Precedence", "List-Id", "List-Unsubscribe", "X-Spam-Flag",
                "X-Spam-Status", "X-Mailer", "User-Agent", "X-Original-To", "Delivered-To")


# -- parsing ------------------------------------------------------------------------


def _header(msg: Message, name: str) -> str:
    value = msg.get(name)
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:  # undecodable header bytes
        return ""


def _addresses(msg: Message, name: str) -> list[dict]:
    values = msg.get_all(name) or []
    out = []
    for display, addr in getaddresses([str(v) for v in values]):
        addr = (addr or "").strip()
        if not addr or "@" not in addr:
            continue
        out.append({"name": (display or "").strip() or None, "handle": addr.lower()})
    return out


def _msgids(value: str) -> list[str]:
    return _MSGID_RE.findall(value or "")


def _decode_part(part: Message) -> str:
    """Text content of a part, tolerating wrong or unknown charsets."""
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content
    except (LookupError, UnicodeError, KeyError, AssertionError):
        pass
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    for candidate in (charset, "utf-8", "windows-1252", "latin-1"):
        try:
            return payload.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace")


def _filename(part: Message, index: int) -> str:
    name = part.get_filename()
    if name:
        return str(name)
    ext = mimetypes.guess_extension(part.get_content_type() or "") or ".bin"
    return f"attachment-{index}{ext}"


def _collect(part: Message, bodies: set[int], out: list[dict]) -> None:
    ctype = part.get_content_type()
    if ctype == "message/rfc822":
        payload = part.get_payload()
        inner = payload[0] if isinstance(payload, list) and payload else payload
        if isinstance(inner, Message):
            subject = _header(inner, "Subject") or "forwarded message"
            safe = re.sub(r"[^\w\- ]+", "", subject)[:60].strip() or "forwarded"
            out.append({"filename": f"{safe}.eml", "content_type": "message/rfc822",
                        "data": inner.as_bytes(policy=policy.default.clone(linesep="\r\n")),
                        "content_id": None, "inline": False})
        return
    if part.is_multipart():
        for sub in part.iter_parts():
            _collect(sub, bodies, out)
        return
    if id(part) in bodies:
        return
    disposition = part.get_content_disposition()
    if ctype in ("text/plain", "text/html") and disposition != "attachment" and not part.get_filename():
        return  # an alternative body we didn't pick (e.g. both html bodies of a signed mail)
    data = part.get_payload(decode=True)
    if data is None:
        return
    cid = (_header(part, "Content-ID") or "").strip("<> ") or None
    out.append({
        "filename": _filename(part, len(out) + 1),
        "content_type": ctype,
        "data": data,
        "content_id": cid,
        "inline": disposition == "inline" or (cid is not None and disposition != "attachment"),
    })


def _is_auto(msg: Message, from_addr: str | None) -> bool:
    auto = _header(msg, "Auto-Submitted").lower()
    if auto and auto != "no":
        return True
    if _header(msg, "Precedence").lower() in ("bulk", "junk", "list", "auto_reply"):
        return True
    if any(msg.get(h) for h in ("X-Autoreply", "X-Autorespond", "X-Auto-Response-Suppress", "List-Id", "List-Unsubscribe")):
        return True
    if _header(msg, "Return-Path") == "<>":
        return True
    local = (from_addr or "").split("@")[0].lower()
    return local in ("mailer-daemon", "postmaster", "no-reply", "noreply", "do-not-reply", "donotreply")


def parse(raw: bytes) -> dict:
    """Raw RFC 5322 bytes -> dict of Inbound fields (without ``channel``/``kind``)."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    senders = _addresses(msg, "From") or _addresses(msg, "Sender")
    sender = senders[0] if senders else {"name": None, "handle": None}
    reply_to = _addresses(msg, "Reply-To")
    html_part = msg.get_body(preferencelist=("html",))
    text_part = msg.get_body(preferencelist=("plain",))
    bodies = {id(p) for p in (html_part, text_part) if p is not None}
    body_html = _decode_part(html_part) if html_part is not None else None
    body_text = _decode_part(text_part) if text_part is not None else None
    if not body_text and body_html:
        body_text = html_to_text(body_html)
    attachments: list[dict] = []
    if msg.is_multipart():
        _collect(msg, bodies, attachments)
    elif id(msg) not in bodies:
        _collect(msg, set(), attachments)
    date = None
    try:
        if msg.get("Date"):
            date = iso(parsedate_to_datetime(str(msg["Date"])))
    except (TypeError, ValueError, IndexError):
        date = None
    in_reply_to = _msgids(_header(msg, "In-Reply-To"))
    headers = {h: _header(msg, h) for h in KEPT_HEADERS if msg.get(h) is not None}
    return {
        "from_handle": sender["handle"],
        "from_name": sender["name"],
        "to": _addresses(msg, "To"),
        "cc": _addresses(msg, "Cc"),
        "reply_to": reply_to[0]["handle"] if reply_to else None,
        "subject": _header(msg, "Subject") or None,
        "body_text": body_text,
        "body_html": body_html,
        "external_id": (_msgids(_header(msg, "Message-ID")) or [None])[0],
        "in_reply_to": in_reply_to[0] if in_reply_to else None,
        "references": _msgids(_header(msg, "References"))[-30:],
        "date": date if date and parse_iso(date) else None,
        "attachments": attachments,
        "headers": headers,
        "is_auto": _is_auto(msg, sender["handle"]),
        "is_spam": _header(msg, "X-Spam-Flag").upper().startswith("YES"),
    }


def to_inbound(channel: dict, raw: bytes, fallback_id: str | None = None):
    """Parse raw mail into an ``Inbound`` for ``channel``."""
    from pps_tools.switchboard.services.inbox import Inbound

    fields = parse(raw)
    if not fields["external_id"] and fallback_id:
        fields["external_id"] = fallback_id
    return Inbound(channel=channel, kind="email", raw=raw, **fields)


# -- building -----------------------------------------------------------------------


def _address(name: str | None, handle: str) -> Address:
    local, _, domain = handle.partition("@")
    try:
        return Address(display_name=name or "", username=local, domain=domain)
    except (ValueError, IndexError):
        return Address(display_name="", addr_spec=handle)


def _stamp(value) -> str:
    """'Mon, Oct 26, 2026 at 3:04 PM UTC' (portable: no %-d)."""
    when = parse_iso(value)
    if not when:
        return ""
    clock = when.strftime("%I:%M %p").lstrip("0")
    return f"{when:%a, %b} {when.day}, {when.year} at {clock} UTC"


def quote_html(reply_to: dict | None) -> str:
    if not reply_to:
        return ""
    who = reply_to.get("from_name") or reply_to.get("from_handle") or "they"
    stamp = _stamp(reply_to.get("date"))
    original = reply_to.get("body_html") or htmllib.escape(reply_to.get("body_text") or "").replace("\n", "<br>")
    return (
        '<div class="sb-quote"><p style="color:#666;margin:16px 0 8px">'
        f"On {htmllib.escape(stamp)}, {htmllib.escape(who)} wrote:</p>"
        '<blockquote type="cite" style="margin:0 0 0 .8ex;border-left:2px solid #ccc;padding-left:1ex">'
        f"{original}</blockquote></div>"
    )


def quote_text(reply_to: dict | None) -> str:
    if not reply_to:
        return ""
    who = reply_to.get("from_name") or reply_to.get("from_handle") or "they"
    original = reply_to.get("body_text") or html_to_text(reply_to.get("body_html"))
    quoted = "\n".join("> " + line for line in (original or "").splitlines())
    return f"\n\nOn {_stamp(reply_to.get('date'))}, {who} wrote:\n{quoted}"


def wrap_html(fragment: str) -> str:
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"></head>"
        "<body style=\"font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;"
        f"line-height:1.5;color:#1d2433\">{fragment}</body></html>"
    )


def build(message: dict, attachments: list[dict], *, from_name: str | None, from_addr: str,
          reply_to: dict | None = None, pixel_url: str | None = None, read_bytes=None) -> EmailMessage:
    """An outbound message row (+ its attachment rows) as a MIME message."""
    from pps_tools.switchboard import db
    from pps_tools.switchboard.services import files

    jload = db.jload
    read = read_bytes or files.read_bytes
    to = jload(message.get("to_json"), []) or []
    cc = jload(message.get("cc_json"), []) or []
    em = EmailMessage(policy=policy.default)
    em["From"] = _address(from_name, from_addr)
    if to:
        em["To"] = [_address(p.get("name"), p["handle"]) for p in to]
    if cc:
        em["Cc"] = [_address(p.get("name"), p["handle"]) for p in cc]
    em["Subject"] = message.get("subject") or ""
    em["Date"] = formatdate(usegmt=True)
    if message.get("external_id"):
        em["Message-ID"] = message["external_id"]
    if message.get("in_reply_to"):
        em["In-Reply-To"] = message["in_reply_to"]
    refs = jload(message.get("references_json"), []) or []
    if refs:
        em["References"] = " ".join(refs)
    if message.get("is_auto"):
        em["Auto-Submitted"] = "auto-replied"
        em["X-Auto-Response-Suppress"] = "All"
    em["X-Mailer"] = "Switchboard"

    body_html = message.get("body_html") or htmllib.escape(message.get("body_text") or "").replace("\n", "<br>")
    html_doc = body_html + quote_html(reply_to)
    if pixel_url:
        html_doc += f'<img src="{htmllib.escape(pixel_url)}" width="1" height="1" alt="" style="display:none">'
    text = (message.get("body_text") or html_to_text(body_html)) + quote_text(reply_to)
    em.set_content(text)
    em.add_alternative(wrap_html(html_doc), subtype="html")

    inline = [a for a in attachments if a.get("is_inline") and a.get("content_id")]
    regular = [a for a in attachments if a not in inline]
    if inline:
        html_part = em.get_body(preferencelist=("html",))
        for att in inline:
            maintype, _, subtype = (att.get("content_type") or "application/octet-stream").partition("/")
            html_part.add_related(read(att), maintype=maintype, subtype=subtype or "octet-stream",
                                  cid=f"<{att['content_id']}>", filename=att["filename"], disposition="inline")
    for att in regular:
        maintype, _, subtype = (att.get("content_type") or "application/octet-stream").partition("/")
        data = read(att)
        if maintype == "text":
            em.add_attachment(data, maintype="application", subtype="octet-stream", filename=att["filename"])
        else:
            em.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=att["filename"])
    return em


def simple(from_name: str | None, from_addr: str, to: str, subject: str, html: str, text: str | None = None) -> EmailMessage:
    em = EmailMessage(policy=policy.default)
    em["From"] = _address(from_name, from_addr)
    em["To"] = _address(None, to)
    em["Subject"] = subject
    em["Date"] = formatdate(usegmt=True)
    em["Auto-Submitted"] = "auto-generated"
    em.set_content(text or html_to_text(html))
    em.add_alternative(wrap_html(html), subtype="html")
    return em
