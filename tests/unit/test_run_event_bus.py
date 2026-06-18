import asyncio

import pytest

import api.services.run_event_bus as reb
from api.models.run_event import EventType


def test_publish_appends_monotonic_seq_and_reads_back(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    bus = reb.RunEventBus()
    e1 = bus.publish("run1", EventType.RUN_STATUS, {"status": "running"})
    e2 = bus.publish("run1", EventType.STEP_STARTED, {"kind": "llm"}, step_id="s1")
    assert (e1.seq, e2.seq) == (1, 2)
    assert e1.run_id == "run1" and e1.ts.endswith("Z")

    log = bus.read_log("run1")
    assert [e.type for e in log] == [EventType.RUN_STATUS, EventType.STEP_STARTED]
    assert bus.read_log("run1", since=1)[0].seq == 2  # since is exclusive


def test_singleton_accessor_is_stable():
    assert reb.get_run_event_bus() is reb.get_run_event_bus()


def test_read_log_skips_corrupt_line(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    bus = reb.RunEventBus()
    bus.publish("rc", EventType.RUN_STATUS, {"status": "running"})
    # inject a corrupt line
    p = bus._log_path("rc")
    with open(p, "a") as f:
        f.write("{not valid json}\n")
    bus2 = reb.RunEventBus()  # fresh, no seq cache
    log = bus2.read_log("rc")
    assert [e.type for e in log] == [EventType.RUN_STATUS]  # corrupt line skipped


def test_read_log_skips_wrong_shape_line(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    bus = reb.RunEventBus()
    bus.publish("rs", EventType.RUN_STATUS, {"status": "running"})
    p = bus._log_path("rs")
    with open(p, "a") as f:
        f.write('{"valid_json": true, "but": "wrong shape, no seq"}\n')
    fresh = reb.RunEventBus()
    log = fresh.read_log("rs")
    assert [e.type for e in log] == [EventType.RUN_STATUS]  # wrong-shape line skipped


@pytest.mark.asyncio
async def test_subscribe_replays_then_tails_live(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    bus = reb.RunEventBus()
    bus.bind_loop(asyncio.get_running_loop())
    bus.publish(
        "r", EventType.RUN_STATUS, {"status": "running"}
    )  # pre-existing (replayed)

    received = []
    sub = bus.subscribe("r", since=0)

    async def reader():
        async for ev in sub:
            received.append(ev)
            if len(received) == 3:
                break

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.05)
    bus.publish("r", EventType.STEP_STARTED, {"kind": "llm"}, step_id="s1")  # live
    bus.publish("r", EventType.STEP_COMPLETED, {"status": "completed"}, step_id="s1")
    await asyncio.wait_for(task, timeout=2.0)

    assert [e.type for e in received] == [
        EventType.RUN_STATUS,
        EventType.STEP_STARTED,
        EventType.STEP_COMPLETED,
    ]
    assert [e.seq for e in received] == [1, 2, 3]
