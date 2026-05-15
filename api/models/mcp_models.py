"""
MCP (Model Context Protocol) Data Models

Pydantic v2 models for registering and managing local MCP servers that
expose tools / resources to workflows, agents, and the composer
workbench.

Two transports are supported:
  - "stdio": spawn a local process and exchange JSON-RPC over stdin/stdout
  - "http":  call a JSON-RPC endpoint over HTTP (or SSE for streaming)

Servers are persisted to data/config/mcp_servers.json so registrations
survive restarts. Sensitive env values stay on disk; the API never
returns env dicts in unmasked form.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

VALID_ID = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


def _validate_id(value: str) -> str:
    if not value or len(value) > 64:
        raise ValueError("id must be 1..64 chars")
    if not all(c in VALID_ID for c in value):
        raise ValueError("id may only contain alphanumerics, '_' and '-'")
    return value


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server registration."""

    id: str = Field(..., description="Stable identifier; used in workflow refs")
    name: str = Field(..., description="Human-readable label")
    description: Optional[str] = None
    transport: Literal["stdio", "http", "sse"] = "stdio"

    # stdio transport
    command: Optional[str] = Field(
        None, description="Executable to spawn (stdio transport)"
    )
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(
        default_factory=dict,
        description="Env vars passed to the spawned process. Treated as secret.",
    )
    cwd: Optional[str] = None

    # http/sse transport
    url: Optional[str] = Field(
        None, description="Base URL for the JSON-RPC endpoint (http/sse transport)"
    )
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="HTTP headers — Authorization etc. Treated as secret.",
    )

    # Lifecycle
    enabled: bool = True
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    tags: List[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _vid(cls, v: str) -> str:
        return _validate_id(v)

    def needs_command(self) -> bool:
        return self.transport == "stdio"

    def needs_url(self) -> bool:
        return self.transport in ("http", "sse")


class MCPServerCreate(BaseModel):
    """Payload for POST /api/mcp/servers."""

    id: str
    name: str
    description: Optional[str] = None
    transport: Literal["stdio", "http", "sse"] = "stdio"
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    cwd: Optional[str] = None
    url: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    timeout_seconds: int = 30
    tags: List[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _vid(cls, v: str) -> str:
        return _validate_id(v)


class MCPServerUpdate(BaseModel):
    """Partial update payload for PATCH /api/mcp/servers/{id}."""

    name: Optional[str] = None
    description: Optional[str] = None
    transport: Optional[Literal["stdio", "http", "sse"]] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    cwd: Optional[str] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    enabled: Optional[bool] = None
    timeout_seconds: Optional[int] = None
    tags: Optional[List[str]] = None


class MCPTool(BaseModel):
    """A tool advertised by an MCP server."""

    server_id: str
    name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any] = Field(default_factory=dict)


class MCPToolCall(BaseModel):
    """Payload for invoking an MCP tool."""

    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class MCPServerStatus(BaseModel):
    """Live status snapshot returned by /test."""

    server_id: str
    reachable: bool
    transport: str
    tools_count: int = 0
    error: Optional[str] = None
    last_checked: datetime = Field(default_factory=datetime.utcnow)
