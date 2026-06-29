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

import yaml

from ..logging_config import logger

EXPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "exports"
GRAPH_CACHE = (
    Path(__file__).parent.parent.parent / "data" / "graph" / "knowledge_graph.json"
)
GRAPH_TTL = 300  # seconds before cache is stale
AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"
WORKFLOWS_DIR = Path(__file__).parent.parent.parent / "data" / "workflows"

STOP_WORDS = {
    "the",
    "and",
    "for",
    "are",
    "but",
    "not",
    "you",
    "all",
    "can",
    "had",
    "her",
    "was",
    "one",
    "our",
    "out",
    "day",
    "get",
    "has",
    "him",
    "his",
    "how",
    "its",
    "let",
    "may",
    "now",
    "old",
    "say",
    "see",
    "two",
    "who",
    "did",
    "does",
    "from",
    "have",
    "been",
    "that",
    "this",
    "they",
    "with",
    "will",
    "which",
    "what",
    "when",
    "where",
    "than",
    "then",
    "here",
    "also",
    "into",
    "some",
    "could",
    "would",
    "should",
    "about",
    "more",
    "very",
    "just",
    "like",
    "your",
    "most",
    "over",
    "come",
    "even",
    "back",
    "chat",
    "session",
    "model",
    "user",
    "assistant",
    "local",
    "message",
    "field",
    "value",
    "total",
    "tokens",
    "duration",
    "messages",
    "enabled",
    "disabled",
    "based",
    "search",
    "using",
    "these",
    "there",
    "their",
    "other",
    "after",
    "before",
    "between",
    "through",
    "each",
    "only",
    "such",
    "both",
    "many",
    "much",
    "well",
    "also",
    "while",
    "being",
    "given",
    "make",
    "made",
    "give",
    "take",
    "used",
    "use",
    "new",
    "need",
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


# ── Agent & Workflow Helpers ───────────────────────────────────────────────


def _build_agent_nodes(nodes: List[Dict], links: List[Dict], topic_set: set) -> None:
    """Scan agents/*.yaml and add agent nodes + uses links to matching topics."""
    if not AGENTS_DIR.is_dir():
        return
    for filepath in sorted(AGENTS_DIR.glob("*.yaml")):
        try:
            with open(filepath, encoding="utf-8") as f:
                agent = yaml.safe_load(f)
            if not agent or not isinstance(agent, dict):
                continue
            agent_id = agent.get("id", filepath.stem)
            node = {
                "id": f"agent:{agent_id}",
                "type": "agent",
                "name": agent.get("name", agent_id),
                "description": agent.get("description", ""),
                "icon": agent.get("icon", ""),
                "model": agent.get("model", ""),
                "role": agent.get("role", ""),
                "tags": agent.get("tags", []),
            }
            nodes.append(node)

            # Build match words from tags + context query words
            match_words: set = set()
            for tag in agent.get("tags", []):
                match_words.add(tag.lower())
            # Extract words from context entries (graph_query or description)
            for ctx in agent.get("context", []):
                if isinstance(ctx, dict):
                    label = ctx.get("label", "")
                    for word in re.findall(r"\b[a-zA-Z]{4,}\b", label.lower()):
                        if word not in STOP_WORDS:
                            match_words.add(word)

            for word in match_words:
                topic_id = f"topic:{word}"
                if topic_id in topic_set:
                    links.append(
                        {
                            "source": f"agent:{agent_id}",
                            "target": topic_id,
                            "type": "uses",
                        }
                    )
        except Exception as e:
            logger.warning(f"Failed to parse agent {filepath.name}: {e}")


def _build_workflow_nodes(nodes: List[Dict], links: List[Dict], topic_set: set) -> None:
    """Scan data/workflows/*/run.json and add workflow_run nodes + produced links."""
    if not WORKFLOWS_DIR.is_dir():
        return
    run_files = sorted(
        WORKFLOWS_DIR.glob("*/run.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )

    for filepath in run_files[:20]:
        try:
            run_data = json.loads(filepath.read_text(encoding="utf-8"))
            run_id = run_data.get("run_id", filepath.parent.name)
            status = run_data.get("status", "unknown")
            workflow_id = run_data.get("workflow_id", "unknown")

            # Calculate total duration and tokens from step results
            total_duration = 0.0
            total_tokens = 0
            for step in run_data.get("step_results", []):
                total_duration += step.get("duration_seconds", 0)
                tc = step.get("token_count", {})
                total_tokens += tc.get("total_tokens", 0)

            node = {
                "id": f"run:{run_id[:12]}",
                "type": "workflow_run",
                "name": workflow_id,
                "status": status,
                "duration": round(total_duration, 3),
                "tokens": total_tokens,
                "started_at": run_data.get("started_at", ""),
            }
            nodes.append(node)

            # Extract keywords from workspace outputs for topic matching
            workspace = run_data.get("context", {}).get("workspace", {})
            workspace_text = json.dumps(workspace).lower()
            for word in re.findall(r"\b[a-zA-Z]{4,}\b", workspace_text):
                if word in STOP_WORDS:
                    continue
                topic_id = f"topic:{word}"
                if topic_id in topic_set:
                    # Avoid duplicate links for the same run→topic
                    link_key = (f"run:{run_id[:12]}", topic_id)
                    if not any(
                        l["source"] == link_key[0] and l["target"] == link_key[1]
                        for l in links
                    ):
                        links.append(
                            {
                                "source": f"run:{run_id[:12]}",
                                "target": topic_id,
                                "type": "produced",
                            }
                        )
        except Exception as e:
            logger.warning(f"Failed to parse workflow run {filepath}: {e}")


def _build_provenance_nodes(nodes: List[Dict], links: List[Dict]) -> int:
    """Scan the provenance store and add response→source grounding edges.

    Each recorded response becomes a ``response`` node; every edge becomes a
    link to a source node (chunk / web / skill / tool), creating the source
    node on first sight. Link type encodes the relationship so the UI can
    colour grounded_on vs activated_skill vs invoked_tool distinctly.

    Returns the number of response nodes added.
    """
    try:
        from .provenance_store import get_provenance_store
    except Exception:  # noqa: BLE001
        return 0

    store = get_provenance_store()
    rows = store.list_responses()
    seen_sources: set = set()
    response_count = 0
    # Newest first, bounded — the graph is a navigation aid, not an archive.
    for prov in sorted(rows, key=lambda r: str(r.created_at), reverse=True)[:50]:
        edges = store.get_edges(prov.response_id)
        if not edges:
            continue
        rnode_id = f"response:{prov.response_id[:18]}"
        nodes.append(
            {
                "id": rnode_id,
                "type": "response",
                "label": (prov.content_preview or prov.response_id)[:48],
                "model": prov.model,
                "conversation_id": prov.conversation_id,
                "edge_count": len(edges),
            }
        )
        response_count += 1
        for e in edges:
            if e.source_type == "rag_chunk":
                sid, stype, ltype = f"chunk:{e.source_id}", "chunk", "grounded_on"
            elif e.source_type == "web_source":
                sid, stype, ltype = f"web:{e.source_id}", "source", "grounded_on"
            elif e.source_type == "skill":
                sid, stype, ltype = f"skill:{e.source_id}", "skill", "activated_skill"
            else:  # mcp_tool / plugin_tool
                sid, stype, ltype = f"tool:{e.source_id}", "tool", "invoked_tool"
            if sid not in seen_sources:
                nodes.append({"id": sid, "type": stype, "label": e.source_label[:40]})
                seen_sources.add(sid)
            links.append(
                {
                    "source": rnode_id,
                    "target": sid,
                    "type": ltype,
                    "weight": e.metadata.get("score") if e.metadata else None,
                }
            )
    return response_count


def _build_structural_links(nodes: List[Dict], links: List[Dict]) -> None:
    """Add agent↔agent, run↔run, agent↔run links that don't depend on
    session-derived topics. Keeps the knowledge graph readable on a
    fresh install (no sessions yet) so the operator can still see
    relationships between the agents and workflow runs they have.

    Link kinds:
      - "shares_tag"   : two agents share any tag
      - "shares_role"  : two agents have the same role
      - "same_workflow": two runs of the same workflow_id
      - "ran_role"     : an agent and a run that used that agent's role
    """
    agents = [n for n in nodes if n.get("type") == "agent"]
    runs = [n for n in nodes if n.get("type") == "workflow_run"]

    # Agent ↔ Agent — share tag / role
    for i, a in enumerate(agents):
        a_tags = {t for t in (a.get("tags") or []) if isinstance(t, str)}
        a_role = (a.get("role") or "").strip()
        for b in agents[i + 1 :]:
            b_tags = {t for t in (b.get("tags") or []) if isinstance(t, str)}
            shared = a_tags & b_tags
            if shared:
                links.append(
                    {
                        "source": a["id"],
                        "target": b["id"],
                        "type": "shares_tag",
                        "weight": len(shared),
                        "shared": sorted(shared)[:5],
                    }
                )
                continue
            b_role = (b.get("role") or "").strip()
            if a_role and a_role == b_role:
                links.append(
                    {
                        "source": a["id"],
                        "target": b["id"],
                        "type": "shares_role",
                        "weight": 1,
                        "shared": [a_role],
                    }
                )

    # Workflow_run ↔ Workflow_run — same workflow_id
    runs_by_wf: Dict[str, List[Dict]] = defaultdict(list)
    for r in runs:
        wf = r.get("name") or r.get("workflow_id")
        if wf:
            runs_by_wf[wf].append(r)
    for wf_id, group in runs_by_wf.items():
        # Chain rather than fully connect (avoids N^2 visual clutter
        # for workflows with many runs); the dataset can still walk
        # them via the chain.
        for prev, cur in zip(group, group[1:]):
            links.append(
                {
                    "source": prev["id"],
                    "target": cur["id"],
                    "type": "same_workflow",
                    "weight": 1,
                    "shared": [wf_id],
                }
            )

    # Agent ↔ Run — agent's role matched a step in the run. We don't
    # have step-level role data in the run node summary, so this is
    # tag-based: if the run's workflow_id (treated as name) contains
    # any of the agent's tags, link them. Cheap heuristic that
    # surfaces meaningful relationships without re-reading run.json.
    for a in agents:
        a_tags = [t.lower() for t in (a.get("tags") or []) if isinstance(t, str)]
        if not a_tags:
            continue
        for r in runs:
            hay = (r.get("name") or "").lower()
            if not hay:
                continue
            hits = [t for t in a_tags if t and t in hay]
            if hits:
                links.append(
                    {
                        "source": a["id"],
                        "target": r["id"],
                        "type": "ran_role",
                        "weight": len(hits),
                        "shared": hits[:3],
                    }
                )


# ── Graph Builder ──────────────────────────────────────────────────────────


def build_graph(force: bool = False) -> Dict[str, Any]:
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
                    {
                        "session_id": session["id"],
                        "url": src["url"],
                        "title": src["title"],
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to parse {filepath.name}: {e}")

    # Topic nodes — include topics shared by 2+ sessions or long enough to be significant
    topic_nodes_added: set = set()
    for topic, session_ids in topic_sessions.items():
        if len(session_ids) >= 2 or len(topic) > 8:
            node_id = f"topic:{topic}"
            if node_id not in topic_nodes_added:
                nodes.append(
                    {
                        "id": node_id,
                        "type": "topic",
                        "label": topic,
                        "session_count": len(session_ids),
                    }
                )
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
            nodes.append(
                {
                    "id": node_id,
                    "type": "source",
                    "label": domain,
                    "citation_count": len(refs),
                }
            )
            source_nodes_added.add(node_id)
        seen_sids: set = set()
        for ref in refs:
            if ref["session_id"] not in seen_sids:
                links.append(
                    {"source": ref["session_id"], "target": node_id, "type": "cites"}
                )
                seen_sids.add(ref["session_id"])

    # Session ↔ session similarity edges (shared topics)
    session_topic_sets: Dict[str, set] = {}
    for node in nodes:
        if node["type"] == "session":
            session_topic_sets[node["id"]] = set(node.get("topics", []))

    session_ids = list(session_topic_sets.keys())
    for i, sid_a in enumerate(session_ids):
        for sid_b in session_ids[i + 1 :]:
            shared = session_topic_sets[sid_a] & session_topic_sets[sid_b]
            if len(shared) >= 2:
                links.append(
                    {
                        "source": sid_a,
                        "target": sid_b,
                        "type": "related",
                        "weight": len(shared),
                        "shared_topics": list(shared)[:5],
                    }
                )

    # Agent and workflow run nodes (linked to existing topic nodes)
    _build_agent_nodes(nodes, links, topic_nodes_added)
    _build_workflow_nodes(nodes, links, topic_nodes_added)

    # Provenance: response→source grounding edges (the #1-gap citation chain).
    provenance_count = _build_provenance_nodes(nodes, links)

    # Structural links — added regardless of whether session exports
    # exist. Ensures the graph reads as connected even on a fresh
    # install (no sessions yet) so the operator can still drill in.
    _build_structural_links(nodes, links)

    # Count agent and workflow_run nodes
    agent_count = sum(1 for n in nodes if n.get("type") == "agent")
    run_count = sum(1 for n in nodes if n.get("type") == "workflow_run")

    graph = {
        "nodes": nodes,
        "links": links,
        "session_count": len(session_files),
        "topic_count": len(topic_nodes_added),
        "source_count": len(source_nodes_added),
        "agent_count": agent_count,
        "workflow_run_count": run_count,
        "provenance_count": provenance_count,
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


def search_nodes(query: str) -> List[Dict[str, Any]]:
    """Search the cached graph for nodes matching a query string.

    Performs case-insensitive substring matching on node name, label,
    description, and tags. Returns matching nodes for agent service
    graph_query context resolution.
    """
    graph = get_graph()
    if not query:
        return []
    q = query.lower()
    results: List[Dict[str, Any]] = []
    for node in graph.get("nodes", []):
        searchable = " ".join(
            str(v)
            for k, v in node.items()
            if k in ("name", "label", "description", "tags") and v
        )
        if q in searchable.lower():
            results.append(node)
    return results
