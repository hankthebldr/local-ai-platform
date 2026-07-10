"""LB0-U1 — LibraryShell + LibraryWizard core; Prompts/MCP adapter migration.

Two layers:

1. Static assertions (bs4 / served-JS corpus, like the rest of tests/ui):
   the shell/wizard modules ship with the full data-action grammar, the v1
   verb enum has NO 'version' verb, the lib-shell CSS grammar exists,
   `.lib-row` is added ALONGSIDE the retained `.mcp-row`, every legacy
   prompts.*/mcp.* action id and container id survives the migration
   (endpoint-and-action-identical contract), and no new inline on*= handlers
   or window globals were introduced by the new modules.

2. Runtime adapter-contract test (Playwright against the dev server, skipped
   when unreachable): a FIXTURE ADAPTER exercises EVERY optional row field
   (icon, chips, badges, dot, status, provenance, blocks, renderRowExtras),
   async detail sections (invoked on first subnav activation only), the Test
   slot via testPane, the filter/group/sidebar-tab grammar, the actions row
   (disabled-with-reason, Confirm-gated delete), LibraryShell.open()
   cross-kind navigation, auth-tier enforcement (admin renderLock when signed
   out; prompts NOT over-gated, mcp gate unchanged), and the LibraryWizard
   4-step flow (empty steps skipped, secrets never echoed).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "api" / "static"
SHELL_JS = (STATIC / "js" / "library" / "shell.js").read_text(encoding="utf-8")
WIZARD_JS = (STATIC / "js" / "library" / "wizard.js").read_text(encoding="utf-8")
PROMPTS_JS = (STATIC / "js" / "library" / "prompts.js").read_text(encoding="utf-8")
MCP_JS = (STATIC / "js" / "library" / "mcp.js").read_text(encoding="utf-8")
MAIN_JS = (STATIC / "js" / "main.js").read_text(encoding="utf-8")


# ── 1. Static: shell grammar ships ─────────────────────────────────────────


def test_shell_registers_all_lib_actions():
    for action in [
        "'lib.sidebar-tab'",
        "'lib.filter'",
        "'lib.group-toggle'",
        "'lib.select'",
        "'lib.subnav'",
        "'lib.action'",
        "'lib.refresh'",
    ]:
        assert action in SHELL_JS, f"shell missing delegated action {action}"
    for action in [
        "'lib.wizard.next'",
        "'lib.wizard.back'",
        "'lib.wizard.cancel'",
        "'lib.wizard.submit'",
    ]:
        assert action in WIZARD_JS, f"wizard missing delegated action {action}"


def test_shell_verb_enum_has_no_version_verb():
    m = re.search(r"const VERBS = \[([^\]]*)\]", SHELL_JS)
    assert m, "VERBS enum missing from shell.js"
    verbs = re.findall(r"'([a-z]+)'", m.group(1))
    assert verbs == ["install", "test", "edit", "promote", "delete"]
    assert "version" not in verbs, "the 'version' verb is a named follow-up, not v1"


def test_shell_subnav_order_is_the_uniform_six():
    m = re.search(r"const SECTION_ORDER = \[([^\]]*)\]", SHELL_JS)
    assert m
    sections = re.findall(r"'([a-z]+)'", m.group(1))
    assert sections == ["overview", "config", "files", "examples", "test", "relations"]


def test_shell_rows_add_lib_row_alongside_retained_mcp_row():
    # Classes are ADDED, never renamed: one row element carries both.
    assert "mcp-row lib-row" in SHELL_JS


def test_shell_supports_every_optional_row_field():
    for needle in ["item.icon", "item.chips", "item.badges", "item.dot",
                   "item.status", "item.provenance", "item.blocks",
                   "renderRowExtras"]:
        assert needle in SHELL_JS, f"row contract field {needle} not rendered"


def test_shell_auth_tiers_enforced_in_fetch_paths():
    assert "AdminAuth.isSignedIn()" in SHELL_JS
    assert "AdminAuth.renderLock" in SHELL_JS
    assert "AdminAuth.fetch" in SHELL_JS
    assert "a.auth === 'none'" in SHELL_JS


def test_wizard_secrets_discipline():
    # password inputs, never prefilled, never echoed into the summary.
    assert 'type="password"' in WIZARD_JS
    assert 'autocomplete="new-password"' in WIZARD_JS
    assert "••••••••" in WIZARD_JS  # masked summary rendering
    # submit transport is always retries:0
    assert "retries: 0" in WIZARD_JS


def test_new_modules_have_no_inline_handlers():
    for name, src in [("shell.js", SHELL_JS), ("wizard.js", WIZARD_JS),
                      ("prompts.js", PROMPTS_JS), ("mcp.js", MCP_JS)]:
        assert not re.search(r"\son[a-z]+\s*=\s*\"", src), f"inline handler in {name}"
    # and no new window globals assigned by the new modules (reads like
    # `window.switchTab ===` are fine; assignment `= <value>` is not)
    for name, src in [("shell.js", SHELL_JS), ("wizard.js", WIZARD_JS)]:
        assert not re.search(r"window\.[A-Za-z_$][\w$]*\s*=[^=]", src), (
            f"new window global assigned in {name}"
        )


def test_main_js_imports_shell_and_wizard():
    assert "from './library/shell.js'" in MAIN_JS
    assert "from './library/wizard.js'" in MAIN_JS


# ── 2. Static: endpoint-and-action-identical migration ─────────────────────


def test_prompts_legacy_action_ids_survive():
    for action in ["prompts.select", "prompts.edit", "prompts.cancel",
                   "prompts.save", "prompts.remove", "prompts.render",
                   "prompts.new", "prompts.refresh", "prompts.create-close",
                   "prompts.create-submit"]:
        assert f"'{action}'" in PROMPTS_JS, f"legacy action {action} dropped"


def test_prompts_endpoints_survive():
    for ep in ["/api/prompts", "/render"]:
        assert ep in PROMPTS_JS


def test_prompts_adapter_not_over_gated():
    m = re.search(r"auth:\s*'(\w+)'", PROMPTS_JS)
    assert m and m.group(1) == "optional", (
        "prompts adapter must stay 'optional' (merged headers), never 'admin'"
    )


def test_mcp_legacy_action_ids_survive():
    for action in ["mcp.select", "mcp.test", "mcp.discover", "mcp.toggle",
                   "mcp.edit", "mcp.remove", "mcp.mkt-install", "mcp.mkt-close"]:
        assert f"'{action}'" in MCP_JS, f"legacy action {action} dropped"


def test_mcp_endpoints_survive():
    for ep in ["/api/mcp/servers", "/api/mcp/discover"]:
        assert ep in MCP_JS


def test_mcp_gate_unchanged():
    m = re.search(r"auth:\s*'(\w+)'", MCP_JS)
    assert m and m.group(1) == "optional", (
        "mcp adapter tier changed — it must keep merged-headers 'optional' "
        "(the tab never rendered the admin-lock; e2e pins that)"
    )


def test_migrated_container_ids_intact(index_soup):
    for el_id in ["prompts-list", "prompts-detail", "prompts-detail-label",
                  "prompts-count", "prompts-create-modal",
                  "mcp-list", "mcp-detail", "mcp-detail-label", "mcp-count",
                  "mcp-edit-modal"]:
        assert index_soup.find(id=el_id) is not None, f"#{el_id} lost in migration"


def test_untouched_tabs_and_relocators_still_present(index_soup):
    # LB0-U1 deliberately does not touch Skills/Models/Plugins or the
    # DOM relocators — pin the only-add contract.
    for el_id in ["tab-admin-plugins", "tab-admin-skills", "tab-admin-mcp",
                  "tab-inventory", "skills-tab-discover-mount",
                  "inv-stats", "inv-grid", "discover-section",
                  "plugins-list", "plugin-detail", "skills-list", "skill-detail"]:
        assert index_soup.find(id=el_id) is not None, f"#{el_id} regressed"


def test_lib_shell_css_grammar_present(index_html_text):
    assert 'id="lib-shell-styles"' in index_html_text
    for sel in [".lib-side-tab", ".lib-filter", ".lib-group-label",
                ".lib-prov-chip.prov-oob", ".lib-prov-chip.prov-user",
                ".lib-block-dot", ".lib-subnav-pill", ".lib-actions-row",
                ".lib-wiz-step"]:
        assert sel in index_html_text, f"CSS selector {sel} missing"


# ── 3. Runtime adapter-contract tests (Playwright, skip when server down) ──

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


FIXTURE_ADAPTER_JS = """
async () => {
  const { LibraryShell } = await import('/static/js/library/shell.js');
  window.__libtest = { asyncRenders: 0, testRenders: 0, actions: [], loads: 0 };
  const host = document.createElement('div');
  host.id = 'libtest-host';
  // overlay above page chrome (so footer/toasts can't occlude clicks) but
  // BELOW .admin-modal (z-index 200) so the shared Confirm modal stays clickable
  host.style.cssText =
    'position:fixed;inset:0;z-index:150;background:var(--bg,#111);overflow:auto;padding:20px';
  document.body.appendChild(host);
  LibraryShell.register({
    kind: 'libtest',
    tabId: 'prompts',
    auth: 'none',
    title: 'Fixture',
    async load() { window.__libtest.loads++; },
    list: () => [
      { id: 'alpha', title: 'Alpha', meta: 'meta-a', group: 'Group A',
        status: 'ready', provenance: 'oob', blocks: ['model', 'tools'],
        icon: 'mcp', chips: [{ label: 'few-shot', cls: '' }],
        badges: [{ label: 'v1.2.0', cls: '' }],
        dot: { cls: 'fit-good', title: 'fits' }, tags: ['alphatag'] },
      { id: 'beta', title: 'Beta', meta: 'meta-b', group: 'Group B',
        provenance: 'user' },
    ],
    discovered: () => [{ id: 'gamma', title: 'Gamma', meta: 'remote', group: 'Remote' }],
    renderRowExtras: (item) => {
      if (item.id !== 'alpha') return null;
      const s = document.createElement('span');
      s.className = 'libtest-extra';
      s.textContent = 'EXTRA';
      return s;
    },
    detail: (id) => ({ sections: {
      overview: `<div class="libtest-ov">ov-${id}</div>`,
      files: async (mountEl) => {
        window.__libtest.asyncRenders++;
        mountEl.innerHTML = `<div class="libtest-files">files-${id}</div>`;
      },
      relations: '<div class="libtest-rel">rel</div>',
    } }),
    testPane: (id) => (mountEl) => {
      window.__libtest.testRenders++;
      mountEl.innerHTML = `<div class="libtest-test">test-${id}</div>`;
    },
    actions: (id) => [
      { label: 'Install', verb: 'install' },
      { label: 'Promote', verb: 'promote', enabled: false, reason: 'already user-layer' },
      { label: 'Delete', verb: 'delete' },
    ],
    onAction: (verb, id) => window.__libtest.actions.push(verb + ':' + id),
  });
  await LibraryShell.mount('libtest', 'libtest-host');
}
"""


@requires_server
def test_fixture_adapter_renders_every_optional_row_field(shell_page):
    page = shell_page
    page.evaluate(FIXTURE_ADAPTER_JS)
    rows = page.locator("#lib-libtest-list .lib-row")
    assert rows.count() == 2
    # retained .mcp-row alongside .lib-row
    assert page.locator("#lib-libtest-list .mcp-row.lib-row").count() == 2
    alpha = page.locator('#lib-libtest-list .lib-row[data-id="alpha"]')
    assert alpha.locator(".admin-card-icon").count() == 1, "icon field not rendered"
    assert alpha.locator(".lib-dot.fit-good").count() == 1, "dot field not rendered"
    assert "few-shot" in alpha.locator(".lib-chip").inner_text()
    assert "v1.2.0" in alpha.locator(".lib-badge").inner_text()
    assert "ready" in alpha.locator(".lib-status").inner_text()
    assert alpha.locator(".lib-prov-chip.prov-oob").count() == 1
    assert alpha.locator(".lib-blocks .lib-block-dot.on").count() == 2
    assert "EXTRA" in alpha.locator(".libtest-extra").inner_text()
    beta = page.locator('#lib-libtest-list .lib-row[data-id="beta"]')
    assert beta.locator(".lib-prov-chip.prov-user").count() == 1
    # group headers render (CSS uppercases them), collapsible
    assert "GROUP A" in page.locator("#lib-libtest-list").inner_text().upper()
    page.click('#lib-libtest-list .lib-group-label[data-group="Group A"]')
    assert not alpha.is_visible(), "group toggle did not collapse"
    page.click('#lib-libtest-list .lib-group-label[data-group="Group A"]')
    assert alpha.is_visible()


@requires_server
def test_fixture_adapter_filter_and_sidebar_tabs(shell_page):
    page = shell_page
    page.evaluate(FIXTURE_ADAPTER_JS)
    # client-side filter matches title+tags substring
    page.fill("#lib-libtest-list .lib-filter", "alphatag")
    assert page.locator("#lib-libtest-list .lib-row").count() == 1
    page.fill("#lib-libtest-list .lib-filter", "")
    assert page.locator("#lib-libtest-list .lib-row").count() == 2
    # Discovered sidebar tab renders the discovered() rows — no fetch involved
    page.click('#lib-libtest-list .lib-side-tab[data-side="discovered"]')
    assert page.locator('#lib-libtest-list .lib-row[data-id="gamma"]').count() == 1
    page.click('#lib-libtest-list .lib-side-tab[data-side="installed"]')
    assert page.locator("#lib-libtest-list .lib-row").count() == 2


@requires_server
def test_fixture_adapter_detail_subnav_async_sections_and_test_slot(shell_page):
    page = shell_page
    page.evaluate(FIXTURE_ADAPTER_JS)
    page.click('#lib-libtest-list .lib-row[data-id="alpha"]')
    assert "// ALPHA" in page.locator("#lib-libtest-detail-label").inner_text().upper()
    pills = page.locator("#lib-libtest-detail .lib-subnav-pill")
    labels = [pills.nth(i).inner_text().strip().upper() for i in range(pills.count())]
    # absent sections (Config, Examples) hidden; Test present via testPane slot
    assert labels == ["OVERVIEW", "FILES", "TEST", "RELATIONS"]
    assert page.locator("#lib-libtest-detail .libtest-ov").inner_text() == "ov-alpha"
    # async section NOT invoked before first activation
    assert page.evaluate("window.__libtest.asyncRenders") == 0
    page.click('#lib-libtest-detail .lib-subnav-pill[data-section="files"]')
    page.wait_for_selector("#lib-libtest-detail .libtest-files", timeout=3_000)
    assert page.evaluate("window.__libtest.asyncRenders") == 1
    # switching away and back does NOT re-invoke (first-activation cache)
    page.click('#lib-libtest-detail .lib-subnav-pill[data-section="overview"]')
    page.click('#lib-libtest-detail .lib-subnav-pill[data-section="files"]')
    assert page.evaluate("window.__libtest.asyncRenders") == 1
    # Test slot renders through adapter.testPane
    page.click('#lib-libtest-detail .lib-subnav-pill[data-section="test"]')
    page.wait_for_selector("#lib-libtest-detail .libtest-test", timeout=3_000)
    assert page.evaluate("window.__libtest.testRenders") == 1


@requires_server
def test_fixture_adapter_actions_row_and_confirm_gated_delete(shell_page):
    page = shell_page
    page.evaluate(FIXTURE_ADAPTER_JS)
    page.click('#lib-libtest-list .lib-row[data-id="alpha"]')
    row = page.locator("#lib-libtest-detail .lib-actions-row .action-btn")
    assert row.count() == 3
    promote = page.locator(
        '#lib-libtest-detail .lib-actions-row [data-verb="promote"]')
    assert promote.is_disabled(), "enabled:false must disable the button"
    assert promote.get_attribute("title") == "already user-layer"
    page.click('#lib-libtest-detail .lib-actions-row [data-verb="install"]')
    assert page.evaluate("window.__libtest.actions") == ["install:alpha"]
    # delete is Confirm-gated through the shared modal
    page.click('#lib-libtest-detail .lib-actions-row [data-verb="delete"]')
    page.wait_for_selector("#enclave-confirm-modal:not([hidden])", timeout=3_000)
    page.click("#enclave-confirm-cancel")
    assert page.evaluate("window.__libtest.actions") == ["install:alpha"]
    page.click('#lib-libtest-detail .lib-actions-row [data-verb="delete"]')
    page.wait_for_selector("#enclave-confirm-modal:not([hidden])", timeout=3_000)
    page.click("#enclave-confirm-ok")
    page.wait_for_function(
        "() => window.__libtest.actions.length === 2", timeout=3_000)
    assert page.evaluate("window.__libtest.actions") == [
        "install:alpha", "delete:alpha"]


@requires_server
def test_open_navigates_cross_kind_and_prompts_has_no_test_tab(shell_page):
    page = shell_page
    ok = page.evaluate(
        """async () => {
            const { LibraryShell } = await import('/static/js/library/shell.js');
            return LibraryShell.open('prompt', 'role/python_developer');
        }"""
    )
    assert ok
    # open() rode switchTab to the adapter's tab and applied the selection
    assert page.locator("#tab-prompts").is_visible()
    page.wait_for_selector(
        '#prompts-list .lib-row[data-key="role/python_developer"].selected',
        timeout=10_000,
    )
    # migrated prompts detail keeps its pre-shell selectors alive
    page.wait_for_selector(
        '#prompts-detail [data-action="prompts.render"]', timeout=5_000)
    # prompts adapter has no testPane → Test tab hidden
    pills = page.locator("#tab-prompts .lib-subnav-pill")
    labels = [pills.nth(i).inner_text().strip().upper() for i in range(pills.count())]
    assert "TEST" not in labels


@requires_server
def test_auth_tiers_prompts_optional_mcp_optional_admin_locks(shell_page):
    page = shell_page
    tiers = page.evaluate(
        """async () => {
            const { LibraryShell } = await import('/static/js/library/shell.js');
            return {
              prompt: LibraryShell.adapter('prompt').auth,
              mcp: LibraryShell.adapter('mcp').auth,
            };
        }"""
    )
    assert tiers == {"prompt": "optional", "mcp": "optional"}
    # admin tier: signed OUT → renderLock fires and adapter.load never runs
    result = page.evaluate(
        """async () => {
            const { LibraryShell } = await import('/static/js/library/shell.js');
            const saved = localStorage.getItem('enclave.licenseKey');
            localStorage.removeItem('enclave.licenseKey');
            const host = document.createElement('div');
            host.id = 'tab-libadmin-fixture';
            document.body.appendChild(host);
            let loaded = 0;
            LibraryShell.register({
              kind: 'libadmin', tabId: 'libadmin-fixture',
              lockPanelId: 'libadmin-fixture', auth: 'admin',
              async load() { loaded++; },
              list: () => [], detail: () => ({sections:{}}), actions: () => [],
            });
            await LibraryShell.reload('libadmin');
            const locked = !!host.querySelector('.admin-lock');
            localStorage.setItem('enclave.licenseKey', saved);
            return { locked, loaded };
        }"""
    )
    assert result == {"locked": True, "loaded": 0}


WIZARD_FLOW_JS = """
async () => {
  const { LibraryWizard } = await import('/static/js/library/wizard.js');
  window.__wiztest = { submitted: null };
  LibraryWizard.open({
    title: 'Fixture install',
    steps: {
      source: (el) => { el.innerHTML =
        '<input type="text" data-wiz-key="repo" id="wiz-repo">'; },
      secrets: { fields: [{ key: 'token', label: 'API token', hint: 'kept local' }] },
    },
    onSubmit: async (state) => {
      window.__wiztest.submitted = {
        repo: state.values.repo, token: state.secrets.token };
      return { ok: true, message: 'installed' };
    },
    submitLabel: 'Install',
  });
}
"""


@requires_server
def test_wizard_skips_empty_steps_and_never_echoes_secrets(shell_page):
    page = shell_page
    page.evaluate(WIZARD_FLOW_JS)
    page.wait_for_selector("#lib-wizard-modal:not([hidden])", timeout=3_000)
    steps = page.locator("#lib-wizard-modal .lib-wiz-step")
    labels = [
        steps.nth(i).inner_text().replace("\n", "").strip().upper()
        for i in range(steps.count())
    ]
    # configure omitted → skipped; confirm always present
    assert labels == ["1SOURCE", "2SECRETS", "3CONFIRM"]
    page.fill("#wiz-repo", "owner/repo")
    page.click('[data-action="lib.wizard.next"]')
    secret_inp = page.locator('#lib-wizard-modal input[type="password"]')
    assert secret_inp.count() == 1
    assert secret_inp.input_value() == ""  # never prefilled
    assert secret_inp.get_attribute("autocomplete") == "new-password"
    secret_inp.fill("s3kr3t-value")
    page.click('[data-action="lib.wizard.next"]')
    # confirm summary masks the secret and never echoes it
    body = page.locator("#lib-wizard-body").inner_text()
    assert "••••••••" in body
    assert "s3kr3t-value" not in page.locator("#lib-wizard-modal").inner_html()
    page.click('[data-action="lib.wizard.submit"]')
    page.wait_for_function("() => !!window.__wiztest.submitted", timeout=3_000)
    assert page.evaluate("window.__wiztest.submitted") == {
        "repo": "owner/repo", "token": "s3kr3t-value"}
    # result strip renders; secret still absent from the modal
    assert "installed" in page.locator("#lib-wizard-result").inner_text()
    assert "s3kr3t-value" not in page.locator("#lib-wizard-modal").inner_html()
    page.click('[data-action="lib.wizard.cancel"]')
    assert page.locator("#lib-wizard-modal").is_hidden()


@requires_server
def test_migrated_mcp_panel_renders_without_lock(shell_page):
    page = shell_page
    page.click('.tab-nav button[data-tab="admin-mcp"]')
    page.wait_for_selector("#tab-admin-mcp", state="visible", timeout=5_000)
    page.wait_for_function(
        """() => {
            const el = document.getElementById('mcp-list');
            return el && (el.querySelector('.lib-rows') || el.innerText.length > 0);
        }""",
        timeout=10_000,
    )
    assert page.locator("#tab-admin-mcp .admin-lock").count() == 0
