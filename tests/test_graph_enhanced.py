"""Tests for enhanced graph service — agent nodes, workflow run nodes, search."""

import json
import os
import tempfile

import pytest
import yaml
from unittest.mock import patch

from api.services.graph_service import build_graph, search_nodes, GRAPH_CACHE


@pytest.fixture(autouse=True)
def _clean_graph_cache():
    """Remove graph cache before each test so build_graph always rebuilds."""
    if GRAPH_CACHE.exists():
        GRAPH_CACHE.unlink()
    yield
    if GRAPH_CACHE.exists():
        GRAPH_CACHE.unlink()


class TestAgentNodes:
    def test_agent_in_graph(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_data = {
            "id": "test",
            "name": "Test Agent",
            "description": "A test agent for unit tests",
            "icon": "flask",
            "model": "mistral",
            "system_prompt": "Test",
            "tags": ["security", "testing"],
        }
        with open(agents_dir / "test.yaml", "w") as f:
            yaml.dump(agent_data, f)

        with patch("api.services.graph_service.AGENTS_DIR", agents_dir):
            graph = build_graph(force=True)

        agent_nodes = [n for n in graph["nodes"] if n.get("type") == "agent"]
        assert len(agent_nodes) >= 1
        node = agent_nodes[0]
        assert node["id"] == "agent:test"
        assert node["name"] == "Test Agent"
        assert node["model"] == "mistral"
        assert "security" in node["tags"]

    def test_agent_links_to_existing_topic(self, tmp_path):
        """Agent tags matching existing topic nodes should create 'uses' links."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        exports_dir = tmp_path / "exports"
        exports_dir.mkdir()

        # Create a session file that will generate a "security" topic node
        # (needs 2+ occurrences or >8 chars to become a topic node)
        session_content = (
            "# Security Analysis\n\n"
            "Security is important. Security matters. Security everywhere.\n"
            "We discuss security in depth here.\n"
        )
        (exports_dir / "session1.md").write_text(session_content)
        (exports_dir / "session2.md").write_text(session_content)

        agent_data = {
            "id": "sec-agent",
            "name": "Security Agent",
            "system_prompt": "Secure things",
            "tags": ["security"],
        }
        with open(agents_dir / "sec-agent.yaml", "w") as f:
            yaml.dump(agent_data, f)

        with patch("api.services.graph_service.AGENTS_DIR", agents_dir), \
             patch("api.services.graph_service.EXPORTS_DIR", exports_dir):
            graph = build_graph(force=True)

        uses_links = [l for l in graph["links"] if l["type"] == "uses"]
        # If "security" became a topic node, the agent should link to it
        if any(n["id"] == "topic:security" for n in graph["nodes"]):
            assert len(uses_links) >= 1
            assert uses_links[0]["source"] == "agent:sec-agent"

    def test_no_agents_dir(self, tmp_path):
        """Graph builds fine when agents directory does not exist."""
        missing_dir = tmp_path / "no-agents"
        with patch("api.services.graph_service.AGENTS_DIR", missing_dir):
            graph = build_graph(force=True)
        agent_nodes = [n for n in graph["nodes"] if n.get("type") == "agent"]
        assert len(agent_nodes) == 0

    def test_malformed_agent_yaml(self, tmp_path):
        """Malformed YAML files are skipped gracefully."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "bad.yaml").write_text(":::not valid yaml[[[")

        with patch("api.services.graph_service.AGENTS_DIR", agents_dir):
            graph = build_graph(force=True)
        agent_nodes = [n for n in graph["nodes"] if n.get("type") == "agent"]
        assert len(agent_nodes) == 0


class TestWorkflowRunNodes:
    def test_workflow_run_in_graph(self, tmp_path):
        workflows_dir = tmp_path / "workflows"
        run_dir = workflows_dir / "abc12345-1234-1234-1234-123456789abc"
        run_dir.mkdir(parents=True)
        run_data = {
            "run_id": "abc12345-1234-1234-1234-123456789abc",
            "workflow_id": "test-workflow",
            "status": "completed",
            "context": {"seed": {}, "workspace": {}, "shared": {}, "metadata": {}},
            "step_results": [
                {
                    "step_id": "s1",
                    "status": "completed",
                    "duration_seconds": 1.5,
                    "token_count": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                }
            ],
            "started_at": "2026-04-08T01:00:00",
            "completed_at": "2026-04-08T01:00:02",
            "error": None,
        }
        (run_dir / "run.json").write_text(json.dumps(run_data))

        with patch("api.services.graph_service.WORKFLOWS_DIR", workflows_dir):
            graph = build_graph(force=True)

        run_nodes = [n for n in graph["nodes"] if n.get("type") == "workflow_run"]
        assert len(run_nodes) == 1
        node = run_nodes[0]
        assert node["id"] == "run:abc12345-123"
        assert node["name"] == "test-workflow"
        assert node["status"] == "completed"
        assert node["tokens"] == 150
        assert node["duration"] == 1.5

    def test_workflow_run_carries_full_ids(self, tmp_path):
        """U13: node id stays truncated (edges rely on it) but the node now
        carries the FULL run_id + workflow_id so the Context rail can pivot to
        the exact run."""
        workflows_dir = tmp_path / "workflows"
        full_run_id = "abc12345-1234-1234-1234-123456789abc"
        run_dir = workflows_dir / full_run_id
        run_dir.mkdir(parents=True)
        run_dir.joinpath("run.json").write_text(json.dumps({
            "run_id": full_run_id,
            "workflow_id": "xsiam-normalize",
            "status": "completed",
            "context": {"seed": {}, "workspace": {}, "shared": {}, "metadata": {}},
            "step_results": [],
            "started_at": "2026-07-08T00:00:00",
            "completed_at": "2026-07-08T00:00:01",
            "error": None,
        }))

        with patch("api.services.graph_service.WORKFLOWS_DIR", workflows_dir):
            graph = build_graph(force=True)

        node = next(n for n in graph["nodes"] if n.get("type") == "workflow_run")
        # Full ids present and untruncated…
        assert node["run_id"] == full_run_id
        assert node["workflow_id"] == "xsiam-normalize"
        # …while the node id (edge key) stays the truncated form.
        assert node["id"] == "run:abc12345-123"
        assert node["id"] != node["run_id"]

    def test_workflow_run_limit_20(self, tmp_path):
        """Only the 20 most recent runs should appear."""
        workflows_dir = tmp_path / "workflows"
        for i in range(25):
            run_id = f"run-{i:04d}-0000-0000-0000-000000000000"
            run_dir = workflows_dir / run_id
            run_dir.mkdir(parents=True)
            run_data = {
                "run_id": run_id,
                "workflow_id": "bulk-test",
                "status": "completed",
                "context": {"seed": {}, "workspace": {}, "shared": {}, "metadata": {}},
                "step_results": [],
                "started_at": f"2026-04-08T00:{i:02d}:00",
                "completed_at": f"2026-04-08T00:{i:02d}:01",
                "error": None,
            }
            (run_dir / "run.json").write_text(json.dumps(run_data))

        with patch("api.services.graph_service.WORKFLOWS_DIR", workflows_dir):
            graph = build_graph(force=True)

        run_nodes = [n for n in graph["nodes"] if n.get("type") == "workflow_run"]
        assert len(run_nodes) == 20

    def test_no_workflows_dir(self, tmp_path):
        """Graph builds fine when workflows directory does not exist."""
        missing_dir = tmp_path / "no-workflows"
        with patch("api.services.graph_service.WORKFLOWS_DIR", missing_dir):
            graph = build_graph(force=True)
        run_nodes = [n for n in graph["nodes"] if n.get("type") == "workflow_run"]
        assert len(run_nodes) == 0


class TestGraphMetadata:
    def test_graph_includes_new_counts(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        yaml.dump(
            {"id": "a1", "name": "Agent One", "system_prompt": "hi", "tags": []},
            open(agents_dir / "a1.yaml", "w"),
        )

        workflows_dir = tmp_path / "workflows"
        run_dir = workflows_dir / "run-0001"
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(json.dumps({
            "run_id": "run-0001",
            "workflow_id": "w1",
            "status": "completed",
            "context": {"seed": {}, "workspace": {}, "shared": {}, "metadata": {}},
            "step_results": [],
            "started_at": "2026-04-08T00:00:00",
            "completed_at": "2026-04-08T00:00:01",
            "error": None,
        }))

        with patch("api.services.graph_service.AGENTS_DIR", agents_dir), \
             patch("api.services.graph_service.WORKFLOWS_DIR", workflows_dir):
            graph = build_graph(force=True)

        assert graph["agent_count"] == 1
        assert graph["workflow_run_count"] == 1


class TestSearchNodes:
    def test_search_by_name(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        yaml.dump(
            {"id": "finder", "name": "Finder Agent", "system_prompt": "find", "tags": ["search"]},
            open(agents_dir / "finder.yaml", "w"),
        )
        with patch("api.services.graph_service.AGENTS_DIR", agents_dir):
            build_graph(force=True)

        results = search_nodes("Finder")
        assert isinstance(results, list)
        assert any(n.get("name") == "Finder Agent" for n in results)

    def test_search_by_tag(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        yaml.dump(
            {"id": "tagged", "name": "Tagged Agent", "system_prompt": "x", "tags": ["unicorn"]},
            open(agents_dir / "tagged.yaml", "w"),
        )
        with patch("api.services.graph_service.AGENTS_DIR", agents_dir):
            build_graph(force=True)

        results = search_nodes("unicorn")
        assert len(results) >= 1

    def test_search_empty_query(self):
        results = search_nodes("")
        assert results == []

    def test_search_no_match(self):
        build_graph(force=True)
        results = search_nodes("zzzznonexistent99999")
        assert results == []
