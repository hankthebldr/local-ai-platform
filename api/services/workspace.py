#!/usr/bin/env python3
"""
Workspace — durable, named, policy-governed local directory runtime.

Where SandboxedFS (api/services/sandbox_fs.py) is an *ephemeral per-conversation*
boundary that is created and reaped, a Workspace is a *durable named binding* to
a real local directory on the host — a repo, the Obsidian vault, a scratch
project. It is the surface that lets long-running autonomous workflows "produce
and operate in local directories": make / read / edit / expand / search markdown
(and other) files, confined to the workspace root by the same traversal guard.

Closes C2 of docs/plans/2026-07-09-fusion-autonomous-local-workspace-feature-request.md.

Operations (verbs the operator asked for — make / edit / expand):
    make    → write(path, content)              create or overwrite a file
    edit    → edit(path, find, replace)         literal find/replace in a file
    expand  → expand(path, content, heading=)   append, or insert under a
                                                 markdown heading (## Section)
    plus    read · list · search · mkdir · delete · stats

Policy (WorkspacePolicy):
    read_only          — refuse every mutating op
    allowed_extensions — None = any; else a suffix allow-list (e.g. ["md"])
    max_file_size_mb   — cap on write size

The registry (WorkspaceRegistry) persists bindings to
<ENCLAVE_DATA_DIR>/workspaces/registry.json so they survive restarts.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..logging_config import logger


class WorkspaceError(Exception):
    """Base for workspace failures (path escape, policy violation, quota)."""


class WorkspaceViolation(WorkspaceError):
    """Path escapes the workspace root, or a read-only/extension rule is broken."""


class WorkspaceQuotaExceeded(WorkspaceError):
    """A write exceeds max_file_size_mb."""


# ── Models ────────────────────────────────────────────────────────────────


class WorkspacePolicy(BaseModel):
    read_only: bool = False
    allowed_extensions: Optional[List[str]] = None  # None = any extension
    max_file_size_mb: int = 10


class WorkspaceMeta(BaseModel):
    name: str
    root: str  # absolute local path
    policy: WorkspacePolicy = Field(default_factory=WorkspacePolicy)
    description: Optional[str] = None
    created_at: float = Field(default_factory=time.time)


# ── Workspace ─────────────────────────────────────────────────────────────


class Workspace:
    """A bound local directory with guarded, policy-checked file operations."""

    def __init__(self, meta: WorkspaceMeta):
        self.meta = meta
        self.root = Path(os.path.expanduser(meta.root)).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ── path guard ───
    def resolve(self, rel_path: str) -> Path:
        """Resolve a path relative to the workspace root; raise on escape.

        Absolute inputs are rejected outright — callers address files by a path
        relative to the workspace root, exactly like SandboxedFS.
        """
        if not rel_path or rel_path in (".", "./"):
            return self.root
        if rel_path.startswith(("/", "\\")):
            raise WorkspaceViolation(f"absolute path '{rel_path}' not allowed")
        candidate = (self.root / rel_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            raise WorkspaceViolation(f"path '{rel_path}' escapes workspace root")
        return candidate

    # ── policy checks ───
    def _require_writable(self) -> None:
        if self.meta.policy.read_only:
            raise WorkspaceViolation(f"workspace '{self.meta.name}' is read-only")

    def _check_extension(self, path: str) -> None:
        allowed = self.meta.policy.allowed_extensions
        if not allowed:
            return
        suffix = Path(path).suffix.lstrip(".").lower()
        if suffix not in [e.lower().lstrip(".") for e in allowed]:
            raise WorkspaceViolation(
                f"extension '.{suffix}' not allowed (allowed: {allowed})"
            )

    def _check_size(self, content: str) -> None:
        cap = self.meta.policy.max_file_size_mb * 1024 * 1024
        if len(content.encode("utf-8")) > cap:
            raise WorkspaceQuotaExceeded(
                f"content exceeds max_file_size_mb={self.meta.policy.max_file_size_mb}"
            )

    # ── read / list / search ───
    def read(self, path: str) -> str:
        p = self.resolve(path)
        if not p.is_file():
            raise FileNotFoundError(f"not found in workspace: {path}")
        return p.read_text(encoding="utf-8")

    def exists(self, path: str) -> bool:
        try:
            return self.resolve(path).exists()
        except WorkspaceViolation:
            return False

    def list(self, subdir: str = "", glob: str = "**/*") -> List[str]:
        base = self.resolve(subdir)
        if not base.exists():
            return []
        return sorted(
            p.relative_to(self.root).as_posix()
            for p in base.glob(glob)
            if p.is_file()
        )

    def search(
        self, query: str, glob: str = "**/*.md", max_results: int = 200
    ) -> List[Dict[str, Any]]:
        """Case-insensitive substring search across matching files. Returns
        {path, line, text} hits — the navigation primitive an agent needs
        before editing/expanding."""
        needle = query.lower()
        hits: List[Dict[str, Any]] = []
        for p in sorted(self.root.glob(glob)):
            if not p.is_file():
                continue
            try:
                for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                    if needle in line.lower():
                        hits.append(
                            {
                                "path": p.relative_to(self.root).as_posix(),
                                "line": i,
                                "text": line.strip()[:200],
                            }
                        )
                        if len(hits) >= max_results:
                            return hits
            except (UnicodeDecodeError, OSError):
                continue
        return hits

    # ── make / edit / expand ───
    def write(self, path: str, content: str) -> Dict[str, Any]:
        """make — create or overwrite a file."""
        self._require_writable()
        self._check_extension(path)
        self._check_size(content)
        p = self.resolve(path)
        existed = p.is_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"path": path, "action": "overwrote" if existed else "created",
                "bytes": len(content.encode("utf-8"))}

    def edit(self, path: str, find: str, replace: str, count: int = 0) -> Dict[str, Any]:
        """edit — literal find/replace. count=0 replaces all occurrences.
        Raises if `find` is absent so the agent never silently no-ops."""
        self._require_writable()
        current = self.read(path)
        occurrences = current.count(find)
        if occurrences == 0:
            raise WorkspaceError(f"find text not present in {path!r}; no edit made")
        updated = current.replace(find, replace) if count == 0 else current.replace(
            find, replace, count
        )
        self._check_size(updated)
        self.resolve(path).write_text(updated, encoding="utf-8")
        replaced = occurrences if count == 0 else min(count, occurrences)
        return {"path": path, "action": "edited", "replacements": replaced}

    def expand(
        self, path: str, content: str, heading: Optional[str] = None
    ) -> Dict[str, Any]:
        """expand — grow a markdown file. With `heading`, insert `content` at
        the end of that `## heading` section (before the next same-or-higher
        heading); without it, append to the end of the file. Creates the file
        if missing."""
        self._require_writable()
        self._check_extension(path)
        current = self.read(path) if self.exists(path) else ""

        if heading is None:
            joiner = "" if current.endswith("\n") or current == "" else "\n"
            updated = f"{current}{joiner}{content.rstrip()}\n"
            where = "appended"
        else:
            updated, where = _insert_under_heading(current, heading, content)

        self._check_size(updated)
        p = self.resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(updated, encoding="utf-8")
        return {"path": path, "action": "expanded", "where": where}

    # ── misc ───
    def mkdir(self, path: str) -> None:
        self._require_writable()
        self.resolve(path).mkdir(parents=True, exist_ok=True)

    def delete(self, path: str) -> None:
        self._require_writable()
        p = self.resolve(path)
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)

    def stats(self) -> Dict[str, Any]:
        files = [p for p in self.root.rglob("*") if p.is_file()]
        return {
            "name": self.meta.name,
            "root": str(self.root),
            "file_count": len(files),
            "total_bytes": sum(p.stat().st_size for p in files),
            "read_only": self.meta.policy.read_only,
        }


def _insert_under_heading(current: str, heading: str, content: str) -> tuple[str, str]:
    """Insert `content` at the end of the markdown section whose heading text
    matches `heading` (any level). If the heading isn't found, append a new
    `## heading` section at the end. Returns (new_text, where)."""
    lines = current.splitlines()
    target = heading.strip().lstrip("#").strip().lower()

    heading_re = re.compile(r"^(#{1,6})\s+(.*)$")
    start_idx = None
    start_level = None
    for i, line in enumerate(lines):
        m = heading_re.match(line)
        if m and m.group(2).strip().lower() == target:
            start_idx = i
            start_level = len(m.group(1))
            break

    if start_idx is None:
        # heading absent → append a fresh section
        joiner = "" if current.endswith("\n") or current == "" else "\n"
        new = f"{current}{joiner}\n## {heading.strip().lstrip('#').strip()}\n\n{content.rstrip()}\n"
        return new, "new-section"

    # find end of this section: next heading of same-or-higher level
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        m = heading_re.match(lines[j])
        if m and len(m.group(1)) <= start_level:
            end_idx = j
            break

    # trim trailing blanks inside the section, then insert
    insert_at = end_idx
    while insert_at - 1 > start_idx and lines[insert_at - 1].strip() == "":
        insert_at -= 1
    block = ["", *content.rstrip().splitlines()]
    new_lines = lines[:insert_at] + block + lines[insert_at:]
    return "\n".join(new_lines).rstrip() + "\n", "under-heading"


# ── Registry ──────────────────────────────────────────────────────────────


def _data_dir() -> Path:
    return Path(os.getenv("ENCLAVE_DATA_DIR", "./data"))


_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class WorkspaceRegistry:
    """Durable set of named Workspaces, persisted to
    <data>/workspaces/registry.json. Deregistering a workspace forgets the
    binding — it never deletes the operator's files."""

    def __init__(self, store_path: Optional[Path] = None):
        self.store_path = store_path or (_data_dir() / "workspaces" / "registry.json")
        self._metas: Dict[str, WorkspaceMeta] = {}
        self._load()

    def _load(self) -> None:
        if self.store_path.exists():
            try:
                raw = json.loads(self.store_path.read_text(encoding="utf-8"))
                for name, m in raw.items():
                    self._metas[name] = WorkspaceMeta(**m)
            except Exception as e:  # a corrupt store must not brick startup
                logger.warning("workspace registry load failed (%s); starting empty", e)

    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {n: m.model_dump() for n, m in self._metas.items()}
        tmp = self.store_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.store_path)

    def create(
        self,
        name: str,
        root: str,
        policy: Optional[WorkspacePolicy] = None,
        description: Optional[str] = None,
    ) -> Workspace:
        if not _NAME_RE.match(name):
            raise WorkspaceError(
                "workspace name must be lowercase alnum/._- and ≤64 chars"
            )
        if name in self._metas:
            raise WorkspaceError(f"workspace '{name}' already exists")
        meta = WorkspaceMeta(
            name=name,
            root=str(Path(os.path.expanduser(root)).resolve()),
            policy=policy or WorkspacePolicy(),
            description=description,
        )
        ws = Workspace(meta)  # resolves + ensures root exists
        self._metas[name] = meta
        self._save()
        logger.info("workspace created: %s -> %s", name, meta.root)
        return ws

    def get(self, name: str) -> Workspace:
        if name not in self._metas:
            raise WorkspaceError(f"workspace '{name}' not found")
        return Workspace(self._metas[name])

    def list(self) -> List[WorkspaceMeta]:
        return list(self._metas.values())

    def delete(self, name: str) -> None:
        if name not in self._metas:
            raise WorkspaceError(f"workspace '{name}' not found")
        del self._metas[name]
        self._save()


_registry: Optional[WorkspaceRegistry] = None


def get_workspace_registry() -> WorkspaceRegistry:
    """Process-wide WorkspaceRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = WorkspaceRegistry()
    return _registry
