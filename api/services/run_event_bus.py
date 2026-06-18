"""In-process run event bus: append-only per-run log + (later) async fan-out.

Source of truth is data/workflows/<run_id>/events.jsonl. publish() is sync and
thread-safe so the synchronous, threaded WorkflowEngine can call it from worker
threads; it works headless (log-only) when no event loop is bound.
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models.run_event import RunEvent

RUNS_DIR = os.getenv("ENCLAVE_RUNS_DIR", "./data/workflows")


class RunEventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq: Dict[str, int] = {}

    def _log_path(self, run_id: str) -> Path:
        return Path(RUNS_DIR) / run_id / "events.jsonl"

    def _next_seq(self, run_id: str) -> int:
        # caller holds self._lock
        nxt = self._seq.get(run_id)
        if nxt is None:
            existing = self.read_log(run_id)
            nxt = existing[-1].seq if existing else 0
        nxt += 1
        self._seq[run_id] = nxt
        return nxt

    def publish(
        self,
        run_id: str,
        type: str,
        data: Optional[Dict[str, Any]] = None,
        step_id: Optional[str] = None,
    ) -> RunEvent:
        with self._lock:
            seq = self._next_seq(run_id)
            event = RunEvent(
                seq=seq,
                run_id=run_id,
                ts=datetime.utcnow().isoformat() + "Z",
                type=type,
                step_id=step_id,
                data=data or {},
            )
            self._append(event)
        return event

    def _append(self, event: RunEvent) -> None:
        path = self._log_path(event.run_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a") as f:
                f.write(json.dumps(event.model_dump(mode="json")) + "\n")
        except OSError:
            # Observability must never crash a run.
            pass

    def read_log(self, run_id: str, since: int = 0) -> List[RunEvent]:
        """Return logged events with seq > `since` (since is exclusive)."""
        path = self._log_path(run_id)
        if not path.exists():
            return []
        out: List[RunEvent] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ev = RunEvent.model_validate(json.loads(line))
                if ev.seq > since:
                    out.append(ev)
        return out


_BUS: Optional[RunEventBus] = None


def get_run_event_bus() -> RunEventBus:
    global _BUS
    if _BUS is None:
        _BUS = RunEventBus()
    return _BUS
