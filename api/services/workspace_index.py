#!/usr/bin/env python3
"""
WorkspaceIndex — durable worklist state co-located in a Workspace (C3).

The pattern this enables: an autonomous agent enumerates a list of items
(sites, files, topics), processes them one at a time — gather info, write a
per-item artifact — and records completion **in a durable index on the local
filesystem**. Because the index is the state, the loop is *resumable*: restart
it and it skips what's already done and continues. The filesystem artifact is
the checkpoint; no in-memory session is required.

Canonical state is JSON under the workspace at `.enclave/index/<name>.json`
(infra, out of the operator's content namespace). A human/Obsidian-facing
Markdown MOC can be rendered from it on demand (render_markdown) — checkboxes +
wikilinks to each item's artifact.

Item lifecycle:  pending → in_progress → done | error | skipped
Resume:          requeue_stale() flips any interrupted in_progress back to
                 pending, so next_pending() alone drives the whole loop.

See C3 of docs/plans/2026-07-09-fusion-autonomous-local-workspace-feature-request.md.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import fcntl  # POSIX advisory file locking (serializes concurrent claims)
except ImportError:  # non-POSIX: degrade to no-op lock
    fcntl = None

from pydantic import BaseModel, Field

from .workspace import Workspace, WorkspaceError

INDEX_SUBDIR = ".enclave/index"
_VALID_STATUS = {"pending", "in_progress", "done", "error", "skipped"}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", s.lower()).strip("-")[:80] or "index"


class IndexItem(BaseModel):
    id: str
    title: str
    url: Optional[str] = None
    status: str = "pending"
    artifact: Optional[str] = None  # workspace-relative path to the produced note
    note: Optional[str] = None  # short status/error note
    updated_at: float = Field(default_factory=time.time)


class WorkspaceIndex:
    """A durable, ordered worklist bound to a Workspace."""

    def __init__(self, workspace: Workspace, name: str):
        self.ws = workspace
        self.name = name
        self.path = (self.ws.root / INDEX_SUBDIR / f"{_slug(name)}.json").resolve()
        # guard: index file must live inside the workspace root
        self.path.relative_to(self.ws.root)
        self._items: "Dict[str, IndexItem]" = {}
        self._order: List[str] = []
        self._load()

    # ── persistence ───
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._order = raw.get("order", [])
            self._items = {
                iid: IndexItem(**data) for iid, data in raw.get("items", {}).items()
            }
        except Exception:
            # a corrupt index must not brick the loop — start empty, overwrite on save
            self._items, self._order = {}, []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": self.name,
            "order": self._order,
            "items": {iid: it.model_dump() for iid, it in self._items.items()},
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # ── mutation ───
    def add_items(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        """Add items (each needs at least a title or url). Existing ids (by
        explicit id, else slug of url|title) are left untouched — so re-adding a
        list is idempotent and never resets completed work."""
        added = 0
        for raw in items:
            title = (raw.get("title") or raw.get("url") or "").strip()
            if not title:
                continue
            iid = str(raw.get("id") or _slug(raw.get("url") or title))
            if iid in self._items:
                continue
            self._items[iid] = IndexItem(
                id=iid, title=title, url=raw.get("url")
            )
            self._order.append(iid)
            added += 1
        if added:
            self._save()
        return {"added": added, "total": len(self._items)}

    def set_status(
        self,
        item_id: str,
        status: str,
        artifact: Optional[str] = None,
        note: Optional[str] = None,
    ) -> IndexItem:
        if status not in _VALID_STATUS:
            raise WorkspaceError(f"invalid status {status!r} (allowed: {_VALID_STATUS})")
        if item_id not in self._items:
            raise WorkspaceError(f"index item {item_id!r} not found")
        it = self._items[item_id]
        it.status = status
        if artifact is not None:
            it.artifact = artifact
        if note is not None:
            it.note = note
        it.updated_at = time.time()
        self._save()
        return it

    @contextmanager
    def _claim_lock(self):
        """Exclusive advisory lock so two concurrent /next requests can't claim
        the same item (the router runs sync handlers in a threadpool, and each
        request builds its own lock-free WorkspaceIndex)."""
        if fcntl is None:
            yield
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(".lock")
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def next_pending(self, claim: bool = True) -> Optional[IndexItem]:
        """First pending item in insertion order. When claim=True, mark it
        in_progress and persist before returning (so a crash leaves a resumable
        trail). The claim is serialized + re-reads from disk under a file lock so
        concurrent callers never double-claim one item."""
        if not claim:
            for iid in self._order:
                if self._items[iid].status == "pending":
                    return self._items[iid]
            return None
        with self._claim_lock():
            self._load()  # re-read under the lock to see other workers' claims
            for iid in self._order:
                it = self._items[iid]
                if it.status == "pending":
                    it.status = "in_progress"
                    it.updated_at = time.time()
                    self._save()
                    return it
            return None

    def requeue_stale(self) -> int:
        """Flip any in_progress item back to pending — call at loop start to
        resume cleanly after an interruption."""
        n = 0
        for it in self._items.values():
            if it.status == "in_progress":
                it.status = "pending"
                it.updated_at = time.time()
                n += 1
        if n:
            self._save()
        return n

    # ── queries ───
    def items(self, status: Optional[str] = None) -> List[IndexItem]:
        ordered = [self._items[i] for i in self._order]
        return [it for it in ordered if status is None or it.status == status]

    def counts(self) -> Dict[str, int]:
        c = {s: 0 for s in _VALID_STATUS}
        for it in self._items.values():
            c[it.status] = c.get(it.status, 0) + 1
        c["total"] = len(self._items)
        return c

    def is_complete(self) -> bool:
        return all(
            it.status in ("done", "skipped", "error") for it in self._items.values()
        ) and len(self._items) > 0

    # ── render ───
    def render_markdown(self, path: Optional[str] = None) -> str:
        """Render an Obsidian MOC (checkbox list + wikilinks to artifacts) and
        write it into the workspace via the policy-checked writer. Returns the
        workspace-relative path written."""
        out_path = path or f"{_slug(self.name)}.md"
        counts = self.counts()
        lines = [
            f"# {self.name} — index",
            "",
            f"> {counts.get('done',0)}/{counts['total']} done "
            f"· {counts.get('pending',0)} pending · {counts.get('error',0)} error",
            "",
        ]
        for it in self.items():
            checked = "x" if it.status == "done" else " "
            if it.artifact:
                link = f"[[{Path(it.artifact).with_suffix('').as_posix()}|{it.title}]]"
            else:
                link = it.title
            suffix = "" if it.status in ("done", "pending") else f" — {it.status}"
            if it.note and it.status in ("error", "skipped"):
                suffix += f" ({it.note})"
            lines.append(f"- [{checked}] {link}{suffix}")
        self.ws.write(out_path, "\n".join(lines) + "\n")
        return out_path
