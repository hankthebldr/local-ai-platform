"""Regression assertions for api/static/*.html.

Each Week-1 task adds one test. A failing test BEFORE the fix demonstrates the
bug; a passing test AFTER demonstrates the fix. Tests are deliberately coarse —
they target invariants, not implementation.
"""
from __future__ import annotations

import re


def test_index_html_loads(index_soup):
    """Sanity: index.html parses as HTML and has a <title>."""
    title = index_soup.find("title")
    assert title is not None
    assert title.text.strip() != ""


def test_index_header_says_enclave_not_cortex(index_html_text):
    """Header branding must read 'Enclave', not 'CORTEX' or 'LOCAL AI PLATFORM'."""
    assert "CORTEX" not in index_html_text, "legacy CORTEX branding still present"
    assert (
        "LOCAL AI PLATFORM" not in index_html_text
    ), "legacy LOCAL AI PLATFORM still present"
    assert (
        "Mission Control" not in index_html_text
    ), "legacy 'Mission Control' tagline still present"


def test_index_footer_version_matches_api(index_html_text):
    """Footer version must match the 0.1.0 release declared in api/main.py."""
    assert "v1.0.0" not in index_html_text, "stale v1.0.0 footer still present"
    assert (
        "Enclave v0.1.0" in index_html_text
    ), "footer must read 'Enclave v0.1.0'"


def test_mobile_media_query_contains_all_responsive_rules(index_html_text):
    """The mobile @media block must wrap all six responsive rule blocks."""
    m = re.search(
        r"@media\s*\(\s*max-width:\s*800px\s*\)\s*\{",
        index_html_text,
    )
    assert m is not None, "mobile @media block not found"
    start = m.end()
    depth = 1
    i = start
    while i < len(index_html_text) and depth > 0:
        c = index_html_text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    block = index_html_text[start : i - 1]
    for selector in [
        ".research-layout",
        ".dashboard-grid",
        ".header",
        ".inv-grid",
        ".mem-grid",
        ".tab-btn",
    ]:
        assert selector in block, (
            f"{selector} is not inside the mobile media query"
        )


def test_chat_input_is_textarea(index_soup):
    """Chat prompt must be a <textarea> so Shift+Enter can insert newlines."""
    el = index_soup.find(id="prompt")
    assert el is not None, "#prompt element missing"
    assert el.name == "textarea", (
        f"#prompt is <{el.name}>, must be <textarea>"
    )


def test_chat_input_has_shift_enter_handler(index_html_text):
    """JS must distinguish Enter (send) from Shift+Enter (newline)."""
    assert (
        "e.shiftKey" in index_html_text or "shiftKey" in index_html_text
    ), "Shift+Enter branch missing from keydown handler"
