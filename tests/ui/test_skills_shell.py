"""LB3-U2 — Skills library panel rebuilt on the LibraryShell.

Two layers, mirroring test_library_shell.py / test_test_pane.py:

1. Static assertions (bs4 / served-JS corpus): the skills module ships the
   full skills.* data-action grammar, the adapter is the honest 'admin' tier
   (backend fully master-key gated — F12), the local esc() shadow is deleted,
   calm rows ride the LB0 row contract (icon/chips/badges), promote is
   Confirm-gated onto the LB3-U1 route, discover.js retires window.prompt()
   in favor of LibraryWizard against byte-identical endpoints, the shared
   skills-data.js loader feeds BOTH the shell and the Composer bench with the
   drag payload unchanged, and the #skills-tab-discover-mount relocation +
   legacy container ids/filters stay alive (only-add).

2. Runtime tests (Playwright against the dev server, skipped when
   unreachable): calm cards render from the row contract, the Test tab shows
   trigger dry-run output, promote Confirm-gates and calls the route, the
   wizard replaces the prompt() flows, the Catalog-page discover relocation
   still binds, and the Composer bench drag-attach payload is identical.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "api" / "static"
SKILLS_JS = (STATIC / "js" / "library" / "skills.js").read_text(encoding="utf-8")
SKILLS_DATA_JS = (STATIC / "js" / "library" / "skills-data.js").read_text(encoding="utf-8")
DISCOVER_JS = (STATIC / "js" / "library" / "discover.js").read_text(encoding="utf-8")
MAIN_JS = (STATIC / "js" / "main.js").read_text(encoding="utf-8")


# ── 1. Static: skills.* action grammar ─────────────────────────────────────


def test_skills_registers_every_spec_action():
    for action in [
        "skills.side-tab", "skills.group", "skills.select", "skills.dtab",
        "skills.file", "skills.test", "skills.promote",
        "skills.refresh-discovery", "skills.install", "skills.import",
        "skills.browse-repo", "skills.create", "skills.edit", "skills.save",
        "skills.cancel", "skills.uninstall", "skills.seed-chat",
    ]:
        assert f"'{action}'" in SKILLS_JS, f"skills.js missing delegated action {action}"


def test_skills_adapter_is_honest_admin_tier():
    # F12 resolution: every backend read this panel needs is master-key
    # gated server-side, so the adapter must be 'admin' — an 'optional'
    # tier claiming degradation would be indistinguishable from a wall.
    m = re.search(r"auth:\s*'(\w+)'", SKILLS_JS)
    assert m and m.group(1) == "admin", "skills adapter must be the honest 'admin' tier"
    assert "lockPanelId: 'admin-skills'" in SKILLS_JS


def test_skills_local_esc_shadow_deleted():
    assert "from '../core/dom.js'" in SKILLS_JS
    assert not re.search(r"\bfunction esc\(", SKILLS_JS), (
        "the local esc() shadow must be deleted — core/dom.js esc is the one escaper"
    )


def test_skills_modules_no_inline_handlers_or_window_globals():
    # discover.js keeps ONE pre-existing inline onclick (ExtDiscover install
    # card, pre-shell) — the rebuilt/new modules must stay clean.
    for name, src in [("skills.js", SKILLS_JS), ("skills-data.js", SKILLS_DATA_JS)]:
        assert not re.search(r"\son[a-z]+\s*=\s*\"", src), f"inline handler in {name}"
    for name, src in [("skills.js", SKILLS_JS), ("skills-data.js", SKILLS_DATA_JS),
                      ("discover.js", DISCOVER_JS)]:
        assert not re.search(r"window\.[A-Za-z_$][\w$]*\s*=[^=]", src), (
            f"new window global assigned in {name}"
        )


def test_skills_calm_rows_use_the_row_contract():
    # Persona icon, ≤3 trigger chips + `+n`, one source badge — expressed
    # through the LB0 row contract fields, not bespoke card markup.
    for needle in ["icon:", "chips:", "badges:", "_triggerChips"]:
        assert needle in SKILLS_JS, f"row-contract field {needle} missing from list()"
    # ≤3 chips with the +n overflow chip
    assert "slice(0, 3)" in SKILLS_JS
    assert "+${kws.length - 3}" in SKILLS_JS


def test_skills_detail_tabs_and_endpoints():
    # Overview/Files/Examples/Relations sections + LB3-U1 endpoints.
    for needle in ["overview:", "files:", "examples:", "relations:",
                   "/api/skills/tree/", "/api/skills/file?plugin_id=",
                   "/api/skills/relations/"]:
        assert needle in SKILLS_JS, f"detail wiring missing: {needle}"
    # rendered SKILL.md, not a raw <pre> dump
    assert "renderMarkdown" in SKILLS_JS


def test_skills_test_pane_mounts_lb1_skill_adapter_with_ctx():
    assert "TestPane.mount('skill'" in SKILLS_JS
    assert "pluginId:" in SKILLS_JS and "skillId:" in SKILLS_JS


def test_skills_promote_confirm_gated_onto_lb3u1_route():
    m = re.search(r"async function promote\(id\)(.*?)\n  }", SKILLS_JS, re.S)
    assert m, "promote() missing from skills.js"
    body = m.group(1)
    assert "Confirm.ask" in body, "promote must be Confirm-gated"
    assert "/promote" in body and "retries: 0" in body
    assert "method: 'POST'" in body


def test_skills_refresh_discovery_is_operator_triggered_only():
    # The visible Refresh re-fires the marketplace provider refresh
    # (retries:0) then re-reads /api/skills/discover. Tab-activation reads
    # (adapter.load) must NOT touch the refresh route.
    m = re.search(r"async function refreshDiscovery\(\)(.*?)\n  }", SKILLS_JS, re.S)
    assert m
    assert "/api/discover/skills-sh/refresh" in m.group(1)
    assert "retries: 0" in m.group(1)
    load_block = re.search(r"async load\(\)(.*?)\n    },", SKILLS_JS, re.S)
    assert load_block and "/refresh" not in load_block.group(1), (
        "adapter.load must never hit a refresh route — reads serve the persisted/cached catalog"
    )


def test_discover_prompt_flows_replaced_by_wizard():
    # window.prompt() retired — install / import-URL / browse-repo all ride
    # the LibraryWizard against byte-identical endpoints.
    assert not re.search(r"(?<![.\w'\"])prompt\(", DISCOVER_JS), (
        "window.prompt()/prompt() call survives in discover.js"
    )
    assert "from './wizard.js'" in DISCOVER_JS
    for ep in ["/api/skills/discover/", "/api/skills/import", "/api/skills/github"]:
        assert ep in DISCOVER_JS, f"endpoint {ep} lost in the wizard migration"


def test_shared_skills_data_loader_feeds_both_surfaces():
    # ONE normalizer: the shell imports it, the Composer bench imports it.
    assert "export function flattenSkills" in SKILLS_DATA_JS
    assert "from './skills-data.js'" in SKILLS_JS
    assert "from './library/skills-data.js'" in MAIN_JS
    m = re.search(r"function renderSkillsWorkbench\(plugins\)(.*?)\n}", MAIN_JS, re.S)
    assert m, "renderSkillsWorkbench missing"
    assert "flattenSkills(plugins)" in m.group(1)
    assert "SKILL_DRAG_MIME" in m.group(1)


def test_composer_drag_payload_unchanged():
    # The drag-attach contract: mime application/df-skill, value
    # <plugin>::<skill>. Pinned here so neither side drifts.
    assert "'application/df-skill'" in SKILLS_DATA_JS
    assert "`${pluginId}::${skillId}`" in SKILLS_DATA_JS
    # the canvas drop handler still reads the same MIME
    assert "application/df-skill" in MAIN_JS


def test_index_containers_toolbar_and_relocators_intact(index_soup):
    # only-add: every pre-shell container id + the DOM-relocator mount and
    # the legacy filter selects stay alive.
    for el_id in ["tab-admin-skills", "skills-list", "skill-detail",
                  "skill-detail-label", "skills-count",
                  "skills-tab-discover-mount", "skills-filter-plugin",
                  "skills-filter-role", "skills-discover-panel",
                  "catalog-skills-mount"]:
        assert index_soup.find(id=el_id) is not None, f"#{el_id} regressed"
    tab = index_soup.find(id="tab-admin-skills")
    for action in ["skills.create", "skills.browse-repo", "skills.import",
                   "skills.refresh-discovery"]:
        assert tab.find(attrs={"data-action": action}) is not None, (
            f"toolbar button data-action={action} missing from #tab-admin-skills"
        )


def test_relocation_wiring_survives_in_main_js():
    # switchTab('admin-skills') still relocates the shared discovery panel
    # and loads it; Catalog entry pulls it back.
    assert "SkillsDiscoverShare.showInSkillsTab()" in MAIN_JS
    assert "SkillsDiscoverShare.showInCatalog()" in MAIN_JS


def test_skills_css_grammar_present(index_html_text):
    for sel in [".skills-md-body", ".skills-tree", ".skills-tree-file",
                ".skills-file-view", ".lib-chip.more", ".lib-badge.skills-src"]:
        assert sel in index_html_text, f"CSS selector {sel} missing"


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


def _open_skills_tab(page):
    page.click('.tab-nav button[data-tab="admin-skills"]')
    page.wait_for_selector("#tab-admin-skills", state="visible", timeout=5_000)
    page.wait_for_selector("#skills-list .lib-row", timeout=10_000)


@requires_server
def test_calm_cards_render_from_the_row_contract(shell_page):
    page = shell_page
    _open_skills_tab(page)
    # no admin lock (signed in), shell chrome + grouped calm rows
    assert page.locator("#tab-admin-skills .admin-lock").count() == 0
    assert page.locator('#skills-list .lib-side-tab[data-side="discovered"]').count() == 1
    rows = page.locator("#skills-list .lib-row")
    assert rows.count() > 0
    first = rows.first
    assert first.get_attribute("data-action") == "skills.select"
    # calm card: persona icon + single-line meta; per-plugin group headers
    assert first.locator(".admin-card-icon").count() == 1, "persona icon missing"
    assert page.locator("#skills-list .lib-group-label").count() > 0, (
        "per-plugin collapsible groups missing"
    )
    # source badge on the row (system|user layer)
    assert first.locator(".lib-badge.skills-src").count() == 1


@requires_server
def test_detail_tabs_and_trigger_dry_run_in_test_tab(shell_page):
    page = shell_page
    _open_skills_tab(page)
    page.click("#skills-list .lib-row >> nth=0")
    page.wait_for_selector("#skill-detail .lib-subnav-pill", timeout=5_000)
    pills = page.locator("#skill-detail .lib-subnav-pill")
    labels = [pills.nth(i).inner_text().strip().upper() for i in range(pills.count())]
    assert labels == ["OVERVIEW", "FILES", "EXAMPLES", "TEST", "RELATIONS"]
    # Overview renders the kv grid + rendered SKILL.md
    page.wait_for_selector("#skill-detail .skills-md-body", timeout=5_000)
    # Files tab drills into the LB3-U1 tree
    page.click('#skill-detail .lib-subnav-pill[data-section="files"]')
    page.wait_for_selector("#skill-detail .skills-tree .skills-tree-file", timeout=5_000)
    # Test tab mounts the LB1 skill TestPane — explicit ctx dry-run always
    # returns this skill's match record with the exact injected text.
    page.click('#skill-detail .lib-subnav-pill[data-section="test"]')
    page.wait_for_selector("#skill-detail .test-pane", timeout=5_000)
    page.fill("#skill-detail .test-msg-input", "dry-run message")
    page.click('#skill-detail [data-action="test.run"]')
    page.wait_for_selector("#skill-detail .test-skill-match", timeout=10_000)
    assert page.locator("#skill-detail .test-skill-match .test-result-body").count() >= 1, (
        "dry-run must show the exact injected text"
    )


@requires_server
def test_promote_confirm_gates_and_calls_the_route(shell_page):
    page = shell_page
    calls = []

    def _stub(route, request):
        calls.append(request.url)
        route.fulfill(
            status=201,
            content_type="application/json",
            body='{"promoted": true, "skill_id": "x", "target_plugin_id": "user-skills"}',
        )

    page.route("**/api/skills/*/promote", _stub)
    _open_skills_tab(page)
    page.click("#skills-list .lib-row >> nth=0")
    promote = page.locator('#skill-detail [data-action="skills.promote"]')
    if promote.get_attribute("disabled") is not None:
        pytest.skip("first skill is already user-layer — promote correctly disabled")
    # Cancel path: Confirm gate, no request
    promote.click()
    page.wait_for_selector("#enclave-confirm-modal:not([hidden])", timeout=3_000)
    page.click("#enclave-confirm-cancel")
    assert calls == [], "cancelled Confirm must not fire the promote route"
    # OK path: route called exactly once
    promote.click()
    page.wait_for_selector("#enclave-confirm-modal:not([hidden])", timeout=3_000)
    page.click("#enclave-confirm-ok")
    page.wait_for_function("() => true", timeout=500)
    page.wait_for_timeout(500)
    assert len(calls) == 1 and calls[0].endswith("/promote")


@requires_server
def test_wizard_replaces_prompt_flows(shell_page):
    page = shell_page
    _open_skills_tab(page)
    # any prompt() call would fail loudly
    page.evaluate(
        """() => {
            window.prompt = () => { throw new Error('window.prompt is retired'); };
            return true;
        }"""
    )
    # Import URL → LibraryWizard with a source step, not a prompt()
    page.click('#tab-admin-skills [data-action="skills.import"]')
    page.wait_for_selector("#lib-wizard-modal:not([hidden])", timeout=3_000)
    assert page.locator('#lib-wizard-modal [data-wiz-key="url"]').count() == 1
    page.click('[data-action="lib.wizard.cancel"]')
    # Browse repo → wizard for the repo choice
    page.click('#tab-admin-skills [data-action="skills.browse-repo"]')
    page.wait_for_selector("#lib-wizard-modal:not([hidden])", timeout=3_000)
    assert page.locator('#lib-wizard-modal [data-wiz-key="repo"]').count() == 1
    page.click('[data-action="lib.wizard.cancel"]')
    assert page.locator("#lib-wizard-modal").is_hidden()


@requires_server
def test_catalog_page_discover_relocation_still_binds(shell_page):
    page = shell_page
    _open_skills_tab(page)
    in_skills = page.evaluate(
        """() => {
            const p = document.getElementById('skills-discover-panel');
            return !!(p && p.closest('#skills-tab-discover-mount'));
        }"""
    )
    assert in_skills, "discover panel must relocate into the Skills tab mount"
    page.evaluate("window.switchTab('workflows')")
    in_catalog = page.evaluate(
        """() => {
            const p = document.getElementById('skills-discover-panel');
            return !!(p && p.closest('#catalog-skills-mount'));
        }"""
    )
    assert in_catalog, "discover panel must relocate back to the Catalog mount"


@requires_server
def test_composer_bench_drag_attach_payload_identical(shell_page):
    page = shell_page
    # the bench pane may be hidden behind another workbench tab — the payload
    # contract holds on the attached nodes regardless of visibility.
    page.wait_for_selector(
        '#bench-skills-list [data-drag-mime="application/df-skill"]',
        state="attached", timeout=15_000,
    )
    value = page.locator(
        '#bench-skills-list [data-drag-mime="application/df-skill"]'
    ).first.get_attribute("data-drag-value")
    assert re.match(r"^[\w.-]+::[\w.-]+$", value or ""), (
        f"bench drag value drifted from <plugin>::<skill>: {value!r}"
    )
