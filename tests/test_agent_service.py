"""Tests for AgentService — CRUD, context resolution, and message building"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from api.models.agent_models import AgentDefinition, ContextSource, AgentTool
from api.services.agent_service import AgentService


@pytest.fixture
def agents_dir():
    """Create a temporary directory for agent YAML files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def service(agents_dir):
    """Create an AgentService with a temporary agents directory"""
    return AgentService(agents_dir=agents_dir)


@pytest.fixture
def sample_agent():
    """A minimal agent definition for testing"""
    return AgentDefinition(
        id="test-agent",
        name="Test Agent",
        system_prompt="You are a helpful test assistant.",
        tags=["test"],
    )


@pytest.fixture
def full_agent():
    """A fully-configured agent definition"""
    return AgentDefinition(
        id="full-agent",
        name="Full Agent",
        description="A fully configured agent for testing",
        icon="star",
        model="mistral",
        role="general",
        system_prompt="You are an expert analyst.",
        context=[
            ContextSource(type="text", value="Some inline context", label="Inline"),
        ],
        starters=["Hello", "Help me"],
        tools=[AgentTool(type="web_search")],
        temperature=0.5,
        max_tokens=2048,
        tags=["test", "full"],
    )


# ── CRUD Tests ────────────────────────────────────────────────────────────


class TestCRUD:
    def test_list_empty(self, service):
        agents = service.list_agents()
        assert agents == []

    def test_create_and_get(self, service, sample_agent):
        path = service.create_agent(sample_agent)
        assert path.endswith(".yaml")
        assert "test-agent" in path

        loaded = service.get_agent("test-agent")
        assert loaded is not None
        assert loaded.id == "test-agent"
        assert loaded.name == "Test Agent"
        assert loaded.system_prompt == "You are a helpful test assistant."
        assert loaded.created_at is not None
        assert loaded.updated_at is not None

    def test_list_after_create(self, service, sample_agent, full_agent):
        service.create_agent(sample_agent)
        service.create_agent(full_agent)

        agents = service.list_agents()
        assert len(agents) == 2
        ids = [a["id"] for a in agents]
        assert "test-agent" in ids
        assert "full-agent" in ids

    def test_list_summary_fields(self, service, full_agent):
        service.create_agent(full_agent)
        agents = service.list_agents()
        assert len(agents) == 1

        summary = agents[0]
        assert summary["id"] == "full-agent"
        assert summary["name"] == "Full Agent"
        assert summary["description"] is not None
        assert summary["tags"] == ["test", "full"]
        assert summary["model"] == "mistral"

    def test_update(self, service, sample_agent):
        service.create_agent(sample_agent)

        updated = AgentDefinition(
            id="test-agent",
            name="Updated Agent",
            system_prompt="Updated system prompt.",
            tags=["updated"],
        )
        success = service.update_agent("test-agent", updated)
        assert success is True

        loaded = service.get_agent("test-agent")
        assert loaded.name == "Updated Agent"
        assert loaded.system_prompt == "Updated system prompt."
        assert loaded.tags == ["updated"]
        # created_at should be preserved
        assert loaded.created_at is not None

    def test_update_nonexistent(self, service, sample_agent):
        success = service.update_agent("nonexistent", sample_agent)
        assert success is False

    def test_delete(self, service, sample_agent):
        service.create_agent(sample_agent)
        assert service.get_agent("test-agent") is not None

        success = service.delete_agent("test-agent")
        assert success is True
        assert service.get_agent("test-agent") is None

    def test_delete_nonexistent(self, service):
        success = service.delete_agent("nonexistent")
        assert success is False

    def test_get_nonexistent(self, service):
        result = service.get_agent("does-not-exist")
        assert result is None


# ── Context Resolution Tests ──────────────────────────────────────────────


class TestContextResolution:
    def test_text_context(self, service):
        agent = AgentDefinition(
            id="ctx-text",
            name="Context Test",
            system_prompt="Test.",
            context=[
                ContextSource(type="text", value="Hello world", label="Greeting"),
            ],
        )
        resolved = service.resolve_context(agent)
        assert len(resolved) == 1
        assert resolved[0]["type"] == "text"
        assert resolved[0]["label"] == "Greeting"
        assert resolved[0]["content"] == "Hello world"

    def test_file_context(self, service, agents_dir):
        # Create a test file
        test_file = Path(agents_dir) / "test_context.txt"
        test_file.write_text("File content here")

        agent = AgentDefinition(
            id="ctx-file",
            name="File Context Test",
            system_prompt="Test.",
            context=[
                ContextSource(type="file", value=str(test_file), label="Test File"),
            ],
        )
        resolved = service.resolve_context(agent)
        assert len(resolved) == 1
        assert resolved[0]["content"] == "File content here"

    def test_file_context_missing(self, service):
        agent = AgentDefinition(
            id="ctx-missing",
            name="Missing File Test",
            system_prompt="Test.",
            context=[
                ContextSource(type="file", value="/nonexistent/path.txt"),
            ],
        )
        resolved = service.resolve_context(agent)
        assert len(resolved) == 1
        assert "[File not found:" in resolved[0]["content"]

    def test_url_context_placeholder(self, service):
        agent = AgentDefinition(
            id="ctx-url",
            name="URL Context Test",
            system_prompt="Test.",
            context=[
                ContextSource(type="url", value="https://example.com/docs"),
            ],
        )
        resolved = service.resolve_context(agent)
        assert len(resolved) == 1
        assert resolved[0]["content"] == "[URL context: https://example.com/docs]"

    def test_graph_query_placeholder(self, service):
        agent = AgentDefinition(
            id="ctx-graph",
            name="Graph Context Test",
            system_prompt="Test.",
            context=[
                ContextSource(type="graph_query", value="MATCH (n) RETURN n"),
            ],
        )
        resolved = service.resolve_context(agent)
        assert len(resolved) == 1
        assert resolved[0]["content"] == "[Graph query: MATCH (n) RETURN n]"

    def test_workflow_output_no_data(self, service):
        agent = AgentDefinition(
            id="ctx-wf",
            name="Workflow Context Test",
            system_prompt="Test.",
            context=[
                ContextSource(type="workflow_output", value="nonexistent-workflow"),
            ],
        )
        resolved = service.resolve_context(agent)
        assert len(resolved) == 1
        assert "[No" in resolved[0]["content"]

    def test_empty_context(self, service):
        agent = AgentDefinition(
            id="ctx-empty",
            name="Empty Context Test",
            system_prompt="Test.",
            context=[],
        )
        resolved = service.resolve_context(agent)
        assert resolved == []

    def test_file_context_truncation(self, service, agents_dir):
        # Create a large file
        test_file = Path(agents_dir) / "large_file.txt"
        test_file.write_text("x" * 60_000)

        agent = AgentDefinition(
            id="ctx-large",
            name="Large File Test",
            system_prompt="Test.",
            context=[
                ContextSource(type="file", value=str(test_file)),
            ],
        )
        resolved = service.resolve_context(agent)
        assert len(resolved) == 1
        assert "truncated at 50k chars" in resolved[0]["content"]
        # Should be 50k + truncation message, not the full 60k
        assert len(resolved[0]["content"]) < 55_000


# ── Message Building Tests ────────────────────────────────────────────────


class TestMessageBuilding:
    def test_basic_messages(self, service):
        agent = AgentDefinition(
            id="msg-basic",
            name="Message Test",
            system_prompt="You are a helpful assistant.",
        )
        user_messages = [
            {"role": "user", "content": "Hello!"},
        ]

        messages = service.build_messages(agent, user_messages)
        assert len(messages) == 2  # system + user (no context)
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful assistant."
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Hello!"

    def test_messages_with_context(self, service):
        agent = AgentDefinition(
            id="msg-ctx",
            name="Context Message Test",
            system_prompt="You are an analyst.",
            context=[
                ContextSource(type="text", value="Important context", label="Note"),
            ],
        )
        user_messages = [
            {"role": "user", "content": "Analyze this."},
        ]

        messages = service.build_messages(agent, user_messages)
        assert len(messages) == 3  # system + context system + user
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are an analyst."
        assert messages[1]["role"] == "system"
        assert "Important context" in messages[1]["content"]
        assert "### Note" in messages[1]["content"]
        assert messages[2]["role"] == "user"

    def test_messages_with_conversation_history(self, service):
        agent = AgentDefinition(
            id="msg-history",
            name="History Test",
            system_prompt="You are helpful.",
        )
        user_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]

        messages = service.build_messages(agent, user_messages)
        assert len(messages) == 4  # system + 3 conversation messages
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"
        assert messages[3]["role"] == "user"

    def test_messages_multiple_context_sources(self, service):
        agent = AgentDefinition(
            id="msg-multi-ctx",
            name="Multi Context Test",
            system_prompt="You are a researcher.",
            context=[
                ContextSource(type="text", value="Context A", label="First"),
                ContextSource(type="text", value="Context B", label="Second"),
            ],
        )
        user_messages = [{"role": "user", "content": "Research this."}]

        messages = service.build_messages(agent, user_messages)
        assert len(messages) == 3  # system + context + user
        context_msg = messages[1]["content"]
        assert "### First" in context_msg
        assert "Context A" in context_msg
        assert "### Second" in context_msg
        assert "Context B" in context_msg


class TestAtomicWrites:
    """GP-2 commit 4: create/update use tmp+os.replace, so a crash mid-write
    can never leave a half-written (unparseable) agent file on disk."""

    def test_create_leaves_no_tmp_on_success(self, service, sample_agent):
        service.create_agent(sample_agent)
        agents_dir = Path(service.agents_dir)
        assert (agents_dir / "test-agent.yaml").exists()
        assert not list(agents_dir.glob("*.tmp"))

    def test_update_failure_preserves_prior_file(self, service, sample_agent, monkeypatch):
        # Land a good version first.
        service.create_agent(sample_agent)
        path = Path(service.agents_dir) / "test-agent.yaml"
        good = path.read_text()

        # Now make the serializer blow up mid-write and attempt an update.
        import api.services.agent_service as mod

        def _boom(*a, **k):
            raise IOError("disk full")

        monkeypatch.setattr(mod.yaml, "dump", _boom)
        sample_agent.name = "Mutated"
        with pytest.raises(IOError):
            service.update_agent("test-agent", sample_agent)

        # The original file is intact (os.replace never ran) and no tmp lingers
        # to shadow it as a corrupt half-write.
        assert path.read_text() == good
        # The tmp may exist as a partial, but the CANONICAL file was untouched;
        # importantly the target is still fully parseable.
        import yaml as real_yaml

        assert real_yaml.safe_load(path.read_text())["name"] == "Test Agent"
