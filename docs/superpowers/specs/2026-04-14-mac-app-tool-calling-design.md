# Phase 1: Mac App + Tool-Calling Loop

**Date**: 2026-04-14
**Status**: Approved
**Goal**: Produce a demo-ready macOS DMG that bundles the Local AI Platform as a native app with agentic tool-calling capabilities.

## Overview

Two deliverables in one phase:

1. **Tool-calling loop** — The LLM can invoke plugin tools mid-conversation, receive results, and iterate. Converts the chat from a simple Q&A into an agentic experience.
2. **Mac app packaging** — PyWebView-based `.app` bundle with bundled Python runtime and Ollama installer, packaged as a DMG. First-run setup wizard handles Ollama installation and model download.

Future phases (separate specs):
- Phase 2: Context graph management
- Phase 3: Virtualization space with permissions

---

## 1. Tool-Calling Loop

### Data Flow

```
User message
    |
Chat endpoint receives request
    |
Plugin skills injected into system prompt (existing)
    |
Tool definitions from plugins converted to Ollama tools format
    |
LLM called with messages + tools
    |
+-- Response has tool_calls? --- YES --> Execute tool via plugin_service.call_tool()
|                                           |
|                                      Append tool result as message
|                                           |
|                                      Call LLM again (loop) <--- max 10 iterations
|
+-- NO (normal text) ---------> Return to user
```

### Ollama Tool Format

Plugin tools declared in `plugin.yaml`:
```yaml
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

Converted to Ollama's `tools` parameter format:
```json
{
  "type": "function",
  "function": {
    "name": "web-search__web_search",
    "description": "Search the web and return results",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {"type": "string"},
        "max_results": {"type": "integer", "default": 5}
      },
      "required": ["query"]
    }
  }
}
```

Tool names are namespaced as `{plugin_id}__{tool_id}` to avoid collisions.

### Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_tool_iterations` | 10 | Max tool-call rounds per request |
| `tool_timeout` | 30 | Seconds per individual tool call |
| Request timeout | 300 | Overall request timeout (existing) |

`max_tool_iterations` is configurable per request via the chat completion body.

### Error Handling

- **Tool throws exception**: Error message sent back to the LLM as a tool result (`{"error": "..."}`) so it can recover or try a different tool.
- **Tool times out**: Treated as an error result, LLM informed.
- **Max iterations reached**: Loop stops, last LLM response returned to user with a warning flag.
- **Model doesn't support tools**: Fall back to current behavior (skills injected, no tool loop). Log a warning.

### Streaming Support

When `stream: true`:
- Tool-call chunks are emitted as SSE events so the client can show "calling web_search..."
- Tool results are emitted as custom SSE events
- Final text response streams normally

### Service Layer — `api/services/tool_executor.py`

| Method | Description |
|--------|-------------|
| `convert_plugin_tools(plugins)` | Convert plugin tool definitions to Ollama tools format |
| `execute_tool_loop(messages, tools, model, temperature, max_tokens, max_iterations)` | Run the iterative tool-call loop, return final response |
| `execute_single_tool(plugin_id, tool_id, params, timeout)` | Call a single tool with timeout |

### Modified Files

- `api/routers/chat.py` — Add `tools` param to Ollama calls, integrate tool executor loop
- `api/services/plugin_service.py` — Add `get_ollama_tools()` method that returns tools in Ollama format
- `api/services/ollama_service.py` — Ensure `chat()` and `chat_stream()` accept `tools` parameter

### Chat Request Model Update

```python
class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 2048
    stream: Optional[bool] = False
    web_search: Optional[bool] = False
    tools: Optional[bool] = True          # NEW: enable/disable tool calling
    max_tool_iterations: Optional[int] = 10  # NEW: cap iterations
```

---

## 2. Mac App Wrapper

### App Bundle Structure

```
LocalAIPlatform.app/
  Contents/
    MacOS/
      LocalAIPlatform          # py2app entry point
    Resources/
      python/                  # Bundled Python 3.x + pip dependencies
      app/                     # Platform code (api/, cli/, models/, plugins/)
      icon.icns                # App icon (Cortex green)
    Info.plist
```

### Lifecycle

1. **Launch** — `desktop/app.py` runs
2. **First-run check** — If `~/.local-ai-platform/setup_complete` missing, open `/setup`
3. **Start server** — Spawn uvicorn in daemon thread on `127.0.0.1:8000`
4. **Wait for ready** — Poll `/health` until server responds
5. **Open window** — PyWebView native window at `http://127.0.0.1:8000` (or `/setup`)
6. **Quit** — Window close → server thread dies (daemon) → process exits

### Entry Point — `desktop/app.py`

```python
import os
import sys
import time
import threading
import webview
import uvicorn
import requests

APP_DIR = os.path.expanduser("~/.local-ai-platform")
SETUP_FLAG = os.path.join(APP_DIR, "setup_complete")
PORT = 8000


def start_server():
    """Start FastAPI in a background thread."""
    # Add app directory to path so api module is importable
    app_root = os.path.join(os.path.dirname(__file__), "app")
    sys.path.insert(0, app_root)
    uvicorn.run("api.main:app", host="127.0.0.1", port=PORT, log_level="warning")


def wait_for_server(timeout=15):
    """Block until the server is ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"http://127.0.0.1:{PORT}/health", timeout=1)
            if r.status_code == 200:
                return True
        except requests.ConnectionError:
            time.sleep(0.3)
    return False


def main():
    os.makedirs(APP_DIR, exist_ok=True)

    server = threading.Thread(target=start_server, daemon=True)
    server.start()
    wait_for_server()

    url = f"http://127.0.0.1:{PORT}"
    if not os.path.exists(SETUP_FLAG):
        url += "/setup"

    webview.create_window(
        "Local AI Platform",
        url,
        width=1200,
        height=800,
        min_size=(900, 600),
    )
    webview.start()


if __name__ == "__main__":
    main()
```

### Build Pipeline — `scripts/build_mac.sh`

```bash
#!/bin/bash
# 1. Install build dependencies
pip install py2app pywebview

# 2. Run py2app
python desktop/setup.py py2app

# 3. Create DMG
create-dmg \
    --volname "Local AI Platform" \
    --window-size 600 400 \
    --icon "LocalAIPlatform.app" 150 200 \
    --app-drop-link 450 200 \
    "dist/LocalAIPlatform.dmg" \
    "dist/LocalAIPlatform.app"
```

### py2app Config — `desktop/setup.py`

```python
from setuptools import setup

APP = ["desktop/app.py"]
DATA_FILES = [
    ("app/api", ["api/"]),
    ("app/plugins", ["plugins/"]),
]
OPTIONS = {
    "argv_emulation": False,
    "includes": ["uvicorn", "fastapi", "pydantic", "yaml", "requests", "webview"],
    "iconfile": "desktop/icon.icns",
    "plist": {
        "CFBundleName": "Local AI Platform",
        "CFBundleIdentifier": "com.localai.platform",
        "CFBundleVersion": "1.0.0",
        "LSMinimumSystemVersion": "12.0",
    },
}

setup(app=APP, data_files=DATA_FILES, options={"py2app": OPTIONS}, setup_requires=["py2app"])
```

---

## 3. First-Run Setup Wizard

### Route — `api/routers/setup.py`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/setup` | GET | Serve setup wizard HTML |
| `/api/setup/check-ollama` | GET | Check if Ollama is reachable |
| `/api/setup/install-ollama` | POST | Copy bundled Ollama.app to /Applications, launch it |
| `/api/setup/pull-model` | POST | Proxy Ollama pull with streaming progress |
| `/api/setup/complete` | POST | Write setup_complete flag, redirect to dashboard |

### Wizard Steps

**Step 1: Welcome**
- "Welcome to Local AI Platform"
- Brief description: "Your private AI, running locally."
- [Get Started] button

**Step 2: Ollama Setup**
- Auto-check: `GET /api/setup/check-ollama`
- If running: "Ollama detected" with green checkmark, auto-advance
- If binary exists but not running: Start it automatically
- If not installed:
  - "Installing Ollama..." with progress indicator
  - `POST /api/setup/install-ollama` runs `curl -fsSL https://ollama.com/install.sh | sh` via subprocess
  - Captures install output and streams progress to the wizard UI
  - Starts `ollama serve` if not already running
  - Polls `localhost:11434` until responsive
  - "Ollama installed" with green checkmark

**Step 3: Model Selection**
- Show 3-4 recommended models:

| Model | Size | Speed | Description |
|-------|------|-------|-------------|
| dolphin3:8b | 4.9 GB | ~40 tok/s | Fast, uncensored daily driver |
| qwen2.5:14b | 9 GB | ~25 tok/s | Balanced quality/speed |
| deepseek-r1:32b | 19 GB | ~10 tok/s | Best reasoning |

- User selects one (or more)
- [Download] triggers `POST /api/setup/pull-model` with SSE progress
- Progress bar shows download percentage

**Step 4: Complete**
- "You're all set!"
- `POST /api/setup/complete` writes `~/.local-ai-platform/setup_complete`
- [Open Dashboard] redirects to `/`

### Ollama Installation Logic

```python
import subprocess
import shutil
import time
import requests

def install_ollama():
    """Install Ollama via official CLI installer and start the service."""
    # Check if already installed
    if shutil.which("ollama"):
        return {"status": "already_installed"}

    # Run the official installer
    result = subprocess.run(
        ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        return {"status": "error", "detail": result.stderr}

    # Start ollama serve if not already running
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Wait for service to be ready
    for _ in range(30):
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=1)
            if r.status_code == 200:
                return {"status": "installed"}
        except requests.ConnectionError:
            time.sleep(1)

    return {"status": "error", "detail": "Ollama installed but service didn't start"}
```

### UI

- `api/static/setup.html` — Single-page wizard with step transitions
- Uses the same Cortex design tokens (--bg, --cyan, etc.)
- Clean, minimal layout — no grid overlay or effects
- Progress bars for downloads
- JavaScript handles step transitions and API calls

---

## Files to Create/Modify

### New Files

| File | Responsibility |
|------|---------------|
| `api/services/tool_executor.py` | Tool format conversion, tool-call loop |
| `api/routers/setup.py` | Setup wizard endpoints |
| `api/static/setup.html` | Setup wizard UI |
| `desktop/app.py` | PyWebView entry point with server lifecycle |
| `desktop/setup.py` | py2app build configuration |
| `desktop/icon.icns` | App icon |
| `scripts/build_mac.sh` | Build pipeline: py2app → bundle Ollama → DMG |
| `tests/test_tool_executor.py` | Tool-calling loop tests |
| `tests/test_setup.py` | Setup wizard endpoint tests |

### Modified Files

| File | Change |
|------|--------|
| `api/main.py` | Register setup router |
| `api/routers/chat.py` | Integrate tool executor loop |
| `api/services/plugin_service.py` | Add `get_ollama_tools()` method |
| `api/services/ollama_service.py` | Accept `tools` parameter in chat methods |
| `setup/requirements.txt` | Add `pywebview`, `py2app` |

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `pywebview` | Native macOS window for the dashboard |
| `py2app` | Bundle Python app as macOS .app |
| `create-dmg` | Package .app into DMG (brew install) |

---

## DMG Contents

```
LocalAIPlatform.dmg
  ├── LocalAIPlatform.app    (~50 MB, bundled Python + platform)
  └── Background.png         (drag-to-Applications artwork)
```

Total DMG size: ~50-80 MB (Ollama installed via CLI at first run)

---

## Out of Scope (Future Phases)

- Context graph management (Phase 2)
- Virtualization space with tool permissions (Phase 3)
- Auto-update mechanism
- Code signing / notarization (needed for distribution outside the team)
- Windows/Linux packaging
