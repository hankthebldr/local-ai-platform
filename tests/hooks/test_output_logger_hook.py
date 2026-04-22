import json
import pytest
from api.services.hook_bus import HookContext
from api.services.prompt_composer import ComposedPrompt
from api.hooks.builtins.output_logger import OutputLoggerHook


class FakeStep:
    def __init__(self, sid):
        self.id = sid

class FakeWorkflow:
    def __init__(self, rid):
        self.run_id = rid


def test_logger_writes_jsonl_entry(tmp_path):
    logfile = tmp_path / "runs.jsonl"
    hook = OutputLoggerHook(log_path=logfile, include_prompt=False)
    ctx = HookContext(
        workflow=FakeWorkflow("run-1"),
        step=FakeStep("analyze"),
        output='{"ok": true}',
        parsed={"ok": True},
    )
    result = hook(ctx)
    assert result.action == "continue"
    lines = logfile.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["run_id"] == "run-1"
    assert record["step_id"] == "analyze"
    assert record["raw_output"] == '{"ok": true}'
    assert record["parsed"] == {"ok": True}


def test_logger_includes_prompt_when_configured(tmp_path):
    logfile = tmp_path / "runs.jsonl"
    hook = OutputLoggerHook(log_path=logfile, include_prompt=True)
    ctx = HookContext(
        workflow=FakeWorkflow("r"),
        step=FakeStep("s"),
        prompt=ComposedPrompt(system="sys", user="usr", params={}),
        output="x",
    )
    hook(ctx)
    record = json.loads(logfile.read_text().strip())
    assert record["prompt"]["system"] == "sys"
    assert record["prompt"]["user"] == "usr"


def test_logger_excludes_prompt_by_default(tmp_path):
    logfile = tmp_path / "runs.jsonl"
    hook = OutputLoggerHook(log_path=logfile)
    ctx = HookContext(
        workflow=FakeWorkflow("r"),
        step=FakeStep("s"),
        prompt=ComposedPrompt(system="sys", user="usr", params={}),
        output="x",
    )
    hook(ctx)
    record = json.loads(logfile.read_text().strip())
    assert "prompt" not in record


def test_logger_appends_multiple_entries(tmp_path):
    logfile = tmp_path / "runs.jsonl"
    hook = OutputLoggerHook(log_path=logfile)
    for i in range(3):
        ctx = HookContext(
            workflow=FakeWorkflow(f"r{i}"),
            step=FakeStep("s"),
            output=f"out-{i}",
        )
        hook(ctx)
    assert len(logfile.read_text().strip().splitlines()) == 3


def test_logger_name_and_stage():
    hook = OutputLoggerHook(log_path="/tmp/x.jsonl")
    assert hook.name == "output_logger"
    assert hook.stage == "after_step"
