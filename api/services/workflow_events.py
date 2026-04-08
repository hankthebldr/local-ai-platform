"""
Workflow Event System — Observable execution with typed events

Provides a publish/subscribe event bus for workflow execution.
Consumers can subscribe to specific event types to build:
- Real-time progress tracking (WebSocket/SSE)
- Execution logging and audit trails
- Metrics and observability
- Webhook notifications
"""

from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ..logging_config import logger
from ..models.workflow_models import WorkflowEvent


# ── Event Types ───────────────────────────────────────────────────────────

class EventType:
    """Standard event type constants"""
    # Workflow lifecycle
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_PAUSED = "workflow.paused"
    WORKFLOW_RESUMED = "workflow.resumed"
    WORKFLOW_CANCELLED = "workflow.cancelled"

    # Batch lifecycle
    BATCH_STARTED = "batch.started"
    BATCH_COMPLETED = "batch.completed"

    # Step lifecycle
    STEP_QUEUED = "step.queued"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    STEP_SKIPPED = "step.skipped"
    STEP_RETRYING = "step.retrying"

    # Quality gates
    GATE_PASSED = "gate.passed"
    GATE_FAILED = "gate.failed"
    GATE_WARNING = "gate.warning"

    # Context
    CONTEXT_UPDATED = "context.updated"
    CHECKPOINT_CREATED = "checkpoint.created"

    # Model
    MODEL_RESOLVED = "model.resolved"
    MODEL_FALLBACK = "model.fallback"


# Type alias for event handlers
EventHandler = Callable[[WorkflowEvent], None]


class WorkflowEventBus:
    """
    Publish/subscribe event bus for workflow execution events.

    Supports both sync and async handlers. Events are dispatched
    to all matching subscribers in registration order.
    """

    def __init__(self, max_history: int = 1000):
        self._handlers: Dict[str, List[EventHandler]] = defaultdict(list)
        self._global_handlers: List[EventHandler] = []
        self._history: deque[WorkflowEvent] = deque(maxlen=max_history)

    # ── Subscribe ─────────────────────────────────────────────────────────

    def on(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe a sync handler to a specific event type"""
        self._handlers[event_type].append(handler)

    def on_all(self, handler: EventHandler) -> None:
        """Subscribe a sync handler to ALL events"""
        self._global_handlers.append(handler)

    def off(self, event_type: str, handler: EventHandler) -> None:
        """Unsubscribe a handler from an event type"""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h != handler
            ]

    # ── Publish ───────────────────────────────────────────────────────────

    def emit(
        self,
        event_type: str,
        run_id: str,
        step_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> WorkflowEvent:
        """
        Emit an event to all subscribers.

        Creates a WorkflowEvent, dispatches to handlers, and stores in history.
        """
        event = WorkflowEvent(
            event_type=event_type,
            run_id=run_id,
            step_id=step_id,
            timestamp=datetime.utcnow(),
            data=data or {},
        )

        # Store in history (deque auto-evicts oldest when full)
        self._history.append(event)

        # Dispatch to type-specific handlers
        for handler in self._handlers.get(event_type, []):
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler error ({event_type}): {e}")

        # Dispatch to global handlers
        for handler in self._global_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Global event handler error: {e}")

        return event

    # ── Query ─────────────────────────────────────────────────────────────

    def get_history(
        self,
        run_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[WorkflowEvent]:
        """Query event history with optional filters"""
        events = list(self._history)
        if run_id:
            events = [e for e in events if e.run_id == run_id]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-limit:]

    def get_step_events(self, run_id: str, step_id: str) -> List[WorkflowEvent]:
        """Get all events for a specific step in a run"""
        return [
            e for e in self._history
            if e.run_id == run_id and e.step_id == step_id
        ]

    def clear_history(self) -> None:
        """Clear event history"""
        self._history.clear()

    @property
    def history_size(self) -> int:
        return len(self._history)


# ── Built-in Event Handlers ──────────────────────────────────────────────


def logging_handler(event: WorkflowEvent) -> None:
    """Default handler that logs all events"""
    step_info = f" step={event.step_id}" if event.step_id else ""
    data_summary = ""
    if event.data:
        # Summarize data without dumping huge outputs
        keys = list(event.data.keys())[:5]
        data_summary = f" keys={keys}"

    logger.info(
        f"[EVENT] {event.event_type} run={event.run_id[:12]}{step_info}{data_summary}"
    )


def metrics_handler(event: WorkflowEvent) -> None:
    """Handler that tracks execution metrics (token counts, durations)"""
    if event.event_type == EventType.STEP_COMPLETED:
        duration = event.data.get("duration_seconds", 0)
        tokens = event.data.get("total_tokens", 0)
        model = event.data.get("model", "unknown")
        logger.info(
            f"[METRICS] step={event.step_id} model={model} "
            f"duration={duration:.1f}s tokens={tokens}"
        )
    elif event.event_type == EventType.WORKFLOW_COMPLETED:
        total_duration = event.data.get("total_duration", 0)
        total_tokens = event.data.get("total_tokens", 0)
        logger.info(
            f"[METRICS] workflow completed duration={total_duration:.1f}s "
            f"tokens={total_tokens}"
        )
