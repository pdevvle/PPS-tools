"""AI ad copy: one brief in, platform-ready copy out for every network.

Each ad format has its own fields and character limits. Claude is asked
for JSON in exactly that shape; every field is then measured here
(models can't count characters reliably), and anything over a hard limit
is sent back once for a targeted rewrite.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from pps_tools.marketing.ai import AIError, default_client, structured_request
from pps_tools.marketing.publisher import x_length


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    limit: int  # hard limit: the platform rejects or cuts anything longer
    recommended: Optional[int] = None  # where text starts getting truncated in the feed
    items: Optional[tuple[int, int]] = None  # for list fields: (min, max) entries
    counter: str = "chars"  # "x" = X's weighted count

    @property
    def is_list(self) -> bool:
        return self.items is not None

    def length(self, text: str) -> int:
        return x_length(text) if self.counter == "x" else len(text)


@dataclass(frozen=True)
class CopyFormat:
    key: str
    label: str
    network: str
    fields: tuple[FieldSpec, ...]
    guidance: str
    fixed_variants: Optional[int] = None


FORMATS: dict[str, CopyFormat] = {
    f.key: f
    for f in (
        CopyFormat(
            "google_rsa",
            "Google & Microsoft Ads · Responsive search ad",
            "google",
            (
                FieldSpec("headlines", "Headlines", 30, items=(10, 15)),
                FieldSpec("descriptions", "Descriptions", 90, items=(4, 4)),
                FieldSpec("path1", "Display path 1", 15),
                FieldSpec("path2", "Display path 2", 15),
            ),
            "One asset set of 15 headlines and 4 descriptions that read well in any combination. "
            "Put a main keyword in at least 3 headlines, the offer in 2, a call to action in 2 and a "
            "trust signal (turnaround, guarantee, reviews) in 2. No exclamation marks in headlines; at "
            "most one per description. Display paths are one or two short lowercase words with no spaces.",
            fixed_variants=1,
        ),
        CopyFormat(
            "meta_feed",
            "Facebook & Instagram · Feed ad",
            "facebook",
            (
                FieldSpec("primary_text", "Primary text", 2200, recommended=125),
                FieldSpec("headline", "Headline", 255, recommended=40),
                FieldSpec("description", "Description", 255, recommended=30),
            ),
            "The first line of the primary text must hook on its own (the rest is hidden behind "
            "'See more' after about 125 characters). The headline states the benefit or offer; the "
            "description adds proof or urgency. At most two emoji.",
        ),
        CopyFormat(
            "instagram_post",
            "Instagram · Post caption",
            "instagram",
            (
                FieldSpec("caption", "Caption", 2200, recommended=300),
                FieldSpec("hashtags", "Hashtags", 40, items=(3, 8)),
            ),
            "Open with a scroll-stopping first line, keep paragraphs short and end with a call to "
            "action. Links aren't clickable in captions, so point people to the link in bio. Give 3-8 "
            "specific hashtags, each starting with #, kept separate from the caption.",
        ),
        CopyFormat(
            "pinterest_pin",
            "Pinterest · Pin",
            "pinterest",
            (
                FieldSpec("title", "Title", 100, recommended=40),
                FieldSpec("description", "Description", 800, recommended=250),
            ),
            "Pinterest works like a search engine: front-load the descriptive phrases people search "
            "for (for example 'wedding invitation ideas'). Inspiring and useful rather than salesy.",
        ),
        CopyFormat(
            "x_post",
            "X · Post",
            "x",
            (FieldSpec("text", "Post", 280, recommended=220, counter="x"),),
            "Punchy and conversational, one idea per post, at most two hashtags. A link counts as 23 "
            "characters; leave it out of the text (it is added when publishing).",
        ),
        CopyFormat(
            "linkedin_sponsored",
            "LinkedIn · Sponsored content",
            "linkedin",
            (
                FieldSpec("intro_text", "Introductory text", 600, recommended=150),
                FieldSpec("headline", "Headline", 200, recommended=70),
                FieldSpec("description", "Description", 300, recommended=100),
            ),
            "Professional and specific for business buyers (marketing managers, office managers, event "
            "planners). Lead with a business problem, use concrete numbers, no hype.",
        ),
        CopyFormat(
            "tiktok_infeed",
            "TikTok · In-feed ad",
            "tiktok",
            (
                FieldSpec("ad_text", "Ad text", 100, recommended=80),
                FieldSpec("hook", "On-screen hook (first 2 seconds)", 60),
                FieldSpec("script", "15-second video outline", 600),
            ),
            "Native and casual, like a creator talking to camera. The hook has to stop the scroll in "
            "under two seconds. No emoji in the ad text. The outline is 3-5 short beats with what is "
            "shown and said.",
        ),
    )
}

GOALS = {
    "awareness": "Awareness — get the business noticed by new local customers",
    "traffic": "Traffic — get clicks to the landing page",
    "leads": "Leads — get quote requests or sign-ups",
    "conversions": "Sales — get people to order online",
}

SYSTEM_TEMPLATE = """You are a senior direct-response copywriter and paid-media strategist writing ads for one business.

About the business:
{brand}

How you work:
- Write for the specific platform and placement; each has its own format, limits and culture (rules below).
- Character limits are hard limits. Stay comfortably under every one of them; shorter is fine.
- Every variant takes a clearly different angle (for example speed, price, quality, convenience, social proof or a seasonal hook). Name it in "angle" in two to four words.
- Be concrete: name the product, the offer and the benefit. Use only prices, discounts, guarantees and turnaround times that appear in the brief or the business description; never invent them.
- Plain, confident language. No clickbait, no ALL-CAPS words (abbreviations are fine), no unprovable superlatives such as "best" or "#1".
- Follow ad policies: no personal-attribute phrasing ("Are you struggling with...?"), no misleading urgency.
- "strategy" is two or three sentences on the overall approach and what to test first.

Platform rules:
{rules}"""


def system_prompt(brand_context: str) -> str:
    rules = []
    for fmt in FORMATS.values():
        limits = []
        for f in fmt.fields:
            text = f"{f.name}: max {f.limit} characters"
            if f.items:
                text = f"{f.name}: {f.items[0]}-{f.items[1]} items, each max {f.limit} characters"
            if f.recommended:
                text += f" (aim for {f.recommended} or fewer)"
            limits.append(text)
        rules.append(f"[{fmt.key}] {fmt.label}\n  Fields: " + "; ".join(limits) + f"\n  {fmt.guidance}")
    return SYSTEM_TEMPLATE.format(brand=brand_context, rules="\n\n".join(rules))


@dataclass
class CopyBrief:
    product: str
    formats: list[str]
    offer: str = ""
    audience: str = ""
    tone: str = "Friendly, confident and clear"
    goal: str = "conversions"
    landing_url: str = ""
    keywords: str = ""
    notes: str = ""
    variants: int = 3

    def cleaned(self) -> "CopyBrief":
        formats = [f for f in self.formats if f in FORMATS]
        if not self.product.strip():
            raise AIError("Describe the product or service to advertise.")
        if not formats:
            raise AIError("Pick at least one ad format.")
        return CopyBrief(
            product=self.product.strip()[:2000],
            formats=formats,
            offer=self.offer.strip()[:500],
            audience=self.audience.strip()[:500],
            tone=(self.tone or "Friendly, confident and clear").strip()[:200],
            goal=self.goal if self.goal in GOALS else "conversions",
            landing_url=self.landing_url.strip()[:500],
            keywords=self.keywords.strip()[:500],
            notes=self.notes.strip()[:1500],
            variants=max(1, min(int(self.variants or 3), 5)),
        )

    def to_dict(self) -> dict:
        return asdict(self)


def variant_count(fmt: CopyFormat, brief: CopyBrief) -> int:
    return fmt.fixed_variants or brief.variants


def build_schema(formats: list[str]) -> dict:
    format_props = {}
    for key in formats:
        fmt = FORMATS[key]
        props: dict[str, Any] = {"angle": {"type": "string"}}
        for f in fmt.fields:
            props[f.name] = {"type": "array", "items": {"type": "string"}} if f.is_list else {"type": "string"}
        format_props[key] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": props,
                "required": list(props),
                "additionalProperties": False,
            },
        }
    return {
        "type": "object",
        "properties": {
            "strategy": {"type": "string"},
            "formats": {
                "type": "object",
                "properties": format_props,
                "required": list(formats),
                "additionalProperties": False,
            },
        },
        "required": ["strategy", "formats"],
        "additionalProperties": False,
    }


def brief_message(brief: CopyBrief) -> str:
    lines = [
        "Write ad copy for this brief.",
        "",
        f"Product or service: {brief.product}",
        f"Goal: {GOALS[brief.goal]}",
        f"Tone: {brief.tone}",
    ]
    if brief.offer:
        lines.append(f"Offer: {brief.offer}")
    if brief.audience:
        lines.append(f"Audience: {brief.audience}")
    if brief.landing_url:
        lines.append(f"Landing page: {brief.landing_url}")
    if brief.keywords:
        lines.append(f"Keywords to work in: {brief.keywords}")
    if brief.notes:
        lines.append(f"Other notes: {brief.notes}")
    lines.append("")
    lines.append("Formats to write:")
    for key in brief.formats:
        fmt = FORMATS[key]
        n = variant_count(fmt, brief)
        unit = "asset set" if fmt.fixed_variants else "variant"
        lines.append(f"- {key}: {n} {unit}{'s' if n != 1 else ''}")
    return "\n".join(lines)


def check_variant(fmt: CopyFormat, variant: dict) -> list[dict]:
    """Measure every field against the format's limits."""
    issues = []
    for f in fmt.fields:
        value = variant.get(f.name)
        if f.is_list:
            items = [v for v in (value or []) if isinstance(v, str)]
            lo, hi = f.items
            if len(items) < lo or len(items) > hi:
                issues.append({"field": f.name, "level": "warning",
                               "message": f"{f.label}: {len(items)} given; expected {lo}–{hi}."})
            for i, item in enumerate(items, 1):
                n = f.length(item)
                if n > f.limit:
                    issues.append({"field": f.name, "level": "error",
                                   "message": f"{f.label} #{i} is {n} characters (limit {f.limit}).", "index": i - 1})
        else:
            text = value if isinstance(value, str) else ""
            n = f.length(text)
            if n > f.limit:
                issues.append({"field": f.name, "level": "error", "message": f"{f.label} is {n} characters (limit {f.limit})."})
            elif f.recommended and n > f.recommended:
                issues.append({"field": f.name, "level": "warning",
                               "message": f"{f.label} is {n} characters; over {f.recommended} may be truncated."})
    return issues


def _normalize(fmt: CopyFormat, variant: Any) -> dict:
    out = {"angle": str((variant or {}).get("angle", "")).strip()}
    for f in fmt.fields:
        value = (variant or {}).get(f.name)
        if f.is_list:
            out[f.name] = [str(v).strip() for v in value or [] if str(v).strip()]
        else:
            out[f.name] = str(value or "").strip()
    return out


@dataclass
class CopyResult:
    strategy: str
    formats: dict[str, list[dict]] = field(default_factory=dict)
    issues: dict[str, list[list[dict]]] = field(default_factory=dict)
    model: str = ""
    repaired: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class Copywriter:
    def __init__(self, brand_context: str, model: str = "claude-opus-5-5", client: Any = None, effort: str = "medium"):
        self.brand_context = brand_context
        self.model = model
        self.effort = effort
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = default_client()
        return self._client

    def _request(self, user: str, formats: list[str]) -> dict:
        return structured_request(
            self.client,
            model=self.model,
            system=system_prompt(self.brand_context),
            user=user,
            schema=build_schema(formats),
            effort=self.effort,
        )

    def _assemble(self, data: dict, formats: list[str]) -> CopyResult:
        result = CopyResult(strategy=str(data.get("strategy", "")).strip(), model=self.model)
        raw_formats = data.get("formats") or {}
        for key in formats:
            fmt = FORMATS[key]
            variants = [_normalize(fmt, v) for v in raw_formats.get(key) or []]
            result.formats[key] = variants
            result.issues[key] = [check_variant(fmt, v) for v in variants]
        return result

    def generate(self, brief: CopyBrief) -> CopyResult:
        brief = brief.cleaned()
        result = self._assemble(self._request(brief_message(brief), brief.formats), brief.formats)
        errors = {
            key: [(i, issue) for i, issues in enumerate(per_variant) for issue in issues if issue["level"] == "error"]
            for key, per_variant in result.issues.items()
        }
        if any(errors.values()):
            result = self._repair(brief, result, errors)
        return result

    def _repair(self, brief: CopyBrief, draft: CopyResult, errors: dict) -> CopyResult:
        """One targeted rewrite of the fields that broke a hard limit."""
        problems = []
        for key, items in errors.items():
            for i, issue in items:
                problems.append(f"- {key}, variant {i + 1}: {issue['message']}")
        draft_json = json.dumps({"strategy": draft.strategy, "formats": draft.formats}, ensure_ascii=False)
        user = (
            brief_message(brief)
            + "\n\nA previous draft for this brief broke hard character limits:\n"
            + "\n".join(problems)
            + "\n\nRewrite only those items so they fit, shortening them while keeping their meaning. "
            "Keep every other item exactly as it is and return the complete JSON.\n\nDraft:\n"
            + draft_json
        )
        try:
            fixed = self._assemble(self._request(user, brief.formats), brief.formats)
        except AIError:
            return draft
        fixed.repaired = True
        return fixed
