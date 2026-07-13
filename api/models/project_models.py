"""
Project Data Models

A "project" is a typed bundle that groups workflows, agents, MCP server
refs, plugin refs, model preferences, RAG documents, and saved chat
sessions into a unit that can be exported, imported, and reasoned about
as a coherent set of artifacts.

Stored as YAML under data/projects/<id>.yaml so the format mirrors how
workflows and agents are persisted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

VALID_ID_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


def _validate_id(value: str) -> str:
    if not value or len(value) > 64:
        raise ValueError("id must be 1..64 chars")
    if not all(c in VALID_ID_CHARS for c in value):
        raise ValueError("id may only contain alphanumerics, '_', or '-'")
    return value


class ProjectArtifacts(BaseModel):
    """Typed references to artifacts owned by a project."""

    workflows: List[str] = Field(default_factory=list)
    agents: List[str] = Field(default_factory=list)
    mcp_servers: List[str] = Field(default_factory=list)
    plugins: List[str] = Field(default_factory=list)
    models: List[str] = Field(default_factory=list)
    documents: List[str] = Field(default_factory=list)
    chats: List[str] = Field(default_factory=list)


class ProjectDefinition(BaseModel):
    """Full project record as stored on disk."""

    id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    artifacts: ProjectArtifacts = Field(default_factory=ProjectArtifacts)
    system_prompt: Optional[str] = Field(
        None,
        description="Optional master system prompt applied to chats opened "
        "from this project's context.",
    )
    context_workspace: Optional[str] = Field(
        None,
        description="Name of the bound docs Workspace (proj-<id>) registered "
        "via POST /api/projects/{id}/context-workspace. None until bound.",
    )
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("id")
    @classmethod
    def _vid(cls, v: str) -> str:
        return _validate_id(v)


class ProjectCreate(BaseModel):
    """Payload for POST /api/projects."""

    id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    artifacts: ProjectArtifacts = Field(default_factory=ProjectArtifacts)
    system_prompt: Optional[str] = None

    @field_validator("id")
    @classmethod
    def _vid(cls, v: str) -> str:
        return _validate_id(v)


class ProjectUpdate(BaseModel):
    """Partial update payload."""

    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    artifacts: Optional[ProjectArtifacts] = None
    system_prompt: Optional[str] = None


# ── Doc → Agent generation ────────────────────────────────────────────────


class AgentGenerationRequest(BaseModel):
    """Request to convert a document (or text) into a draft agent."""

    document_id: Optional[str] = Field(
        None, description="ID of a previously-uploaded document"
    )
    text: Optional[str] = Field(
        None, description="Raw text input (alternative to document_id)"
    )
    name_hint: Optional[str] = None
    role_hint: Optional[str] = None
    model: Optional[str] = Field(
        None, description="Model to use for the analyzer LLM call"
    )
    include_source_as_context: bool = True


class AgentGenerationResult(BaseModel):
    """Draft agent produced by the generator. Returned to the UI for review."""

    draft: Dict[str, Any]  # an AgentDefinition-shaped dict
    suggestions: Dict[str, Any] = Field(
        default_factory=dict,
        description="Auxiliary suggestions: alt prompts, model picks, etc.",
    )
    source: Dict[str, Any] = Field(
        default_factory=dict,
        description="What was used as the source (document id, text snippet)",
    )


class AgentEvaluationCase(BaseModel):
    """A single eval case: prompt + expected substring."""

    prompt: str
    expected_contains: Optional[str] = None


class AgentEvaluationRequest(BaseModel):
    """Run an agent against a set of eval cases."""

    cases: List[AgentEvaluationCase]


class AgentEvaluationCaseResult(BaseModel):
    prompt: str
    response: str
    expected_contains: Optional[str] = None
    passed: bool
    duration_seconds: float


class AgentEvaluationReport(BaseModel):
    agent_id: str
    passed: int
    failed: int
    cases: List[AgentEvaluationCaseResult]
