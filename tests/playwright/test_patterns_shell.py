"""PT-1 — Patterns library shell + bench drill-down inspector.

Two surfaces land here:

  1. The Patterns LibraryShell tab (nav → Patterns): a uniform .lib-row list of
     the 8 shipped presets ∪ any user patterns, a "Structure" drill-down and a
     "JSON" source subnav, and Send-to-Composer / Edit / Promote / Delete
     actions (Delete disabled on a shipped builtin).
  2. The Composer Patterns bench drill-down: hovering a pattern card paints its
     structure (node list + ASCII wiring + config defaults) into
     #df-config-panel via the SHARED dfRenderPatternStructure renderer —
     read-only, never opening the Step Config popup, and a canvas node
     selection still wins.
"""

from __future__ import annotations

SEED_SEL = "#drawflow-canvas .df-seed-node"
PATTERNS_TAB = '.workbench-tab[data-bench="patterns"]'
PATTERN_CARD = '#patterns-palette .df-pattern-card'


def _wait_composer(page):
    page.wait_for_selector(SEED_SEL, state="visible", timeout=10_000)
    page.wait_for_function(
        "() => typeof window.dfRenderPatternStructure === 'function'"
        " && typeof window.dfResolvePattern === 'function'",
        timeout=10_000,
    )


# ── Library shell ───────────────────────────────────────────────────────────


def test_patterns_tab_lists_builtins_uniform_rows(signed_in_page):
    """The Patterns nav tab mounts the shell and renders the 8 shipped presets
    as uniform .lib-row rows carrying an oob provenance chip."""
    page = signed_in_page
    _wait_composer(page)
    page.click('.tab-btn[data-tab="patterns"]')
    page.wait_for_selector("#patterns-shell .lib-shell", state="visible", timeout=10_000)
    page.wait_for_function(
        "() => document.querySelectorAll('#lib-pattern-list .lib-row').length >= 8",
        timeout=10_000,
    )
    rows = page.locator("#lib-pattern-list .lib-row")
    assert rows.count() >= 8
    titles = page.evaluate(
        "() => Array.from(document.querySelectorAll('#lib-pattern-list .lib-row "
        ".lib-row-title')).map(t => t.textContent)"
    )
    joined = " ".join(titles)
    assert "Ralph loop" in joined and "Research fan-out" in joined
    # count badge in the nav reflects the merged list
    assert (page.locator("#patterns-count").text_content() or "").strip() != ""


def test_pattern_detail_structure_and_source(signed_in_page):
    """Selecting a builtin shows a Structure drill-down (ASCII wiring + config
    defaults) and a JSON source subnav; the shipped preset's Delete is disabled
    and Promote is enabled."""
    page = signed_in_page
    _wait_composer(page)
    page.click('.tab-btn[data-tab="patterns"]')
    page.wait_for_selector("#lib-pattern-list .lib-row", state="visible", timeout=10_000)
    page.evaluate("() => window.PatternsPanel.select('ralph_loop')")
    page.wait_for_selector("#lib-pattern-detail .lib-section", timeout=5_000)
    struct = page.evaluate(
        "() => document.querySelector('#lib-pattern-detail .lib-section[data-section=\"overview\"]').textContent"
    )
    # the drill-down surfaces the nested body ids + ralph halt caps
    assert "plan" in struct and "execute" in struct and "verify" in struct
    assert "ralph halt" in struct or "halt gate" in struct
    # Promote enabled, Delete disabled for a pure builtin
    actions = page.evaluate(
        """() => Array.from(document.querySelectorAll('#lib-pattern-detail .lib-actions-row button'))
            .map(b => ({ a: b.dataset.action, disabled: b.disabled }))"""
    )
    by_action = {x["a"]: x for x in actions}
    assert by_action["patterns.delete"]["disabled"] is True
    assert by_action["patterns.promote"]["disabled"] is False
    assert "patterns.send-to-composer" in by_action


# ── Composer bench drill-down inspector ─────────────────────────────────────


def test_bench_pattern_hover_paints_structure_without_popup(signed_in_page):
    """Hovering a Patterns-bench card drills its structure into #df-config-panel
    (data-inspect-kind='pattern', data-step-id stays '(none)') and never opens
    the Step Config popup — the shared dfRenderPatternStructure renderer."""
    page = signed_in_page
    _wait_composer(page)
    page.click(PATTERNS_TAB)
    page.wait_for_selector(PATTERN_CARD, state="visible", timeout=10_000)
    # the static cards carry the drill-down action + inspect key (not bench.drag)
    ralph = page.locator('#patterns-palette [data-pattern="ralph_loop"]')
    assert ralph.get_attribute("data-action") == "bench.inspect-pattern"
    assert ralph.get_attribute("data-inspect-key") == "ralph_loop"
    # still draggable with the shared pattern MIME (drop path unchanged)
    assert ralph.get_attribute("data-drag-mime") == "application/df-pattern"
    page.evaluate(
        """() => document.querySelector('#patterns-palette [data-pattern="ralph_loop"]')
            .dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))"""
    )
    page.wait_for_function(
        "() => document.getElementById('ws-step-meta').getAttribute('data-inspect-kind') === 'pattern'",
        timeout=5_000,
    )
    meta = page.locator("#ws-step-meta")
    assert meta.get_attribute("data-inspect-kind") == "pattern"
    assert meta.get_attribute("data-step-id") == "(none)"
    panel_text = page.evaluate(
        "() => document.getElementById('df-config-panel').textContent"
    )
    assert "STRUCTURE" in panel_text and "plan" in panel_text
    inspector = page.locator("#df-config-panel .ws-inspector")
    assert inspector.count() == 1
    assert inspector.get_attribute("data-inspect-kind") == "pattern"
    # read-only drill-down never auto-opens the Step Config popup
    assert page.locator("#df-config-popup").get_attribute("hidden") is not None


def test_node_click_beats_pattern_drilldown(signed_in_page):
    """A canvas node selection wins over lingering pattern drill-down content —
    the inspect stamp clears and the Step Config form repaints."""
    page = signed_in_page
    _wait_composer(page)
    page.click(PATTERNS_TAB)
    page.wait_for_selector(PATTERN_CARD, state="visible", timeout=10_000)
    page.evaluate(
        """() => document.querySelector('#patterns-palette [data-pattern="llm_step"]')
            .dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))"""
    )
    page.wait_for_function(
        "() => document.getElementById('ws-step-meta').getAttribute('data-inspect-kind') === 'pattern'",
        timeout=5_000,
    )
    # spawn + select a real node — its Step Config must supersede the drill-down
    node_id = page.evaluate(
        "() => window.dfAddNodeFromTemplate('custom', 340, 220)"
    )
    page.evaluate("(id) => window.dfRenderConfigPanel(id)", node_id)
    page.evaluate(
        "() => window.ComposerWorkstream && window.ComposerWorkstream.focusStep('custom')"
    )
    assert page.evaluate(
        "() => !document.getElementById('ws-step-meta').hasAttribute('data-inspect-kind')"
    )
    assert page.locator("#df-config-panel .ws-inspector").count() == 0
