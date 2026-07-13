"""
Release-cycle UI/UX regression suite.

Pins the behaviour of the new SPA features landed in PRs #71-#81 so a
future change can't silently revert them. Every test here corresponds to
a specific user-visible affordance that was added or fixed in this
release cycle.

Run via:
    pytest tests/playwright/test_release_ui_features.py -v

Live container at $ENCLAVE_PLAYWRIGHT_BASE_URL (default
http://localhost:8000) must be reachable. signed_in_page fixture
auto-forces dark theme + injects the license key.
"""

from __future__ import annotations

# ── Catalog Models tab populates (#73) ───────────────────────────────────


def test_catalog_models_section_populates_inventory_grid(signed_in_page):
    """The Catalog page (legacy `data-tab="workflows"`) should display
    the inventory grid in its Models section. PR #73 fixed a regression
    where DOM relocation moved the grid out of #tab-inventory at boot
    but the Catalog section never received it. CatalogModelsShare now
    moves it on demand."""
    page = signed_in_page
    page.evaluate("() => window.switchTab && switchTab('workflows')")
    page.wait_for_timeout(3500)
    cards = page.evaluate("""() => {
            const mount = document.getElementById('catalog-models-mount');
            const grid = mount?.querySelector('#inv-grid');
            return grid ? grid.children.length : 0;
        }""")
    assert cards > 0, (
        "Catalog Models section is empty. Either CatalogModelsShare didn't "
        "fire on switchTab('workflows') or the inventory loader didn't populate "
        "#inv-grid. Check api/static/index.html: CatalogModelsShare + loadCatalog."
    )


def test_models_tab_still_populates_after_visiting_catalog(signed_in_page):
    """Earlier regression: opening the Catalog moved #inv-grid out of
    #tab-inventory permanently, leaving the Models tab blank. Now the
    grid moves BACK when the Models tab activates."""
    page = signed_in_page
    page.evaluate("() => switchTab('workflows')")  # Catalog first
    page.wait_for_timeout(2500)
    page.evaluate("() => switchTab('inventory')")  # then Models tab
    page.wait_for_timeout(2500)
    grid_in_tab = page.evaluate(
        "() => !!document.querySelector('#tab-inventory #inv-grid')"
    )
    assert grid_in_tab, (
        "#inv-grid did NOT move back to #tab-inventory after switching from "
        "Catalog. CatalogModelsShare.showInModelsTab() must fire on the "
        "'inventory' tab activation in switchTab()."
    )


# ── Mini-DAG silhouettes show vertical stacking for fan-in (#72, #80) ────


def test_mini_dag_silhouettes_stack_parallel_ranks(signed_in_page):
    """Workflow Index cards must render parallel ranks as a vertical
    stack of dots, NOT as a single pill or a flat row. This catches
    regressions back to the dagre-LR-collapse era."""
    page = signed_in_page
    page.evaluate("() => switchTab('workflow-index')")
    page.wait_for_timeout(4000)
    # Wait for the lazy hydration to render circles.
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('.wfi-card-dag-svg circle').length >= 20",
            timeout=10_000,
        )
    except Exception:
        pass
    # xsiam-normalization-pipeline has a fan-in pattern; its silhouette
    # should have multiple distinct y-positions (= parallel siblings
    # stacked vertically).
    info = page.evaluate("""() => {
            const slot = document.querySelector(
                '.wfi-card-dag[data-wf-id="xsiam-normalization-pipeline"]');
            if (!slot) return {err: 'workflow not in index'};
            const circles = slot.querySelectorAll('circle');
            const ys = Array.from(circles).map(c => Math.round(+c.getAttribute('cy')));
            return {
                circle_count: circles.length,
                distinct_y_positions: new Set(ys).size,
            };
        }""")
    assert "err" not in info, info["err"]
    assert info["circle_count"] >= 10, (
        f"xsiam-normalization-pipeline silhouette should have >=10 circles; "
        f"got {info['circle_count']}. Check rank-bucket renderer."
    )
    assert info["distinct_y_positions"] >= 3, (
        "Mini-DAG silhouette collapsed parallel ranks to a single y. "
        "Fan-in shapes should stack vertically inside each rank-slot — "
        "see _renderRankSilhouette in api/static/index.html."
    )


# ── Agent chat persistence (#74) ─────────────────────────────────────────


def test_agent_chat_persists_to_localstorage(signed_in_page):
    """Chat history + active agent must survive a page reload via
    localStorage['enclave.agentChat.v1']. PR #74 added this so tab
    navigation + reloads don't lose conversation state."""
    page = signed_in_page
    page.evaluate("() => switchTab('agents')")
    page.wait_for_timeout(2000)
    page.evaluate("() => window.openAgentChat && openAgentChat('xql-snippet-curator')")
    page.wait_for_timeout(1200)
    # Push fake history (avoid waiting on a real model call here).
    page.evaluate("""() => {
            _agentHistory.push({role:'user', content:'persistence test'});
            _agentHistory.push({role:'assistant', content:'reply'});
            _persistAgentChat();
        }""")
    has_ls = page.evaluate("() => !!localStorage.getItem('enclave.agentChat.v1')")
    assert has_ls, "Chat state did not persist to localStorage"

    # Now reload and verify the chat panel rebuilds.
    page.reload()
    page.wait_for_selector("#tab-dashboard", state="visible", timeout=10_000)
    page.evaluate("() => switchTab('agents')")
    page.wait_for_timeout(2500)
    info = page.evaluate("""() => ({
            panel_visible: getComputedStyle(
                document.getElementById('agent-chat-panel')
            ).display !== 'none',
            header_name: document.getElementById('agent-chat-name').textContent,
            bubble_count: document.querySelectorAll(
                '#agent-chat-messages > div'
            ).length,
        })""")
    assert info["panel_visible"], "Chat panel did not re-appear after reload"
    assert info["header_name"], "Chat header name was empty after restore"
    assert (
        info["bubble_count"] >= 2
    ), f"Expected >=2 restored bubbles; got {info['bubble_count']}"


# ── Composer description is a textarea, not single-line input (#75) ─────


def test_composer_description_is_autosizing_textarea(signed_in_page):
    """#df-wf-desc must be a TEXTAREA with an oninput handler that
    auto-resizes to fit content. Single-line <input> truncated multi-
    paragraph workflow descriptions."""
    page = signed_in_page
    info = page.evaluate("""() => {
            const el = document.getElementById('df-wf-desc');
            return el ? {tag: el.tagName, has_oninput: !!el.oninput} : null;
        }""")
    assert info is not None, "#df-wf-desc not present on the dashboard"
    assert (
        info["tag"] == "TEXTAREA"
    ), f"Expected textarea, got {info['tag']}. PR #75 regressed."
    assert info[
        "has_oninput"
    ], "Description textarea is missing its auto-resize oninput handler."


# ── Composer Clear button (#77) ──────────────────────────────────────────


def test_composer_clear_button_exists_and_clears(signed_in_page):
    """The explicit Clear button is separate from the New button and
    prompts before wiping. Both behaviours must hold."""
    page = signed_in_page
    page.evaluate("() => composerLoadById('email-draft')")
    page.wait_for_timeout(3000)
    # Chat-led redesign: the workflow-admin toolbar (New / Clear / Load / Import)
    # now lives inside the receding `.composer-mgmt-drawer` <details>, collapsed
    # by default. Open it so the Clear button is interactable — the same gesture
    # an operator makes to reach workflow admin.
    page.evaluate(
        "() => { const d = document.querySelector('.composer-mgmt-drawer'); if (d) d.open = true; }"
    )
    btn = page.locator('button[onclick="composerClearWithConfirm()"]')
    assert btn.count() == 1, "Clear button not present in the composer actions row"
    btn.click()
    # The dialog-unification rework retired native window.confirm() in favour of
    # the in-app Confirm modal (window.Confirm.ask → #enclave-confirm-ok). The
    # Clear only fires once that button is clicked, so accept it explicitly —
    # a `page.on("dialog", …)` handler never triggers for the custom modal.
    ok = page.locator("#enclave-confirm-ok")
    ok.wait_for(state="visible", timeout=5000)
    ok.click()
    page.wait_for_timeout(1200)
    # The composer now keeps always-present editable START/END anchors, so an
    # empty canvas legitimately holds those two __start__/__end__ nodes. The
    # agentic-composer revamp additionally auto-seeds an editable __seed__
    # node on every empty canvas (dfEnsureSeedNode via dfRefreshAnchors), so
    # it too is part of the legitimate empty state. Count only the real
    # (non-anchor, non-seed) steps when asserting the wipe.
    state = page.evaluate("""() => {
            const data = dfEditor?.drawflow?.drawflow?.Home?.data || {};
            const realNodes = Object.values(data).filter(
                n => n.name !== '__start__' && n.name !== '__end__'
                  && n.name !== '__seed__'
            ).length;
            return {
                id: document.getElementById('df-wf-id').value,
                name: document.getElementById('df-wf-name').value,
                desc: document.getElementById('df-wf-desc').value,
                realNodes,
            };
        }""")
    assert state == {
        "id": "",
        "name": "",
        "desc": "",
        "realNodes": 0,
    }, f"Clear button did not fully wipe composer state: {state}"


# ── Runs progress chip lives in the panel header, not the canvas (#80) ──


def test_runs_progress_chip_lives_in_header_not_canvas(signed_in_page):
    """The progress chip must NOT live inside .runs-tab-graph (where
    it overlapped DAG nodes). It must live inside #runs-tab-detail-head
    as an inline-flex header element."""
    page = signed_in_page
    page.evaluate("() => switchTab('runs')")
    page.wait_for_timeout(2500)
    info = page.evaluate("""() => {
            const chip = document.getElementById('runs-tab-progress-chip');
            const head = document.getElementById('runs-tab-detail-head');
            const graph = document.querySelector('.runs-tab-graph');
            return {
                in_head: !!head?.contains(chip),
                in_canvas: !!graph?.contains(chip),
                position: getComputedStyle(chip).position,
            };
        }""")
    assert info["in_head"], "Progress chip is not in #runs-tab-detail-head"
    assert not info["in_canvas"], (
        "Progress chip is inside .runs-tab-graph — that re-introduces the "
        "node-overlap class of bug PR #80 fixed."
    )
    assert info["position"] == "static", (
        f"Progress chip position is '{info['position']}' — should be static. "
        "If it's absolute, it's likely positioned on top of the canvas again."
    )


# ── Brand text-selection covers form fields (#76, #81) ───────────────────


def test_brand_selection_rule_covers_form_fields(signed_in_page):
    """The ::selection brand override must apply to <input> and
    <textarea> elements too — on macOS WebKit those use the OS accent
    by default. PR #81 split the cross-vendor variants into separate
    rules so Chrome doesn't drop the base rule when it can't parse
    ::-moz-selection."""
    page = signed_in_page
    rules = page.evaluate("""() => {
            const found = [];
            for (const ss of document.styleSheets) {
                let list;
                try { list = ss.cssRules; } catch(_) { continue; }
                for (const r of list || []) {
                    if (r.selectorText && /selection/i.test(r.selectorText)) {
                        found.push(r.selectorText);
                    }
                }
            }
            return found;
        }""")
    # Must include both the base ::selection AND the form-field variant.
    has_base = any(s == "::selection" for s in rules)
    has_form = any("input::selection" in s for s in rules)
    assert (
        has_base
    ), f"Base ::selection rule is missing from the cascade. Rules found: {rules}"
    assert has_form, f"Form-field selection override is missing. Rules found: {rules}"


# ── Click-to-add agent (#81) ─────────────────────────────────────────────


def test_workbench_agent_card_has_click_to_add(signed_in_page):
    """Drag-and-drop fails inconsistently across browser zoom / macOS
    trackpad. Every agent card must also accept a plain click to spawn
    the agent at canvas center."""
    page = signed_in_page
    # Activate the agents workbench (visible by default but the cards
    # render after agent fetch completes).
    page.evaluate("() => composerSwitchBench && composerSwitchBench('agents')")
    page.wait_for_timeout(2000)
    # Scope to the agents bench. The skills/plugins/mcp composer benches reuse
    # the `.agent-card` base class via _capCard and are drag-only by design, so
    # an unscoped selector would (correctly) find cards without the click
    # handler whenever any skill/plugin is installed.
    card_count = page.locator("#bench-agents-list .workbench-item.agent-card").count()
    assert card_count >= 1, "No agent cards in the workbench"
    # The card must carry the delegated click action that spawns the agent
    # (inline onclick became data-action="bench.add-agent" when the composer
    # surfaces moved to delegated events; accept either shape).
    has_handler = page.evaluate("""() => {
            const cards = document.querySelectorAll('#bench-agents-list .workbench-item.agent-card');
            return Array.from(cards).every(c =>
                (c.getAttribute('data-action') || '') === 'bench.add-agent'
                || (c.getAttribute('onclick') || '').includes('composerAddAgentAtCenter'));
        }""")
    assert has_handler, (
        "Agent cards lack the bench.add-agent click action (or legacy "
        "composerAddAgentAtCenter onclick). Drag-only fallback regressed."
    )
    # composerAddAgentAtCenter must be window-registered.
    assert page.evaluate(
        "() => typeof window.composerAddAgentAtCenter === 'function'"
    ), "composerAddAgentAtCenter is not exposed on window"


# ── Composer chat parses agent endpoint response shape (#81) ─────────────


def test_composer_chat_parses_agent_endpoint_response(
    signed_in_page, base_url, api_headers
):
    """The composer chat's sendMessage() routes to /api/agents/{id}/chat
    when an agent is selected. That endpoint returns {content, model,
    usage} — NOT OpenAI's {choices:[{message:{content}}]} shape. The
    parser must read both. Before PR #81 it only knew the OpenAI shape
    and rendered every agent reply as literal '(empty response)'."""
    page = signed_in_page
    page.evaluate("switchTab('chat')")  # chat dock (#prompt/#send-btn/#messages) moved to #tab-chat
    # Wire the chat dock to an agent.
    page.evaluate("() => { window._chatAgent = 'xql-snippet-curator'; }")
    page.evaluate(
        "() => { document.getElementById('prompt').value = 'Say hi in 5 words.'; }"
    )
    page.click("#send-btn")
    # Wait for an assistant bubble to materialize. The chat may take
    # 60-120s on CPU with a 4k-token grounded prompt — give it generous
    # headroom but accept partial response (length>0, no empty literal).
    try:
        page.wait_for_function(
            """() => {
                const msgs = document.querySelectorAll('#messages .msg.assistant');
                if (!msgs.length) return false;
                const last = msgs[msgs.length - 1];
                const t = (last.innerText || '').trim();
                return t.length > 0 && !t.includes('(empty response)');
            }""",
            timeout=180_000,
        )
    except Exception:
        # Fall back to assert: if the timeout hit, the test fails with the
        # literal '(empty response)' check below — clearer diagnostic.
        pass
    info = page.evaluate("""() => {
            const msgs = document.querySelectorAll('#messages .msg.assistant');
            const last = msgs.length ? msgs[msgs.length - 1] : null;
            return {
                count: msgs.length,
                preview: last ? last.innerText.trim().slice(0, 80) : null,
                empty_literal: last ? last.innerText.includes('(empty response)') : null,
            };
        }""")
    assert info["count"] >= 1, "No assistant bubble was rendered"
    assert not info["empty_literal"], (
        "Composer chat rendered '(empty response)' — agent endpoint response "
        "shape parser regressed (see PR #81)."
    )
