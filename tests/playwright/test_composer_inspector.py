"""BU5 — sidebar <-> bottom polymorphic inspector.

Hovering (mouseover) an agent bench card paints a read-only inspection of
the resolved agent (model + tools + context) into #df-config-panel — never
the popup — and stamps #ws-step-meta with data-inspect-kind while
data-step-id stays '(none)'. Clicking a canvas node afterwards restores the
Step Config form: node selection always wins over lingering inspector
content. Pure canvas/bench UI — no model runs.
"""

from __future__ import annotations

SEED_SEL = "#drawflow-canvas .df-seed-node"
AGENT_CARD = "#bench-agents-list .agent-card"


def _wait_composer(page):
    """Canvas booted (seed pill spawned), Agents bench switched to and
    populated with cards (the Task palette is the default-active bench)."""
    page.wait_for_selector(SEED_SEL, state="visible", timeout=10_000)
    page.click('.workbench-tab[data-bench="agents"]')
    page.wait_for_selector(AGENT_CARD, state="visible", timeout=10_000)


def _hover_agent_card(page):
    """Dispatch a bubbling mouseover on the first agent card (deterministic
    headless equivalent of hover) and wait out the value-change debounce."""
    page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        }""",
        AGENT_CARD,
    )
    page.wait_for_function(
        "() => document.getElementById('ws-step-meta')"
        ".hasAttribute('data-inspect-kind')",
        timeout=5_000,
    )


def test_agent_hover_populates_bottom_inspector(signed_in_page):
    """Agent-card hover renders the agent's model into #df-config-panel,
    stamps #ws-step-meta with data-inspect-kind='agent' (data-step-id stays
    '(none)'), and never opens the config popup."""
    page = signed_in_page
    _wait_composer(page)
    agent_id = page.locator(AGENT_CARD).first.get_attribute("data-agent-id")
    _hover_agent_card(page)
    meta = page.locator("#ws-step-meta")
    assert meta.get_attribute("data-inspect-kind") == "agent"
    assert meta.get_attribute("data-step-id") == "(none)"
    # The inspector shows the RESOLVED agent's model (ask #6) plus the
    # tools/context rows, read-only, in the bottom pane only.
    agent = page.evaluate(
        "(id) => fetch('/api/agents/' + id).then(r => r.json())", agent_id
    )
    panel_text = page.evaluate(
        "() => document.getElementById('df-config-panel').textContent"
    )
    assert (agent.get("model") or "(role-based)") in panel_text
    assert "Tools" in panel_text and "Context" in panel_text
    inspector = page.locator("#df-config-panel .ws-inspector")
    assert inspector.count() == 1
    assert inspector.get_attribute("data-inspect-kind") == "agent"
    assert not page.locator("#df-config-popup").is_visible(), (
        "inspector must never auto-open the step-config popup"
    )


def test_node_click_restores_step_config_over_inspector(signed_in_page):
    """A canvas-node single click beats lingering inspector content: the
    Step Config form repaints and the data-inspect-kind stamp clears."""
    page = signed_in_page
    _wait_composer(page)
    # Dock the popup so the spawned node doesn't overlay the canvas.
    page.evaluate("() => { window._stepConfigDocked = true; }")
    node_id = page.evaluate("() => window.dfAddNodeFromTemplate('analyzer', 320, 220)")
    assert node_id, "dfAddNodeFromTemplate returned no node id"
    # Bench hover replaces the freshly rendered Step Config with the
    # read-only agent inspection...
    _hover_agent_card(page)
    assert page.locator("#df-config-panel .ws-inspector").count() == 1
    # ...then clicking the node restores the editable Step Config form.
    page.locator(f"#node-{node_id} .df-node-body").click()
    page.wait_for_function(
        "() => !document.getElementById('ws-step-meta')"
        ".hasAttribute('data-inspect-kind')",
        timeout=5_000,
    )
    meta = page.locator("#ws-step-meta")
    assert meta.get_attribute("data-step-id") != "(none)"
    panel_text = page.evaluate(
        "() => document.getElementById('df-config-panel').textContent"
    )
    assert "Identity" in panel_text, "Step Config form not restored"
    assert page.locator("#df-config-panel .ws-inspector").count() == 0
