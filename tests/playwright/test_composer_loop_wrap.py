"""BU8b — Loop wrap: the toolbar affordance that makes any workflow a ralph loop.

The `composer.loop-wrap` action (Actions-wired button in the composer
actions row — no inline onclick) wraps the CURRENT canvas into ONE
kind:ralph parent whose body holds the previous top-level steps (the
same nested-body semantics the BU4 ralph scaffold spawns), pre-filled
with journal_path + halt budget caps, then opens the parent's Safety
rails config (BU8a). An empty (seed-only) canvas toasts 'Add steps
first'; the restructure is gated by the shared Confirm dialog; and the
wrapped result round-trips dfExportYaml → the frozen WorkflowDefinition
model. (Schedule/recurring-cron is CUT from v1 — no schedule UI exists.)
"""

from __future__ import annotations

import yaml

from api.models.workflow_models import WorkflowDefinition

BTN = '[data-action="composer.loop-wrap"]'
SEED_SEL = "#drawflow-canvas .df-seed-node"


def _wait_canvas(page):
    """Canvas booted = the seed pill has spawned (debounced ~150 ms) and the
    bridge exposes the pattern spawner + exporter."""
    page.wait_for_selector(SEED_SEL, state="visible", timeout=10_000)
    page.wait_for_function(
        "() => typeof window.dfAddPatternFromTemplate === 'function'"
        " && typeof window.dfExportYaml === 'function'",
        timeout=10_000,
    )


def _click_wrap(page):
    """Dispatch the click through the Actions delegation router directly —
    the actions row can sit inside a collapsed <details>, and headless
    element-clicks on it are flaky (same precedent as the drag sims)."""
    page.evaluate(f"() => document.querySelector('{BTN}').click()")


def test_loop_wrap_button_is_actions_wired(signed_in_page):
    """Exactly one toolbar affordance, wired via data-action — never a new
    inline onclick handler."""
    page = signed_in_page
    _wait_canvas(page)
    btn = page.locator(BTN)
    assert btn.count() == 1, "composer.loop-wrap toolbar button missing"
    assert btn.get_attribute("onclick") is None, "new button must not use inline onclick"


def test_loop_wrap_empty_canvas_toasts_add_steps_first(signed_in_page):
    """A seed-only canvas counts as empty: toast, no confirm, no restructure."""
    page = signed_in_page
    _wait_canvas(page)
    _click_wrap(page)
    page.wait_for_selector(".enclave-toast", timeout=5_000)
    # inner_text() applies the toast title's text-transform:uppercase.
    assert "add steps first" in page.locator(".enclave-toast").first.inner_text().lower()
    modal = page.locator("#enclave-confirm-modal:not([hidden])")
    assert modal.count() == 0, "empty canvas must not open the confirm dialog"
    assert not page.evaluate(
        "() => Object.values(window.dfNodeData || {}).some(d => d && d.kind === 'ralph')"
    )


def test_loop_wrap_cancel_leaves_canvas_untouched(signed_in_page):
    """Cancelling the Confirm dialog aborts the restructure entirely."""
    page = signed_in_page
    _wait_canvas(page)
    page.evaluate("() => window.dfAddPatternFromTemplate('llm_step', 320, 200)")
    before = page.evaluate("() => Object.keys(window.dfNodeData || {}).length")
    _click_wrap(page)
    page.wait_for_selector("#enclave-confirm-modal:not([hidden])", timeout=5_000)
    page.click("#enclave-confirm-cancel")
    assert page.evaluate("() => Object.keys(window.dfNodeData || {}).length") == before
    assert not page.evaluate(
        "() => Object.values(window.dfNodeData || {}).some(d => d && d.kind === 'ralph')"
    )


def test_loop_wrap_restructures_and_round_trips(signed_in_page):
    """Two chained llm steps wrap into one ralph parent (body of 2, journal +
    halt pre-filled, output invariant honored), the Safety rails open, and
    the export round-trips the frozen WorkflowDefinition model."""
    page = signed_in_page
    _wait_canvas(page)
    # Two llm steps — dfAutoChain wires seed → a → b on the canvas.
    page.evaluate("() => window.dfAddPatternFromTemplate('llm_step', 320, 200)")
    page.evaluate("() => window.dfAddPatternFromTemplate('llm_step', 620, 200)")
    _click_wrap(page)
    page.wait_for_selector("#enclave-confirm-modal:not([hidden])", timeout=5_000)
    page.click("#enclave-confirm-ok")
    page.wait_for_function(
        "() => Object.values(window.dfNodeData || {})"
        ".some(d => d && d.kind === 'ralph' && d._sub_of == null)",
        timeout=5_000,
    )
    parent = page.evaluate(
        "() => Object.values(window.dfNodeData || {})"
        ".find(d => d && d.kind === 'ralph' && d._sub_of == null)"
    )
    assert parent["id"].startswith("ralph_wrap_")
    assert len(parent["body"]) == 2, "both canvas steps must fold into the body"
    assert parent["ralph"]["journal_path"], "journal_path must be pre-filled"
    halt = parent["ralph"]["halt"]
    for cap in (
        "max_iterations",
        "max_wall_seconds",
        "max_total_tokens",
        "max_consecutive_failures",
    ):
        assert halt.get(cap, 0) >= 1, f"halt budget {cap} must be pre-filled"
    # goal_gate stays empty — the wrapped body has no verify step to gate on.
    assert not halt.get("goal_gate")
    # Ralph output invariant: every parent output produced by SOME body step.
    produced = {o for b in parent["body"] for o in b.get("outputs", [])}
    assert set(parent["outputs"]) <= produced
    # The Safety rails config (BU8a) opened on the new parent.
    page.wait_for_selector("#df-config-popup:not([hidden])", timeout=5_000)
    # inner_text() applies the section header's text-transform:uppercase.
    assert "safety rails" in page.locator("#df-config-popup").inner_text().lower()
    # Round-trip: dfExportYaml → the frozen model IS the validator.
    yaml_text = page.evaluate("() => window.dfExportYaml()")
    defn = WorkflowDefinition(**yaml.safe_load(yaml_text))
    ralph_steps = [s for s in defn.steps if s.kind == "ralph"]
    assert len(ralph_steps) == 1
    assert len(ralph_steps[0].body) == 2
    assert ralph_steps[0].ralph.journal_path
