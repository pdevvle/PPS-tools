"""Claude-powered assists for the inbox: thread summaries, reply drafts, job extraction,
rewrites and translation.

Calls go through the official Anthropic SDK. The key comes from Settings → AI
assistant (``ai.api_key``) or the ``ANTHROPIC_API_KEY`` environment variable. The
default model is Claude Opus 5.5 with server-side refusal fallbacks; its thinking is
always adaptive, so ``effort`` is what keeps these interactive requests quick.
Answers come back as JSON via structured outputs, and any HTML is sanitized before it
reaches the browser.
"""

from __future__ import annotations

import html
import json
import os
import re
import threading
from datetime import datetime, time, timedelta

import anthropic

from pps_tools.switchboard import db
from pps_tools.switchboard.services import inbox_query, settings
from pps_tools.switchboard.services import users as users_svc
from pps_tools.switchboard.services.sanitize import sanitize
from pps_tools.switchboard.util import first_name, html_to_text, iso, now, parse_iso

DEFAULT_MODEL = "claude-opus-5-5"
MODELS = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "hint": "Best quality (recommended)"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "hint": "Faster, lower cost"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "hint": "Fastest, lowest cost"},
]
# Models that accept server-side refusal fallbacks (fallbacks="default").
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-fable-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 8000          # room for adaptive thinking plus a short answer
MAX_MESSAGE_CHARS = 12000  # per message in a transcript; longer bodies are marked as cut

settings.register_defaults({"ai.enabled": True, "ai.api_key": None, "ai.model": DEFAULT_MODEL},
                           private_prefixes=["ai.api_key"])


class AIError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# -- configuration ------------------------------------------------------------------


def api_key() -> str | None:
    return (settings.get("ai.api_key") or "").strip() or os.environ.get("ANTHROPIC_API_KEY") or None


def key_source() -> str | None:
    if (settings.get("ai.api_key") or "").strip():
        return "settings"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "environment"
    return None


def model() -> str:
    return (settings.get("ai.model") or "").strip() or DEFAULT_MODEL


def status() -> dict:
    enabled = bool(settings.get("ai.enabled"))
    return {"enabled": enabled, "configured": enabled and api_key() is not None, "model": model()}


_clients: dict[str, anthropic.Anthropic] = {}
_clients_lock = threading.Lock()


def _client(key: str) -> anthropic.Anthropic:
    """One SDK client per key, reused so connections are pooled."""
    with _clients_lock:
        if key not in _clients:
            _clients.clear()
            _clients[key] = anthropic.Anthropic(api_key=key)
        return _clients[key]


# -- calling Claude -----------------------------------------------------------------


def complete(system: str, content: list[dict], *, schema: dict | None = None, effort: str = "low",
             timeout: float = 60.0) -> str:
    """One request; returns the answer text (JSON text when ``schema`` is given)."""
    if not settings.get("ai.enabled"):
        raise AIError(400, "ai_not_configured", "AI assist is turned off. An admin can turn it on in Settings → AI assistant.")
    key = api_key()
    if not key:
        raise AIError(400, "ai_not_configured", "Add an Anthropic API key in Settings → AI assistant to use AI assist.")
    name = model()
    output_config: dict = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    request = {
        "model": name,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": content}],
        "output_config": output_config,
    }
    client = _client(key).with_options(timeout=timeout, max_retries=1)
    try:
        if name in FALLBACK_MODELS:
            response = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **request)
        else:
            response = client.messages.create(**request)
    except anthropic.AuthenticationError:
        raise AIError(400, "ai_auth", "The Anthropic API key was rejected. Check it in Settings → AI assistant.")
    except anthropic.PermissionDeniedError:
        raise AIError(400, "ai_permission", "This Anthropic API key isn't allowed to use that model.")
    except anthropic.NotFoundError:
        raise AIError(400, "ai_model", f"The model '{name}' isn't available. Pick another in Settings → AI assistant.")
    except anthropic.RateLimitError:
        raise AIError(429, "ai_rate_limited", "Claude is busy right now. Try again in a minute.")
    except anthropic.BadRequestError as exc:
        raise AIError(502, "ai_error", f"Claude couldn't process the request: {exc.message}")
    except anthropic.APITimeoutError:
        raise AIError(502, "ai_timeout", "Claude took too long to answer. Try again.")
    except anthropic.APIConnectionError:
        raise AIError(502, "ai_unreachable", "Couldn't reach Anthropic. Check the server's internet connection.")
    except anthropic.APIStatusError as exc:
        raise AIError(502, "ai_unavailable", f"Anthropic returned an error ({exc.status_code}). Try again shortly.")
    if response.stop_reason == "refusal":
        raise AIError(422, "ai_refused", "Claude declined to help with this one.")
    text = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text").strip()
    if response.stop_reason == "max_tokens":
        raise AIError(502, "ai_incomplete", "Claude's answer was cut off. Try again.")
    if not text:
        raise AIError(502, "ai_empty", "Claude returned an empty answer. Try again.")
    return text


def complete_json(system: str, content: list[dict], schema: dict, **kwargs) -> dict:
    text = complete(system, content, schema=schema, **kwargs)
    try:
        data = json.loads(text)
    except ValueError:
        raise AIError(502, "ai_bad_output", "Claude's answer wasn't in the expected format. Try again.")
    if not isinstance(data, dict):
        raise AIError(502, "ai_bad_output", "Claude's answer wasn't in the expected format. Try again.")
    return data


# -- conversation context -----------------------------------------------------------

_QUOTE_HEADER = re.compile(
    r"^(On .{4,200}wrote:|-{2,}\s*Original Message\s*-{2,}|-{2,}\s*Forwarded message\s*-{2,}|"
    r"From: .+\n(Sent|Date): .+)",
    re.I | re.M,
)


def strip_quoted(text: str | None) -> str:
    """Drop quoted history from an email body: everything from the first 'On … wrote:'
    / 'Original Message' header, and any '>'-quoted lines. Earlier messages are in the
    transcript already."""
    if not text:
        return ""
    m = _QUOTE_HEADER.search(text)
    if m and m.start() > 0:
        text = text[: m.start()]
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    return "\n".join(lines).strip()


def _attr(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _when(value: str | None, tz) -> str:
    dt = parse_iso(value)
    return dt.astimezone(tz).strftime("%a %b %d %Y, %I:%M %p").replace(" 0", " ") if dt else ""


def transcript(user: dict, cid: int) -> tuple[str, dict]:
    """The thread as tagged text, plus the conversation summary. Raises the usual 404
    when ``user`` can't see the conversation."""
    detail = inbox_query.detail(user, cid)
    conv = detail["conversation"]
    contact = detail.get("contact") or {}
    tz = settings.timezone()
    channel = (conv.get("channel") or {}).get("type") or "internal"
    parts = [
        f'<conversation subject="{_attr(conv.get("subject"))}" channel="{_attr(channel)}" '
        f'customer="{_attr(contact.get("display_name"))}" customer_email="{_attr(contact.get("email"))}" '
        f'organization="{_attr((contact.get("organization") or {}).get("name"))}">'
    ]
    n = 0
    for item in detail["timeline"]:
        if item["type"] == "message":
            if item["status"] in ("scheduled", "failed"):
                continue
            n += 1
            body = strip_quoted(item.get("body_text") or html_to_text(item.get("body_html")))
            if len(body) > MAX_MESSAGE_CHARS:
                body = body[:MAX_MESSAGE_CHARS] + "\n[… rest of this message cut for length …]"
            if item["direction"] == "in":
                who = f'{item.get("from_name") or ""} <{item.get("from_handle") or ""}>'.strip()
                tag = "customer_message"
            else:
                who = f"{users_svc.name_of(item.get('author_id'), item.get('from_name') or 'Team')} (our team)"
                tag = "our_reply"
            parts.append(f'<{tag} n="{n}" from="{_attr(who)}" date="{_attr(_when(item["at"], tz))}">\n{body}\n</{tag}>')
        elif item["type"] == "comment":
            n += 1
            who = users_svc.name_of(item.get("user_id"), "Teammate")
            parts.append(f'<internal_note n="{n}" author="{_attr(who)}" date="{_attr(_when(item["at"], tz))}">\n'
                         f'{html_to_text(item.get("body"))}\n</internal_note>')
    parts.append("</conversation>")
    return "\n".join(parts), conv


def _today_line() -> str:
    tz = settings.timezone()
    local = now().astimezone(tz)
    return f"Today is {local.strftime('%A, %B %d, %Y')} ({settings.get('org.timezone')}); the time is {local.strftime('%I:%M %p')}."


def _thread_blocks(text: str, task: str) -> list[dict]:
    # The transcript is the stable part: cache it so a regenerate (or summarize, then
    # draft) on the same thread can reuse it. Task text varies and goes after it.
    return [
        {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": task},
    ]


# -- assists ------------------------------------------------------------------------

SUMMARY_SYSTEM = """You help a small business team keep track of customer conversations in their shared inbox.
Summarize the conversation for a teammate who hasn't read it.
- bullets: 3 to 5 short bullets, most important first: what the customer wants, the key details (quantities, dates, prices, files, decisions) and where things stand.
- next_step: the single most useful next action for the team, phrased as an instruction (for example "Send Lena the revised quote"). If nothing is needed, say that.
Use plain language with no greetings. Use only facts from the conversation. Internal notes are the team's own comments.
Write in English unless the whole conversation is in another language; then use that language."""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "bullets": {"type": "array", "items": {"type": "string"}},
        "next_step": {"type": "string"},
    },
    "required": ["bullets", "next_step"],
    "additionalProperties": False,
}


def summarize(user: dict, cid: int) -> dict:
    text, _conv = transcript(user, cid)
    data = complete_json(SUMMARY_SYSTEM, _thread_blocks(text, "Summarize this conversation."), SUMMARY_SCHEMA)
    bullets = [str(b).strip() for b in data.get("bullets") or [] if str(b).strip()][:6]
    summary_html = "<ul>" + "".join(f"<li>{html.escape(b)}</li>" for b in bullets) + "</ul>" if bullets else ""
    return {"summary_html": summary_html, "next_step": str(data.get("next_step") or "").strip()}


DRAFT_SYSTEM = """You draft replies for a small business's shared inbox. Write the reply a skilled, friendly team member would send next in this conversation.
- Answer what the customer actually asked. Use only facts from the conversation, the internal notes and the example responses. Never invent prices, dates, quantities or promises; where one is needed and unknown, leave a clear placeholder in square brackets, like [price].
- Internal notes are private team context. Let them inform the reply, but never quote them or mention that they exist.
- Match the customer's language, and the team's tone from the example responses. Be concise.
- Write only the message body: no subject line and no signature, because the app adds the signature. Greet the customer by first name when it's known.
- For email, format the body as simple HTML using only <p>, <br>, <ul>, <ol>, <li>, <b>, <i> and <a>. For text messages and website chat, write one or two short plain paragraphs, each in <p>, with no lists."""

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {"body_html": {"type": "string"}},
    "required": ["body_html"],
    "additionalProperties": False,
}


def _examples(user: dict, limit: int = 5) -> str:
    team_ids = users_svc.team_ids_of(user["id"]) or [0]
    rows = db.query(
        f"SELECT title, body_html FROM canned_responses WHERE visibility = 'shared' OR owner_user_id = ? "
        f"OR (visibility = 'team' AND team_id IN ({db.placeholders(team_ids)})) "
        f"ORDER BY usage_count DESC, id LIMIT ?",
        [user["id"], *team_ids, limit],
    )
    if not rows:
        return ""
    items = "\n".join(
        f'<example title="{_attr(r["title"])}">\n{html_to_text(r["body_html"])[:800]}\n</example>' for r in rows
    )
    return f"<example_responses>\n{items}\n</example_responses>\n"


def draft_reply(user: dict, cid: int, instructions: str | None = None) -> dict:
    text, conv = transcript(user, cid)
    channel = (conv.get("channel") or {}).get("type") or "email"
    kind = {"sms": "a text message (SMS)", "whatsapp": "a WhatsApp message", "chat": "a website chat reply"}.get(channel, "an email")
    who = user["name"] + (f", {user['title']}" if user.get("title") else "")
    task = (
        f"{_examples(user)}"
        f"Business: {settings.get('org.name')}. You are writing as {who}. The reply goes out as {kind}.\n"
        f"{_today_line()}\n"
        + (f"Guidance from {first_name(user['name'])}: {instructions.strip()}\n" if (instructions or "").strip() else "")
        + "Write the next reply to the customer."
    )
    data = complete_json(DRAFT_SYSTEM, _thread_blocks(text, task), DRAFT_SCHEMA, effort="medium", timeout=90.0)
    body = sanitize(str(data.get("body_html") or ""), "basic")
    if not body:
        raise AIError(502, "ai_empty", "Claude returned an empty draft. Try again.")
    return {"body_html": body}


EXTRACT_SYSTEM = """You turn a customer conversation at a print shop into a job ticket: what the customer wants made.
- title: short and specific, for example "200 trifold menus — Desert Bloom Café".
- description: one to three sentences with requirements not captured by the other fields.
- quantity: the number of finished pieces as an integer, or null if it isn't stated.
- due_at: when the customer needs it, as an ISO 8601 date (2026-11-10) or a date-time with a UTC offset. Resolve relative dates ("Friday", "by the 10th", "next week") against today's date given below. Use null if no date is mentioned.
- priority: "rush" if they need it within two business days or say rush or ASAP; "high" if within a week or they stress urgency; "low" if they say there's no hurry; otherwise "normal".
- specs: fill each field from the conversation and use null for anything not mentioned. Don't guess."""

DEFAULT_SPECS = [
    ("product", "Product (business cards, brochure, banner…)"),
    ("paper_stock", "Paper or material"),
    ("finished_size", "Finished size"),
    ("ink", "Ink / colors (e.g. 4/4 full color both sides)"),
    ("finishing", "Finishing (folding, binding, lamination, cutting…)"),
]


def spec_fields() -> list[tuple[str, str]]:
    rows = db.query("SELECT key, label, type, options_json FROM job_fields ORDER BY position, id")
    if not rows:
        return DEFAULT_SPECS
    out = []
    for r in rows:
        label = r["label"]
        options = db.jload(r["options_json"], []) or []
        if options:
            label += " (one of: " + ", ".join(str(o) for o in options) + ")"
        out.append((r["key"], label))
    return out


def _nullable(type_: str, description: str) -> dict:
    return {"anyOf": [{"type": type_}, {"type": "null"}], "description": description}


def extract_schema(fields: list[tuple[str, str]]) -> dict:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "quantity": _nullable("integer", "Number of finished pieces"),
            "due_at": _nullable("string", "ISO 8601 date or date-time"),
            "priority": {"type": "string", "enum": ["low", "normal", "high", "rush"]},
            "specs": {
                "type": "object",
                "properties": {key: _nullable("string", label) for key, label in fields},
                "required": [key for key, _ in fields],
                "additionalProperties": False,
            },
        },
        "required": ["title", "description", "quantity", "due_at", "priority", "specs"],
        "additionalProperties": False,
    }


def normalize_due(value, tz) -> str | None:
    """A date means end of that business day (5 PM local); a naive date-time is local."""
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            day = datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None
        return iso(datetime.combine(day, time(17, 0), tzinfo=tz))
    dt = parse_iso(text if re.search(r"(Z|[+-]\d{2}:?\d{2})$", text) else None)
    if dt is None:
        try:
            naive = datetime.fromisoformat(text)
        except ValueError:
            return None
        dt = naive.replace(tzinfo=tz) if naive.tzinfo is None else naive
    return iso(dt)


def extract_job(user: dict, cid: int) -> dict:
    text, conv = transcript(user, cid)
    fields = spec_fields()
    task = f"{_today_line()}\nExtract the job ticket for this conversation."
    data = complete_json(EXTRACT_SYSTEM, _thread_blocks(text, task), extract_schema(fields), effort="medium")
    tz = settings.timezone()
    priority = data.get("priority") if data.get("priority") in ("low", "normal", "high", "rush") else "normal"
    quantity = data.get("quantity")
    try:
        quantity = int(quantity) if quantity not in (None, "") else None
    except (TypeError, ValueError):
        quantity = None
    if quantity is not None and quantity <= 0:
        quantity = None
    raw_specs = data.get("specs") if isinstance(data.get("specs"), dict) else {}
    specs = {key: (str(raw_specs[key]).strip() if raw_specs.get(key) not in (None, "") else None) for key, _ in fields}
    return {
        "title": str(data.get("title") or conv.get("subject") or "New job").strip()[:200],
        "description": str(data.get("description") or "").strip(),
        "quantity": quantity,
        "due_at": normalize_due(data.get("due_at"), tz),
        "priority": priority,
        "specs": specs,
        "conversation_id": cid,
        "contact_id": (conv.get("contact") or {}).get("id"),
    }


EDIT_SYSTEM = """You edit messages a small business sends to its customers. You receive a draft as HTML and an editing instruction.
- Keep the meaning, facts, names, numbers, dates, prices and links exactly as they are; don't add new claims or promises.
- Keep any placeholders in square brackets.
- Return the edited message as simple HTML using only <p>, <br>, <ul>, <ol>, <li>, <b>, <i>, <u>, <a> and <blockquote>, with no subject line and no signature unless the draft already has them."""

EDIT_SCHEMA = {
    "type": "object",
    "properties": {"html": {"type": "string"}},
    "required": ["html"],
    "additionalProperties": False,
}

REWRITE_MODES = {
    "friendly": "Make it warmer and friendlier while staying professional.",
    "formal": "Make it more formal and polished.",
    "shorter": "Make it shorter and more direct. Remove filler; keep every important detail.",
    "longer": "Expand it a little with helpful detail and context, without inventing facts.",
    "fix": "Fix spelling, grammar and punctuation only. Change nothing else.",
}


def _edit(source_html: str, instruction: str) -> dict:
    clean = sanitize(source_html or "", "basic")
    if not html_to_text(clean).strip():
        raise AIError(400, "empty", "Write something first.")
    content = [{"type": "text", "text": f"<draft>\n{clean}\n</draft>\n\nInstruction: {instruction}"}]
    data = complete_json(EDIT_SYSTEM, content, EDIT_SCHEMA, effort="low")
    out = sanitize(str(data.get("html") or ""), "basic")
    if not out:
        raise AIError(502, "ai_empty", "Claude returned an empty result. Try again.")
    return {"html": out}


def rewrite(source_html: str, mode: str) -> dict:
    if mode not in REWRITE_MODES:
        raise AIError(400, "bad_mode", f"mode must be one of: {', '.join(REWRITE_MODES)}")
    return _edit(source_html, REWRITE_MODES[mode])


def translate(source_html: str, language: str) -> dict:
    language = (language or "").strip()
    if not language or len(language) > 40:
        raise AIError(400, "bad_language", "Say which language to translate into.")
    return _edit(source_html, f"Translate it into {language}. Keep the formatting.")


def test_connection() -> dict:
    """A tiny request to confirm the key and model work."""
    started = now()
    text = complete("Reply with the single word OK.", [{"type": "text", "text": "Ping"}], effort="low", timeout=30.0)
    return {"ok": True, "model": model(), "reply": text[:40],
            "latency_ms": int((now() - started) / timedelta(milliseconds=1))}
