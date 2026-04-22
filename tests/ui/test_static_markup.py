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


def test_switchtab_does_not_rely_on_bare_event_global(index_html_text):
    """switchTab must accept the element explicitly, not read a bare global."""
    # Extract the switchTab function body.
    m = re.search(r"function\s+switchTab\s*\(([^)]*)\)\s*\{", index_html_text)
    assert m is not None, "switchTab function not found"
    params = [p.strip() for p in m.group(1).split(",") if p.strip()]
    # Signature must include an element param alongside name.
    assert len(params) >= 2, (
        f"switchTab signature is {params!r}; must accept (name, el)"
    )
    # And no caller may still rely on the implicit `event` global:
    # find function body bounds.
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
    body = index_html_text[start : i - 1]
    assert "event.currentTarget" not in body, (
        "switchTab still references event.currentTarget — use the el parameter"
    )


def test_index_does_not_load_external_cdns(index_html_text):
    """Privacy promise: no external CDN loads in the shipped HTML."""
    for needle in [
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "cdnjs.cloudflare.com",
        "cdn.jsdelivr.net",
        "unpkg.com",
    ]:
        assert needle not in index_html_text, (
            f"external CDN reference remains: {needle}"
        )


def test_setup_does_not_load_external_cdns(setup_html_text):
    """Setup wizard must also run offline."""
    for needle in [
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "cdnjs.cloudflare.com",
        "cdn.jsdelivr.net",
        "unpkg.com",
    ]:
        assert needle not in setup_html_text, (
            f"setup.html external CDN reference remains: {needle}"
        )


def test_color_tokens_are_honest(index_html_text):
    """Token values must match their semantic name.

    --amber rendering as green and --warn missing entirely were caught
    in the audit; this guards against regression.
    """
    m = re.search(r":root\s*\{([^}]*)\}", index_html_text)
    assert m is not None, ":root CSS variable block not found"
    root = m.group(1)

    def hex_to_rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    def is_green(hex_str: str) -> bool:
        r, g, b = hex_to_rgb(hex_str)
        return g > r and g > b

    # If --warn is defined, its base hex (not an alias) must actually be
    # amber/orange — i.e. NOT green-dominant.
    warn = re.search(r"--warn:\s*#([0-9A-Fa-f]{6})\b", root)
    assert warn is not None, "--warn token missing — introduce a real amber for warnings"
    assert not is_green(warn.group(1)), (
        f"--warn resolves to green #{warn.group(1)} — must be amber/orange"
    )

    # --danger must also exist as a real red.
    danger = re.search(r"--danger:\s*#([0-9A-Fa-f]{6})\b", root)
    assert danger is not None, "--danger token missing"
    dr, dg, db = hex_to_rgb(danger.group(1))
    assert dr > dg and dr > db, (
        f"--danger #{danger.group(1)} is not red-dominant"
    )
