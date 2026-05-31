from __future__ import annotations

import platform
import re

import defusedxml.ElementTree as ET  # XXE + billion-laughs hardened (drop-in for xml.etree)

from ..fingerprint import app_frames, fingerprint_event
from ..models import FailureEvent

# pytest's assertion-failure form ends with a line like:  path/test_x.py:12: AssertionError
_PYTEST_TAIL = re.compile(r"^(?P<path>.+?):(?P<line>\d+):\s+(?P<etype>[A-Za-z_][\w.]*)\s*$")
# A standard Python traceback's final line is:  ExceptionType: message
_PY_FINAL = re.compile(r"^(?P<etype>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt))\b")


def _relpath(path: str, repo_root: str) -> str:
    if repo_root and path.startswith(repo_root):
        return path[len(repo_root):].lstrip("/")
    return path


def _extract(message: str, tb: str, declared_type: str | None, repo_root: str):
    """Return (etype, file, line). Handles both pytest-assertion output
    (`path:line: Type` tail) and standard Python tracebacks (`File "...", line N`
    frames + final `Type: msg`)."""
    etype = declared_type or None
    file = None
    line = None

    # 1. pytest assertion tail: "path:lineno: ExceptionType" (last match wins)
    for raw in reversed((tb or "").strip().splitlines()):
        m = _PYTEST_TAIL.match(raw.strip())
        if m:
            file = _relpath(m.group("path"), repo_root)
            line = int(m.group("line"))
            etype = etype or m.group("etype")
            break

    # 2. standard `File "x", line N, in func` frames (errors / raised exceptions)
    if file is None:
        frames = app_frames(tb, repo_root)
        if frames:
            file, line, _func = frames[-1]

    # 3. exception type from a standard traceback's final "Type: msg" line
    if etype is None:
        for raw in reversed((tb or "").strip().splitlines()):
            m = _PY_FINAL.match(raw.strip())
            if m:
                etype = m.group("etype")
                break

    # 4. last resort: a "Type: ..." style message attr, else generic
    if etype is None:
        head = (message or "").split(":", 1)[0].strip()
        etype = head if (head and head[0].isupper() and " " not in head) else "Failure"

    return etype, file, line


def parse_junit(path: str, *, repo_root: str = "", enclave_version: str = "unknown") -> tuple[list[FailureEvent], int]:
    root = ET.parse(path).getroot()
    env = {
        "python_version": platform.python_version(),
        "os": platform.system(),
        "enclave_version": enclave_version,
    }
    events: list[FailureEvent] = []
    total = 0
    for tc in root.iter("testcase"):
        total += 1
        node = tc.find("failure")
        if node is None:
            node = tc.find("error")
        if node is None:
            continue
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        test_id = f"{classname}::{name}" if classname else name
        message = node.get("message", "") or ""
        tb = node.text or ""
        etype, file, line = _extract(message, tb, node.get("type"), repo_root)
        ev = FailureEvent(
            source="ci",
            exception_type=etype,
            message=(message.splitlines()[0][:300] if message else etype),
            traceback=tb,
            test_id=test_id,
            file=file,
            line=line,
            env=dict(env),
        )
        ev.fingerprint = fingerprint_event(ev, repo_root=repo_root)
        events.append(ev)
    return events, total
