from __future__ import annotations

from triage.emitters.step_summary import StepSummaryEmitter
from triage.models import FailureEvent, TriageVerdict, Severity, Category


def _v():
    ev = FailureEvent(source="ci", exception_type="AssertionError", message="boom", test_id="t::a")
    return TriageVerdict(event=ev, severity=Severity.medium, category=Category.assertion, rule_summary="regression")


def test_writes_markdown_table(tmp_path):
    path = tmp_path / "summary.md"
    StepSummaryEmitter(path=str(path)).emit([_v()])
    text = path.read_text()
    assert "## " in text and "| Severity |" in text
    assert "`t::a`" in text and "medium" in text


def test_no_path_is_noop(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    StepSummaryEmitter(path=None).emit([_v()])  # must not raise, writes nothing
