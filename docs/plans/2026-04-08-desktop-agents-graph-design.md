# Design: macOS Desktop App, Custom Agents, Context Graph

**Date:** 2026-04-08
**Status:** Approved
**Scope:** Three interconnected features for the Local AI Platform

---

## 1. macOS Desktop App (`desktop/`)

### Architecture
- **pywebview** for native WKWebView window (uses system WebKit, no bundled browser)
- **py2app** for .app bundle creation
- Existing FastAPI server runs as a background thread — zero changes to `api/`

### Files
| File | Purpose |
|------|---------|
| `desktop/app.py` | Launcher: Ollama lifecycle → uvicorn thread → WKWebView window |
| `desktop/setup_app.py` | py2app configuration (icon, plist, bundled packages) |
| `desktop/build.sh` | Build automation: venv → py2app → codesign → DMG |
| `desktop/entitlements.plist` | Code signing entitlements (network, unsigned memory) |
| `desktop/icon.icns` | App icon (Cortex hex gradient) |

### Lifecycle
1. App launches → `ensure_ollama()` checks port 11434, starts Ollama if needed
2. Picks a random available port for FastAPI
3. Starts uvicorn in a daemon thread
4. Opens WKWebView window at `http://127.0.0.1:{port}`
5. On window close → stops uvicorn, terminates Ollama (only if we started it)

### Key Decisions
- Random port avoids conflicts with dev server on 8000
- Ollama management is best-effort (works if already running, starts if not)
- py2app standalone mode bundles Python runtime (~25MB total)
- No auto-updater in v1 (future enhancement)

---

## 2. Custom Agent/Gem Builder

### Concept
Local alternative to Claude Gems / OpenAI GPTs. Users create reusable agent personas with system prompts, pinned context, model preferences, and tool access. Agents are YAML files on disk — the UI creates/edits YAML, and hand-authored YAML works identically.

### Data Model (`api/models/agent_models.py`)

```python
class ContextSource(BaseModel):
    type: Literal["file", "url", "graph_query", "workflow_output", "text"]
    value: str                    # path, URL, query, or inline text
    label: Optional[str] = None   # display name

class AgentTool(BaseModel):
    type: Literal["web_search", "workflow", "code_exec"]
    config: Dict[str, Any] = {}   # e.g., {"workflow_id": "xsiam-data-model-rules"}

class AgentDefinition(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None            # emoji or icon name
    model: Optional[str] = None           # explicit model
    role: Optional[str] = None            # role-based resolution
    system_prompt: str
    context: List[ContextSource] = []
    starters: List[str] = []              # conversation starters
    tools: List[AgentTool] = []
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    tags: List[str] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

### YAML Format (`agents/*.yaml`)
```yaml
id: xsiam-analyst
name: "XSIAM Data Model Analyst"
icon: "🛡️"
model: deepseek-r1:32b
system_prompt: |
  You are a Palo Alto Networks Cortex XSIAM data model specialist.
  You help security engineers create data model rules, parsing rules,
  and correlation rules for log source onboarding.
context:
  - type: file
    value: workflows/xsiam-data-model-rules.yaml
    label: "XSIAM workflow definition"
  - type: graph_query
    value: "xsiam OR xdr OR normalization"
    label: "Related knowledge graph nodes"
starters:
  - "Analyze these log samples and generate XDM mappings"
  - "What XDM fields are needed for brute force detection?"
  - "Review my data model rules for completeness"
tools:
  - type: web_search
  - type: workflow
    config:
      workflow_id: xsiam-data-model-rules
tags: ["security", "xsiam", "cortex"]
```

### Service Layer (`api/services/agent_service.py`)

**Core operations:**
- `list_agents()` — scan `agents/` directory for YAML files
- `get_agent(id)` — load and parse single agent YAML
- `create_agent(defn)` — write YAML to `agents/{id}.yaml`
- `update_agent(id, defn)` — overwrite YAML
- `delete_agent(id)` — remove YAML file
- `resolve_context(agent)` — resolve all context sources at chat time:
  - `file` → read file content
  - `url` → fetch URL (cached)
  - `graph_query` → search knowledge graph for matching nodes
  - `workflow_output` → load latest workflow run artifacts
  - `text` → inline text
- `build_messages(agent, user_messages)` — construct full message array:
  1. System message (agent's system_prompt)
  2. Context block (resolved context sources as structured data)
  3. User conversation history

### API Endpoints (`api/routers/agents.py`)
```
GET    /api/agents              — List all agents
GET    /api/agents/{id}         — Get agent definition
POST   /api/agents              — Create agent (returns YAML path)
PUT    /api/agents/{id}         — Update agent
DELETE /api/agents/{id}         — Delete agent
POST   /api/agents/{id}/chat    — Chat with agent (injects context + system prompt)
GET    /api/agents/{id}/context — Preview resolved context
```

### Dashboard UI — Agents Tab
- **Agent gallery** — grid of agent cards with icon, name, description, model badge
- **Agent builder** — form to create/edit: name, system prompt (code editor), context sources (drag-drop), model selector, starters, tools
- **Quick chat** — click agent card → opens chat panel with agent's persona pre-loaded
- **Import/Export** — download agent as YAML, upload YAML to create

---

## 3. Enhanced Context Graph

### Current State
- D3.js force graph with session, topic, and source nodes
- Basic rebuild from session exports
- No filtering, no agent integration, no workflow integration

### Enhancements

**New node types:**
| Type | Color | Source |
|------|-------|--------|
| Session | Cortex Green | Existing — from `data/exports/` |
| Topic | PANW Grey | Existing — extracted from sessions |
| Source | Prisma Blue | Existing — URLs/domains from sessions |
| Agent | Orange | NEW — from `agents/*.yaml` |
| Workflow Run | Purple | NEW — from `data/workflows/*/run.json` |

**New link types:**
| Link | Meaning |
|------|---------|
| agent → topic | Agent's context query matches topic |
| agent → source | Agent has file/URL context source |
| workflow_run → topic | Workflow output contains topic keywords |
| workflow_run → agent | Workflow was triggered by an agent |

**Interactive features:**
- **Search bar** — filter nodes by name, type, date
- **Type toggles** — show/hide each node type
- **Context selection mode** — Shift+click nodes → "Use as context" button → creates a new agent context source or injects into current chat
- **Node detail panel** — click node → shows full content, related nodes, actions
- **Subgraph zoom** — double-click topic cluster → zooms to subgraph

**Graph service updates (`api/services/graph_service.py`):**
- `build_graph()` now also scans `agents/` and `data/workflows/`
- Agent nodes link to topics via their `context[].graph_query` values
- Workflow run nodes link to topics via output keyword extraction
- Incremental update support (add nodes without full rebuild)

---

## Integration Points

### Agent ↔ Graph
- Agent `context.type: graph_query` → resolved via `graph_service.search_nodes(query)`
- Creating an agent from graph → select nodes, auto-generate context sources
- Graph shows which agents consume which topics/sources

### Agent ↔ Workflow
- Agent `tools.type: workflow` → agent can trigger workflow execution
- Workflow results feed back into agent context on next chat turn
- Graph links workflow runs to the agent that triggered them

### Desktop ↔ Everything
- Desktop app wraps the same dashboard — no feature differences
- All features work identically in browser and in the native app

---

## Implementation Order

### Phase 1: Agent System (backend + API)
1. `api/models/agent_models.py` — Pydantic models
2. `api/services/agent_service.py` — CRUD + context resolution
3. `api/routers/agents.py` — REST endpoints
4. `agents/xsiam-analyst.yaml` — example agent
5. Tests

### Phase 2: Agents Tab (dashboard UI)
6. Agent gallery (list, cards)
7. Agent builder form (create/edit)
8. Agent chat integration (chat with agent persona)

### Phase 3: Enhanced Context Graph
9. Graph service updates (agent + workflow nodes)
10. Graph UI enhancements (search, filter, context selection)
11. Agent ↔ graph integration (resolve graph_query context)

### Phase 4: macOS Desktop App
12. `desktop/app.py` launcher
13. `desktop/setup_app.py` py2app config
14. `desktop/build.sh` automation
15. Icon generation
16. Test build on M4 Pro
