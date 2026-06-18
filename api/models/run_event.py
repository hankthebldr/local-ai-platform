"""Run event envelope + taxonomy (v1). One event = one append-only log line."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EventType:
    """v1 event-type string constants. Mirrors OpenCode session.status / todo.updated / permission.asked."""

    STREAM_HELLO = "stream.hello"
    STREAM_RESYNC = "stream.resync"
    STREAM_END = "stream.end"
    RUN_STATUS = "run.status"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    PLAN_UPDATED = "plan.updated"
    GATE_PENDING = "gate.pending"
    GATE_RESOLVED = "gate.resolved"
    TOOL_CALLED = "tool.called"
    TOKEN_DELTA = "token.delta"  # defined for forward-compat; not emitted in v1
    LOG = "log"


class RunEvent(BaseModel):
    """A single run event. `seq` is monotonic per run (used as SSE Last-Event-ID)."""

    seq: int
    run_id: str
    ts: str  # ISO-8601 UTC
    type: str
    step_id: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
