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


class TestContextStore:
    def test_create_and_get(self):
        from api.services.context_store import ContextStore
        store = ContextStore()
        store.create("conv_1", "dolphin3:latest")
        ctx = store.get("conv_1")
        assert ctx is not None
        assert ctx.model == "dolphin3:latest"

    def test_get_nonexistent(self):
        from api.services.context_store import ContextStore
        store = ContextStore()
        assert store.get("nonexistent") is None

    def test_record_tool_call(self):
        from api.services.context_store import ContextStore
        from api.models.context_models import ToolCallRecord
        store = ContextStore()
        store.create("conv_2", "test-model")
        tc = ToolCallRecord(
            tool_name="echo__echo", arguments={"text": "hi"},
            result={"echo": "hi"}, iteration=1, duration_ms=100,
        )
        store.record_tool_call("conv_2", tc)
        ctx = store.get("conv_2")
        assert len(ctx.tool_calls) == 1
        assert ctx.tool_calls[0].tool_name == "echo__echo"

    def test_record_skill(self):
        from api.services.context_store import ContextStore
        store = ContextStore()
        store.create("conv_3", "test-model")
        store.record_skill("conv_3", "search-expert")
        ctx = store.get("conv_3")
        assert "search-expert" in ctx.skills_injected

    def test_update_activity(self):
        from api.services.context_store import ContextStore
        store = ContextStore()
        store.create("conv_4", "test-model")
        original = store.get("conv_4").last_activity
        import time; time.sleep(0.01)
        store.update_activity("conv_4")
        updated = store.get("conv_4")
        assert updated.message_count == 1
        assert updated.last_activity >= original

    def test_list_active(self):
        from api.services.context_store import ContextStore
        store = ContextStore()
        store.create("conv_a", "model-a")
        store.create("conv_b", "model-b")
        active = store.list_active()
        assert len(active) == 2
        ids = [c["conversation_id"] for c in active]
        assert "conv_a" in ids
        assert "conv_b" in ids

    def test_remove(self):
        from api.services.context_store import ContextStore
        store = ContextStore()
        store.create("conv_rm", "test-model")
        ctx = store.remove("conv_rm")
        assert ctx is not None
        assert store.get("conv_rm") is None


class TestSessionManager:
    def test_close_session_persists(self):
        import tempfile, shutil
        tmpdir = tempfile.mkdtemp()
        from api.services.context_store import ContextStore
        from api.services.memory_service import MemoryService
        from api.services.session_manager import SessionManager

        store = ContextStore()
        mem = MemoryService(data_dir=tmpdir)
        mgr = SessionManager(store, mem)

        store.create("conv_close", "test-model")
        store.update_activity("conv_close")

        result = mgr.close_session("conv_close", preview="Test close")
        assert result is not None
        assert result["id"] == "conv_close"
        assert store.get("conv_close") is None

        sessions = mem.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == "conv_close"

        shutil.rmtree(tmpdir)

    def test_close_nonexistent(self):
        from api.services.context_store import ContextStore
        from api.services.memory_service import MemoryService
        from api.services.session_manager import SessionManager
        import tempfile, shutil
        tmpdir = tempfile.mkdtemp()
        mgr = SessionManager(ContextStore(), MemoryService(data_dir=tmpdir))
        assert mgr.close_session("nonexistent") is None
        shutil.rmtree(tmpdir)
