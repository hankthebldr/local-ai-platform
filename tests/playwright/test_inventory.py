"""
Models tab (#tab-inventory) — local inventory + HuggingFace discovery.

Lower-stakes than the workflow/chat tests but a known regression site:
the Models tab silently 401'd in the dual-tier era and showed an empty
catalogue. This file guards the unified-auth path on the Models surface.
"""

from __future__ import annotations

import pytest
import requests


def test_models_tab_renders(signed_in_page):
    """Switching to the Models tab makes #tab-inventory visible."""
    page = signed_in_page
    page.click('button[data-tab="inventory"]')
    page.wait_for_selector("#tab-inventory", state="visible", timeout=5_000)


def test_models_tab_lists_locally_installed_models(
    signed_in_page, base_url, api_headers
):
    """Whatever Ollama has pulled should appear in the local-models section
    of the Models tab. The container ships with no models; this test skips
    in that state so it doesn't false-fail on a fresh stack."""
    r = requests.get(f"{base_url}/v1/models", headers=api_headers, timeout=5)
    r.raise_for_status()
    installed = [m["id"] for m in r.json().get("data", [])]
    if not installed:
        pytest.skip("No models pulled; nothing to assert against")

    page = signed_in_page
    page.click('button[data-tab="inventory"]')
    page.wait_for_selector("#tab-inventory", state="visible", timeout=5_000)
    page.wait_for_function(
        "() => document.getElementById('tab-inventory').innerText.length > 100",
        timeout=15_000,
    )
    panel_text = page.locator("#tab-inventory").inner_text()
    # At least one installed model name should appear in the tab content.
    assert any(
        m in panel_text for m in installed
    ), f"None of the installed models {installed!r} appear in the Models tab"


def test_models_tab_count_badge_reflects_installed_count(
    signed_in_page, base_url, api_headers
):
    """The #inv-count badge on the Models tab button should equal the count
    of locally installed models."""
    r = requests.get(f"{base_url}/v1/models", headers=api_headers, timeout=5)
    installed_count = len(r.json().get("data", []))
    page = signed_in_page
    # Give the count poller a moment.
    page.wait_for_timeout(2_000)
    badge = page.locator("#inv-count")
    if badge.count() == 0 or not badge.inner_text().strip():
        pytest.skip("inv-count badge not yet populated — variant build")
    text = badge.inner_text().strip()
    digits = "".join(c for c in text if c.isdigit())
    if digits:
        assert (
            int(digits) == installed_count
        ), f"#inv-count={digits} but /v1/models reports {installed_count} installed"


def test_models_discover_section_is_present(signed_in_page):
    """Models tab must expose the Discover sub-section (HuggingFace catalogue).
    Discover is collapsible; we just assert the toggle exists."""
    page = signed_in_page
    page.click('button[data-tab="inventory"]')
    page.wait_for_selector("#tab-inventory", state="visible", timeout=5_000)
    # The Discover section is keyed off the disc-count badge or refresh button.
    discover = page.locator("#disc-refresh-btn")
    assert (
        discover.count() == 1
    ), "Discover section / refresh button missing from Models tab"
