"""Regression for the expanded run-step detail overflow ("doesn't fit in the box").

.ws-run-step is a 4-column grid, but .ws-run-step-head has its OWN grid and the
.run-step-expanded body is full-width content — so both must span all of
.ws-run-step's columns, else the expanded metadata (tokens/model/started/input/
output) gets squeezed into a single ~120px grid cell.
"""

import re


def test_step_head_and_expanded_span_all_columns(index_html_text):
    # Both the head and the expanded body must be set to grid-column: 1 / -1.
    m = re.search(
        r"\.ws-run-step\s*>\s*\.ws-run-step-head,\s*\.ws-run-step\s*>\s*\.run-step-expanded\s*\{[^}]*grid-column:\s*1\s*/\s*-1",
        index_html_text,
    )
    assert m is not None, (
        "expanded run-step detail not spanning full width — it will be squeezed "
        "into a single grid column and overflow its box"
    )


def test_expanded_long_values_can_wrap_or_scroll(index_html_text):
    # The error text + output panels must wrap/scroll long content, not overflow.
    assert "white-space: pre-wrap; word-break: break-word;" in index_html_text
