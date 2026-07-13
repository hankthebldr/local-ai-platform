#!/usr/bin/env python3
"""
Graph Router — Knowledge graph data and deep research endpoints.

GET  /api/graph           → Return cached graph JSON for D3.js
POST /api/graph/rebuild   → Force rebuild from all session exports
POST /api/research/deep-dive → Orchestrated multi-step research with web search
"""

import json
import os
import re
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..services.graph_service import build_graph, get_graph
from ..services.search_service import search as search_web, format_search_context
from ..services.ollama_service import OllamaService

router = APIRouter(tags=["graph"])

_ollama = OllamaService(os.getenv("OLLAMA_HOST", "http://localhost:11434"))


# ── Graph Endpoints ────────────────────────────────────────────────────────


@router.get("/api/graph")
async def graph_data():
    """Return knowledge graph (nodes + links) for D3.js visualization."""
    return get_graph()


@router.post("/api/graph/rebuild")
async def rebuild_graph():
    """Force-rebuild the knowledge graph by re-parsing all session exports."""
    graph = build_graph()
    return {
        "status": "rebuilt",
        "nodes": len(graph["nodes"]),
        "links": len(graph["links"]),
        "sessions": graph["session_count"],
        "topics": graph["topic_count"],
        "sources": graph["source_count"],
    }


# ── Deep Research Endpoint ─────────────────────────────────────────────────


class DeepDiveRequest(BaseModel):
    topic: str = Field(..., description="Research topic or question")
    model: str = Field("dolphin3:latest", description="Ollama model to use")
    depth: int = Field(3, ge=1, le=5, description="Number of sub-questions to explore")
    # RX-1: optional session to continue. When present the fresh synthesis is
    # appended to that session; when absent a new session is minted. The
    # response always carries the resulting `session_id`.
    session_id: Optional[str] = Field(
        None, description="Existing ResearchSession id to continue (optional)"
    )


@router.post("/api/research/deep-dive")
async def deep_dive(req: DeepDiveRequest):
    """
    Orchestrated deep research:
      1. Use model to decompose topic into N sub-questions
      2. Web search each sub-question
      3. Synthesize gathered context into a structured report
    """
    logger.info(f"Deep dive: topic='{req.topic}', model={req.model}, depth={req.depth}")

    # ── Step 1: Generate sub-questions ──────────────────────────────────
    breakdown_prompt = (
        f"Break this research topic into {req.depth} specific, searchable sub-questions.\n"
        f"Return ONLY a JSON array of strings. No explanation, no markdown, just the array.\n"
        f"Topic: {req.topic}\n"
        f'Example: ["What is X?", "How does Y work?", "What are Z implications?"]'
    )

    sub_questions = [req.topic]
    try:
        result = _ollama.chat(
            model=req.model,
            messages=[{"role": "user", "content": breakdown_prompt}],
            temperature=0.3,
            max_tokens=512,
        )
        raw = result.get("content", "[]")
        arr_match = re.search(r"\[.+?\]", raw, re.DOTALL)
        if arr_match:
            parsed = json.loads(arr_match.group(0))
            if isinstance(parsed, list) and parsed:
                sub_questions = [str(q) for q in parsed[: req.depth]]
    except Exception as e:
        logger.warning(f"Sub-question generation failed: {e}")

    # ── Step 2: Search each sub-question ────────────────────────────────
    research_sections = []
    all_sources = []

    for question in sub_questions:
        try:
            search_result = await search_web(question)
            context = format_search_context(question, search_result.results)
            sources = [s.to_dict() for s in search_result.results]
            all_sources.extend(sources)
            research_sections.append({
                "question": question,
                "context": context,
                "sources": sources,
            })
        except Exception as e:
            logger.warning(f"Search failed for '{question}': {e}")
            research_sections.append({"question": question, "context": "", "sources": []})

    # ── Step 3: Synthesize ───────────────────────────────────────────────
    context_block = "\n\n".join(
        f"### {s['question']}\n{s['context']}"
        for s in research_sections
        if s["context"]
    )

    synthesis_prompt = (
        f"You are a research synthesizer. Write a comprehensive, well-structured research report on:\n\n"
        f"**{req.topic}**\n\n"
        f"Structure your response with:\n"
        f"- **Executive Summary** (2–3 sentences)\n"
        f"- **Key Findings** (bulleted)\n"
        f"- **Detailed Analysis** (subsections)\n"
        f"- **Conclusions**\n\n"
        f"Use markdown formatting. Cite sources as [1], [2], etc. when referencing specific claims.\n\n"
        f"GATHERED RESEARCH:\n{context_block or 'No web search results available — use your training knowledge.'}"
    )

    synthesis = "Research synthesis unavailable."
    try:
        synth_result = _ollama.chat(
            model=req.model,
            messages=[{"role": "user", "content": synthesis_prompt}],
            temperature=0.7,
            max_tokens=2048,
        )
        synthesis = synth_result.get("content", synthesis)
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        synthesis = f"Synthesis error: {e}"

    # Deduplicate sources
    seen_urls: set = set()
    unique_sources = []
    for src in all_sources:
        url = src.get("url", "")
        if url and url not in seen_urls:
            unique_sources.append(src)
            seen_urls.add(url)

    # ── RX-1: mint (or continue) a stateful research session ─────────────
    # Turns the one-shot deep-dive into a resumable, followable session and
    # writes a human-readable MOC into the shared `research` workspace. Best
    # effort: a session-store failure never fails the research response.
    session_id: Optional[str] = None
    try:
        from ..services import research_session

        session = research_session.record_deep_dive(
            topic=req.topic,
            model=req.model,
            source_ids=[s.get("url", "") for s in unique_sources if s.get("url")],
            synthesis=synthesis,
            sub_questions=sub_questions,
            session_id=req.session_id,
        )
        session_id = session.id
    except Exception as e:  # noqa: BLE001 — session mint is additive
        logger.warning(f"Research session mint failed: {e}")

    return {
        "topic": req.topic,
        "model": req.model,
        "sub_questions": sub_questions,
        "research": research_sections,
        "synthesis": synthesis,
        "sources": unique_sources,
        "session_id": session_id,
    }
