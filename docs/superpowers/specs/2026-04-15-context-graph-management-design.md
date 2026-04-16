# Phase 2: Context Graph Management

**Date**: 2026-04-15
**Status**: Approved
**Goal**: Give the agent persistent memory — track tool usage per conversation, auto-summarize sessions, let users pin facts, persist across sessions, and manage everything from a dashboard tab.

## Overview

Four sub-phases building on each other:

1. **Tool state tracking** — Per-conversation context recording what tools were called, with what params, and what came back
2. **Agent memory** — Auto-generated conversation summaries + user-pinnable facts
3. **Multi-session persistence** — YAML/JSON file storage in `data/memory/`, loaded on conversation start
4. **Management UI** — Memory tab in the existing Cortex dashboard

---

## 1. Tool State Tracking

### Data Model — `ConversationContext`

```python
@dataclass
class ToolCall:
    tool_name: str           # e.g. "web-search__web_search"
    arguments: dict          # what was passed
    result: dict             # what came back
    timestamp: str           # ISO 8601
    iteration: int           # which loop iteration
    duration_ms: int         # how long the call took

@dataclass
class ConversationContext:
    conversation_id: str     # UUID, generated on first message
    model: str               # which model is being used
    started_at: str          # ISO 8601
    last_activity: str       # ISO 8601, updated on each message
    message_count: int       # total messages exchanged
    tool_calls: list[ToolCall]  # all tool calls in this conversation
    skills_injected: list[str]  # skill IDs that were triggered
    metadata: dict           # extensible key-value (model, temperature, etc.)
```

### ContextStore Service — `api/services/context_store.py`

In-memory store keyed by `conversation_id`. The chat router generates a conversation ID on the first request (or accepts one from the client via a header).

| Method | Description |
|--------|-------------|
| `create(conversation_id, model)` | Initialize a new conversation context |
| `get(conversation_id)` | Return the current context |
| `record_tool_call(conversation_id, tool_call)` | Append a tool call to the context |
| `record_skill(conversation_id, skill_id)` | Record which skills were injected |
| `update_activity(conversation_id)` | Bump last_activity and message_count |
| `list_active()` | Return all active (non-persisted) conversations |

### Integration Points

- **ToolExecutor**: After each tool call in the loop, call `context_store.record_tool_call()`
- **Chat Router**: On each request, call `context_store.update_activity()`. Generate `conversation_id` if not provided via `X-Conversation-ID` header.
- **Plugin skill injection**: Record which skills matched via `context_store.record_skill()`

### API Endpoints — `api/routers/context.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/context` | GET | List all active conversations with summary |
| `/api/context/{id}` | GET | Full context for a conversation |
| `/api/context/{id}/tool-calls` | GET | Just the tool calls for a conversation |

---

## 2. Agent Memory

### Conversation Summary (Auto-Generated)

When a conversation ends (no activity for 5 minutes, or client sends a close signal), the system auto-generates a summary from metadata — no LLM call required:

```yaml
id: "conv_abc123"
model: "dolphin3:latest"
started_at: "2026-04-15T14:30:00Z"
ended_at: "2026-04-15T14:45:00Z"
duration_minutes: 15
message_count: 12
tool_calls_count: 3
tools_used: ["web-search__web_search"]
skills_triggered: ["search-expert"]
topics: []  # extracted from message content via keyword frequency (reuse graph_service logic)
preview: "First user message text (truncated to 200 chars)..."
```

Topics are extracted using the existing `_extract_topics()` function from `api/services/graph_service.py` — no new dependency.

### Pinned Facts (User-Created)

Users can pin facts from the dashboard. Facts are key-value pairs with optional tags:

```yaml
facts:
  - id: "fact_xyz789"
    content: "User prefers dolphin3 for coding tasks"
    tags: ["preferences", "models"]
    created_at: "2026-04-15T14:40:00Z"
    source_conversation: "conv_abc123"  # optional, which conversation it came from
    pinned_by: "user"                   # "user" or "auto" (future)
```

### Memory Injection

On each new conversation, the memory service:
1. Loads all pinned facts
2. Formats them as a system message: `"User memory: {fact1}. {fact2}. ..."`
3. Prepends to the message list (before skill injection)

This is lightweight — just string concatenation, no LLM call.

### Memory Service — `api/services/memory_service.py`

| Method | Description |
|--------|-------------|
| `save_session(conversation_context)` | Persist a completed conversation summary |
| `list_sessions(limit, offset)` | List saved sessions with summaries |
| `get_session(session_id)` | Full session detail |
| `delete_session(session_id)` | Remove a session from memory |
| `add_fact(content, tags, source_conversation)` | Pin a new fact |
| `list_facts()` | All pinned facts |
| `delete_fact(fact_id)` | Remove a pinned fact |
| `get_injection_context()` | Format facts for system prompt injection |
| `search_sessions(query)` | Keyword search across session summaries and topics |

---

## 3. Multi-Session Persistence

### File Structure

```
data/memory/
├── sessions/
│   ├── conv_abc123.yaml       # one file per conversation
│   ├── conv_def456.yaml
│   └── ...
├── facts.yaml                 # all pinned facts
└── index.yaml                 # session index (lightweight, for fast listing)
```

### Session File Format (`data/memory/sessions/conv_abc123.yaml`)

```yaml
id: "conv_abc123"
model: "dolphin3:latest"
started_at: "2026-04-15T14:30:00Z"
ended_at: "2026-04-15T14:45:00Z"
duration_minutes: 15
message_count: 12
tool_calls_count: 3
tools_used:
  - "web-search__web_search"
skills_triggered:
  - "search-expert"
topics:
  - "quantum computing"
  - "physics"
preview: "Tell me about quantum computing..."
tool_calls:
  - tool_name: "web-search__web_search"
    arguments: {query: "quantum computing basics"}
    result: {results: [...]}
    timestamp: "2026-04-15T14:32:00Z"
    iteration: 1
    duration_ms: 1200
```

### Index File (`data/memory/index.yaml`)

Lightweight index for fast listing without reading every session file:

```yaml
sessions:
  - id: "conv_abc123"
    model: "dolphin3:latest"
    started_at: "2026-04-15T14:30:00Z"
    duration_minutes: 15
    message_count: 12
    tool_calls_count: 3
    preview: "Tell me about quantum computing..."
    topics: ["quantum computing", "physics"]
```

### Facts File (`data/memory/facts.yaml`)

```yaml
facts:
  - id: "fact_xyz789"
    content: "User prefers dolphin3 for coding tasks"
    tags: ["preferences", "models"]
    created_at: "2026-04-15T14:40:00Z"
    source_conversation: "conv_abc123"
```

### Lifecycle

1. **Conversation starts** → `ContextStore.create()` — in-memory only
2. **During conversation** → Tool calls, skills, messages recorded in memory
3. **Conversation ends** (5 min inactivity or explicit close) → `MemoryService.save_session()` writes YAML + updates index
4. **New conversation starts** → `MemoryService.get_injection_context()` loads facts for system prompt

### API Endpoints — `api/routers/memory.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/memory/sessions` | GET | List all saved sessions (from index) |
| `/api/memory/sessions/{id}` | GET | Full session detail with tool calls |
| `/api/memory/sessions/{id}` | DELETE | Delete a session |
| `/api/memory/sessions/search` | POST | Search sessions by keyword |
| `/api/memory/facts` | GET | List all pinned facts |
| `/api/memory/facts` | POST | Pin a new fact |
| `/api/memory/facts/{id}` | DELETE | Delete a fact |
| `/api/memory/stats` | GET | Memory stats (total sessions, facts, tool calls) |

---

## 4. Management UI — Memory Tab

### Dashboard Integration

Add a "Memory" tab to the existing tab bar in `api/static/index.html`. The tab contains three panels:

**Panel 1: Session History**
- Scrollable list of past conversations
- Each entry shows: preview text, model, date, duration, tool call count, topic tags
- Click to expand → shows full tool call timeline
- Delete button per session

**Panel 2: Pinned Facts**
- List of user-pinned facts with tags
- "Add Fact" button → inline input with tag selector
- Delete button per fact
- Facts are injected into every new conversation

**Panel 3: Memory Stats**
- Total sessions, total tool calls, total facts
- Most-used tools (bar chart or simple list)
- Most-used models
- Storage size

### Search

A search bar at the top of the Memory tab that searches across:
- Session previews and topics
- Pinned fact content and tags

Results are highlighted and filterable.

---

## Files to Create/Modify

### New Files

| File | Responsibility |
|------|---------------|
| `api/models/context_models.py` | Pydantic/dataclass models for ToolCall, ConversationContext, SessionSummary, Fact |
| `api/services/context_store.py` | In-memory per-conversation context tracking |
| `api/services/memory_service.py` | Session persistence, fact management, memory injection |
| `api/routers/context.py` | Active conversation context endpoints |
| `api/routers/memory.py` | Persisted session and fact management endpoints |
| `tests/test_context_store.py` | Context tracking tests |
| `tests/test_memory_service.py` | Memory persistence and search tests |

### Modified Files

| File | Change |
|------|--------|
| `api/main.py` | Register context and memory routers |
| `api/services/tool_executor.py` | Record tool calls to context store |
| `api/routers/chat.py` | Generate conversation_id, inject memory, record activity |
| `api/static/index.html` | Add Memory tab with session history, facts, stats, search |

---

## Dependencies

No new Python dependencies. Uses:
- `yaml` (already installed) for persistence
- `dataclasses` (stdlib) for models
- `uuid` (stdlib) for conversation IDs
- Existing `_extract_topics()` from `graph_service.py` for topic extraction

---

## Out of Scope

- LLM-based fact extraction (future enhancement, not Phase 2)
- Semantic/vector search across memories (Phase 3 with ChromaDB)
- Memory sharing across machines/users
- Conversation message persistence (only metadata + tool calls persisted, not full message history)
