"""Structural test for the per-step kind chip in the Runs view.

We can't drive the browser here, so we assert the template + CSS that
deliver the chip are present in api/static/index.html. Pairs with the
backend test in tests/test_workflow_router_kinds.py which proves the API
decorates step_results with `kind`.
"""

from __future__ import annotations

import re

# The Runs view renderer injects this span for every step row.
KIND_SPAN_RE = re.compile(
    r'class="run-step-kind kind-\$\{esc\(s\.kind \|\| \'llm\'\)\}"'
)


def test_runs_view_renders_kind_chip(index_html_text):
    """The Runs view step renderer must include a kind chip with a
    class that interpolates the step's kind."""
    assert KIND_SPAN_RE.search(
        index_html_text
    ), "kind chip span missing from Runs view step renderer"


def test_kind_chip_css_palette_present(index_html_text):
    """One CSS rule per kind we ship — the chips need a color so the
    operator can tell parallel from loop at a glance. kind=llm is
    deliberately display:none (the dominant case shouldn't add noise)."""
    css = index_html_text
    # Base class.
    assert ".run-step-kind {" in css
    # Per-kind rules.
    for kind in (
        "kind-parallel",
        "kind-loop",
        "kind-a2a",
        "kind-orchestrator",
        "kind-consolidate",
        "kind-ralph",
    ):
        assert f".run-step-kind.{kind}" in css, f"missing CSS rule for {kind}"
    # kind=llm is hidden — chip noise on the dominant case is worse than
    # silence.
    assert re.search(
        r"\.run-step-kind\.kind-llm\s*{\s*display:\s*none;\s*}", css
    ), "kind-llm chip should be display:none"
