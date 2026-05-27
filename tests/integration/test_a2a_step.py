"""Phase 3a — kind=a2a step executor.

Drives the engine through a real `kind: a2a` step against a stubbed remote
agent. The transport is mocked via httpx.MockTransport so no socket calls
escape the test process.
"""

from __future__ import annotations

import json
import textwrap
import threading
from pathlib import Path

import httpx
import pytest

from api.services.workflow_engine import WorkflowEngine
from api.services import a2a_client as a2a_client_module

# ── Stub Ollama (same shape Phase 1/2 tests use) ────────────────────────


class _StubOllama:
    """Bare Ollama for tests that don't issue any LLM calls."""

    def chat(self, model, messages, temperature=None, max_tokens=None, **kwargs):
        return {"content": "", "prompt_eval_count": 0, "eval_count": 0}

    def health_check(self):
        return True

    def list_models(self):
        return [{"name": "mistral:latest"}]


# ── Stub remote A2A agent ────────────────────────────────────────────────


def _agent_card_body(skills=("enrich_iocs",)):
    return {
        "name": "Stub Intel Agent",
        "description": "Test fixture",
        "url": "https://intel.local/a2a",
        "version": "0.1.0",
        "provider": {"organization": "test"},
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["text", "data"],
        "defaultOutputModes": ["data"],
        "skills": [
            {
                "id": skill,
                "name": skill,
                "description": "test skill",
                "tags": ["test"],
                "examples": [],
                "inputModes": ["text", "data"],
                "outputModes": ["data"],
            }
            for skill in skills
        ],
    }


def _task_payload(state, task_id="task-1", artifacts=None, error_text=None):
    status = {"state": state, "timestamp": "2026-05-23T00:00:00Z"}
    if error_text:
        status["message"] = {
            "role": "agent",
            "parts": [{"type": "text", "text": error_text}],
        }
    return {
        "id": task_id,
        "status": status,
        "artifacts": artifacts or [],
        "history": [],
    }


class _RecordingHandler:
    """httpx.MockTransport handler that records every call + scripts the
    Agent Card and JSON-RPC responses for the test."""

    def __init__(
        self,
        card_body=None,
        send_response=None,
        poll_states=("completed",),
        artifacts=None,
        send_status=200,
        card_status=200,
    ):
        self.calls: list[dict] = []
        self._lock = threading.Lock()
        self._card_body = card_body if card_body is not None else _agent_card_body()
        self._send_response = send_response
        self._poll_states = list(poll_states)
        self._artifacts = artifacts or []
        self._send_status = send_status
        self._card_status = card_status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        with self._lock:
            self.calls.append(
                {
                    "method": request.method,
                    "url": url,
                    "headers": dict(request.headers),
                    "body": (request.content.decode() if request.content else ""),
                }
            )
        if request.method == "GET" and "/.well-known/agent.json" in url:
            return httpx.Response(self._card_status, json=self._card_body)
        if request.method == "POST" and url.endswith("/a2a"):
            body = json.loads(request.content.decode())
            method = body.get("method")
            if method in ("tasks/send", "tasks/get"):
                if method == "tasks/send" and self._send_response is not None:
                    return httpx.Response(self._send_status, json=self._send_response)
                # Each RPC call consumes one state from the script. tasks/send
                # consumes the first one (this models a remote that returns
                # working from the synchronous send and then continues to a
                # terminal state via subsequent tasks/get polls).
                state = self._poll_states.pop(0) if self._poll_states else "completed"
                artifacts = self._artifacts if state == "completed" else []
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "result": _task_payload(state, artifacts=artifacts),
                    },
                )
        return httpx.Response(404, json={"error": "unhandled"})


@pytest.fixture(autouse=True)
def patch_client(monkeypatch):
    """Force every A2AClient instance to use the per-test MockTransport."""
    state = {"handler": None}

    original_client_method = a2a_client_module.A2AClient._client

    def _override(self):
        if self._http is None:
            transport = httpx.MockTransport(state["handler"])
            self._http = httpx.Client(transport=transport, base_url="")
        return self._http

    monkeypatch.setattr(a2a_client_module.A2AClient, "_client", _override)
    return state


@pytest.fixture
def isolated_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKFLOW_DATA_DIR", str(tmp_path / "runs"))
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    return workflows


def _write_yaml(dirpath: Path, contents: str) -> Path:
    p = dirpath / "wf.yaml"
    p.write_text(contents)
    return p


# ── YAML fixtures ───────────────────────────────────────────────────────


_A2A_HAPPY = textwrap.dedent("""
    id: test-a2a-happy
    name: A2A Happy
    schema_version: 1
    steps:
      - id: enrich
        name: Call remote enrichment
        kind: a2a
        agent_card_url: https://intel.local/.well-known/agent.json
        skill: enrich_iocs
        inputs:
          - seed.iocs
        outputs:
          - enriched
        timeout: 5
    """)


_A2A_BEARER = textwrap.dedent("""
    id: test-a2a-bearer
    name: A2A With Bearer
    schema_version: 1
    steps:
      - id: enrich
        name: Call remote with auth
        kind: a2a
        agent_card_url: https://intel.local/.well-known/agent.json
        skill: enrich_iocs
        auth:
          type: bearer
          token_env: TEST_A2A_TOKEN
        inputs:
          - seed.iocs
        outputs:
          - enriched
        timeout: 5
    """)


# ── Tests ───────────────────────────────────────────────────────────────


def test_a2a_happy_path_writes_artifact_to_workspace(isolated_dir, patch_client):
    """End-to-end: card fetch → tasks/send → terminal → outputs populated."""
    patch_client["handler"] = _RecordingHandler(
        artifacts=[
            {
                "name": "enriched",
                "parts": [
                    {
                        "type": "data",
                        "data": {"iocs": [{"ioc": "x.com", "verdict": "bad"}]},
                    }
                ],
                "index": 0,
            }
        ]
    )
    yaml_path = _write_yaml(isolated_dir, _A2A_HAPPY)
    engine = WorkflowEngine(_StubOllama())
    defn = engine.load(str(yaml_path))
    engine.validate(defn, seed_keys=["iocs"])

    run = engine.run(defn, seed={"iocs": ["x.com"]})

    assert run.status == "completed", run.error
    enriched = run.context.get_workspace("enrich", "enriched")
    assert enriched == {"iocs": [{"ioc": "x.com", "verdict": "bad"}]}
    # Expect: GET card + POST tasks/send (terminal on first POST).
    methods = [(c["method"], c["url"]) for c in patch_client["handler"].calls]
    assert methods[0] == (
        "GET",
        "https://intel.local/.well-known/agent.json",
    )
    assert methods[1] == ("POST", "https://intel.local/a2a")


def test_a2a_polls_until_terminal(isolated_dir, patch_client):
    """When tasks/send returns non-terminal, the client polls tasks/get
    until terminal."""
    patch_client["handler"] = _RecordingHandler(
        poll_states=["working", "working", "completed"],
        artifacts=[
            {
                "name": "enriched",
                "parts": [{"type": "data", "data": {"done": True}}],
                "index": 0,
            }
        ],
    )
    # Drive the poll interval to ~0 so the test doesn't sleep.
    import api.services.a2a_client as mod

    original = mod._POLL_INTERVAL_SECONDS
    mod._POLL_INTERVAL_SECONDS = 0.01
    try:
        yaml_path = _write_yaml(isolated_dir, _A2A_HAPPY)
        engine = WorkflowEngine(_StubOllama())
        defn = engine.load(str(yaml_path))
        run = engine.run(defn, seed={"iocs": ["x.com"]})
    finally:
        mod._POLL_INTERVAL_SECONDS = original

    assert run.status == "completed", run.error
    assert run.context.get_workspace("enrich", "enriched") == {"done": True}
    rpc_calls = [c for c in patch_client["handler"].calls if c["method"] == "POST"]
    rpc_methods = [json.loads(c["body"])["method"] for c in rpc_calls]
    # 1× tasks/send + 2× tasks/get (working, working) before the third
    # tasks/get returns "completed".
    assert rpc_methods == ["tasks/send", "tasks/get", "tasks/get"]


def test_a2a_bearer_token_is_attached(isolated_dir, patch_client, monkeypatch):
    """Auth=bearer reads the env var at request time and adds an
    Authorization header to every outbound call."""
    monkeypatch.setenv("TEST_A2A_TOKEN", "tok-secret")
    patch_client["handler"] = _RecordingHandler(
        artifacts=[
            {
                "name": "enriched",
                "parts": [{"type": "data", "data": {"x": 1}}],
                "index": 0,
            }
        ]
    )
    yaml_path = _write_yaml(isolated_dir, _A2A_BEARER)
    engine = WorkflowEngine(_StubOllama())
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={"iocs": ["x.com"]})

    assert run.status == "completed", run.error
    for call in patch_client["handler"].calls:
        assert (
            call["headers"].get("authorization") == "Bearer tok-secret"
        ), f"missing auth header on {call['method']} {call['url']}"


_A2A_APIKEY = textwrap.dedent("""
    id: test-a2a-apikey
    name: A2A With API Key
    schema_version: 1
    steps:
      - id: enrich
        name: Call remote with api key
        kind: a2a
        agent_card_url: https://intel.local/.well-known/agent.json
        skill: enrich_iocs
        auth:
          type: api_key
          token_env: TEST_A2A_TOKEN
          header_name: X-Service-Key
        inputs:
          - seed.iocs
        outputs:
          - enriched
        timeout: 5
    """)


def test_a2a_api_key_header_is_attached(isolated_dir, patch_client, monkeypatch):
    """Auth=api_key sends the secret under the configured header on every call."""
    monkeypatch.setenv("TEST_A2A_TOKEN", "key-secret")
    patch_client["handler"] = _RecordingHandler(
        artifacts=[
            {
                "name": "enriched",
                "parts": [{"type": "data", "data": {"x": 1}}],
                "index": 0,
            }
        ]
    )
    yaml_path = _write_yaml(isolated_dir, _A2A_APIKEY)
    engine = WorkflowEngine(_StubOllama())
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={"iocs": ["x.com"]})

    assert run.status == "completed", run.error
    for call in patch_client["handler"].calls:
        # httpx lowercases header keys in the recorded request.
        assert (
            call["headers"].get("x-service-key") == "key-secret"
        ), f"missing api-key header on {call['method']} {call['url']}"
        # And it must NOT have sent an Authorization header.
        assert "authorization" not in call["headers"]


def test_a2a_bearer_missing_token_fails_step(isolated_dir, patch_client, monkeypatch):
    """If the token env var is unset, the step fails before any HTTP call."""
    monkeypatch.delenv("TEST_A2A_TOKEN", raising=False)
    patch_client["handler"] = _RecordingHandler()
    yaml_path = _write_yaml(isolated_dir, _A2A_BEARER)
    engine = WorkflowEngine(_StubOllama())
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={"iocs": ["x.com"]})

    assert run.status == "failed"
    assert "TEST_A2A_TOKEN" in (run.error or "")
    # No outbound calls should have been made.
    assert patch_client["handler"].calls == []


def test_a2a_skill_not_advertised_fails_step(isolated_dir, patch_client):
    """Agent Card doesn't advertise the requested skill → clean failure."""
    patch_client["handler"] = _RecordingHandler(
        card_body=_agent_card_body(skills=("some_other_skill",)),
    )
    yaml_path = _write_yaml(isolated_dir, _A2A_HAPPY)
    engine = WorkflowEngine(_StubOllama())
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={"iocs": ["x.com"]})

    assert run.status == "failed"
    assert "enrich_iocs" in (run.error or "")
    # Only the card was fetched; tasks/send was never attempted.
    methods = [c["method"] for c in patch_client["handler"].calls]
    assert methods == ["GET"]


class _FailureMessageHandler(_RecordingHandler):
    """Variant that attaches a non-empty error message when state=failed."""

    def __init__(self, *args, failure_text: str = "upstream backend exploded", **kw):
        super().__init__(*args, **kw)
        self._failure_text = failure_text

    def __call__(self, request: httpx.Request) -> httpx.Response:
        resp = super().__call__(request)
        if request.method != "POST":
            return resp
        try:
            body = json.loads(resp.read())
        except Exception:
            return resp
        result = body.get("result") or {}
        if result.get("status", {}).get("state") == "failed":
            result["status"]["message"] = {
                "role": "agent",
                "parts": [{"type": "text", "text": self._failure_text}],
            }
            body["result"] = result
            return httpx.Response(200, json=body)
        return resp


def test_a2a_remote_failure_propagates(isolated_dir, patch_client):
    """Remote returns state=failed → step fails with the remote's message."""
    patch_client["handler"] = _FailureMessageHandler(poll_states=["failed"])
    yaml_path = _write_yaml(isolated_dir, _A2A_HAPPY)
    engine = WorkflowEngine(_StubOllama())
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={"iocs": ["x.com"]})

    assert run.status == "failed"
    assert "upstream backend exploded" in (run.error or "")


def test_a2a_card_fetch_404_fails_step(isolated_dir, patch_client):
    """Agent Card endpoint returns 404 → step fails with HTTP-level error."""
    patch_client["handler"] = _RecordingHandler(card_status=404)
    yaml_path = _write_yaml(isolated_dir, _A2A_HAPPY)
    engine = WorkflowEngine(_StubOllama())
    defn = engine.load(str(yaml_path))
    run = engine.run(defn, seed={"iocs": ["x.com"]})

    assert run.status == "failed"
    err = (run.error or "").lower()
    assert "agentcard" in err or "404" in err
