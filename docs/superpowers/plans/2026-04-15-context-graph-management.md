# Phase 2: Context Graph Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent persistent memory — track tool usage per conversation, auto-summarize sessions, let users pin facts, persist across sessions in YAML, and manage everything from a Memory tab in the dashboard.

**Architecture:** Three-layer system: `ContextStore` (in-memory per-conversation tracking) → `MemoryService` (YAML persistence, fact management, memory injection) → Dashboard Memory tab (session browser, fact manager, stats). The context store records tool calls during conversations, the memory service persists completed sessions and manages pinnable facts, and the chat router injects saved facts into new conversations.

**Tech Stack:** Python 3, FastAPI, PyYAML, dataclasses, uuid (all stdlib/existing)

**Spec:** `docs/superpowers/specs/2026-04-15-context-graph-management-design.md`

---

## File Map

### New Files
| File | Responsibility |
|------|---------------|
| `api/models/context_models.py` | Dataclass models: ToolCallRecord, ConversationContext, SessionSummary, PinnedFact |
| `api/services/context_store.py` | In-memory per-conversation context tracking |
| `api/services/memory_service.py` | YAML persistence, fact CRUD, session search, memory injection |
| `api/routers/context.py` | Active conversation context endpoints |
| `api/routers/memory.py` | Persisted session + fact management endpoints |
| `tests/test_context_store.py` | Context tracking tests |
| `tests/test_memory_service.py` | Memory persistence, facts, search tests |

### Modified Files
| File | Change |
|------|--------|
| `api/main.py:18,99-109` | Register context and memory routers |
| `api/services/tool_executor.py:23-98` | Accept context_store, record tool calls |
| `api/routers/chat.py:46-207` | Generate conversation_id, inject memory, pass context to executor |
| `api/static/index.html` | Add Memory tab with session history, facts, stats |

---

## Task 1: Context Models

**Files:**
- Create: `api/models/context_models.py`
- Test: `tests/test_context_store.py`

- [ ] **Step 1: Write failing test for models**

Create `tests/test_context_store.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_context_store.py::TestContextModels -v`
Expected: FAIL — `api.models.context_models` doesn't exist

- [ ] **Step 3: Create the context models**

Create `api/models/context_models.py`:

```python
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
    """Record of a single tool invocation during a conversation."""
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
    """Per-conversation context tracking tool calls, skills, and metadata."""
    conversation_id: str
    model: str
    started_at: str = field(default_factory=_now_iso)
    last_activity: str = field(default_factory=_now_iso)
    message_count: int = 0
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    skills_injected: List[str] = field(default_factory=list)
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
    """Persisted summary of a completed conversation."""
    id: str
    model: str
    started_at: str
    ended_at: str
    duration_minutes: int
    message_count: int
    tool_calls_count: int
    tools_used: List[str]
    skills_triggered: List[str]
    topics: List[str] = field(default_factory=list)
    preview: str = ""
    tool_calls: List[dict] = field(default_factory=list)

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
            "id": self.id,
            "model": self.model,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_minutes": self.duration_minutes,
            "message_count": self.message_count,
            "tool_calls_count": self.tool_calls_count,
            "tools_used": self.tools_used,
            "skills_triggered": self.skills_triggered,
            "topics": self.topics,
            "preview": self.preview,
            "tool_calls": self.tool_calls,
        }

    def to_index_entry(self) -> dict:
        """Lightweight dict for the session index (no tool call details)."""
        return {
            "id": self.id,
            "model": self.model,
            "started_at": self.started_at,
            "duration_minutes": self.duration_minutes,
            "message_count": self.message_count,
            "tool_calls_count": self.tool_calls_count,
            "preview": self.preview,
            "topics": self.topics,
        }


@dataclass
class PinnedFact:
    """A user-pinned fact stored in memory."""
    content: str
    tags: List[str] = field(default_factory=list)
    id: str = field(default_factory=_fact_id)
    created_at: str = field(default_factory=_now_iso)
    source_conversation: Optional[str] = None
    pinned_by: str = "user"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "tags": self.tags,
            "created_at": self.created_at,
            "source_conversation": self.source_conversation,
            "pinned_by": self.pinned_by,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_context_store.py::TestContextModels -v`
Expected: All 5 PASS

- [ ] **Step 5: Commit**

```bash
git add api/models/context_models.py tests/test_context_store.py
git commit -m "feat: add context models for conversation tracking and memory"
```

---

## Task 2: Context Store Service

**Files:**
- Create: `api/services/context_store.py`
- Test: `tests/test_context_store.py` (append)

- [ ] **Step 1: Append tests**

Append to `tests/test_context_store.py`:

```python
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
            tool_name="echo__echo",
            arguments={"text": "hi"},
            result={"echo": "hi"},
            iteration=1,
            duration_ms=100,
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_context_store.py::TestContextStore -v`
Expected: FAIL — `api.services.context_store` doesn't exist

- [ ] **Step 3: Create the context store**

Create `api/services/context_store.py`:

```python
#!/usr/bin/env python3
"""
Context Store — In-memory per-conversation context tracking

Stores active conversation contexts keyed by conversation_id.
Records tool calls, skill injections, and message counts.
Contexts are removed when sessions are persisted to memory.
"""

from __future__ import annotations

from ..logging_config import logger
from ..models.context_models import ConversationContext, ToolCallRecord, _now_iso


class ContextStore:
    """In-memory store for active conversation contexts."""

    def __init__(self):
        self._contexts: dict[str, ConversationContext] = {}

    def create(self, conversation_id: str, model: str) -> ConversationContext:
        """Initialize a new conversation context."""
        ctx = ConversationContext(
            conversation_id=conversation_id,
            model=model,
        )
        self._contexts[conversation_id] = ctx
        logger.info(f"Context created: {conversation_id} (model={model})")
        return ctx

    def get(self, conversation_id: str):
        """Return the context for a conversation, or None."""
        return self._contexts.get(conversation_id)

    def record_tool_call(self, conversation_id: str, tool_call: ToolCallRecord) -> None:
        """Append a tool call record to a conversation context."""
        ctx = self._contexts.get(conversation_id)
        if ctx:
            ctx.tool_calls.append(tool_call)
            ctx.last_activity = _now_iso()

    def record_skill(self, conversation_id: str, skill_id: str) -> None:
        """Record that a skill was injected into this conversation."""
        ctx = self._contexts.get(conversation_id)
        if ctx and skill_id not in ctx.skills_injected:
            ctx.skills_injected.append(skill_id)

    def update_activity(self, conversation_id: str) -> None:
        """Bump last_activity timestamp and increment message count."""
        ctx = self._contexts.get(conversation_id)
        if ctx:
            ctx.message_count += 1
            ctx.last_activity = _now_iso()

    def list_active(self) -> list:
        """Return summary dicts for all active conversations."""
        return [ctx.to_dict() for ctx in self._contexts.values()]

    def remove(self, conversation_id: str):
        """Remove and return a context (for persistence)."""
        return self._contexts.pop(conversation_id, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_context_store.py -v`
Expected: All 12 PASS (5 models + 7 store)

- [ ] **Step 5: Commit**

```bash
git add api/services/context_store.py tests/test_context_store.py
git commit -m "feat: add context store for per-conversation tracking"
```

---

## Task 3: Memory Service

**Files:**
- Create: `api/services/memory_service.py`
- Test: `tests/test_memory_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_memory_service.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_memory_service.py -v`
Expected: FAIL — `api.services.memory_service` doesn't exist

- [ ] **Step 3: Create the memory service**

Create `api/services/memory_service.py`:

```python
#!/usr/bin/env python3
"""
Memory Service — YAML persistence for session summaries and pinned facts

Manages:
- Session summaries in data/memory/sessions/{id}.yaml
- Session index in data/memory/index.yaml
- Pinned facts in data/memory/facts.yaml
- Memory injection for new conversations
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from ..logging_config import logger
from ..models.context_models import PinnedFact, SessionSummary


class MemoryService:
    """Persists session summaries and pinned facts to YAML files."""

    def __init__(self, data_dir: Optional[str] = None):
        self._dir = Path(data_dir) if data_dir else Path("data/memory")
        self._sessions_dir = self._dir / "sessions"
        self._index_file = self._dir / "index.yaml"
        self._facts_file = self._dir / "facts.yaml"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    # ── Session Persistence ───────────────────────────────────────────

    def save_session(self, summary: SessionSummary) -> None:
        """Save a session summary to YAML and update the index."""
        # Write full session file
        session_file = self._sessions_dir / f"{summary.id}.yaml"
        session_file.write_text(yaml.dump(summary.to_dict(), default_flow_style=False))

        # Update index
        index = self._load_index()
        # Remove existing entry if re-saving
        index = [e for e in index if e["id"] != summary.id]
        index.insert(0, summary.to_index_entry())
        self._save_index(index)
        logger.info(f"Session saved: {summary.id} ({summary.message_count} messages)")

    def list_sessions(self, limit: int = 50, offset: int = 0) -> list:
        """List saved sessions from the index (newest first)."""
        index = self._load_index()
        return index[offset:offset + limit]

    def get_session(self, session_id: str) -> Optional[dict]:
        """Load full session detail from its YAML file."""
        session_file = self._sessions_dir / f"{session_id}.yaml"
        if not session_file.exists():
            return None
        try:
            return yaml.safe_load(session_file.read_text())
        except yaml.YAMLError as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def delete_session(self, session_id: str) -> bool:
        """Delete a session file and remove from index."""
        session_file = self._sessions_dir / f"{session_id}.yaml"
        if session_file.exists():
            session_file.unlink()
        index = self._load_index()
        new_index = [e for e in index if e["id"] != session_id]
        if len(new_index) == len(index):
            return False
        self._save_index(new_index)
        logger.info(f"Session deleted: {session_id}")
        return True

    def search_sessions(self, query: str) -> list:
        """Search sessions by keyword in preview and topics."""
        query_lower = query.lower()
        index = self._load_index()
        results = []
        for entry in index:
            preview = entry.get("preview", "").lower()
            topics = [t.lower() for t in entry.get("topics", [])]
            if query_lower in preview or any(query_lower in t for t in topics):
                results.append(entry)
        return results

    # ── Facts ─────────────────────────────────────────────────────────

    def add_fact(self, content: str, tags: list = None, source_conversation: str = None) -> dict:
        """Pin a new fact."""
        fact = PinnedFact(
            content=content,
            tags=tags or [],
            source_conversation=source_conversation,
        )
        facts = self._load_facts()
        facts.append(fact.to_dict())
        self._save_facts(facts)
        logger.info(f"Fact added: {fact.id}")
        return fact.to_dict()

    def list_facts(self) -> list:
        """List all pinned facts."""
        return self._load_facts()

    def delete_fact(self, fact_id: str) -> bool:
        """Delete a pinned fact by ID."""
        facts = self._load_facts()
        new_facts = [f for f in facts if f["id"] != fact_id]
        if len(new_facts) == len(facts):
            return False
        self._save_facts(new_facts)
        logger.info(f"Fact deleted: {fact_id}")
        return True

    def get_injection_context(self) -> str:
        """Format pinned facts as a string for system prompt injection."""
        facts = self._load_facts()
        if not facts:
            return ""
        lines = [f"- {f['content']}" for f in facts]
        return "User memory (pinned facts):\n" + "\n".join(lines)

    # ── Stats ─────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return memory statistics."""
        index = self._load_index()
        facts = self._load_facts()
        total_tool_calls = sum(e.get("tool_calls_count", 0) for e in index)
        return {
            "total_sessions": len(index),
            "total_facts": len(facts),
            "total_tool_calls": total_tool_calls,
        }

    # ── Private Helpers ───────────────────────────────────────────────

    def _load_index(self) -> list:
        if not self._index_file.exists():
            return []
        data = yaml.safe_load(self._index_file.read_text()) or {}
        return data.get("sessions", [])

    def _save_index(self, sessions: list) -> None:
        self._index_file.write_text(yaml.dump({"sessions": sessions}, default_flow_style=False))

    def _load_facts(self) -> list:
        if not self._facts_file.exists():
            return []
        data = yaml.safe_load(self._facts_file.read_text()) or {}
        return data.get("facts", [])

    def _save_facts(self, facts: list) -> None:
        self._facts_file.write_text(yaml.dump({"facts": facts}, default_flow_style=False))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_memory_service.py -v`
Expected: All 9 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/memory_service.py tests/test_memory_service.py
git commit -m "feat: add memory service with YAML persistence for sessions and facts"
```

---

## Task 4: Context and Memory Routers

**Files:**
- Create: `api/routers/context.py`
- Create: `api/routers/memory.py`
- Modify: `api/main.py`
- Test: `tests/test_context_store.py` (append)
- Test: `tests/test_memory_service.py` (append)

- [ ] **Step 1: Create context router**

Create `api/routers/context.py`:

```python
#!/usr/bin/env python3
"""
Context Router — Active conversation context endpoints
"""

from fastapi import APIRouter, HTTPException

from ..services.context_store import ContextStore

router = APIRouter(prefix="/api/context", tags=["context"])

# Shared instance — same store used by chat router
context_store = ContextStore()


@router.get("")
async def list_active_contexts():
    """List all active (in-memory) conversation contexts."""
    return context_store.list_active()


@router.get("/{conversation_id}")
async def get_context(conversation_id: str):
    """Get full context for an active conversation."""
    ctx = context_store.get(conversation_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ctx.to_dict()


@router.get("/{conversation_id}/tool-calls")
async def get_tool_calls(conversation_id: str):
    """Get just the tool calls for a conversation."""
    ctx = context_store.get(conversation_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return [tc.to_dict() for tc in ctx.tool_calls]
```

- [ ] **Step 2: Create memory router**

Create `api/routers/memory.py`:

```python
#!/usr/bin/env python3
"""
Memory Router — Persisted session and fact management endpoints
"""

from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.memory_service import MemoryService

router = APIRouter(prefix="/api/memory", tags=["memory"])

memory_service = MemoryService()


class AddFactRequest(BaseModel):
    content: str = Field(..., description="The fact to pin")
    tags: List[str] = Field(default_factory=list, description="Optional tags")
    source_conversation: Optional[str] = Field(None, description="Source conversation ID")


class SearchRequest(BaseModel):
    query: str = Field(..., description="Search query")


@router.get("/sessions")
async def list_sessions(limit: int = 50, offset: int = 0):
    """List saved sessions from the index."""
    return memory_service.list_sessions(limit=limit, offset=offset)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get full session detail with tool calls."""
    session = memory_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a saved session."""
    if not memory_service.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted", "id": session_id}


@router.post("/sessions/search")
async def search_sessions(body: SearchRequest):
    """Search sessions by keyword in preview and topics."""
    return memory_service.search_sessions(body.query)


@router.get("/facts")
async def list_facts():
    """List all pinned facts."""
    return memory_service.list_facts()


@router.post("/facts", status_code=201)
async def add_fact(body: AddFactRequest):
    """Pin a new fact."""
    return memory_service.add_fact(
        content=body.content,
        tags=body.tags,
        source_conversation=body.source_conversation,
    )


@router.delete("/facts/{fact_id}")
async def delete_fact(fact_id: str):
    """Delete a pinned fact."""
    if not memory_service.delete_fact(fact_id):
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"status": "deleted", "id": fact_id}


@router.get("/stats")
async def memory_stats():
    """Return memory statistics."""
    return memory_service.get_stats()
```

- [ ] **Step 3: Register routers in `api/main.py`**

Update the import line (line 18):
```python
from .routers import chat, completions, models, inventory, exports, graph, workflows, api_keys, plugins, setup, context, memory
```

Add after `app.include_router(setup.router)` (line 109):
```python
app.include_router(context.router)
app.include_router(memory.router)
```

- [ ] **Step 4: Append router tests to test files**

Append to `tests/test_context_store.py`:

```python
import os
import importlib
from fastapi.testclient import TestClient


class TestContextRouter:
    @pytest.fixture(scope="class")
    def client(self):
        os.environ["ENABLE_API_AUTH"] = "false"
        os.environ["RATE_LIMIT_RPM"] = "0"
        import api.middleware
        importlib.reload(api.middleware)
        import api.main
        importlib.reload(api.main)
        from api.main import app
        return TestClient(app)

    def test_list_active_contexts(self, client):
        resp = client.get("/api/context")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_nonexistent_context(self, client):
        resp = client.get("/api/context/nonexistent")
        assert resp.status_code == 404
```

Append to `tests/test_memory_service.py`:

```python
import os
import importlib
from fastapi.testclient import TestClient


class TestMemoryRouter:
    @pytest.fixture(scope="class")
    def client(self):
        os.environ["ENABLE_API_AUTH"] = "false"
        os.environ["RATE_LIMIT_RPM"] = "0"
        import api.middleware
        importlib.reload(api.middleware)
        import api.main
        importlib.reload(api.main)
        from api.main import app
        return TestClient(app)

    def test_list_sessions_empty(self, client):
        resp = client.get("/api/memory/sessions")
        assert resp.status_code == 200

    def test_add_and_list_facts_via_api(self, client):
        resp = client.post("/api/memory/facts", json={
            "content": "Test fact via API",
            "tags": ["test"],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "Test fact via API"

        resp = client.get("/api/memory/facts")
        assert resp.status_code == 200
        facts = resp.json()
        assert any(f["content"] == "Test fact via API" for f in facts)

    def test_memory_stats(self, client):
        resp = client.get("/api/memory/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_sessions" in data
        assert "total_facts" in data

    def test_delete_fact_via_api(self, client):
        resp = client.post("/api/memory/facts", json={
            "content": "Delete me via API", "tags": [],
        })
        fact_id = resp.json()["id"]
        resp = client.delete(f"/api/memory/facts/{fact_id}")
        assert resp.status_code == 200

    def test_search_sessions(self, client):
        resp = client.post("/api/memory/sessions/search", json={"query": "test"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
```

- [ ] **Step 5: Run all tests**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_context_store.py tests/test_memory_service.py -v`
Expected: All PASS (12 context + 2 router + 9 memory + 5 router = 28)

- [ ] **Step 6: Commit**

```bash
git add api/routers/context.py api/routers/memory.py api/main.py tests/test_context_store.py tests/test_memory_service.py
git commit -m "feat: add context and memory routers with full CRUD endpoints"
```

---

## Task 5: Wire Context Store into Tool Executor and Chat Router

**Files:**
- Modify: `api/services/tool_executor.py`
- Modify: `api/routers/chat.py`

- [ ] **Step 1: Update ToolExecutor to accept and use context store**

In `api/services/tool_executor.py`, modify the class:

Add import at top:
```python
import time
from ..models.context_models import ToolCallRecord
```

Change `__init__` to optionally accept a context_store and conversation_id:
```python
    def __init__(self, ollama_service: OllamaService, plugin_service: PluginService):
        self.ollama = ollama_service
        self.plugins = plugin_service
        self._context_store = None

    def set_context(self, context_store, conversation_id: str):
        """Set the context store and conversation ID for recording tool calls."""
        self._context_store = context_store
        self._conversation_id = conversation_id
```

In the `execute` method, after each tool call (line 78-88), add context recording:
```python
                tool_result = self._execute_tool(tool_name, arguments)
                end_time = time.time()
                tool_calls_made.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": tool_result,
                    "iteration": iteration + 1,
                })

                # Record to context store if available
                if self._context_store and self._conversation_id:
                    self._context_store.record_tool_call(
                        self._conversation_id,
                        ToolCallRecord(
                            tool_name=tool_name,
                            arguments=arguments,
                            result=tool_result,
                            iteration=iteration + 1,
                            duration_ms=int((end_time - start_time) * 1000),
                        ),
                    )
```

Add `start_time = time.time()` before `tool_result = self._execute_tool(...)`.

- [ ] **Step 2: Update Chat Router to use context store and inject memory**

In `api/routers/chat.py`:

Add imports:
```python
import uuid
from fastapi import APIRouter, Request
from ..services.memory_service import MemoryService
from .context import context_store as _context_store
```

Add after `_tool_executor`:
```python
_memory_service = MemoryService()
```

In `chat_completions`, change signature to accept Request for headers:
```python
async def chat_completions(request: ChatCompletionRequest, req: Request):
```

At the top of the function body (after logging), add conversation ID generation and memory injection:
```python
    # ── Conversation Tracking ─────────────────────────────────────────
    conversation_id = req.headers.get("X-Conversation-ID", str(uuid.uuid4()))
    if not _context_store.get(conversation_id):
        _context_store.create(conversation_id, request.model)
    _context_store.update_activity(conversation_id)

    # ── Memory Injection ──────────────────────────────────────────────
    memory_context = _memory_service.get_injection_context()
    if memory_context:
        messages = [{"role": "system", "content": memory_context}] + messages
```

In the plugin skill injection block, add skill recording:
```python
    matched_skills = _plugin_service.get_skills(last_user_content)
    for skill in matched_skills:
        _context_store.record_skill(conversation_id, skill.get("id", ""))
        if skill["inject"] == "system":
            messages = [{"role": "system", "content": skill["content"]}] + messages
        elif skill["inject"] == "context":
            messages.append({"role": "system", "content": skill["content"]})
```

Before calling `_tool_executor.execute()`, set its context:
```python
        _tool_executor.set_context(_context_store, conversation_id)
```

Add `conversation_id` to the response:
```python
        response["conversation_id"] = conversation_id
```

Do the same for the no-tools path.

- [ ] **Step 3: Run all tests**

Run: `source ../../../venv/bin/activate && python -m pytest tests/ --tb=short -k "not integration" 2>&1 | tail -10`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add api/services/tool_executor.py api/routers/chat.py
git commit -m "feat: wire context store into tool executor and chat router"
```

---

## Task 6: Session Auto-Save on Conversation End

**Files:**
- Create: `api/services/session_manager.py`
- Modify: `api/routers/context.py`

- [ ] **Step 1: Create session manager**

Create `api/services/session_manager.py`:

```python
#!/usr/bin/env python3
"""
Session Manager — Handles conversation lifecycle and auto-save

Provides an endpoint to explicitly close a conversation, which
persists it to the memory service. Also provides a cleanup method
for stale conversations (called periodically or on shutdown).
"""

from __future__ import annotations

from ..logging_config import logger
from ..models.context_models import SessionSummary
from .context_store import ContextStore
from .memory_service import MemoryService


class SessionManager:
    """Manages conversation lifecycle: close and persist."""

    def __init__(self, context_store: ContextStore, memory_service: MemoryService):
        self.context_store = context_store
        self.memory_service = memory_service

    def close_session(self, conversation_id: str, preview: str = "") -> dict:
        """Close a conversation and persist it to memory."""
        ctx = self.context_store.remove(conversation_id)
        if not ctx:
            return None

        summary = SessionSummary.from_context(ctx, preview=preview)
        self.memory_service.save_session(summary)
        logger.info(f"Session closed and saved: {conversation_id}")
        return summary.to_dict()

    def cleanup_stale(self, max_age_seconds: int = 300) -> int:
        """Close conversations with no activity for max_age_seconds."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        closed = 0
        for ctx_dict in self.context_store.list_active():
            last = datetime.fromisoformat(ctx_dict["last_activity"])
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age = (now - last).total_seconds()
            if age > max_age_seconds:
                self.close_session(ctx_dict["conversation_id"], preview=ctx_dict.get("preview", ""))
                closed += 1
        return closed
```

- [ ] **Step 2: Add close endpoint to context router**

Update `api/routers/context.py` — add imports and endpoint:

```python
from ..services.memory_service import MemoryService
from ..services.session_manager import SessionManager

_memory_service = MemoryService()
_session_manager = SessionManager(context_store, _memory_service)


@router.post("/{conversation_id}/close")
async def close_conversation(conversation_id: str):
    """Close a conversation and persist it to memory."""
    result = _session_manager.close_session(conversation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return result


@router.post("/cleanup")
async def cleanup_stale():
    """Close stale conversations (no activity for 5 min)."""
    closed = _session_manager.cleanup_stale(max_age_seconds=300)
    return {"closed": closed}
```

- [ ] **Step 3: Add tests**

Append to `tests/test_context_store.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_context_store.py tests/test_memory_service.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/session_manager.py api/routers/context.py tests/test_context_store.py
git commit -m "feat: add session manager with close and auto-cleanup"
```

---

## Task 7: Memory Tab in Dashboard

**Files:**
- Modify: `api/static/index.html`

This task adds the Memory tab to the existing dashboard. The tab has three panels: Session History, Pinned Facts, and Memory Stats. Due to the file size, this task provides the JavaScript and HTML to append — the CSS follows existing dashboard patterns.

- [ ] **Step 1: Add Memory tab button**

In `api/static/index.html`, find the tab bar (the `<div>` containing `.tab-btn` elements) and add a new tab button after the last existing one:

```html
<button class="tab-btn" data-tab="memory" onclick="switchTab('memory')">
  <span>Memory</span>
</button>
```

- [ ] **Step 2: Add Memory tab content panel**

After the last `.tab-content` div, add:

```html
<!-- ── MEMORY TAB ──────────────────────────────────────────────── -->
<div class="tab-content" id="tab-memory" style="display:none">
  <div style="display:flex;gap:12px;margin-bottom:16px;">
    <input type="text" id="memory-search" placeholder="Search sessions and facts..."
      style="flex:1;background:var(--bg-panel);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:6px;font-family:var(--mono);font-size:0.85rem;"
      oninput="searchMemory(this.value)">
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
    <!-- Session History -->
    <div class="panel" style="border:1px solid var(--border);border-radius:8px;padding:16px;">
      <h3 style="color:var(--cyan);margin-bottom:12px;font-size:0.9rem;">Session History</h3>
      <div id="session-list" style="max-height:400px;overflow-y:auto;"></div>
    </div>
    <!-- Pinned Facts -->
    <div class="panel" style="border:1px solid var(--border);border-radius:8px;padding:16px;">
      <h3 style="color:var(--cyan);margin-bottom:12px;font-size:0.9rem;">Pinned Facts</h3>
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <input type="text" id="new-fact-input" placeholder="Add a fact..."
          style="flex:1;background:var(--bg-panel);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:4px;font-family:var(--mono);font-size:0.8rem;">
        <button onclick="addFact()" style="background:var(--cyan);color:#000;border:none;padding:6px 14px;border-radius:4px;cursor:pointer;font-weight:600;font-size:0.8rem;">Pin</button>
      </div>
      <div id="facts-list" style="max-height:350px;overflow-y:auto;"></div>
    </div>
  </div>
  <!-- Stats -->
  <div style="display:flex;gap:16px;margin-top:16px;">
    <div class="panel" style="border:1px solid var(--border);border-radius:8px;padding:12px;flex:1;text-align:center;">
      <div style="font-size:1.4rem;font-weight:600;color:var(--cyan);" id="stat-sessions">0</div>
      <div style="font-size:0.75rem;color:var(--text-dim);">Sessions</div>
    </div>
    <div class="panel" style="border:1px solid var(--border);border-radius:8px;padding:12px;flex:1;text-align:center;">
      <div style="font-size:1.4rem;font-weight:600;color:var(--cyan);" id="stat-tool-calls">0</div>
      <div style="font-size:0.75rem;color:var(--text-dim);">Tool Calls</div>
    </div>
    <div class="panel" style="border:1px solid var(--border);border-radius:8px;padding:12px;flex:1;text-align:center;">
      <div style="font-size:1.4rem;font-weight:600;color:var(--cyan);" id="stat-facts">0</div>
      <div style="font-size:0.75rem;color:var(--text-dim);">Facts</div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add Memory tab JavaScript**

Append to the `<script>` block in `index.html`:

```javascript
// ── Memory Tab ───────────────────────────────────────────────────
async function loadMemoryTab() {
  loadSessions();
  loadFacts();
  loadMemoryStats();
}

async function loadSessions() {
  try {
    const r = await fetch('/api/memory/sessions');
    const sessions = await r.json();
    const el = document.getElementById('session-list');
    if (!sessions.length) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:8px;">No saved sessions yet.</div>';
      return;
    }
    el.innerHTML = sessions.map(s => `
      <div style="padding:10px;border-bottom:1px solid var(--border);cursor:pointer;" onclick="toggleSessionDetail('${s.id}')">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div style="font-size:0.85rem;color:var(--text);">${escHtml(s.preview || 'No preview')}</div>
          <button onclick="event.stopPropagation();deleteSession('${s.id}')" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:0.75rem;">delete</button>
        </div>
        <div style="font-size:0.7rem;color:var(--text-dim);margin-top:4px;">
          ${s.model || ''} &middot; ${s.message_count || 0} msgs &middot; ${s.tool_calls_count || 0} tool calls &middot; ${s.duration_minutes || 0}m
        </div>
        <div id="session-detail-${s.id}" style="display:none;margin-top:8px;padding:8px;background:var(--bg-deep);border-radius:4px;font-size:0.75rem;"></div>
      </div>
    `).join('');
  } catch(e) { console.error('Failed to load sessions:', e); }
}

async function toggleSessionDetail(id) {
  const el = document.getElementById('session-detail-' + id);
  if (el.style.display !== 'none') { el.style.display = 'none'; return; }
  try {
    const r = await fetch('/api/memory/sessions/' + id);
    const s = await r.json();
    let html = '<div style="color:var(--text-dim);">';
    if (s.tools_used && s.tools_used.length) html += '<div>Tools: ' + s.tools_used.join(', ') + '</div>';
    if (s.topics && s.topics.length) html += '<div>Topics: ' + s.topics.join(', ') + '</div>';
    if (s.tool_calls && s.tool_calls.length) {
      html += '<div style="margin-top:6px;font-weight:500;color:var(--text);">Tool Calls:</div>';
      s.tool_calls.forEach(tc => {
        html += '<div style="margin:4px 0;padding:4px;background:var(--bg);border-radius:3px;">' +
          '<span style="color:var(--cyan);">' + escHtml(tc.tool_name) + '</span> ' +
          '<span style="color:var(--text-muted);">' + tc.duration_ms + 'ms</span></div>';
      });
    }
    html += '</div>';
    el.innerHTML = html;
    el.style.display = '';
  } catch(e) { el.innerHTML = '<div style="color:var(--red);">Failed to load</div>'; el.style.display = ''; }
}

async function deleteSession(id) {
  await fetch('/api/memory/sessions/' + id, {method: 'DELETE'});
  loadSessions();
  loadMemoryStats();
}

async function loadFacts() {
  try {
    const r = await fetch('/api/memory/facts');
    const facts = await r.json();
    const el = document.getElementById('facts-list');
    if (!facts.length) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:8px;">No pinned facts. Add one above.</div>';
      return;
    }
    el.innerHTML = facts.map(f => `
      <div style="padding:8px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:start;">
        <div>
          <div style="font-size:0.85rem;color:var(--text);">${escHtml(f.content)}</div>
          <div style="font-size:0.7rem;color:var(--text-dim);margin-top:2px;">
            ${(f.tags||[]).map(t => '<span style="color:var(--cyan);">#'+escHtml(t)+'</span>').join(' ')}
          </div>
        </div>
        <button onclick="deleteFact('${f.id}')" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:0.75rem;">delete</button>
      </div>
    `).join('');
  } catch(e) { console.error('Failed to load facts:', e); }
}

async function addFact() {
  const input = document.getElementById('new-fact-input');
  const content = input.value.trim();
  if (!content) return;
  await fetch('/api/memory/facts', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({content, tags: []}),
  });
  input.value = '';
  loadFacts();
  loadMemoryStats();
}

async function deleteFact(id) {
  await fetch('/api/memory/facts/' + id, {method: 'DELETE'});
  loadFacts();
  loadMemoryStats();
}

async function loadMemoryStats() {
  try {
    const r = await fetch('/api/memory/stats');
    const s = await r.json();
    document.getElementById('stat-sessions').textContent = s.total_sessions || 0;
    document.getElementById('stat-tool-calls').textContent = s.total_tool_calls || 0;
    document.getElementById('stat-facts').textContent = s.total_facts || 0;
  } catch(e) {}
}

async function searchMemory(query) {
  if (!query.trim()) { loadSessions(); return; }
  try {
    const r = await fetch('/api/memory/sessions/search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({query}),
    });
    const results = await r.json();
    const el = document.getElementById('session-list');
    if (!results.length) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;padding:8px;">No results for "' + escHtml(query) + '"</div>';
      return;
    }
    el.innerHTML = results.map(s => `
      <div style="padding:10px;border-bottom:1px solid var(--border);">
        <div style="font-size:0.85rem;color:var(--text);">${escHtml(s.preview || 'No preview')}</div>
        <div style="font-size:0.7rem;color:var(--text-dim);margin-top:4px;">${s.model || ''} &middot; ${s.message_count || 0} msgs</div>
      </div>
    `).join('');
  } catch(e) {}
}

function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
```

Also update the existing `switchTab` function to call `loadMemoryTab()` when the memory tab is activated:

Find the `switchTab` function and add a case:
```javascript
if (tab === 'memory') loadMemoryTab();
```

- [ ] **Step 4: Verify the page loads**

Run: `source ../../../venv/bin/activate && python -m api.main &`
Then: `curl -s http://localhost:8000/ | grep -c "memory"` — should return a count > 0
Kill the server.

- [ ] **Step 5: Commit**

```bash
git add api/static/index.html
git commit -m "feat: add Memory tab to dashboard with sessions, facts, and stats"
```

---

## Task 8: Final Integration Verification

**Files:** None (verification only)

- [ ] **Step 1: Run all tests**

```bash
source ../../../venv/bin/activate && python -m pytest tests/ -v --tb=short -k "not integration"
```
Expected: All tests pass

- [ ] **Step 2: Verify memory flow end-to-end**

```bash
source ../../../venv/bin/activate && python -m api.main &
sleep 3

# Pin a fact
curl -s -X POST http://localhost:8000/api/memory/facts \
  -H "Content-Type: application/json" \
  -d '{"content": "User prefers dolphin3 for coding", "tags": ["preferences"]}'

# List facts
curl -s http://localhost:8000/api/memory/facts | python -m json.tool

# Check active contexts
curl -s http://localhost:8000/api/context | python -m json.tool

# Get memory stats
curl -s http://localhost:8000/api/memory/stats | python -m json.tool

kill %1 2>/dev/null
```

- [ ] **Step 3: Rebuild DMG with memory features**

```bash
./scripts/build_mac.sh
```
Expected: DMG builds with new memory endpoints included

- [ ] **Step 4: Commit any fixes**

```bash
git add -A && git commit -m "chore: Phase 2 final integration verification"
```
