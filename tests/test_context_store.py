#!/usr/bin/env python3
"""Tests for context tracking and conversation context models"""

import pytest
from datetime import datetime


class TestContextModels:
    def test_tool_call_record_creation(self):
        from api.models.context_models import ToolCallRecord
        tc = ToolCallRecord(
            tool_name="echo__echo",
            arguments={"text": "hello"},
            result={"echo": "hello"},
            iteration=1,
            duration_ms=150,
        )
        assert tc.tool_name == "echo__echo"
        assert tc.duration_ms == 150
        assert tc.timestamp is not None

    def test_conversation_context_creation(self):
        from api.models.context_models import ConversationContext
        ctx = ConversationContext(
            conversation_id="conv_test123",
            model="dolphin3:latest",
        )
        assert ctx.conversation_id == "conv_test123"
        assert ctx.message_count == 0
        assert ctx.tool_calls == []
        assert ctx.skills_injected == []
        assert ctx.started_at is not None

    def test_conversation_context_to_dict(self):
        from api.models.context_models import ConversationContext
        ctx = ConversationContext(
            conversation_id="conv_test456",
            model="qwen2.5:14b",
        )
        d = ctx.to_dict()
        assert d["conversation_id"] == "conv_test456"
        assert d["model"] == "qwen2.5:14b"
        assert isinstance(d["tool_calls"], list)

    def test_pinned_fact_creation(self):
        from api.models.context_models import PinnedFact
        fact = PinnedFact(
            content="User prefers dolphin3 for coding",
            tags=["preferences", "models"],
        )
        assert fact.content == "User prefers dolphin3 for coding"
        assert fact.id.startswith("fact_")
        assert fact.pinned_by == "user"

    def test_session_summary_from_context(self):
        from api.models.context_models import ConversationContext, SessionSummary, ToolCallRecord
        ctx = ConversationContext(
            conversation_id="conv_summ",
            model="dolphin3:latest",
        )
        ctx.message_count = 8
        ctx.tool_calls.append(ToolCallRecord(
            tool_name="web-search__web_search",
            arguments={"query": "test"},
            result={"results": []},
            iteration=1,
            duration_ms=500,
        ))
        ctx.skills_injected.append("search-expert")

        summary = SessionSummary.from_context(ctx, preview="Tell me about testing...")
        assert summary.id == "conv_summ"
        assert summary.message_count == 8
        assert summary.tool_calls_count == 1
        assert summary.tools_used == ["web-search__web_search"]
        assert summary.skills_triggered == ["search-expert"]
        assert summary.preview == "Tell me about testing..."
