"""LB5-U1 — Plugins library panel on the LibraryShell + marketplaces digest.

Two layers, mirroring test_skills_shell.py:

1. Static assertions (bs4 / served-JS corpus): the plugins module ships the
   LB5-U1 plugins.* data-action grammar, the adapter keeps the AdminAuth hard
   gate ('admin' tier), selection moves from title-text matching to data-id,
   Installed rows carry the layer chip + version badge through the LB0 row
   contract, Discovered rows ride the persisted claude-marketplaces digest
   (license + diff badges, never a fetch on read), the LOCAL CAPABILITY
   BUNDLE kind banner + MCP cross-link state the plugin-vs-MCP split, the
   import flow surfaces the license BEFORE bridging into POST
   /api/skills/import, and the old inline-onclick AssetPeek button is
   replaced by a delegated action on newly rendered rows.

2. Runtime tests (Playwright against the dev server, skipped when
   unreachable): sub-tabs render behind the AdminAuth gate, data-id selection
   works, the kind banner + cross-link open the MCP surface, and the
   Discovered tab serves the persisted digest state.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "api" / "static"
PLUGINS_JS = (STATIC / "js" / "library" / "plugins.js").read_text(encoding="utf-8")
SHELL_JS = (STATIC / "js" / "library" / "shell.js").read_text(encoding="utf-8")


# ── 1. Static: plugins.* action grammar ─────────────────────────────────────


def test_plugins_registers_every_spec_action():
    for action in [
        "plugins.select", "plugins.sub-tab", "plugins.refresh-digest",
        "plugins.view-manifest", "plugins.import-skills",
        "plugins.seed-wizard", "plugins.goto-mcp", "plugins.peek",
        "plugins.run-tool",
    ]:
        assert f"'{action}'" in PLUGINS_JS, f"plugins.js missing delegated action {action}"


def test_plugins_adapter_keeps_the_adminauth_hard_gate():
    m = re.search(r"auth:\s*'(\w+)'", PLUGINS_JS)
    assert m and m.group(1) == "admin", "plugins adapter must keep the admin hard gate"
    assert "lockPanelId: 'admin-plugins'" in PLUGINS_JS


def test_selection_is_data_id_not_title_text():
    # the pre-shell panel matched rows by title text — retired.
    assert ".textContent.includes(" not in PLUGINS_JS, (
        "title-text row matching must be replaced by data-id selection"
    )
    assert "selectAction: 'plugins.select'" in PLUGINS_JS
    assert "LibraryShell.select('plugin'" in PLUGINS_JS


def test_legacy_plugin_card_selectors_stay_alive():
    # runtime suites pin .plugin-card[data-action="plugins.select"][data-id]
    # — the shell row builder keeps the legacy class via adapter.rowClass.
    assert "rowClass: 'plugin-card'" in PLUGINS_JS
    assert "a.rowClass" in SHELL_JS, "shell must honor adapter.rowClass (only-add)"


def test_no_inline_handlers_and_no_new_window_globals():
    assert "onclick=" not in PLUGINS_JS, (
        "inline AssetPeek onclick must be replaced by the delegated plugins.peek"
    )
    assert not re.search(r"\son[a-z]+\s*=\s*\"", PLUGINS_JS)
    assert not re.search(r"window\.[A-Za-z_$][\w$]*\s*=[^=]", PLUGINS_JS), (
        "new window global assigned in plugins.js"
    )
    assert "'plugins.peek'" in PLUGINS_JS and "AssetPeek.open('plugin'" in PLUGINS_JS


def test_installed_rows_carry_layer_chip_and_version_badge():
    m = re.search(r"list\(\)\s*{(.*?)\n    },", PLUGINS_JS, re.S)
    assert m, "adapter list() missing"
    body = m.group(1)
    assert "chips:" in body and "p.layer || p.origin" in body, "layer chip missing"
    assert "badges:" in body and "p.version" in body, "version badge missing"
    # version is metadata, not an action — no 'version' verb exists in v1
    assert "verb: 'version'" not in PLUGINS_JS


def test_discovered_rows_ride_the_persisted_digest():
    m = re.search(r"discovered\(\)\s*{(.*?)\n    },", PLUGINS_JS, re.S)
    assert m, "adapter discovered() missing"
    body = m.group(1)
    assert "_digest" in body
    assert "md.license" in body, "per-record license badge missing"
    for cls in ["lib-diff-new", "lib-diff-update"]:
        assert cls in body, f"diff badge class {cls} missing"


def test_reads_never_fetch_refresh_is_operator_triggered_only():
    # adapter.load reads /api/plugins + the digest-backed provider feed —
    # never a refresh route; network runs only behind the visible button.
    load_block = re.search(r"async load\(\)\s*{(.*?)\n    },", PLUGINS_JS, re.S)
    assert load_block and "/refresh" not in load_block.group(1), (
        "adapter.load must never hit a refresh route"
    )
    assert "/api/discover/claude-marketplaces'" in PLUGINS_JS
    m = re.search(r"async function refreshDigest\(\)(.*?)\n  }", PLUGINS_JS, re.S)
    assert m, "refreshDigest missing"
    assert "/api/discover/claude-marketplaces/refresh" in m.group(1)
    assert "retries: 0" in m.group(1)


def test_kind_banner_states_the_plugin_vs_mcp_split():
    assert "Local capability bundle" in PLUGINS_JS
    assert "External integration? → MCP" in PLUGINS_JS
    # cross-link, never merged: rides LibraryShell.open
    assert "LibraryShell.open('mcp')" in PLUGINS_JS


def test_import_skills_surfaces_license_and_bridges_native_importer():
    m = re.search(r"function importSkills\(id\)(.*?)\n  }\n", PLUGINS_JS, re.S)
    assert m, "importSkills missing"
    body = m.group(1)
    lic_pos = body.index("License:")
    submit_pos = body.index("/api/skills/import")
    assert lic_pos < submit_pos, "license must be surfaced BEFORE the import submits"
    assert "LibraryWizard.open" in body, "import rides the LibraryWizard"
    assert "retries: 0" in body
    assert "skill_md_url" in body


def test_seed_wizard_prefills_from_the_digest_record():
    m = re.search(r"function seedWizard\(id\)(.*?)\n  }\n", PLUGINS_JS, re.S)
    assert m, "seedWizard missing"
    body = m.group(1)
    assert "rec.description" in body and "data-wiz-key=\"description\"" in body
    assert "_forgeSeed" in body, "staged seed must survive for the LB5-U3 forge"


def test_lb1_tool_tester_heritage_intact():
    # the worked example (Plugins > websearch) keeps its DOM ids + pane mount
    for needle in ["tool-form-", "tool-tester-run-", "tool-result-",
                   "tool-history-", "plugin-test-pane",
                   "TestPane.mount('plugin-tool'"]:
        assert needle in PLUGINS_JS, f"LB1-U2 tester surface lost: {needle}"


def test_index_skeleton_and_digest_button(index_soup):
    # only-add: the tab skeleton + container ids stay; the visible digest
    # refresh button is delegated (data-action), not an inline handler.
    tab = index_soup.find(id="tab-admin-plugins")
    assert tab is not None
    for el_id in ["plugins-list", "plugin-detail", "plugin-detail-label"]:
        assert index_soup.find(id=el_id) is not None, f"#{el_id} regressed"
    btn = tab.find(attrs={"data-action": "plugins.refresh-digest"})
    assert btn is not None, "visible ⟳ Digest button missing from #tab-admin-plugins"
    # in-process execution warning banner retained
    assert "execute plugin code" in tab.get_text().lower()


# ── 2. Runtime (Playwright, skip when server down) ─────────────────────────

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


@pytest.fixture()
def shell_page(page):
    """Booted, signed-in SPA page (mirrors tests/playwright signed_in_page)."""
    import requests

    key = requests.get(f"{BASE_URL}/api/setup/local-license", timeout=5).json().get("key", "")
    page.goto(f"{BASE_URL}/")
    page.evaluate(
        """(key) => {
            window.localStorage.setItem('enclave.licenseKey', key);
            window.localStorage.setItem('enclave.theme', 'dark');
        }""",
        key,
    )
    page.goto(f"{BASE_URL}/")
    page.wait_for_selector("#tab-dashboard", state="visible", timeout=10_000)
    return page


def _open_plugins_tab(page):
    page.click('.tab-nav button[data-tab="admin-plugins"]')
    page.wait_for_selector("#tab-admin-plugins", state="visible", timeout=5_000)
    page.wait_for_selector("#plugins-list .lib-row", timeout=10_000)


@requires_server
def test_sub_tabs_render_behind_the_adminauth_gate(shell_page):
    page = shell_page
    _open_plugins_tab(page)
    assert page.locator("#tab-admin-plugins .admin-lock").count() == 0
    # Installed | Discovered sub-tabs on the sidebar
    assert page.locator('#plugins-list .lib-side-tab[data-side="installed"]').count() == 1
    assert page.locator('#plugins-list .lib-side-tab[data-side="discovered"]').count() == 1
    # rows keep the legacy .plugin-card class + the layer chip and dot
    first = page.locator("#plugins-list .lib-row.plugin-card").first
    assert first.get_attribute("data-action") == "plugins.select"
    assert first.get_attribute("data-id"), "rows must carry data-id"
    assert first.locator(".lib-chip").count() >= 1, "layer chip missing"


@requires_server
def test_data_id_selection_renders_detail_with_kind_banner(shell_page):
    page = shell_page
    _open_plugins_tab(page)
    first = page.locator("#plugins-list .lib-row.plugin-card").first
    pid = first.get_attribute("data-id")
    first.click()
    page.wait_for_selector("#plugin-detail .plugin-kind-banner", timeout=10_000)
    # selection is data-id: the detail head echoes the id, not a fuzzy title
    head = page.locator("#plugin-detail .lib-detail-head code").first.inner_text()
    assert head == pid
    banner = page.locator("#plugin-detail .plugin-kind-banner").inner_text()
    assert "local capability bundle" in banner.lower()


@requires_server
def test_cross_link_opens_the_mcp_surface(shell_page):
    page = shell_page
    _open_plugins_tab(page)
    page.locator("#plugins-list .lib-row.plugin-card").first.click()
    page.wait_for_selector('#plugin-detail [data-action="plugins.goto-mcp"]', timeout=10_000)
    page.click('#plugin-detail [data-action="plugins.goto-mcp"]')
    page.wait_for_selector("#tab-admin-mcp", state="visible", timeout=5_000)


@requires_server
def test_discovered_tab_serves_the_persisted_digest_offline(shell_page):
    page = shell_page
    # kill the refresh route — switching to Discovered must never fetch
    calls = []

    def _deny(route, request):
        calls.append(request.url)
        route.fulfill(status=500, body="refresh must not fire on tab activation")

    page.route("**/api/discover/claude-marketplaces/refresh", _deny)
    _open_plugins_tab(page)
    page.click('#plugins-list .lib-side-tab[data-side="discovered"]')
    # either persisted digest rows or the honest empty state — but NO fetch
    page.wait_for_selector(
        "#plugins-list .lib-rows .lib-row, #plugins-list .lib-rows .model-empty",
        timeout=5_000,
    )
    assert calls == [], "Discovered-tab activation must not trigger the refresh route"
