"""MS-2 — Composer canvas state: empty-overlay clears on add + benches stay
on a single row.

Two live-DOM invariants, both regressions the operator hit on this branch:

  1. The #composer-canvas-empty guide ("Compose a workflow") is gated on REAL
     step count — a boot seed alone keeps it up — and any manual add (palette
     drop / click-to-add) clears it. Before MS-2 it stayed painted OVER the
     freshly dropped node because no state recompute fired on the add.
  2. The workbench benches never wrap to a second row; at 1600px they share a
     single offsetTop, scrolling horizontally (overflow-x:auto) instead.
"""

from __future__ import annotations

SEED_SEL = "#drawflow-canvas .df-seed-node"
OVERLAY = "#composer-canvas-empty"
PANEL = "#composer-canvas-panel"


def _wait_canvas(page):
    """Canvas booted = the seed pill has spawned (ComposerView.init +
    dfAddSeedNode have both run their empty-state recompute) and the window
    bridge exposes the add helpers this suite drives. ComposerView itself is
    ES-module-scoped (not on window) — the suite asserts the resulting DOM,
    which the boot + add paths already settle."""
    page.wait_for_selector(SEED_SEL, state="visible", timeout=10_000)
    page.wait_for_function(
        "() => typeof window.dfAddNodeFromTemplate === 'function'",
        timeout=10_000,
    )


def _has_nodes(page) -> bool:
    return page.evaluate(
        "() => document.querySelector('#composer-canvas-panel')"
        ".classList.contains('has-nodes')"
    )


def _overlay_display(page) -> str:
    return page.evaluate(
        "() => getComputedStyle(document.querySelector('#composer-canvas-empty')).display"
    )


def test_empty_overlay_up_on_seed_only_canvas(signed_in_page):
    """A fresh canvas carries only the boot seed — not a real step — so the
    empty-state guide stays painted and the panel is NOT flagged has-nodes.
    (The seed must not falsely count as has-nodes.)"""
    page = signed_in_page
    _wait_canvas(page)
    # Sanity: only the seed is on the canvas (no real steps).
    real_steps = page.evaluate(
        "() => Object.values(window.dfNodeData || {}).filter(d => d && !d.is_seed).length"
    )
    assert real_steps == 0, "precondition: a fresh canvas has no real steps"
    assert _has_nodes(page) is False, "seed-only canvas must not be flagged has-nodes"
    assert _overlay_display(page) != "none", "guide must stay up on a seed-only canvas"


def test_palette_drop_clears_empty_overlay(signed_in_page):
    """Dropping a step template registers a REAL step, flags the panel
    has-nodes, and hides #composer-canvas-empty. Drives the actual drop
    handler (synthetic DataTransfer) so the drop-handler-tail update runs —
    not a direct helper call."""
    page = signed_in_page
    _wait_canvas(page)
    assert _overlay_display(page) != "none", "precondition: overlay visible pre-drop"
    before = page.evaluate("() => Object.keys(window.dfNodeData || {}).length")
    # 'analyzer' is a stable dfStepTemplates key. dfStepTemplates is module-
    # scoped (not on window), so pass the key in rather than reading it out.
    key = "analyzer"
    page.evaluate(
        """(k) => {
            const canvas = document.getElementById('drawflow-canvas');
            const r = canvas.getBoundingClientRect();
            const dt = new DataTransfer();
            dt.setData('application/df-template', k);
            canvas.dispatchEvent(new DragEvent('drop', {
                bubbles: true, cancelable: true, dataTransfer: dt,
                clientX: r.left + r.width / 2, clientY: r.top + r.height / 2,
            }));
        }""",
        key,
    )
    page.wait_for_function(
        "n => Object.keys(window.dfNodeData || {}).length > n",
        arg=before,
        timeout=5_000,
    )
    real_steps = page.evaluate(
        "() => Object.values(window.dfNodeData || {}).filter(d => d && !d.is_seed).length"
    )
    assert real_steps >= 1, f"template drop ({key!r}) did not register a real step"
    assert _has_nodes(page) is True, "panel must be has-nodes after a real step drops"
    assert _overlay_display(page) == "none", "overlay must hide once a real step exists"


def test_bench_tabs_stay_single_row_at_1600(signed_in_page):
    """At 1600px the workbench benches share a single offsetTop — they scroll
    horizontally (flex-wrap:nowrap + overflow-x:auto), never wrap to a second
    row (which would shove the canvas down and read as breakage)."""
    page = signed_in_page
    page.set_viewport_size({"width": 1600, "height": 900})
    _wait_canvas(page)
    tops = page.evaluate(
        "() => Array.from(document.querySelectorAll('.workbench-tabs .workbench-tab'))"
        ".map(t => t.offsetTop)"
    )
    assert len(tops) >= 6, f"expected >=6 workbench tabs, got {len(tops)}"
    assert len(set(tops)) == 1, f"workbench tabs wrapped to multiple rows: {tops}"
    flex_wrap = page.evaluate(
        "() => getComputedStyle(document.querySelector('.workbench-tabs')).flexWrap"
    )
    assert flex_wrap == "nowrap", f"workbench-tabs must not wrap, got flex-wrap={flex_wrap}"
    overflow_x = page.evaluate(
        "() => getComputedStyle(document.querySelector('.workbench-tabs')).overflowX"
    )
    assert overflow_x in ("auto", "scroll"), f"benches must scroll, got overflow-x={overflow_x}"
