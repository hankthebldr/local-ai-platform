"""Tests for WorkflowEventBus — event system for workflow observability"""

import pytest
from api.services.workflow_events import WorkflowEventBus, EventType


class TestEventBus:
    def test_emit_and_handler(self):
        bus = WorkflowEventBus()
        received = []
        bus.on(EventType.STEP_COMPLETED, lambda e: received.append(e))

        bus.emit(EventType.STEP_COMPLETED, run_id="r1", step_id="s1", data={"tokens": 100})

        assert len(received) == 1
        assert received[0].event_type == EventType.STEP_COMPLETED
        assert received[0].step_id == "s1"
        assert received[0].data["tokens"] == 100

    def test_global_handler(self):
        bus = WorkflowEventBus()
        received = []
        bus.on_all(lambda e: received.append(e.event_type))

        bus.emit(EventType.WORKFLOW_STARTED, run_id="r1")
        bus.emit(EventType.STEP_STARTED, run_id="r1", step_id="s1")

        assert len(received) == 2
        assert EventType.WORKFLOW_STARTED in received
        assert EventType.STEP_STARTED in received

    def test_no_handler_no_error(self):
        bus = WorkflowEventBus()
        # Should not raise even with no handlers
        event = bus.emit("custom.event", run_id="r1")
        assert event.event_type == "custom.event"

    def test_handler_exception_caught(self):
        bus = WorkflowEventBus()
        bus.on(EventType.STEP_FAILED, lambda e: 1 / 0)  # Will raise ZeroDivisionError

        # Should not propagate the exception
        event = bus.emit(EventType.STEP_FAILED, run_id="r1", step_id="s1")
        assert event is not None

    def test_history(self):
        bus = WorkflowEventBus()
        bus.emit(EventType.WORKFLOW_STARTED, run_id="r1")
        bus.emit(EventType.STEP_STARTED, run_id="r1", step_id="s1")
        bus.emit(EventType.STEP_COMPLETED, run_id="r1", step_id="s1")

        history = bus.get_history(run_id="r1")
        assert len(history) == 3

    def test_history_filter_by_type(self):
        bus = WorkflowEventBus()
        bus.emit(EventType.STEP_STARTED, run_id="r1", step_id="s1")
        bus.emit(EventType.STEP_COMPLETED, run_id="r1", step_id="s1")
        bus.emit(EventType.STEP_STARTED, run_id="r1", step_id="s2")

        started = bus.get_history(event_type=EventType.STEP_STARTED)
        assert len(started) == 2

    def test_step_events(self):
        bus = WorkflowEventBus()
        bus.emit(EventType.STEP_STARTED, run_id="r1", step_id="s1")
        bus.emit(EventType.STEP_COMPLETED, run_id="r1", step_id="s1")
        bus.emit(EventType.STEP_STARTED, run_id="r1", step_id="s2")

        s1_events = bus.get_step_events("r1", "s1")
        assert len(s1_events) == 2

    def test_unsubscribe(self):
        bus = WorkflowEventBus()
        received = []
        handler = lambda e: received.append(e)
        bus.on(EventType.STEP_COMPLETED, handler)

        bus.emit(EventType.STEP_COMPLETED, run_id="r1")
        assert len(received) == 1

        bus.off(EventType.STEP_COMPLETED, handler)
        bus.emit(EventType.STEP_COMPLETED, run_id="r1")
        assert len(received) == 1  # No new event

    def test_clear_history(self):
        bus = WorkflowEventBus()
        bus.emit(EventType.WORKFLOW_STARTED, run_id="r1")
        assert bus.history_size > 0
        bus.clear_history()
        assert bus.history_size == 0

    def test_max_history(self):
        bus = WorkflowEventBus(max_history=5)
        for i in range(10):
            bus.emit("test", run_id=f"r{i}")
        assert bus.history_size == 5

    def test_multiple_handlers_same_event(self):
        bus = WorkflowEventBus()
        results = []
        bus.on(EventType.STEP_COMPLETED, lambda e: results.append("a"))
        bus.on(EventType.STEP_COMPLETED, lambda e: results.append("b"))

        bus.emit(EventType.STEP_COMPLETED, run_id="r1")
        assert results == ["a", "b"]
