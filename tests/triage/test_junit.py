from __future__ import annotations

from pathlib import Path

from triage.collectors.junit import parse_junit

FIX = Path(__file__).parent.parent / "fixtures" / "junit"


def test_parse_single_failure():
    events, total = parse_junit(str(FIX / "single_failure.xml"), repo_root="/repo")
    assert total == 3
    assert len(events) == 1
    ev = events[0]
    assert ev.source == "ci"
    assert ev.exception_type == "AssertionError"
    assert ev.test_id == "tests.unit.test_math::test_divide"
    assert ev.file == "tests/unit/test_math.py" and ev.line == 12
    assert ev.fingerprint  # populated


def test_parse_pass_yields_no_events():
    events, total = parse_junit(str(FIX / "pass.xml"))
    assert events == [] and total == 2


def test_parse_mass_failure():
    events, total = parse_junit(str(FIX / "mass_failure.xml"))
    assert total == 5 and len(events) == 4


def test_parse_real_pytest_assertion_without_type_attr():
    # Real pytest emits assertion failures with NO `type` attr; the exception
    # type + file + line live in the "path:line: ExceptionType" tail, not in a
    # standard `File "...", line N` frame. Regression for the smoke-test finding.
    events, total = parse_junit(str(FIX / "real_assertion.xml"), repo_root="/repo")
    assert total == 1 and len(events) == 1
    ev = events[0]
    assert ev.exception_type == "AssertionError"  # NOT "2" parsed from the message
    assert ev.file == "tests/unit/test_real.py" and ev.line == 2
