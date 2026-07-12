"""GP-2 commit 6 — escAttr / safeUrl sanitizers in core/dom.js.

esc() (textContent→innerHTML) escapes &<> but NOT quotes, so every
`attr="${esc(untrusted)}"` was a quote-breakout XSS and every `href="${esc(url)}"`
still executed a `javascript:` scheme on click. These tests import the real
module in a live browser and assert the two new helpers close both holes.

Runs against the live SPA; auto-skips when the stack is down.
"""

from __future__ import annotations

import os

import pytest

BASE_URL = os.environ.get("ENCLAVE_PLAYWRIGHT_BASE_URL", "http://localhost:8000")


@pytest.fixture()
def dom_module(page):
    page.goto(f"{BASE_URL}/")
    # Dynamically import the ES module in page context and hang it off window.
    page.evaluate(
        """async (base) => {
            const m = await import(base + '/static/js/core/dom.js');
            window.__dom = m;
        }""",
        BASE_URL,
    )
    return page


def _call(page, fn, arg):
    return page.evaluate(f"(a) => window.__dom.{fn}(a)", arg)


def test_safeurl_neutralizes_javascript_scheme(dom_module):
    assert _call(dom_module, "safeUrl", "javascript:alert(1)") == "#"
    assert _call(dom_module, "safeUrl", "  JavaScript:alert(1)") == "#"
    assert _call(dom_module, "safeUrl", "data:text/html,<script>x</script>") == "#"
    assert _call(dom_module, "safeUrl", "vbscript:msgbox(1)") == "#"


def test_safeurl_allows_http_and_relative(dom_module):
    assert _call(dom_module, "safeUrl", "https://example.com/x") == "https://example.com/x"
    assert _call(dom_module, "safeUrl", "http://a.b/c") == "http://a.b/c"
    assert _call(dom_module, "safeUrl", "/local/path") == "/local/path"
    assert _call(dom_module, "safeUrl", "#anchor") == "#anchor"
    assert _call(dom_module, "safeUrl", "mailto:a@b.co") == "mailto:a@b.co"
    assert _call(dom_module, "safeUrl", "") == "#"


def test_safeurl_escapes_attribute_breakout(dom_module):
    # A quote in an otherwise-allowed URL must be escaped so it can't break out
    # of the href attribute and inject a new one.
    out = _call(dom_module, "safeUrl", 'https://a.b/"><img src=x onerror=alert(1)>')
    assert '"' not in out
    assert "<img" not in out  # '<' escaped to &lt;


def test_escattr_escapes_quotes_and_angles(dom_module):
    out = _call(dom_module, "escAttr", 'a" onmouseover="alert(1)')
    assert '"' not in out
    assert "&quot;" in out
    out2 = _call(dom_module, "escAttr", "x' onload='y")
    assert "'" not in out2
    assert "&#39;" in out2
    out3 = _call(dom_module, "escAttr", "<b>&</b>")
    assert out3 == "&lt;b&gt;&amp;&lt;/b&gt;"


def test_escattr_handles_nullish(dom_module):
    assert _call(dom_module, "escAttr", None) == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
