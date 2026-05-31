from __future__ import annotations

import os

from ..models import TriageVerdict


class StepSummaryEmitter:
    def __init__(self, path: str | None = None):
        self.path = path if path is not None else os.getenv("GITHUB_STEP_SUMMARY")

    def emit(self, verdicts: list[TriageVerdict]) -> None:
        if not self.path:
            return
        lines = ["## 🔎 Triage summary", "", "| Severity | Category | Test / Route | Summary |", "|---|---|---|---|"]
        if not verdicts:
            lines.append("| — | — | — | No failures 🎉 |")
        for v in verdicts:
            loc = v.event.test_id or v.event.route or "—"
            lines.append(f"| {v.severity.value} | {v.category.value} | `{loc}` | {v.rule_summary} |")
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
