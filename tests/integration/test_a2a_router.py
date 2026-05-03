"""
A2A router integration tests.

Uses FastAPI's TestClient against the live router with a stubbed A2AService
(no Ollama, no real workflow execution). Exercises:
  - GET /.well-known/agent.json
  - POST /a2a tasks/send (chat skill)
  - POST /a2a tasks/get + tasks/cancel
  - POST /a2a method/error envelope handling
  - POST /a2a tasks/sendSubscribe SSE streaming

Marked as integration to keep the unit suite fast, but it does not require
network or external services.
"""

import asyncio
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.models.a2a_models import (
    Artifact,
    DataPart,
    Message,
    MessageRole,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
    workflow_skill_id,
)
from api.routers import a2a as a2a_router
from api.services.a2a_service import A2AService


# ── Stubbed dependencies ───────────────────────────────────────────────────


class _StubOllama:
    def chat(self, model, messages, temperature=None, max_tokens=None):
        return {
            "content": f"echo: {messages[-1]['content']}",
            "prompt_eval_count": 7,
            "eval_count": 11,
        }


class _StubWorkflows:
    """Minimal WorkflowEngine stand-in — list_workflows is enough for the card."""

    def list_workflows(self):
        return [
            {"id": "demo", "name": "Demo Workflow", "description": "demo"},
        ]


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Pin task persistence under tmp_path so tests don't pollute data/a2a.
    monkeypatch.setattr(
        "api.services.a2a_service.TASK_DATA_DIR", tmp_path / "a2a"
    )
    (tmp_path / "a2a").mkdir(parents=True, exist_ok=True)

    svc = A2AService(_StubOllama(), _StubWorkflows())
    a2a_router.init_a2a_service(svc)

    app = FastAPI()
    app.include_router(a2a_router.router)
    return TestClient(app)


# ── Agent Card ─────────────────────────────────────────────────────────────


def test_agent_card_served_at_well_known(client):
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    # Spec-required fields.
    assert card["name"]
    assert card["url"].endswith("/a2a")
    assert card["version"]
    assert card["capabilities"]["streaming"] is True
    # Both built-in chat and the discovered workflow skill should be present.
    skill_ids = {s["id"] for s in card["skills"]}
    assert "chat" in skill_ids
    assert workflow_skill_id("demo") in skill_ids


# ── tasks/send happy path (chat skill) ─────────────────────────────────────


def test_tasks_send_chat_returns_completed_task(client):
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tasks/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "hello"}],
                "metadata": {"skillId": "chat"},
            }
        },
    }
    resp = client.post("/a2a", json=body)
    assert resp.status_code == 200
    env = resp.json()
    assert env["jsonrpc"] == "2.0"
    assert env["id"] == 1
    task = env["result"]
    assert task["status"]["state"] == TaskState.COMPLETED.value
    assert len(task["artifacts"]) == 1
    assert task["artifacts"][0]["parts"][0]["type"] == "text"
    assert task["artifacts"][0]["parts"][0]["text"].startswith("echo:")


# ── tasks/get + tasks/cancel ───────────────────────────────────────────────


def test_tasks_get_unknown_id_returns_task_not_found(client):
    body = {
        "jsonrpc": "2.0",
        "id": "lookup-1",
        "method": "tasks/get",
        "params": {"id": "does-not-exist"},
    }
    resp = client.post("/a2a", json=body)
    env = resp.json()
    assert env["error"]["code"] == -32001
    assert "not found" in env["error"]["message"].lower()


def test_tasks_cancel_completed_task_returns_not_cancelable(client):
    # First create a task by sending one.
    send = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "ping"}],
                    "metadata": {"skillId": "chat"},
                }
            },
        },
    )
    task_id = send.json()["result"]["id"]
    cancel = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tasks/cancel",
            "params": {"id": task_id},
        },
    )
    env = cancel.json()
    assert env["error"]["code"] == -32002


# ── Envelope error paths ───────────────────────────────────────────────────


def test_unknown_method_returns_method_not_found(client):
    resp = client.post(
        "/a2a",
        json={"jsonrpc": "2.0", "id": 9, "method": "tasks/bogus", "params": {}},
    )
    env = resp.json()
    assert env["error"]["code"] == -32601


def test_unsupported_method_returns_unsupported_operation(client):
    resp = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tasks/pushNotification/set",
            "params": {"id": "x"},
        },
    )
    env = resp.json()
    assert env["error"]["code"] == -32004


def test_parse_error_returns_envelope(client):
    resp = client.post(
        "/a2a",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    env = resp.json()
    assert env["error"]["code"] == -32700


def test_invalid_skill_id_returns_invalid_params(client):
    resp = client.post(
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tasks/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "hi"}],
                    "metadata": {"skillId": "not-a-real-skill"},
                }
            },
        },
    )
    env = resp.json()
    assert env["error"]["code"] == -32602


# ── tasks/sendSubscribe (SSE) ──────────────────────────────────────────────


def test_send_subscribe_streams_events_to_terminal(client):
    """
    Verify SSE stream emits at least one TaskStatusUpdateEvent and ends with
    a final=True frame followed by [DONE].
    """
    with client.stream(
        "POST",
        "/a2a",
        json={
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tasks/sendSubscribe",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "stream me"}],
                    "metadata": {"skillId": "chat"},
                }
            },
        },
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = []
        done_seen = False
        for raw in resp.iter_lines():
            if not raw or not raw.startswith("data: "):
                continue
            payload = raw[len("data: ") :]
            if payload == "[DONE]":
                done_seen = True
                break
            events.append(json.loads(payload))

    assert done_seen
    assert events, "expected at least one SSE frame before [DONE]"
    # All frames are JSON-RPC envelopes carrying task event payloads.
    for env in events:
        assert env["jsonrpc"] == "2.0"
        assert "result" in env
        assert "id" in env["result"]  # task id, not RPC id
    # Final frame must be a status update with final=true.
    last_status = [e for e in events if "status" in e["result"]][-1]
    assert last_status["result"]["final"] is True
    assert last_status["result"]["status"]["state"] in {"completed", "failed"}
