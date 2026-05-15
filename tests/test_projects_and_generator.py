#!/usr/bin/env python3
"""Tests for project service + agent generator."""

from __future__ import annotations


import pytest

from api.models.project_models import (
    AgentEvaluationCase,
    ProjectCreate,
    ProjectUpdate,
)
from api.services.agent_generator import AgentGenerator
from api.services.project_service import ProjectService

# ── Project service ────────────────────────────────────────────────────


@pytest.fixture
def svc(tmp_path):
    return ProjectService(projects_dir=str(tmp_path / "projects"))


def test_create_get_update_delete(svc):
    svc.create_project(ProjectCreate(id="p1", name="P1", tags=["t"]))
    assert svc.get_project("p1")["name"] == "P1"

    svc.update_project("p1", ProjectUpdate(description="hello"))
    assert svc.get_project("p1")["description"] == "hello"

    assert svc.delete_project("p1") is True
    assert svc.delete_project("p1") is False


def test_add_remove_artifact(svc):
    svc.create_project(ProjectCreate(id="p", name="P"))
    svc.add_artifact("p", "workflows", "wf-a")
    svc.add_artifact("p", "workflows", "wf-a")  # idempotent
    svc.add_artifact("p", "agents", "ag-1")
    cur = svc.get_project("p")
    assert cur["artifacts"]["workflows"] == ["wf-a"]
    assert cur["artifacts"]["agents"] == ["ag-1"]

    svc.remove_artifact("p", "workflows", "wf-a")
    cur = svc.get_project("p")
    assert cur["artifacts"]["workflows"] == []


def test_unknown_kind_rejected(svc):
    svc.create_project(ProjectCreate(id="p", name="P"))
    with pytest.raises(ValueError):
        svc.add_artifact("p", "bogus", "x")


def test_id_validation(svc):
    with pytest.raises(ValueError):
        svc.create_project(ProjectCreate(id="bad slug", name="x"))


def test_export_missing_raises(svc):
    with pytest.raises(FileNotFoundError):
        svc.export_bundle("nope")


# ── Agent generator (heuristic fallback) ───────────────────────────────


class FakeOllama:
    """Always raises so the generator drops to the heuristic path."""

    def chat(self, **kwargs):
        raise RuntimeError("offline")

    def list_models(self):
        return []


def test_generator_heuristic_path_emits_valid_draft():
    gen = AgentGenerator(FakeOllama())
    result = gen.generate_from_text(
        "# XSIAM Quickstart\n\nXDM normalization is the core idea.",
        name_hint="XSIAM Helper",
        role_hint="reasoning",
    )
    draft = result.draft
    assert draft["id"]
    assert draft["role"] == "reasoning"
    assert "XSIAM" in draft["name"] or "XSIAM" in draft["system_prompt"]
    assert isinstance(draft["starters"], list) and draft["starters"]


def test_generator_attaches_source_as_context():
    gen = AgentGenerator(FakeOllama())
    result = gen.generate_from_text("hello world content", source_file="/tmp/x.md")
    ctx = result.draft.get("context", [])
    assert any(c["type"] == "file" and c["value"].endswith("x.md") for c in ctx)


def test_generator_save_round_trip(tmp_path):
    from api.services.agent_service import AgentService as _AS

    gen = AgentGenerator(FakeOllama())
    gen._agents = _AS(str(tmp_path / "agents"))
    result = gen.generate_from_text("Notes on system X.", name_hint="System X Agent")
    path = gen.save_draft(result.draft)
    assert path
    # Second save without overwrite -> conflict
    with pytest.raises(FileExistsError):
        gen.save_draft(result.draft, overwrite=False)
    # Overwrite succeeds.
    gen.save_draft(result.draft, overwrite=True)


def test_generator_evaluation_runs_each_case(tmp_path, monkeypatch):
    """Evaluator should invoke the underlying chat once per case and tally results."""
    monkeypatch.setenv("AGENTS_DIR", str(tmp_path / "agents"))

    # Stand up a tiny agent on disk.
    import yaml as _yaml

    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "demo.yaml").write_text(
        _yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo",
                "system_prompt": "be brief",
            }
        )
    )

    calls: list = []

    class EchoOllama:
        def chat(self, **kwargs):
            calls.append(kwargs)
            user = next(m["content"] for m in kwargs["messages"] if m["role"] == "user")
            return {"message": {"content": f"You asked: {user}"}}

        def list_models(self):
            return []

    from api.services.agent_service import AgentService as _AS

    gen = AgentGenerator(EchoOllama())
    gen._agents = _AS(str(agents_dir))
    report = gen.evaluate_agent(
        "demo",
        [
            AgentEvaluationCase(prompt="hi", expected_contains="hi"),
            AgentEvaluationCase(prompt="bye", expected_contains="nope"),
        ],
    )
    assert report.agent_id == "demo"
    assert report.passed == 1
    assert report.failed == 1
    assert len(calls) == 2
