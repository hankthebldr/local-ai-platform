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
