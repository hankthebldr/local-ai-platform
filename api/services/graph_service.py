#!/usr/bin/env python3
"""
Graph Service — Build a knowledge graph from exported Markdown session files.

Extracts topics, sources, and session relationships from data/exports/*.md
and produces a JSON graph (nodes + links) for D3.js visualization.
"""

import json
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from ..logging_config import logger

EXPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "exports"
GRAPH_CACHE = Path(__file__).parent.parent.parent / "data" / "graph" / "knowledge_graph.json"
GRAPH_TTL = 300  # seconds before cache is stale

STOP_WORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had", "her",
    "was", "one", "our", "out", "day", "get", "has", "him", "his", "how", "its",
    "let", "may", "now", "old", "say", "see", "two", "who", "did", "does", "from",
    "have", "been", "that", "this", "they", "with", "will", "which", "what", "when",
    "where", "than", "then", "here", "also", "into", "some", "could", "would",
    "should", "about", "more", "very", "just", "like", "your", "most", "over",
    "come", "even", "back", "chat", "session", "model", "user", "assistant",
    "local", "message", "field", "value", "total", "tokens", "duration",
    "messages", "enabled", "disabled", "based", "search", "using", "these",
    "there", "their", "other", "after", "before", "between", "through", "each",
    "only", "such", "both", "many", "much", "well", "also", "while", "being",
    "given", "make", "made", "give", "take", "used", "use", "new", "need",
}


# ── Parsing Helpers ────────────────────────────────────────────────────────


def _extract_topics(text: str, max_topics: int = 12) -> List[str]:
    """Extract meaningful topic keywords from session text."""
    freq: Dict[str, int] = defaultdict(int)

    # Individual words (4+ chars, not stop words)
    for word in re.findall(r"\b[a-zA-Z][a-zA-Z\-]{3,}\b", text.lower()):
        if word not in STOP_WORDS:
            freq[word] += 1

    # Boost heading text (H1–H3 carry more semantic weight)
    for heading in re.findall(r"^#{1,3}\s+(.+)$", text, re.MULTILINE):
        phrase = heading.strip()
        if 3 < len(phrase) < 60:
            clean = re.sub(r"[^\w\s\-]", "", phrase).lower().strip()
            if clean and clean not in STOP_WORDS:
                freq[clean] += 3

    sorted_topics = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [t for t, c in sorted_topics[:max_topics] if c >= 2]


def _extract_sources(text: str) -> List[Dict[str, str]]:
    """Extract cited URLs from session markdown (markdown links)."""
    sources = []
    seen = set()
    for m in re.finditer(r"\[([^\]]+)\]\((https?://[^\)]+)\)", text):
        title, url = m.group(1), m.group(2)
        if url in seen:
            continue
        seen.add(url)
        domain = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
        sources.append({"title": title, "url": url, "domain": domain})
    return sources[:10]


def _parse_session(filepath: Path) -> Dict[str, Any]:
    """Parse a session .md file into a structured graph node."""
    content = filepath.read_text(encoding="utf-8")

    title_m = re.search(r"^# (.+)$", content, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else filepath.stem

    model_m = re.search(r"\|\s*Model\s*\|\s*([^\|]+)\s*\|", content)
    model = model_m.group(1).strip() if model_m else "unknown"

    date_m = re.search(r"\|\s*(?:Date|Started|Time)\s*\|\s*([^\|]+)\s*\|", content)
    date = date_m.group(1).strip() if date_m else ""

    stat = filepath.stat()
    return {
        "id": f"session:{filepath.stem}",
        "type": "session",
        "label": title,
        "filename": filepath.name,
        "model": model,
        "date": date,
        "topics": _extract_topics(content),
        "sources": _extract_sources(content),
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "preview": content[:400],
    }


# ── Graph Builder ──────────────────────────────────────────────────────────


def build_graph() -> Dict[str, Any]:
    """Parse all session exports and build the knowledge graph."""
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    GRAPH_CACHE.parent.mkdir(parents=True, exist_ok=True)

    nodes: List[Dict] = []
    links: List[Dict] = []
    topic_sessions: Dict[str, List[str]] = defaultdict(list)
    source_sessions: Dict[str, List[Dict]] = defaultdict(list)

    session_files = list(EXPORTS_DIR.glob("*.md"))
    for filepath in session_files:
        try:
            session = _parse_session(filepath)
            nodes.append(session)
            for topic in session["topics"]:
                topic_sessions[topic].append(session["id"])
            for src in session["sources"]:
                source_sessions[src["domain"]].append(
                    {"session_id": session["id"], "url": src["url"], "title": src["title"]}
                )
        except Exception as e:
            logger.warning(f"Failed to parse {filepath.name}: {e}")

    # Topic nodes — include topics shared by 2+ sessions or long enough to be significant
    topic_nodes_added: set = set()
    for topic, session_ids in topic_sessions.items():
        if len(session_ids) >= 2 or len(topic) > 8:
            node_id = f"topic:{topic}"
            if node_id not in topic_nodes_added:
                nodes.append({
                    "id": node_id,
                    "type": "topic",
                    "label": topic,
                    "session_count": len(session_ids),
                })
                topic_nodes_added.add(node_id)
            for sid in session_ids:
                links.append({"source": sid, "target": node_id, "type": "mentions"})

    # Source domain nodes
    source_nodes_added: set = set()
    for domain, refs in source_sessions.items():
        if not domain:
            continue
        node_id = f"source:{domain}"
        if node_id not in source_nodes_added:
            nodes.append({
                "id": node_id,
                "type": "source",
                "label": domain,
                "citation_count": len(refs),
            })
            source_nodes_added.add(node_id)
        seen_sids: set = set()
        for ref in refs:
            if ref["session_id"] not in seen_sids:
                links.append({"source": ref["session_id"], "target": node_id, "type": "cites"})
                seen_sids.add(ref["session_id"])

    # Session ↔ session similarity edges (shared topics)
    session_topic_sets: Dict[str, set] = {}
    for node in nodes:
        if node["type"] == "session":
            session_topic_sets[node["id"]] = set(node.get("topics", []))

    session_ids = list(session_topic_sets.keys())
    for i, sid_a in enumerate(session_ids):
        for sid_b in session_ids[i + 1:]:
            shared = session_topic_sets[sid_a] & session_topic_sets[sid_b]
            if len(shared) >= 2:
                links.append({
                    "source": sid_a,
                    "target": sid_b,
                    "type": "related",
                    "weight": len(shared),
                    "shared_topics": list(shared)[:5],
                })

    graph = {
        "nodes": nodes,
        "links": links,
        "session_count": len(session_files),
        "topic_count": len(topic_nodes_added),
        "source_count": len(source_nodes_added),
        "built_at": time.time(),
    }

    GRAPH_CACHE.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    logger.info(
        f"Knowledge graph built: {len(nodes)} nodes, {len(links)} links "
        f"({len(session_files)} sessions)"
    )
    return graph


def get_graph() -> Dict[str, Any]:
    """Return cached graph, rebuilding if stale or missing."""
    if GRAPH_CACHE.exists():
        age = time.time() - GRAPH_CACHE.stat().st_mtime
        if age < GRAPH_TTL:
            try:
                return json.loads(GRAPH_CACHE.read_text(encoding="utf-8"))
            except Exception:
                pass
    return build_graph()
