"""
Agent System Data Models — Custom Agent / Gem Builder

Pydantic v2 models for:
- Agent definitions with system prompts, context sources, and tools
- YAML-backed persistence for portable agent configurations
- Context resolution from files, URLs, graph queries, and workflow outputs
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ── Context Source ───────────────────────────────────────────────────────


class ContextSource(BaseModel):
    """A source of context injected into the agent's system prompt"""
    type: Literal["file", "url", "graph_query", "workflow_output", "text"]
    value: str
    label: Optional[str] = None


# ── Agent Tool ───────────────────────────────────────────────────────────


class AgentTool(BaseModel):
    """A tool available to the agent during conversation"""
    type: Literal["web_search", "workflow", "code_exec"]
    config: Dict[str, Any] = Field(default_factory=dict)


# ── Agent Definition ─────────────────────────────────────────────────────


class AgentDefinition(BaseModel):
    """
    Complete agent definition — a custom AI persona with context and tools.

    Agents are defined in YAML files under the agents/ directory and can be
    loaded, edited, and used for chat sessions via the API.
    """
    id: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    model: Optional[str] = None
    role: Optional[str] = None
    system_prompt: str
    context: List[ContextSource] = Field(default_factory=list)
    starters: List[str] = Field(default_factory=list)
    tools: List[AgentTool] = Field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int = 4096
    tags: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("system_prompt")
    @classmethod
    def system_prompt_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("system_prompt must not be empty")
        return v
