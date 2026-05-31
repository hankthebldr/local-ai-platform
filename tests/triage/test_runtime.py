from __future__ import annotations

from triage.collectors.runtime import from_exception


def test_from_exception_builds_redacted_event():
    try:
        raise ValueError("token=sk-AAAAAAAAAAAAAAAA")
    except ValueError as exc:
        ev = from_exception(
            exc, route="POST /v1/chat", request_id="r1", enclave_version="1.1.1"
        )
    assert ev.source == "runtime"
    assert ev.exception_type == "ValueError"
    assert ev.route == "POST /v1/chat" and ev.request_id == "r1"
    assert ev.fingerprint
    assert ev.occurred_at
    assert "sk-AAAA" not in ev.message  # redacted
