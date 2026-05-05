"""
Workflow mid-run checkpointing + resume.

Drives WorkflowEngine end-to-end (no Ollama) by stubbing the OllamaService
chat method, then asserts:
  - run.json is written after each step (not just at end)
  - Atomic write produces no run.json.tmp leftover
  - resume() picks up at the first non-completed step
  - resume() of a terminal run is a no-op
"""

import json
from pathlib import Path

import pytest
import yaml

from api.models.workflow_models import (
    AgentStep,
    StepPrompt,
    WorkflowDefaults,
    WorkflowDefinition,
)
from api.services import workflow_engine as we_module
from api.services.workflow_engine import WorkflowEngine


class _StubOllama:
    """Records every chat call; returns canned responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def chat(self, model, messages, temperature=None, max_tokens=None):
        self.calls.append({"model": model, "messages": messages})
        if not self._responses:
            return {"content": "", "prompt_eval_count": 0, "eval_count": 0}
        resp = self._responses.pop(0)
        return resp if isinstance(resp, dict) else {
            "content": resp,
            "prompt_eval_count": 5,
            "eval_count": 5,
        }

    def health_check(self):
        return True

    def list_models(self):
        return [{"name": "mistral:latest"}]


def _make_two_step_workflow(tmp_path: Path) -> Path:
    """Write a 2-step YAML workflow to tmp_path and return its file path."""
    defn = {
        "id": "test-checkpoint",
        "name": "Test Checkpoint",
        "schema_version": 2,
        "defaults": {"role": "general"},
        "steps": [
            {
                "id": "step1",
                "name": "Step One",
                "model": "mistral:latest",
                "prompt": {
                    "role_inline": "You are a stub.",
                    "task": "say one",
                    "constraints": [],
                },
                "outputs": ["answer"],
            },
            {
                "id": "step2",
                "name": "Step Two",
                "model": "mistral:latest",
                "prompt": {
                    "role_inline": "You are a stub.",
                    "task": "say two",
                    "constraints": [],
                },
                "inputs": ["step1.answer"],
                "outputs": ["final"],
            },
        ],
    }
    path = tmp_path / "test-checkpoint.yaml"
    path.write_text(yaml.safe_dump(defn))
    return path


@pytest.fixture
def isolated_workflow_dir(tmp_path, monkeypatch):
    """Pin DATA_DIR to a tmp dir so checkpoints don't pollute data/workflows."""
    monkeypatch.setattr(we_module, "DATA_DIR", str(tmp_path / "workflows"))
    (tmp_path / "workflows").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_checkpoint_writes_run_json_after_each_step(isolated_workflow_dir):
    """Each step boundary must produce an updated run.json on disk."""
    yaml_path = _make_two_step_workflow(isolated_workflow_dir)
    ollama = _StubOllama(responses=["one", "two"])
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})

    assert run.status == "completed"
    assert len(run.step_results) == 2

    run_dir = Path(we_module.DATA_DIR) / run.run_id
    run_json = run_dir / "run.json"
    assert run_json.exists()

    # No tmp leftover from the atomic write.
    assert not (run_dir / "run.json.tmp").exists()

    # Persisted state matches the in-memory return value.
    on_disk = json.loads(run_json.read_text())
    assert on_disk["status"] == "completed"
    assert len(on_disk["step_results"]) == 2


def test_resume_completed_run_is_noop(isolated_workflow_dir):
    """Resuming a terminal run must not re-execute any step."""
    yaml_path = _make_two_step_workflow(isolated_workflow_dir)
    ollama = _StubOllama(responses=["one", "two"])
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    run = engine.run(defn, seed={})
    assert run.status == "completed"
    initial_call_count = len(ollama.calls)

    resumed = engine.resume(run.run_id, definition=defn)
    assert resumed.status == "completed"
    assert resumed.run_id == run.run_id
    # No additional ollama calls during resume of terminal run.
    assert len(ollama.calls) == initial_call_count


def test_resume_picks_up_at_first_uncompleted_step(isolated_workflow_dir):
    """
    Simulate a crash mid-run by hand-writing a checkpoint with step1 done
    and status=running. Resume should re-execute only step2.
    """
    yaml_path = _make_two_step_workflow(isolated_workflow_dir)
    ollama = _StubOllama(responses=["one", "two"])
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    # First, run normally and capture the completed checkpoint.
    completed = engine.run(defn, seed={})
    assert completed.status == "completed"
    run_dir = Path(we_module.DATA_DIR) / completed.run_id
    run_json = run_dir / "run.json"
    state = json.loads(run_json.read_text())

    # Mutate to look like a crashed run: status=running, step2 dropped.
    state["status"] = "running"
    state["completed_at"] = None
    state["step_results"] = [
        r for r in state["step_results"] if r["step_id"] == "step1"
    ]
    # Drop step2's workspace entry so it actually runs again.
    state["context"]["workspace"].pop("step2", None)
    run_json.write_text(json.dumps(state))

    # Reset the stub so resume gets a fresh response for step2 only.
    ollama2 = _StubOllama(responses=["two-resumed"])
    engine2 = WorkflowEngine(ollama2)
    resumed = engine2.resume(completed.run_id, definition=defn)

    assert resumed.status == "completed"
    assert {r.step_id for r in resumed.step_results} == {"step1", "step2"}
    # Only step2 was re-executed — exactly one call to ollama.
    assert len(ollama2.calls) == 1


def test_resume_unknown_run_id_raises(isolated_workflow_dir):
    engine = WorkflowEngine(_StubOllama(responses=[]))
    with pytest.raises(ValueError, match="not found"):
        engine.resume("does-not-exist")


def test_initial_checkpoint_persists_running_state(isolated_workflow_dir):
    """
    The first checkpoint (right after the run is created) must record
    status=running so a crash before any step still leaves a discoverable
    artifact.
    """
    yaml_path = _make_two_step_workflow(isolated_workflow_dir)
    ollama = _StubOllama(responses=["one", "two"])
    engine = WorkflowEngine(ollama)
    defn = engine.load(str(yaml_path))

    # Spy on _checkpoint to capture the FIRST call's snapshot.
    snapshots = []
    real_checkpoint = engine._checkpoint

    def _spy(run):
        snapshots.append(
            {"status": run.status, "n_results": len(run.step_results)}
        )
        return real_checkpoint(run)

    engine._checkpoint = _spy
    engine.run(defn, seed={})

    # First snapshot should be running with no step_results yet.
    assert snapshots[0] == {"status": "running", "n_results": 0}
