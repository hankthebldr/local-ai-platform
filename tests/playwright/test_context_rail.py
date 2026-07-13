"""
U14 — Context node rail (op5-context-rail).

The Context tab's node detail moved out of the left column into the right
rail, joined by a #context-node-list run/response picker. The rail is driven
through the shared, kind-agnostic shell/context-node-rail.js pane-guard: a
context-pane selection paints the run/promote/provenance pivots into
#context-detail-actions; a research-pane selection must NOT.

These tests exercise the three Verify criteria from the spec:
  1. rail row select fills #context-detail-title;
  2. graph.open-run lands on #tab-runs;
  3. a Research-pane node selection does NOT drive the Context rail.

They drive the SPA through the legacy-bridged window globals (window.selectNode
/ window.renderGraph, already in the parity golden) plus a synthetic graph so
the run/provenance nodes are deterministic without depending on the live
/api/graph corpus.
"""

from __future__ import annotations

# A deterministic run/provenance dataset: one full-id workflow_run, one
# response, and one research-pane session node (which the context picker must
# ignore). Injected via a getter override because window.graphData is a
# getter-only legacy-bridge property.
_SETUP_JS = """
() => {
  const SYN = {
    nodes: [
      { id: 'run-abc123456789', run_id: 'run-abc123456789', type: 'workflow_run',
        label: 'demo-run', status: 'success', workflow_id: 'demo' },
      { id: 'resp-xyz987654321', type: 'response', label: 'demo-response', edge_count: 3 },
      { id: 'sess-1', type: 'session', label: 'a-session' }
    ],
    links: []
  };
  Object.defineProperty(window, 'graphData', { get: () => SYN, configurable: true });
  // Paints the context pane + builds its pane state, and dispatches
  // graph:context-rendered → the picker refreshes off window.graphData.
  window.renderGraph(SYN, 'context');
  document.dispatchEvent(new CustomEvent('graph:context-rendered'));
}
"""

_CTX_RUN_NODE_JS = """
() => window.selectNode(
  { id: 'run-abc123456789', run_id: 'run-abc123456789', type: 'workflow_run',
    label: 'demo-run', status: 'success', workflow_id: 'demo' },
  'context'
)
"""


def _open_context(page):
    page.click('.tab-nav button[data-tab="context"]')
    page.wait_for_selector("#tab-context", state="visible", timeout=5_000)


def test_context_node_list_populates_and_row_fills_detail(signed_in_page):
    """The #context-node-list picker lists the run/response nodes (never the
    research session node), and clicking a row fills #context-detail-title."""
    page = signed_in_page
    _open_context(page)
    page.evaluate(_SETUP_JS)

    page.wait_for_selector("#context-node-list .context-node-row", timeout=5_000)
    # Only the two run/provenance nodes — the session node is research-pane.
    assert page.locator("#context-node-count").inner_text().strip() == "2"
    assert page.locator("#context-node-list .context-node-row").count() == 2

    # Row select → graph.node-select → selectNodeById('…','context') →
    # selectNode fills the relocated detail panel.
    page.locator("#context-node-list .context-node-row").first.click()
    page.wait_for_function(
        "() => (document.getElementById('context-detail-title') || {}).textContent"
        ".includes('demo-run')",
        timeout=5_000,
    )
    # .panel-label is CSS text-transform:uppercase — compare case-insensitively.
    assert "demo-run" in page.locator("#context-detail-title").inner_text().lower()


def test_context_detail_relocated_into_right_rail(signed_in_page):
    """#context-detail (ids preserved) now lives inside .research-right — the
    sidebar rail — not the left graph column."""
    page = signed_in_page
    _open_context(page)
    in_rail = page.evaluate(
        "() => { const d = document.getElementById('context-detail');"
        " return !!(d && d.closest('.research-right')); }"
    )
    assert in_rail, "#context-detail must be relocated into the .research-right rail"
    # All child ids survived the move (relocated, not renamed).
    for cid in (
        "context-detail-kind",
        "context-detail-title",
        "context-detail-meta",
        "context-detail-connections",
        "context-detail-actions",
    ):
        assert page.locator(f"#{cid}").count() == 1, f"missing relocated id #{cid}"


def test_open_run_pivot_lands_on_runs(signed_in_page):
    """Selecting a full-id run node paints an enabled graph.open-run pivot;
    clicking it switches to #tab-runs and calls RunsTab.select."""
    page = signed_in_page
    _open_context(page)
    page.evaluate(_CTX_RUN_NODE_JS)

    btn = page.locator('#context-detail-actions [data-action="graph.open-run"]')
    page.wait_for_selector(
        '#context-detail-actions [data-action="graph.open-run"]', timeout=5_000
    )
    assert btn.get_attribute("data-run-id") == "run-abc123456789"
    assert not btn.is_disabled(), "a full run id must enable the Open-run pivot"

    btn.click()
    page.wait_for_selector("#tab-runs", state="visible", timeout=5_000)
    assert page.locator("#tab-runs").is_visible()


def test_research_click_does_not_drive_context_rail(signed_in_page):
    """The single pane-guard: a Research-pane selection must never repaint the
    Context rail's pivot footer."""
    page = signed_in_page
    _open_context(page)
    page.evaluate(_CTX_RUN_NODE_JS)
    page.wait_for_selector(
        '#context-detail-actions [data-action="graph.open-run"]', timeout=5_000
    )
    before = page.locator("#context-detail-actions").inner_html()

    # A research-pane node selection writes #session-detail, and its
    # ContextNodeRail.activate('context-node', …, 'research') is rejected by
    # the guard — so #context-detail-actions must be byte-identical after.
    page.evaluate(
        "() => window.selectNode({ id: 'sess-1', type: 'session',"
        " label: 'a-session' }, 'research')"
    )
    after = page.locator("#context-detail-actions").inner_html()
    assert before == after, "a Research-pane click drove the Context rail"
