"""
Admin dropdown — after the IA reorg the dropdown is intentionally lean:

    System  ·  Cloud Models  ·  Exports

System is a HUB spanning Memory · License Keys · Runs, surfaced via an
in-panel sub-nav. Plugins, Skills, and MCP are now top-level tabs and are
covered in `test_top_level_tabs.py`.
"""

from __future__ import annotations


def _open_admin(page):
    """Open the Admin dropdown so menuitems are clickable."""
    trigger = page.locator("#admin-trigger")
    if trigger.get_attribute("aria-expanded") != "true":
        trigger.click()
    page.wait_for_selector("#admin-menu", state="visible", timeout=2_000)


def test_admin_dropdown_has_expected_menu_order(signed_in_page):
    """Lean three-item dropdown: System (hub) · Cloud Models · Exports.
    If this drifts, somebody re-promoted a panel into the dropdown that
    should live elsewhere."""
    page = signed_in_page
    _open_admin(page)
    items = page.locator("#admin-menu .admin-menu-item").all_inner_texts()
    expected = ["System", "Cloud Models", "Exports"]
    cleaned = [t.strip() for t in items if t.strip()]
    assert (
        cleaned == expected
    ), f"Admin dropdown order drifted.\n  expected: {expected}\n  actual:   {cleaned}"


def test_admin_system_opens_memory_panel(signed_in_page):
    """Admin → System routes to the Memory tab content (Memory is the
    default landing inside the System hub)."""
    page = signed_in_page
    _open_admin(page)
    page.click('#admin-menu .admin-menu-item:has-text("System")')
    page.wait_for_selector("#tab-memory", state="visible", timeout=5_000)
    page.wait_for_function(
        """() => {
            const m = document.querySelector('#tab-memory');
            return m && m.innerText.length > 0;
        }""",
        timeout=10_000,
    )


def test_admin_cloud_models_panel_renders(signed_in_page):
    """Cloud Models is where per-provider OUTBOUND API keys live (OpenAI,
    Gemini, Anthropic). Distinct from the Enclave license key."""
    page = signed_in_page
    _open_admin(page)
    page.click('#admin-menu .admin-menu-item:has-text("Cloud Models")')
    page.wait_for_selector("#tab-admin-cloud", state="visible", timeout=5_000)


def test_admin_exports_panel_renders(signed_in_page):
    """Admin → Exports must render the export interface."""
    page = signed_in_page
    _open_admin(page)
    page.click('#admin-menu .admin-menu-item:has-text("Exports")')
    page.wait_for_selector("#tab-admin-exports", state="visible", timeout=5_000)


# ── System hub — Memory · License Keys · Runs sub-nav ─────────────────────


def test_system_subnav_present_on_memory(signed_in_page):
    """When you land on Memory via Admin → System, the System sub-nav is
    visible at the top with Memory marked active."""
    page = signed_in_page
    _open_admin(page)
    page.click('#admin-menu .admin-menu-item:has-text("System")')
    page.wait_for_selector("#tab-memory .system-subnav", state="visible", timeout=5_000)
    active = page.locator("#tab-memory .system-subnav-link.active").inner_text().strip()
    # .system-subnav-link has text-transform: uppercase — compare case-insensitive.
    assert (
        active.lower() == "memory"
    ), f"Active sub-nav link should be 'Memory', got {active!r}"


def test_system_subnav_navigates_to_license_keys(signed_in_page):
    """Click System → License Keys via the in-panel sub-nav. The License
    Keys panel renders with the LICENSE KEYS header (no lock state)."""
    page = signed_in_page
    _open_admin(page)
    page.click('#admin-menu .admin-menu-item:has-text("System")')
    page.wait_for_selector("#tab-memory .system-subnav", state="visible", timeout=5_000)
    page.click('#tab-memory .system-subnav-link:has-text("License Keys")')
    page.wait_for_selector("#tab-admin-keys", state="visible", timeout=5_000)

    header = page.locator("#tab-admin-keys .panel-label").first.inner_text()
    assert "LICENSE KEYS" in header.upper(), f"License Keys header missing: {header!r}"
    assert (
        page.locator("#tab-admin-keys .admin-lock").count() == 0
    ), "License Keys panel rendered locked under unified auth"

    # And the sub-nav at the top still shows you're in System, now with
    # License Keys active.
    active = (
        page.locator("#tab-admin-keys .system-subnav-link.active").inner_text().strip()
    )
    assert active.lower() == "license keys"


def test_system_subnav_navigates_to_runs(signed_in_page):
    """Click System → Runs via the in-panel sub-nav. Runs is the workflow
    run history; it must render under the System sub-nav."""
    page = signed_in_page
    _open_admin(page)
    page.click('#admin-menu .admin-menu-item:has-text("System")')
    page.wait_for_selector("#tab-memory .system-subnav", state="visible", timeout=5_000)
    page.click('#tab-memory .system-subnav-link:has-text("Runs")')
    page.wait_for_selector("#tab-workflows", state="visible", timeout=5_000)
    active = (
        page.locator("#tab-workflows .system-subnav-link.active").inner_text().strip()
    )
    assert active.lower() == "runs"


def test_no_admin_lock_state_anywhere(signed_in_page):
    """Regression guard: no panel reachable via the dropdown or the System
    sub-nav should render the dual-tier locked state."""
    page = signed_in_page

    # Dropdown items
    for menuitem in ["Cloud Models", "Exports"]:
        _open_admin(page)
        page.click(f'#admin-menu .admin-menu-item:has-text("{menuitem}")')
        page.wait_for_timeout(400)
        lock = page.locator(".admin-lock:visible").count()
        assert lock == 0, f"Admin → {menuitem} rendered locked under unified auth"

    # System sub-nav items
    _open_admin(page)
    page.click('#admin-menu .admin-menu-item:has-text("System")')
    for sub in ["Memory", "License Keys", "Runs"]:
        page.click(f".system-subnav-link:visible:has-text('{sub}')")
        page.wait_for_timeout(400)
        assert (
            page.locator(".admin-lock:visible").count() == 0
        ), f"System → {sub} rendered locked under unified auth"
