from __future__ import annotations

import os

from triage.redact import redact, redact_event
from triage.models import FailureEvent


def test_scrubs_secrets_and_keys():
    text = "key sk-ABCDEF0123456789ABCD and Authorization: Bearer abc.def.ghi and password=hunter2"
    out = redact(text)
    assert "sk-ABCDEF" not in out
    assert "hunter2" not in out
    assert "Bearer abc.def.ghi" not in out


def test_scrubs_email_pii():
    assert "henry@example.com" not in redact("contact henry@example.com")


def test_rewrites_home_path():
    home = os.path.expanduser("~")
    out = redact(f"opened {home}/.ssh/id_rsa")
    assert home not in out and "~/.ssh" in out


def test_redact_event_scrubs_message_and_traceback():
    ev = FailureEvent(
        source="runtime",
        exception_type="ValueError",
        message="token=sk-AAAAAAAAAAAAAAAA",
        traceback="password=hunter2",
    )
    out = redact_event(ev)
    assert "sk-AAAA" not in out.message
    assert "hunter2" not in (out.traceback or "")
