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
