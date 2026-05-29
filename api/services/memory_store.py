"""
Memory Store — durable cross-run memory for kind=consolidate steps.

Three stores, all local files (no cloud, no telemetry — same posture as the
rest of Enclave):

  playbooks/<name>.md
      Human-readable, append-friendly operating rules. The canonical store
      for "what did we learn that should change future runs". An operator can
      read, edit, or git-commit a playbook directly.

  memory/semantic/<concept>.md
      Distilled facts about a concept (e.g. "the canonical XDM timestamp is
      data_received_time"). Same on-disk shape as a playbook, keyed by concept.

  memory/episodic/<key>.jsonl
      Append-only log of run digests. Each consolidate writes one JSON record
      (run_id, timestamp, content). Retrieval is recency-ordered for now;
      similarity search via the RAG pipeline is a follow-up.

All writes are atomic (tmp + os.replace) so a crash mid-write never corrupts
a store. The merge strategies for the markdown stores:

  replace            — overwrite the file with the new content
  append             — append the new content under a timestamped heading
  append_with_dedup  — append, but skip blocks already present (normalized
                       line comparison) so re-running a workflow doesn't
                       duplicate rules it already wrote
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..logging_config import logger

# Default root for all memory stores. Override via MEMORY_DATA_DIR — the ralph
# loop (Phase 5) points this at a per-repo .enclave/ directory.
DEFAULT_MEMORY_DIR = os.getenv("MEMORY_DATA_DIR", "./data")

VALID_TARGETS = ("playbook", "semantic", "episodic")
VALID_STRATEGIES = ("replace", "append", "append_with_dedup")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _normalize_block(text: str) -> str:
    """Normalize a block for dedup comparison: collapse internal whitespace
    runs, lowercase, drop blank lines. Two blocks that differ only in
    whitespace/case are duplicates."""
    lines = [" ".join(ln.split()).lower() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


class MemoryStore:
    """File-backed memory across the three stores.

    Stateless beyond the base directory — safe to construct per-step or share
    one instance. All reads return "" / [] for missing stores rather than
    raising, so a first run against an empty store just sees empty memory.
    """

    def __init__(self, base_dir: Optional[str] = None):
        # Read the env at construction (not module import) so the base dir
        # honors a runtime override — the ralph loop repoints MEMORY_DATA_DIR
        # per-repo, and tests isolate via monkeypatch.
        self.base = Path(base_dir or os.getenv("MEMORY_DATA_DIR", "./data"))

    # ── Path helpers ──────────────────────────────────────────────────

    def playbook_path(self, name: str) -> Path:
        return self.base / "playbooks" / f"{_safe_name(name)}.md"

    def semantic_path(self, concept: str) -> Path:
        return self.base / "memory" / "semantic" / f"{_safe_name(concept)}.md"

    def episodic_path(self, key: str) -> Path:
        return self.base / "memory" / "episodic" / f"{_safe_name(key)}.jsonl"

    # ── Listings (Memory tab UI) ──────────────────────────────────────

    def list_playbooks(self) -> List[Dict[str, Any]]:
        """All playbook files with name + size + modified timestamp."""
        return _list_markdown_dir(self.base / "playbooks")

    def list_semantic(self) -> List[Dict[str, Any]]:
        """All semantic-concept files with name + size + modified timestamp."""
        return _list_markdown_dir(self.base / "memory" / "semantic")

    def list_episodic(self) -> List[Dict[str, Any]]:
        """All episodic log keys with record count, size, modified timestamp."""
        d = self.base / "memory" / "episodic"
        if not d.is_dir():
            return []
        out: List[Dict[str, Any]] = []
        for p in sorted(d.glob("*.jsonl")):
            try:
                stat = p.stat()
                # Cheap record count — just count non-empty lines.
                with open(p, "r", encoding="utf-8") as f:
                    record_count = sum(1 for line in f if line.strip())
            except OSError:
                continue
            out.append(
                {
                    "name": p.stem,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                    "record_count": record_count,
                }
            )
        return out

    # ── Reads ─────────────────────────────────────────────────────────

    def read_playbook(self, name: str) -> str:
        return _read_text(self.playbook_path(name))

    def read_semantic(self, concept: str) -> str:
        return _read_text(self.semantic_path(concept))

    def read_episodic(self, key: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the most recent `limit` episodic records (newest last)."""
        path = self.episodic_path(key)
        if not path.exists():
            return []
        records: List[Dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError as exc:
            logger.warning("episodic read failed for %s: %s", key, exc)
            return []
        return records[-limit:] if limit and limit > 0 else records

    def read_episodic_digest(self, key: str, limit: int = 10) -> str:
        """Human/LLM-readable digest of recent episodic records — what a step
        sees when it declares `$memory.episodic.<key>` as an input."""
        records = self.read_episodic(key, limit=limit)
        if not records:
            return ""
        chunks = []
        for rec in records:
            ts = rec.get("timestamp", "?")
            run_id = rec.get("run_id", "?")
            content = rec.get("content", "")
            chunks.append(f"### {ts} (run {run_id})\n{content}")
        return "\n\n".join(chunks)

    # ── Writes ────────────────────────────────────────────────────────

    def write_playbook(
        self, name: str, content: str, strategy: str = "append_with_dedup"
    ) -> str:
        return self._write_markdown(self.playbook_path(name), content, strategy)

    def write_semantic(
        self, concept: str, content: str, strategy: str = "append_with_dedup"
    ) -> str:
        return self._write_markdown(self.semantic_path(concept), content, strategy)

    def append_episodic(
        self, key: str, content: str, run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Append one record to the episodic log. Returns the written record."""
        path = self.episodic_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": _utcnow_iso(),
            "run_id": run_id,
            "content": content,
        }
        # Append is inherently non-atomic for JSONL, but a torn final line is
        # tolerable: read_episodic skips unparseable lines. We open in append
        # mode so concurrent writers don't clobber each other's records.
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except OSError as exc:
            logger.warning("episodic append failed for %s: %s", key, exc)
        return record

    # ── Internal ──────────────────────────────────────────────────────

    def _write_markdown(self, path: Path, content: str, strategy: str) -> str:
        """Apply a merge strategy and write. Returns the resulting file body."""
        if strategy not in VALID_STRATEGIES:
            raise ValueError(
                f"unknown merge strategy {strategy!r} (valid: {VALID_STRATEGIES})"
            )
        existing = _read_text(path)

        if strategy == "replace" or not existing.strip():
            body = content.rstrip() + "\n"
            _atomic_write(path, body)
            return body

        heading = f"\n\n## Consolidated {_utcnow_iso()}\n\n"

        if strategy == "append":
            body = existing.rstrip() + heading + content.rstrip() + "\n"
            _atomic_write(path, body)
            return body

        # append_with_dedup — split the new content into blocks (by blank line)
        # and only append blocks whose normalized form isn't already present.
        existing_norm = _normalize_block(existing)
        new_blocks = [b for b in _split_blocks(content) if b.strip()]
        novel = [b for b in new_blocks if _normalize_block(b) not in existing_norm]
        if not novel:
            logger.info("playbook/semantic dedup: no novel blocks to append")
            return existing
        body = existing.rstrip() + heading + "\n\n".join(novel).rstrip() + "\n"
        _atomic_write(path, body)
        return body


def _safe_name(name: str) -> str:
    """Reduce an arbitrary store name to a filesystem-safe slug.

    Prevents path traversal (no slashes, no ..) and keeps names tidy. Empty
    or fully-stripped names fall back to 'default'."""
    keep = []
    for ch in (name or "").strip():
        if ch.isalnum() or ch in ("-", "_"):
            keep.append(ch)
        elif ch in (" ", ".", "/"):
            keep.append("_")
    slug = "".join(keep).strip("_")
    return slug or "default"


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("memory read failed for %s: %s", path, exc)
        return ""


def _split_blocks(text: str) -> List[str]:
    """Split text into blocks on blank lines, preserving each block's lines."""
    blocks: List[str] = []
    current: List[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                blocks.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _list_markdown_dir(d: Path) -> List[Dict[str, Any]]:
    """List all `*.md` files in a directory with name + size + modified."""
    if not d.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(d.glob("*.md")):
        try:
            stat = p.stat()
        except OSError:
            continue
        out.append(
            {
                "name": p.stem,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
    return out
