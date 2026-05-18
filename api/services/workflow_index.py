#!/usr/bin/env python3
"""
Workflow Index Service

Indexes the contents of the workflows/ directory, extracts metadata
(category / tags / referenced roles, skills, tools, MCPs), and builds
import / export bundles so workflows can be shared between Enclave
instances together with their dependencies.

The "category" field on a workflow is derived from a small set of
known tags (security, devops, data, content, code, research, …). If a
workflow does not declare a category or recognised tag it is bucketed
under "general".
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from ..logging_config import logger

KNOWN_CATEGORIES: List[str] = [
    "security",
    "devops",
    "data",
    "code",
    "content",
    "research",
    "automation",
    "general",
]

# Map tag -> canonical category
_TAG_TO_CATEGORY = {
    "xsiam": "security",
    "xdr": "security",
    "cortex": "security",
    "soc": "security",
    "siem": "security",
    "infra": "devops",
    "k8s": "devops",
    "ci": "devops",
    "release": "devops",
    "etl": "data",
    "parsing": "data",
    "normalization": "data",
    "schema": "data",
    "code": "code",
    "coding": "code",
    "refactor": "code",
    "writing": "content",
    "blog": "content",
    "marketing": "content",
    "research": "research",
    "investigation": "research",
    "automation": "automation",
}


def _categorize(workflow: Dict[str, Any]) -> str:
    # Look at top-level AND nested metadata.* — workflows shipped over
    # time have used both shapes interchangeably.
    metadata = workflow.get("metadata") or {}
    explicit = workflow.get("category") or (
        metadata.get("category") if isinstance(metadata, dict) else None
    )
    if isinstance(explicit, str) and explicit in KNOWN_CATEGORIES:
        return explicit
    candidate_tags: List[Any] = []
    for src in (
        workflow.get("tags"),
        metadata.get("tags") if isinstance(metadata, dict) else None,
    ):
        if isinstance(src, list):
            candidate_tags.extend(src)
    for t in candidate_tags:
        if not isinstance(t, str):
            continue
        cat = _TAG_TO_CATEGORY.get(t.lower())
        if cat:
            return cat
    wfid = (workflow.get("id") or "").lower()
    for token, cat in _TAG_TO_CATEGORY.items():
        if token in wfid:
            return cat
    return "general"


def _safe_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value or ""))


def _read_yaml(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse %s: %s", path, exc)
        return None


def _extract_references(workflow: Dict[str, Any]) -> Dict[str, Set[str]]:
    """
    Scan a workflow definition for references to:
      - role / model names
      - plugin tool ids (plugin__tool format)
      - MCP servers (mcp__server format)
      - agent ids
    Returns a dict of typed reference sets.
    """
    refs: Dict[str, Set[str]] = {
        "roles": set(),
        "models": set(),
        "plugins": set(),
        "mcp_servers": set(),
        "agents": set(),
        "skills": set(),
    }
    defaults = workflow.get("defaults") or {}
    if defaults.get("role"):
        refs["roles"].add(str(defaults["role"]))
    if defaults.get("model"):
        refs["models"].add(str(defaults["model"]))

    for step in workflow.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("role"):
            refs["roles"].add(str(step["role"]))
        if step.get("model"):
            refs["models"].add(str(step["model"]))
        if step.get("agent"):
            refs["agents"].add(str(step["agent"]))
        for tool in step.get("tools") or []:
            if isinstance(tool, dict):
                tid = tool.get("id") or tool.get("name")
            else:
                tid = tool
            if not isinstance(tid, str):
                continue
            if tid.startswith("mcp__"):
                # mcp__<server>__<tool>
                parts = tid.split("__", 2)
                if len(parts) >= 2:
                    refs["mcp_servers"].add(parts[1])
            elif "__" in tid:
                refs["plugins"].add(tid.split("__", 1)[0])
        for skill in step.get("skills") or []:
            if isinstance(skill, str):
                refs["skills"].add(skill)
    return refs


class WorkflowIndexService:
    """Catalogue + import/export for workflows/."""

    def __init__(
        self,
        workflows_dir: Optional[str] = None,
        private_dir: Optional[str] = None,
    ):
        self._dir = Path(workflows_dir or os.getenv("WORKFLOWS_DIR", "./workflows"))
        # Private overlay — same convention WorkflowEngine uses. When the
        # same id exists in both, the private copy wins (loaded second).
        self._private_dir = Path(
            private_dir or os.getenv("WORKFLOWS_PRIVATE_DIR", "./workflows-private")
        )

    # ── catalogue ───────────────────────────────────────────────────

    def build_index(self) -> Dict[str, Any]:
        """Return a categorised view of all workflow YAML files."""
        items: List[Dict[str, Any]] = []
        categories: Dict[str, int] = {}
        for entry in self._iter_workflow_files():
            workflow = _read_yaml(entry)
            if workflow is None:
                continue
            cat = _categorize(workflow)
            refs = _extract_references(workflow)
            source = self._source_for(entry)
            summary = {
                "id": workflow.get("id") or entry.stem,
                "name": workflow.get("name") or workflow.get("id") or entry.stem,
                "description": workflow.get("description") or "",
                "version": workflow.get("version") or "",
                "category": cat,
                "tags": workflow.get("tags") or [],
                "steps": len(workflow.get("steps") or []),
                "file": (
                    str(entry.relative_to(self._dir.parent))
                    if entry.is_relative_to(self._dir.parent)
                    else str(entry)
                ),
                "source": source,
                "references": {k: sorted(v) for k, v in refs.items()},
            }
            items.append(summary)
            categories[cat] = categories.get(cat, 0) + 1

        items.sort(key=lambda x: (x["category"], x["name"].lower()))
        return {
            "categories": [
                {"id": cat, "count": categories.get(cat, 0)}
                for cat in KNOWN_CATEGORIES
                if categories.get(cat, 0) > 0
            ],
            "workflows": items,
            "total": len(items),
        }

    # ── bundle export ───────────────────────────────────────────────

    def export_bundle(self, workflow_id: str) -> Dict[str, Any]:
        """
        Build a portable bundle for the named workflow.

        Bundle shape:
          { "workflow": <yaml dict>,
            "agents":   [<agent yaml dicts referenced>],
            "metadata": { "category": ..., "references": ... } }
        """
        if not _safe_id(workflow_id):
            raise ValueError("invalid workflow id")
        # Honor the overlay: prefer private if both exist.
        private_target = self._private_dir / f"{workflow_id}.yaml"
        public_target = self._dir / f"{workflow_id}.yaml"
        target = private_target if private_target.exists() else public_target
        if not target.exists():
            raise FileNotFoundError(workflow_id)
        workflow = _read_yaml(target)
        if workflow is None:
            raise ValueError("workflow file is not valid YAML")
        refs = _extract_references(workflow)
        agents = []
        agents_dir = Path("agents")
        for agent_id in refs["agents"]:
            ap = agents_dir / f"{agent_id}.yaml"
            if ap.exists():
                data = _read_yaml(ap)
                if data is not None:
                    agents.append(data)
        return {
            "schema": "enclave.workflow-bundle/v1",
            "workflow": workflow,
            "agents": agents,
            "metadata": {
                "category": _categorize(workflow),
                "references": {k: sorted(v) for k, v in refs.items()},
            },
        }

    # ── bundle import ──────────────────────────────────────────────

    def import_bundle(
        self, bundle: Dict[str, Any], overwrite: bool = False
    ) -> Dict[str, Any]:
        """Install a workflow bundle (workflow + referenced agents)."""
        if not isinstance(bundle, dict):
            raise ValueError("bundle must be a JSON object")
        if bundle.get("schema") not in (None, "enclave.workflow-bundle/v1"):
            raise ValueError("unknown bundle schema")
        workflow = bundle.get("workflow")
        if not isinstance(workflow, dict):
            raise ValueError("bundle missing 'workflow' object")
        wf_id = workflow.get("id")
        if not isinstance(wf_id, str) or not _safe_id(wf_id):
            raise ValueError("workflow id missing or unsafe")

        self._dir.mkdir(parents=True, exist_ok=True)
        target = (self._dir / f"{wf_id}.yaml").resolve()
        try:
            target.relative_to(self._dir.resolve())
        except ValueError:
            raise ValueError("workflow path escapes workflows/")

        if target.exists() and not overwrite:
            raise FileExistsError(wf_id)

        target.write_text(
            yaml.safe_dump(workflow, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        installed_agents: List[str] = []
        agents_dir = Path("agents")
        agents_dir.mkdir(parents=True, exist_ok=True)
        for agent in bundle.get("agents") or []:
            if not isinstance(agent, dict):
                continue
            aid = agent.get("id")
            if not isinstance(aid, str) or not _safe_id(aid):
                continue
            ap = (agents_dir / f"{aid}.yaml").resolve()
            try:
                ap.relative_to(agents_dir.resolve())
            except ValueError:
                continue
            if ap.exists() and not overwrite:
                continue
            ap.write_text(
                yaml.safe_dump(agent, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            installed_agents.append(aid)

        return {
            "imported": True,
            "workflow_id": wf_id,
            "agents_installed": installed_agents,
        }

    # ── helpers ────────────────────────────────────────────────────

    def _iter_workflow_files(self):
        """Yield workflow files from public + private overlay.

        When the same stem exists in both directories, the private copy
        wins — matching the WorkflowEngine.resolve_workflow_path contract.
        """
        seen: Dict[str, Path] = {}
        # Public first so private can override by stem.
        for root in (self._dir, self._private_dir):
            if not root.exists():
                continue
            for child in sorted(root.iterdir()):
                if child.suffix in (".yaml", ".yml") and child.is_file():
                    seen[child.stem] = child
        for stem in sorted(seen):
            yield seen[stem]

    def _source_for(self, path: Path) -> str:
        try:
            if path.is_relative_to(self._private_dir):
                return "private"
        except (AttributeError, ValueError):
            pass
        return "public"


# ── classify a discovered HF model into workflow roles ──────────────────

ROLE_PATTERNS: List[Tuple[str, List[str]]] = [
    (
        "coding",
        ["code", "coder", "starcoder", "deepseek-coder", "qwen-coder", "wizardcoder"],
    ),
    ("reasoning", ["r1", "reason", "qwq", "deepseek-r", "o1", "thinker", "reflection"]),
    (
        "uncensored",
        ["abliterated", "uncensored", "dolphin", "unsensored", "wizardlm-unc"],
    ),
    ("fast", ["1b", "1.5b", "1.8b", "3b", "phi-mini", "tinyllama", "gemma-2b"]),
    ("general", ["instruct", "chat", "general", "assistant"]),
]


def classify_workflow_roles(model_entry: Dict[str, Any]) -> List[str]:
    """
    Return the list of workflow roles a discovered model fits.
    A model can map to several roles (e.g. coding AND reasoning).
    """
    name = " ".join(
        str(model_entry.get(k, "") or "") for k in ("repo_id", "name", "pipeline_tag")
    ).lower()
    tags = " ".join(str(t).lower() for t in model_entry.get("tags") or [])
    haystack = f"{name} {tags}"
    roles: List[str] = []
    for role, tokens in ROLE_PATTERNS:
        if any(tok in haystack for tok in tokens):
            roles.append(role)
    if not roles:
        roles.append("general")
    if model_entry.get("is_abliterated") and "uncensored" not in roles:
        roles.append("uncensored")
    return roles


# ── Module singleton ────────────────────────────────────────────────────

_default_service: Optional[WorkflowIndexService] = None


def get_workflow_index() -> WorkflowIndexService:
    global _default_service
    if _default_service is None:
        _default_service = WorkflowIndexService()
    return _default_service
