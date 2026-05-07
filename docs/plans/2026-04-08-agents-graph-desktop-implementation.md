# Agents, Context Graph & Desktop App Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a custom agent/gem builder (YAML-backed), enhanced context graph with agent/workflow nodes, and macOS desktop app packaging.

**Architecture:** Agents are YAML files in `agents/` — the UI creates/edits YAML via REST API. Agent chat injects system prompt + resolved context (files, graph queries, workflow outputs) into LLM messages. The context graph is extended with agent and workflow run nodes. The desktop app wraps the existing FastAPI dashboard in a native WKWebView window via pywebview.

**Tech Stack:** Python 3.9+, FastAPI, Pydantic v2, PyYAML, pywebview, py2app, D3.js v7

---

## Phase 1: Agent System (Backend)

### Task 1: Agent Data Models

**Files:**
- Create: `api/models/agent_models.py`
- Test: `tests/test_agent_models.py`

**Step 1: Write failing tests**

```python
# tests/test_agent_models.py
"""Tests for agent data models"""
import pytest
from api.models.agent_models import (
    AgentDefinition, ContextSource, AgentTool,
)


class TestContextSource:
    def test_file_source(self):
        src = ContextSource(type="file", value="workflows/xsiam.yaml", label="XSIAM")
        assert src.type == "file"
        assert src.label == "XSIAM"

    def test_graph_query_source(self):
        src = ContextSource(type="graph_query", value="xsiam OR xdr")
        assert src.type == "graph_query"

    def test_invalid_type_fails(self):
        with pytest.raises(ValueError):
            ContextSource(type="invalid", value="x")


class TestAgentTool:
    def test_web_search_tool(self):
        tool = AgentTool(type="web_search")
        assert tool.config == {}

    def test_workflow_tool(self):
        tool = AgentTool(type="workflow", config={"workflow_id": "xsiam-data-model-rules"})
        assert tool.config["workflow_id"] == "xsiam-data-model-rules"


class TestAgentDefinition:
    def test_minimal(self):
        agent = AgentDefinition(id="test", name="Test", system_prompt="You are a test agent.")
        assert agent.id == "test"
        assert agent.context == []
        assert agent.starters == []

    def test_full(self):
        agent = AgentDefinition(
            id="xsiam", name="XSIAM Analyst", icon="shield",
            model="deepseek-r1:32b",
            system_prompt="You are an XSIAM specialist.",
            context=[ContextSource(type="file", value="x.yaml")],
            starters=["Analyze logs"],
            tools=[AgentTool(type="web_search")],
            tags=["security"],
        )
        assert len(agent.context) == 1
        assert len(agent.tools) == 1

    def test_empty_system_prompt_fails(self):
        with pytest.raises(ValueError):
            AgentDefinition(id="x", name="X", system_prompt="   ")
```

**Step 2: Run tests, verify failure**

```bash
pytest tests/test_agent_models.py -v
# Expected: ModuleNotFoundError
```

**Step 3: Implement models**

```python
# api/models/agent_models.py
"""Agent/Gem Data Models — YAML-backed reusable agent personas"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ContextSource(BaseModel):
    """A context source pinned to an agent"""
    type: Literal["file", "url", "graph_query", "workflow_output", "text"]
    value: str
    label: Optional[str] = None


class AgentTool(BaseModel):
    """A tool/capability enabled for an agent"""
    type: Literal["web_search", "workflow", "code_exec"]
    config: Dict[str, Any] = Field(default_factory=dict)


class AgentDefinition(BaseModel):
    """Complete agent persona definition — serialized to/from YAML"""
    id: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    model: Optional[str] = None
    role: Optional[str] = None
    system_prompt: str
    context: List[ContextSource] = Field(default_factory=list)
    starters: List[str] = Field(default_factory=list)
    tools: List[AgentTool] = Field(default_factory=list)
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("system_prompt")
    @classmethod
    def system_prompt_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("system_prompt must not be empty")
        return v
```

**Step 4: Run tests, verify pass**

```bash
pytest tests/test_agent_models.py -v
# Expected: all PASS
```

**Step 5: Commit**

```bash
git add api/models/agent_models.py tests/test_agent_models.py
git commit -m "feat: add agent data models (ContextSource, AgentTool, AgentDefinition)"
```

---

### Task 2: Agent Service (CRUD + Context Resolution)

**Files:**
- Create: `api/services/agent_service.py`
- Test: `tests/test_agent_service.py`

**Step 1: Write failing tests**

```python
# tests/test_agent_service.py
"""Tests for AgentService — CRUD and context resolution"""
import os
import tempfile
import pytest
from api.services.agent_service import AgentService
from api.models.agent_models import AgentDefinition, ContextSource


@pytest.fixture
def agents_dir():
    d = tempfile.mkdtemp()
    yield d


@pytest.fixture
def service(agents_dir):
    return AgentService(agents_dir=agents_dir)


class TestAgentCRUD:
    def test_list_empty(self, service):
        assert service.list_agents() == []

    def test_create_and_get(self, service):
        defn = AgentDefinition(id="test", name="Test", system_prompt="You are test.")
        path = service.create_agent(defn)
        assert path.endswith(".yaml")
        loaded = service.get_agent("test")
        assert loaded.name == "Test"

    def test_list_after_create(self, service):
        service.create_agent(AgentDefinition(id="a", name="A", system_prompt="A"))
        service.create_agent(AgentDefinition(id="b", name="B", system_prompt="B"))
        agents = service.list_agents()
        assert len(agents) == 2

    def test_update(self, service):
        service.create_agent(AgentDefinition(id="x", name="Old", system_prompt="V1"))
        service.update_agent("x", AgentDefinition(id="x", name="New", system_prompt="V2"))
        updated = service.get_agent("x")
        assert updated.name == "New"
        assert updated.system_prompt == "V2"

    def test_delete(self, service):
        service.create_agent(AgentDefinition(id="d", name="D", system_prompt="D"))
        assert service.delete_agent("d") is True
        assert service.get_agent("d") is None

    def test_get_nonexistent(self, service):
        assert service.get_agent("nope") is None

    def test_delete_nonexistent(self, service):
        assert service.delete_agent("nope") is False


class TestContextResolution:
    def test_resolve_text_context(self, service):
        agent = AgentDefinition(
            id="t", name="T", system_prompt="T",
            context=[ContextSource(type="text", value="Inline context data")],
        )
        resolved = service.resolve_context(agent)
        assert len(resolved) == 1
        assert resolved[0]["content"] == "Inline context data"

    def test_resolve_file_context(self, service, agents_dir):
        # Create a file to reference
        test_file = os.path.join(agents_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("File content here")
        agent = AgentDefinition(
            id="f", name="F", system_prompt="F",
            context=[ContextSource(type="file", value=test_file)],
        )
        resolved = service.resolve_context(agent)
        assert resolved[0]["content"] == "File content here"

    def test_resolve_missing_file(self, service):
        agent = AgentDefinition(
            id="m", name="M", system_prompt="M",
            context=[ContextSource(type="file", value="/nonexistent/path.txt")],
        )
        resolved = service.resolve_context(agent)
        assert "not found" in resolved[0]["content"].lower() or resolved[0]["error"]


class TestMessageBuilding:
    def test_build_messages_basic(self, service):
        agent = AgentDefinition(id="b", name="B", system_prompt="You are helpful.")
        user_msgs = [{"role": "user", "content": "Hello"}]
        messages = service.build_messages(agent, user_msgs)
        assert messages[0]["role"] == "system"
        assert "helpful" in messages[0]["content"]
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Hello"

    def test_build_messages_with_context(self, service):
        agent = AgentDefinition(
            id="c", name="C", system_prompt="Expert.",
            context=[ContextSource(type="text", value="Key fact: X=42")],
        )
        messages = service.build_messages(agent, [{"role": "user", "content": "What is X?"}])
        # Context should appear between system and user messages
        full_text = " ".join(m["content"] for m in messages)
        assert "X=42" in full_text
```

**Step 2: Run tests, verify failure**

```bash
pytest tests/test_agent_service.py -v
# Expected: ModuleNotFoundError
```

**Step 3: Implement service**

```python
# api/services/agent_service.py
"""Agent Service — CRUD for YAML-backed agent personas with context resolution"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ..logging_config import logger
from ..models.agent_models import AgentDefinition, ContextSource

AGENTS_DIR = os.getenv("AGENTS_DIR", "./agents")


class AgentService:
    """Manages agent personas as YAML files on disk"""

    def __init__(self, agents_dir: str = AGENTS_DIR):
        self.agents_dir = Path(agents_dir)
        self.agents_dir.mkdir(parents=True, exist_ok=True)

    def list_agents(self) -> List[Dict[str, Any]]:
        results = []
        for f in sorted(self.agents_dir.glob("*.yaml")):
            try:
                agent = self._load_yaml(f)
                results.append({
                    "id": agent.id,
                    "name": agent.name,
                    "description": agent.description,
                    "icon": agent.icon,
                    "model": agent.model,
                    "role": agent.role,
                    "tags": agent.tags,
                    "starters": agent.starters,
                    "context_count": len(agent.context),
                    "tool_count": len(agent.tools),
                })
            except Exception as e:
                logger.warning(f"Skipping invalid agent {f}: {e}")
        return results

    def get_agent(self, agent_id: str) -> Optional[AgentDefinition]:
        path = self.agents_dir / f"{agent_id}.yaml"
        if not path.exists():
            return None
        return self._load_yaml(path)

    def create_agent(self, defn: AgentDefinition) -> str:
        defn.created_at = defn.created_at or datetime.utcnow()
        defn.updated_at = datetime.utcnow()
        path = self.agents_dir / f"{defn.id}.yaml"
        self._save_yaml(path, defn)
        logger.info(f"Created agent '{defn.id}' at {path}")
        return str(path)

    def update_agent(self, agent_id: str, defn: AgentDefinition) -> bool:
        path = self.agents_dir / f"{agent_id}.yaml"
        if not path.exists():
            return False
        defn.updated_at = datetime.utcnow()
        self._save_yaml(path, defn)
        logger.info(f"Updated agent '{agent_id}'")
        return True

    def delete_agent(self, agent_id: str) -> bool:
        path = self.agents_dir / f"{agent_id}.yaml"
        if not path.exists():
            return False
        path.unlink()
        logger.info(f"Deleted agent '{agent_id}'")
        return True

    # ── Context Resolution ────────────────────────────────────────────────

    def resolve_context(self, agent: AgentDefinition) -> List[Dict[str, Any]]:
        resolved = []
        for src in agent.context:
            try:
                content = self._resolve_source(src)
                resolved.append({
                    "type": src.type,
                    "label": src.label or src.value,
                    "content": content,
                })
            except Exception as e:
                resolved.append({
                    "type": src.type,
                    "label": src.label or src.value,
                    "content": f"Error resolving context: {e}",
                    "error": True,
                })
        return resolved

    def _resolve_source(self, src: ContextSource) -> str:
        if src.type == "text":
            return src.value
        elif src.type == "file":
            path = Path(src.value)
            if not path.exists():
                return f"File not found: {src.value}"
            return path.read_text(errors="replace")[:50000]
        elif src.type == "url":
            return f"[URL context: {src.value}]"  # TODO: fetch with caching
        elif src.type == "graph_query":
            return f"[Graph query: {src.value}]"  # TODO: integrate with graph_service
        elif src.type == "workflow_output":
            return self._resolve_workflow_output(src.value)
        return f"Unknown context type: {src.type}"

    def _resolve_workflow_output(self, workflow_ref: str) -> str:
        from .workflow_engine import DATA_DIR
        data_path = Path(DATA_DIR)
        if not data_path.exists():
            return f"No workflow data found for: {workflow_ref}"
        # Find latest run matching the workflow ID
        for run_dir in sorted(data_path.iterdir(), reverse=True):
            run_file = run_dir / "run.json"
            if run_file.exists():
                try:
                    with open(run_file) as f:
                        data = json.load(f)
                    if data.get("workflow_id") == workflow_ref and data.get("status") == "completed":
                        workspace = data.get("context", {}).get("workspace", {})
                        return json.dumps(workspace, indent=2, default=str)[:30000]
                except Exception:
                    continue
        return f"No completed runs found for workflow: {workflow_ref}"

    # ── Message Building ──────────────────────────────────────────────────

    def build_messages(
        self,
        agent: AgentDefinition,
        user_messages: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        messages = [{"role": "system", "content": agent.system_prompt}]

        # Inject resolved context
        resolved = self.resolve_context(agent)
        if resolved:
            context_parts = []
            for ctx in resolved:
                if not ctx.get("error"):
                    context_parts.append(f"### {ctx['label']}\n{ctx['content']}")
            if context_parts:
                context_block = "## Agent Context\n\n" + "\n\n".join(context_parts)
                messages.append({"role": "system", "content": context_block})

        messages.extend(user_messages)
        return messages

    # ── YAML I/O ──────────────────────────────────────────────────────────

    def _load_yaml(self, path: Path) -> AgentDefinition:
        with open(path) as f:
            raw = yaml.safe_load(f)
        return AgentDefinition(**raw)

    def _save_yaml(self, path: Path, defn: AgentDefinition) -> None:
        data = defn.model_dump(mode="json", exclude_none=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
```

**Step 4: Run tests, verify pass**

```bash
pytest tests/test_agent_service.py -v
```

**Step 5: Commit**

```bash
git add api/services/agent_service.py tests/test_agent_service.py
git commit -m "feat: add agent service — CRUD, context resolution, message building"
```

---

### Task 3: Agent API Router

**Files:**
- Create: `api/routers/agents.py`
- Modify: `api/main.py:18,106` — add agents router import and include
- Test: `tests/test_agent_api.py`

**Step 1: Write failing tests**

```python
# tests/test_agent_api.py
"""Tests for agent API endpoints"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


VALID_AGENT = {
    "id": "test-agent",
    "name": "Test Agent",
    "system_prompt": "You are a test agent.",
    "starters": ["Hello"],
    "tags": ["test"],
}


@pytest.fixture
def mock_ollama():
    mock = MagicMock()
    mock.health_check.return_value = True
    mock.list_models.return_value = [{"name": "dolphin3:8b", "size": 5000000000}]
    mock.chat.return_value = {"content": "Agent response", "prompt_eval_count": 10, "eval_count": 20}
    return mock


@pytest.fixture
def client(mock_ollama):
    with patch("api.main.ollama_service", mock_ollama):
        from api.main import app
        return TestClient(app)


class TestAgentAPI:
    def test_list_agents(self, client):
        response = client.get("/api/agents")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_agent(self, client):
        response = client.post("/api/agents", json=VALID_AGENT)
        assert response.status_code == 200
        assert response.json()["id"] == "test-agent"

    def test_get_agent(self, client):
        client.post("/api/agents", json=VALID_AGENT)
        response = client.get("/api/agents/test-agent")
        assert response.status_code == 200
        assert response.json()["name"] == "Test Agent"

    def test_get_nonexistent(self, client):
        response = client.get("/api/agents/nonexistent")
        assert response.status_code == 404

    def test_delete_agent(self, client):
        client.post("/api/agents", json=VALID_AGENT)
        response = client.delete("/api/agents/test-agent")
        assert response.status_code == 200
```

**Step 2: Implement router**

```python
# api/routers/agents.py
"""Agent Router — CRUD and chat endpoints for custom agent personas"""

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import logger
from ..models.agent_models import AgentDefinition
from ..services.agent_service import AgentService
from ..services.ollama_service import OllamaService
from ..services.model_resolver import ModelResolver

router = APIRouter(prefix="/api/agents", tags=["agents"])

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
AGENTS_DIR = os.getenv("AGENTS_DIR", "./agents")

_service: Optional[AgentService] = None
_ollama: Optional[OllamaService] = None


def _get_service() -> AgentService:
    global _service
    if _service is None:
        _service = AgentService(AGENTS_DIR)
    return _service


def _get_ollama() -> OllamaService:
    global _ollama
    if _ollama is None:
        _ollama = OllamaService(OLLAMA_HOST)
    return _ollama


class AgentChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


@router.get("")
async def list_agents():
    return _get_service().list_agents()


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    agent = _get_service().get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return agent.model_dump(mode="json", exclude_none=True)


@router.post("")
async def create_agent(defn: AgentDefinition):
    path = _get_service().create_agent(defn)
    return {"id": defn.id, "path": path, "status": "created"}


@router.put("/{agent_id}")
async def update_agent(agent_id: str, defn: AgentDefinition):
    if not _get_service().update_agent(agent_id, defn):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return {"id": agent_id, "status": "updated"}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    if not _get_service().delete_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return {"id": agent_id, "status": "deleted"}


@router.post("/{agent_id}/chat")
async def chat_with_agent(agent_id: str, req: AgentChatRequest):
    service = _get_service()
    agent = service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    messages = service.build_messages(agent, req.messages)
    resolver = ModelResolver(_get_ollama())
    resolved_model = resolver.resolve(model=agent.model, role=agent.role)

    result = _get_ollama().chat(
        model=resolved_model,
        messages=messages,
        temperature=req.temperature or agent.temperature or 0.7,
        max_tokens=req.max_tokens or agent.max_tokens or 4096,
    )

    return {
        "agent_id": agent_id,
        "model": resolved_model,
        "content": result.get("content", ""),
        "token_count": {
            "prompt_tokens": result.get("prompt_eval_count", 0),
            "completion_tokens": result.get("eval_count", 0),
        },
    }


@router.get("/{agent_id}/context")
async def preview_context(agent_id: str):
    service = _get_service()
    agent = service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    resolved = service.resolve_context(agent)
    return {"agent_id": agent_id, "context": resolved}
```

**Step 3: Register router in main.py**

Add to `api/main.py` line 18:
```python
from .routers import chat, completions, models, inventory, exports, graph, workflows, agents
```

Add after line 106:
```python
app.include_router(agents.router)
```

**Step 4: Create example agent YAML**

```yaml
# agents/xsiam-analyst.yaml
id: xsiam-analyst
name: "XSIAM Data Model Analyst"
description: "Cortex XSIAM specialist for data model rules, parsing rules, and XDM normalization"
icon: "shield"
model: deepseek-r1:32b
system_prompt: |
  You are a Palo Alto Networks Cortex XSIAM data model specialist.
  You help security engineers create data model rules, parsing rules,
  and correlation rules for log source onboarding into XSIAM/XDR.

  Your expertise includes:
  - CEF, LEEF, Syslog, JSON log format analysis
  - Cortex Data Model (XDM) field mapping
  - XQL query language for detection rules
  - NICE Framework analytics mapping
  - Cross-source data stitching and causality chains
context:
  - type: file
    value: workflows/xsiam-data-model-rules.yaml
    label: "XSIAM workflow definition"
starters:
  - "Analyze these log samples and generate XDM field mappings"
  - "What XDM fields are needed for brute force detection across all sources?"
  - "Review my data model rules for completeness and correctness"
  - "Generate a correlation rule template for lateral movement detection"
tools:
  - type: web_search
  - type: workflow
    config:
      workflow_id: xsiam-data-model-rules
tags: ["security", "xsiam", "cortex", "xdr"]
```

**Step 5: Run tests, commit**

```bash
pytest tests/test_agent_api.py tests/test_agent_models.py tests/test_agent_service.py -v
git add api/routers/agents.py api/main.py agents/xsiam-analyst.yaml tests/test_agent_api.py
git commit -m "feat: add agent REST API, register router, create XSIAM example agent"
```

---

### Task 4: Agents Tab in Dashboard UI

**Files:**
- Modify: `api/static/index.html` — add Agents tab button, tab content, CSS, JS

**Step 1: Add tab button** (in the tab nav bar, after WORKFLOWS)

Add a new `<button>` to the tab nav with `onclick="switchTab('agents')"`.

**Step 2: Add tab content HTML**

Agent gallery (cards grid), agent builder form (create/edit modal with system prompt textarea, context source list, model selector, starters list, tools checkboxes), and agent chat panel.

**Step 3: Add CSS classes**

`.agent-card`, `.agent-grid`, `.agent-builder`, `.agent-chat-panel`, `.agent-icon`, `.agent-starter`.

**Step 4: Add JavaScript functions**

- `loadAgentsTab()` — fetch `/api/agents`, render gallery
- `createAgent()` — collect form data, POST to `/api/agents`
- `editAgent(id)` — load agent into form
- `deleteAgent(id)` — DELETE call with confirm
- `chatWithAgent(id)` — open chat panel with agent persona
- `sendAgentMessage(id)` — POST to `/api/agents/{id}/chat`

**Step 5: Test in browser, commit**

```bash
git add api/static/index.html
git commit -m "feat: add Agents tab — gallery, builder form, agent chat"
```

---

### Task 5: Enhanced Context Graph

**Files:**
- Modify: `api/services/graph_service.py` — add agent + workflow nodes
- Modify: `api/static/index.html` — graph UI enhancements
- Test: `tests/test_graph_enhanced.py`

**Step 1: Write failing tests**

```python
# tests/test_graph_enhanced.py
"""Tests for enhanced graph with agent and workflow nodes"""
import json
import os
import tempfile
import pytest
from unittest.mock import patch
from api.services.graph_service import build_graph


class TestAgentNodes:
    def test_agent_nodes_in_graph(self):
        agents_dir = tempfile.mkdtemp()
        # Write a test agent YAML
        agent_yaml = {
            "id": "test-agent",
            "name": "Test Agent",
            "system_prompt": "Test",
            "context": [{"type": "text", "value": "security analysis"}],
            "tags": ["security"],
        }
        import yaml
        with open(os.path.join(agents_dir, "test-agent.yaml"), "w") as f:
            yaml.dump(agent_yaml, f)

        with patch("api.services.graph_service.AGENTS_DIR", agents_dir):
            graph = build_graph(force=True)

        agent_nodes = [n for n in graph["nodes"] if n.get("type") == "agent"]
        assert len(agent_nodes) >= 1
        assert agent_nodes[0]["id"] == "agent:test-agent"
```

**Step 2: Update graph_service.py**

Add `AGENTS_DIR` constant, `_build_agent_nodes()` function that scans `agents/*.yaml`, creates agent nodes and links them to topic nodes via tag/keyword matching.

Add `_build_workflow_nodes()` that scans `data/workflows/*/run.json` for completed runs, creates workflow_run nodes.

Update `build_graph()` to call both new functions after existing session/topic/source nodes.

**Step 3: Update graph UI in index.html**

- Add agent (orange) and workflow_run (purple) to the D3 color map
- Add type toggle buttons in the Research tab
- Add search input that filters nodes by name
- Update legend with new node types

**Step 4: Run tests, commit**

```bash
pytest tests/test_graph_enhanced.py -v
git add api/services/graph_service.py api/static/index.html tests/test_graph_enhanced.py
git commit -m "feat: enhanced context graph — agent and workflow nodes, search, type filters"
```

---

### Task 6: macOS Desktop App

**Files:**
- Create: `desktop/app.py`
- Create: `desktop/setup_app.py`
- Create: `desktop/build.sh`
- Create: `desktop/entitlements.plist`
- Modify: `setup/requirements.txt` — add pywebview

**Step 1: Add pywebview to requirements**

```bash
echo "pywebview==5.3.2" >> setup/requirements.txt
pip install pywebview
```

**Step 2: Create launcher**

```python
# desktop/app.py
#!/usr/bin/env python3
"""Local AI Platform — macOS Desktop App"""

import os
import signal
import socket
import subprocess
import sys
import threading
import time

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

APP_NAME = "Local AI Platform"
OLLAMA_PORT = 11434
_ollama_proc = None


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def is_port_open(port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


def ensure_ollama() -> bool:
    global _ollama_proc
    if is_port_open(OLLAMA_PORT):
        return True
    for candidate in ["/usr/local/bin/ollama", "/opt/homebrew/bin/ollama"]:
        if os.path.isfile(candidate):
            _ollama_proc = subprocess.Popen(
                [candidate, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(20):
                if is_port_open(OLLAMA_PORT):
                    return True
                time.sleep(0.5)
            return False
    return False


def start_server(port: int):
    import uvicorn
    uvicorn.run("api.main:app", host="127.0.0.1", port=port, log_level="warning")


def cleanup():
    global _ollama_proc
    if _ollama_proc and _ollama_proc.poll() is None:
        _ollama_proc.terminate()
        try:
            _ollama_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ollama_proc.kill()


def main():
    import webview

    ensure_ollama()
    port = find_free_port()
    server = threading.Thread(target=start_server, args=(port,), daemon=True)
    server.start()

    # Wait for server
    for _ in range(40):
        if is_port_open(port):
            break
        time.sleep(0.25)

    window = webview.create_window(
        APP_NAME,
        f"http://127.0.0.1:{port}",
        width=1280,
        height=820,
        min_size=(800, 600),
    )
    webview.start()
    cleanup()


if __name__ == "__main__":
    main()
```

**Step 3: Create build script**

```bash
# desktop/build.sh
#!/bin/bash
set -e
echo "Building Local AI Platform.app..."
cd "$(dirname "$0")"
python setup_app.py py2app 2>&1
echo "Built: dist/Local AI Platform.app"
```

**Step 4: Create entitlements.plist**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
    <key>com.apple.security.network.client</key>
    <true/>
</dict>
</plist>
```

**Step 5: Test launcher directly**

```bash
python desktop/app.py
# Expected: Native window opens with dashboard
```

**Step 6: Commit**

```bash
git add desktop/ setup/requirements.txt
git commit -m "feat: macOS desktop app — pywebview launcher, build automation"
```

---

### Task 7: Final Integration & CLAUDE.md Update

**Files:**
- Modify: `CLAUDE.md` — document agents, desktop app
- Modify: `.gitignore` — add `desktop/dist/`, `desktop/build/`

**Step 1: Update CLAUDE.md** with agent system docs and desktop app section.

**Step 2: Update .gitignore**

```
desktop/dist/
desktop/build/
*.app
*.dmg
```

**Step 3: Run full test suite**

```bash
pytest tests/ -v -k "not test_api.py"
# Expected: all pass
```

**Step 4: Final commit and push**

```bash
git add -A
git commit -m "docs: update CLAUDE.md with agents, desktop app, enhanced graph"
git push
```
