"""Tests for agent data models — ContextSource, AgentTool, AgentDefinition"""

import pytest
from datetime import datetime
from pydantic import ValidationError

from api.models.agent_models import (
    AgentDefinition,
    AgentTool,
    ContextSource,
)


class TestContextSource:
    def test_file_type(self):
        ctx = ContextSource(type="file", value="/path/to/file.txt")
        assert ctx.type == "file"
        assert ctx.value == "/path/to/file.txt"
        assert ctx.label is None

    def test_file_with_label(self):
        ctx = ContextSource(type="file", value="/path/to/file.txt", label="My File")
        assert ctx.label == "My File"

    def test_graph_query(self):
        ctx = ContextSource(type="graph_query", value="MATCH (n) RETURN n LIMIT 10")
        assert ctx.type == "graph_query"
        assert ctx.value == "MATCH (n) RETURN n LIMIT 10"

    def test_text_type(self):
        ctx = ContextSource(type="text", value="Some inline context")
        assert ctx.type == "text"

    def test_url_type(self):
        ctx = ContextSource(type="url", value="https://example.com/docs")
        assert ctx.type == "url"

    def test_workflow_output_type(self):
        ctx = ContextSource(type="workflow_output", value="xsiam-data-model-rules")
        assert ctx.type == "workflow_output"

    def test_invalid_type(self):
        with pytest.raises(ValidationError):
            ContextSource(type="invalid_type", value="something")

    def test_missing_value(self):
        with pytest.raises(ValidationError):
            ContextSource(type="file")


class TestAgentTool:
    def test_web_search(self):
        tool = AgentTool(type="web_search")
        assert tool.type == "web_search"
        assert tool.config == {}

    def test_workflow_tool(self):
        tool = AgentTool(type="workflow", config={"workflow_id": "my-workflow"})
        assert tool.type == "workflow"
        assert tool.config["workflow_id"] == "my-workflow"

    def test_code_exec(self):
        tool = AgentTool(type="code_exec", config={"sandbox": True})
        assert tool.type == "code_exec"
        assert tool.config["sandbox"] is True

    def test_invalid_tool_type(self):
        with pytest.raises(ValidationError):
            AgentTool(type="invalid_tool")

    def test_default_config(self):
        tool = AgentTool(type="web_search")
        assert isinstance(tool.config, dict)
        assert len(tool.config) == 0


class TestAgentDefinition:
    def test_minimal(self):
        agent = AgentDefinition(
            id="test-agent",
            name="Test Agent",
            system_prompt="You are a helpful assistant.",
        )
        assert agent.id == "test-agent"
        assert agent.name == "Test Agent"
        assert agent.system_prompt == "You are a helpful assistant."
        assert agent.temperature == 0.7
        assert agent.max_tokens == 4096
        assert agent.context == []
        assert agent.starters == []
        assert agent.tools == []
        assert agent.tags == []
        assert agent.model is None
        assert agent.role is None

    def test_full(self):
        now = datetime.utcnow()
        agent = AgentDefinition(
            id="full-agent",
            name="Full Agent",
            description="A fully configured agent",
            icon="rocket",
            model="deepseek-r1:32b",
            role="reasoning",
            system_prompt="You are an expert analyst.",
            context=[
                ContextSource(type="file", value="/path/to/file.txt", label="My File"),
                ContextSource(type="text", value="Inline context"),
            ],
            starters=["Hello", "Help me analyze"],
            tools=[
                AgentTool(type="web_search"),
                AgentTool(type="workflow", config={"workflow_id": "test"}),
            ],
            temperature=0.4,
            max_tokens=8192,
            tags=["security", "xsiam"],
            created_at=now,
            updated_at=now,
        )
        assert agent.id == "full-agent"
        assert agent.description == "A fully configured agent"
        assert agent.icon == "rocket"
        assert agent.model == "deepseek-r1:32b"
        assert agent.role == "reasoning"
        assert len(agent.context) == 2
        assert len(agent.starters) == 2
        assert len(agent.tools) == 2
        assert agent.temperature == 0.4
        assert agent.max_tokens == 8192
        assert len(agent.tags) == 2
        assert agent.created_at == now
        assert agent.updated_at == now

    def test_empty_system_prompt_fails(self):
        with pytest.raises(ValidationError, match="system_prompt must not be empty"):
            AgentDefinition(
                id="bad-agent",
                name="Bad Agent",
                system_prompt="",
            )

    def test_whitespace_system_prompt_fails(self):
        with pytest.raises(ValidationError, match="system_prompt must not be empty"):
            AgentDefinition(
                id="bad-agent",
                name="Bad Agent",
                system_prompt="   \n  ",
            )

    def test_missing_id_fails(self):
        with pytest.raises(ValidationError):
            AgentDefinition(
                name="No ID Agent",
                system_prompt="You are helpful.",
            )

    def test_missing_name_fails(self):
        with pytest.raises(ValidationError):
            AgentDefinition(
                id="no-name",
                system_prompt="You are helpful.",
            )

    def test_serialization_roundtrip(self):
        agent = AgentDefinition(
            id="roundtrip",
            name="Roundtrip Agent",
            system_prompt="You are a test agent.",
            tags=["test"],
        )
        data = agent.model_dump(mode="json")
        restored = AgentDefinition(**data)
        assert restored.id == agent.id
        assert restored.name == agent.name
        assert restored.system_prompt == agent.system_prompt
        assert restored.tags == agent.tags
