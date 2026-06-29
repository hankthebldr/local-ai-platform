"""Regression for the composer's vertical (chat-top / canvas-bottom) layout.

The composer split was flipped from left/right to a full-height vertical stack:
chat on top, a row-resize divider, the workflow canvas below, then the
workstream strip. --chat-frac is now a HEIGHT fraction. The Chat/Canvas/Focus
view toggle is the front-and-center control for flipping between them.
"""

import re


def test_split_is_vertical_rows(index_html_text):
    m = re.search(r"\.composer-split\s*\{[^}]*\}", index_html_text, re.S)
    assert m, ".composer-split rule not found"
    block = m.group(0)
    assert (
        "grid-template-rows: var(--chat-frac" in block
    ), "split is not row-based (chat-frac height)"
    assert (
        "grid-template-columns: minmax(0, 1fr)" in block
    ), "split should be a single column"


def test_chat_top_canvas_bottom_placement(index_html_text):
    assert "> .agent-chat-dock      { grid-row: 1;" in index_html_text  # chat on top
    assert "> .composer-grid        { grid-row: 3;" in index_html_text  # canvas below
    assert (
        "> .composer-workstream  { grid-row: 4;" in index_html_text
    )  # workstream strip


def test_divider_is_row_resize(index_html_text):
    assert "cursor: row-resize;" in index_html_text
    # vertical drag math: clientY / rect.height
    assert "(e.clientY - rect.top) / rect.height" in index_html_text
    # a11y: separator now horizontal
    assert 'aria-orientation="horizontal"' in index_html_text


def test_focus_mode_full_canvas(index_html_text):
    # Focus hides the chat for a full-bleed canvas.
    assert re.search(
        r"\.composer-split\.mode-focus\s*>\s*\.agent-chat-dock\s*\{\s*display:\s*none",
        index_html_text,
    )


def test_view_toggle_is_prominent(index_html_text):
    # Solid-accent active segment so the current view reads at a glance.
    m = re.search(
        r'\.composer-mode-toggle \.mode-btn\[aria-pressed="true"\]\s*\{[^}]*background:\s*var\(--accent\)',
        index_html_text,
    )
    assert (
        m is not None
    ), "active view-toggle segment is not solid-accent (not prominent)"
