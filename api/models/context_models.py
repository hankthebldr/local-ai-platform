#!/usr/bin/env python3
"""
Context Models — Data structures for conversation tracking and memory
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fact_id() -> str:
    return f"fact_{secrets.token_hex(6)}"


@dataclass
class ToolCallRecord:
    tool_name: str
    arguments: dict
    result: dict
    iteration: int
    duration_ms: int
    timestamp: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "result": self.result,
            "iteration": self.iteration,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
        }


@dataclass
class ConversationContext:
    conversation_id: str
    model: str
    started_at: str = field(default_factory=_now_iso)
    last_activity: str = field(default_factory=_now_iso)
    message_count: int = 0
    tool_calls: list = field(default_factory=list)
    skills_injected: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "model": self.model,
            "started_at": self.started_at,
            "last_activity": self.last_activity,
            "message_count": self.message_count,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "skills_injected": self.skills_injected,
            "metadata": self.metadata,
        }


@dataclass
class SessionSummary:
    id: str
    model: str
    started_at: str
    ended_at: str
    duration_minutes: int
    message_count: int
    tool_calls_count: int
    tools_used: list
    skills_triggered: list
    topics: list = field(default_factory=list)
    preview: str = ""
    tool_calls: list = field(default_factory=list)

    @classmethod
    def from_context(cls, ctx: ConversationContext, preview: str = "") -> SessionSummary:
        now = _now_iso()
        started = datetime.fromisoformat(ctx.started_at)
        ended = datetime.now(timezone.utc)
        duration = max(1, int((ended - started).total_seconds() / 60))
        tools_used = list(set(tc.tool_name for tc in ctx.tool_calls))
        return cls(
            id=ctx.conversation_id,
            model=ctx.model,
            started_at=ctx.started_at,
            ended_at=now,
            duration_minutes=duration,
            message_count=ctx.message_count,
            tool_calls_count=len(ctx.tool_calls),
            tools_used=tools_used,
            skills_triggered=list(set(ctx.skills_injected)),
            preview=preview[:200],
            tool_calls=[tc.to_dict() for tc in ctx.tool_calls],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "model": self.model,
            "started_at": self.started_at, "ended_at": self.ended_at,
            "duration_minutes": self.duration_minutes,
            "message_count": self.message_count,
            "tool_calls_count": self.tool_calls_count,
            "tools_used": self.tools_used,
            "skills_triggered": self.skills_triggered,
            "topics": self.topics, "preview": self.preview,
            "tool_calls": self.tool_calls,
        }

    def to_index_entry(self) -> dict:
        return {
            "id": self.id, "model": self.model,
            "started_at": self.started_at,
            "duration_minutes": self.duration_minutes,
            "message_count": self.message_count,
            "tool_calls_count": self.tool_calls_count,
            "preview": self.preview, "topics": self.topics,
        }


@dataclass
class PinnedFact:
    content: str
    tags: list = field(default_factory=list)
    id: str = field(default_factory=_fact_id)
    created_at: str = field(default_factory=_now_iso)
    source_conversation: str = None
    pinned_by: str = "user"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "content": self.content,
            "tags": self.tags, "created_at": self.created_at,
            "source_conversation": self.source_conversation,
            "pinned_by": self.pinned_by,
        }
