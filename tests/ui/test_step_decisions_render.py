"""Static-markup regression for the Runs per-step decisions panel.

_renderStepDecisions surfaces the skills / MCP / tool invocations (and the
timing/pressure KV grid) the engine persists per step. Shipped with no test;
this pins the chip taxonomy + the honest 'pure LLM turn' fallback.
"""


def test_render_step_decisions_defined(index_html_text):
    assert "function _renderStepDecisions(" in index_html_text


def test_decision_chip_classes_present(index_html_text):
    for cls in (
        ".run-decision-chips",
        ".run-decision-chip",
        ".run-decision-chip.skill",
        ".run-decision-chip.mcp",
        ".run-decision-chip.tool",
        ".run-decision-chip.none",
    ):
        assert cls in index_html_text, f"CSS rule {cls} missing"


def test_decisions_read_the_three_telemetry_arrays(index_html_text):
    for field in ("skills_activated", "mcp_calls", "plugin_tools_called"):
        assert field in index_html_text, f"telemetry field {field} not read"


def test_decisions_have_honest_empty_fallback(index_html_text):
    # No invocation must render the explicit pure-LLM-turn chip, not nothing.
    assert "run-decision-chip none" in index_html_text
    assert "no skills / MCP / tools invoked" in index_html_text


def test_decisions_panel_wired_into_run_step_render(index_html_text):
    # The panel is actually invoked from the per-step render path.
    assert "_renderStepDecisions(s)" in index_html_text
