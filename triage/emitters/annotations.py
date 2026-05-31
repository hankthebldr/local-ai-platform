from __future__ import annotations

from ..models import TriageVerdict, Severity


def _level(sev: Severity) -> str:
    return "warning" if sev == Severity.low else "error"


class AnnotationEmitter:
    def emit(self, verdicts: list[TriageVerdict]) -> None:
        for v in verdicts:
            ev = v.event
            params: list[str] = []
            if ev.file:
                params.append(f"file={ev.file}")
                if ev.line:
                    params.append(f"line={ev.line}")
            params.append(f"title={v.severity.value}: {v.category.value}")
            param_str = ",".join(params)
            msg = f"{v.rule_summary} — {ev.message}"
            print(f"::{_level(v.severity)} {param_str}::{msg}")
