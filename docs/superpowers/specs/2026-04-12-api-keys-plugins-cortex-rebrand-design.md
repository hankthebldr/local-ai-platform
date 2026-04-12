# API Key Management, Plugin System & Cortex Rebrand

**Date**: 2026-04-12
**Status**: Approved
**Approach**: Modular services (Approach 2)

## Overview

Three features for the local-ai-platform:

1. **API Key Management** — Multi-key creation/revocation with usage tracking, stored in YAML files
2. **Plugin System** — Unified skills (prompt augmentation) + tools (callable functions) with directory-convention discovery
3. **Cortex Color Rebrand** — Full replacement of cyberpunk theme with Palo Alto Networks Cortex green palette

---

## 1. API Key Management

### Data Model

Keys stored in `data/config/api_keys.yaml`:

```yaml
keys:
  - id: "key_abc123"
    name: "Development"
    key_hash: "<sha256 hash>"
    prefix: "sk-dev-"
    created_at: "2026-04-12T20:00:00Z"
    last_used_at: "2026-04-12T21:30:00Z"
    expires_at: null
    rate_limit_rpm: 60
    scopes: ["chat", "completions", "models"]
    enabled: true
    usage:
      total_requests: 1542
      total_tokens: 234567
```

### Key Format

Pattern: `sk-{name_slug}-{random_32_chars}` (e.g., `sk-dev-a1b2c3d4e5f6...`).

The full key is shown **once** at creation. Only the hash is stored. Display shows prefix + last 4 chars.

### Service Layer — `api/services/api_key_service.py`

| Method | Description |
|--------|-------------|
| `create_key(name, scopes, rate_limit, expires_at)` | Returns full key (only visible once) |
| `validate_key(raw_key)` | Returns key metadata or None |
| `revoke_key(key_id)` | Disables a key |
| `list_keys()` | Returns keys with masked values |
| `update_usage(key_id, tokens_used)` | Increments usage counters |
| `rotate_key(key_id)` | Revoke old, create new with same settings |

### Router — `api/routers/api_keys.py`

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `/api/keys` | POST | Create new key | Master key |
| `/api/keys` | GET | List all keys (masked) | Master key |
| `/api/keys/{id}` | DELETE | Revoke a key | Master key |
| `/api/keys/{id}/rotate` | POST | Rotate a key | Master key |
| `/api/keys/{id}/usage` | GET | Usage stats | Master key |

### Middleware Update

Upgrade `APIKeyAuthMiddleware` in `api/middleware.py`:
- Call `api_key_service.validate_key()` instead of simple string comparison
- Support per-key rate limits (override global default)
- Track `last_used_at` on each request
- Check `scopes` against the requested endpoint
- Check `expires_at` for expiration

### Master Key

`MASTER_API_KEY` env var controls access to key management endpoints. This is the only key in `.env`. All other keys managed via API/dashboard.

---

## 2. Plugin System

### Directory Structure

```
plugins/
├── example-web-search/
│   ├── plugin.yaml          # manifest (required)
│   ├── skills/
│   │   └── search-expert.md # skill file
│   └── tools/
│       └── web_search.py    # callable tool
├── example-code-runner/
│   ├── plugin.yaml
│   ├── skills/
│   │   └── code-review.md
│   └── tools/
│       └── run_code.py
└── _disabled/               # move plugins here to disable
```

### Plugin Manifest — `plugin.yaml`

```yaml
name: "Web Search"
id: "web-search"
version: "1.0.0"
description: "Adds web search capability to any conversation"
author: "local"

skills:
  - id: "search-expert"
    file: "skills/search-expert.md"
    triggers:
      - keyword: "search"
      - keyword: "find online"
      - manual: true

tools:
  - id: "web_search"
    file: "tools/web_search.py"
    function: "execute"
    description: "Search the web and return results"
    parameters:
      query:
        type: string
        required: true
      max_results:
        type: integer
        default: 5
```

### Skill Files (Markdown)

```markdown
---
name: Search Expert
description: Augments the LLM with web search best practices
inject: system
---

You have access to a web search tool. When the user asks about
current events or anything benefiting from live data, use the
`web_search` tool before answering.

Format search results with source attribution.
```

Injection modes: `system` (system prompt), `context` (user context), `none` (manual only).

### Tool Files (Python)

```python
# tools/web_search.py
def execute(query: str, max_results: int = 5) -> dict:
    """Search the web. Returns {results: [{title, url, snippet}]}"""
    return {"results": [...]}
```

Tools are plain Python functions. No base class required. The platform loads them via `importlib`, calls the declared `function` entry point, and passes declared parameters.

### Service Layer — `api/services/plugin_service.py`

| Method | Description |
|--------|-------------|
| `scan_plugins()` | Discover and validate all plugins in `plugins/` |
| `load_plugin(plugin_id)` | Load skills + import tool modules |
| `get_skills(triggers)` | Return matching skills for context |
| `call_tool(plugin_id, tool_id, params)` | Execute a tool function |
| `list_plugins()` | All discovered plugins with status |

### Router — `api/routers/plugins.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/plugins` | GET | List all plugins and status |
| `/api/plugins/{id}` | GET | Plugin details (skills, tools) |
| `/api/plugins/{id}/tools/{tool_id}` | POST | Invoke a tool directly |

### Chat Integration

The chat endpoint is updated to:
1. Check active plugins for matching skill triggers based on user message
2. Inject matched skills into the system prompt
3. Include tool definitions in the Ollama call (function/tool calling)
4. Execute tool calls from LLM responses and feed results back

### Security

- Tools run in-process (no sandbox in Phase 1)
- Only local `plugins/` directory is scanned — no remote install
- Tools cannot access internal services (api_key_service, etc.)
- File I/O restricted to the plugin's own directory + `data/`

---

## 3. Cortex Color Rebrand

Full replacement of CSS variables in `api/static/index.html`.

### Color Token Mapping

| Token | Old (Cyberpunk) | New (Cortex) | Role |
|-------|-----------------|--------------|------|
| `--bg-deep` | `#060a10` | `#0a0a0a` | Deepest background |
| `--bg` | `#0a0e14` | `#141414` | Primary dark bg |
| `--bg-panel` | `rgba(10,16,24,0.85)` | `rgba(20,20,20,0.9)` | Panel background |
| `--border` | `#1a2332` | `#2a2a2a` | Neutral border |
| `--cyan` (rename to `--primary`) | `#00d4ff` | `#00CC66` | Primary accent (Cortex Green) |
| `--amber` (rename to `--secondary`) | `#ff8c00` | `#19AA61` | Secondary green |
| `--green` (rename to `--success`) | `#00ff88` | `#00CC66` | Success state |
| `--red` (rename to `--danger`) | `#ff3366` | `#FA582D` | Error/danger (Cortex Orange) |
| `--purple` (rename to `--info`) | `#b388ff` | `#00C0E8` | Info accent (Cortex Cyan) |
| `--text` | `#d0dae8` | `#e0e0e0` | Primary text |
| `--text-dim` | `#556677` | `#8D8D8D` | Secondary text |
| `--text-muted` | `#334455` | `#555555` | Muted text |

### Dim Variants (40% opacity)

| Token | New Value |
|-------|-----------|
| `--primary-dim` | `#00CC6660` |
| `--secondary-dim` | `#19AA6160` |
| `--success-dim` | `#00CC6660` |
| `--danger-dim` | `#FA582D60` |
| `--info-dim` | `#00C0E860` |

### Glow Effects

| Token | New Value |
|-------|-----------|
| `--glow-primary` | `0 0 12px #00CC6630, 0 0 4px #00CC6620` |
| `--glow-success` | `0 0 12px #00CC6630, 0 0 4px #00CC6620` |
| `--glow-danger` | `0 0 12px #FA582D30, 0 0 4px #FA582D20` |
| `--glow-secondary` | `0 0 12px #19AA6130, 0 0 4px #19AA6120` |

### Gradient Updates

**Background gradient:**
```css
radial-gradient(ellipse 80% 50% at 20% 20%, #00CC6606 0%, transparent 60%),
radial-gradient(ellipse 60% 40% at 80% 80%, #19AA6104 0%, transparent 60%),
linear-gradient(180deg, var(--bg-deep) 0%, #141414 100%)
```

**Hero/CTA gradient:**
```css
linear-gradient(84deg, #05552D 13%, #19AA61 100%)
```

### Removals

- Remove grid overlay pattern (the 60px repeating lines)
- Remove scanline animation effect
- Remove magenta/purple from the palette entirely
- Simplify glow intensities for a cleaner corporate look

### Typography

Keep existing fonts (`JetBrains Mono` for code, `Space Grotesk` for headings) — they work well with the Cortex aesthetic.

---

## Files to Create/Modify

### New Files
- `api/services/api_key_service.py` — Key management service
- `api/routers/api_keys.py` — Key management endpoints
- `api/services/plugin_service.py` — Plugin discovery and loading
- `api/routers/plugins.py` — Plugin management endpoints
- `data/config/api_keys.yaml` — Key storage (created on first key creation)
- `plugins/` — Top-level plugin directory
- `plugins/example-web-search/plugin.yaml` — Example plugin manifest
- `plugins/example-web-search/skills/search-expert.md` — Example skill
- `plugins/example-web-search/tools/web_search.py` — Example tool

### Modified Files
- `api/main.py` — Register new routers, initialize plugin service on startup
- `api/middleware.py` — Upgrade auth middleware to use api_key_service
- `api/routers/chat.py` — Integrate plugin skills/tools into chat flow
- `api/static/index.html` — Full CSS variable replacement + remove effects
- `.env.example` — Add `MASTER_API_KEY`

---

## Dependencies

No new Python dependencies required. Uses only stdlib:
- `hashlib` for key hashing
- `secrets` for key generation
- `importlib` for dynamic tool loading
- `yaml` (already installed) for config files
