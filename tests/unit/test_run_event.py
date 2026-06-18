from api.models.run_event import RunEvent, EventType


def test_run_event_roundtrips_and_has_core_types():
    ev = RunEvent(
        seq=1,
        run_id="r1",
        ts="2026-06-18T00:00:00Z",
        type=EventType.STEP_STARTED,
        step_id="s1",
        data={"kind": "llm"},
    )
    dumped = ev.model_dump(mode="json")
    assert dumped["seq"] == 1
    assert dumped["type"] == "step.started"
    assert dumped["step_id"] == "s1"
    assert RunEvent.model_validate(dumped).data["kind"] == "llm"
    assert EventType.RUN_STATUS == "run.status"
    assert EventType.PLAN_UPDATED == "plan.updated"
    assert EventType.GATE_PENDING == "gate.pending"
    assert EventType.TOOL_CALLED == "tool.called"
    assert EventType.STREAM_HELLO == "stream.hello"
