"""Small shared helpers: time, tokens, text and handles."""

from __future__ import annotations

import hashlib
import html
import re
import secrets
from datetime import date, datetime, time, timedelta, timezone
from email.utils import getaddresses
from html.parser import HTMLParser

# -- time -------------------------------------------------------------------------

UTC = timezone.utc


def now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    """Canonical storage format: UTC, millisecond precision, 'Z' suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return iso(now())


def parse_iso(value) -> datetime | None:
    """Parse an ISO-8601 instant (any offset, 'Z', or naive meaning UTC)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def norm_iso(value) -> str | None:
    """Normalize client input to the storage format; None for empty/invalid."""
    return iso(parse_iso(value))


def add_minutes(value: str, minutes: float) -> str:
    return iso(parse_iso(value) + timedelta(minutes=minutes))


def minutes_between(start: str, end: str) -> float:
    return (parse_iso(end) - parse_iso(start)).total_seconds() / 60.0


def get_zone(name: str | None):
    """ZoneInfo for ``name``; UTC when unknown (or tzdata is missing on Windows)."""
    if not name:
        return UTC
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return UTC


def local_to_utc_iso(day: str | date, hhmm: str, tz) -> str:
    """'2026-10-26' + '08:30' in ``tz`` -> storage instant."""
    if isinstance(day, str):
        day = date.fromisoformat(day)
    h, m = (int(x) for x in hhmm.split(":")[:2])
    if h == 24:  # allow '24:00' as end of day
        return iso(datetime.combine(day + timedelta(days=1), time(0, m), tzinfo=tz))
    return iso(datetime.combine(day, time(h, m), tzinfo=tz))


def to_local(value: str, tz) -> datetime:
    return parse_iso(value).astimezone(tz)


def parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# -- tokens -------------------------------------------------------------------------


def token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# -- handles ------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


def is_email(value: str | None) -> bool:
    return bool(value and _EMAIL_RE.match(value.strip()))


def norm_email(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().strip("<>").lower()
    return value if is_email(value) else None


def norm_phone(value: str | None, default_country: str = "1") -> str | None:
    """Best-effort E.164: '(602) 555-0100' -> '+16025550100'. Keeps 'whatsapp:' off."""
    if not value:
        return None
    value = value.strip()
    if value.lower().startswith("whatsapp:"):
        value = value[9:]
    plus = value.startswith("+")
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    if plus:
        return "+" + digits
    if len(digits) == 10 and default_country == "1":
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1") and default_country == "1":
        return "+" + digits
    return "+" + digits


def parse_address_list(value) -> list[dict]:
    """'Ann <ann@x.com>, bob@y.com' or [{"name","handle"}] / ['a@b'] -> [{"name","handle"}]."""
    if not value:
        return []
    if isinstance(value, str):
        pairs = getaddresses([value])
    else:
        pairs = []
        for item in value:
            if isinstance(item, dict):
                pairs.append((item.get("name") or "", item.get("handle") or item.get("email") or ""))
            else:
                pairs.extend(getaddresses([str(item)]))
    out, seen = [], set()
    for name, handle in pairs:
        handle = (handle or "").strip()
        if not handle:
            continue
        key = handle.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": (name or "").strip() or None, "handle": handle})
    return out


def first_name(name: str | None) -> str:
    return (name or "").strip().split(" ")[0] if name else ""


def initials(name: str | None) -> str:
    parts = [p for p in re.split(r"[\s._@-]+", name or "") if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


PALETTE = [
    "#3b5bdb", "#0c8599", "#2f9e44", "#e8590c", "#c2255c", "#7048e8",
    "#1971c2", "#d6336c", "#5c940d", "#f08c00", "#ae3ec9", "#0b7285",
]


def pick_color(seed) -> str:
    return PALETTE[int(hashlib.md5(str(seed).encode()).hexdigest(), 16) % len(PALETTE)]


# -- text ---------------------------------------------------------------------------

_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
    "pre", "table", "ul", "ol", "hr", "section", "article", "header", "footer",
}
_SKIP_TAGS = {"style", "script", "head", "title", "template"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.href: list[str | None] = []
        self.quote_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self.skip += 1
            return
        if tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "blockquote":
            self.quote_depth += 1
            self.parts.append("\n")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a":
            self.href.append(dict(attrs).get("href"))
        if tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self.parts.append(f"[{alt}]")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if tag == "a" and self.href:
            href = self.href.pop()
            if href and href.startswith(("http://", "https://")):
                text_so_far = "".join(self.parts[-3:])
                if href not in text_so_far:
                    self.parts.append(f" ({href})")
        if tag == "blockquote":
            self.quote_depth = max(0, self.quote_depth - 1)
        if tag in _BLOCK_TAGS and tag != "br":
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self.quote_depth:
            data = data.replace("\n", "\n" + "> " * self.quote_depth)
        self.parts.append(data)


def html_to_text(markup: str | None) -> str:
    if not markup:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # pragma: no cover - malformed HTML is common in email
        pass
    text = "".join(parser.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_URL_RE = re.compile(r"(https?://[^\s<>\"']+[^\s<>\"'.,;:!?)\]])")


def text_to_html(text: str | None) -> str:
    """Plain text -> safe HTML paragraphs with clickable links."""
    if not text:
        return ""
    escaped = html.escape(text)
    linked = _URL_RE.sub(r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', escaped)
    paragraphs = re.split(r"\n{2,}", linked.strip())
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)


def snippet(text: str | None, length: int = 180) -> str:
    if not text:
        return ""
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= length else flat[: length - 1].rstrip() + "…"


def normalize_subject(subject: str | None) -> str:
    """Strip reply/forward prefixes so 'Re: Fwd: Quote' threads with 'Quote'."""
    s = (subject or "").strip()
    while True:
        new = re.sub(r"^\s*(re|fw|fwd|aw|sv|antw)\s*(\[\d+\])?\s*:\s*", "", s, flags=re.I)
        if new == s:
            return s.strip()
        s = new


def render_template(text: str | None, context: dict) -> str:
    """Replace {{ dotted.keys }} from a nested dict; unknown keys become ''."""
    if not text:
        return ""

    def lookup(match):
        value = context
        for part in match.group(1).split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
            if value is None:
                return match.group(2) or ""
        return html.escape(str(value)) if context.get("__html__") else str(value)

    return re.sub(r"\{\{\s*([\w.]+)\s*(?:\|\s*default\s*:\s*'([^']*)')?\s*\}\}", lookup, text)
