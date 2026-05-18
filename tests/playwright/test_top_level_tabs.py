"""
Top-level tabs — Plugins, Skills, and MCP were promoted out of the admin
dropdown to first-class tabs. This file guards that promotion: each tab
is reachable directly from the main nav, renders its content under
unified auth, and never falls into a locked state.
"""

from __future__ import annotations


def test_top_level_nav_has_promoted_tabs(signed_in_page):
    """Plugins, Skills, MCP must be reachable from the main tab strip,
    not buried in the Admin dropdown."""
    page = signed_in_page
    for data_tab, label in [
        ("admin-plugins", "Plugins"),
        ("admin-skills", "Skills"),
        ("admin-mcp", "MCP"),
    ]:
        btn = page.locator(f'.tab-nav button[data-tab="{data_tab}"]')
        assert btn.count() == 1, f"top-level {label!r} tab missing from nav"
        # .tab-btn has text-transform: uppercase — compare case-insensitively.
        assert (
            label.lower() in btn.inner_text().lower()
        ), f"top-level tab {data_tab} should display {label!r}; got {btn.inner_text()!r}"


def test_top_level_nav_no_longer_has_runs(signed_in_page):
    """Runs moved into the System hub — it must NOT remain as a top-level tab."""
    page = signed_in_page
    runs_at_top = page.locator('.tab-nav button[data-tab="workflows"]:has-text("Runs")')
    assert (
        runs_at_top.count() == 0
    ), "Runs is still a top-level tab; should be in System"


def test_top_level_plugins_lists_xdm_toolkit(signed_in_page):
    """Plugins tab must list the xdm-toolkit plugin (3 tools, 2 skills).
    Waits for the async plugin-list fetch to complete — the initial render
    shows just a security warning banner (~150 chars), so a length-based
    wait must clear that threshold."""
    page = signed_in_page
    page.click('.tab-nav button[data-tab="admin-plugins"]')
    page.wait_for_selector("#tab-admin-plugins", state="visible", timeout=5_000)
    # Wait for the plugin list to actually appear, not just the banner.
    page.wait_for_function(
        """() => {
            const el = document.getElementById('tab-admin-plugins');
            return el && (el.innerText.toLowerCase().includes('xdm-toolkit')
                       || el.innerText.toLowerCase().includes('xdm toolkit')
                       || el.innerText.length > 500);
        }""",
        timeout=20_000,
    )
    text = page.locator("#tab-admin-plugins").inner_text()
    assert (
        "xdm-toolkit" in text.lower() or "xdm" in text.lower()
    ), f"xdm-toolkit not listed in top-level Plugins tab; got: {text[:300]}"


def test_top_level_skills_tab_renders(signed_in_page):
    """Skills tab must render content (xdm-toolkit ships with 2 skills)."""
    page = signed_in_page
    page.click('.tab-nav button[data-tab="admin-skills"]')
    page.wait_for_selector("#tab-admin-skills", state="visible", timeout=5_000)
    page.wait_for_function(
        "() => document.getElementById('tab-admin-skills').innerText.length > 30",
        timeout=15_000,
    )


def test_top_level_mcp_tab_renders(signed_in_page):
    """MCP Servers tab must render even when the server list is empty
    (the default state on a fresh stack)."""
    page = signed_in_page
    page.click('.tab-nav button[data-tab="admin-mcp"]')
    page.wait_for_selector("#tab-admin-mcp", state="visible", timeout=5_000)


def test_top_level_promoted_tabs_not_locked(signed_in_page):
    """Regression: no top-level tab should render the legacy admin-lock state."""
    page = signed_in_page
    for data_tab in ["admin-plugins", "admin-skills", "admin-mcp"]:
        page.click(f'.tab-nav button[data-tab="{data_tab}"]')
        page.wait_for_timeout(400)
        assert (
            page.locator(f"#tab-{data_tab} .admin-lock:visible").count() == 0
        ), f"tab-{data_tab} rendered locked under unified auth"
