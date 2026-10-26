"""UTM link building, so every network's traffic lands in analytics labelled the same way."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id")

# utm_source / utm_medium per network, for paid ads and for organic posts.
NETWORK_PRESETS = {
    "google": {"paid": ("google", "cpc"), "organic": ("google", "organic")},
    "facebook": {"paid": ("facebook", "paid_social"), "organic": ("facebook", "social")},
    "instagram": {"paid": ("instagram", "paid_social"), "organic": ("instagram", "social")},
    "pinterest": {"paid": ("pinterest", "paid_social"), "organic": ("pinterest", "social")},
    "x": {"paid": ("x", "paid_social"), "organic": ("x", "social")},
    "linkedin": {"paid": ("linkedin", "paid_social"), "organic": ("linkedin", "social")},
    "tiktok": {"paid": ("tiktok", "paid_social"), "organic": ("tiktok", "social")},
    # What Microsoft's own UTM auto-tagging uses for search ads.
    "microsoft": {"paid": ("bing", "cpc"), "organic": ("bing", "organic")},
    "email": {"paid": ("newsletter", "email"), "organic": ("newsletter", "email")},
}


class UTMError(ValueError):
    pass


def slug(text: str) -> str:
    """'Spring Sale — Business Cards!' -> 'spring-sale-business-cards'."""
    text = re.sub(r"[^a-z0-9]+", "-", (text or "").lower())
    return text.strip("-")[:80]


def build_url(
    base_url: str,
    source: str,
    medium: str,
    campaign: str,
    term: Optional[str] = None,
    content: Optional[str] = None,
    campaign_id: Optional[str] = None,
) -> str:
    """Add UTM parameters to a URL, replacing any it already has and keeping the rest."""
    base_url = (base_url or "").strip()
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise UTMError("Enter a full web address starting with http:// or https://")
    if not (source and medium and campaign):
        raise UTMError("Source, medium and campaign are required.")
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in UTM_KEYS]
    utm = [
        ("utm_source", source.strip()),
        ("utm_medium", medium.strip()),
        ("utm_campaign", campaign.strip()),
        ("utm_term", (term or "").strip()),
        ("utm_content", (content or "").strip()),
        ("utm_id", (campaign_id or "").strip()),
    ]
    query = urlencode(kept + [(k, v) for k, v in utm if v])
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", query, parts.fragment))


def tag_for_network(url: str, network: str, campaign: str, paid: bool = False, content: Optional[str] = None) -> str:
    preset = NETWORK_PRESETS.get(network, {"paid": (network, "paid_social"), "organic": (network, "social")})
    source, medium = preset["paid" if paid else "organic"]
    return build_url(url, source, medium, slug(campaign) or "post", content=content)


def google_ads_final_url_suffix() -> str:
    """A Final URL suffix for Google Ads that fills UTMs from ValueTrack parameters."""
    return (
        "utm_source=google&utm_medium=cpc&utm_campaign={campaignid}"
        "&utm_content={creative}&utm_term={keyword}"
    )
