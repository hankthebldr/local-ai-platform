"""LB1-U2 — TestPane: layered test harness in the shell Test tab.

Two layers, mirroring test_library_shell.py:

1. Static assertions (served-JS corpus / index.html): the TestPane module
   ships the full test.* data-action grammar, registers exactly the six v1
   kinds (agent DEFERRED to follow-up #1), every run POST is retries:0, the
   schema form kit (renderToolForm/_collectParams/_renderHistory) moved out
   of plugins.js into ToolFormKit with the tester DOM ids preserved and the
   local esc() shadow deleted, mcp.js wires adapter.testPane and retires
   window.prompt() for marketplace env keys, _sendStepMessage sends
   temperature/max_tokens, model promote is disabled-with-reason, and the
   test-pane CSS grammar exists.

2. Runtime tests (Playwright against the dev server, skipped when
   unreachable): a FIXTURE TestPane impl exercises the layer machinery —
   L0–L3 sections, diff chips, per-field + per-layer reset, the normalized
   result strip with the override chip, last-5 history with snapshot
   restore — plus the real mcp-tool Test slot on the MCP shell tab and the
   plugin-tool mount in the plugin detail.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "api" / "static"
TEST_PANE_JS = (STATIC / "js" / "library" / "test-pane.js").read_text(encoding="utf-8")
PLUGINS_JS = (STATIC / "js" / "library" / "plugins.js").read_text(encoding="utf-8")
MCP_JS = (STATIC / "js" / "library" / "mcp.js").read_text(encoding="utf-8")
MAIN_JS = (STATIC / "js" / "main.js").read_text(encoding="utf-8")


# ── 1. Static: TestPane grammar ─────────────────────────────────────────────


def test_test_pane_registers_all_test_actions():
    for action in [
        "'test.run'",
        "'test.layer.toggle'",
        "'test.field.reset'",
        "'test.layer.reset'",
        "'test.skill.attach'",
        "'test.skill.detach'",
        "'test.tool.pick'",
        "'test.model.warm'",
        "'test.history.restore'",
        "'test.promote'",
    ]:
        assert action in TEST_PANE_JS, f"test-pane missing delegated action {action}"


def test_test_pane_registers_six_kinds_agent_deferred():
    kinds = re.findall(r"register\('([a-z-]+)',", TEST_PANE_JS)
    assert sorted(kinds) == sorted(
        ["prompt", "model", "skill", "plugin-tool", "mcp-tool", "step"]
    ), "TestPane must register exactly the six v1 kinds"
    assert "register('agent'" not in TEST_PANE_JS, (
        "agent adapter is DEFERRED to the Agents-migration follow-up (#1) — "
        "no adapter ships without a reachable surface"
    )


def test_test_pane_runs_are_always_retries_zero():
    # every Net.call the pane makes that mutates/executes uses retries: 0 —
    # no retries value other than 0 may appear in the module.
    values = set(re.findall(r"retries:\s*(\d+)", TEST_PANE_JS))
    assert values == {"0"}, f"non-zero retries in test-pane.js: {values}"


def test_test_pane_no_inline_handlers_or_window_globals():
    assert not re.search(r"\son[a-z]+\s*=\s*\"", TEST_PANE_JS), (
        "inline handler in test-pane.js"
    )
    assert not re.search(r"window\.[A-Za-z_$][\w$]*\s*=[^=]", TEST_PANE_JS), (
        "new window global assigned in test-pane.js"
    )


def test_test_pane_backends_per_kind():
    # each registered kind rides its spec'd backend route
    for route in [
        "/tools/${encodeURIComponent(tool.id)}/test",  # plugin-tool (LB1-U1)
        "/api/skills/test",                            # skill dry-run (LB1-U1)
        "/api/inventory/warm",                         # model warm (LB1-U1)
        "/api/workflows/test-step",                    # prompt + step
        "/v1/chat/completions",                        # model
        "/invoke",                                     # mcp-tool (stateless)
        "/render",                                     # prompt render
    ]:
        assert route in TEST_PANE_JS, f"backend route {route} not wired"
    # the mcp warm-session pool was CUT (YAGNI) — the pane invokes the
    # existing stateless route only, never a pooled/warm session endpoint
    assert "/api/mcp/servers/${encodeURIComponent(st.id)}/invoke" in TEST_PANE_JS
    assert "/session" not in TEST_PANE_JS


def test_model_promote_disabled_with_reason():
    assert "promoteDisabledReason" in TEST_PANE_JS
    assert "follow-up #10" in TEST_PANE_JS, (
        "model promote must carry the named-follow-up reason, not a dead button"
    )


def test_warm_noop_runners_get_reason_not_dead_button():
    assert "noop" in TEST_PANE_JS
    assert "vLLM pins weights at server start" in TEST_PANE_JS


def test_masked_secrets_never_round_trip():
    # masked L0 fields render disabled and the promote path strips them
    assert "masked — secrets never round-trip" in TEST_PANE_JS
    assert "delete ov.brave_api_key" in TEST_PANE_JS


def test_saved_samples_ride_localstorage():
    assert "enclave.testpane.sample." in TEST_PANE_JS
    assert "localStorage" in TEST_PANE_JS


# ── 2. Static: plugins.js extraction (kit) ──────────────────────────────────


def test_plugins_local_esc_shadow_deleted():
    assert "function esc(" not in PLUGINS_JS, (
        "the local esc() shadow must be deleted — core/dom.js esc is the one"
    )
    assert "import { esc" in PLUGINS_JS


def test_plugins_imports_kit_from_test_pane():
    assert "from './test-pane.js'" in PLUGINS_JS
    assert "ToolFormKit" in PLUGINS_JS


def test_plugin_tester_dom_ids_preserved():
    # the pre-extract tester selectors live on (pinned by older suites)
    for needle in ["tool-form-", "tool-tester-run-", "tool-result-", "tool-history-"]:
        assert needle in PLUGINS_JS, f"plugin tester id {needle} lost"
    # the kit keeps the default 'tool-param-' prefix the accordion relies on
    assert "'tool-param-'" in TEST_PANE_JS


def test_plugins_public_surface_unchanged():
    for name in ["renderToolForm", "_collectParams", "runTool", "renderToolAccordion"]:
        assert name in PLUGINS_JS, f"plugins.js public member {name} dropped"


def test_plugins_detail_mounts_plugin_tool_pane():
    assert "plugin-test-pane" in PLUGINS_JS
    assert "TestPane.mount('plugin-tool'" in PLUGINS_JS


# ── 3. Static: mcp.js wiring ────────────────────────────────────────────────


def test_mcp_wires_test_pane_slot():
    assert "testPane(id)" in MCP_JS
    assert "TestPane.mount('mcp-tool'" in MCP_JS


def test_mcp_marketplace_env_keys_ride_wizard_not_prompt():
    assert "LibraryWizard.open" in MCP_JS
    # window.prompt() is retired from the install flow
    assert not re.search(r"\bprompt\(\s*`", MCP_JS), (
        "marketplace env-key window.prompt() must be replaced by the "
        "LibraryWizard Secrets step"
    )
    # endpoint stays byte-identical
    assert "/api/mcp/discover/${encodeURIComponent(entry.id)}/install" in MCP_JS


def test_mcp_legacy_actions_still_alive():
    for action in ["mcp.select", "mcp.test", "mcp.discover", "mcp.toggle",
                   "mcp.edit", "mcp.remove", "mcp.mkt-install", "mcp.mkt-close"]:
        assert f"'{action}'" in MCP_JS, f"legacy action {action} dropped"


# ── 4. Static: main.js ──────────────────────────────────────────────────────


def test_main_imports_test_pane():
    assert "from './library/test-pane.js'" in MAIN_JS


def test_send_step_message_sends_sampling_params():
    fn = MAIN_JS[MAIN_JS.index("async function _sendStepMessage"):]
    fn = fn[: fn.index("\nfunction ")]
    assert "temperature" in fn and "max_tokens" in fn, (
        "_sendStepMessage must send temperature/max_tokens to test-step"
    )


# ── 5. Static: CSS grammar ──────────────────────────────────────────────────


def test_test_pane_css_grammar_present(index_html_text):
    assert 'id="test-pane-styles"' in index_html_text
    for sel in [".test-layer", ".test-diff-chip", ".test-field-reset",
                ".test-result-strip", ".test-history-row", ".test-warm-badge",
                ".test-layer-lock", ".test-attach-chip"]:
        assert sel in index_html_text, f"CSS selector {sel} missing"


# ── 6. Runtime (Playwright, skip when server down) ──────────────────────────

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
    """Booted, signed-in SPA page (mirrors tests/ui/test_library_shell.py)."""
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


FIXTURE_PANE_JS = """
async () => {
  const { TestPane } = await import('/static/js/library/test-pane.js');
  window.__tptest = { runs: [] };
  const host = document.createElement('div');
  host.id = 'tptest-host';
  host.style.cssText =
    'position:fixed;inset:0;z-index:150;background:var(--bg,#111);overflow:auto;padding:20px';
  document.body.appendChild(host);
  TestPane.register('tptest', {
    layerAuth: {},
    async prepare(st) {
      st.baseline.l0 = { greeting: 'hello', count: 3 };
      st.fields.l0 = [
        { key: 'greeting', label: 'greeting', type: 'text' },
        { key: 'count', label: 'count', type: 'number' },
      ];
      st.baseline.l2 = { model: '', temperature: 0.7, max_tokens: 256 };
      st.fields.l2 = [
        { key: 'temperature', label: 'temperature', type: 'number', step: 0.1 },
        { key: 'max_tokens', label: 'max_tokens', type: 'number', step: 1 },
      ];
      st.attached = ['plug.skill-a'];
    },
    layers(st) {
      return {
        l0: { label: 'Component config', fields: st.fields.l0 },
        l1: { label: 'Attached skills', attach: true,
              items: st.attached.map(r => ({ ref: r, label: r })) },
        l2: { label: 'Model params', fields: st.fields.l2 },
        l3: { label: 'Input sample', message: true },
      };
    },
    async run(st, input) {
      window.__tptest.runs.push({
        overrides: JSON.parse(JSON.stringify(st.overrides)),
        attached: st.attached.slice(),
        input,
      });
      return { status: 'ok', latency_ms: 42, content: 'fixture-reply', raw: { echo: true } };
    },
    promote(st) {
      return {
        label: 'fixture write-back',
        diff: Object.entries(st.overrides.l0).map(([key, value]) => ({ key, value })),
        apply: async () => ({ ok: true, message: 'fixture promoted' }),
      };
    },
  });
  await TestPane.mount('tptest', 'unit-1', host, {});
}
"""


@requires_server
def test_fixture_pane_layers_diff_chips_and_reset(shell_page):
    page = shell_page
    page.evaluate(FIXTURE_PANE_JS)
    pane = page.locator("#tptest-host .test-pane")
    assert pane.count() == 1
    # all four layers render with their tags
    tags = page.locator("#tptest-host .test-layer-tag")
    assert [tags.nth(i).inner_text() for i in range(tags.count())] == [
        "L0", "L1", "L2", "L3"]
    # no diff chips before any edit
    assert page.locator("#tptest-host .test-diff-chip:visible").count() == 0
    # edit an L0 field → '1 override' chip + per-field reset appears
    inp = page.locator('#tptest-host [data-field-wrap="l0:greeting"] input')
    inp.fill("hi there")
    chip = page.locator('#tptest-host .test-diff-chip[data-layer="l0"]')
    assert chip.is_visible() and chip.inner_text() == "1 override"
    reset = page.locator(
        '#tptest-host [data-field-wrap="l0:greeting"] .test-field-reset')
    assert reset.is_visible()
    # second field → '2 overrides'
    page.locator('#tptest-host [data-field-wrap="l0:count"] input').fill("9")
    assert chip.inner_text() == "2 overrides"
    # per-field reset restores baseline value + decrements the chip
    reset.click()
    assert page.locator(
        '#tptest-host [data-field-wrap="l0:greeting"] input').input_value() == "hello"
    assert page.locator(
        '#tptest-host .test-diff-chip[data-layer="l0"]').inner_text() == "1 override"
    # layer reset clears the rest
    page.click('#tptest-host .test-layer-reset[data-layer="l0"]')
    assert page.locator("#tptest-host .test-diff-chip:visible").count() == 0


@requires_server
def test_fixture_pane_run_result_strip_history_and_restore(shell_page):
    page = shell_page
    page.evaluate(FIXTURE_PANE_JS)
    # apply one override so the run carries an override chip
    page.locator('#tptest-host [data-field-wrap="l0:count"] input').fill("7")
    page.locator("#tptest-host .test-msg-input").fill("sample msg")
    page.click('#tptest-host [data-action="test.run"]')
    page.wait_for_selector("#tptest-host .test-result-strip", timeout=5_000)
    strip = page.locator("#tptest-host .test-result-strip").inner_text()
    assert "OK" in strip and "42 ms" in strip and "1 override" in strip
    assert "fixture-reply" in page.locator(
        "#tptest-host .test-result-body").inner_text()
    # the run saw the overrides + the L1 attachment + the message
    run = page.evaluate("window.__tptest.runs[0]")
    assert run["overrides"]["l0"] == {"count": 7}
    assert run["attached"] == ["plug.skill-a"]
    assert run["input"]["message"] == "sample msg"
    # history row rendered with restore
    assert page.locator("#tptest-host .test-history-row").count() == 1
    # change state, then restore the snapshot
    page.click('#tptest-host .test-layer-reset[data-layer="l0"]')
    assert page.locator("#tptest-host .test-diff-chip:visible").count() == 0
    page.click('#tptest-host [data-action="test.history.restore"]')
    chip = page.locator('#tptest-host .test-diff-chip[data-layer="l0"]')
    assert chip.is_visible() and chip.inner_text() == "1 override"
    assert page.locator(
        '#tptest-host [data-field-wrap="l0:count"] input').input_value() == "7"


@requires_server
def test_fixture_pane_skill_attach_detach(shell_page):
    page = shell_page
    page.evaluate(FIXTURE_PANE_JS)
    page.locator("#tptest-host .test-attach-input").fill("plug.skill-b")
    page.click('#tptest-host [data-action="test.skill.attach"]')
    chips = page.locator("#tptest-host .test-attach-chip")
    assert chips.count() == 2
    page.click(
        '#tptest-host .test-chip-x[data-ref="plug.skill-a"]')
    assert page.locator("#tptest-host .test-attach-chip").count() == 1
    assert "plug.skill-b" in page.locator(
        "#tptest-host .test-attach-chips").inner_text()


@requires_server
def test_mcp_test_tab_renders_via_shell_slot(shell_page):
    """Register a scratch MCP server, open its Test tab through the shell
    subnav, assert the mcp-tool pane renders (tools not cached → honest
    empty state), then clean up."""
    import requests

    sid = "tptest-scratch"
    requests.delete(f"{BASE_URL}/api/mcp/servers/{sid}", timeout=5)
    r = requests.post(f"{BASE_URL}/api/mcp/servers", json={
        "id": sid, "name": "TestPane scratch", "transport": "stdio",
        "command": "true", "args": [],
    }, timeout=5)
    assert r.status_code in (200, 201), r.text
    page = shell_page
    try:
        page.click('.tab-nav button[data-tab="admin-mcp"]')
        page.wait_for_selector(f'#mcp-list .lib-row[data-id="{sid}"]', timeout=10_000)
        page.click(f'#mcp-list .lib-row[data-id="{sid}"]')
        test_pill = page.locator(
            '#mcp-detail .lib-subnav-pill[data-section="test"]')
        assert test_pill.count() == 1, "Test subnav slot missing on MCP detail"
        test_pill.click()
        page.wait_for_selector("#mcp-detail .test-pane", timeout=5_000)
        # no tools cached → the L3 layer states it honestly
        assert "Discover tools" in page.locator(
            "#mcp-detail .test-pane").inner_text()
        # L0 server-config layer renders the timeout field
        assert page.locator(
            '#mcp-detail [data-field-wrap="l0:timeout_seconds"]').count() == 1
    finally:
        requests.delete(f"{BASE_URL}/api/mcp/servers/{sid}", timeout=5)


@requires_server
def test_plugin_detail_mounts_tool_pane_with_schema_form(shell_page):
    """Library > Plugins > web-search: the Test section renders the layered
    pane — masked L0 settings, tool picker, schema-driven L3 form."""
    page = shell_page
    page.click('button[data-tab="admin-plugins"]')
    page.wait_for_selector(
        '.plugin-card[data-action="plugins.select"]', timeout=10_000)
    page.click('.plugin-card[data-id="web-search"]')
    # the auto-selected first plugin also mounts a pane — wait for the
    # web-search pane specifically (its tool option is the discriminator)
    page.wait_for_selector(
        "#plugin-test-pane .test-tool-pick option[value='web_search']",
        state="attached", timeout=10_000)
    # L0 saved-settings layer renders with the masked key read-only
    masked = page.locator(
        '#plugin-test-pane [data-field-wrap="l0:brave_api_key"] input')
    assert masked.count() == 1 and masked.is_disabled()
    # L3 schema form renders the declared params
    assert page.locator(
        f"#plugin-test-pane input[id$='-param-query']").count() == 1
    # editing max_results (L0) shows the override chip the worked example names
    page.locator(
        '#plugin-test-pane [data-field-wrap="l0:max_results"] input').fill("3")
    chip = page.locator('#plugin-test-pane .test-diff-chip[data-layer="l0"]')
    assert chip.is_visible() and chip.inner_text() == "1 override"
