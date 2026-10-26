"""The HTML sanitizer is the line between inbound email and our origin."""

from __future__ import annotations

import pytest

from pps_tools.switchboard.services.sanitize import is_blank, mention_ids, sanitize


@pytest.mark.parametrize("payload", [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<a href=\"javascript:alert(1)\">x</a>",
    "<a href=\"  JaVaScRiPt:alert(1)\">x</a>",
    "<a href=\"java&#x09;script:alert(1)\">x</a>",
    "<iframe src=\"https://evil.test\"></iframe>",
    "<svg><script>alert(1)</script></svg>",
    "<svg onload=alert(1)>",
    "<object data=\"x.swf\"></object>",
    "<div style=\"background:url(javascript:alert(1))\">x</div>",
    "<div style=\"width: expression(alert(1))\">x</div>",
    "<form action=\"https://evil.test\"><input name=p></form>",
    "<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>",
    "<a href=\"vbscript:msgbox(1)\">x</a>",
    "<img src=\"data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==\">",
])
@pytest.mark.parametrize("profile", ["basic", "email"])
def test_dangerous_markup_is_neutralized(payload, profile):
    out = sanitize(payload, profile).lower()
    assert "<script" not in out
    assert "onerror" not in out and "onload" not in out
    assert "javascript:" not in out and "vbscript:" not in out
    assert "<iframe" not in out and "<svg" not in out and "<object" not in out
    assert "expression(" not in out
    assert "<form" not in out and "<input" not in out
    assert "data:text/html" not in out


def test_basic_profile_keeps_formatting_and_mentions():
    html = ('<p>Hi <b>there</b> <span data-mention="7">@Joe</span> '
            '<a href="https://pps.test/x">link</a></p><ul><li>one</li></ul>')
    out = sanitize(html, "basic")
    assert "<b>there</b>" in out
    assert '<span data-mention="7">@Joe</span>' in out
    assert 'href="https://pps.test/x"' in out and 'target="_blank"' in out
    assert "<li>one</li>" in out
    assert mention_ids(out) == [7]


def test_basic_profile_drops_styles_and_tables():
    out = sanitize('<style>p{color:red}</style><table><tr><td style="color:red">x</td></tr></table>', "basic")
    assert "<style" not in out and "<table" not in out and "style=" not in out
    assert "x" in out


def test_email_profile_keeps_layout():
    html = ('<html><head><title>T</title><style>.a{color:red}</style></head><body>'
            '<table cellpadding="4"><tr><td class="a" style="color: blue">Cell</td></tr></table>'
            '<img src="cid:logo123" alt="Logo"></body></html>')
    out = sanitize(html, "email")
    assert "<style>.a{color:red}</style>" in out
    assert 'cellpadding="4"' in out and 'class="a"' in out and 'style="color: blue"' in out
    assert 'src="cid:logo123"' in out
    assert "<title>" not in out and "T</" not in out


def test_unclosed_tags_are_closed():
    assert sanitize("<b>bold <i>both", "basic") == "<b>bold <i>both</i></b>"


def test_text_is_escaped():
    assert sanitize("1 < 2 & 3 > 2", "basic") == "1 &lt; 2 &amp; 3 &gt; 2"


def test_is_blank():
    assert is_blank("<p><br></p>")
    assert is_blank("<div>&nbsp;</div>")
    assert not is_blank("<p>x</p>")
    assert not is_blank('<p><img src="cid:x"></p>')
