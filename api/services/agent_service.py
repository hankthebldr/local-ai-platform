"""
Agent Service — CRUD and context resolution for custom agents

Manages YAML-backed agent definitions with:
- File-based persistence in agents/ directory
- Context resolution from multiple source types
- Message building with system prompt + resolved context
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ..logging_config import logger
from ..models.agent_models import AgentDefinition, ContextSource
from .workflow_engine import DATA_DIR as WORKFLOW_DATA_DIR

AGENTS_DIR = os.getenv("AGENTS_DIR", "./agents")

# Maximum characters to read from a file context source
FILE_CONTEXT_MAX_CHARS = 50_000

# Agent IDs become filenames; restrict to a safe charset and reject any
# path-separator / traversal attempts. Without this, an ID like
# "../../etc/foo" would write outside agents_dir.
_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _validate_agent_id(agent_id: str) -> None:
    if not isinstance(agent_id, str) or not _AGENT_ID_RE.match(agent_id):
        raise ValueError(
            f"invalid agent id {agent_id!r}: must match {_AGENT_ID_RE.pattern}"
        )


def _dump_agent_yaml_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Serialize an agent definition to YAML with a tmp+os.replace so a crash
    mid-write can never leave a half-written (unparseable) agent file on disk.
    os.replace is atomic within a filesystem; the tmp sits alongside the target
    so it shares one. Mirrors prompts.py::_write_atomic / workflows save (GP-2
    commit 4)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        yaml.dump(
            data, f, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
    os.replace(tmp, path)


class AgentService:
    """
    Service for managing custom agent definitions.

    Agents are stored as YAML files in the agents directory and can be
    loaded, created, updated, and deleted via this service. Context
    resolution handles multiple source types including files, URLs,
    graph queries, and workflow outputs.
    """

    def __init__(self, agents_dir: str = AGENTS_DIR):
        self.agents_dir = Path(agents_dir)
        self.agents_dir.mkdir(parents=True, exist_ok=True)

    # ── CRUD Operations ──────────────────────────────────────────────────

    def list_agents(self) -> List[Dict]:
        """Scan agents/*.yaml and return summary dicts"""
        results = []
        if not self.agents_dir.exists():
            return results

        for f in sorted(self.agents_dir.glob("*.yaml")):
            try:
                with open(f) as fh:
                    raw = yaml.safe_load(fh)
                if raw is None:
                    continue
                results.append(
                    {
                        "id": raw.get("id", f.stem),
                        "name": raw.get("name", f.stem),
                        "description": raw.get("description"),
                        "icon": raw.get("icon"),
                        "model": raw.get("model"),
                        "role": raw.get("role"),
                        "tags": raw.get("tags", []),
                        "file": str(f),
                        "starters": raw.get("starters", []),
                        "created_at": raw.get("created_at"),
                        "updated_at": raw.get("updated_at"),
                    }
                )
            except Exception as e:
                logger.warning(f"Skipping invalid agent {f}: {e}")

        return results

    def get_agent(self, agent_id: str) -> Optional[AgentDefinition]:
        """Load an agent definition from YAML by ID"""
        _validate_agent_id(agent_id)
        yaml_path = self.agents_dir / f"{agent_id}.yaml"
        if not yaml_path.exists():
            return None

        try:
            with open(yaml_path) as f:
                raw = yaml.safe_load(f)
            if raw is None:
                return None
            return AgentDefinition(**raw)
        except Exception as e:
            logger.error(f"Failed to load agent '{agent_id}': {e}")
            return None

    def create_agent(self, defn: AgentDefinition) -> str:
        """Write agent definition to YAML file, returns the file path"""
        _validate_agent_id(defn.id)
        for w in self._validate_tools(defn):
            logger.warning(f"agent '{defn.id}': {w}")
        now = datetime.utcnow()
        defn.created_at = now
        defn.updated_at = now

        yaml_path = self.agents_dir / f"{defn.id}.yaml"
        data = defn.model_dump(mode="json")

        _dump_agent_yaml_atomic(yaml_path, data)

        logger.info(f"Created agent '{defn.id}' at {yaml_path}")
        return str(yaml_path)

    def update_agent(self, agent_id: str, defn: AgentDefinition) -> bool:
        """Update an existing agent definition"""
        _validate_agent_id(agent_id)
        _validate_agent_id(defn.id)
        yaml_path = self.agents_dir / f"{agent_id}.yaml"
        if not yaml_path.exists():
            return False

        for w in self._validate_tools(defn):
            logger.warning(f"agent '{defn.id}': {w}")

        defn.updated_at = datetime.utcnow()

        # Preserve original created_at if not provided
        if defn.created_at is None:
            existing = self.get_agent(agent_id)
            if existing and existing.created_at:
                defn.created_at = existing.created_at

        data = defn.model_dump(mode="json")

        _dump_agent_yaml_atomic(yaml_path, data)

        logger.info(f"Updated agent '{agent_id}'")
        return True

    def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent definition by ID"""
        _validate_agent_id(agent_id)
        yaml_path = self.agents_dir / f"{agent_id}.yaml"
        if not yaml_path.exists():
            return False

        yaml_path.unlink()
        logger.info(f"Deleted agent '{agent_id}'")
        return True

    # ── Tool reachability validation ─────────────────────────────────────

    def _validate_tools(self, defn: AgentDefinition) -> List[str]:
        """Verify each declared plugin/MCP tool actually resolves.

        Reuses the workflow extension-preflight helpers so agents and
        workflow steps validate their tool surface identically. Raises
        ``ValueError`` on definite-missing refs (plugin absent, plugin
        tool not found, MCP server not registered). Returns a list of
        non-fatal warnings (e.g. a registered-but-unreachable MCP server,
        where we can't refute the tool's existence) for the caller to
        surface. Built-in tools (``type``) need no registry lookup.
        """
        from .extension_preflight import (
            _default_mcp_service,
            _default_plugin_service,
            _mcp_has_tool,
            _mcp_reachable,
            _mcp_registered,
            _plugin_has_tool,
            _plugin_present,
        )

        plugin_service = _default_plugin_service()
        mcp_service = _default_mcp_service()
        errors: List[str] = []
        warnings: List[str] = []

        for tool in defn.tools:
            if tool.type is not None:
                continue  # built-in; nothing to resolve
            if tool.plugin_id:
                if not _plugin_present(plugin_service, tool.plugin_id):
                    errors.append(f"plugin not installed: {tool.plugin_id}")
                elif tool.tool_id and not _plugin_has_tool(
                    plugin_service, tool.plugin_id, tool.tool_id
                ):
                    errors.append(
                        f"plugin '{tool.plugin_id}' has no tool '{tool.tool_id}'"
                    )
            elif tool.mcp_server:
                if not _mcp_registered(mcp_service, tool.mcp_server):
                    errors.append(f"MCP server not registered: {tool.mcp_server}")
                elif not _mcp_reachable(mcp_service, tool.mcp_server):
                    warnings.append(
                        f"MCP server '{tool.mcp_server}' is registered but "
                        f"unreachable; tool '{tool.tool_id}' cannot be verified"
                    )
                elif (
                    tool.tool_id
                    and tool.tool_id != "*"
                    and not _mcp_has_tool(mcp_service, tool.mcp_server, tool.tool_id)
                ):
                    errors.append(
                        f"MCP server '{tool.mcp_server}' exposes no tool "
                        f"'{tool.tool_id}'"
                    )

        if errors:
            raise ValueError("agent tool validation failed: " + "; ".join(errors))
        return warnings

    # ── Context Resolution ───────────────────────────────────────────────

    def resolve_context(self, agent: AgentDefinition) -> List[Dict]:
        """
        Resolve each ContextSource to its actual content.

        Returns a list of dicts with keys: type, label, content
        """
        resolved = []

        for ctx in agent.context:
            entry = {
                "type": ctx.type,
                "label": ctx.label or ctx.value,
                "content": self._resolve_single_context(ctx),
            }
            resolved.append(entry)

        return resolved

    def _resolve_single_context(self, ctx: ContextSource) -> str:
        """Resolve a single context source to its string content"""
        if ctx.type == "text":
            return ctx.value

        elif ctx.type == "file":
            return self._resolve_file_context(ctx.value)

        elif ctx.type == "url":
            return f"[URL context: {ctx.value}]"

        elif ctx.type == "graph_query":
            return f"[Graph query: {ctx.value}]"

        elif ctx.type == "workflow_output":
            return self._resolve_workflow_output(ctx.value)

        else:
            return f"[Unknown context type: {ctx.type}]"

    def _resolve_file_context(self, file_path: str) -> str:
        """Read file content, truncated to FILE_CONTEXT_MAX_CHARS"""
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"Context file not found: {file_path}")
            return f"[File not found: {file_path}]"

        try:
            content = path.read_text(encoding="utf-8")
            if len(content) > FILE_CONTEXT_MAX_CHARS:
                content = (
                    content[:FILE_CONTEXT_MAX_CHARS]
                    + "\n\n... [truncated at 50k chars]"
                )
            return content
        except Exception as e:
            logger.error(f"Failed to read context file '{file_path}': {e}")
            return f"[Error reading file: {file_path}: {e}]"

    def _resolve_workflow_output(self, workflow_id: str) -> str:
        """Load latest completed run's workspace for a given workflow_id"""
        data_path = Path(WORKFLOW_DATA_DIR)
        if not data_path.exists():
            return f"[No workflow data found for: {workflow_id}]"

        # Scan run directories (newest first) for matching workflow_id
        latest_workspace = None
        for run_dir in sorted(data_path.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            run_file = run_dir / "run.json"
            if not run_file.exists():
                continue
            try:
                with open(run_file) as f:
                    run_data = json.load(f)
                if (
                    run_data.get("workflow_id") == workflow_id
                    and run_data.get("status") == "completed"
                ):
                    latest_workspace = run_data.get("context", {}).get("workspace", {})
                    break
            except Exception:
                continue

        if latest_workspace is None:
            return f"[No completed runs found for workflow: {workflow_id}]"

        # Return workspace as formatted JSON
        try:
            return json.dumps(latest_workspace, indent=2, default=str)
        except Exception:
            return str(latest_workspace)

    # ── Message Building ─────────────────────────────────────────────────

    def build_messages(
        self,
        agent: AgentDefinition,
        user_messages: List[Dict],
    ) -> List[Dict]:
        """
        Build the full message list for an LLM call.

        Structure:
        1. System message with the agent's system prompt
        2. (Optional) Second system message with resolved context
        3. User conversation messages
        """
        messages: List[Dict[str, Any]] = []

        # Primary system prompt
        messages.append(
            {
                "role": "system",
                "content": agent.system_prompt,
            }
        )

        # Resolved context as second system message
        resolved = self.resolve_context(agent)
        if resolved:
            context_parts = []
            for entry in resolved:
                label = entry["label"]
                content = entry["content"]
                context_parts.append(f"### {label}\n\n{content}")

            context_message = (
                "The following context has been loaded for this conversation:\n\n"
                + "\n\n---\n\n".join(context_parts)
            )
            messages.append(
                {
                    "role": "system",
                    "content": context_message,
                }
            )

        # User conversation messages
        messages.extend(user_messages)

        return messages
