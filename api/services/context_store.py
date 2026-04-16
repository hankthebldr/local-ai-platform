#!/usr/bin/env python3
"""
Context Store — In-memory per-conversation context tracking
"""

from __future__ import annotations

from ..logging_config import logger
from ..models.context_models import ConversationContext, ToolCallRecord, _now_iso


class ContextStore:
    def __init__(self):
        self._contexts = {}

    def create(self, conversation_id: str, model: str) -> ConversationContext:
        ctx = ConversationContext(conversation_id=conversation_id, model=model)
        self._contexts[conversation_id] = ctx
        logger.info(f"Context created: {conversation_id} (model={model})")
        return ctx

    def get(self, conversation_id: str):
        return self._contexts.get(conversation_id)

    def record_tool_call(self, conversation_id: str, tool_call: ToolCallRecord) -> None:
        ctx = self._contexts.get(conversation_id)
        if ctx:
            ctx.tool_calls.append(tool_call)
            ctx.last_activity = _now_iso()

    def record_skill(self, conversation_id: str, skill_id: str) -> None:
        ctx = self._contexts.get(conversation_id)
        if ctx and skill_id not in ctx.skills_injected:
            ctx.skills_injected.append(skill_id)

    def update_activity(self, conversation_id: str) -> None:
        ctx = self._contexts.get(conversation_id)
        if ctx:
            ctx.message_count += 1
            ctx.last_activity = _now_iso()

    def list_active(self) -> list:
        return [ctx.to_dict() for ctx in self._contexts.values()]

    def remove(self, conversation_id: str):
        return self._contexts.pop(conversation_id, None)
