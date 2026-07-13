"""Artifacts inventory — a read-only unified view over three disjoint stores.

O5 of the Operate plane. This router aggregates, **router-side**, the durable
outputs a local run leaves behind — the frozen workflow engine is never touched
and never consulted through this path:

  run       scan the engine run root ``<project_root>/data/workflows`` — each
            run dir's ``artifacts/<step_id>.json`` step outputs + ``summary.md``.
            Model/provenance per step comes from ``run.json`` ``step_results``.
  feedback  tail ``data/feedback/artifacts.jsonl`` (feedback.py's real log) —
            research/agent captures. Body is inline (no per-record file).
  export    ``data/exports/*.md`` — saved chat-session markdown exports.

Workspace files are a **named cut** from this unified inventory in v1 (they are
browsable in the Artifacts tab's Workspaces pane over /api/workspaces instead).

Every record is ``{id, source, type, title, produced_at, size_bytes,
provenance {run_id, step_id, workflow_id, model_used}|null}``. ``id`` is a
composite ``<source>:<...>`` handle; ``GET /{id}`` and ``GET /{id}/raw`` re-parse
it and re-derive the on-disk path with **resolved-path containment** (the
prompts.py / run_index.py discipline) before any file is opened — a ``../``
handle resolves to 404, never an escape.

Read-only by contract: there are **no write or delete endpoints in v1**
(delete/compaction is a named follow-up — §12 — not a stub). Reads are scope-
gated ``workflows`` via the SCOPE_MAP entry shipped with this unit (F9).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from ..logging_config import logger
from ..services import run_index

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])

# Newest-N run dirs scanned for step/summary artifacts per request (spec §4.1).
RUN_SCAN_CAP = 500
# Body preview clamp for GET /{id} (raw download is uncapped).
_PREVIEW_BYTES = 64_000

# Sources.
_SRC_RUN = "run"
_SRC_FEEDBACK = "feedback"
_SRC_EXPORT = "export"
_SUMMARY_STEP = "__summary__"  # sentinel step-id for a run's summary.md


# ── Store roots (mirror the frozen engine derivation — F11) ──────────────────


def _feedback_log() -> Path:
    # Mirror feedback.py:31 so the two point at one file under test.
    return Path(os.getenv("DATA_FEEDBACK_DIR", "data/feedback")) / "artifacts.jsonl"


def _exports_dir() -> Path:
    # Mirror exports.py EXPORTS_DIR (project_root/data/exports).
    return Path(__file__).resolve().parents[2] / "data" / "exports"


# ── Composite id ─────────────────────────────────────────────────────────────


def _bad(reason: str = "artifact not found") -> HTTPException:
    return HTTPException(status_code=404, detail=reason)


def _split_id(artifact_id: str) -> Tuple[str, str]:
    src, sep, rest = (artifact_id or "").partition(":")
    if not sep or not rest:
        raise _bad("malformed artifact id")
    return src, rest


class ArtifactRecord(BaseModel):
    id: str
    source: str
    type: str
    title: str
    produced_at: Optional[str] = None
    size_bytes: int = 0
    provenance: Optional[Dict[str, Any]] = None


class ArtifactDetail(ArtifactRecord):
    preview: str = ""
    preview_truncated: bool = False


# ── run store ────────────────────────────────────────────────────────────────


def _step_models(data: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for s in data.get("step_results") or []:
        if isinstance(s, dict) and s.get("step_id"):
            out[str(s["step_id"])] = str(s.get("model_used") or "") or ""
    return out


def _step_completed_at(data: Dict[str, Any], step_id: str) -> Optional[str]:
    for s in data.get("step_results") or []:
        if isinstance(s, dict) and str(s.get("step_id")) == step_id:
            return s.get("completed_at") or s.get("started_at")
    return None


def _run_produced_at(data: Dict[str, Any]) -> Optional[str]:
    return data.get("completed_at") or data.get("started_at")


def _run_items(cap: int = RUN_SCAN_CAP) -> List[ArtifactRecord]:
    """Newest-``cap`` run dirs → their step artifacts + summary.md as records.

    Reuses run_index's contained run-root resolution and JSON reader so this
    scanner and the Runs index stay pinned to one directory and one traversal
    guard. Never touches the frozen engine."""
    root = run_index._run_root()
    items: List[ArtifactRecord] = []
    try:
        index = run_index._load_index(root)  # (started_at, run_id) desc
    except Exception as exc:  # noqa: BLE001 — an unreadable root yields nothing
        logger.debug("artifacts run scan: index unavailable: %s", exc)
        return items
    for _started, run_id in index[:cap]:
        run_dir = run_index._resolve_run_dir(root, run_id)
        if run_dir is None:
            continue
        data = run_index._read_json(run_dir / "run.json") or {}
        workflow_id = str(data.get("workflow_id") or "")
        models = _step_models(data)
        label = workflow_id or run_id[:8]
        produced = _run_produced_at(data)
        # summary.md
        summary = run_dir / "summary.md"
        if summary.is_file():
            try:
                size = summary.stat().st_size
            except OSError:
                size = 0
            items.append(
                ArtifactRecord(
                    id=f"{_SRC_RUN}:{run_id}:{_SUMMARY_STEP}",
                    source=_SRC_RUN,
                    type="summary",
                    title=f"{label} · summary",
                    produced_at=produced,
                    size_bytes=size,
                    provenance={
                        "run_id": run_id,
                        "step_id": None,
                        "workflow_id": workflow_id or None,
                        "model_used": None,
                    },
                )
            )
        # artifacts/<step_id>.json
        art_dir = run_dir / "artifacts"
        if art_dir.is_dir():
            try:
                entries = sorted(art_dir.glob("*.json"))
            except OSError:
                entries = []
            for f in entries:
                step_id = f.stem
                try:
                    size = f.stat().st_size
                except OSError:
                    size = 0
                items.append(
                    ArtifactRecord(
                        id=f"{_SRC_RUN}:{run_id}:{step_id}",
                        source=_SRC_RUN,
                        type="step",
                        title=f"{label} · {step_id}",
                        produced_at=_step_completed_at(data, step_id) or produced,
                        size_bytes=size,
                        provenance={
                            "run_id": run_id,
                            "step_id": step_id,
                            "workflow_id": workflow_id or None,
                            "model_used": models.get(step_id) or None,
                        },
                    )
                )
    return items


def _run_path(rest: str) -> Tuple[Path, str]:
    """(contained file path, media_type) for a ``run:<run_id>:<step>`` handle."""
    run_id, sep, step_id = rest.partition(":")
    if not sep or not run_id or not step_id:
        raise _bad("malformed run artifact id")
    root = run_index._run_root()
    run_dir = run_index._resolve_run_dir(root, run_id)  # containment + isdir
    if run_dir is None:
        raise _bad()
    if step_id == _SUMMARY_STEP:
        candidate = (run_dir / "summary.md").resolve()
        media = "text/markdown"
    else:
        # step_id is a filename stem — containment guard rejects ../ escapes.
        candidate = (run_dir / "artifacts" / f"{step_id}.json").resolve()
        media = "application/json"
    try:
        candidate.relative_to(run_dir.resolve())
    except ValueError:
        raise _bad()
    if not candidate.is_file():
        raise _bad()
    return candidate, media


# ── feedback store ───────────────────────────────────────────────────────────


def _feedback_items() -> List[ArtifactRecord]:
    out: List[ArtifactRecord] = []
    for rec in _tail_jsonl(_feedback_log(), limit=1000):
        aid = rec.get("id")
        if not aid:
            continue
        body = rec.get("body") or ""
        ctx = rec.get("context") if isinstance(rec.get("context"), dict) else {}
        prov: Optional[Dict[str, Any]] = None
        run_id = ctx.get("run_id")
        wf = ctx.get("workflow_id")
        if run_id or wf:
            prov = {
                "run_id": run_id,
                "step_id": ctx.get("step_id"),
                "workflow_id": wf,
                "model_used": ctx.get("model"),
            }
        out.append(
            ArtifactRecord(
                id=f"{_SRC_FEEDBACK}:{aid}",
                source=_SRC_FEEDBACK,
                type=str(rec.get("source") or "capture"),
                title=str(rec.get("title") or aid),
                produced_at=rec.get("captured_at"),
                size_bytes=len(body.encode("utf-8")),
                provenance=prov,
            )
        )
    return out


def _feedback_body(aid: str) -> Tuple[str, Dict[str, Any]]:
    for rec in _tail_jsonl(_feedback_log(), limit=100_000):
        if rec.get("id") == aid:
            return str(rec.get("body") or ""), rec
    raise _bad()


def _tail_jsonl(path: Path, limit: int) -> List[Dict[str, Any]]:
    """Newest-first tolerant JSONL tail (feedback.py._tail_jsonl idiom, kept
    local so this router doesn't reach into another router's privates)."""
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
        if len(out) >= limit:
            break
    return out


# ── export store ─────────────────────────────────────────────────────────────


def _export_items() -> List[ArtifactRecord]:
    d = _exports_dir()
    out: List[ArtifactRecord] = []
    if not d.is_dir():
        return out
    from datetime import datetime, timezone

    try:
        files = sorted(d.glob("*.md"))
    except OSError:
        return out
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        out.append(
            ArtifactRecord(
                id=f"{_SRC_EXPORT}:{f.name}",
                source=_SRC_EXPORT,
                type="markdown",
                title=f.name,
                produced_at=datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc
                ).isoformat(),
                size_bytes=st.st_size,
                provenance=None,
            )
        )
    return out


def _export_path(filename: str) -> Path:
    d = _exports_dir().resolve()
    # basename strips any directory component; containment re-checks the resolve.
    name = os.path.basename(filename)
    if not name or not name.endswith(".md"):
        raise _bad()
    candidate = (d / name).resolve()
    try:
        candidate.relative_to(d)
    except ValueError:
        raise _bad()
    if not candidate.is_file():
        raise _bad()
    return candidate


# ── aggregation ──────────────────────────────────────────────────────────────


def _all_items() -> List[ArtifactRecord]:
    items = _run_items() + _feedback_items() + _export_items()
    items.sort(key=lambda r: (r.produced_at or "", r.id), reverse=True)
    return items


def _facets(items: List[ArtifactRecord]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {"source": {}, "type": {}, "model": {}}
    for it in items:
        out["source"][it.source] = out["source"].get(it.source, 0) + 1
        out["type"][it.type] = out["type"].get(it.type, 0) + 1
        model = (it.provenance or {}).get("model_used")
        if model:
            out["model"][model] = out["model"].get(model, 0) + 1
    return out


# ── endpoints ────────────────────────────────────────────────────────────────


@router.get("")
async def list_artifacts(
    source: Optional[str] = None,
    type: Optional[str] = None,  # noqa: A002 — public query name matches spec
    model: Optional[str] = None,
    workflow_id: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Unified, filtered, paged inventory across run/feedback/export stores.

    ``facets`` counts are computed over the FULL corpus (all sources) so the UI
    can render every available filter value; ``items``/``total``/``has_more``
    reflect the applied filters + offset/limit window."""
    everything = _all_items()
    facets = _facets(everything)

    def _keep(it: ArtifactRecord) -> bool:
        if source and it.source != source:
            return False
        if type and it.type != type:
            return False
        prov = it.provenance or {}
        if model and prov.get("model_used") != model:
            return False
        if workflow_id and prov.get("workflow_id") != workflow_id:
            return False
        if q:
            needle = q.lower()
            hay = f"{it.title} {it.id}".lower()
            if needle not in hay:
                return False
        return True

    filtered = [it for it in everything if _keep(it)]
    total = len(filtered)
    window = filtered[offset : offset + limit]
    return {
        "items": [it.model_dump() for it in window],
        "total": total,
        "has_more": offset + limit < total,
        "facets": facets,
    }


def _record_for(artifact_id: str) -> ArtifactRecord:
    src, rest = _split_id(artifact_id)
    for it in _all_items():
        if it.id == artifact_id:
            return it
    # Not in the (capped) inventory — but a direct-hit path may still resolve
    # (e.g. a run older than the 500-dir cap). Rebuild a minimal record.
    if src == _SRC_RUN:
        path, _media = _run_path(rest)
        run_id, _sep, step_id = rest.partition(":")
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        is_summary = step_id == _SUMMARY_STEP
        return ArtifactRecord(
            id=artifact_id,
            source=_SRC_RUN,
            type="summary" if is_summary else "step",
            title=f"{run_id[:8]} · {'summary' if is_summary else step_id}",
            size_bytes=size,
            provenance={
                "run_id": run_id,
                "step_id": None if is_summary else step_id,
                "workflow_id": None,
                "model_used": None,
            },
        )
    if src == _SRC_EXPORT:
        path = _export_path(rest)
        return ArtifactRecord(
            id=artifact_id,
            source=_SRC_EXPORT,
            type="markdown",
            title=rest,
            size_bytes=path.stat().st_size,
        )
    raise _bad()


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str) -> Dict[str, Any]:
    """One record + a size-capped body preview (raw download is uncapped)."""
    src, rest = _split_id(artifact_id)
    rec = _record_for(artifact_id)
    if src == _SRC_RUN:
        path, _media = _run_path(rest)
        raw = path.read_bytes()
    elif src == _SRC_EXPORT:
        raw = _export_path(rest).read_bytes()
    elif src == _SRC_FEEDBACK:
        body, _full = _feedback_body(rest)
        raw = body.encode("utf-8")
    else:
        raise _bad()
    truncated = len(raw) > _PREVIEW_BYTES
    preview = raw[:_PREVIEW_BYTES].decode("utf-8", errors="replace")
    detail = ArtifactDetail(
        **rec.model_dump(), preview=preview, preview_truncated=truncated
    )
    return detail.model_dump()


@router.get("/{artifact_id}/raw")
async def download_artifact(artifact_id: str) -> Response:
    """Raw bytes as an attachment download. Uncapped; containment-guarded."""
    src, rest = _split_id(artifact_id)
    if src == _SRC_RUN:
        path, media = _run_path(rest)
        data = path.read_bytes()
        fname = path.name
    elif src == _SRC_EXPORT:
        path = _export_path(rest)
        data = path.read_bytes()
        media = "text/markdown"
        fname = path.name
    elif src == _SRC_FEEDBACK:
        body, _full = _feedback_body(rest)
        data = body.encode("utf-8")
        media = "text/markdown"
        fname = f"{rest}.md"
    else:
        raise _bad()
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
