"""Regression assertions for api/static/*.html.

Each Week-1 task adds one test. A failing test BEFORE the fix demonstrates the
bug; a passing test AFTER demonstrates the fix. Tests are deliberately coarse —
they target invariants, not implementation.
"""
from __future__ import annotations


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
