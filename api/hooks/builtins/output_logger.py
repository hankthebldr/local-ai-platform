"""
output_logger hook — appends per-step execution records to a JSONL file.

Stage: after_step.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from api.services.hook_bus import HookContext, HookResult


@dataclass
class OutputLoggerHook:
    log_path: str | Path = "data/logs/workflow_runs.jsonl"
    include_prompt: bool = False

    name: str = "output_logger"
    stage: str = "after_step"

    def __call__(self, ctx: HookContext) -> HookResult:
        path = Path(self.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        record: dict = {
            "ts": datetime.utcnow().isoformat(),
            "run_id": getattr(ctx.workflow, "run_id", None),
            "step_id": getattr(ctx.step, "id", None),
            "attempt": ctx.attempt,
            "raw_output": ctx.output,
            "parsed": ctx.parsed,
        }
        if self.include_prompt and ctx.prompt is not None:
            record["prompt"] = {
                "system": ctx.prompt.system,
                "user": ctx.prompt.user,
                "params": ctx.prompt.params,
            }

        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        return HookResult(action="continue")
