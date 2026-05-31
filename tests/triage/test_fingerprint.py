from __future__ import annotations

from triage.fingerprint import app_frames, fingerprint_event
from triage.models import FailureEvent

TB = """Traceback (most recent call last):
  File "/repo/api/services/foo.py", line 40, in handle
    do_thing()
  File "/usr/lib/python3.12/site-packages/lib/x.py", line 9, in do_thing
    raise ValueError("x")
ValueError: x"""


def test_app_frames_skips_libs_and_normalizes():
    frames = app_frames(TB, repo_root="/repo")
    assert frames == [("api/services/foo.py", 40, "handle")]


def test_fingerprint_stable_across_line_shifts():
    tb_shifted = TB.replace("line 40", "line 57")
    a = FailureEvent(
        source="ci",
        exception_type="ValueError",
        message="x",
        traceback=TB,
        test_id="t::a",
    )
    b = FailureEvent(
        source="ci",
        exception_type="ValueError",
        message="x",
        traceback=tb_shifted,
        test_id="t::a",
    )
    assert fingerprint_event(a, repo_root="/repo") == fingerprint_event(
        b, repo_root="/repo"
    )


def test_fingerprint_differs_on_exception_type():
    a = FailureEvent(
        source="ci",
        exception_type="ValueError",
        message="x",
        traceback=TB,
        test_id="t::a",
    )
    b = FailureEvent(
        source="ci",
        exception_type="KeyError",
        message="x",
        traceback=TB,
        test_id="t::a",
    )
    assert fingerprint_event(a, repo_root="/repo") != fingerprint_event(
        b, repo_root="/repo"
    )
