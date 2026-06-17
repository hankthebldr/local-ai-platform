"""
Feedback Router — Chat output ratings + research-artifact captures.

  POST /api/feedback/messages   — record a thumbs up/down on an assistant message
  GET  /api/feedback/messages   — list recent ratings (newest first)
  POST /api/feedback/artifacts  — capture a research/agent output as a context artifact
  GET  /api/feedback/artifacts  — list captured artifacts

Storage: append-only JSONL under data/feedback/{messages,artifacts}.jsonl.
Cheap, durable, easy to grep, easy to ship to disk-backed analytics
without any DB dependency. The keystore guards everything per the
auth middleware.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import logger

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

_FEEDBACK_DIR = Path(os.getenv("DATA_FEEDBACK_DIR", "data/feedback"))
_MESSAGES_LOG = _FEEDBACK_DIR / "messages.jsonl"
_ARTIFACTS_LOG = _FEEDBACK_DIR / "artifacts.jsonl"
# Per-agent tuning is an aggregate (counters + prefer/avoid examples), so it's
# a keyed JSON map rather than an append-only log: read-modify-write per agent.
_TUNING_FILE = _FEEDBACK_DIR / "agent_tuning.json"
_MAX_TUNING_EXAMPLES = 3


def _ensure_dir() -> None:
    _FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)


def _append(path: Path, payload: Dict[str, Any]) -> None:
    _ensure_dir()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str) + "\n")


def _tail_jsonl(path: Path, limit: int) -> List[Dict[str, Any]]:
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
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    return out


# ── Message ratings ─────────────────────────────────────────────────────────


class MessageRating(BaseModel):
    id: str = Field(..., description="Client-generated message id (e.g. cmsg-…)")
    kind: str = Field(..., pattern="^(up|down)$")
    ts: Optional[str] = None
    text: Optional[str] = Field(
        None,
        description="Excerpt of the rated assistant message (truncated client-side to ~4KB)",
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional context: model, agent id, web_search flag, etc.",
    )
    note: Optional[str] = Field(
        None, description="Optional free-text note from the operator"
    )


@router.post("/messages")
async def record_message_rating(body: MessageRating) -> Dict[str, Any]:
    """Append one chat-output rating to the durable log."""
    payload = body.model_dump()
    payload["recorded_at"] = datetime.utcnow().isoformat() + "Z"
    try:
        _append(_MESSAGES_LOG, payload)
    except OSError as e:
        logger.warning("Failed to write message rating: %s", e)
        raise HTTPException(status_code=500, detail="Could not persist rating")
    return {"ok": True, "id": body.id, "kind": body.kind}


@router.get("/messages")
async def list_message_ratings(limit: int = 100) -> List[Dict[str, Any]]:
    """Tail the message-rating log, newest first."""
    return _tail_jsonl(_MESSAGES_LOG, max(1, min(limit, 1000)))


# ── Research / agent-output artifacts ──────────────────────────────────────


class ArtifactCapture(BaseModel):
    source: str = Field(
        ...,
        description="Where the artifact came from: 'chat' | 'research' | 'workflow' | 'manual'",
    )
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, description="The full text being captured")
    tags: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Source-specific context: for source=research, the originating query + "
            "depth + model. For source=chat, the message id + agent id."
        ),
    )


@router.post("/artifacts")
async def capture_artifact(body: ArtifactCapture) -> Dict[str, Any]:
    """Capture a research finding / agent output / workflow result as a
    durable context artifact. Returns the artifact id; the SPA can show
    a link to it for later retrieval."""
    payload = body.model_dump()
    artifact_id = f"art_{int(datetime.utcnow().timestamp() * 1000):x}"
    payload["id"] = artifact_id
    payload["captured_at"] = datetime.utcnow().isoformat() + "Z"
    try:
        _append(_ARTIFACTS_LOG, payload)
    except OSError as e:
        logger.warning("Failed to write artifact capture: %s", e)
        raise HTTPException(status_code=500, detail="Could not persist artifact")

    # Best-effort: also ingest into the RAG store so the artifact becomes
    # searchable. Falls back silently if RAG isn't wired (rag dependencies
    # not installed, or the document service is disabled).
    try:
        from ..services import document_service  # type: ignore

        if hasattr(document_service, "upload"):
            doc_filename = f"{artifact_id}-{body.title[:80]}.md".replace("/", "_")
            md = f"# {body.title}\n\n{body.body}\n"
            if body.tags:
                md += "\n\n_tags: " + ", ".join(body.tags) + "_\n"
            document_service.upload(doc_filename, md.encode("utf-8"))
            payload["rag_ingested"] = True
    except Exception as e:
        logger.debug("Artifact RAG ingestion skipped: %s", e)
        payload["rag_ingested"] = False

    return payload


@router.get("/artifacts")
async def list_artifacts(limit: int = 100) -> List[Dict[str, Any]]:
    """Tail the artifact log, newest first."""
    return _tail_jsonl(_ARTIFACTS_LOG, max(1, min(limit, 1000)))


# ── Per-agent tuning (durable mirror of the client's AgentTuning) ───────────


class AgentTuningUpdate(BaseModel):
    """One up/down tuning event for an agent (or 'role:<role>') key.

    Mirrors the client's ``AgentTuning.record`` so ratings survive reload and
    aggregate across sessions: increment the up/down counter and, when a text
    excerpt is supplied, append it to the prefer (up) or avoid (down) list,
    capped to the most recent few examples.
    """

    agent_key: str = Field(..., min_length=1, max_length=200)
    kind: str = Field(..., pattern="^(up|down)$")
    text: Optional[str] = Field(None, description="Excerpt to learn prefer/avoid from")


def _load_tuning() -> Dict[str, Any]:
    if not _TUNING_FILE.exists():
        return {}
    try:
        return json.loads(_TUNING_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_tuning(data: Dict[str, Any]) -> None:
    _ensure_dir()
    tmp = _TUNING_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, _TUNING_FILE)


@router.post("/agent-tuning")
async def record_agent_tuning(body: AgentTuningUpdate) -> Dict[str, Any]:
    """Record an up/down tuning signal for one agent key; returns the
    updated aggregate so the client can reconcile its local copy."""
    data = _load_tuning()
    rec = data.get(body.agent_key) or {"up": 0, "down": 0, "prefer": [], "avoid": []}
    if body.kind == "up":
        rec["up"] = int(rec.get("up", 0)) + 1
        bucket = "prefer"
    else:
        rec["down"] = int(rec.get("down", 0)) + 1
        bucket = "avoid"
    if body.text:
        examples = list(rec.get(bucket, []))
        examples.append(body.text[:800])
        rec[bucket] = examples[-_MAX_TUNING_EXAMPLES:]
    rec["updated_at"] = datetime.utcnow().isoformat() + "Z"
    data[body.agent_key] = rec
    try:
        _save_tuning(data)
    except OSError as e:
        logger.warning("Failed to persist agent tuning: %s", e)
        raise HTTPException(status_code=500, detail="Could not persist tuning")
    return {"ok": True, "agent_key": body.agent_key, "tuning": rec}


@router.get("/agent-tuning")
async def list_agent_tuning() -> Dict[str, Any]:
    """Return the full per-agent tuning map (keyed by agent id / role)."""
    return _load_tuning()


@router.get("/agent-tuning/{agent_key}")
async def get_agent_tuning(agent_key: str) -> Dict[str, Any]:
    """Return one agent's tuning aggregate (empty record if none yet)."""
    data = _load_tuning()
    return data.get(agent_key) or {"up": 0, "down": 0, "prefer": [], "avoid": []}
