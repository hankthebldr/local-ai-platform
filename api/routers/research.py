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
from ..services import research_session
from ..services.ollama_service import OllamaService
from ..services.search_service import format_search_context
from ..services.search_service import search as search_web

router = APIRouter(prefix="/api/research", tags=["research"])

_ollama = OllamaService(os.getenv("OLLAMA_HOST", "http://localhost:11434"))

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
        from ..routers.documents import rag_service
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
        raise HTTPException(status_code=404, detail=f"research session '{session_id}' not found")
    return session.model_dump()


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
    answer = ""
    try:
        result = _ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": _FOLLOWUP_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.6,
            max_tokens=1536,
        )
        answer = (result or {}).get("content", "") or ""
    except Exception as exc:  # noqa: BLE001 — model failure surfaces as a turn
        logger.error("research followup model call failed: %s", exc)
        answer = f"_Answer unavailable — the local model call failed: {exc}_"

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
        raise HTTPException(status_code=404, detail="research session vanished mid-turn")

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
