#!/usr/bin/env python3
"""
Project Service — CRUD + bundle operations for project records.

Projects are YAML-backed bundles that group workflows, agents, MCP
server references, plugins, models, documents, and chat sessions.

Storage layout: data/projects/<id>.yaml
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ..logging_config import logger
from ..models.project_models import (
    ProjectArtifacts,
    ProjectCreate,
    ProjectDefinition,
    ProjectUpdate,
)

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _projects_dir() -> Path:
    return Path(os.getenv("PROJECTS_DIR", "data/projects"))


def _safe_id(value: str) -> bool:
    return bool(SAFE_ID.match(value or ""))


class ProjectService:
    """CRUD + bundle export/import for project records."""

    def __init__(self, projects_dir: Optional[str] = None):
        self._dir = Path(projects_dir) if projects_dir else _projects_dir()

    # ── CRUD ────────────────────────────────────────────────────────

    def list_projects(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not self._dir.exists():
            return out
        for path in sorted(self._dir.glob("*.yaml")):
            data = self._read(path)
            if data is None:
                continue
            out.append(self._summary(data))
        return out

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        if not _safe_id(project_id):
            raise ValueError("invalid project id")
        path = self._dir / f"{project_id}.yaml"
        if not path.exists():
            return None
        return self._read(path)

    def create_project(self, body: ProjectCreate) -> Dict[str, Any]:
        path = self._target_path(body.id)
        if path.exists():
            raise FileExistsError(body.id)
        now = datetime.now(timezone.utc)
        defn = ProjectDefinition(
            **body.model_dump(),
            created_at=now,
            updated_at=now,
        )
        self._write(path, defn)
        logger.info("Created project %s", body.id)
        return defn.model_dump(mode="json")

    def update_project(self, project_id: str, patch: ProjectUpdate) -> Dict[str, Any]:
        if not _safe_id(project_id):
            raise ValueError("invalid project id")
        path = self._dir / f"{project_id}.yaml"
        if not path.exists():
            raise KeyError(project_id)
        cur = self._read(path)
        cur_def = ProjectDefinition(**cur)
        data = cur_def.model_dump(mode="json")
        for k, v in patch.model_dump(exclude_unset=True).items():
            if k == "artifacts" and v is not None:
                # Replace the artifact bag wholesale when provided.
                data["artifacts"] = v if isinstance(v, dict) else v.model_dump()
            else:
                data[k] = v
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        defn = ProjectDefinition(**data)
        self._write(path, defn)
        return defn.model_dump(mode="json")

    def delete_project(self, project_id: str) -> bool:
        if not _safe_id(project_id):
            raise ValueError("invalid project id")
        path = self._dir / f"{project_id}.yaml"
        if not path.exists():
            return False
        path.unlink()
        return True

    # ── Artifact membership helpers ────────────────────────────────

    def add_artifact(
        self, project_id: str, kind: str, artifact_id: str
    ) -> Dict[str, Any]:
        """Append an artifact reference to a project (idempotent)."""
        kind = self._normalise_kind(kind)
        if not _safe_id(artifact_id):
            raise ValueError("invalid artifact id")
        cur = self.get_project(project_id)
        if cur is None:
            raise KeyError(project_id)
        artifacts = cur.get("artifacts", {}) or {}
        bag = list(artifacts.get(kind, []) or [])
        if artifact_id not in bag:
            bag.append(artifact_id)
        artifacts[kind] = bag
        return self.update_project(
            project_id,
            ProjectUpdate(artifacts=ProjectArtifacts(**artifacts)),
        )

    def remove_artifact(
        self, project_id: str, kind: str, artifact_id: str
    ) -> Dict[str, Any]:
        kind = self._normalise_kind(kind)
        cur = self.get_project(project_id)
        if cur is None:
            raise KeyError(project_id)
        artifacts = cur.get("artifacts", {}) or {}
        bag = [a for a in (artifacts.get(kind, []) or []) if a != artifact_id]
        artifacts[kind] = bag
        return self.update_project(
            project_id,
            ProjectUpdate(artifacts=ProjectArtifacts(**artifacts)),
        )

    # ── Context workspace bind (C3 — Docs "Bind context directory") ──

    def bind_context_workspace(
        self, project_id: str, root: Optional[str] = None
    ) -> Dict[str, Any]:
        """Bind (or reuse) a durable docs Workspace for this project.

        - Absent ``root`` → ``data/projects/<id>/docs/`` (the local default).
        - An explicit path that is (or lives inside) an Obsidian vault — detected
          by a ``.obsidian`` marker at the path or an ancestor — is re-rooted at
          ``<vault>/00-Inbox/``, enforcing the operator's 00-Inbox-only write rule
          purely through workspace path containment (no new policy machinery).
        - Registers workspace ``proj-<id>`` in the existing registry (idempotent —
          an existing binding is reused), sets ``ProjectDefinition.context_workspace``,
          and idempotently seeds the skeleton (index.md MOC, specs/, plans/,
          notes/status.md, decisions/log.md with ``##`` headings for expand()).

        Idempotent: calling twice yields the same workspace and never clobbers
        existing seeded files.
        """
        from .workspace import WorkspaceError, get_workspace_registry

        proj = self.get_project(project_id)
        if proj is None:
            raise KeyError(project_id)

        ws_name = f"proj-{project_id}".lower()
        # Workspace names are lowercase alnum/._- and ≤64 chars.
        if len(ws_name) > 64:
            raise ValueError("project id too long to derive a workspace name")

        resolved_root = self._resolve_docs_root(project_id, root)

        registry = get_workspace_registry()
        existing = {m.name for m in registry.list()}
        if ws_name in existing:
            ws = registry.get(ws_name)
        else:
            try:
                ws = registry.create(
                    ws_name,
                    str(resolved_root),
                    description=f"Docs context for project {project_id}",
                )
            except WorkspaceError as exc:
                raise ValueError(str(exc))

        self._seed_skeleton(ws, proj.get("name") or project_id)

        # Persist the binding on the project record.
        path = self._dir / f"{project_id}.yaml"
        cur_def = ProjectDefinition(**self._read(path))
        data = cur_def.model_dump(mode="json")
        data["context_workspace"] = ws_name
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write(path, ProjectDefinition(**data))

        return {
            "project_id": project_id,
            "workspace": ws_name,
            "root": str(ws.root),
            "seeded": True,
        }

    def _resolve_docs_root(self, project_id: str, root: Optional[str]) -> Path:
        """Resolve the docs workspace root, applying the vault→00-Inbox re-root."""
        if not root or not str(root).strip():
            return (self._dir / project_id / "docs").resolve()
        candidate = Path(os.path.expanduser(str(root).strip())).resolve()
        vault = self._detect_vault(candidate)
        if vault is not None:
            return (vault / "00-Inbox").resolve()
        return candidate

    @staticmethod
    def _detect_vault(path: Path) -> Optional[Path]:
        """Return the vault root if ``path`` is (or is inside) an Obsidian vault,
        identified by a ``.obsidian`` directory at the path or any ancestor."""
        for base in (path, *path.parents):
            if (base / ".obsidian").is_dir():
                return base
        return None

    def _seed_skeleton(self, ws: Any, project_name: str) -> None:
        """Idempotently seed the docs skeleton. Never overwrites existing files."""
        ws.mkdir("specs")
        ws.mkdir("plans")
        if not ws.exists("index.md"):
            ws.write(
                "index.md",
                f"# {project_name} — Map of Content\n\n"
                "## Specs\n\n## Plans\n\n## Notes\n\n## Decisions\n",
            )
        if not ws.exists("notes/status.md"):
            ws.write("notes/status.md", "# Status\n\n## Current\n\n## History\n")
        if not ws.exists("decisions/log.md"):
            ws.write("decisions/log.md", "# Decision Log\n\n## Decisions\n")

    # ── Bundle export ──────────────────────────────────────────────

    def export_bundle(self, project_id: str) -> Dict[str, Any]:
        """
        Export a project together with the YAML of every workflow and
        agent it references. MCP and plugin entries are exported as
        refs only (their config lives outside the project).
        """

        proj = self.get_project(project_id)
        if proj is None:
            raise FileNotFoundError(project_id)
        artifacts = proj.get("artifacts", {}) or {}

        workflows_dir = Path(os.getenv("WORKFLOWS_DIR", "./workflows"))
        agents_dir = Path("agents")

        workflows = []
        for wid in artifacts.get("workflows", []) or []:
            wp = workflows_dir / f"{wid}.yaml"
            if wp.exists():
                try:
                    workflows.append(yaml.safe_load(wp.read_text(encoding="utf-8")))
                except Exception:  # noqa: BLE001
                    continue

        agents = []
        for aid in artifacts.get("agents", []) or []:
            ap = agents_dir / f"{aid}.yaml"
            if ap.exists():
                try:
                    agents.append(yaml.safe_load(ap.read_text(encoding="utf-8")))
                except Exception:  # noqa: BLE001
                    continue

        return {
            "schema": "enclave.project-bundle/v1",
            "project": proj,
            "workflows": workflows,
            "agents": agents,
        }

    def import_bundle(
        self, bundle: Dict[str, Any], overwrite: bool = False
    ) -> Dict[str, Any]:
        """Install a project bundle: project record + workflows + agents."""
        if not isinstance(bundle, dict):
            raise ValueError("bundle must be a JSON object")
        if bundle.get("schema") not in (None, "enclave.project-bundle/v1"):
            raise ValueError("unknown bundle schema")
        proj = bundle.get("project") or {}
        if not isinstance(proj, dict) or not _safe_id(proj.get("id") or ""):
            raise ValueError("bundle missing valid project")

        # Install referenced workflows + agents through their existing
        # index service so categorisation stays consistent.
        from .workflow_index import get_workflow_index

        wf_index = get_workflow_index()
        installed_workflows: List[str] = []
        for wf in bundle.get("workflows") or []:
            if not isinstance(wf, dict):
                continue
            try:
                wf_index.import_bundle(
                    {
                        "schema": "enclave.workflow-bundle/v1",
                        "workflow": wf,
                        "agents": [],
                    },
                    overwrite=overwrite,
                )
                installed_workflows.append(wf.get("id"))
            except FileExistsError:
                continue  # respect overwrite=False

        agents_dir = Path("agents")
        agents_dir.mkdir(parents=True, exist_ok=True)
        installed_agents: List[str] = []
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

        # Persist the project last so its artifact refs are valid.
        path = self._target_path(proj["id"])
        if path.exists() and not overwrite:
            raise FileExistsError(proj["id"])
        defn = ProjectDefinition(**proj)
        self._write(path, defn)
        return {
            "imported": True,
            "project_id": defn.id,
            "workflows_installed": installed_workflows,
            "agents_installed": installed_agents,
        }

    # ── helpers ────────────────────────────────────────────────────

    def _summary(self, data: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = data.get("artifacts", {}) or {}
        return {
            "id": data["id"],
            "name": data.get("name", data["id"]),
            "description": data.get("description") or "",
            "category": data.get("category") or "general",
            "tags": data.get("tags") or [],
            "counts": {
                k: len(artifacts.get(k, []) or [])
                for k in (
                    "workflows",
                    "agents",
                    "mcp_servers",
                    "plugins",
                    "models",
                    "documents",
                    "chats",
                )
            },
            "updated_at": data.get("updated_at"),
        }

    def _read(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read project %s: %s", path, exc)
            return None

    def _write(self, path: Path, defn: ProjectDefinition) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(
            defn.model_dump(mode="json", exclude_none=True),
            sort_keys=False,
            allow_unicode=True,
        )
        path.write_text(text, encoding="utf-8")

    def _target_path(self, project_id: str) -> Path:
        if not _safe_id(project_id):
            raise ValueError("invalid project id")
        self._dir.mkdir(parents=True, exist_ok=True)
        target = (self._dir / f"{project_id}.yaml").resolve()
        try:
            target.relative_to(self._dir.resolve())
        except ValueError:
            raise ValueError("project path escapes projects/")
        return target

    def _normalise_kind(self, kind: str) -> str:
        kind = (kind or "").lower()
        if kind not in {
            "workflows",
            "agents",
            "mcp_servers",
            "plugins",
            "models",
            "documents",
            "chats",
        }:
            raise ValueError(f"unknown artifact kind: {kind}")
        return kind


# ── Module singleton ────────────────────────────────────────────────────

_default_service: Optional[ProjectService] = None


def get_project_service() -> ProjectService:
    global _default_service
    if _default_service is None:
        _default_service = ProjectService()
    return _default_service
