from __future__ import annotations

import os
import re

from .models import FailureEvent

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email (PII)
]


def redact(text: str | None, *, extra: list[re.Pattern] | None = None) -> str | None:
    if not text:
        return text
    home = os.path.expanduser("~")
    if home and home != "~":
        text = text.replace(home, "~")
    for rx in _PATTERNS + (extra or []):
        text = rx.sub("[REDACTED]", text)
    return text


def redact_event(event: FailureEvent, *, extra: list[re.Pattern] | None = None) -> FailureEvent:
    return event.model_copy(
        update={
            "message": redact(event.message, extra=extra) or "",
            "traceback": redact(event.traceback, extra=extra),
        }
    )
