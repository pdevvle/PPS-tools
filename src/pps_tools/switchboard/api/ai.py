"""AI assist API (Claude). Everything except /status and the admin settings needs the
'inbox' permission and access to the conversation it works on."""

from __future__ import annotations

import functools

from flask import Blueprint

from pps_tools.switchboard.services import ai, inbox, settings
from pps_tools.switchboard.web import ApiError, as_int, body, current_user, login_required, ok, require, require_fields

bp = Blueprint("ai", __name__)


def _ai_errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ai.AIError as exc:
            raise ApiError(exc.status, exc.code, exc.message)

    return wrapper


def _conversation_id(data: dict, required: bool = True) -> int | None:
    if required:
        require_fields(data, "conversation_id")
    cid = as_int(data.get("conversation_id"), "conversation_id")
    if cid is not None:
        inbox.get_for(current_user(), cid)  # 404 unless they can see it
    return cid


@bp.get("/api/ai/status")
@login_required
def status():
    return ok(ai.status())


@bp.post("/api/ai/summarize")
@require("inbox")
@_ai_errors
def summarize():
    cid = _conversation_id(body())
    return ok(ai.summarize(current_user(), cid))


@bp.post("/api/ai/draft")
@require("inbox")
@_ai_errors
def draft():
    data = body()
    cid = _conversation_id(data)
    instructions = (data.get("instructions") or "").strip()[:2000] or None
    return ok(ai.draft_reply(current_user(), cid, instructions))


@bp.post("/api/ai/extract-job")
@require("inbox")
@_ai_errors
def extract_job():
    cid = _conversation_id(body())
    return ok(ai.extract_job(current_user(), cid))


@bp.post("/api/ai/rewrite")
@require("inbox")
@_ai_errors
def rewrite():
    data = body()
    _conversation_id(data, required=False)
    require_fields(data, "html", "mode")
    return ok(ai.rewrite(data["html"], data["mode"]))


@bp.post("/api/ai/translate")
@require("inbox")
@_ai_errors
def translate():
    data = body()
    _conversation_id(data, required=False)
    require_fields(data, "html", "language")
    return ok(ai.translate(data["html"], data["language"]))


@bp.get("/api/ai/settings")
@require("admin")
def get_ai_settings():
    stored = (settings.get("ai.api_key") or "").strip()
    return ok({
        "enabled": bool(settings.get("ai.enabled")),
        "model": ai.model(),
        "models": ai.MODELS,
        "key_source": ai.key_source(),
        "key_hint": ("…" + stored[-4:]) if stored else None,
        "configured": ai.status()["configured"],
    })


@bp.post("/api/ai/test")
@require("admin")
@_ai_errors
def test():
    return ok(ai.test_connection())


def bootstrap(user: dict) -> dict:
    return {"ai": ai.status()}
