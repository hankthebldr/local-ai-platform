from __future__ import annotations

import requests

from ..models import TriageVerdict


class WebhookEmitter:
    def __init__(self, *, url: str, token: str | None = None, timeout: int = 10):
        self.url = url
        self.token = token
        self.timeout = timeout

    def emit(self, verdicts: list[TriageVerdict]) -> None:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        for v in verdicts:
            try:
                requests.post(self.url, json=v.model_dump(mode="json"), headers=headers, timeout=self.timeout)
            except Exception:
                pass  # operator sink unreachable → swallow; caller logs the warning
