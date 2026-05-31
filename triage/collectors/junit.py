from __future__ import annotations

import platform

import defusedxml.ElementTree as ET  # XXE + billion-laughs hardened (drop-in for xml.etree)

from ..fingerprint import app_frames, fingerprint_event
from ..models import FailureEvent


def _etype_from_message(message: str) -> str:
    head = (message or "").strip().split(":", 1)[0]
    return head.split()[-1] if head else "Failure"


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
        etype = node.get("type") or _etype_from_message(message)
        ev = FailureEvent(
            source="ci",
            exception_type=etype,
            message=(message.splitlines()[0][:300] if message else etype),
            traceback=tb,
            test_id=test_id,
            env=dict(env),
        )
        frames = app_frames(tb, repo_root)
        if frames:
            ev.file, ev.line, ev.func = frames[-1]
        ev.fingerprint = fingerprint_event(ev, repo_root=repo_root)
        events.append(ev)
    return events, total
