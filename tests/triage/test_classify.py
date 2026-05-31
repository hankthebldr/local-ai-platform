from __future__ import annotations

import pytest

from triage.classify import classify
from triage.models import FailureEvent, Severity, Category


def _ev(etype, msg="", source="ci", route=None):
    return FailureEvent(source=source, exception_type=etype, message=msg, route=route)


@pytest.mark.parametrize(
    "etype,msg,sev,cat",
    [
        (
            "OllamaConnectionError",
            "connection refused",
            Severity.high,
            Category.connection,
        ),
        ("AssertionError", "assert 1 == 2", Severity.medium, Category.assertion),
        (
            "ModuleNotFoundError",
            "No module named 'api.services.x'",
            Severity.critical,
            Category.import_error,
        ),
        (
            "ModuleNotFoundError",
            "No module named 'thirdparty'",
            Severity.high,
            Category.import_error,
        ),
        ("TimeoutError", "timed out", Severity.low, Category.timeout),
    ],
)
def test_classify_rules(etype, msg, sev, cat):
    s, c, _summary = classify(_ev(etype, msg))
    assert (s, c) == (sev, cat)


def test_mass_failure_escalates_to_critical():
    s, c, _ = classify(_ev("AssertionError", "x"), total=10, failed=8)
    assert s == Severity.critical and c == Category.import_error


def test_runtime_unhandled_default():
    s, c, _ = classify(
        _ev("RuntimeError", "boom", source="runtime", route="POST /v1/chat")
    )
    assert s == Severity.high and c == Category.unhandled
