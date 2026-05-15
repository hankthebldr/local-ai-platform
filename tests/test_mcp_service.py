#!/usr/bin/env python3
"""Tests for MCP service registry + workflow index."""

from __future__ import annotations

import json

import pytest

from api.models.mcp_models import MCPServerCreate, MCPServerUpdate
from api.services.mcp_service import MCPService
from api.services.workflow_index import (
    WorkflowIndexService,
    classify_workflow_roles,
)

# ── MCP registry ──────────────────────────────────────────────────────────


@pytest.fixture
def mcp(tmp_path):
    return MCPService(storage_path=tmp_path / "mcp_servers.json")


def test_register_stdio_server_persists_and_masks(mcp, tmp_path):
    mcp.register(
        MCPServerCreate(
            id="local-fs",
            name="Local FS",
            transport="stdio",
            command="/usr/bin/echo",
            args=["hello"],
            env={"API_KEY": "supersecretvalue"},
        )
    )

    listed = mcp.list_servers()
    assert len(listed) == 1
    assert listed[0]["id"] == "local-fs"
    assert listed[0]["env"]["API_KEY"] != "supersecretvalue"  # masked
    assert "sup" in listed[0]["env"]["API_KEY"]

    # Persistence
    raw = json.loads((tmp_path / "mcp_servers.json").read_text())
    assert raw["servers"][0]["env"]["API_KEY"] == "supersecretvalue"


def test_stdio_requires_command(mcp):
    with pytest.raises(ValueError, match="command"):
        mcp.register(
            MCPServerCreate(id="bad", name="bad", transport="stdio", command=None)
        )


def test_http_requires_url(mcp):
    with pytest.raises(ValueError, match="url"):
        mcp.register(MCPServerCreate(id="bad", name="bad", transport="http", url=None))


def test_update_round_trip(mcp):
    mcp.register(
        MCPServerCreate(
            id="x", name="x", transport="http", url="http://example.com/mcp"
        )
    )
    mcp.update("x", MCPServerUpdate(name="renamed", enabled=False))
    cur = mcp.get_server("x")
    assert cur["name"] == "renamed"
    assert cur["enabled"] is False


def test_remove_idempotent(mcp):
    mcp.register(
        MCPServerCreate(
            id="x", name="x", transport="http", url="http://example.com/mcp"
        )
    )
    assert mcp.remove("x") is True
    assert mcp.remove("x") is False
    assert mcp.get_server("x") is None


def test_duplicate_id_rejected(mcp):
    mcp.register(
        MCPServerCreate(id="x", name="x", transport="http", url="http://example.com")
    )
    with pytest.raises(ValueError, match="already registered"):
        mcp.register(
            MCPServerCreate(
                id="x", name="x2", transport="http", url="http://example.com"
            )
        )


def test_id_validation():
    with pytest.raises(ValueError):
        MCPServerCreate(id="bad slug", name="x", transport="stdio", command="echo")


# ── Workflow index + classification ───────────────────────────────────────


def test_classify_workflow_roles_reasoning():
    roles = classify_workflow_roles(
        {"repo_id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek-R1", "tags": []}
    )
    assert "reasoning" in roles


def test_classify_workflow_roles_coding():
    roles = classify_workflow_roles(
        {"repo_id": "qwen/Qwen2.5-Coder-7B", "name": "qwen-coder", "tags": []}
    )
    assert "coding" in roles


def test_classify_workflow_roles_uncensored_from_flag():
    roles = classify_workflow_roles(
        {"repo_id": "x/y", "name": "neutral-model", "tags": [], "is_abliterated": True}
    )
    assert "uncensored" in roles


def test_classify_workflow_roles_default_general():
    roles = classify_workflow_roles({"repo_id": "x/y", "name": "y", "tags": []})
    assert roles == ["general"]


def test_workflow_index_builds(tmp_path):
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "sec.yaml").write_text(
        "id: sec\nname: Security\ntags: [xsiam]\nsteps:\n  - id: a\n    role: reasoning\n    system_prompt: hi\n    outputs: [out]\n"
    )
    (wf_dir / "gen.yaml").write_text(
        "id: gen\nname: Gen\nsteps:\n  - id: a\n    role: general\n    system_prompt: hi\n    outputs: [out]\n"
    )

    svc = WorkflowIndexService(workflows_dir=str(wf_dir))
    idx = svc.build_index()
    assert idx["total"] == 2
    cats = {c["id"]: c["count"] for c in idx["categories"]}
    assert cats.get("security") == 1
    assert cats.get("general") == 1


def test_workflow_index_export_import_roundtrip(tmp_path, monkeypatch):
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "wf.yaml").write_text(
        "id: wf\nname: WF\nsteps:\n  - id: a\n    role: reasoning\n    system_prompt: hi\n    outputs: [out]\n"
    )
    svc = WorkflowIndexService(workflows_dir=str(wf_dir))
    bundle = svc.export_bundle("wf")
    assert bundle["schema"] == "enclave.workflow-bundle/v1"
    assert bundle["workflow"]["id"] == "wf"

    # Import into a fresh dir
    new_dir = tmp_path / "fresh"
    new_dir.mkdir()
    svc2 = WorkflowIndexService(workflows_dir=str(new_dir))
    monkeypatch.chdir(tmp_path)  # so agents dir resolves under tmp_path
    result = svc2.import_bundle(bundle)
    assert result["imported"] is True
    assert (new_dir / "wf.yaml").exists()


def test_workflow_bundle_import_rejects_unsafe_id(tmp_path):
    svc = WorkflowIndexService(workflows_dir=str(tmp_path / "workflows"))
    with pytest.raises(ValueError):
        svc.import_bundle({"workflow": {"id": "../escape", "steps": []}})


def test_workflow_bundle_import_rejects_existing_without_overwrite(
    tmp_path, monkeypatch
):
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    svc = WorkflowIndexService(workflows_dir=str(wf_dir))
    monkeypatch.chdir(tmp_path)
    bundle = {"workflow": {"id": "dup", "name": "dup", "steps": []}}
    svc.import_bundle(bundle)
    with pytest.raises(FileExistsError):
        svc.import_bundle(bundle)
