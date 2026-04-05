# Session Export & Knowledge Graph — Design Doc

**Date:** 2026-03-30
**Status:** Approved for Phase 1 (MD export), Phase 2 (graph) to be designed after Phase 1 ships

## Problem

Chat sessions exist only in browser memory — lost on refresh. No way to save, search, or reuse past conversations. The platform needs session persistence as Markdown artifacts, which later feed into a knowledge graph for context injection.

## Phase 1: Markdown Export to Disk

### Scope

- Manual export button in chat UI
- Generates rich Markdown with metadata (model, timestamps, tokens, sources)
- Browser download + server-side save to `data/exports/`
- Server API to list/read past exports from the dashboard

### Architecture

Frontend generates the Markdown (it already has all the data), downloads it, and POSTs a copy to the server.

```
[Export Button] → JS generates .md string
                    ├→ Browser download (instant)
                    └→ POST /api/exports/save (fire-and-forget)
                         └→ Saves to data/exports/YYYY-MM-DD-HHmm-{model}.md
```

### Markdown Format

```markdown
# Chat Session — 2026-03-30 12:45

| Field | Value |
|-------|-------|
| Model | dolphin3:latest |
| Duration | 8m 32s |
| Messages | 6 |
| Total Tokens | 1,847 |
| Web Search | Enabled |

---

## User
What is the latest news about local AI models?

## Assistant
Based on recent developments [1], local AI models have...

### Sources
1. [AI Trends 2026](https://example.com) — Summary text...

---

## User
Tell me more

## Assistant
...
```

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `POST /api/exports/save` | POST | Save session markdown to disk |
| `GET /api/exports` | GET | List saved exports (newest first) |
| `GET /api/exports/{filename}` | GET | Read a specific export |
| `DELETE /api/exports/{filename}` | DELETE | Remove an export |

### Frontend Changes

- Export button (download icon) in chat header, next to model selector
- Tracks per-message metadata: timestamp, token usage, sources
- Generates Markdown client-side from enriched chatHistory
- On click: browser download + POST to server

### Files to Create/Modify

- **NEW:** `api/routers/exports.py` — Export CRUD endpoints
- **MODIFY:** `api/main.py` — Register exports router
- **MODIFY:** `api/static/index.html` — Export button, enriched chat state, MD generation
- **NEW:** `tests/test_exports.py` — Export endpoint tests

## Phase 2: Knowledge Graph (Future — design after Phase 1 ships)

### Direction

Once sessions are saved as .md files, the next step is making them searchable and reusable:

1. Chunk exported sessions and embed into ChromaDB
2. Before inference, search past sessions for relevant context
3. Inject matched context as system message (RAG pattern)
4. Dashboard visualization of session topics and connections

Phase 2 design will be written after Phase 1 is validated in use.
