"""Static-markup regression for the Run lens.

A new view over EXISTING run telemetry: scrub timeline, per-step timing plates,
and an as-executed inspector (rendered system prompt / prompt / output as they
ran). Pins the markup, the launcher, and that it reads real persisted step
telemetry fields without new backend.
"""


def test_run_lens_markup_present(index_soup):
    assert index_soup.find(id="rl-backdrop") is not None, "run-lens modal missing"
    assert index_soup.find(id="rl-scrub") is not None, "scrub timeline missing"
    assert index_soup.find(id="rl-plates") is not None, "timing plates missing"
    assert index_soup.find(id="rl-inspect") is not None, "as-executed inspector missing"
    assert index_soup.find(id="runs-tab-lens-btn") is not None, "lens launcher missing"


def test_run_lens_module_present(index_html_text):
    assert "window.RunLens" in index_html_text
    assert 'id="enclave-runlens-js"' in index_html_text
    assert 'id="enclave-runlens-styles"' in index_html_text
    assert "RunLens.open()" in index_html_text  # launcher wiring


def test_run_lens_reads_existing_run_telemetry(index_html_text):
    # Opens the current run (or fetches one) — no new backend.
    assert "window._lastRunSummary" in index_html_text
    assert "/api/workflows/runs/" in index_html_text
    assert "step_results" in index_html_text


def test_as_executed_inspector_shows_recorded_prompts_and_output(index_html_text):
    # The honest "as it ran" panels.
    assert "rendered_system_prompt" in index_html_text
    assert "rendered_prompt" in index_html_text
    assert "as executed" in index_html_text
    assert "context.workspace" in index_html_text  # actual step output source


def test_scrub_segments_sized_by_duration(index_html_text):
    # Timeline segments scale to each step's real duration.
    assert "duration_seconds" in index_html_text
    assert "rl-seg" in index_html_text
    assert "RunLens.select(" in index_html_text  # click a segment → inspect
