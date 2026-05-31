from __future__ import annotations

import requests

from .models import TriageVerdict

_PROMPT = """You are triaging a software failure. Be terse and concrete.

Exception: {etype}
Message: {message}
Traceback (tail):
{tb}

Respond in exactly two lines:
LIKELY CAUSE: <one sentence>
FIRST CHECK: <one concrete thing to inspect>"""


def _parse(text: str) -> tuple[str | None, str | None]:
    cause = check = None
    for line in text.splitlines():
        s = line.strip()
        if s.upper().startswith("LIKELY CAUSE:"):
            cause = s.split(":", 1)[1].strip()
        elif s.upper().startswith("FIRST CHECK:"):
            check = s.split(":", 1)[1].strip()
    return cause, check


def enrich(verdict: TriageVerdict, *, url: str, model: str, timeout: int = 60) -> TriageVerdict:
    ev = verdict.event
    prompt = _PROMPT.format(etype=ev.exception_type, message=ev.message, tb=(ev.traceback or "")[-1500:])
    try:
        resp = requests.post(
            f"{url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}},
            timeout=timeout,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "")
    except Exception:
        return verdict  # enriched stays False — graceful degradation
    cause, check = _parse(text)
    return verdict.model_copy(
        update={"likely_cause": cause, "first_check": check, "enriched": bool(cause or check)}
    )
