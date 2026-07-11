"""MS-5 — the Agents tab migrated onto the LibraryShell grammar.

Two layers, mirroring test_skills_shell.py / test_plugins_shell.py:

1. Static assertions (bs4 / served-JS corpus): #tab-agents is rebuilt on the
   shared two-pane plugins-layout (uniform `.lib-row` list + subnav detail),
   the AgentsPanel adapter ships the full agents.* data-action grammar as the
   honest 'none' tier (/api/agents is an unguarded read), rowClass 'agent-card'
   is carried alongside `.lib-row`, the bespoke card grid + inline chat panel +
   `--cyan` + inline on*= handlers are gone from the tab, the chat lifecycle is
   re-pointed (openAgentChat focuses the detail chat slot, loadAgentsTab
   delegates to the shell), and the migration is grammar-only (no TestPane /
   provenance / re-sync; no backend change).

2. Runtime (Playwright against the dev server, skipped when unreachable):
   uniform `.lib-row` rows render, the detail carries Overview/Chat subnav,
   the chat still sends, delete is Confirm-gated, and create/edit round-trips
   through the agent modal.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "api" / "static"
AGENTS_JS = (STATIC / "js" / "library" / "agents.js").read_text(encoding="utf-8")
SHELL_JS = (STATIC / "js" / "library" / "shell.js").read_text(encoding="utf-8")
MAIN_JS = (STATIC / "js" / "main.js").read_text(encoding="utf-8")


# ── 1. Static: agents.* action grammar + adapter ───────────────────────────


def test_agents_registers_every_spec_action():
    for action in [
        "agents.new", "agents.refresh", "agents.chat-open", "agents.edit-open",
        "agents.peek", "agents.remove", "agents.starter-open",
        "agents.chat-send", "agents.chat-close", "agents.chat-input",
    ]:
        assert f"'{action}'" in AGENTS_JS, f"agents.js missing delegated action {action}"


def test_agents_adapter_registers_on_the_shell():
    # kind 'agent' on the shared LibraryShell, adopting the existing panel DOM.
    assert "from './shell.js'" in AGENTS_JS, "agents.js must reuse the LibraryShell"
    assert "LibraryShell.register(" in AGENTS_JS
    for needle in [
        "kind: 'agent'", "tabId: 'agents'", "listElId: 'agents-list'",
        "detailElId: 'agents-detail'", "labelElId: 'agents-detail-label'",
        "countBadgeId: 'agents-count'", "rowClass: 'agent-card'",
    ]:
        assert needle in AGENTS_JS, f"adapter field missing: {needle}"
    # honest tier — /api/agents is an unguarded read.
    m = re.search(r"auth:\s*'(\w+)'", AGENTS_JS)
    assert m and m.group(1) == "none", "agents adapter must be the honest 'none' tier"


def test_agents_list_uses_the_row_contract():
    # Uniform LB0 row contract (icon/chips/tags/blocks) — not a bespoke card.
    m = re.search(r"list\(\)\s*\{(.*?)\n    \},", AGENTS_JS, re.S)
    assert m, "adapter.list() missing"
    body = m.group(1)
    for field in ["id:", "title:", "meta:", "icon:", "chips", "tags:", "blocks"]:
        assert field in body, f"row-contract field {field} missing from list()"
    assert "/api/agents" in AGENTS_JS


def test_agents_detail_is_overview_plus_chat_subnav():
    # Grammar-only detail: Overview + a Chat slot. NO TestPane / provenance /
    # re-sync / runtime execution (frozen engine — Library f/u #2).
    assert "sectionOrder: ['overview', 'chat']" in AGENTS_JS
    assert "overview:" in AGENTS_JS and "chat:" in AGENTS_JS
    assert "testPane" not in AGENTS_JS, "TestPane stays OUT of the grammar-only migration"
    # the chat slot reuses the exact ids the main.js chat lifecycle drives
    for cid in ["agent-chat-panel", "agent-chat-name", "agent-chat-messages",
                "agent-chat-input"]:
        assert cid in AGENTS_JS, f"chat slot id {cid} missing from the detail renderer"


def test_agents_delete_is_confirm_gated():
    # Delete routes through deleteAgent(), which Confirm-gates (single prompt —
    # not double-confirmed via the shell's lib.action gate).
    assert "'agents.remove'" in AGENTS_JS and "deleteAgent" in AGENTS_JS
    m = re.search(r"async function deleteAgent\(agentId\)(.*?)\n\}", MAIN_JS, re.S)
    assert m, "deleteAgent missing from main.js"
    assert "Confirm.ask" in m.group(1), "deleteAgent must Confirm-gate the delete"


def test_agents_module_no_inline_handlers_or_new_window_globals():
    assert not re.search(r"\son[a-z]+\s*=\s*\"", AGENTS_JS), "inline on*= handler in agents.js"
    assert not re.search(r"window\.[A-Za-z_$][\w$]*\s*=[^=]", AGENTS_JS), (
        "new window global assigned in agents.js"
    )


def test_main_repoints_chat_lifecycle_onto_the_shell_slot():
    # loadAgentsTab delegates to the adapter; openAgentChat focuses the detail
    # chat slot before populating; the starter path latches through the async
    # populate; the module is imported.
    assert "import { AgentGen, AgentsPanel } from './library/agents.js'" in MAIN_JS
    m = re.search(r"async function loadAgentsTab\(\)(.*?)\n\}", MAIN_JS, re.S)
    assert m and "AgentsPanel.load()" in m.group(1), (
        "loadAgentsTab must delegate to the AgentsPanel shell adapter"
    )
    o = re.search(r"async function openAgentChat\(agentId\)(.*?)\n\}", MAIN_JS, re.S)
    assert o and "AgentsPanel.focusChat(agentId)" in o.group(1), (
        "openAgentChat must focus the detail chat slot before populating"
    )
    assert "_pendingStarter" in MAIN_JS, "the starter latch must carry chips through populate"


def test_agents_tab_markup_is_the_shell_skeleton(index_soup):
    tab = index_soup.find(id="tab-agents")
    assert tab is not None, "#tab-agents regressed"
    # two-pane shared layout + adopted panel ids
    assert tab.find(class_="plugins-layout") is not None, "shell two-pane layout missing"
    for el_id in ["agents-list", "agents-detail", "agents-detail-label"]:
        assert index_soup.find(id=el_id) is not None, f"#{el_id} missing from the shell skeleton"
    # toolbar verbs are delegated
    for action in ["agents.new", "agents.refresh"]:
        assert tab.find(attrs={"data-action": action}) is not None, (
            f"toolbar data-action={action} missing"
        )
    # count badge still lives on the tab button (shell updates it)
    assert index_soup.find(id="agents-count") is not None


def test_agents_tab_dropped_inline_handlers_and_cyan(index_soup):
    tab = index_soup.find(id="tab-agents")
    html = str(tab)
    assert not re.search(r"\son[a-z]+=", html), (
        "the Agents tab must carry NO inline on*= handlers (pre-authorized markup swap)"
    )
    assert "var(--cyan)" not in html and "--cyan" not in html, (
        "the legacy --cyan identity must be gone from the migrated Agents tab"
    )
    # the old bespoke grid + static chat panel are gone
    assert tab.find(class_="agent-tile") is None, "legacy agent-tile grid must be gone"
    assert tab.find(id="agent-chat-panel") is None, (
        "the static chat panel must move into the detail chat slot"
    )


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


def _open_agents_tab(page):
    page.click('.tab-nav button[data-tab="agents"]')
    page.wait_for_selector("#tab-agents", state="visible", timeout=5_000)
    page.wait_for_selector("#agents-list .lib-row", timeout=10_000)


@requires_server
def test_uniform_lib_rows_render(shell_page):
    page = shell_page
    _open_agents_tab(page)
    rows = page.locator("#agents-list .lib-row")
    assert rows.count() > 0, "no agent rows rendered on the shell"
    first = rows.first
    # uniform grammar: default lib.select action + the migrating rowClass
    assert first.get_attribute("data-action") == "lib.select"
    assert "agent-card" in (first.get_attribute("class") or "")
    # the shell filter is present (uniform sidebar chrome)
    assert page.locator("#agents-list .lib-filter").count() == 1


@requires_server
def test_detail_subnav_and_overview(shell_page):
    page = shell_page
    _open_agents_tab(page)
    page.click("#agents-list .lib-row >> nth=0")
    page.wait_for_selector("#agents-detail .lib-subnav-pill", timeout=5_000)
    pills = page.locator("#agents-detail .lib-subnav-pill")
    labels = [pills.nth(i).inner_text().strip().upper() for i in range(pills.count())]
    assert labels == ["OVERVIEW", "CHAT"], f"subnav drifted: {labels}"
    # overview renders the kv grid (system prompt block present)
    assert page.locator("#agents-detail pre.prompts-body").count() >= 1


@requires_server
def test_chat_slot_sends(shell_page):
    page = shell_page
    _open_agents_tab(page)
    page.click("#agents-list .lib-row >> nth=0")
    page.wait_for_selector("#agents-detail .lib-subnav-pill", timeout=5_000)
    # Chat action opens the detail chat slot
    page.click('#agents-detail [data-action="agents.chat-open"]')
    page.wait_for_selector("#agent-chat-panel #agent-chat-input", timeout=5_000)
    # Wait for openAgentChat's async populate to finish (header filled + greeting
    # painted) BEFORE sending — otherwise the greeting write races the send and
    # clobbers the freshly-appended bubbles.
    page.wait_for_function(
        "() => { const n = document.getElementById('agent-chat-name');"
        " return n && n.textContent.trim().length > 0; }",
        timeout=8_000,
    )
    page.fill("#agent-chat-input", "ping from the shell chat slot")
    page.click('[data-action="agents.chat-send"]')
    # the user bubble is inserted synchronously (before the model round-trip)
    page.wait_for_function(
        "() => document.querySelectorAll('#agent-chat-messages > div').length >= 2",
        timeout=8_000,
    )


@requires_server
def test_delete_is_confirm_gated(shell_page):
    page = shell_page
    calls = []
    page.route("**/api/agents/*", lambda route, req: (
        calls.append(req.method) or route.continue_()
    ))
    _open_agents_tab(page)
    page.click("#agents-list .lib-row >> nth=0")
    page.wait_for_selector('#agents-detail [data-action="agents.remove"]', timeout=5_000)
    page.click('#agents-detail [data-action="agents.remove"]')
    page.wait_for_selector("#enclave-confirm-modal:not([hidden])", timeout=3_000)
    page.click("#enclave-confirm-cancel")
    page.wait_for_timeout(300)
    assert "DELETE" not in calls, "cancelled Confirm must not fire the DELETE route"


@requires_server
def test_create_round_trips_through_the_modal(shell_page):
    page = shell_page
    _open_agents_tab(page)
    before = page.locator("#agents-list .lib-row").count()
    aid = f"ms5-shell-{uuid.uuid4().hex[:8]}"
    page.click('#tab-agents [data-action="agents.new"]')
    page.wait_for_selector("#am-id", timeout=5_000)
    page.fill("#am-id", aid)
    page.fill("#am-name", "MS5 Shell Probe")
    page.fill("#am-prompt", "You are a throwaway test agent.")
    page.click('[data-action="agents.modal-save"]')
    try:
        # the new agent round-trips back into the shell list
        page.wait_for_function(
            "(n) => document.querySelectorAll('#agents-list .lib-row').length > n",
            arg=before, timeout=8_000,
        )
        assert page.locator(f'#agents-list .lib-row[data-id="{aid}"]').count() == 1
    finally:
        # cleanup — delete the probe agent so the dev tree stays clean
        page.evaluate(
            "(id) => fetch('/api/agents/' + id, {method:'DELETE'})", aid
        )
