"""Provenance models — response → source grounding chains.

The #1 gap closed by the gap-closure track: every chat or workflow response
that was grounded on something (a retrieved RAG chunk, a web source, an
activated skill, an invoked plugin/MCP tool) now records *what* it was
grounded on. Those records — ``ProvenanceEdge`` rows keyed by a stable
``response_id`` — feed the citation rail under chat messages and the
knowledge graph's grounded_on / activated_skill / invoked_tool edges.

A response with no edges is fine (an ungrounded model answer); the absence
is itself information the UI can surface ("no sources").
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

SourceType = Literal[
    "rag_chunk",  # a retrieved document chunk (RAG)
    "web_source",  # a web-search result page
    "skill",  # an activated plugin skill
    "mcp_tool",  # an invoked MCP-server tool
    "plugin_tool",  # an invoked in-process plugin tool
]


class ProvenanceEdge(BaseModel):
    """One grounding link: ``response_id`` was grounded on ``source_id``.

    ``source_id`` is stable and type-specific:
      * rag_chunk   → ``"{doc_id}::chunk_{i}"``
      * web_source  → the result URL
      * skill       → ``"{plugin_id}.{skill_id}"``
      * mcp_tool    → ``"{server_id}.{tool_name}"``
      * plugin_tool → ``"{plugin_id}.{tool_id}"``
    """

    response_id: str
    source_type: SourceType
    source_id: str
    source_label: str  # human-readable (filename, page title, skill name…)
    # Type-specific extras: rag score, chunk_index, mcp duration_ms/status, etc.
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResponseProvenance(BaseModel):
    """The header record for a single response's grounding chain."""

    response_id: str
    conversation_id: Optional[str] = None
    model: Optional[str] = None
    origin: Literal["chat", "workflow"] = "chat"
    content_preview: str = ""  # first ~500 chars of the answer, for the graph label
    edges: List[ProvenanceEdge] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
