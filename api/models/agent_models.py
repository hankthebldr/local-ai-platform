"""
Agent System Data Models — Custom Agent / Gem Builder

Pydantic v2 models for:
- Agent definitions with system prompts, context sources, and tools
- YAML-backed persistence for portable agent configurations
- Context resolution from files, URLs, graph queries, and workflow outputs
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# ── Context Source ───────────────────────────────────────────────────────


class ContextSource(BaseModel):
    """A source of context injected into the agent's system prompt"""

    type: Literal["file", "url", "graph_query", "workflow_output", "text"]
    value: str
    label: Optional[str] = None


# ── Agent Tool ───────────────────────────────────────────────────────────


class AgentTool(BaseModel):
    """A tool the agent can invoke during a turn.

    Two shapes are accepted so YAML authors can use whichever feels natural:

      - Built-in tool: ``type: web_search | workflow | code_exec`` with an
        optional ``config`` dict.
      - Plugin tool reference: ``plugin_id: <plugin>`` and ``tool_id: <tool>``,
        pointing at any registered plugin tool (e.g. ``xdm-toolkit::analyse_xql``).

    Exactly one of the two shapes must be present.
    """

    type: Optional[Literal["web_search", "workflow", "code_exec"]] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    plugin_id: Optional[str] = None
    tool_id: Optional[str] = None
    # MCP-server tool reference: ``mcp_server: <server_id>`` with a ``tool_id``
    # ("*" = all tools the server exposes). Lets an agent be aligned to MCP
    # capabilities alongside built-ins and plugin tools.
    mcp_server: Optional[str] = None

    @model_validator(mode="after")
    def _one_shape(self) -> "AgentTool":
        has_builtin = self.type is not None
        has_plugin = bool(self.plugin_id) or (
            bool(self.tool_id) and not self.mcp_server
        )
        has_mcp = bool(self.mcp_server)
        if not (has_builtin or has_plugin or has_mcp):
            raise ValueError(
                "AgentTool requires one of: 'type' (built-in), "
                "'plugin_id'+'tool_id' (plugin tool), or 'mcp_server'+'tool_id' (MCP)."
            )
        if has_plugin and not (self.plugin_id and self.tool_id):
            raise ValueError(
                "plugin tool reference must include both 'plugin_id' and 'tool_id'."
            )
        if has_mcp and not self.tool_id:
            raise ValueError(
                "MCP tool reference must include 'tool_id' ('*' for all tools)."
            )
        return self


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
