from __future__ import annotations

from triage.emitters.annotations import AnnotationEmitter
from triage.models import FailureEvent, TriageVerdict, Severity, Category


def _v(sev, file=None, line=None):
    ev = FailureEvent(
        source="ci",
        exception_type="AssertionError",
        message="boom",
        file=file,
        line=line,
    )
    return TriageVerdict(
        event=ev, severity=sev, category=Category.assertion, rule_summary="regression"
    )


def test_error_annotation_with_location(capsys):
    AnnotationEmitter().emit([_v(Severity.high, file="api/x.py", line=12)])
    out = capsys.readouterr().out
    assert out.startswith("::error ")
    assert "file=api/x.py,line=12" in out
    assert "title=high: assertion" in out


def test_low_severity_is_warning(capsys):
    AnnotationEmitter().emit([_v(Severity.low)])
    assert capsys.readouterr().out.startswith("::warning")
