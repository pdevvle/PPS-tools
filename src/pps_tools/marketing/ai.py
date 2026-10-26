"""Shared plumbing for the Claude-powered features (ad copy + performance insights).

Requests ask for JSON that matches a schema (structured outputs), so the
answer can be used directly without scraping text. They opt into
server-side fallbacks, so a request one model declines is retried
automatically on the model Anthropic recommends for it.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept `fallbacks: "default"`.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class AIError(RuntimeError):
    """A Claude request failed; the message is meant for the dashboard user."""


def ai_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def default_client():
    import anthropic

    return anthropic.Anthropic()


def structured_request(
    client: Any,
    *,
    model: str,
    system: str,
    user: str,
    schema: dict,
    effort: str = "medium",
    max_tokens: int = 16000,
) -> dict:
    """Send one request and return the parsed JSON object Claude produced."""
    import anthropic

    kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        # The system prompt is identical across calls, so it's cached.
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    )
    if model in FALLBACK_MODELS:
        kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
    try:
        response = client.beta.messages.create(**kwargs)
    except anthropic.AuthenticationError as exc:
        raise AIError("Claude isn't set up: add a valid ANTHROPIC_API_KEY to your .env file.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AIError("This Anthropic API key isn't allowed to use that model.") from exc
    except anthropic.RateLimitError as exc:
        raise AIError("Claude is rate-limited right now — try again in a minute.") from exc
    except anthropic.APIStatusError as exc:
        raise AIError(f"Claude API error ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise AIError("Couldn't reach the Claude API — check the network connection.") from exc
    except TypeError as exc:  # raised when no credentials can be resolved
        raise AIError(f"Claude isn't set up: {exc}") from exc

    if response.stop_reason == "refusal":
        raise AIError("Claude declined this request. Try rephrasing the brief.")
    if response.stop_reason == "max_tokens":
        raise AIError("The answer was cut off before it finished. Ask for fewer formats or variants.")
    text = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Claude returned non-JSON output: %r", text[:500])
        raise AIError("Claude's answer couldn't be read. Please try again.") from exc
    if not isinstance(data, dict):
        raise AIError("Claude's answer had an unexpected shape. Please try again.")
    return data
