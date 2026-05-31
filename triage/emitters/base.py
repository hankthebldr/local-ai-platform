from __future__ import annotations

from typing import Protocol

from ..models import TriageVerdict


class Emitter(Protocol):
    def emit(self, verdicts: list[TriageVerdict]) -> None: ...
