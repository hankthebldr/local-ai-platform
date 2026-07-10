"""BU3 — editable seed node + unified double-click node config.

The Composer auto-spawns exactly one editable seed node on an empty canvas
(compose mode). Double-clicking it opens the seed config surface (query
textarea + schema rows); Save persists into dfNodeData, asserted through the
window bridge's live getter. Pure canvas UI — no model runs, resilient to a
partial stack (session-scoped `_require_stack` skips when the API is down).
"""

from __future__ import annotations

SEED_SEL = "#drawflow-canvas .df-seed-node"


def _wait_seed_node(page):
    """The seed spawns on the debounced anchor refresh (~150 ms after the
    Composer boots); wait for the pill rather than sleeping."""
    page.wait_for_selector(SEED_SEL, state="visible", timeout=10_000)


def test_seed_node_autospawns_on_empty_canvas(signed_in_page):
    """Compose mode on a fresh canvas shows exactly one seed node, registered
    in dfNodeData (it's a real node, not the decorative __start__ ghost)."""
    page = signed_in_page
    _wait_seed_node(page)
    seed_count = page.evaluate(
        "() => Object.values(window.dfNodeData || {})"
        ".filter(d => d && d.is_seed).length"
    )
    assert seed_count == 1, f"expected exactly one seed node, got {seed_count}"
    # The real seed supersedes the decorative START ghost on the canvas.
    assert page.locator("#drawflow-canvas .wf-anchor-start:not(.df-seed-node)").count() == 0


def test_seed_dblclick_opens_config_with_query_textarea(signed_in_page):
    """Unified dblclick-to-edit: double-clicking the seed opens the config
    popup with the seed's query textarea + schema rows."""
    page = signed_in_page
    _wait_seed_node(page)
    page.dblclick(SEED_SEL)
    popup = page.locator("#df-config-popup")
    popup.wait_for(state="visible", timeout=5_000)
    assert popup.locator(".df-seed-cfg-query").is_visible(), "seed query textarea missing"
    assert popup.locator(".df-seed-cfg-row").count() >= 1, "seed schema rows missing"


def test_seed_query_save_persists_into_node_data(signed_in_page):
    """Typing a query + Save persists into the seed's dfNodeData entry
    (the value dfRunWorkflowLive feeds into the run payload)."""
    page = signed_in_page
    _wait_seed_node(page)
    page.dblclick(SEED_SEL)
    popup = page.locator("#df-config-popup")
    popup.wait_for(state="visible", timeout=5_000)
    query = "summarize the quarterly telemetry"
    popup.locator(".df-seed-cfg-query").fill(query)
    popup.locator('[data-action="composer.seed-save"]').click()
    page.wait_for_function(
        "() => { const d = Object.values(window.dfNodeData || {})"
        ".find(d => d && d.is_seed); return !!(d && d.query); }",
        timeout=5_000,
    )
    stored = page.evaluate(
        "() => Object.values(window.dfNodeData || {})"
        ".find(d => d && d.is_seed).query"
    )
    assert stored == query
    # The canvas pill repaints with the saved query preview.
    assert query in (page.locator(SEED_SEL).inner_text() or "")
