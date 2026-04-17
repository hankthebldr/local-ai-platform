# Phase 3: Virtualization Space — Profiles + Sandboxing

**Date**: 2026-04-15
**Status**: Approved
**Goal**: Govern what tools the agent can access (profiles) and contain what those tools can do (filesystem sandbox) — a two-layer security model on top of the existing plugin and tool-calling infrastructure.

## Overview

Phase 3 adds a policy + enforcement layer to the agentic harness:

1. **Profile System** — YAML-declared policies that control which plugins/tools are available per conversation. Denied tools are silently hidden from the LLM.
2. **Sandboxed Filesystem** — Per-conversation filesystem boundary. Tools use a `SandboxedFS` helper to read/write files; any escape attempt raises `SandboxViolation`.
3. **Integration** — Chat router resolves the active profile, filters the tool list, and passes a sandbox instance to the tool executor. Dashboard's Memory tab gains a read-only Profiles section.

---

## 1. Profile System

### File Format — `data/profiles/{profile_id}.yaml`

```yaml
id: "research"
name: "Research Profile"
description: "Web search and document analysis only"
version: "1.0.0"

# Plugins allowed for this profile
allowed_plugins:
  - "web-search"
  - "doc-analyzer"

# Per-plugin tool allowlists (omit to allow all tools in plugin)
tool_rules:
  web-search:
    allowed_tools: ["web_search"]
  doc-analyzer:
    allowed_tools: ["read_document", "extract_text"]

# Filesystem sandbox configuration
sandbox:
  mode: "strict"                              # strict | permissive | none
  root_dir: "data/sandboxes/{conversation_id}"
  max_file_size_mb: 10
  allowed_extensions: null                    # null = all; or ["txt", "md", "json"]

# Network policy (stubbed for now; enforced as warning)
network:
  mode: "unrestricted"
  allowed_hosts: []

# Optional API key binding
bound_to_keys: []
```

### Built-in Profiles

The platform ships with three profiles seeded in `data/profiles/`:

| Profile ID | Allowed Plugins | Sandbox Mode |
|------------|-----------------|--------------|
| `default` | All (wildcard) | strict |
| `research` | web-search, doc-analyzer | strict |
| `unrestricted` | All (wildcard) | none |

### Profile Resolution

On each chat request, the profile is resolved in priority order:

1. `X-Profile-ID` header (highest priority)
2. API key's `profile` field (if the request is authenticated and the key has one)
3. `DEFAULT_PROFILE` env var (default: `default`)

If the resolved profile doesn't exist, fall back to `default`. If `default` doesn't exist, fall back to `unrestricted` with a warning logged.

### Service — `api/services/profile_service.py`

| Method | Description |
|--------|-------------|
| `load_profiles()` | Scan `data/profiles/` and load all YAML files into memory |
| `get_profile(profile_id)` | Return profile dict or None |
| `list_profiles()` | All profiles with metadata |
| `resolve(header, key_id)` | Resolve active profile using priority order above |
| `filter_tools(ollama_tools, profile_id)` | Remove disallowed tools from a tool list |
| `is_tool_allowed(plugin_id, tool_id, profile_id)` | Runtime check for tool invocation |
| `reload()` | Hot-reload profiles from disk |

### Profile Router — `api/routers/profiles.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/profiles` | GET | List all loaded profiles |
| `/api/profiles/{id}` | GET | Full profile detail |
| `/api/profiles/reload` | POST | Re-scan `data/profiles/` |
| `/api/profiles/active` | GET | Return default profile ID |

Profiles are **not** created/edited via API — they live as YAML files on disk for inspectability and version control.

### Tool Filtering Semantics — Silent Hide

When a profile doesn't allow a plugin or tool:
- The tool is **omitted** from the `tools` array sent to Ollama
- The LLM never sees it exists
- If the LLM somehow calls a tool by name that's filtered out (e.g., from training data), the tool executor's defense-in-depth check returns an error result

---

## 2. Sandboxed Filesystem

### SandboxedFS — `api/services/sandbox_fs.py`

```python
class SandboxedFS:
    """Restricts filesystem access to a designated sandbox root."""

    def __init__(
        self,
        sandbox_root: str,
        max_file_size_mb: int = 10,
        allowed_extensions: list = None,
    ):
        self.root = Path(sandbox_root).resolve()
        self.max_file_size = max_file_size_mb * 1024 * 1024
        self.allowed_extensions = allowed_extensions
        self.root.mkdir(parents=True, exist_ok=True)

    def read(self, path: str, encoding: str = "utf-8") -> str: ...
    def write(self, path: str, content: str, encoding: str = "utf-8") -> None: ...
    def open(self, path: str, mode: str = "r", **kwargs): ...
    def exists(self, path: str) -> bool: ...
    def listdir(self, path: str = "") -> list: ...
    def delete(self, path: str) -> None: ...
    def get_absolute_path(self, relative_path: str) -> Path: ...
    def stats(self) -> dict:
        """Return size, file count, and usage for the sandbox."""
```

### Path Safety

`get_absolute_path(relative_path)` implements the security critical path resolution:

1. Strip leading `/` so absolute paths are treated as relative to root
2. Join with `self.root`
3. Call `.resolve()` to collapse `..` and symlinks
4. Assert that the resolved path has `self.root` as an ancestor
5. Raise `SandboxViolation` if the assertion fails

This blocks:
- `../../../etc/passwd` — resolves outside root
- `/etc/passwd` — joined as relative, resolves outside root
- Symlink escapes (a symlink inside root pointing outside)

### Size and Extension Enforcement

- `write()` checks `len(content.encode(encoding))` against `max_file_size` before writing
- If `allowed_extensions` is set, any path whose suffix isn't in the list raises `SandboxViolation`

### Exceptions

```python
class SandboxViolation(Exception):
    """Raised when a tool attempts to access outside the sandbox or violates a rule."""

class SandboxQuotaExceeded(Exception):
    """Raised when a tool exceeds size limits."""
```

Both subclass `Exception` (not `RuntimeError` — we want them distinguishable). The tool executor catches both and returns them as `{"error": "..."}` results to the LLM.

### Tool Access Pattern — Sandbox Injection

Tools opt in to sandboxing by accepting a `__sandbox` keyword parameter:

```python
# plugins/example-writer/tools/note_writer.py
def execute(filename: str, content: str, __sandbox=None) -> dict:
    if __sandbox is None:
        return {"error": "Sandbox required but not provided"}
    __sandbox.write(filename, content)
    return {"status": "written", "path": filename, "size": len(content)}
```

The plugin service inspects the tool function's signature via `inspect.signature()`. If the function accepts `__sandbox`, the plugin service injects the current sandbox instance when calling it. Tools that don't accept `__sandbox` don't get one (fully backward compatible with existing plugins that don't touch the filesystem).

### Per-Conversation Sandboxes

- Each conversation gets `data/sandboxes/{conversation_id}/`
- Created lazily on first tool call that uses `__sandbox`
- When the session is closed via `SessionManager.close_session`, the sandbox directory is **archived into the session YAML** as metadata (file list + sizes, not contents) and then the physical directory is deleted
- Directories older than 24 hours with no associated active context are garbage-collected by a periodic cleanup endpoint

---

## 3. Integration

### Tool Executor — Sandbox Injection + Defense-in-Depth

`ToolExecutor` gains:

```python
def set_policy(self, profile_service, profile_id, sandbox):
    self._profile_service = profile_service
    self._profile_id = profile_id
    self._sandbox = sandbox
```

Before each `self.plugins.call_tool()`:

1. Parse `tool_name` into `plugin_id, tool_id`
2. If `profile_service` is set, call `is_tool_allowed(plugin_id, tool_id, profile_id)`
3. If not allowed: set `tool_result = {"error": f"Tool '{tool_name}' not permitted by profile '{profile_id}'"}`
4. Otherwise: call the tool with the sandbox (passed through `plugin_service.call_tool`)

### Plugin Service — Sandbox Injection into Tool Calls

`PluginService.call_tool()` gains an optional `sandbox` parameter:

```python
def call_tool(self, plugin_id: str, tool_id: str, params: dict, sandbox=None) -> dict:
    ...
    # Inspect function signature — inject __sandbox only if the function accepts it
    sig = inspect.signature(func)
    if "__sandbox" in sig.parameters and sandbox is not None:
        params = {**params, "__sandbox": sandbox}
    return func(**params)
```

### Chat Router — Profile Resolution + Tool Filtering

In `chat_completions()`, after conversation context setup:

```python
# Resolve active profile
profile_id = req.headers.get("X-Profile-ID") \
    or _profile_for_key(req) \
    or os.getenv("DEFAULT_PROFILE", "default")

profile = _profile_service.get_profile(profile_id)
if profile is None:
    profile_id = "default"

# Record on context
ctx = _context_store.get(conversation_id)
if ctx:
    ctx.metadata["profile_id"] = profile_id

# Create sandbox for this conversation
sandbox_root = f"data/sandboxes/{conversation_id}"
sandbox_cfg = profile.get("sandbox", {}) if profile else {}
sandbox = None
if sandbox_cfg.get("mode") != "none":
    sandbox = SandboxedFS(
        sandbox_root=sandbox_root,
        max_file_size_mb=sandbox_cfg.get("max_file_size_mb", 10),
        allowed_extensions=sandbox_cfg.get("allowed_extensions"),
    )

# Wire into executor
_tool_executor.set_policy(_profile_service, profile_id, sandbox)
```

When building the tool list passed to Ollama:

```python
# The filtering happens inside the executor when it fetches tools
# so the LLM only sees permitted tools
```

Add `profile_id` to response dicts:

```python
response["profile_id"] = profile_id
```

### Context Store

`ConversationContext` already has a `metadata` dict. Profile ID is stored there as `metadata["profile_id"]`. No schema change needed.

### Session Manager — Sandbox Archive

`SessionManager.close_session()` gains:

```python
# After building the summary, if a sandbox dir exists, archive it
sandbox_dir = Path(f"data/sandboxes/{conversation_id}")
if sandbox_dir.exists():
    files = []
    for f in sandbox_dir.rglob("*"):
        if f.is_file():
            files.append({
                "path": str(f.relative_to(sandbox_dir)),
                "size": f.stat().st_size,
            })
    summary.metadata = summary.metadata or {}
    summary.metadata["sandbox_files"] = files
    # Remove the directory
    shutil.rmtree(sandbox_dir)
```

`SessionSummary` gains a `metadata: dict = field(default_factory=dict)` field.

### Dashboard — Profiles Section in Memory Tab

Add below the existing Session History / Pinned Facts grid:

```html
<div class="panel" style="border:1px solid var(--border);border-radius:8px;padding:16px;margin-top:16px;">
  <h3 style="color:var(--cyan);">Active Profile: <span id="active-profile">default</span></h3>
  <div id="profiles-list" style="margin-top:12px;"></div>
  <button onclick="reloadProfiles()" style="...">Reload Profiles</button>
</div>
```

JavaScript fetches `/api/profiles` and renders each profile as a collapsible card showing the YAML content (read-only). Clicking "Reload Profiles" calls `POST /api/profiles/reload`.

---

## Files to Create/Modify

### New Files

| File | Responsibility |
|------|---------------|
| `api/services/profile_service.py` | Profile loading, resolution, tool filtering |
| `api/services/sandbox_fs.py` | `SandboxedFS` class and exceptions |
| `api/routers/profiles.py` | Profile management endpoints |
| `data/profiles/default.yaml` | Default profile (all plugins, strict sandbox) |
| `data/profiles/research.yaml` | Research-only profile |
| `data/profiles/unrestricted.yaml` | Legacy compatibility (no sandbox, no restrictions) |
| `tests/test_profile_service.py` | Profile resolution and filtering tests |
| `tests/test_sandbox_fs.py` | Path traversal, size, extension tests |

### Modified Files

| File | Change |
|------|--------|
| `api/services/plugin_service.py` | Add optional `sandbox` parameter to `call_tool`, inject via `__sandbox` kwarg when tool signature accepts it |
| `api/services/tool_executor.py` | Add `set_policy()`, enforce profile rules before each tool call, pass sandbox through |
| `api/services/session_manager.py` | Archive and clean up sandbox directory on session close |
| `api/models/context_models.py` | Add `metadata` field to `SessionSummary` |
| `api/routers/chat.py` | Resolve profile, create sandbox, wire into executor, include `profile_id` in response |
| `api/main.py` | Register profiles router |
| `api/static/index.html` | Add Profiles section to Memory tab |
| `.env.example` | Add `DEFAULT_PROFILE=default` |

---

## Dependencies

No new Python dependencies. Uses `pathlib`, `inspect`, `shutil`, `yaml` (all stdlib or already installed).

---

## Out of Scope

- Network sandboxing (stubbed in profile YAML for future)
- Resource limits (CPU, memory, wall-clock per tool call)
- Subprocess/container isolation
- Profile creation/edit via API (YAML files only)
- UI for editing profiles (read-only display, edit via filesystem)
- Automatic profile suggestions based on conversation content
