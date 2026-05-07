"""
A2A resubscribe persistence: simulate a process restart by spinning up a
fresh A2AService against the same on-disk events.jsonl and confirming the
event log replays correctly.
"""

import asyncio
import json

import pytest

from api.models.a2a_models import (
    Artifact,
    Message,
    MessageRole,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
    TextPart,
)
from api.services import a2a_service
from api.services.a2a_service import A2AService


class _StubOllama:
    def chat(self, model, messages, temperature=None, max_tokens=None):
        return {
            "content": "echo back",
            "prompt_eval_count": 3,
            "eval_count": 5,
        }


class _StubWorkflows:
    def list_workflows(self):
        return []


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(a2a_service, "TASK_DATA_DIR", tmp_path / "a2a")
    (tmp_path / "a2a").mkdir(parents=True, exist_ok=True)
    return tmp_path / "a2a"


@pytest.mark.asyncio
async def test_resubscribe_replays_from_disk_after_restart(isolated_data_dir):
    """
    Run a chat task to completion with one A2AService instance. Spawn a
    second A2AService — its in-memory _runtime is empty — and confirm
    resubscribe still works by reading events.jsonl.
    """
    svc1 = A2AService(_StubOllama(), _StubWorkflows())
    msg = Message(role=MessageRole.USER, parts=[TextPart(text="hi")])
    task = await svc1.send(skill_id="chat", message=msg)
    assert task.status.state == TaskState.COMPLETED

    # The events log should have been written.
    log_path = isolated_data_dir / task.id / "events.jsonl"
    assert log_path.exists(), "events.jsonl was not persisted"
    lines = [l for l in log_path.read_text().splitlines() if l.strip()]
    assert len(lines) >= 2, "expected at least one status + one artifact event"

    # Spawn a fresh service that has no in-memory record of the task.
    svc2 = A2AService(_StubOllama(), _StubWorkflows())
    assert task.id not in svc2._runtime

    stream = await svc2.resubscribe(task.id)
    replayed = []
    async for event in stream:
        replayed.append(event)

    # Should have the same number of frames as the on-disk log.
    assert len(replayed) == len(lines)
    # Final replayed event must be a final status update.
    last = replayed[-1]
    assert isinstance(last, TaskStatusUpdateEvent)
    assert last.final is True


@pytest.mark.asyncio
async def test_resubscribe_unknown_id_raises_keyerror(isolated_data_dir):
    svc = A2AService(_StubOllama(), _StubWorkflows())
    with pytest.raises(KeyError):
        await svc.resubscribe("does-not-exist")
