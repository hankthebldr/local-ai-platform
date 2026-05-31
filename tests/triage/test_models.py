from __future__ import annotations

from triage.models import FailureEvent, TriageVerdict, Severity, Category


def test_failure_event_defaults():
    ev = FailureEvent(source="ci", exception_type="AssertionError", message="boom")
    assert ev.fingerprint == ""
    assert ev.env == {}
    assert ev.traceback is None


def test_triage_verdict_roundtrip():
    ev = FailureEvent(source="runtime", exception_type="ValueError", message="bad")
    v = TriageVerdict(
        event=ev, severity=Severity.high, category=Category.unhandled, rule_summary="x"
    )
    assert v.seen_count == 1
    assert v.enriched is False
    assert v.model_dump(mode="json")["severity"] == "high"
