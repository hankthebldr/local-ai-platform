from __future__ import annotations

import traceback as tb_mod
from datetime import datetime, timezone

from ..fingerprint import app_frames, fingerprint_event
from ..models import FailureEvent
from ..redact import redact_event


def from_exception(
    exc: BaseException,
    *,
    route: str | None = None,
    request_id: str | None = None,
    enclave_version: str = "unknown",
    repo_root: str = "",
) -> FailureEvent:
    tb = "".join(tb_mod.format_exception(type(exc), exc, exc.__traceback__))
    ev = FailureEvent(
        source="runtime",
        exception_type=type(exc).__name__,
        message=(str(exc)[:300] or type(exc).__name__),
        traceback=tb,
        route=route,
        request_id=request_id,
        occurred_at=datetime.now(timezone.utc).isoformat(),
        env={"enclave_version": enclave_version},
    )
    frames = app_frames(tb, repo_root)
    if frames:
        ev.file, ev.line, ev.func = frames[-1]
    ev.fingerprint = fingerprint_event(ev, repo_root=repo_root)
    return redact_event(ev)
