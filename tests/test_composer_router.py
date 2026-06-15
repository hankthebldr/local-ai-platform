#!/usr/bin/env python3
"""
Composer Router Tests — chat-led workflow authoring HTTP surface.

Covers the ASGI wiring of api/routers/composer.py end-to-end with a real
TestClient: request validation, Pydantic request/response coercion, and the
service-call glue. The underlying SpecCaptureService / ScaffoldPlannerService
are unit-tested separately (test_spec_capture.py / test_scaffold_planner.py)
and the Playwright flow STUBS these routes, so this file is the only coverage
of the router itself. Services are mocked here — no Ollama, no network.

Run:  pytest tests/test_composer_router.py -v
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """Test client with auth + rate-limiting disabled (lifespan not fired)."""
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    import importlib
    import api.middleware

    importlib.reload(api.middleware)
    import api.main

    importlib.reload(api.main)
    from api.main import app

    return TestClient(app)


@pytest.fixture
def mock_services():
    """Patch the router's two services + Ollama factory; yield the instances."""
    with (
        patch("api.routers.composer._ollama", return_value=MagicMock()),
        patch("api.routers.composer.SpecCaptureService") as SpecCls,
        patch("api.routers.composer.ScaffoldPlannerService") as ScaffoldCls,
    ):
        spec_svc = SpecCls.return_value
        scaffold_svc = ScaffoldCls.return_value
        yield spec_svc, scaffold_svc


# ── /api/composer/capture-spec ───────────────────────────────────────────────


def test_capture_spec_rejects_empty_messages(client, mock_services):
    """No messages → 400, and the service is never constructed/called."""
    spec_svc, _ = mock_services
    resp = client.post("/api/composer/capture-spec", json={"messages": []})
    assert resp.status_code == 400
    assert "messages is required" in resp.json()["detail"]
    spec_svc.capture.assert_not_called()


def test_capture_spec_happy_path_shapes_response(client, mock_services):
    """Service dict is coerced into CaptureSpecResponse (inputs → SpecInput[])."""
    spec_svc, _ = mock_services
    spec_svc.capture.return_value = {
        "goal": "Summarize a meeting transcript into decisions",
        "inputs": [{"key": "transcript", "description": "raw notes"}],
        "checks": ["output names at least one decision"],
        "model": "qwen2.5:7b",
    }
    resp = client.post(
        "/api/composer/capture-spec",
        json={
            "messages": [
                {"role": "user", "content": "help me summarize meetings"},
                {"role": "assistant", "content": "sure, paste the transcript"},
            ],
            "role": "reasoning",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["goal"].startswith("Summarize")
    assert body["inputs"] == [{"key": "transcript", "description": "raw notes"}]
    assert body["checks"] == ["output names at least one decision"]
    assert body["model"] == "qwen2.5:7b"
    # router forwards the message dicts + role through to the service
    spec_svc.capture.assert_called_once()
    args, kwargs = spec_svc.capture.call_args
    assert args[0][0]["content"] == "help me summarize meetings"
    assert kwargs["role"] == "reasoning"


def test_capture_spec_input_missing_description_defaults_empty(client, mock_services):
    """SpecInput.description defaults to '' when the service omits it."""
    spec_svc, _ = mock_services
    spec_svc.capture.return_value = {
        "goal": "G",
        "inputs": [{"key": "topic"}],
        "checks": [],
        "model": "m",
    }
    resp = client.post(
        "/api/composer/capture-spec",
        json={"messages": [{"role": "user", "content": "x"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["inputs"] == [{"key": "topic", "description": ""}]


# ── /api/composer/scaffold ───────────────────────────────────────────────────


def test_scaffold_rejects_blank_goal(client, mock_services):
    """Whitespace-only goal → 400, service untouched."""
    _, scaffold_svc = mock_services
    resp = client.post("/api/composer/scaffold", json={"goal": "   "})
    assert resp.status_code == 400
    assert "goal is required" in resp.json()["detail"]
    scaffold_svc.scaffold.assert_not_called()


@pytest.mark.parametrize("source", ["template", "llm", "fallback"])
def test_scaffold_passes_through_source_and_definition(client, mock_services, source):
    """All three planner sources round-trip through ScaffoldResponse."""
    _, scaffold_svc = mock_services
    scaffold_svc.scaffold.return_value = {
        "definition": {"id": "wf-1", "steps": [{"id": "s1"}]},
        "source": source,
        "matched_workflow_id": "brainstorm-decision" if source == "template" else None,
        "bindings": [{"input": "topic", "step": "s1"}],
    }
    resp = client.post(
        "/api/composer/scaffold",
        json={
            "goal": "brainstorm then decide",
            "inputs": [{"key": "topic", "description": "the subject"}],
            "checks": ["names a decision"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == source
    assert body["definition"]["id"] == "wf-1"
    assert body["bindings"] == [{"input": "topic", "step": "s1"}]
    if source == "template":
        assert body["matched_workflow_id"] == "brainstorm-decision"
    # router forwards goal/inputs/checks to the planner
    _, kwargs = scaffold_svc.scaffold.call_args
    assert kwargs["goal"] == "brainstorm then decide"
    assert kwargs["inputs"] == [{"key": "topic", "description": "the subject"}]
    assert kwargs["checks"] == ["names a decision"]


def test_scaffold_defaults_optional_fields(client, mock_services):
    """matched_workflow_id/bindings default cleanly when the planner omits them."""
    _, scaffold_svc = mock_services
    scaffold_svc.scaffold.return_value = {
        "definition": {"id": "wf-2", "steps": []},
        "source": "fallback",
    }
    resp = client.post("/api/composer/scaffold", json={"goal": "do a thing"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched_workflow_id"] is None
    assert body["bindings"] == []
