"""
A2A (Agent-to-Agent) Protocol Data Models — v0.2.x compatible

Implements the type surface from https://google.github.io/A2A/ specification:
AgentCard, Task, Message, Artifact, JSON-RPC envelopes, SSE event types,
and the A2A-specific JSON-RPC error codes.

This module is transport-agnostic; the router decides JSON-RPC over HTTP
vs SSE streaming.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


# ── Core enums ─────────────────────────────────────────────────────────────


class TaskState(str, Enum):
    """A2A task lifecycle states."""

    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    UNKNOWN = "unknown"


class MessageRole(str, Enum):
    USER = "user"
    AGENT = "agent"


# ── Parts (text / file / data) ─────────────────────────────────────────────


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str
    metadata: Optional[Dict[str, Any]] = None


class FilePart(BaseModel):
    type: Literal["file"] = "file"
    file: Dict[str, Any]  # {name, mimeType, bytes|uri}
    metadata: Optional[Dict[str, Any]] = None


class DataPart(BaseModel):
    type: Literal["data"] = "data"
    data: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None


Part = Union[TextPart, FilePart, DataPart]


# ── Message + Artifact ─────────────────────────────────────────────────────


class Message(BaseModel):
    role: MessageRole
    parts: List[Part] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None

    def text(self) -> str:
        """Concatenate text parts; non-text parts are ignored."""
        return "\n".join(p.text for p in self.parts if isinstance(p, TextPart))


class Artifact(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parts: List[Part] = Field(default_factory=list)
    index: int = 0
    append: Optional[bool] = None
    last_chunk: Optional[bool] = Field(default=None, alias="lastChunk")
    metadata: Optional[Dict[str, Any]] = None

    model_config = {"populate_by_name": True}


# ── Task ───────────────────────────────────────────────────────────────────


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStatus(BaseModel):
    state: TaskState
    message: Optional[Message] = None
    timestamp: str = Field(default_factory=_utcnow)


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    status: TaskStatus
    artifacts: List[Artifact] = Field(default_factory=list)
    history: List[Message] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None

    model_config = {"populate_by_name": True}


# ── Streaming events (sent over SSE) ───────────────────────────────────────


class TaskStatusUpdateEvent(BaseModel):
    id: str
    status: TaskStatus
    final: bool = False
    metadata: Optional[Dict[str, Any]] = None


class TaskArtifactUpdateEvent(BaseModel):
    id: str
    artifact: Artifact
    metadata: Optional[Dict[str, Any]] = None


# ── Agent Card (advertisement at /.well-known/agent.json) ──────────────────


class AgentProvider(BaseModel):
    organization: str
    url: Optional[str] = None


class AgentCapabilities(BaseModel):
    streaming: bool = False
    push_notifications: bool = Field(default=False, alias="pushNotifications")
    state_transition_history: bool = Field(default=False, alias="stateTransitionHistory")

    model_config = {"populate_by_name": True}


class AgentAuthentication(BaseModel):
    schemes: List[str] = Field(default_factory=list)  # e.g. ["bearer"]
    credentials: Optional[str] = None  # opaque hint, not the secret itself


class AgentSkill(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    input_modes: List[str] = Field(default_factory=lambda: ["text"], alias="inputModes")
    output_modes: List[str] = Field(default_factory=lambda: ["text"], alias="outputModes")

    model_config = {"populate_by_name": True}


class AgentCard(BaseModel):
    name: str
    description: Optional[str] = None
    url: str
    provider: Optional[AgentProvider] = None
    version: str
    documentation_url: Optional[str] = Field(default=None, alias="documentationUrl")
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    authentication: Optional[AgentAuthentication] = None
    default_input_modes: List[str] = Field(
        default_factory=lambda: ["text"], alias="defaultInputModes"
    )
    default_output_modes: List[str] = Field(
        default_factory=lambda: ["text"], alias="defaultOutputModes"
    )
    skills: List[AgentSkill] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


# ── JSON-RPC 2.0 envelope ──────────────────────────────────────────────────


class JsonRpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: Optional[Union[str, int]] = None
    method: str
    params: Optional[Dict[str, Any]] = None


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JsonRpcResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: Optional[Union[str, int]] = None
    result: Optional[Any] = None
    error: Optional[JsonRpcError] = None

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.result is None) == (self.error is None):
            raise ValueError("JsonRpcResponse must have exactly one of result/error")
        return self


# ── A2A method param types ─────────────────────────────────────────────────


class TaskSendParams(BaseModel):
    id: Optional[str] = None
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    message: Message
    accepted_output_modes: Optional[List[str]] = Field(
        default=None, alias="acceptedOutputModes"
    )
    metadata: Optional[Dict[str, Any]] = None

    model_config = {"populate_by_name": True}


class TaskQueryParams(BaseModel):
    id: str
    history_length: Optional[int] = Field(default=None, alias="historyLength")

    model_config = {"populate_by_name": True}


class TaskIdParams(BaseModel):
    id: str
    metadata: Optional[Dict[str, Any]] = None


# ── A2A JSON-RPC error codes ───────────────────────────────────────────────
# Standard JSON-RPC range: -32700..-32600
# A2A-specific range: -32001..-32099

class A2AErrorCode:
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    TASK_NOT_FOUND = -32001
    TASK_NOT_CANCELABLE = -32002
    PUSH_NOTIFICATION_NOT_SUPPORTED = -32003
    UNSUPPORTED_OPERATION = -32004
    CONTENT_TYPE_NOT_SUPPORTED = -32005


# ── Built-in skill IDs ─────────────────────────────────────────────────────


CHAT_SKILL_ID = "chat"
WORKFLOW_SKILL_PREFIX = "workflow:"


def workflow_skill_id(workflow_id: str) -> str:
    return f"{WORKFLOW_SKILL_PREFIX}{workflow_id}"


def parse_skill_id(skill_id: str) -> tuple[str, Optional[str]]:
    """
    Returns ("chat", None) or ("workflow", "<workflow_id>").
    Unknown skill IDs raise ValueError.
    """
    if skill_id == CHAT_SKILL_ID:
        return ("chat", None)
    if skill_id.startswith(WORKFLOW_SKILL_PREFIX):
        return ("workflow", skill_id[len(WORKFLOW_SKILL_PREFIX) :])
    raise ValueError(f"unknown A2A skill id: {skill_id!r}")
