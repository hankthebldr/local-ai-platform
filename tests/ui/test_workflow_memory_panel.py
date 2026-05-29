"""Structural test for the Workflow Memory panel in the Memory tab.

We can't drive the browser here; we assert the template + CSS + the JS module
needed to render the panel are present in api/static/index.html. The backend
tests in tests/test_workflow_memory_routes.py cover the API the panel calls.
"""

from __future__ import annotations

import re


def test_workflow_memory_panel_html_present(index_html_text):
    """The Memory tab must contain the workflow-memory-panel container with
    one list per store (playbooks / semantic / episodic)."""
    assert 'id="workflow-memory-panel"' in index_html_text
    for list_id in ("wm-playbooks-list", "wm-semantic-list", "wm-episodic-list"):
        assert f'id="{list_id}"' in index_html_text, f"missing list container {list_id}"
    # Refresh button wired to the JS module.
    assert "WorkflowMemory.refresh()" in index_html_text


def test_workflow_memory_css_grid_present(index_html_text):
    """Three-column grid with per-target column styling."""
    css = index_html_text
    assert ".wm-grid" in css
    assert "grid-template-columns: repeat(3, 1fr)" in css
    for cls in (".wm-col", ".wm-col-head", ".wm-item", ".wm-detail-body"):
        assert cls in css, f"missing CSS rule {cls}"


def test_workflow_memory_js_module_present(index_html_text):
    """The IIFE module + global window binding must be there so the
    Memory-tab switch hook can call .refresh()."""
    assert "const WorkflowMemory = (function ()" in index_html_text
    assert "window.WorkflowMemory = WorkflowMemory" in index_html_text


def test_workflow_memory_calls_correct_api(index_html_text):
    """The module must call the /api/workflows/memory/* endpoints — not the
    legacy /api/memory router (which is for session/fact memory)."""
    assert "/api/workflows/memory/" in index_html_text
    # Sanity: each TARGETS entry references a real store name.
    for kind in ("playbooks", "semantic", "episodic"):
        assert (
            f"kind: '{kind}'" in index_html_text
        ), f"target {kind!r} missing from module"


def test_memory_tab_activation_wires_workflow_memory(index_html_text):
    """The Memory-tab switch hook must call WorkflowMemory.refresh() so the
    panel populates when the operator opens the tab."""
    # Find the tab-switch hook line that handles 'memory'.
    match = re.search(
        r"if\s*\(\s*name\s*===\s*'memory'\s*\)\s*\{[^}]*\}",
        index_html_text,
    )
    assert match, "memory tab activation block not found"
    block = match.group(0)
    assert "WorkflowMemory" in block, "WorkflowMemory not invoked on tab activation"
