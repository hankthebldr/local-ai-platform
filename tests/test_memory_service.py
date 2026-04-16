#!/usr/bin/env python3
"""Tests for memory persistence, facts, and search"""

import os
import pytest
import tempfile
import shutil
from pathlib import Path


@pytest.fixture
def memory_svc():
    tmpdir = tempfile.mkdtemp()
    from api.services.memory_service import MemoryService
    svc = MemoryService(data_dir=tmpdir)
    yield svc
    shutil.rmtree(tmpdir)


class TestSessionPersistence:
    def test_save_and_list_sessions(self, memory_svc):
        from api.models.context_models import ConversationContext, SessionSummary
        ctx = ConversationContext(conversation_id="conv_persist", model="dolphin3:latest")
        ctx.message_count = 5
        summary = SessionSummary.from_context(ctx, preview="Hello world test")
        memory_svc.save_session(summary)
        sessions = memory_svc.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == "conv_persist"
        assert sessions[0]["preview"] == "Hello world test"

    def test_get_session_detail(self, memory_svc):
        from api.models.context_models import ConversationContext, SessionSummary
        ctx = ConversationContext(conversation_id="conv_detail", model="test-model")
        summary = SessionSummary.from_context(ctx, preview="Detail test")
        memory_svc.save_session(summary)
        detail = memory_svc.get_session("conv_detail")
        assert detail is not None
        assert detail["id"] == "conv_detail"
        assert detail["model"] == "test-model"

    def test_delete_session(self, memory_svc):
        from api.models.context_models import ConversationContext, SessionSummary
        ctx = ConversationContext(conversation_id="conv_delete", model="test-model")
        summary = SessionSummary.from_context(ctx, preview="Delete me")
        memory_svc.save_session(summary)
        assert memory_svc.delete_session("conv_delete") is True
        assert memory_svc.get_session("conv_delete") is None
        assert len(memory_svc.list_sessions()) == 0

    def test_search_sessions(self, memory_svc):
        from api.models.context_models import ConversationContext, SessionSummary
        ctx1 = ConversationContext(conversation_id="conv_s1", model="test")
        s1 = SessionSummary.from_context(ctx1, preview="Quantum computing research")
        s1.topics = ["quantum", "physics"]
        memory_svc.save_session(s1)

        ctx2 = ConversationContext(conversation_id="conv_s2", model="test")
        s2 = SessionSummary.from_context(ctx2, preview="Python web scraping tutorial")
        s2.topics = ["python", "scraping"]
        memory_svc.save_session(s2)

        results = memory_svc.search_sessions("quantum")
        assert len(results) == 1
        assert results[0]["id"] == "conv_s1"

        results = memory_svc.search_sessions("python")
        assert len(results) == 1
        assert results[0]["id"] == "conv_s2"


class TestFacts:
    def test_add_and_list_facts(self, memory_svc):
        memory_svc.add_fact("User prefers dolphin3", tags=["preferences"])
        facts = memory_svc.list_facts()
        assert len(facts) == 1
        assert facts[0]["content"] == "User prefers dolphin3"
        assert facts[0]["tags"] == ["preferences"]

    def test_delete_fact(self, memory_svc):
        memory_svc.add_fact("Temporary fact", tags=[])
        facts = memory_svc.list_facts()
        fact_id = facts[0]["id"]
        assert memory_svc.delete_fact(fact_id) is True
        assert len(memory_svc.list_facts()) == 0

    def test_get_injection_context(self, memory_svc):
        memory_svc.add_fact("User prefers dolphin3 for coding", tags=["preferences"])
        memory_svc.add_fact("Project uses PostgreSQL", tags=["tech"])
        injection = memory_svc.get_injection_context()
        assert "dolphin3" in injection
        assert "PostgreSQL" in injection

    def test_get_injection_context_empty(self, memory_svc):
        injection = memory_svc.get_injection_context()
        assert injection == ""


class TestMemoryStats:
    def test_stats(self, memory_svc):
        from api.models.context_models import ConversationContext, SessionSummary, ToolCallRecord
        ctx = ConversationContext(conversation_id="conv_stats", model="test")
        ctx.tool_calls.append(ToolCallRecord(
            tool_name="echo__echo", arguments={}, result={},
            iteration=1, duration_ms=100,
        ))
        summary = SessionSummary.from_context(ctx, preview="Stats test")
        memory_svc.save_session(summary)
        memory_svc.add_fact("A fact", tags=[])
        stats = memory_svc.get_stats()
        assert stats["total_sessions"] == 1
        assert stats["total_facts"] == 1
        assert stats["total_tool_calls"] == 1
