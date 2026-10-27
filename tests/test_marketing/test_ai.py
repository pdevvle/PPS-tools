"""Claude features: the request we send, the copy checks, and insight vetting."""

import json
from types import SimpleNamespace

import pytest

import anthropic

httpx2 = pytest.importorskip("httpx2")  # the HTTP library under anthropic>=1.0
from pps_tools.marketing.ai import AIError, structured_request
from pps_tools.marketing.copywriter import FORMATS, CopyBrief, Copywriter, build_schema, check_variant
from pps_tools.marketing.insights import Analyst, apply_recommendation
from pps_tools.marketing.models import ACTIVE, PAUSED


def sdk_client(handler):
    """A real Anthropic client whose HTTP traffic goes to `handler` instead of the network."""
    return anthropic.Anthropic(
        api_key="test-key",
        base_url="http://anthropic.test",
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )


def message(payload: dict, stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


class TestStructuredRequest:
    def test_request_shape(self):
        seen = {}

        def handler(request):
            seen["headers"] = request.headers
            seen["body"] = json.loads(request.content)
            return httpx2.Response(200, json=message({"ok": True}))

        out = structured_request(sdk_client(handler), model="claude-opus-5-5", system="sys", user="hi",
                                 schema={"type": "object", "properties": {"ok": {"type": "boolean"}},
                                         "required": ["ok"], "additionalProperties": False}, effort="high")
        assert out == {"ok": True}
        body = seen["body"]
        assert body["fallbacks"] == "default"
        assert seen["headers"]["anthropic-beta"] == "server-side-fallback-2026-07-01"
        assert body["output_config"]["effort"] == "high"
        assert body["output_config"]["format"]["type"] == "json_schema"
        assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert "temperature" not in body

    def test_models_without_server_side_fallback_skip_it(self):
        seen = {}

        def handler(request):
            seen["body"] = json.loads(request.content)
            seen["beta"] = request.headers.get("anthropic-beta")
            return httpx2.Response(200, json=message({"ok": True}))

        structured_request(sdk_client(handler), model="claude-haiku-5-5", system="s", user="u", schema={"type": "object"})
        assert "fallbacks" not in seen["body"] and seen["beta"] is None

    @pytest.mark.parametrize("stop_reason,needle", [("refusal", "declined"), ("max_tokens", "cut off")])
    def test_unusable_stops_raise_friendly_errors(self, stop_reason, needle):
        client = sdk_client(lambda r: httpx2.Response(200, json=message({}, stop_reason)))
        with pytest.raises(AIError, match=needle):
            structured_request(client, model="claude-opus-5-5", system="s", user="u", schema={"type": "object"})

    def test_bad_key(self):
        client = sdk_client(lambda r: httpx2.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}))
        client = client.with_options(max_retries=0)
        with pytest.raises(AIError, match="ANTHROPIC_API_KEY"):
            structured_request(client, model="claude-opus-5-5", system="s", user="u", schema={"type": "object"})


class StubClient:
    """Returns canned JSON answers in order; records every request."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        text = json.dumps(self.answers.pop(0))
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


GOOD_RSA = {"angle": "Speed", "headlines": ["Business Cards in 2 Days"] * 12, "descriptions": ["Premium 16pt cards printed fast."] * 4,
            "path1": "cards", "path2": "fast"}


class TestCopywriter:
    def test_schema_matches_selected_formats(self):
        schema = build_schema(["x_post", "google_rsa"])
        props = schema["properties"]["formats"]["properties"]
        assert set(props) == {"x_post", "google_rsa"}
        item = props["google_rsa"]["items"]
        assert item["additionalProperties"] is False
        assert item["properties"]["headlines"] == {"type": "array", "items": {"type": "string"}}
        assert set(item["required"]) == {"angle", "headlines", "descriptions", "path1", "path2"}

    def test_checks_use_platform_limits(self):
        long_headline = dict(GOOD_RSA, headlines=["x" * 31] + GOOD_RSA["headlines"][1:])
        issues = check_variant(FORMATS["google_rsa"], long_headline)
        assert [i["level"] for i in issues] == ["error"] and "limit 30" in issues[0]["message"]
        x_issue = check_variant(FORMATS["x_post"], {"angle": "a", "text": "y" * 250})
        assert x_issue and x_issue[0]["level"] == "warning"  # over the 220 we aim for, under the 280 hard limit

    def test_generate_returns_checked_copy(self):
        stub = StubClient({"strategy": "Lead with speed.", "formats": {"google_rsa": [GOOD_RSA]}})
        result = Copywriter("A print shop.", client=stub).generate(CopyBrief(product="Business cards", formats=["google_rsa"]))
        assert result.strategy == "Lead with speed." and not result.repaired
        assert result.issues["google_rsa"] == [[]]
        request = stub.requests[0]
        assert "google_rsa: 1 asset set" in request["messages"][0]["content"]
        assert "A print shop." in request["system"][0]["text"]

    def test_hard_limit_breaks_trigger_one_targeted_rewrite(self):
        too_long = dict(GOOD_RSA, headlines=["Way Too Long Headline For Google Ads"] + GOOD_RSA["headlines"][1:])
        stub = StubClient({"strategy": "s", "formats": {"google_rsa": [too_long]}},
                          {"strategy": "s", "formats": {"google_rsa": [GOOD_RSA]}})
        result = Copywriter("A print shop.", client=stub).generate(CopyBrief(product="Cards", formats=["google_rsa"]))
        assert result.repaired and result.issues["google_rsa"] == [[]]
        assert "Headlines #1 is 36 characters (limit 30)" in stub.requests[1]["messages"][0]["content"]

    def test_brief_validation(self):
        with pytest.raises(AIError):
            CopyBrief(product=" ", formats=["x_post"]).cleaned()
        with pytest.raises(AIError):
            CopyBrief(product="Cards", formats=["myspace"]).cleaned()
        assert CopyBrief(product="Cards", formats=["x_post"], variants=99).cleaned().variants == 5


SNAPSHOT = {
    "totals": {"current": {"spend": 500}},
    "campaigns": [
        {"key": "google_ads:1:10", "platform": "google_ads", "name": "Search", "status": ACTIVE, "daily_budget": 40.0, "budget_editable": True},
        {"key": "meta:act_1:20", "platform": "meta", "name": "Prospecting", "status": PAUSED, "daily_budget": None, "budget_editable": False},
    ],
}


def rec(**kw):
    base = {"title": "t", "detail": "d", "priority": "high", "platform": "google_ads", "campaign_key": "",
            "action": "other", "change_pct": 0, "expected_impact": ""}
    base.update(kw)
    return base


class TestInsights:
    def test_vet_keeps_only_safe_campaign_actions(self):
        report = {"recommendations": [
            rec(campaign_key="google_ads:1:10", action="increase_budget", change_pct=80),
            rec(campaign_key="google_ads:1:999", action="pause"),
            rec(campaign_key="meta:act_1:20", action="enable"),
            rec(campaign_key="google_ads:1:10", action="enable"),
        ]}
        recs = Analyst("biz", max_budget_change_pct=50).vet(report, SNAPSHOT)["recommendations"]
        assert recs[0]["applicable"] and recs[0]["change_pct"] == 50 and recs[0]["new_budget"] == 60.0
        assert recs[1]["campaign_key"] == "" and recs[1]["action"] == "other" and not recs[1]["applicable"]
        assert recs[2]["applicable"]  # paused campaign can be enabled
        assert not recs[3]["applicable"]  # already active

    def test_empty_data_is_refused_before_calling_claude(self):
        stub = StubClient()
        with pytest.raises(AIError, match="no ad data"):
            Analyst("biz", client=stub).analyze({"campaigns": [], "totals": {"current": {"spend": 0}}})
        assert stub.requests == []

    def test_apply_uses_the_hub_with_the_cap(self):
        calls = []
        hub = SimpleNamespace(
            set_campaign_status=lambda key, status, actor: calls.append(("status", key, status, actor)) or SimpleNamespace(name="Search"),
            set_campaign_budget=lambda key, amount, actor, enforce_cap: calls.append(("budget", key, amount, enforce_cap))
            or SimpleNamespace(name="Search", daily_budget=amount),
        )
        assert "Paused" in apply_recommendation(hub, {"campaign_key": "k", "action": "pause"})
        apply_recommendation(hub, {"campaign_key": "k", "action": "increase_budget", "new_budget": 60.0})
        assert calls == [("status", "k", PAUSED, "AI insights"), ("budget", "k", 60.0, True)]
        with pytest.raises(AIError):
            apply_recommendation(hub, {"campaign_key": "", "action": "pause"})
