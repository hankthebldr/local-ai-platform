import api.services.run_event_bus as reb
from api.models.run_event import EventType


def test_emit_tool_called_helper(tmp_path, monkeypatch):
    monkeypatch.setattr(reb, "RUNS_DIR", str(tmp_path))
    reb._BUS = None
    from api.hooks.builtins.mcp_tool_invoker import _emit_tool_called

    _emit_tool_called(run_id="r", step_id="s", tool="search", server="srv", status="ok")
    evs = [
        e
        for e in reb.get_run_event_bus().read_log("r")
        if e.type == EventType.TOOL_CALLED
    ]
    assert evs and evs[0].data["tool"] == "search" and evs[0].data["server"] == "srv"
    assert evs[0].step_id == "s"
