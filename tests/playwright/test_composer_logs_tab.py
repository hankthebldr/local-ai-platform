"""BU6 — Logs workstream tab.

The Composer's bottom workstream strip gains a 4th tab (Logs) that renders
per-step I/O for the active run: rendered prompts in, workspace output out,
plus a metadata-only strategy strip (MCP calls / plugin tools / skills).
The tab is Actions-wired (data-action="ws.switch") — no inline onclick.

The step-section assertions are conditional on a completed run with step
results existing under data/workflows (queried via the API) so the test
stays hermetic on a fresh install.
"""

from __future__ import annotations

LOGS_TAB = '.workstream-tab[data-ws="logs"]'


def _prime_composer(page):
    """Reveal the canvas surface — the workstream strip lives inside the
    composer split, which is dormant until primed (chat-led redesign)."""
    page.wait_for_function("() => typeof ComposerSplit !== 'undefined'", timeout=10_000)
    page.evaluate("ComposerSplit.setSpinePrimed(true)")
    page.wait_for_selector(".composer-grid", state="visible", timeout=10_000)


def test_logs_tab_exists_and_shows_empty_state(signed_in_page, no_console_errors):
    """The Logs tab is present, Actions-wired (no inline onclick), and
    switching to it on a fresh page shows the no-run-yet empty state
    without console errors."""
    page = signed_in_page
    _prime_composer(page)
    tab = page.locator(LOGS_TAB)
    assert tab.count() == 1, "Logs workstream tab missing"
    assert tab.get_attribute("data-action") == "ws.switch"
    assert tab.get_attribute("onclick") is None, "Logs tab must not use inline onclick"
    tab.click()
    page.wait_for_selector("#ws-pane-logs:not([hidden])", timeout=5_000)
    assert "active" in (tab.get_attribute("class") or "")
    # No run recorded on a fresh page → the empty state invites a run.
    page.wait_for_function(
        "() => document.getElementById('ws-logs-body')"
        ".textContent.includes('Run the workflow to see per-step logs')",
        timeout=5_000,
    )
    # The other panes hid: exactly one visible ws-pane.
    assert page.locator("#ws-pane-step").get_attribute("hidden") is not None


def test_logs_tab_renders_step_sections_for_completed_run(signed_in_page):
    """If a completed run with step results exists on disk, seeding it as
    the active run and switching to Logs renders one section per step with
    Input / Output blocks. Skips (passes trivially) when no such run
    exists — fresh installs have no run history."""
    page = signed_in_page
    _prime_composer(page)
    # Find a completed run that actually carries step_results, via the
    # SPA's own authed fetch wrapper.
    run = page.evaluate(
        """async () => {
            const r = await fetch('/api/workflows/runs?limit=25');
            if (!r.ok) return null;
            const list = await r.json();
            const rows = Array.isArray(list) ? list : (list && list.runs) || [];
            for (const row of rows) {
                if (row.status !== 'completed' || !row.run_id) continue;
                const d = await fetch('/api/workflows/runs/' + encodeURIComponent(row.run_id));
                if (!d.ok) continue;
                const full = await d.json();
                if ((full.step_results || []).length) return full;
            }
            return null;
        }"""
    )
    if not run:
        return  # hermetic: no completed run on this install — nothing to assert
    # Seed it as the active run the same way a live run does, then switch.
    page.evaluate(
        "(r) => window.ComposerWorkstream.recordRun({ run_id: r.run_id, status: r.status })",
        run,
    )
    page.click(LOGS_TAB)
    page.wait_for_selector("#ws-pane-logs .ws-log-step", timeout=10_000)
    sections = page.locator("#ws-pane-logs .ws-log-step")
    assert sections.count() == len(run["step_results"])
    body_text = page.locator("#ws-logs-body").inner_text()
    for s in run["step_results"]:
        assert s["step_id"] in body_text
    # Every step shows an Input block — the rendered prompt when captured,
    # the explicit fallback otherwise.
    first = run["step_results"][0]
    if not (first.get("rendered_prompt") or first.get("rendered_system_prompt")):
        assert "prompt not captured" in body_text
    # Labels render text-transform:uppercase, so match case-insensitively.
    assert "input" in body_text.lower() and "output" in body_text.lower()
    # Meta chip reflects the step count.
    assert str(len(run["step_results"])) in page.locator("#ws-logs-meta").inner_text()
    # Click-to-expand: toggling a captured block flips its arrow (the pane
    # re-renders, so re-locate by the stable data-log-key).
    toggles = page.locator('#ws-pane-logs [data-action="wslogs.output-toggle"]')
    assert toggles.count() >= 1, "no expandable Input/Output block rendered"
    key = toggles.first.get_attribute("data-log-key")
    assert toggles.first.inner_text().startswith("▸")
    toggles.first.click()
    page.wait_for_function(
        """(key) => {
            const btn = document.querySelector(
                '#ws-pane-logs [data-log-key=' + JSON.stringify(key) + ']');
            return btn && btn.textContent.trim().startsWith('▾');
        }""",
        arg=key,
        timeout=5_000,
    )
