from __future__ import annotations

from unittest.mock import patch

from triage.enrich import enrich
from triage.models import FailureEvent, TriageVerdict, Severity, Category


def _v():
    ev = FailureEvent(
        source="runtime", exception_type="ValueError", message="bad", traceback="..."
    )
    return TriageVerdict(
        event=ev, severity=Severity.high, category=Category.unhandled, rule_summary="x"
    )


def test_enrich_parses_two_lines():
    fake = {
        "response": "LIKELY CAUSE: a null value\nFIRST CHECK: inspect the request body"
    }
    with patch("triage.enrich.requests.post") as post:
        post.return_value.json.return_value = fake
        post.return_value.raise_for_status.return_value = None
        out = enrich(_v(), url="http://x", model="m")
    assert out.enriched is True
    assert out.likely_cause == "a null value"
    assert out.first_check == "inspect the request body"


def test_enrich_degrades_silently_on_error():
    with patch(
        "triage.enrich.requests.post", side_effect=Exception("connection refused")
    ):
        out = enrich(_v(), url="http://x", model="m")
    assert out.enriched is False and out.likely_cause is None
