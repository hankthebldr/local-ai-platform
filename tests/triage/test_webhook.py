from __future__ import annotations

from unittest.mock import patch

from triage.emitters.webhook import WebhookEmitter
from triage.models import FailureEvent, TriageVerdict, Severity, Category


def _v():
    ev = FailureEvent(
        source="runtime", exception_type="ValueError", message="bad", route="POST /x"
    )
    return TriageVerdict(
        event=ev, severity=Severity.high, category=Category.unhandled, rule_summary="x"
    )


def test_posts_json_with_token():
    with patch("triage.emitters.webhook.requests.post") as post:
        WebhookEmitter(url="https://sink/in", token="t").emit([_v()])
        args, kwargs = post.call_args
        assert args[0] == "https://sink/in"
        assert kwargs["headers"]["Authorization"] == "Bearer t"
        assert kwargs["json"]["severity"] == "high"


def test_unreachable_sink_is_swallowed():
    with patch("triage.emitters.webhook.requests.post", side_effect=Exception("down")):
        WebhookEmitter(url="https://sink/in").emit([_v()])  # must not raise
