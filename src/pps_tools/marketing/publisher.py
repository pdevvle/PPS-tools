"""Cross-posting: write once, publish to every network now or on a schedule.

Each network has different rules (X counts characters its own way,
Instagram and Pinterest need an image, links only work in some places),
so a post is checked per target before anything is sent, and the text
can be overridden per network. Links are UTM-tagged per network so the
traffic each post drives shows up separately in analytics.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime
from typing import Optional

from pps_tools.marketing import store as st
from pps_tools.marketing.models import PostContent, PublishTarget, network_for
from pps_tools.marketing.utm import UTMError, tag_for_network

logger = logging.getLogger(__name__)

TEXT_LIMITS = {
    "facebook": 63206,
    "instagram": 2200,
    "pinterest": 800,
    "x": 280,
    "linkedin": 3000,
}
PINTEREST_TITLE_LIMIT = 100
INSTAGRAM_MAX_HASHTAGS = 30
NEEDS_IMAGE = {"instagram", "pinterest"}
# Networks where a link in the text is clickable (or attached as a link preview).
LINK_NETWORKS = {"facebook", "x", "linkedin", "pinterest"}

_URL_RE = re.compile(r"https?://\S+")
X_URL_LENGTH = 23  # X wraps every link in t.co, which always counts as 23 characters


def _x_char_weight(ch: str) -> int:
    cp = ord(ch)
    if cp <= 0x10FF or 0x2000 <= cp <= 0x200D or 0x2010 <= cp <= 0x201F or 0x2032 <= cp <= 0x2037:
        return 1
    return 2


def x_length(text: str) -> int:
    """Length as X counts it: links are 23, CJK and emoji count double."""
    total = 0
    pos = 0
    for m in _URL_RE.finditer(text):
        total += sum(_x_char_weight(c) for c in text[pos : m.start()]) + X_URL_LENGTH
        pos = m.end()
    total += sum(_x_char_weight(c) for c in text[pos:])
    return total


def text_length(network: str, text: str) -> int:
    return x_length(text) if network == "x" else len(text)


def content_for(post: dict, network: str) -> PostContent:
    """The text, link and image a given network should get for this post."""
    text = (post.get("overrides") or {}).get(network) or post["body"]
    link = post.get("link") or None
    if link and post.get("utm_campaign"):
        try:
            link = tag_for_network(link, network, post["utm_campaign"])
        except UTMError:
            pass
    if network == "x" and link and link not in text:
        text = f"{text.rstrip()}\n\n{link}"
    if network not in LINK_NETWORKS:
        link = None
    return PostContent(text=text.strip(), link=link, image_url=post.get("image_url") or None, title=post.get("title"))


def problems_for(post: dict, target: PublishTarget) -> list[str]:
    """Reasons this post can't go to this target as written (empty list = OK)."""
    network = target.network
    content = content_for(post, network)
    label = network_for(network).label
    issues = []
    limit = TEXT_LIMITS.get(network)
    length = text_length(network, content.text)
    if limit and length > limit:
        issues.append(f"{label}: text is {length:,} characters; the limit is {limit:,}.")
    if not content.text and network != "pinterest":
        issues.append(f"{label}: the post needs some text.")
    if network in NEEDS_IMAGE and not content.image_url:
        issues.append(f"{label} needs an image URL.")
    if content.image_url and not content.image_url.lower().startswith("https://"):
        issues.append(f"{label}: the image URL must be a public https:// address.")
    if network == "instagram" and content.text.count("#") > INSTAGRAM_MAX_HASHTAGS:
        issues.append(f"Instagram allows at most {INSTAGRAM_MAX_HASHTAGS} hashtags.")
    if network == "pinterest" and content.title and len(content.title) > PINTEREST_TITLE_LIMIT:
        issues.append(f"Pinterest titles are limited to {PINTEREST_TITLE_LIMIT} characters.")
    if network == "linkedin" and content.link and not (content.title or "").strip():
        issues.append("LinkedIn link posts need a title (fill in the Title field).")
    return issues


def validate(post: dict, targets: list[PublishTarget]) -> list[str]:
    if not targets:
        return ["Pick at least one place to publish."]
    issues: list[str] = []
    for t in targets:
        issues.extend(problems_for(post, t))
    return issues


def resolve_targets(hub, keys: list[str]) -> list[PublishTarget]:
    available = {t.key: t for t in hub.targets(enabled_only=False)}
    return [available[k] for k in keys if k in available]


def publish_post(hub, post_id: int, retry_failed: bool = False) -> Optional[dict]:
    """Send a post to its targets. Returns the post afterwards, or None if it was already taken."""
    from_statuses = (st.PARTIAL, st.FAILED) if retry_failed else (st.SCHEDULED, st.DRAFT)
    if not hub.store.claim_post(post_id, from_statuses):
        return None
    post = hub.store.get_post(post_id)
    results = dict(post["results"]) if retry_failed else {}
    targets = {t.key: t for t in resolve_targets(hub, post["targets"])}
    for key in post["targets"]:
        if retry_failed and results.get(key, {}).get("ok"):
            continue
        target = targets.get(key)
        if target is None:
            results[key] = {"ok": False, "error": "This destination is no longer connected."}
            continue
        issues = problems_for(post, target)
        if issues:
            results[key] = {"ok": False, "error": " ".join(issues), "network": target.network, "name": target.name}
            continue
        result = hub.publish_to(target, content_for(post, target.network))
        results[key] = {**result.to_dict(), "name": target.name}

    oks = [r.get("ok") for r in results.values()]
    status = st.PUBLISHED if oks and all(oks) else (st.PARTIAL if any(oks) else st.FAILED)
    hub.store.update_post(post_id, status=status, results=results, published_at=st.utc_iso())
    return hub.store.get_post(post_id)


def publish_due(hub, now: Optional[datetime] = None) -> list[int]:
    """Publish every scheduled post whose time has come. Safe to run from several places."""
    done = []
    for post_id in hub.store.due_post_ids(now):
        try:
            if publish_post(hub, post_id) is not None:
                done.append(post_id)
        except Exception:  # keep the scheduler alive; the post shows up as failed
            logger.exception("Publishing scheduled post %s failed", post_id)
            hub.store.update_post(post_id, status=st.FAILED)
    return done


class Scheduler(threading.Thread):
    """Background thread that publishes due posts while the web app is running."""

    def __init__(self, hub, interval: float = 60.0):
        super().__init__(name="marketing-scheduler", daemon=True)
        self.hub = hub
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                published = publish_due(self.hub)
                if published:
                    logger.info("Scheduler published post(s) %s", published)
            except Exception:
                logger.exception("Scheduler tick failed")
            self._stop_event.wait(self.interval)

    def stop(self) -> None:
        self._stop_event.set()
