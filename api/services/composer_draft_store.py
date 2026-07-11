"""Composer draft store (DR-1) — durable, opaque canvas snapshots.

The Composer keystone: an in-progress workflow must STICK across reloads. A
*draft* is the lossless canvas snapshot the frontend produces
(``dfEditor.export()`` + ``dfNodeData`` + ``dfNextId`` + ``dfSeedSchema`` +
meta) keyed by a client-minted ``draft_id`` (uuid4 hex, distinct from the
published ``workflow_id``). This store persists that blob verbatim; it NEVER
validates it against the workflow engine (a half-built canvas is not a runnable
workflow, and the whole point is to survive an un-runnable intermediate state).

Storage (mirrors tasks.py / prompts.py, the layered-store precedent):

    user_storage_root/composer/drafts/<draft_id>.json   writable operator layer

Persistence discipline copied from the workspace glob-traversal incident:
  * id-charset allowlist AND resolved-path containment (``relative_to``);
  * atomic writes (tmp + ``os.replace``);
  * a hard ~2 MB per-draft cap so a runaway canvas can't fill the disk.

No deployment.ensure_dirs touch is needed — ``_write_atomic`` lazily creates
``composer/drafts`` on first save (parents=True), so the store is
self-provisioning and the DR-1 file list stays minimal.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
# user layer fallback when no deployment is detected (bare unit tests / dev).
_USER_FALLBACK = _REPO_ROOT / "data" / "composer" / "drafts"

# uuid4 hex is 32 lowercase hex chars; keep the general library charset so a
# renamed/duplicated draft id (uuid4hex + suffix) still validates. Same shape
# tasks.py/prompts.py enforce: alnum start, alnum/_/- body, <= 80.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")

# Hard ceiling on a single persisted draft. A ralph+seed canvas serializes to a
# few KB; 2 MB is ~1000x headroom and still bounds a pathological paste.
MAX_DRAFT_BYTES = 2 * 1024 * 1024


class DraftTooLarge(ValueError):
    """Raised when a draft record exceeds MAX_DRAFT_BYTES (→ router 413)."""


class InvalidDraftId(ValueError):
    """Raised when a draft id fails the charset/containment allowlist (→ 400)."""


def _drafts_root() -> Path:
    """user_storage_root/composer/drafts — deployment-resolved, test-patchable."""
    try:
        from .deployment import _get_current

        return _get_current().user_storage_root / "composer" / "drafts"
    except Exception:  # noqa: BLE001 — no deployment detected (unit tests)
        return _USER_FALLBACK


def _draft_path(draft_id: str, must_exist: bool = True) -> Path:
    """Resolve one draft id to its JSON file with full containment checks."""
    if not _ID_RE.match(draft_id or ""):
        raise InvalidDraftId("invalid draft id (alnum start, alnum/_/-, <=80)")
    base = _drafts_root().resolve()
    candidate = (base / f"{draft_id}.json").resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise InvalidDraftId("path escapes draft store")
    if must_exist and not candidate.is_file():
        raise FileNotFoundError(f"draft '{draft_id}' not found")
    return candidate


def _write_atomic(p: Path, data: Dict[str, Any]) -> int:
    """Serialize + atomically replace. Returns the byte length written.
    Enforces MAX_DRAFT_BYTES BEFORE touching disk (no partial oversized tmp)."""
    text = json.dumps(data, indent=2)
    size = len(text.encode("utf-8"))
    if size > MAX_DRAFT_BYTES:
        raise DraftTooLarge(
            f"draft is {size} bytes; the limit is {MAX_DRAFT_BYTES} bytes"
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)  # atomic
    return size


def _summary(rec: Dict[str, Any]) -> Dict[str, Any]:
    """The In-Progress row projection — everything EXCEPT the heavy blob."""
    return {k: v for k, v in rec.items() if k != "blob"}


def save_draft(
    draft_id: str,
    *,
    blob: Dict[str, Any],
    name: str = "",
    workflow_id: Optional[str] = None,
    step_count: int = 0,
    published: bool = False,
    last_run_status: Optional[str] = None,
) -> Dict[str, Any]:
    """Upsert a draft. The ``blob`` is stored VERBATIM (opaque; never engine-
    validated). ``created_at`` is preserved across updates; ``updated_at`` is
    stamped now. Returns the summary (blob-free) record."""
    p = _draft_path(draft_id, must_exist=False)
    now = time.time()
    created = now
    if p.is_file():
        try:
            prior = json.loads(p.read_text(encoding="utf-8"))
            created = prior.get("created_at", now)
        except (OSError, json.JSONDecodeError):
            created = now
    rec: Dict[str, Any] = {
        "draft_id": draft_id,
        "name": (name or "").strip() or "Untitled workflow",
        "workflow_id": workflow_id or None,
        "step_count": int(step_count or 0),
        "published": bool(published),
        "last_run_status": last_run_status or None,
        "created_at": created,
        "updated_at": now,
        "blob": blob if isinstance(blob, dict) else {},
    }
    _write_atomic(p, rec)
    return _summary(rec)


def get_draft(draft_id: str) -> Dict[str, Any]:
    """Full record INCLUDING the blob (the restore-on-open payload)."""
    p = _draft_path(draft_id, must_exist=True)
    return json.loads(p.read_text(encoding="utf-8"))


def patch_draft(
    draft_id: str,
    *,
    name: Optional[str] = None,
    workflow_id: Optional[str] = None,
    published: Optional[bool] = None,
    last_run_status: Optional[str] = None,
) -> Dict[str, Any]:
    """Metadata-only edit (rename / relink / mark published / last-run dot).
    Leaves the canvas blob untouched. 404 when the draft is absent."""
    rec = get_draft(draft_id)  # raises FileNotFoundError → router 404
    if name is not None:
        rec["name"] = name.strip() or rec.get("name") or "Untitled workflow"
    if workflow_id is not None:
        rec["workflow_id"] = workflow_id or None
    if published is not None:
        rec["published"] = bool(published)
    if last_run_status is not None:
        rec["last_run_status"] = last_run_status or None
    rec["updated_at"] = time.time()
    _write_atomic(_draft_path(draft_id, must_exist=False), rec)
    return _summary(rec)


def list_drafts() -> List[Dict[str, Any]]:
    """All draft summaries (blob-free), newest-edited first."""
    base = _drafts_root()
    if not base.exists():
        return []
    out: List[Dict[str, Any]] = []
    for f in base.glob("*.json"):
        if f.name.endswith(".tmp"):
            continue
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append(_summary(rec))
    out.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
    return out


def delete_draft(draft_id: str) -> Dict[str, Any]:
    """Remove a draft (publish-freeze or explicit delete). Idempotent-ish:
    404 (FileNotFoundError) when it never existed."""
    p = _draft_path(draft_id, must_exist=True)
    p.unlink()
    return {"deleted": draft_id}
