from __future__ import annotations

from unittest.mock import patch

from triage.config import TriageConfig
from triage.reporting import report, _sink
from triage.models import FailureEvent, TriageVerdict, Severity, Category


def _cfg(**kw):
    base = dict(
        enabled=True,
        sink="webhook",
        sink_url="https://s/in",
        sink_token=None,
        vendor=False,
        vendor_url=None,
        enrich=False,
        ollama_url="http://x",
        ollama_model="m",
        redact=True,
    )
    base.update(kw)
    return TriageConfig(**base)


def _v():
    ev = FailureEvent(source="runtime", exception_type="ValueError", message="x")
    return TriageVerdict(
        event=ev, severity=Severity.high, category=Category.unhandled, rule_summary="x"
    )


def test_sink_selection_webhook():
    assert _sink(_cfg()).__class__.__name__ == "WebhookEmitter"


def test_sink_none_returns_none():
    assert _sink(_cfg(sink="none", sink_url=None)) is None


def test_report_emits_to_sink():
    with patch("triage.reporting.WebhookEmitter") as We:
        report(_v(), _cfg())
        We.return_value.emit.assert_called_once()
