"""CH-1 static-markup regressions — NextActions strip + round-trip pivots.

Coarse invariants (no browser): the mounts exist, the pivots are wired via
data-action (no new inline handlers), the live serializer + resume-from-failed
seams are present in the served JS corpus, and the new symbols are bridged onto
window so nothing silently no-ops under ES modules.
"""

from __future__ import annotations

import re


def test_next_actions_strip_mount_exists(index_soup):
    strip = index_soup.find(id="next-actions-strip")
    assert strip is not None, "NextActions strip mount missing"
    # Hidden until an event fills it (persist-until-next-event).
    assert strip.has_attr("hidden")


def test_last_run_chip_mount_exists(index_soup):
    chip = index_soup.find(id="composer-last-run-chip")
    assert chip is not None, "last-run health chip mount missing"
    assert chip.has_attr("hidden")


def test_run_progress_chip_opens_active_run(index_soup):
    chip = index_soup.find(id="df-run-progress")
    assert chip is not None
    assert chip.get("data-action") == "composer.open-active-run", (
        "floating run chip must re-open the active run via data-action"
    )


def test_fix_failing_step_button_is_delegated(index_soup):
    btn = index_soup.find(id="runs-tab-fix-btn")
    assert btn is not None, "Fix-failing-step button missing from runs toolbar"
    # No new inline handler — must go through the Actions registry.
    assert not btn.has_attr("onclick"), "Fix button must not use an inline onclick"
    assert btn.get("data-action") == "runs.open-in-composer"


def test_run_live_tooltip_no_longer_claims_save(index_html_text):
    # The old tooltip lied ("Save + run"); Run › live now sends the LIVE canvas
    # with no save. Assert the honest copy replaced the lie.
    m = re.search(r'onclick="dfRunWorkflowLive\(\)"[^>]*title="([^"]+)"', index_html_text)
    assert m, "Run ▶ live button not found"
    assert "no save required" in m.group(1).lower()


def test_live_serializer_and_build_definition_present(index_html_text):
    # The pure serializer + the live-definition builder must both exist so
    # dfRunWorkflowLive sends the canvas the operator is looking at (P0-1).
    assert "function dfComposeYamlString(" in index_html_text
    assert "function dfBuildWorkflowDefinition(" in index_html_text
    # dfExportYaml keeps its panel side-effect (back-compat wrapper).
    assert "function dfExportYaml(" in index_html_text


def test_resume_from_failed_endpoint_referenced(index_html_text):
    assert "resume-from-failed" in index_html_text, (
        "runs-tab resume must target the resume-from-failed endpoint"
    )


def test_next_action_verbs_registered(index_html_text):
    for verb in (
        "next.fix-step", "next.resume", "next.run", "next.save",
        "next.schedule", "next.promote", "ws.history-open",
        "runs.open-in-composer", "composer.open-active-run",
    ):
        assert f"'{verb}'" in index_html_text, f"action verb {verb} not registered"


def test_ch1_symbols_bridged_to_window(index_html_text):
    for sym in (
        "dfBuildWorkflowDefinition", "dfComposeYamlString",
        "dfShowLastRunHealth", "composerOpenActiveRun", "dfFocusStepFromSignal",
    ):
        assert f"window.{sym} = app.{sym}" in index_html_text, (
            f"{sym} not bridged onto window"
        )
