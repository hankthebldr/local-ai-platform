"""Research session store — stateful, multi-turn deep research.

A *research session* ties one deep-dive to the follow-up conversation that
grows out of it. Same idiom as ``conversation_store`` and the workflow-engine
run persistence: one JSON file per session, written atomically (tmp +
``os.replace``) under ``RESEARCH_DATA_DIR``.

Each session also mirrors a human-readable Map-of-Content (MOC) markdown file
into the shared ``research`` workspace (``sessions/<id>.md``) so the operator
can browse it, and so RX-2's Obsidian-like store surfaces it. The workspace
slug ``research`` is PINNED here (Blocker 2 / RX-2 / Operate U11 consume the
same constant — producer and consumer agree on the name).

Persisted shape (``ResearchSession``)::

    {topic, model, source_ids, turns, moc_path}

Turns are ``{kind, question, answer, sources, web_search, grounded, created_at}``
where ``kind`` is ``"synthesis"`` (the seed deep-dive) or ``"followup"``.

Privacy: this module never reaches the network. Web egress for follow-ups is
owned by the operator-triggered ``POST /api/research/followup`` handler and is
OFF by default there.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..logging_config import logger

# Pinned shared slug — RX-2 store + Operate U11 workspace preset consume this.
RESEARCH_WORKSPACE = "research"

# One JSON file per session. Env-overridable for tests / alternate deployments,
# mirroring conversation_store's CONVERSATION_DATA_DIR idiom.
RESEARCH_DATA_DIR = os.getenv("RESEARCH_DATA_DIR", "./data/research/sessions")

# Session ids become filenames; reject anything that could escape the dir.
_SAFE_ID_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(sid: str) -> str:
    c = (sid or "").strip()
    if not c or c in (".", "..") or not all(ch in _SAFE_ID_CHARS for ch in c):
        raise ValueError(f"unsafe research session id: {sid!r}")
    return c


class ResearchSession(BaseModel):
    """One durable, resumable research session."""

    id: str
    topic: str = ""
    model: Optional[str] = None
    # Stable references (source urls) for the sources this session is grounded on.
    source_ids: List[str] = Field(default_factory=list)
    # Ordered Q/A turns — turn[0] is the seed synthesis when present.
    turns: List[Dict[str, Any]] = Field(default_factory=list)
    # Relative path (inside the `research` workspace) of the rendered MOC.
    moc_path: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    def summary(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "model": self.model,
            "turns": len(self.turns),
            "source_count": len(self.source_ids),
            "moc_path": self.moc_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _sessions_dir() -> Path:
    return Path(RESEARCH_DATA_DIR)


def _session_path(sid: str) -> Path:
    return _sessions_dir() / f"{_safe_id(sid)}.json"


# ── Persistence ────────────────────────────────────────────────────────────


def save_session(session: ResearchSession) -> ResearchSession:
    """Atomically persist a session (tmp + os.replace)."""
    sid = _safe_id(session.id)
    path = _session_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    session.updated_at = _now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(session.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return session


def get_session(sid: str) -> Optional[ResearchSession]:
    try:
        path = _session_path(sid)
    except ValueError:
        return None
    if not path.exists():
        return None
    try:
        return ResearchSession.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — a corrupt record must not 500
        logger.warning("research_session: failed to read %r: %s", sid, exc)
        return None


def list_sessions() -> List[Dict[str, Any]]:
    d = _sessions_dir()
    if not d.exists():
        return []
    rows: List[ResearchSession] = []
    for f in d.glob("*.json"):
        try:
            rows.append(ResearchSession.model_validate_json(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    rows.sort(key=lambda s: s.updated_at, reverse=True)
    return [s.summary() for s in rows]


# ── The `research` workspace (shared store) ────────────────────────────────


def research_workspace_root() -> Path:
    """Canonical on-disk root for the shared `research` workspace.

    Rooted under the same data dir the workspace registry uses so RX-2 (which
    also ensures this workspace) resolves the identical path — idempotent.
    """
    data_dir = Path(os.getenv("ENCLAVE_DATA_DIR", "./data"))
    return (data_dir / "research" / "workspace").resolve()


def ensure_research_workspace():
    """Idempotently ensure the `research` workspace exists (markdown-only).

    Returns the ``Workspace`` or ``None`` when the registry is unavailable —
    MOC writes are best-effort and never block a session mint.
    """
    try:
        from .workspace import (
            WorkspaceError,
            WorkspacePolicy,
            get_workspace_registry,
        )
    except Exception as exc:  # noqa: BLE001 — workspace subsystem absent
        logger.debug("research workspace unavailable: %s", exc)
        return None

    reg = get_workspace_registry()
    try:
        return reg.get(RESEARCH_WORKSPACE)
    except WorkspaceError:
        pass
    try:
        return reg.create(
            RESEARCH_WORKSPACE,
            str(research_workspace_root()),
            WorkspacePolicy(allowed_extensions=["md"]),
            "Stateful research sessions, saved sources, and notes.",
        )
    except WorkspaceError:
        # Lost a create race (RX-2 / a concurrent session) — fetch the winner.
        try:
            return reg.get(RESEARCH_WORKSPACE)
        except WorkspaceError:
            return None


def _render_moc(session: ResearchSession) -> str:
    """Build the human-readable Map-of-Content markdown for a session."""
    lines: List[str] = [
        f"# Research: {session.topic or '(untitled)'}",
        "",
        f"- session: `{session.id}`",
        f"- model: {session.model or '?'}",
        f"- updated: {session.updated_at}",
        "",
    ]
    if session.source_ids:
        lines.append("## Sources")
        lines.append("")
        for url in session.source_ids:
            lines.append(f"- {url}")
        lines.append("")
    for i, turn in enumerate(session.turns):
        q = str(turn.get("question") or "").strip()
        a = str(turn.get("answer") or "").strip()
        kind = turn.get("kind", "followup")
        heading = "Synthesis" if kind == "synthesis" else f"Follow-up {i}"
        lines.append(f"## {heading}")
        if q and kind != "synthesis":
            lines.append("")
            lines.append(f"**Q:** {q}")
        if turn.get("web_search"):
            lines.append("")
            lines.append("_(operator-initiated web search)_")
        lines.append("")
        lines.append(a or "_(no answer generated)_")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_moc(session: ResearchSession) -> Optional[str]:
    """Render + write the session MOC into the `research` workspace.

    Best-effort: returns the relative path on success, ``None`` otherwise. A
    failure here never breaks a session mint or a follow-up turn.
    """
    ws = ensure_research_workspace()
    if ws is None:
        return None
    rel = f"sessions/{session.id}.md"
    try:
        ws.write(rel, _render_moc(session))
        return rel
    except Exception as exc:  # noqa: BLE001 — MOC is an additive nicety
        logger.debug("research MOC write skipped: %s", exc)
        return None


# ── ConversationStore mirror (optional) ────────────────────────────────────


def _mirror_conversation(session: ResearchSession) -> None:
    """Best-effort mirror of a session's turns into the ConversationStore as a
    `research`-kinded thread (id `research-<sid>`), so the thread switcher and
    knowledge graph can see research conversations. Never raises."""
    try:
        from ..models.conversation_models import SavedConversation
        from .conversation_store import get_conversation_store

        messages: List[Dict[str, Any]] = []
        for turn in session.turns:
            q = str(turn.get("question") or "").strip()
            if q:
                messages.append({"role": "user", "content": q})
            messages.append({"role": "assistant", "content": str(turn.get("answer") or "")})
        conv = SavedConversation(
            id=f"research-{session.id}",
            title=f"Research: {session.topic or session.id}"[:120],
            model=session.model,
            messages=messages,
        )
        get_conversation_store().save(conv)
    except Exception as exc:  # noqa: BLE001 — mirror is optional
        logger.debug("research conversation mirror skipped: %s", exc)


# ── High-level operations ──────────────────────────────────────────────────


def record_deep_dive(
    topic: str,
    model: Optional[str],
    source_ids: Optional[List[str]] = None,
    synthesis: Optional[str] = None,
    sub_questions: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    mirror_conversation: bool = True,
) -> ResearchSession:
    """Mint (or continue) a research session from a deep-dive result.

    When ``session_id`` names an existing session the fresh synthesis is
    appended as a new turn; otherwise a new session is minted. Writes the MOC
    and (optionally) mirrors the thread. Returns the persisted session.
    """
    existing = get_session(session_id) if session_id else None
    if existing is not None:
        session = existing
        session.topic = topic or session.topic
        session.model = model or session.model
        # Merge new source urls, preserving order + de-duping.
        seen = set(session.source_ids)
        for u in source_ids or []:
            if u and u not in seen:
                session.source_ids.append(u)
                seen.add(u)
    else:
        sid = None
        if session_id:
            try:
                sid = _safe_id(session_id)
            except ValueError:
                sid = None
        session = ResearchSession(
            id=sid or uuid.uuid4().hex,
            topic=topic,
            model=model,
            source_ids=[u for u in (source_ids or []) if u],
        )

    turn = {
        "kind": "synthesis",
        "question": topic,
        "answer": synthesis or "",
        "sources": list(session.source_ids),
        "sub_questions": list(sub_questions or []),
        "web_search": True,  # deep-dive itself always searches the web
        "grounded": False,
        "created_at": _now_iso(),
    }
    session.turns.append(turn)
    session.moc_path = _write_moc(session) or session.moc_path
    save_session(session)
    if mirror_conversation:
        _mirror_conversation(session)
    return session


def append_followup(
    session_id: str,
    question: str,
    answer: str,
    sources: Optional[List[Dict[str, Any]]] = None,
    web_search: bool = False,
    grounded: bool = False,
    mirror_conversation: bool = True,
) -> Optional[ResearchSession]:
    """Append a follow-up turn to an existing session; rewrite the MOC.

    Returns the updated session, or ``None`` when the session is missing.
    """
    session = get_session(session_id)
    if session is None:
        return None
    src = sources or []
    turn = {
        "kind": "followup",
        "question": question,
        "answer": answer or "",
        "sources": src,
        "web_search": bool(web_search),
        "grounded": bool(grounded),
        "created_at": _now_iso(),
    }
    session.turns.append(turn)
    # Merge any new source urls into the stable reference list.
    seen = set(session.source_ids)
    for s in src:
        u = s.get("url") if isinstance(s, dict) else None
        if u and u not in seen:
            session.source_ids.append(u)
            seen.add(u)
    session.moc_path = _write_moc(session) or session.moc_path
    save_session(session)
    if mirror_conversation:
        _mirror_conversation(session)
    return session
