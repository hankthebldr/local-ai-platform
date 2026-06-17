"""Regression for the graph polish + the composer chat↔canvas composition fix.

Graph: a 'tokens' sizing mode (node size ∝ token usage) + the knowledge-graph
panel sharing the same dot-grid/accent-glow background as the composer/runs
canvas. Composition: the legacy 520px+ min-height floors on .composer-grid /
.composer-canvas-panel are collapsed inside the vertical split (else the canvas
overflows its row and the chat↔canvas proportion breaks across all modes).
"""

import re


def test_graph_token_sizing_mode(index_html_text):
    # Picker offers a Tokens mode + the weight function sizes by d.tokens.
    assert "['tokens'," in index_html_text
    assert re.search(r"mode === 'tokens'.*d\.tokens", index_html_text)


def test_graph_panel_shares_canvas_background(index_html_text):
    # .graph-panel must use the dot-grid + accent-glow, not a flat --bg-panel.
    m = re.search(r"\.graph-panel\s*\{[^}]*\}", index_html_text, re.S)
    assert m, ".graph-panel rule missing"
    block = m.group(0)
    assert (
        "radial-gradient(var(--border) 1px, transparent 1px)" in block
    ), "graph panel missing dot grid"
    assert "background-size: 100% 100%, 22px 22px" in block


def test_split_collapses_legacy_min_height_floors(index_html_text):
    # The 520px+ floors must be overridden inside the split, or the canvas
    # overflows its row and breaks the chat↔canvas composition.
    assert re.search(
        r"\.composer-split\s*>\s*\.composer-grid\s*\{[^}]*min-height:\s*0\s*!important",
        index_html_text,
    )
    assert re.search(
        r"\.composer-split\s+\.composer-canvas-panel\s*\{[^}]*min-height:\s*0\s*!important",
        index_html_text,
    )


def test_workstream_capped_so_canvas_keeps_share(index_html_text):
    # The bottom workstream strip is capped so it can't starve the canvas row.
    assert re.search(
        r"\.composer-split\s*>\s*\.composer-workstream\s*\{[^}]*max-height:\s*150px",
        index_html_text,
    )
