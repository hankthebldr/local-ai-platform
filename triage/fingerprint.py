from __future__ import annotations

import hashlib
import re

from .models import FailureEvent

_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
_NOISE = [
    re.compile(r"0x[0-9a-fA-F]+"),
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
    re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"),
]


def app_frames(traceback: str | None, repo_root: str = "") -> list[tuple[str, int, str]]:
    """Return (relpath, line, func) for frames inside the repo; skip stdlib/site-packages."""
    out: list[tuple[str, int, str]] = []
    for path, line, func in _FRAME_RE.findall(traceback or ""):
        if "/site-packages/" in path or "/lib/python" in path:
            continue
        rel = path
        if repo_root and path.startswith(repo_root):
            rel = path[len(repo_root):].lstrip("/")
        out.append((rel, int(line), func))
    return out


def _scrub(text: str) -> str:
    for rx in _NOISE:
        text = rx.sub("", text)
    return text


def compute(*, source: str, exception_type: str, location: str) -> str:
    basis = _scrub(f"{source}|{exception_type}|{location}")
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def fingerprint_event(event: FailureEvent, repo_root: str = "") -> str:
    frames = app_frames(event.traceback, repo_root)
    sigs = [f"{rel}:{func}" for rel, _line, func in frames]
    if event.source == "ci":
        location = event.test_id or (sigs[-1] if sigs else (event.func or ""))
    else:
        location = (event.route or "") + "|" + "|".join(sigs[:3])
    return compute(source=event.source, exception_type=event.exception_type, location=location)
