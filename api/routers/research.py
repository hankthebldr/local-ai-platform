#!/usr/bin/env python3
"""
Research Router — stateful follow-up conversation over a deep-dive session.

The deep-dive endpoint (``POST /api/research/deep-dive``, in graph.py) mints a
``ResearchSession`` and returns a ``session_id``. This router grows that session
into a conversation:

  GET  /api/research/sessions            → list session summaries
  GET  /api/research/sessions/{id}       → one session (topic, turns, MOC path)
  POST /api/research/followup            → answer a follow-up, append a turn

A follow-up loads the prior synthesis + saved sources for the session, grounds
the question over the local Chroma RAG store (semantic recall of everything the
operator has captured), optionally runs an OPERATOR-INITIATED web search
(``web_search`` — OFF by default; privacy-first appliance), answers with the
local model via ``ollama.chat``, and appends the turn (rewriting the session
MOC). Nothing leaves the box unless the operator ticks ``web_search`` on this
POST — reads/tab-activation never egress.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..services import rag_ingest, research_session
from ..services.ollama_service import OllamaService
from ..services.search_service import format_search_context
from ..services.search_service import search as search_web

router = APIRouter(prefix="/api/research", tags=["research"])

_ollama = OllamaService(os.getenv("OLLAMA_HOST", "http://localhost:11434"))

# ── RX-2: Obsidian-like store subdirs inside the shared `research` workspace.
# The store is browsable as sessions/ (RX-1 MOCs), sources/ (saved research
# results), notes/ (compare + graph-walk reports). Writes are constrained to
# this allowlist so a save can never escape the store layout.
_STORE_SUBDIRS = ("sources", "notes")
# Filename-safe slug charset (mirrors prompts.py id containment): a slug that
# isn't purely this charset is rejected before it ever reaches the filesystem,
# so `../` / absolute-path traversal is structurally impossible.
_SLUG_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
_SLUG_MAX = 80

# Keep grounding + answer bounded so a large session can't blow up the prompt.
_MAX_GROUNDING_CHARS = 4000
_MAX_PRIOR_CHARS = 4000
_FOLLOWUP_SYSTEM = (
    "You are a research assistant continuing an ongoing investigation. Answer "
    "the operator's follow-up using the PRIOR SYNTHESIS, the RETRIEVED CONTEXT "
    "from their local knowledge store, and any FRESH WEB RESULTS provided. Be "
    "concise and well-structured (markdown). Cite retrieved/web sources as "
    "[1], [2] when you lean on them. If the context does not cover the "
    "question, say so plainly rather than inventing facts."
)


class FollowupRequest(BaseModel):
    session_id: str = Field(..., description="ResearchSession id from deep-dive")
    question: str = Field(..., min_length=1, description="Operator follow-up question")
    # Privacy-first: web egress is OFF unless the operator explicitly opts in
    # on THIS request. No background search on read/tab-activation.
    web_search: bool = False
    model: Optional[str] = None


def _rag_ground(question: str) -> Dict[str, Any]:
    """Best-effort semantic recall from the local Chroma store. Returns
    ``{context, results}``; empty when the RAG backend is unavailable. Never
    raises and never touches the network (local embeddings only)."""
    try:
        # Route through _ensure_rag() so a backend that came up mid-session
        # heals here too — not just on the Documents tab. Returns None while
        # the embedding backend stays down (best-effort grounding).
        from ..routers.documents import _ensure_rag

        rag_service = _ensure_rag()
    except Exception as exc:  # noqa: BLE001 — RAG optional
        logger.debug("research followup RAG unavailable: %s", exc)
        return {"context": "", "results": []}
    if rag_service is None:
        return {"context": "", "results": []}
    try:
        out = rag_service.search(query=question, top_k=5)
        ctx = rag_service.format_context(out, max_chars=_MAX_GROUNDING_CHARS)
        return {"context": ctx, "results": out.get("results", [])}
    except Exception as exc:  # noqa: BLE001
        logger.debug("research followup RAG search failed: %s", exc)
        return {"context": "", "results": []}


def _prior_synthesis(session: research_session.ResearchSession) -> str:
    """The most recent synthesis turn's answer (the report the follow-up builds
    on), bounded so a long report can't dominate the prompt."""
    for turn in reversed(session.turns):
        if turn.get("kind") == "synthesis" and str(turn.get("answer") or "").strip():
            return str(turn["answer"])[:_MAX_PRIOR_CHARS]
    # No explicit synthesis turn — fall back to the last answer of any kind.
    for turn in reversed(session.turns):
        if str(turn.get("answer") or "").strip():
            return str(turn["answer"])[:_MAX_PRIOR_CHARS]
    return ""


@router.get("/sessions")
async def list_research_sessions() -> List[Dict[str, Any]]:
    """List research session summaries (newest first). Read-open, no egress."""
    return research_session.list_sessions()


@router.get("/sessions/{session_id}")
async def get_research_session(session_id: str) -> Dict[str, Any]:
    """One research session — full topic/model/turns/source_ids/MOC path."""
    session = research_session.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404, detail=f"research session '{session_id}' not found"
        )
    return session.model_dump()


def _chat_or_503(what: str, **chat_kwargs: Any) -> str:
    """Run the local model or raise 503 ``model_unavailable``.

    The research surfaces used to swallow a model exception and hand back a
    ``_… unavailable — …_`` sentinel with HTTP 200, which every caller then
    persisted as durable success (a session turn + MOC + ConversationStore
    mirror; a store note + RAG ingest; a graph-walk item marked ``done`` that
    ``requeue_stale`` could never retry). Convention (CLAUDE.md): never write
    a failure sentinel to a durable store, never return 200 on a local-model
    exception. Callers get the answer text or the exception — no third state.
    """
    try:
        result = _ollama.chat(**chat_kwargs)
    except Exception as exc:  # noqa: BLE001 — surfaced, never persisted
        logger.error("research %s model call failed: %s", what, exc)
        raise HTTPException(
            status_code=503,
            detail=f"local model call failed while producing the {what}: {exc}",
            headers={"X-Enclave-Error": "model_unavailable"},
        )
    return (result or {}).get("content", "") or ""


@router.post("/followup")
async def research_followup(req: FollowupRequest) -> Dict[str, Any]:
    """Answer a follow-up on an existing session and append the turn.

    Grounds over local RAG (always, local-only), optionally over an
    operator-initiated web search (``web_search`` — OFF by default), then
    answers with the local model and persists the turn + updated MOC.
    """
    session = research_session.get_session(req.session_id)
    if session is None:
        raise HTTPException(
            status_code=404, detail=f"research session '{req.session_id}' not found"
        )

    prior = _prior_synthesis(session)
    grounding = _rag_ground(req.question)
    grounded = bool((grounding.get("context") or "").strip())

    # Optional operator-initiated web search — the ONLY egress here, gated on
    # the explicit request flag (default OFF).
    web_ctx = ""
    web_sources: List[Dict[str, Any]] = []
    if req.web_search:
        try:
            sr = await search_web(req.question)
            web_ctx = format_search_context(req.question, sr.results)
            web_sources = [s.to_dict() for s in sr.results]
        except Exception as exc:  # noqa: BLE001 — search failure degrades, never 5xx
            logger.warning("research followup web search failed: %s", exc)

    prompt_parts: List[str] = []
    if session.topic:
        prompt_parts.append(f"RESEARCH TOPIC: {session.topic}")
    if prior:
        prompt_parts.append(f"PRIOR SYNTHESIS:\n{prior}")
    if session.source_ids:
        prompt_parts.append(
            "SAVED SOURCES:\n" + "\n".join(f"- {u}" for u in session.source_ids[:20])
        )
    if grounding.get("context"):
        prompt_parts.append(grounding["context"])
    if web_ctx:
        prompt_parts.append(f"FRESH WEB RESULTS:\n{web_ctx}")
    prompt_parts.append(f"FOLLOW-UP QUESTION: {req.question}")
    user_prompt = "\n\n".join(prompt_parts)

    model = req.model or session.model or "dolphin3:latest"
    # A model failure is a 503 — never a fake turn. Nothing below this line
    # runs on failure, so no sentinel reaches the session / MOC / mirror.
    answer = _chat_or_503(
        "follow-up answer",
        model=model,
        messages=[
            {"role": "system", "content": _FOLLOWUP_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.6,
        max_tokens=1536,
    )

    # Attach the RAG hits (as reference rows) + any web sources to the turn.
    turn_sources: List[Dict[str, Any]] = []
    for r in grounding.get("results", []):
        turn_sources.append(
            {
                "kind": "rag",
                "title": r.get("filename", ""),
                "doc_id": r.get("doc_id", ""),
                "score": r.get("score"),
            }
        )
    turn_sources.extend({"kind": "web", **s} for s in web_sources)

    session = research_session.append_followup(
        req.session_id,
        question=req.question,
        answer=answer,
        sources=turn_sources,
        web_search=req.web_search,
        grounded=grounded,
    )
    if session is None:  # deleted mid-flight
        raise HTTPException(
            status_code=404, detail="research session vanished mid-turn"
        )

    return {
        "session_id": session.id,
        "question": req.question,
        "answer": answer,
        "grounded": grounded,
        "web_search": req.web_search,
        "sources": turn_sources,
        "turns": len(session.turns),
        "moc_path": session.moc_path,
        "model": model,
    }


# ── RX-2: actionable results → the Obsidian-like `research` store ────────────
#
# The operator turns a research result (a source, a synthesis, a graph node)
# into a durable, RAG-indexed markdown note inside the shared `research`
# workspace. Every note is ingest_markdown'd so it becomes semantically
# recallable by later follow-ups. Web egress happens ONLY inside the two
# operator-triggered refresh handlers below (compare-node, graph-walk) — never
# on a read/tab-activation.


def _derive_slug(text: str) -> str:
    """Reduce free text to a filename-safe slug from the strict allowlist.

    Lowercase; runs of non-allowlist chars collapse to a single '-'. The result
    is guaranteed to contain only ``_SLUG_CHARS`` (so it can never carry a path
    separator or ``..``)."""
    out: List[str] = []
    prev_dash = False
    for ch in (text or "").lower():
        if ch in _SLUG_CHARS and ch not in "-_":
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    slug = "".join(out).strip("-_")[:_SLUG_MAX].strip("-_")
    return slug or "note"


def _validate_slug(slug: str) -> str:
    """Containment guard for a client-supplied slug: reject anything that isn't
    purely the safe charset (mirrors prompts.py id validation). Empty / '.' /
    '..' / anything with a separator raises 400."""
    s = (slug or "").strip()
    if not s or s in (".", "..") or not all(c in _SLUG_CHARS for c in s):
        raise HTTPException(status_code=400, detail=f"unsafe store slug: {slug!r}")
    return s[:_SLUG_MAX]


def _write_store_note(subdir: str, slug: str, markdown: str) -> str:
    """Atomically write a markdown note into the research store and return its
    workspace-relative path. Containment is enforced three ways: subdir is from
    a fixed allowlist, slug is charset-validated, and the resolved path is
    checked to sit inside the workspace root (defense in depth)."""
    if subdir not in _STORE_SUBDIRS:
        raise HTTPException(status_code=400, detail=f"unknown store area: {subdir!r}")
    ws = research_session.ensure_research_workspace()
    if ws is None:
        raise HTTPException(status_code=503, detail="research workspace unavailable")
    rel = f"{subdir}/{slug}.md"
    # Resolve inside the workspace (raises WorkspaceViolation on escape).
    from ..services.workspace import WorkspaceViolation

    try:
        target = ws.resolve(rel)
    except WorkspaceViolation as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    target.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: tmp + os.replace, mirroring the session-store idiom.
    tmp = target.with_suffix(".md.tmp")
    tmp.write_text(markdown, encoding="utf-8")
    os.replace(tmp, target)
    return rel


class SaveSourceRequest(BaseModel):
    title: str = Field(..., min_length=1, description="Human title for the note")
    content: str = Field("", description="Markdown body")
    url: Optional[str] = Field(None, description="Origin url, recorded in the note")
    tags: Optional[List[str]] = None
    # Which store area to write into. sources = saved research results,
    # notes = operator/agent notes. Constrained to the store layout.
    area: str = Field("sources", description="Store subdir: sources|notes")
    slug: Optional[str] = Field(
        None, description="Explicit slug (else derived from title)"
    )


@router.post("/save-source")
async def save_source(req: SaveSourceRequest) -> Dict[str, Any]:
    """Save a research result as a durable markdown note + RAG-index it.

    This is the ``research.save-source`` action's backend: it writes
    ``<area>/<slug>.md`` into the shared `research` workspace (atomic, contained)
    and hands the markdown to ``ingest_markdown`` so it becomes searchable. No
    egress — the content is already in hand."""
    slug = _validate_slug(req.slug) if req.slug else _derive_slug(req.title)
    body = req.content or ""
    lines = [f"# {req.title}", ""]
    if req.url:
        lines.append(f"> source: {req.url}")
        lines.append("")
    lines.append(body)
    if req.tags:
        lines.append("")
        lines.append("_tags: " + ", ".join(str(t) for t in req.tags) + "_")
    md = "\n".join(lines).rstrip() + "\n"

    rel = _write_store_note(req.area, slug, md)
    rag_ingested = rag_ingest.ingest_markdown(
        title=req.title, body=body, tags=req.tags, doc_id=slug
    )
    return {
        "path": rel,
        "slug": slug,
        "area": req.area,
        "rag_ingested": rag_ingested,
        "workspace": research_session.RESEARCH_WORKSPACE,
    }


# ── Exploratory compare + resumable graph walk (operator-triggered egress) ──

_COMPARE_SYSTEM = (
    "You are a research analyst. Compare the FOCUS against the CONTEXT (prior "
    "findings + any fresh web results) and return a structured markdown answer "
    "with EXACTLY these sections, each a level-2 heading: '## Agreements', "
    "'## Contradictions', '## New angles', '## Open questions'. Be concise; "
    "ground claims in the provided material and say so plainly when the material "
    "is thin rather than inventing facts."
)


class CompareNodeRequest(BaseModel):
    focus: str = Field(..., min_length=1, description="Node label / topic to compare")
    against: Optional[str] = Field(None, description="Prior context to compare against")
    # Operator-initiated: a fresh web search only runs when this is ticked ON.
    web_search: bool = False
    model: Optional[str] = None
    session_id: Optional[str] = None
    save: bool = Field(False, description="Persist the comparison as a store note")


def _split_sections(markdown: str) -> Dict[str, str]:
    """Split a '## Heading' structured answer into {heading: body}. Best-effort;
    an unstructured answer lands under a single 'Summary' key."""
    sections: Dict[str, str] = {}
    current = "Summary"
    buf: List[str] = []
    for line in (markdown or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if buf:
                sections[current] = "\n".join(buf).strip()
                buf = []
            current = stripped[3:].strip() or current
        else:
            buf.append(line)
    if buf:
        sections[current] = "\n".join(buf).strip()
    return {k: v for k, v in sections.items() if v}


@router.post("/compare-node")
async def compare_node(req: CompareNodeRequest) -> Dict[str, Any]:
    """Compare a graph/research node against prior findings + (opt-in) fresh web
    results, returning structured sections. The ONLY egress is the operator-
    ticked web search on THIS request."""
    grounding = _rag_ground(req.focus)
    web_ctx = ""
    web_sources: List[Dict[str, Any]] = []
    if req.web_search:
        try:
            sr = await search_web(req.focus)
            web_ctx = format_search_context(req.focus, sr.results)
            web_sources = [s.to_dict() for s in sr.results]
        except Exception as exc:  # noqa: BLE001 — search failure degrades
            logger.warning("research compare web search failed: %s", exc)

    parts: List[str] = [f"FOCUS: {req.focus}"]
    if req.against:
        parts.append(f"PRIOR CONTEXT:\n{req.against[:_MAX_PRIOR_CHARS]}")
    if grounding.get("context"):
        parts.append(grounding["context"])
    if web_ctx:
        parts.append(f"FRESH WEB RESULTS:\n{web_ctx}")
    user_prompt = "\n\n".join(parts)

    # 503 on model failure — a comparison is never saved / ingested / walked
    # over as a sentinel string.
    answer = _chat_or_503(
        "comparison",
        model=req.model or "dolphin3:latest",
        messages=[
            {"role": "system", "content": _COMPARE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.5,
        max_tokens=1280,
    )

    sections = _split_sections(answer)
    saved_path: Optional[str] = None
    if req.save and answer.strip():
        slug = _derive_slug(f"compare-{req.focus}")
        md = f"# Comparison: {req.focus}\n\n{answer}\n"
        try:
            saved_path = _write_store_note("notes", slug, md)
            rag_ingest.ingest_markdown(
                title=f"Comparison: {req.focus}",
                body=answer,
                tags=["research", "compare"],
                doc_id=slug,
            )
        except HTTPException:
            saved_path = None

    return {
        "focus": req.focus,
        "answer": answer,
        "sections": sections,
        "grounded": bool((grounding.get("context") or "").strip()),
        "web_search": req.web_search,
        "sources": web_sources,
        "saved_path": saved_path,
    }


class GraphWalkRequest(BaseModel):
    # Optional seed list of node labels to walk. When present they are (idempotently)
    # added to the durable worklist; when absent, the walk resumes the existing one.
    nodes: Optional[List[str]] = None
    index: str = Field("graph-walk", description="Worklist name inside the workspace")
    web_search: bool = False
    model: Optional[str] = None
    # requeue interrupted items at the start of a walk (resume prep).
    requeue_stale: bool = False
    # also requeue items that ERRORED (model/search outage) on a prior step so
    # the walk retries them once the box is healthy again.
    retry_errors: bool = False


@router.post("/graph-walk")
async def graph_walk(req: GraphWalkRequest) -> Dict[str, Any]:
    """Advance a resumable exploratory walk over the research store.

    Uses the workspace durable index (the same ``/index/{name}/next`` worklist
    Operate's resumable loops use) so a walk survives interruption: each call
    claims the next pending node, runs a structured compare on it, records the
    result as a store note + appends to a MOC report, and marks the item done.
    Returns the item just processed + live counts; when the worklist is drained
    the walk is complete. Egress is the operator-ticked web search only.

    A model failure marks the claimed item ``error`` (never ``done``), writes
    nothing durable, and surfaces as the model's 503 — pass ``retry_errors``
    on a later walk to requeue errored items."""
    from ..services.workspace_index import WorkspaceIndex

    ws = research_session.ensure_research_workspace()
    if ws is None:
        raise HTTPException(status_code=503, detail="research workspace unavailable")
    idx = WorkspaceIndex(ws, req.index)

    if req.nodes:
        idx.add_items([{"id": _derive_slug(n), "title": n} for n in req.nodes if n])
    if req.requeue_stale:
        idx.requeue_stale()
    if req.retry_errors:
        idx.requeue_errors()

    nxt = idx.next_pending(claim=True)
    if nxt is None:
        return {
            "item": None,
            "complete": idx.is_complete(),
            "counts": idx.counts(),
            "index": req.index,
            "report_path": f"notes/{_derive_slug(req.index)}-report.md",
        }

    label = nxt.title or nxt.id or ""
    item_id = nxt.id
    try:
        result = await compare_node(
            CompareNodeRequest(focus=label, web_search=req.web_search, model=req.model)
        )
    except HTTPException as exc:
        # The claimed item must NOT be marked done (it was), and the failure
        # text must NOT become a note / MOC section / RAG document (it did).
        # Record ``error`` so the worklist stays honest and resumable:
        # ``retry_errors`` on a later walk requeues it.
        try:
            idx.set_status(item_id, "error", note=str(exc.detail)[:500])
        except Exception as inner:  # noqa: BLE001 — status is best-effort
            logger.warning("graph-walk could not mark %s error: %s", item_id, inner)
        raise HTTPException(
            status_code=exc.status_code,
            detail=f"graph-walk step '{label}' failed and was marked error "
            f"(retry with retry_errors=true): {exc.detail}",
            headers=exc.headers,
        )
    answer = result.get("answer", "")
    slug = _derive_slug(f"{req.index}-{label}")
    note_path: Optional[str] = None
    try:
        note_path = _write_store_note("notes", slug, f"# {label}\n\n{answer}\n")
        rag_ingest.ingest_markdown(
            title=label, body=answer, tags=["research", "graph-walk"], doc_id=slug
        )
    except HTTPException:
        note_path = None

    # Append to the MOC report (created on first walk step).
    report_rel = f"notes/{_derive_slug(req.index)}-report.md"
    try:
        section = f"## {label}\n\n{answer}\n"
        if ws.exists(report_rel):
            ws.expand(report_rel, section)
        else:
            ws.write(report_rel, f"# Graph walk: {req.index}\n\n{section}")
    except Exception as exc:  # noqa: BLE001 — MOC is additive
        logger.debug("graph-walk report write skipped: %s", exc)

    idx.set_status(item_id, "done", artifact=note_path or "")
    return {
        "item": {"id": item_id, "label": label, "note_path": note_path},
        "sections": result.get("sections", {}),
        "complete": idx.is_complete(),
        "counts": idx.counts(),
        "index": req.index,
        "report_path": report_rel,
    }
