"""LB0-U2 — Admin ▸ Sources panel (js/admin/sources.js + #tab-admin-sources).

Two layers, mirroring test_library_shell.py:

1. Static assertions (bs4 / served-JS corpus): the panel ships the spec'd
   data-action grammar, the ApiKeysPanel-strict gate (isSignedIn +
   renderLock BEFORE any fetch), the #tab-admin-sources markup + Sources
   admin-menu item carry NO inline on*= handlers, main.js re-emits
   adminPanelActivated for admin-sources, and no new window global leaks.

2. Runtime (Playwright against the dev server, skipped when unreachable):
   signed OUT → the lock screen renders and NO /api/discover fetch fires;
   signed IN → providers + config panels render from the gated routes.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "api" / "static"
SOURCES_JS = (STATIC / "js" / "admin" / "sources.js").read_text(encoding="utf-8")
MAIN_JS = (STATIC / "js" / "main.js").read_text(encoding="utf-8")
INDEX_HTML = (STATIC / "index.html").read_text(encoding="utf-8")


# ── 1. Static: data-action grammar ─────────────────────────────────────────


def test_sources_panel_registers_spec_actions():
    for action in [
        "'admin.sources.refresh-one'",
        "'admin.sources.edit'",
        "'admin.sources.save'",
    ]:
        assert action in SOURCES_JS, f"sources.js missing delegated action {action}"
    # Wiring helpers (menu open / modal cancel) also ride Actions — the
    # no-new-inline-handlers rule leaves them no other home.
    assert "'admin.sources.open'" in SOURCES_JS
    assert "'admin.sources.cancel'" in SOURCES_JS


def test_markup_uses_data_actions_not_inline_handlers():
    # The Sources menu item + the whole #tab-admin-sources subtree must be
    # inline-handler-free (all new wiring rides js/shell/actions.js).
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(INDEX_HTML, "html.parser")
    menu_btn = soup.select_one('#admin-menu [data-panel="admin-sources"]')
    assert menu_btn is not None, "Sources item missing from #admin-menu"
    assert menu_btn.get("data-action") == "admin.sources.open"

    tab = soup.select_one("#tab-admin-sources")
    assert tab is not None, "#tab-admin-sources markup missing"
    offenders = [
        (el.name, attr)
        for el in [tab, menu_btn, *tab.find_all(True)]
        for attr in el.attrs
        if attr.lower().startswith("on")
    ]
    assert offenders == [], f"inline handlers found in new markup: {offenders}"

    # Spec'd action buttons present in the markup.
    assert tab.select_one('[data-action="admin.sources.edit"]') is not None
    assert tab.select_one('[data-action="admin.sources.save"]') is not None
    assert tab.select_one('[data-action="admin.sources.cancel"]') is not None


def test_edit_modal_secret_hygiene():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(INDEX_HTML, "html.parser")
    tok = soup.select_one("#admin-sources-token")
    assert tok is not None
    assert tok.get("type") == "password"
    assert tok.get("autocomplete") == "off"
    # The JS never writes a value into the token field (masked placeholder
    # only) and clears it on close.
    assert "tok.value = ''" in SOURCES_JS


# ── 2. Static: ApiKeysPanel-strict gate ────────────────────────────────────


def test_gate_isSignedIn_renderLock_before_any_fetch():
    assert "AdminAuth.isSignedIn()" in SOURCES_JS
    assert "AdminAuth.renderLock('admin-sources')" in SOURCES_JS
    # The gate must appear BEFORE the first fetch in the module source —
    # a crude but effective order check on the load() path.
    gate_at = SOURCES_JS.index("AdminAuth.isSignedIn()")
    fetch_at = SOURCES_JS.index("AdminAuth.fetch(")
    assert gate_at < fetch_at, "gate must precede any fetch"
    # Every fetch rides AdminAuth.fetch (admin tier), never bare Net.call.
    assert "Net.call" not in SOURCES_JS


def test_panel_listens_for_activation_and_main_reemits():
    assert "adminPanelActivated" in SOURCES_JS
    assert "'admin-sources'" in SOURCES_JS
    # switchTab's admin-* re-emit list includes admin-sources (deep-link path).
    m = re.search(
        r"if \(name === 'admin-plugins'[^)]*'admin-sources'\)", MAIN_JS, re.S
    )
    assert m, "main.js switchTab re-emit list must include admin-sources"
    assert "./admin/sources.js" in MAIN_JS


def test_no_new_window_global():
    assert "window.SourcesPanel" not in SOURCES_JS
    assert "window.SourcesPanel" not in MAIN_JS


def test_hits_gated_config_routes():
    assert "/api/discover/sources" in SOURCES_JS
    assert "/api/discover/config" in SOURCES_JS
    assert "/refresh" in SOURCES_JS  # per-source POST .../refresh


# ── 3. Runtime (Playwright, skip when the dev server is down) ──────────────

BASE_URL = os.environ.get("ENCLAVE_PLAYWRIGHT_BASE_URL", "http://localhost:8000")


def _server_up() -> bool:
    import requests

    try:
        return requests.get(f"{BASE_URL}/health", timeout=3).status_code == 200
    except Exception:
        return False


requires_server = pytest.mark.skipif(
    not _server_up(), reason=f"Enclave dev server not reachable at {BASE_URL}"
)


@requires_server
def test_lock_screen_when_signed_out_and_no_fetch(page):
    page.goto(f"{BASE_URL}/")
    page.evaluate("() => window.localStorage.removeItem('enclave.licenseKey')")
    page.goto(f"{BASE_URL}/")
    page.wait_for_selector("#tab-dashboard", state="attached", timeout=10_000)

    discover_calls: list = []
    page.on(
        "request",
        lambda r: discover_calls.append(r.url) if "/api/discover" in r.url else None,
    )
    page.evaluate("() => AdminMenu.select('admin-sources')")
    page.wait_for_selector("#tab-admin-sources .admin-lock", state="visible", timeout=5_000)
    # Strict gate: signed out ⇒ zero fetches behind the lock.
    assert discover_calls == []


@requires_server
def test_signed_in_panel_renders_providers_and_config(page):
    import requests

    key = requests.get(f"{BASE_URL}/api/setup/local-license", timeout=5).json().get("key", "")
    page.goto(f"{BASE_URL}/")
    page.evaluate(
        "(key) => window.localStorage.setItem('enclave.licenseKey', key)", key
    )
    page.goto(f"{BASE_URL}/")
    page.wait_for_selector("#tab-dashboard", state="attached", timeout=10_000)
    page.evaluate("() => AdminMenu.select('admin-sources')")
    # Provider rows render (skills-sh + mcp-registry ship registered).
    page.wait_for_selector(
        '#admin-sources-list [data-source="skills-sh"]', state="visible", timeout=10_000
    )
    # Config summary renders the persisted-file note (masked view only).
    cfg_text = page.inner_text("#admin-sources-config")
    assert "discovery_sources.json" in cfg_text
    # Edit modal opens via the data-action and never shows a raw token.
    page.click('[data-action="admin.sources.edit"]')
    page.wait_for_selector("#admin-sources-edit-modal", state="visible", timeout=5_000)
    assert page.input_value("#admin-sources-token") == ""
    page.click('[data-action="admin.sources.cancel"]')
