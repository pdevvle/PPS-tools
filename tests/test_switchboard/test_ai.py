"""AI assist: what goes to Claude (model, refusal fallbacks, structured output, cached
transcript), how answers are cleaned up, how failures surface, and who may use it.
The Anthropic client is faked, so nothing leaves the machine."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import anthropic
import pytest

from pps_tools.switchboard import db
from pps_tools.switchboard.services import ai, inbox, settings
from pps_tools.switchboard.services.inbox import Inbound
from pps_tools.switchboard.util import get_zone, iso, now_iso, token

try:  # the SDK's HTTP library (httpx2 in current releases, httpx before)
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

PHX = get_zone("America/Phoenix")


class FakeClaude:
    """Stands in for anthropic.Anthropic: records each request, answers from a queue."""

    def __init__(self):
        self.requests: list[tuple[str, dict]] = []
        self.options: list[dict] = []
        self.answers: list = ["{}"]
        self.stop_reason = "end_turn"
        self.messages = SimpleNamespace(create=lambda **kw: self._create("messages", kw))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: self._create("beta", kw)))

    def with_options(self, **kw):
        self.options.append(kw)
        return self

    def _create(self, namespace, kw):
        self.requests.append((namespace, kw))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[
            SimpleNamespace(type="thinking", thinking="…"),
            SimpleNamespace(type="text", text=text),
        ])

    @property
    def last(self):
        return self.requests[-1]


def api_error(cls, status):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=request), body=None)


def set_setting(key, value):
    with db.transaction():
        settings.set(key, value)


@pytest.fixture
def claude(client, monkeypatch):
    fake = FakeClaude()
    monkeypatch.setattr(ai, "_client", lambda key: fake)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    set_setting("ai.api_key", "sk-ant-test-1234")
    return fake


def make_conversation(body="Hi! Can you print 250 trifold menus on 100lb gloss by Friday?", visibility="shared", owner_id=None):
    with db.transaction():
        ch_id = db.insert("channels", {
            "type": "email", "name": "Orders", "address": f"{token(4)}@shop.test", "visibility": visibility,
            "owner_user_id": owner_id, "config_json": "{}", "public_key": token(8), "created_at": now_iso(),
        })
    channel = db.one("SELECT * FROM channels WHERE id = ?", ch_id)
    quoted = "\n\nOn Mon, Oct 5, 2026 at 9:00 AM Shop <orders@shop.test> wrote:\n> an older message we already have"
    msg = inbox.deliver_inbound(Inbound(
        channel=channel, kind="email", from_handle="lena@cafe.test", from_name="Lena Ortiz", subject="Menu reprint",
        body_text=body + quoted, external_id=f"<{token(6)}@cafe.test>",
    ))
    return msg["conversation_id"]


# -- status & configuration --------------------------------------------------------------


def test_status_and_not_configured(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.get("/api/ai/status") == {"enabled": True, "configured": False, "model": "claude-opus-5-5"}
    cid = make_conversation()
    err = client.post("/api/ai/summarize", {"conversation_id": cid}, expect=400)["error"]
    assert err["code"] == "ai_not_configured"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    assert client.get("/api/ai/status")["configured"] is True
    assert client.get("/api/ai/settings")["key_source"] == "environment"
    set_setting("ai.enabled", False)
    assert client.get("/api/ai/status")["configured"] is False
    assert client.post("/api/ai/summarize", {"conversation_id": cid}, expect=400)["error"]["code"] == "ai_not_configured"


def test_settings_never_expose_the_key(client, claude, make_user):
    res = client.get("/api/ai/settings")
    assert res["key_hint"] == "…1234" and res["key_source"] == "settings" and res["configured"] is True
    assert res["models"][0]["id"] == "claude-opus-5-5"
    assert "sk-ant-test-1234" not in json.dumps(res)
    assert "ai.api_key" not in client.get("/api/settings")["settings"]
    _, agent = make_user("agent")
    agent.get("/api/ai/settings", expect=403)
    agent.post("/api/ai/test", expect=403)
    agent.patch("/api/settings", {"ai.api_key": "sk-ant-mine"}, expect=403)


def test_save_key_and_model_then_test_connection(client, claude):
    client.patch("/api/settings", {"ai.api_key": "sk-ant-new-9999", "ai.model": "claude-sonnet-5-5"})
    assert client.get("/api/ai/settings")["key_hint"] == "…9999"
    claude.answers = ["OK"]
    res = client.post("/api/ai/test")
    assert res["ok"] is True and res["model"] == "claude-sonnet-5-5" and res["reply"] == "OK"
    namespace, req = claude.last
    assert namespace == "beta" and req["model"] == "claude-sonnet-5-5" and req["fallbacks"] == "default"
    logged = db.one("SELECT data_json FROM audit_log WHERE action = 'settings.update' ORDER BY id DESC LIMIT 1")
    assert "sk-ant-new-9999" not in logged["data_json"]


# -- requests ---------------------------------------------------------------------------


def test_summarize_request_shape(client, claude):
    cid = make_conversation()
    claude.answers = [{"bullets": ["Wants 250 trifold menus", "Needs them <b>Friday</b>"], "next_step": "Send a quote"}]
    res = client.post("/api/ai/summarize", {"conversation_id": cid})
    assert res == {"summary_html": "<ul><li>Wants 250 trifold menus</li><li>Needs them &lt;b&gt;Friday&lt;/b&gt;</li></ul>",
                   "next_step": "Send a quote"}

    namespace, req = claude.last
    assert namespace == "beta"  # Opus 5.5 goes through server-side refusal fallbacks
    assert req["betas"] == [ai.FALLBACK_BETA] and req["fallbacks"] == "default"
    assert req["model"] == "claude-opus-5-5" and req["max_tokens"] == ai.MAX_TOKENS
    assert "temperature" not in req and "thinking" not in req
    assert req["output_config"]["effort"] == "low"
    assert req["output_config"]["format"] == {"type": "json_schema", "schema": ai.SUMMARY_SCHEMA}
    assert claude.options[-1] == {"timeout": 60.0, "max_retries": 1}

    transcript, task = req["messages"][0]["content"]
    assert transcript["cache_control"] == {"type": "ephemeral"} and "cache_control" not in task
    assert '<customer_message n="1" from="Lena Ortiz &lt;lena@cafe.test&gt;"' in transcript["text"]
    assert "250 trifold menus" in transcript["text"]
    assert "an older message we already have" not in transcript["text"]  # quoted history is stripped


def test_other_models_use_the_plain_endpoint(client, claude):
    set_setting("ai.model", "claude-haiku-5-5")
    cid = make_conversation()
    claude.answers = [{"bullets": ["One"], "next_step": "Reply"}]
    client.post("/api/ai/summarize", {"conversation_id": cid})
    namespace, req = claude.last
    assert namespace == "messages" and req["model"] == "claude-haiku-5-5"
    assert "betas" not in req and "fallbacks" not in req


def test_draft_is_sanitized_and_follows_guidance(client, claude):
    cid = make_conversation()
    with db.transaction():
        db.insert("canned_responses", {"title": "Quote follow-up", "body_html": "<p>Thanks for asking! Here's your quote.</p>",
                                       "created_at": now_iso()})
    claude.answers = [{"body_html": '<p>Hi Lena,</p><script>alert(1)</script><p onclick="x()">Yes, we can.</p>'}]
    res = client.post("/api/ai/draft", {"conversation_id": cid, "instructions": "Mention the 10% reorder discount"})
    assert "<script" not in res["body_html"] and "onclick" not in res["body_html"]
    assert "Hi Lena," in res["body_html"] and "Yes, we can." in res["body_html"]
    _, req = claude.last
    task = req["messages"][0]["content"][1]["text"]
    assert "Mention the 10% reorder discount" in task and "Quote follow-up" in task and "an email" in task
    assert req["output_config"]["effort"] == "medium" and claude.options[-1]["timeout"] == 90.0


def test_extract_job_normalizes_the_answer(client, claude):
    cid = make_conversation()
    claude.answers = [{
        "title": "250 trifold menus", "description": "Reprint of last spring's menu.", "quantity": "250",
        "due_at": "2026-11-06", "priority": "whenever",
        "specs": {"product": "Trifold menu", "paper_stock": "100lb gloss", "finished_size": None, "ink": "", "finishing": "Fold"},
    }]
    res = client.post("/api/ai/extract-job", {"conversation_id": cid})
    assert res["title"] == "250 trifold menus" and res["quantity"] == 250 and res["priority"] == "normal"
    assert res["due_at"] == iso(datetime(2026, 11, 6, 17, 0, tzinfo=PHX))  # a bare date means 5 PM local
    assert res["specs"] == {"product": "Trifold menu", "paper_stock": "100lb gloss", "finished_size": None, "ink": None,
                            "finishing": "Fold"}
    assert res["conversation_id"] == cid and res["contact_id"]
    schema = claude.last[1]["output_config"]["format"]["schema"]
    assert schema["properties"]["specs"]["required"] == ["product", "paper_stock", "finished_size", "ink", "finishing"]
    assert {"type": "null"} in schema["properties"]["quantity"]["anyOf"]


def test_normalize_due():
    assert ai.normalize_due("2026-11-06T09:30", PHX) == "2026-11-06T16:30:00.000Z"  # naive means local
    assert ai.normalize_due("2026-11-06T09:30:00Z", PHX) == "2026-11-06T09:30:00.000Z"
    assert ai.normalize_due("next Friday", PHX) is None
    assert ai.normalize_due(None, PHX) is None


def test_rewrite_and_translate(client, claude):
    claude.answers = [{"html": "<p>Hello there!</p><img src=x onerror=alert(1)>"}]
    res = client.post("/api/ai/rewrite", {"html": "<p>hello ther</p>", "mode": "fix"})
    assert res["html"].startswith("<p>Hello there!</p>") and "onerror" not in res["html"]
    assert "Fix spelling" in claude.last[1]["messages"][0]["content"][0]["text"]
    claude.answers = [{"html": "<p>¡Hola!</p>"}]
    assert client.post("/api/ai/translate", {"html": "<p>Hello!</p>", "language": "Spanish"})["html"] == "<p>¡Hola!</p>"
    assert "Translate it into Spanish" in claude.last[1]["messages"][0]["content"][0]["text"]
    assert client.post("/api/ai/rewrite", {"html": "<p>x</p>", "mode": "pirate"}, expect=400)["error"]["code"] == "bad_mode"
    assert client.post("/api/ai/rewrite", {"html": "<p> </p>", "mode": "fix"}, expect=400)["error"]["code"] == "empty"
    client.post("/api/ai/translate", {"html": "<p>Hi</p>", "language": ""}, expect=400)
    assert client.post("/api/ai/translate", {"html": "<p>Hi</p>", "language": "x" * 41}, expect=400)["error"]["code"] == "bad_language"


# -- failures ---------------------------------------------------------------------------


@pytest.mark.parametrize("failure, status, code", [
    (lambda: api_error(anthropic.AuthenticationError, 401), 400, "ai_auth"),
    (lambda: api_error(anthropic.NotFoundError, 404), 400, "ai_model"),
    (lambda: api_error(anthropic.RateLimitError, 429), 429, "ai_rate_limited"),
    (lambda: api_error(anthropic.InternalServerError, 500), 502, "ai_unavailable"),
    (lambda: anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com")), 502, "ai_timeout"),
    (lambda: anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")), 502, "ai_unreachable"),
])
def test_api_errors_become_friendly_errors(client, claude, failure, status, code):
    cid = make_conversation()
    claude.answers = [failure()]
    assert client.post("/api/ai/summarize", {"conversation_id": cid}, expect=status)["error"]["code"] == code


def test_refusals_and_bad_answers(client, claude):
    cid = make_conversation()
    claude.stop_reason = "refusal"
    assert client.post("/api/ai/summarize", {"conversation_id": cid}, expect=422)["error"]["code"] == "ai_refused"
    claude.stop_reason = "max_tokens"
    assert client.post("/api/ai/summarize", {"conversation_id": cid}, expect=502)["error"]["code"] == "ai_incomplete"
    claude.stop_reason = "end_turn"
    claude.answers = ["this is not json"]
    assert client.post("/api/ai/summarize", {"conversation_id": cid}, expect=502)["error"]["code"] == "ai_bad_output"
    claude.answers = [""]
    assert client.post("/api/ai/summarize", {"conversation_id": cid}, expect=502)["error"]["code"] == "ai_empty"


# -- permissions --------------------------------------------------------------------------


def test_permissions(client, claude, owner, make_user):
    private = make_conversation(visibility="personal", owner_id=owner["id"])
    _, agent = make_user("agent")
    _, staff = make_user("staff")
    claude.answers = [{"bullets": ["x"], "next_step": "y"}]
    agent.post("/api/ai/summarize", {"conversation_id": private}, expect=404)  # can't see it
    staff.post("/api/ai/summarize", {"conversation_id": private}, expect=403)
    staff.post("/api/ai/rewrite", {"html": "<p>x</p>", "mode": "fix"}, expect=403)
    assert staff.get("/api/ai/status")["configured"] is True
    client.post("/api/ai/summarize", {"conversation_id": private})
    assert len(claude.requests) == 1  # only the owner's request reached Claude
