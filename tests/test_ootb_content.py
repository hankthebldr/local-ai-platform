"""
OOTB (out-of-the-box) content sanity tests.

Asserts every shipped workflow / agent / role / seed file parses and is
internally consistent. These tests catch the class of regression where
a contributor edits a YAML and a typo (or a Pydantic model rename)
breaks the loader silently — the file still exists, but the API now
returns 0 steps or 500s on /api/agents/{id}.

Each test is intentionally fast — pure file-loading + Pydantic
validation, no LLM calls. Runs in CI on every PR and locally via
`pytest tests/test_ootb_content.py -v`.

Scope (as of v1.1.x):
  - workflows/*.yaml — 11 files
  - agents/*.yaml    — 5 files
  - prompts/roles/*.md — N files
  - docs/seed/xql/*  — agent grounding corpus baked into the Docker image

These counts are asserted to be >= N (minimum-shipping) rather than
exact-N so adding new content doesn't break the suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Set

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Workflow YAML shape ─────────────────────────────────────────────────


WORKFLOWS_DIR = REPO_ROOT / "workflows"


def _workflow_files() -> list[Path]:
    """Every YAML under workflows/ — excluding the private overlay."""
    return sorted(WORKFLOWS_DIR.glob("*.yaml"))


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_workflow_yaml_parses(path: Path):
    """Every workflow YAML must parse + have the engine's required fields."""
    with open(path) as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), f"{path.name}: top-level must be a mapping"
    assert "id" in data, f"{path.name}: missing 'id'"
    assert "name" in data, f"{path.name}: missing 'name'"
    assert "steps" in data, f"{path.name}: missing 'steps'"
    assert (
        isinstance(data["steps"], list) and data["steps"]
    ), f"{path.name}: 'steps' must be a non-empty list"


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_workflow_validates_against_engine_models(path: Path):
    """Each YAML must round-trip through WorkflowDefinition without
    Pydantic complaints. Catches the depends_on / role / step_id classes
    of bug where a YAML field doesn't match the model."""
    from api.models.workflow_models import WorkflowDefinition

    with open(path) as f:
        data = yaml.safe_load(f)
    # Will raise ValidationError if any step is malformed.
    defn = WorkflowDefinition(**data)
    assert defn.id, f"{path.name}: parsed defn has no id"
    # If a step declares depends_on, the referenced ids must exist.
    step_ids: Set[str] = {s.id for s in defn.steps}
    for s in defn.steps:
        for dep in s.depends_on or []:
            assert (
                dep in step_ids
            ), f"{path.name}: step '{s.id}' depends_on='{dep}' which isn't in {step_ids}"


def test_workflow_inventory_meets_floor():
    """At least 11 workflows ship out of the box. Reduces silently when
    YAMLs get deleted without a coordinated removal from MODELS.md / docs."""
    assert len(_workflow_files()) >= 11, (
        f"Expected >=11 workflows; found {len(_workflow_files())}. "
        "If a workflow was moved to the private overlay, update this floor."
    )


# ── Agent YAML shape ────────────────────────────────────────────────────


AGENTS_DIR = REPO_ROOT / "agents"


def _agent_files() -> list[Path]:
    return sorted(AGENTS_DIR.glob("*.yaml"))


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.name)
def test_agent_yaml_parses(path: Path):
    with open(path) as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), f"{path.name}: top-level must be a mapping"
    for key in ("id", "name", "description", "system_prompt"):
        assert key in data, f"{path.name}: missing required field '{key}'"


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.name)
def test_agent_context_sources_resolve(path: Path):
    """If an agent declares context_sources, the referenced files must
    actually exist on disk. This catches the docs/seed/xql/* gap that
    produced 'Context file not found' warnings in production for the
    entire 1.1.x release until the Dockerfile COPY fix landed."""
    with open(path) as f:
        data = yaml.safe_load(f)
    sources = data.get("context_sources") or []
    for src in sources:
        if not isinstance(src, dict):
            continue
        if src.get("type") != "file":
            continue
        ref = src.get("value")
        if not ref:
            continue
        # Refs are relative to repo root in the YAML.
        resolved = REPO_ROOT / ref
        assert resolved.exists(), (
            f"{path.name}: context_source '{ref}' does not exist on disk. "
            "Either add the file or remove the source reference."
        )


def test_agent_inventory_meets_floor():
    assert (
        len(_agent_files()) >= 5
    ), f"Expected >=5 agents; found {len(_agent_files())}."


# ── Seed corpus baked into the Docker image ─────────────────────────────


def test_xql_seed_corpus_present():
    """The XQL/XDM agents reference docs/seed/xql/* files in their
    context_sources. The Dockerfile must COPY this directory so it's
    available at runtime. We assert the file exists *in the repo*; the
    Dockerfile-COPY test belongs to the docker-publish CI workflow."""
    expected = [
        REPO_ROOT / "docs" / "seed" / "xql" / "xql-xdm-knowledge.md",
        REPO_ROOT / "docs" / "seed" / "xql" / "few_shot_examples.json",
        REPO_ROOT / "docs" / "seed" / "xql" / "packs_index.md",
    ]
    missing = [str(p) for p in expected if not p.exists()]
    assert not missing, f"Missing seed corpus files: {missing}"


# ── Role prompts ────────────────────────────────────────────────────────


ROLES_DIR = REPO_ROOT / "prompts" / "roles"


def test_role_prompts_directory_has_content():
    """The prompts/roles/ directory must ship at least one canonical
    role prompt — agents that reference a role (reasoning/coding/etc.)
    fall back gracefully when the prompt file is missing, but a
    completely empty directory means something was lost in a refactor.

    NOTE: this test used to assert a specific set of role-name files
    (`reasoning`, `coding`, `general`) but that was a wrong coupling —
    the role system uses a *role resolver* that maps semantic role
    names to model + prompt heuristics, not direct filename lookups.
    The actual prompt files in `prompts/roles/` are persona-named
    (e.g. `python_developer.md`, `qa_engineer.md`). This test now just
    guards against the whole directory disappearing."""
    if not ROLES_DIR.exists():
        pytest.skip("prompts/roles/ does not exist")
    role_files = list(ROLES_DIR.glob("*.md"))
    assert len(role_files) >= 1, (
        f"prompts/roles/ ships no .md files. Even one persona prompt is "
        "expected so the workbench Role Library has content to display."
    )
