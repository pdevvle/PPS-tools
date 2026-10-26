"""Allow-list HTML sanitizer.

Two profiles:

* ``email`` — for inbound mail. Keeps layout markup (tables, inline styles, <style>
  blocks, classes) because newsletters and invoices need it. The web app additionally
  renders it in a sandboxed iframe with a restrictive CSP, so this is defence in depth.
* ``basic`` — for comments, chat and composer output: simple formatting, links,
  lists, quotes, code, and mention chips (``<span data-mention="12">``).

Anything not explicitly allowed is dropped: scripts, frames, forms, SVG, event
handlers, javascript:/vbscript: URLs, CSS expressions and @import.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

VOID = {"br", "hr", "img", "col", "wbr", "area", "source"}

# Dropped together with everything inside them.
DROP_CONTENT = {"script", "noscript", "iframe", "frame", "frameset", "object", "embed", "applet",
                "svg", "math", "template", "title", "textarea", "select", "button"}

BASIC_TAGS = {"a", "b", "strong", "i", "em", "u", "s", "strike", "del", "br", "p", "div", "span",
              "ul", "ol", "li", "blockquote", "code", "pre", "h1", "h2", "h3", "h4", "hr", "sub", "sup",
              "mark", "img"}

EMAIL_TAGS = BASIC_TAGS | {
    "abbr", "address", "article", "aside", "big", "caption", "center", "cite", "col", "colgroup",
    "dd", "details", "dfn", "dl", "dt", "figcaption", "figure", "font", "footer", "h5", "h6",
    "header", "ins", "kbd", "main", "nav", "q", "samp", "section", "small", "summary", "table",
    "tbody", "td", "tfoot", "th", "thead", "tr", "tt", "var", "wbr", "style", "label", "legend",
    "fieldset", "picture", "time", "bdi", "bdo", "ruby", "rt", "rp", "html", "body", "head",
}

GLOBAL_ATTRS = {"title", "dir", "lang", "align"}
EMAIL_GLOBAL_ATTRS = GLOBAL_ATTRS | {"style", "class", "id", "valign", "width", "height", "bgcolor",
                                     "color", "border", "background"}

TAG_ATTRS = {
    "a": {"href", "name", "target"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan", "nowrap", "scope", "headers"},
    "th": {"colspan", "rowspan", "nowrap", "scope", "headers"},
    "table": {"cellpadding", "cellspacing", "summary", "frame", "rules"},
    "col": {"span"},
    "colgroup": {"span"},
    "font": {"face", "size", "color"},
    "ol": {"start", "type", "reversed"},
    "li": {"value"},
    "blockquote": {"cite", "type"},
    "q": {"cite"},
    "time": {"datetime"},
    "span": {"data-mention"},
    "details": {"open"},
}

SAFE_URL_SCHEMES = ("http:", "https:", "mailto:", "tel:", "sms:", "cid:")
_CTRL_RE = re.compile(r"[\x00-\x20\x7f]+")
_CSS_BAD_RE = re.compile(r"expression\s*\(|javascript\s*:|vbscript\s*:|behavior\s*:|-moz-binding|@import", re.I)
_CSS_URL_RE = re.compile(r"url\s*\(\s*(['\"]?)(.*?)\1\s*\)", re.I)


def _safe_url(value: str, allow_data_image: bool = False) -> str | None:
    raw = html.unescape(value or "").strip()
    probe = _CTRL_RE.sub("", raw).lower()
    if not probe:
        return None
    if probe.startswith(("#", "/")) and not probe.startswith("//"):
        return raw
    if allow_data_image and re.match(r"^data:image/(png|jpe?g|gif|webp|bmp);base64,", probe):
        return raw
    if probe.startswith("//"):
        return "https:" + raw.lstrip()
    if ":" not in probe.split("/")[0]:
        return raw  # relative path
    if probe.startswith(SAFE_URL_SCHEMES):
        return raw
    return None


def _safe_css(css: str) -> str:
    css = _CTRL_RE.sub(" ", css)
    if _CSS_BAD_RE.search(css):
        css = _CSS_BAD_RE.sub("", css)

    def fix_url(m):
        url = _safe_url(m.group(2), allow_data_image=True)
        return f"url('{url}')" if url and "'" not in url else "none"

    return _CSS_URL_RE.sub(fix_url, css)


class _Sanitizer(HTMLParser):
    def __init__(self, profile: str):
        super().__init__(convert_charrefs=False)
        self.email = profile == "email"
        self.tags = EMAIL_TAGS if self.email else BASIC_TAGS
        self.global_attrs = EMAIL_GLOBAL_ATTRS if self.email else GLOBAL_ATTRS
        self.out: list[str] = []
        self.stack: list[str] = []
        self.drop_depth = 0
        self.drop_tag: str | None = None
        self.in_style = False

    # -- tags --------------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, self_closing=True)

    def _start(self, tag, attrs, self_closing):
        tag = tag.lower()
        if self.drop_depth:
            if tag == self.drop_tag and not self_closing:
                self.drop_depth += 1
            return
        if tag in DROP_CONTENT or (tag == "style" and not self.email):
            if not self_closing and tag not in VOID:
                self.drop_depth = 1
                self.drop_tag = tag
            return
        if tag not in self.tags:
            return  # drop the tag, keep its children
        if tag in ("html", "body", "head"):
            return
        allowed = self.global_attrs | TAG_ATTRS.get(tag, set())
        parts = []
        href_seen = False
        for name, value in attrs:
            name = name.lower()
            if name.startswith("on") or name not in allowed:
                continue
            value = value or ""
            if name in ("href", "src", "background", "cite"):
                safe = _safe_url(value, allow_data_image=(tag == "img" and name == "src"))
                if safe is None:
                    continue
                value = safe
                if name == "href":
                    href_seen = True
            elif name == "style":
                value = _safe_css(value)
            elif name == "target":
                continue  # forced below
            elif name == "data-mention" and not value.isdigit():
                continue
            parts.append(f' {name}="{html.escape(value, quote=True)}"')
        if tag == "a" and href_seen:
            parts.append(' target="_blank" rel="noopener noreferrer nofollow"')
        if tag == "style":
            self.in_style = True
        self.out.append(f"<{tag}{''.join(parts)}>")
        if tag not in VOID and not self_closing:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.drop_depth:
            if tag == self.drop_tag:
                self.drop_depth -= 1
                if self.drop_depth == 0:
                    self.drop_tag = None
            return
        if tag not in self.stack:
            return
        # close anything left open inside it
        while self.stack:
            open_tag = self.stack.pop()
            self.out.append(f"</{open_tag}>")
            if open_tag == "style":
                self.in_style = False
            if open_tag == tag:
                break

    # -- content -----------------------------------------------------------

    def handle_data(self, data):
        if self.drop_depth:
            return
        if self.in_style:
            self.out.append(_safe_css(data).replace("</", "<\\/"))
        else:
            self.out.append(html.escape(data, quote=False))

    def handle_entityref(self, name):
        if not self.drop_depth:
            self.out.append(f"&{name};" if re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,31}", name) else "")

    def handle_charref(self, name):
        if not self.drop_depth:
            self.out.append(f"&#{name};" if re.fullmatch(r"[xX]?[0-9a-fA-F]{1,8}", name) else "")

    def handle_comment(self, data):
        pass  # drops conditional comments too

    def handle_decl(self, decl):
        pass

    def handle_pi(self, data):
        pass

    def unknown_decl(self, data):
        pass

    def result(self) -> str:
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def sanitize(markup: str | None, profile: str = "basic") -> str:
    if not markup:
        return ""
    parser = _Sanitizer(profile)
    parser.feed(markup)
    parser.close()
    return parser.result().strip()


def mention_ids(markup: str | None) -> list[int]:
    """User ids from ``<span data-mention="12">`` chips, in order, unique."""
    seen, out = set(), []
    for m in re.finditer(r'data-mention="(\d+)"', markup or ""):
        uid = int(m.group(1))
        if uid not in seen:
            seen.add(uid)
            out.append(uid)
    return out


def is_blank(markup: str | None) -> bool:
    """True when the HTML has no visible text and no images."""
    if not markup:
        return True
    if "<img" in markup.lower():
        return False
    text = re.sub(r"<[^>]+>", "", markup)
    text = html.unescape(text).replace("\xa0", " ")
    return not text.strip()
