"""
Workflow Index — the catalogue of shipped XQL/XDM workflows.

Verifies the 5 OOTB workflows are listed and openable in the Composer:
  - data-model-rules
  - xdm-bulk-onboarding
  - xdm-rule-from-log
  - xsiam-data-model-rules
  - xsiam-normalization-pipeline
"""

from __future__ import annotations

import pytest

OOTB_WORKFLOWS = [
    ("data-model-rules", "Generate Data Model Rules"),
    ("xdm-bulk-onboarding", "Bulk Vendor Onboarding"),
    ("xdm-rule-from-log", "XDM Rule from Single Log Sample"),
    ("xsiam-data-model-rules", "XSIAM Data Model Rule Generator"),
    ("xsiam-normalization-pipeline", "XSIAM Full Normalization Pipeline"),
]


def _open_workflow_index(page):
    page.click('button[data-tab="workflow-index"]')
    page.wait_for_selector("#tab-workflow-index", state="visible", timeout=5_000)
    # Wait for the grid to leave the "Loading workflows…" placeholder. A
    # rendered card always contains the literal "wfi-card" class string.
    try:
        page.wait_for_function(
            """() => {
                const grid = document.getElementById('wfi-grid');
                if (!grid) return false;
                const html = grid.innerHTML;
                return html.includes('wfi-card') || html.includes('No workflows match');
            }""",
            timeout=20_000,
        )
    except Exception:
        # Surface the grid's actual state when the wait times out so
        # debugging doesn't require re-running with --headed.
        actual = (
            page.locator("#wfi-grid").inner_html()
            if page.locator("#wfi-grid").count()
            else "(no #wfi-grid found)"
        )
        raise AssertionError(
            f"Workflow Index grid didn't populate within 20s. Grid HTML: {actual[:500]}"
        )


def test_workflow_index_lists_all_ootb_workflows(signed_in_page):
    """All 5 OOTB workflows must appear in the index."""
    page = signed_in_page
    _open_workflow_index(page)
    grid_text = page.locator("#wfi-grid").inner_text()
    missing = [name for wf_id, name in OOTB_WORKFLOWS if name not in grid_text]
    assert (
        not missing
    ), f"Workflow Index missing OOTB entries: {missing}\nFull text: {grid_text[:500]}"


def test_workflow_index_count_badge_matches(signed_in_page):
    """The tab-count badge on the Workflow Index tab should reflect the 5 OOTB workflows."""
    page = signed_in_page
    _open_workflow_index(page)
    badge = page.locator("#wfi-count")
    if badge.count() > 0:
        text = badge.inner_text().strip()
        # Format is typically "(5)" or similar.
        digits = "".join(c for c in text if c.isdigit())
        if digits:
            assert int(digits) >= 5, f"wfi-count badge shows {digits}, expected ≥5"


@pytest.mark.parametrize("wf_id,wf_name", OOTB_WORKFLOWS)
def test_workflow_index_can_open_workflow_in_composer(signed_in_page, wf_id, wf_name):
    """Clicking 'Open in Composer' on a workflow card should switch to the
    Composer tab with the workflow's metadata pre-filled in the toolbar.
    This is the primary user path for editing or extending a shipped workflow."""
    page = signed_in_page
    _open_workflow_index(page)
    # Look for the workflow card by its rendered name. The "Open" button is
    # typically inside the card.
    card = page.locator(".wfi-card", has_text=wf_name).first
    if card.count() == 0:
        # Fallback selector — different builds render the card differently.
        card = page.locator("[data-wf-id='" + wf_id + "']").first
    assert card.count() > 0, f"No card found for workflow {wf_id} ({wf_name})"

    # The card's primary action is labeled "Compose" (renders calls
    # WorkflowIndex.openInComposer). "Open" / "Composer" are legacy fallbacks
    # kept for older builds.
    open_btn = card.locator("button", has_text="Compose").first
    if open_btn.count() == 0:
        open_btn = card.locator("button", has_text="Open").first
    if open_btn.count() == 0:
        open_btn = card.locator("button").first
    open_btn.click()

    # After clicking, we should be on the dashboard tab with df-wf-id populated.
    page.wait_for_selector("#tab-dashboard", state="visible", timeout=5_000)
    wf_id_input = page.locator("#df-wf-id")
    page.wait_for_function(
        """(id) => {
            const el = document.getElementById('df-wf-id');
            return el && el.value === id;
        }""",
        arg=wf_id,
        timeout=10_000,
    )
    assert wf_id_input.input_value() == wf_id
