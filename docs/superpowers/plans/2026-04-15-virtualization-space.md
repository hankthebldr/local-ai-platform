# Phase 3: Virtualization Space — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add policy + enforcement layers to the agentic harness — YAML profiles govern which plugins/tools are available per conversation, and a per-conversation filesystem sandbox contains what those tools can do.

**Architecture:** Two new services (`ProfileService` for policy, `SandboxedFS` for enforcement) plugged into the existing tool-calling pipeline. Chat router resolves the active profile on each request, filters the tool list before the LLM sees it (silent hide), and passes a sandbox instance to the tool executor. Tools opt in to sandboxing via a `__sandbox` kwarg; the plugin service injects it using `inspect.signature` introspection.

**Tech Stack:** Python 3, FastAPI, PyYAML, `pathlib`, `inspect`, `shutil` (all stdlib or already installed)

**Spec:** `docs/superpowers/specs/2026-04-15-virtualization-space-design.md`

---

## File Map

### New Files
| File | Responsibility |
|------|---------------|
| `api/services/sandbox_fs.py` | `SandboxedFS` class + `SandboxViolation`/`SandboxQuotaExceeded` exceptions |
| `api/services/profile_service.py` | Profile loading, resolution, tool filtering, runtime checks |
| `api/routers/profiles.py` | GET list/detail, POST reload, GET active |
| `data/profiles/default.yaml` | Built-in default profile (all plugins, strict sandbox) |
| `data/profiles/research.yaml` | Research-only profile |
| `data/profiles/unrestricted.yaml` | Legacy/opt-out profile |
| `tests/test_sandbox_fs.py` | Path traversal, size limit, extension tests |
| `tests/test_profile_service.py` | Profile loading, resolution, filtering tests |

### Modified Files
| File | Change |
|------|--------|
| `api/services/plugin_service.py:163-181` | Accept optional `sandbox` param, inject `__sandbox` kwarg if tool signature accepts it |
| `api/services/tool_executor.py:18-134` | Add `set_policy()`, enforce profile before each tool call, pass sandbox |
| `api/services/session_manager.py:21-28` | Archive sandbox file list into session metadata, delete sandbox dir |
| `api/models/context_models.py` | Add `metadata: dict` field to `SessionSummary` |
| `api/routers/chat.py` | Resolve profile, create sandbox, wire into executor, include `profile_id` in response |
| `api/main.py` | Register profiles router |
| `api/static/index.html` | Add Profiles section to Memory tab |
| `.env.example` | Add `DEFAULT_PROFILE=default` |

---

## Task 1: SandboxedFS — core filesystem boundary

**Files:**
- Create: `api/services/sandbox_fs.py`
- Test: `tests/test_sandbox_fs.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sandbox_fs.py`:

```python
#!/usr/bin/env python3
"""Tests for SandboxedFS — filesystem boundary enforcement"""

import os
import pytest
import tempfile
import shutil
from pathlib import Path


@pytest.fixture
def sandbox_dir():
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    shutil.rmtree(tmpdir)


class TestBasicIO:
    def test_write_and_read(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        sb.write("hello.txt", "world")
        assert sb.read("hello.txt") == "world"

    def test_exists(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        assert not sb.exists("missing.txt")
        sb.write("there.txt", "x")
        assert sb.exists("there.txt")

    def test_listdir(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        sb.write("a.txt", "1")
        sb.write("b.txt", "2")
        entries = sb.listdir()
        assert sorted(entries) == ["a.txt", "b.txt"]

    def test_delete(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        sb.write("doomed.txt", "bye")
        sb.delete("doomed.txt")
        assert not sb.exists("doomed.txt")

    def test_nested_directory_creation(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        sb.write("sub/dir/file.txt", "nested")
        assert sb.read("sub/dir/file.txt") == "nested"


class TestPathTraversal:
    def test_parent_dir_escape(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS, SandboxViolation
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        with pytest.raises(SandboxViolation):
            sb.read("../../../etc/passwd")

    def test_absolute_path_blocked(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS, SandboxViolation
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        with pytest.raises(SandboxViolation):
            sb.read("/etc/passwd")

    def test_symlink_escape_blocked(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS, SandboxViolation
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        # Create a target outside the sandbox
        outside = tempfile.NamedTemporaryFile(delete=False, mode="w")
        outside.write("secret")
        outside.close()
        try:
            # Create a symlink inside the sandbox pointing outside
            link_path = Path(sandbox_dir) / "evil_link"
            os.symlink(outside.name, link_path)
            with pytest.raises(SandboxViolation):
                sb.read("evil_link")
        finally:
            os.unlink(outside.name)

    def test_write_outside_blocked(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS, SandboxViolation
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        with pytest.raises(SandboxViolation):
            sb.write("../escape.txt", "nope")


class TestQuotas:
    def test_size_limit_enforced(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS, SandboxQuotaExceeded
        sb = SandboxedFS(sandbox_root=sandbox_dir, max_file_size_mb=1)
        too_big = "x" * (2 * 1024 * 1024)  # 2MB when utf-8 encoded
        with pytest.raises(SandboxQuotaExceeded):
            sb.write("huge.txt", too_big)

    def test_size_under_limit_ok(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir, max_file_size_mb=1)
        small = "x" * 1024  # 1KB
        sb.write("small.txt", small)
        assert sb.read("small.txt") == small

    def test_extension_allowlist_enforced(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS, SandboxViolation
        sb = SandboxedFS(sandbox_root=sandbox_dir, allowed_extensions=["txt", "md"])
        sb.write("doc.txt", "ok")  # allowed
        sb.write("notes.md", "ok")  # allowed
        with pytest.raises(SandboxViolation):
            sb.write("script.sh", "bad")

    def test_extension_none_allows_all(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir, allowed_extensions=None)
        sb.write("any.xyz", "ok")


class TestStats:
    def test_stats_empty(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        s = sb.stats()
        assert s["file_count"] == 0
        assert s["total_bytes"] == 0

    def test_stats_with_files(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        sb.write("a.txt", "hello")
        sb.write("sub/b.txt", "world")
        s = sb.stats()
        assert s["file_count"] == 2
        assert s["total_bytes"] == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_sandbox_fs.py -v`
Expected: FAIL — `api.services.sandbox_fs` does not exist

- [ ] **Step 3: Create `api/services/sandbox_fs.py`**

```python
#!/usr/bin/env python3
"""
SandboxedFS — Per-conversation filesystem boundary

Tools opt in to sandboxing via a __sandbox kwarg. All paths are treated
as relative to the sandbox root and checked for traversal escape before
any filesystem operation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..logging_config import logger


class SandboxViolation(Exception):
    """Raised when a tool attempts to access outside the sandbox or violates a rule."""


class SandboxQuotaExceeded(Exception):
    """Raised when a tool exceeds size limits."""


class SandboxedFS:
    """Restricts filesystem access to a designated sandbox root directory."""

    def __init__(
        self,
        sandbox_root: str,
        max_file_size_mb: int = 10,
        allowed_extensions: Optional[list] = None,
    ):
        self.root = Path(sandbox_root).resolve()
        self.max_file_size = max_file_size_mb * 1024 * 1024
        self.allowed_extensions = allowed_extensions
        self.root.mkdir(parents=True, exist_ok=True)

    def get_absolute_path(self, relative_path: str) -> Path:
        """Resolve a relative path within the sandbox; raise SandboxViolation on escape."""
        # Strip leading slashes so "/etc/passwd" is treated as relative
        clean = relative_path.lstrip("/\\")
        candidate = (self.root / clean).resolve()
        # Python 3.9 compatible containment check
        try:
            candidate.relative_to(self.root)
        except ValueError:
            raise SandboxViolation(
                f"Path '{relative_path}' escapes sandbox root"
            )
        return candidate

    def _check_extension(self, path: str) -> None:
        if self.allowed_extensions is None:
            return
        suffix = Path(path).suffix.lstrip(".").lower()
        allowed = [e.lower().lstrip(".") for e in self.allowed_extensions]
        if suffix not in allowed:
            raise SandboxViolation(
                f"Extension '.{suffix}' not in allowed list {allowed}"
            )

    def read(self, path: str, encoding: str = "utf-8") -> str:
        abs_path = self.get_absolute_path(path)
        if not abs_path.exists():
            raise FileNotFoundError(f"File not found in sandbox: {path}")
        return abs_path.read_text(encoding=encoding)

    def write(self, path: str, content: str, encoding: str = "utf-8") -> None:
        self._check_extension(path)
        abs_path = self.get_absolute_path(path)
        encoded = content.encode(encoding)
        if len(encoded) > self.max_file_size:
            raise SandboxQuotaExceeded(
                f"File size {len(encoded)} exceeds max {self.max_file_size}"
            )
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(encoded)

    def open(self, path: str, mode: str = "r", **kwargs):
        abs_path = self.get_absolute_path(path)
        if "w" in mode or "a" in mode:
            self._check_extension(path)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
        return abs_path.open(mode, **kwargs)

    def exists(self, path: str) -> bool:
        try:
            abs_path = self.get_absolute_path(path)
        except SandboxViolation:
            return False
        return abs_path.exists()

    def listdir(self, path: str = "") -> list:
        abs_path = self.get_absolute_path(path) if path else self.root
        if not abs_path.exists():
            return []
        return [p.name for p in abs_path.iterdir()]

    def delete(self, path: str) -> None:
        abs_path = self.get_absolute_path(path)
        if abs_path.is_file():
            abs_path.unlink()
        elif abs_path.is_dir():
            import shutil
            shutil.rmtree(abs_path)

    def stats(self) -> dict:
        file_count = 0
        total_bytes = 0
        if self.root.exists():
            for p in self.root.rglob("*"):
                if p.is_file():
                    file_count += 1
                    total_bytes += p.stat().st_size
        return {
            "root": str(self.root),
            "file_count": file_count,
            "total_bytes": total_bytes,
            "max_file_size": self.max_file_size,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_sandbox_fs.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/sandbox_fs.py tests/test_sandbox_fs.py
git commit -m "feat: add SandboxedFS for per-conversation filesystem boundary"
```

---

## Task 2: Seeded Profile YAML Files

**Files:**
- Create: `data/profiles/default.yaml`
- Create: `data/profiles/research.yaml`
- Create: `data/profiles/unrestricted.yaml`

- [ ] **Step 1: Create `data/profiles/default.yaml`**

```yaml
id: "default"
name: "Default Profile"
description: "All plugins allowed, strict filesystem sandboxing"
version: "1.0.0"

allowed_plugins: ["*"]

tool_rules: {}

sandbox:
  mode: "strict"
  root_dir: "data/sandboxes/{conversation_id}"
  max_file_size_mb: 10
  allowed_extensions: null

network:
  mode: "unrestricted"
  allowed_hosts: []

bound_to_keys: []
```

- [ ] **Step 2: Create `data/profiles/research.yaml`**

```yaml
id: "research"
name: "Research Profile"
description: "Web search and document analysis only, strict sandbox"
version: "1.0.0"

allowed_plugins:
  - "web-search"
  - "doc-analyzer"

tool_rules:
  web-search:
    allowed_tools: ["web_search"]
  doc-analyzer:
    allowed_tools: ["read_document", "extract_text"]

sandbox:
  mode: "strict"
  root_dir: "data/sandboxes/{conversation_id}"
  max_file_size_mb: 5
  allowed_extensions: ["txt", "md", "json"]

network:
  mode: "unrestricted"
  allowed_hosts: []

bound_to_keys: []
```

- [ ] **Step 3: Create `data/profiles/unrestricted.yaml`**

```yaml
id: "unrestricted"
name: "Unrestricted Profile"
description: "No profile enforcement. Legacy behavior — use with caution."
version: "1.0.0"

allowed_plugins: ["*"]

tool_rules: {}

sandbox:
  mode: "none"
  root_dir: "data/sandboxes/{conversation_id}"
  max_file_size_mb: 100
  allowed_extensions: null

network:
  mode: "unrestricted"
  allowed_hosts: []

bound_to_keys: []
```

- [ ] **Step 4: Commit**

```bash
git add data/profiles/
git commit -m "feat: seed built-in profiles (default, research, unrestricted)"
```

---

## Task 3: ProfileService

**Files:**
- Create: `api/services/profile_service.py`
- Test: `tests/test_profile_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_profile_service.py`:

```python
#!/usr/bin/env python3
"""Tests for ProfileService — loading, resolution, tool filtering"""

import os
import pytest
import tempfile
import shutil
import yaml
from pathlib import Path


@pytest.fixture
def profile_dir():
    tmpdir = tempfile.mkdtemp()
    # Seed with test profiles
    Path(tmpdir, "default.yaml").write_text(yaml.dump({
        "id": "default",
        "name": "Default",
        "description": "All plugins allowed",
        "version": "1.0.0",
        "allowed_plugins": ["*"],
        "tool_rules": {},
        "sandbox": {"mode": "strict", "max_file_size_mb": 10, "allowed_extensions": None},
        "network": {"mode": "unrestricted", "allowed_hosts": []},
        "bound_to_keys": [],
    }))
    Path(tmpdir, "research.yaml").write_text(yaml.dump({
        "id": "research",
        "name": "Research",
        "description": "Search only",
        "version": "1.0.0",
        "allowed_plugins": ["web-search"],
        "tool_rules": {"web-search": {"allowed_tools": ["web_search"]}},
        "sandbox": {"mode": "strict", "max_file_size_mb": 5},
        "network": {"mode": "unrestricted", "allowed_hosts": []},
        "bound_to_keys": [],
    }))
    yield tmpdir
    shutil.rmtree(tmpdir)


class TestProfileLoading:
    def test_load_profiles(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert "default" in [p["id"] for p in svc.list_profiles()]
        assert "research" in [p["id"] for p in svc.list_profiles()]

    def test_get_profile(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        profile = svc.get_profile("research")
        assert profile["id"] == "research"
        assert profile["allowed_plugins"] == ["web-search"]

    def test_get_missing_profile_returns_none(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert svc.get_profile("nonexistent") is None

    def test_reload(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        initial_count = len(svc.list_profiles())

        # Add a new profile file
        Path(profile_dir, "new.yaml").write_text(yaml.dump({
            "id": "new", "name": "New", "description": "Test",
            "version": "1.0.0", "allowed_plugins": ["*"], "tool_rules": {},
            "sandbox": {"mode": "strict"}, "network": {"mode": "unrestricted"},
            "bound_to_keys": [],
        }))
        svc.reload()
        assert len(svc.list_profiles()) == initial_count + 1
        assert svc.get_profile("new") is not None


class TestProfileResolution:
    def test_resolve_header_priority(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        resolved = svc.resolve(header="research", key_id=None)
        assert resolved == "research"

    def test_resolve_default_fallback(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        resolved = svc.resolve(header=None, key_id=None)
        assert resolved == "default"

    def test_resolve_missing_profile_falls_back_to_default(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        resolved = svc.resolve(header="nonexistent", key_id=None)
        assert resolved == "default"


class TestToolFiltering:
    def _make_tools(self):
        return [
            {"type": "function", "function": {
                "name": "web-search__web_search",
                "description": "Search the web",
                "parameters": {"type": "object", "properties": {}, "required": []},
            }},
            {"type": "function", "function": {
                "name": "web-search__index_site",
                "description": "Index a site",
                "parameters": {"type": "object", "properties": {}, "required": []},
            }},
            {"type": "function", "function": {
                "name": "file-writer__write_file",
                "description": "Write a file",
                "parameters": {"type": "object", "properties": {}, "required": []},
            }},
        ]

    def test_filter_tools_wildcard_allows_all(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        filtered = svc.filter_tools(self._make_tools(), "default")
        assert len(filtered) == 3

    def test_filter_tools_restricted_plugin(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        # research profile only allows web-search plugin
        filtered = svc.filter_tools(self._make_tools(), "research")
        names = [t["function"]["name"] for t in filtered]
        assert "file-writer__write_file" not in names
        assert "web-search__web_search" in names

    def test_filter_tools_with_tool_rules(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        # research profile restricts web-search to only web_search tool
        filtered = svc.filter_tools(self._make_tools(), "research")
        names = [t["function"]["name"] for t in filtered]
        assert "web-search__index_site" not in names
        assert "web-search__web_search" in names


class TestIsToolAllowed:
    def test_allowed_via_wildcard(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert svc.is_tool_allowed("anything", "whatever", "default") is True

    def test_blocked_plugin(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert svc.is_tool_allowed("file-writer", "write_file", "research") is False

    def test_blocked_tool_within_allowed_plugin(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        assert svc.is_tool_allowed("web-search", "index_site", "research") is False
        assert svc.is_tool_allowed("web-search", "web_search", "research") is True

    def test_unknown_profile_allows_nothing(self, profile_dir):
        from api.services.profile_service import ProfileService
        svc = ProfileService(profiles_dir=profile_dir)
        svc.load_profiles()
        # An unknown profile is treated as a bug, not a free-pass — deny
        assert svc.is_tool_allowed("x", "y", "missing") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_profile_service.py -v`
Expected: FAIL — `api.services.profile_service` does not exist

- [ ] **Step 3: Create `api/services/profile_service.py`**

```python
#!/usr/bin/env python3
"""
Profile Service — YAML-declared policy for which plugins/tools are available.

Profiles live in data/profiles/*.yaml. Resolution priority:
  1. X-Profile-ID header
  2. API key binding
  3. DEFAULT_PROFILE env var
  4. "default" profile
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

from ..logging_config import logger


class ProfileService:
    """Loads and queries agent permission profiles."""

    def __init__(self, profiles_dir: Optional[str] = None):
        self._dir = Path(profiles_dir) if profiles_dir else Path("data/profiles")
        self._profiles: dict = {}

    def load_profiles(self) -> list:
        """Scan the profiles directory and load all YAML files."""
        self._profiles.clear()
        if not self._dir.exists():
            logger.warning(f"Profiles directory not found: {self._dir}")
            return []

        loaded = []
        for path in sorted(self._dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text())
                if not isinstance(data, dict) or "id" not in data:
                    logger.error(f"Invalid profile (missing id): {path}")
                    continue
                self._profiles[data["id"]] = data
                loaded.append(data)
                logger.info(f"Loaded profile: {data['id']}")
            except yaml.YAMLError as e:
                logger.error(f"Invalid YAML in {path}: {e}")
        return loaded

    def reload(self) -> list:
        """Re-scan the profiles directory."""
        return self.load_profiles()

    def get_profile(self, profile_id: str) -> Optional[dict]:
        return self._profiles.get(profile_id)

    def list_profiles(self) -> list:
        return list(self._profiles.values())

    def resolve(self, header: Optional[str], key_id: Optional[str]) -> str:
        """
        Resolve which profile to use.
        Priority: header > key binding > DEFAULT_PROFILE env > "default".
        Falls back to "default" if resolved ID doesn't exist.
        """
        # 1. Header override
        if header and header in self._profiles:
            return header
        # 2. API key binding
        if key_id:
            for pid, profile in self._profiles.items():
                if key_id in (profile.get("bound_to_keys") or []):
                    return pid
        # 3. Env var
        env_profile = os.getenv("DEFAULT_PROFILE", "default")
        if env_profile in self._profiles:
            return env_profile
        # 4. default fallback
        if "default" in self._profiles:
            return "default"
        # 5. any profile
        if self._profiles:
            return next(iter(self._profiles))
        logger.warning("No profiles loaded — returning 'default' by convention")
        return "default"

    def is_tool_allowed(self, plugin_id: str, tool_id: str, profile_id: str) -> bool:
        """Check if a specific tool invocation is permitted by the profile."""
        profile = self.get_profile(profile_id)
        if profile is None:
            return False  # unknown profile = deny

        allowed_plugins = profile.get("allowed_plugins", [])
        # Wildcard allows all plugins
        if "*" not in allowed_plugins and plugin_id not in allowed_plugins:
            return False

        # Check tool-level rules
        tool_rules = profile.get("tool_rules") or {}
        plugin_rule = tool_rules.get(plugin_id)
        if plugin_rule:
            allowed_tools = plugin_rule.get("allowed_tools")
            if allowed_tools is not None and tool_id not in allowed_tools:
                return False

        return True

    def filter_tools(self, ollama_tools: list, profile_id: str) -> list:
        """Remove disallowed tools from an Ollama-format tool list."""
        filtered = []
        for tool in ollama_tools:
            name = tool.get("function", {}).get("name", "")
            parts = name.split("__", 1)
            if len(parts) != 2:
                continue  # malformed names are silently dropped
            plugin_id, tool_id = parts
            if self.is_tool_allowed(plugin_id, tool_id, profile_id):
                filtered.append(tool)
        return filtered
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_profile_service.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/profile_service.py tests/test_profile_service.py
git commit -m "feat: add ProfileService for YAML-declared agent permissions"
```

---

## Task 4: Plugin Service — Sandbox Injection

**Files:**
- Modify: `api/services/plugin_service.py`
- Test: `tests/test_sandbox_fs.py` (append)

- [ ] **Step 1: Append tests for sandbox injection**

Append to `tests/test_sandbox_fs.py`:

```python
class TestSandboxInjectionIntoPlugins:
    def _make_plugin_dir(self, tool_code: str):
        import tempfile
        tmpdir = tempfile.mkdtemp()
        plugin = Path(tmpdir) / "test-plugin"
        plugin.mkdir()
        (plugin / "plugin.yaml").write_text(yaml.dump({
            "name": "Test", "id": "test-plugin", "version": "1.0.0",
            "description": "Test", "author": "test",
            "tools": [{
                "id": "sb_tool", "file": "tools/sb_tool.py",
                "function": "execute", "description": "Sandbox test",
                "parameters": {"path": {"type": "string", "required": True}},
            }],
        }))
        tools = plugin / "tools"
        tools.mkdir()
        (tools / "__init__.py").write_text("")
        (tools / "sb_tool.py").write_text(tool_code)
        return tmpdir

    def test_tool_receives_sandbox_when_declared(self, sandbox_dir):
        import yaml
        from pathlib import Path
        from api.services.plugin_service import PluginService
        from api.services.sandbox_fs import SandboxedFS

        tool_code = (
            "def execute(path: str, __sandbox=None) -> dict:\n"
            "    if __sandbox is None:\n"
            "        return {'error': 'no sandbox'}\n"
            "    __sandbox.write(path, 'sandboxed content')\n"
            "    return {'wrote': path}\n"
        )
        tmpdir = self._make_plugin_dir(tool_code)
        try:
            svc = PluginService(plugins_dir=tmpdir)
            svc.scan_plugins()
            sb = SandboxedFS(sandbox_root=sandbox_dir)
            result = svc.call_tool("test-plugin", "sb_tool", {"path": "out.txt"}, sandbox=sb)
            assert result == {"wrote": "out.txt"}
            assert sb.read("out.txt") == "sandboxed content"
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_tool_without_sandbox_param_still_works(self, sandbox_dir):
        import yaml
        from pathlib import Path
        from api.services.plugin_service import PluginService
        from api.services.sandbox_fs import SandboxedFS

        # Tool doesn't declare __sandbox — shouldn't receive it
        tool_code = (
            "def execute(value: str) -> dict:\n"
            "    return {'echoed': value}\n"
        )
        tmpdir = self._make_plugin_dir(tool_code)
        try:
            svc = PluginService(plugins_dir=tmpdir)
            svc.scan_plugins()
            sb = SandboxedFS(sandbox_root=sandbox_dir)
            # Passing sandbox should not break a tool that doesn't declare __sandbox
            result = svc.call_tool("test-plugin", "sb_tool", {"value": "hi"}, sandbox=sb)
            assert result == {"echoed": "hi"}
        finally:
            import shutil
            shutil.rmtree(tmpdir)
```

Also ensure the file has the necessary imports at the top. Add after the existing imports:
```python
import yaml
from pathlib import Path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_sandbox_fs.py::TestSandboxInjectionIntoPlugins -v`
Expected: FAIL — `call_tool` doesn't accept `sandbox` parameter

- [ ] **Step 3: Modify `api/services/plugin_service.py`**

Add `import inspect` to the imports at the top (after `import sys`).

Replace the `call_tool` method (lines 163-181):

```python
    def call_tool(self, plugin_id: str, tool_id: str, params: dict, sandbox=None) -> dict:
        """Execute a tool function and return its result.

        If `sandbox` is provided and the tool function declares a `__sandbox`
        parameter, the sandbox instance is injected before invocation.
        """
        if plugin_id not in self._plugins:
            raise ValueError(f"Plugin not found: {plugin_id}")

        key = (plugin_id, tool_id)
        if key not in self._tools:
            raise ValueError(f"Tool not found: {plugin_id}/{tool_id}")

        entry = self._tools[key]
        func_name = entry["function"]
        func = getattr(entry["module"], func_name, None)
        if func is None:
            raise ValueError(f"Function '{func_name}' not found in {plugin_id}/{tool_id}")

        # Inject __sandbox only if the tool declares it
        call_params = dict(params)
        if sandbox is not None:
            try:
                sig = inspect.signature(func)
                if "__sandbox" in sig.parameters:
                    call_params["__sandbox"] = sandbox
            except (TypeError, ValueError):
                # Introspection failed; don't inject
                pass

        try:
            return func(**call_params)
        except Exception as e:
            logger.error(f"Tool {plugin_id}/{tool_id} failed: {e}")
            raise RuntimeError(f"Tool execution failed: {e}") from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_sandbox_fs.py tests/test_plugins.py -v`
Expected: All PASS (existing plugin tests + new sandbox injection tests)

- [ ] **Step 5: Commit**

```bash
git add api/services/plugin_service.py tests/test_sandbox_fs.py
git commit -m "feat: inject SandboxedFS into tools that declare __sandbox param"
```

---

## Task 5: Tool Executor — Profile Enforcement + Sandbox Pass-through

**Files:**
- Modify: `api/services/tool_executor.py`
- Test: `tests/test_tool_executor.py` (append)

- [ ] **Step 1: Append tests**

Append to `tests/test_tool_executor.py`:

```python
class TestToolExecutorPolicy:
    def _setup_plugin_and_profile(self):
        import tempfile, yaml, shutil
        from pathlib import Path
        from api.services.plugin_service import PluginService
        from api.services.profile_service import ProfileService

        tmp_plugin = tempfile.mkdtemp()
        p = Path(tmp_plugin) / "echo-plugin"
        p.mkdir()
        (p / "plugin.yaml").write_text(yaml.dump({
            "name": "Echo", "id": "echo", "version": "1.0.0",
            "description": "Echo", "author": "test",
            "tools": [{
                "id": "echo", "file": "tools/echo.py", "function": "execute",
                "description": "Echo", "parameters": {"text": {"type": "string", "required": True}},
            }],
        }))
        tools = p / "tools"
        tools.mkdir()
        (tools / "__init__.py").write_text("")
        (tools / "echo.py").write_text(
            "def execute(text: str) -> dict:\n    return {'echo': text}\n"
        )

        tmp_profile = tempfile.mkdtemp()
        Path(tmp_profile, "no-echo.yaml").write_text(yaml.dump({
            "id": "no-echo", "name": "No Echo", "description": "Echo blocked",
            "version": "1.0.0",
            "allowed_plugins": ["other-plugin"],
            "tool_rules": {}, "sandbox": {"mode": "strict"},
            "network": {"mode": "unrestricted"}, "bound_to_keys": [],
        }))
        Path(tmp_profile, "allow-all.yaml").write_text(yaml.dump({
            "id": "allow-all", "name": "Allow All", "description": "Open",
            "version": "1.0.0",
            "allowed_plugins": ["*"], "tool_rules": {},
            "sandbox": {"mode": "strict"},
            "network": {"mode": "unrestricted"}, "bound_to_keys": [],
        }))

        plugin_svc = PluginService(plugins_dir=tmp_plugin)
        plugin_svc.scan_plugins()
        profile_svc = ProfileService(profiles_dir=tmp_profile)
        profile_svc.load_profiles()
        return plugin_svc, profile_svc, tmp_plugin, tmp_profile

    def test_profile_blocks_disallowed_tool_at_execution(self):
        from api.services.tool_executor import ToolExecutor
        from api.services.ollama_service import OllamaService
        import shutil

        plugin_svc, profile_svc, tp, tpr = self._setup_plugin_and_profile()
        try:
            executor = ToolExecutor(OllamaService(), plugin_svc)
            executor.set_policy(profile_svc, "no-echo", None)

            tc_resp = MagicMock()
            tc_resp.status_code = 200
            tc_resp.json.return_value = {
                "message": {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "echo__echo", "arguments": {"text": "hi"}}}
                ]},
                "prompt_eval_count": 10, "eval_count": 5,
            }
            final_resp = MagicMock()
            final_resp.status_code = 200
            final_resp.json.return_value = {
                "message": {"role": "assistant", "content": "Blocked, sorry."},
                "prompt_eval_count": 20, "eval_count": 10,
            }
            with patch("api.services.ollama_service.requests.post", side_effect=[tc_resp, final_resp]):
                result = executor.execute(model="test", messages=[{"role": "user", "content": "echo hi"}])
                assert len(result["tool_calls_made"]) == 1
                assert "not permitted" in result["tool_calls_made"][0]["result"]["error"]
        finally:
            shutil.rmtree(tp)
            shutil.rmtree(tpr)

    def test_profile_allows_permitted_tool(self):
        from api.services.tool_executor import ToolExecutor
        from api.services.ollama_service import OllamaService
        import shutil

        plugin_svc, profile_svc, tp, tpr = self._setup_plugin_and_profile()
        try:
            executor = ToolExecutor(OllamaService(), plugin_svc)
            executor.set_policy(profile_svc, "allow-all", None)

            tc_resp = MagicMock()
            tc_resp.status_code = 200
            tc_resp.json.return_value = {
                "message": {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "echo__echo", "arguments": {"text": "hi"}}}
                ]},
                "prompt_eval_count": 10, "eval_count": 5,
            }
            final_resp = MagicMock()
            final_resp.status_code = 200
            final_resp.json.return_value = {
                "message": {"role": "assistant", "content": "Done"},
                "prompt_eval_count": 20, "eval_count": 10,
            }
            with patch("api.services.ollama_service.requests.post", side_effect=[tc_resp, final_resp]):
                result = executor.execute(model="test", messages=[{"role": "user", "content": "echo hi"}])
                assert result["tool_calls_made"][0]["result"] == {"echo": "hi"}
        finally:
            shutil.rmtree(tp)
            shutil.rmtree(tpr)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_tool_executor.py::TestToolExecutorPolicy -v`
Expected: FAIL — `set_policy` doesn't exist

- [ ] **Step 3: Modify `api/services/tool_executor.py`**

Replace the class `__init__` and add `set_policy`. Replace lines 21-30:

```python
    def __init__(self, ollama_service: OllamaService, plugin_service: PluginService):
        self.ollama = ollama_service
        self.plugins = plugin_service
        self._context_store = None
        self._conversation_id = None
        self._profile_service = None
        self._profile_id = None
        self._sandbox = None

    def set_context(self, context_store, conversation_id: str):
        """Set the context store and conversation ID for recording tool calls."""
        self._context_store = context_store
        self._conversation_id = conversation_id

    def set_policy(self, profile_service, profile_id: str, sandbox):
        """Set the active profile and sandbox for this execution."""
        self._profile_service = profile_service
        self._profile_id = profile_id
        self._sandbox = sandbox
```

Modify the `execute` method to filter tools per profile. Replace line 40:

```python
        ollama_tools = self.plugins.get_ollama_tools()
        if self._profile_service and self._profile_id:
            ollama_tools = self._profile_service.filter_tools(ollama_tools, self._profile_id)
```

Modify `_execute_tool` (lines 122-134) to check profile before calling and pass the sandbox:

```python
    def _execute_tool(self, tool_name: str, arguments: dict) -> dict:
        parts = tool_name.split("__", 1)
        if len(parts) != 2:
            return {"error": f"Invalid tool name format: {tool_name}. Expected 'plugin_id__tool_id'."}
        plugin_id, tool_id = parts

        # Defense-in-depth: even if filtering missed it, re-check the profile
        if self._profile_service and self._profile_id:
            if not self._profile_service.is_tool_allowed(plugin_id, tool_id, self._profile_id):
                return {"error": f"Tool '{tool_name}' not permitted by profile '{self._profile_id}'"}

        try:
            return self.plugins.call_tool(plugin_id, tool_id, arguments, sandbox=self._sandbox)
        except (ValueError, RuntimeError) as e:
            logger.error(f"Tool execution failed: {tool_name}: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Unexpected tool error: {tool_name}: {e}")
            return {"error": f"Unexpected error: {e}"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_tool_executor.py -v`
Expected: All PASS (existing + 2 new policy tests)

- [ ] **Step 5: Commit**

```bash
git add api/services/tool_executor.py tests/test_tool_executor.py
git commit -m "feat: enforce profile permissions and pass sandbox in tool executor"
```

---

## Task 6: Profiles Router + Main Registration

**Files:**
- Create: `api/routers/profiles.py`
- Modify: `api/main.py`
- Modify: `.env.example`
- Test: `tests/test_profile_service.py` (append)

- [ ] **Step 1: Create `api/routers/profiles.py`**

```python
#!/usr/bin/env python3
"""
Profiles Router — Read-only profile management endpoints.

Profiles are edited as YAML files in data/profiles/. POST /api/profiles/reload
re-scans the directory to pick up changes.
"""

import os
from fastapi import APIRouter, HTTPException

from ..services.profile_service import ProfileService

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

profile_service = ProfileService()
profile_service.load_profiles()


@router.get("")
async def list_profiles():
    """List all loaded profiles."""
    return profile_service.list_profiles()


@router.get("/active")
async def get_active_default():
    """Return the configured default profile ID."""
    default_id = os.getenv("DEFAULT_PROFILE", "default")
    return {"default_profile_id": default_id}


@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    """Return full profile detail."""
    profile = profile_service.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.post("/reload")
async def reload_profiles():
    """Re-scan data/profiles/ for changes."""
    loaded = profile_service.reload()
    return {"loaded": len(loaded), "ids": [p["id"] for p in loaded]}
```

- [ ] **Step 2: Register the router in `api/main.py`**

Find the imports line that starts with `from .routers import`. Add `profiles` to it:

```python
from .routers import chat, completions, models, inventory, exports, graph, workflows, api_keys, plugins, setup, context, memory, profiles
```

After the last `app.include_router(...)` line, add:

```python
app.include_router(profiles.router)
```

- [ ] **Step 3: Add DEFAULT_PROFILE to `.env.example`**

Append to `.env.example`:

```
# Profile System (Phase 3)
DEFAULT_PROFILE=default
```

- [ ] **Step 4: Append router tests to `tests/test_profile_service.py`**

```python
import importlib
from fastapi.testclient import TestClient


class TestProfileRouter:
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

    def test_list_profiles_endpoint(self, client):
        resp = client.get("/api/profiles")
        assert resp.status_code == 200
        # Should include at least the seeded profiles
        ids = [p["id"] for p in resp.json()]
        assert "default" in ids

    def test_get_profile_detail(self, client):
        resp = client.get("/api/profiles/default")
        assert resp.status_code == 200
        assert resp.json()["id"] == "default"

    def test_get_missing_profile_404(self, client):
        resp = client.get("/api/profiles/nonexistent")
        assert resp.status_code == 404

    def test_reload_profiles(self, client):
        resp = client.post("/api/profiles/reload")
        assert resp.status_code == 200
        assert "loaded" in resp.json()

    def test_active_default(self, client):
        resp = client.get("/api/profiles/active")
        assert resp.status_code == 200
        assert "default_profile_id" in resp.json()
```

- [ ] **Step 5: Run tests**

Run: `source ../../../venv/bin/activate && python -m pytest tests/test_profile_service.py -v`
Expected: All PASS (service + router tests)

- [ ] **Step 6: Commit**

```bash
git add api/routers/profiles.py api/main.py .env.example tests/test_profile_service.py
git commit -m "feat: add profiles router with list/detail/reload endpoints"
```

---

## Task 7: Chat Router Integration + Session Manager Archive

**Files:**
- Modify: `api/routers/chat.py`
- Modify: `api/services/session_manager.py`
- Modify: `api/models/context_models.py`

- [ ] **Step 1: Add `metadata` to `SessionSummary`**

In `api/models/context_models.py`, find the `SessionSummary` dataclass. Add a `metadata` field. Locate the class definition and append a `metadata` field before `@classmethod from_context`:

```python
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
    tools_used: list
    skills_triggered: list
    topics: list = field(default_factory=list)
    preview: str = ""
    tool_calls: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
```

Update `to_dict()` to include metadata:

```python
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
            "metadata": self.metadata,
        }
```

- [ ] **Step 2: Modify `api/services/session_manager.py` to archive sandbox**

Replace the `close_session` method:

```python
    def close_session(self, conversation_id: str, preview: str = ""):
        ctx = self.context_store.remove(conversation_id)
        if not ctx:
            return None
        summary = SessionSummary.from_context(ctx, preview=preview)

        # Preserve profile ID in metadata if present
        if ctx.metadata.get("profile_id"):
            summary.metadata["profile_id"] = ctx.metadata["profile_id"]

        # Archive sandbox contents (file list only) then delete the directory
        import shutil
        from pathlib import Path
        sandbox_dir = Path(f"data/sandboxes/{conversation_id}")
        if sandbox_dir.exists():
            files = []
            for f in sandbox_dir.rglob("*"):
                if f.is_file():
                    files.append({
                        "path": str(f.relative_to(sandbox_dir)),
                        "size": f.stat().st_size,
                    })
            summary.metadata["sandbox_files"] = files
            try:
                shutil.rmtree(sandbox_dir)
            except OSError as e:
                logger.warning(f"Could not remove sandbox dir {sandbox_dir}: {e}")

        self.memory_service.save_session(summary)
        logger.info(f"Session closed and saved: {conversation_id}")
        return summary.to_dict()
```

- [ ] **Step 3: Modify `api/routers/chat.py` to resolve profile and create sandbox**

Add imports at the top (after existing imports):

```python
from ..services.profile_service import ProfileService
from ..services.sandbox_fs import SandboxedFS
from .profiles import profile_service as _profile_service
```

After `_memory_service = MemoryService()` line, add (no new service instance needed since we import from profiles router):

(No new variable — `_profile_service` is imported above.)

Inside `chat_completions`, after the conversation tracking block and before the skill injection block, add:

```python
    # ── Profile Resolution ────────────────────────────────────────────
    profile_header = req.headers.get("X-Profile-ID")
    profile_id = _profile_service.resolve(header=profile_header, key_id=None)
    ctx = _context_store.get(conversation_id)
    if ctx is not None:
        ctx.metadata["profile_id"] = profile_id

    # ── Sandbox Setup ────────────────────────────────────────────────
    profile = _profile_service.get_profile(profile_id) or {}
    sandbox_cfg = profile.get("sandbox") or {}
    sandbox = None
    if sandbox_cfg.get("mode") and sandbox_cfg["mode"] != "none":
        sandbox = SandboxedFS(
            sandbox_root=f"data/sandboxes/{conversation_id}",
            max_file_size_mb=sandbox_cfg.get("max_file_size_mb", 10),
            allowed_extensions=sandbox_cfg.get("allowed_extensions"),
        )
```

Before the `_tool_executor.execute(...)` call, add:

```python
        _tool_executor.set_policy(_profile_service, profile_id, sandbox)
```

Add `profile_id` to both response dicts (the tools path and the no-tools path):

```python
        response["profile_id"] = profile_id
```

- [ ] **Step 4: Run full test suite**

Run: `source ../../../venv/bin/activate && python -m pytest tests/ --tb=short -k "not integration" 2>&1 | tail -10`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add api/routers/chat.py api/services/session_manager.py api/models/context_models.py
git commit -m "feat: wire profiles and sandbox into chat router and session manager"
```

---

## Task 8: Profiles Section in Memory Tab + Final Verification

**Files:**
- Modify: `api/static/index.html`

- [ ] **Step 1: Add Profiles section to Memory tab**

In `api/static/index.html`, find the Memory tab panel (the `<div class="tab-content" id="tab-memory" ...>`). Inside that div, after the existing Stats row (the last `<div style="display:flex;gap:16px;margin-top:16px;">`), add:

```html
<!-- Profiles Section -->
<div class="panel" style="border:1px solid var(--border);border-radius:8px;padding:16px;margin-top:16px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <h3 style="color:var(--cyan);font-size:0.9rem;">Active Profile: <span id="active-profile-id" style="color:var(--amber);">loading…</span></h3>
    <button onclick="reloadProfiles()" style="background:var(--cyan);color:#000;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-weight:600;font-size:0.75rem;">Reload</button>
  </div>
  <div id="profiles-list" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;"></div>
  <div style="margin-top:10px;font-size:0.7rem;color:var(--text-dim);">
    Profiles are edited in <code style="color:var(--cyan);">data/profiles/*.yaml</code>. Click Reload after changes.
  </div>
</div>
```

- [ ] **Step 2: Add JavaScript for the Profiles section**

In the same file, add these functions near the existing Memory tab functions (e.g., after `loadMemoryStats`). Use the existing `esc()` helper (not `escapeHtml`):

```javascript
async function loadProfiles() {
  try {
    const [profilesResp, activeResp] = await Promise.all([
      fetch('/api/profiles'),
      fetch('/api/profiles/active'),
    ]);
    const profiles = await profilesResp.json();
    const active = await activeResp.json();
    document.getElementById('active-profile-id').textContent = active.default_profile_id || 'default';

    const el = document.getElementById('profiles-list');
    if (!profiles.length) {
      el.innerHTML = '<div style="color:var(--text-muted);font-size:0.8rem;">No profiles loaded.</div>';
      return;
    }
    el.innerHTML = profiles.map(p => {
      const pluginCount = (p.allowed_plugins || []).length;
      const sandboxMode = (p.sandbox || {}).mode || 'none';
      const wildcard = (p.allowed_plugins || []).includes('*');
      return `
        <div style="padding:10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-deep);">
          <div style="font-size:0.85rem;color:var(--text);font-weight:500;">${esc(p.name || p.id)}</div>
          <div style="font-size:0.7rem;color:var(--text-dim);margin-top:2px;">${esc(p.description || '')}</div>
          <div style="font-size:0.7rem;color:var(--text-dim);margin-top:6px;">
            <span style="color:var(--cyan);">${wildcard ? 'all plugins' : pluginCount + ' plugins'}</span>
            · <span>sandbox: ${esc(sandboxMode)}</span>
          </div>
        </div>
      `;
    }).join('');
  } catch(e) { console.error('Failed to load profiles:', e); }
}

async function reloadProfiles() {
  try {
    await fetch('/api/profiles/reload', {method: 'POST'});
    loadProfiles();
  } catch(e) { console.error('Reload failed:', e); }
}
```

Update `loadMemoryTab()` to also call `loadProfiles()`:

Find the existing `loadMemoryTab` function and add `loadProfiles();` to it so it becomes:

```javascript
async function loadMemoryTab() {
  loadSessions();
  loadFacts();
  loadMemoryStats();
  loadProfiles();
}
```

- [ ] **Step 3: Run the full test suite**

Run: `source ../../../venv/bin/activate && python -m pytest tests/ --tb=short -k "not integration" 2>&1 | tail -10`
Expected: All tests pass

- [ ] **Step 4: Verify endpoints end-to-end**

```bash
source ../../../venv/bin/activate && python -m api.main &
sleep 3

# List profiles
curl -s http://localhost:8000/api/profiles | python -m json.tool | head -20

# Get a specific profile
curl -s http://localhost:8000/api/profiles/research | python -m json.tool

# Make a chat request with a profile header (requires Ollama running)
curl -s -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Profile-ID: research" \
  -d '{"model":"dolphin3:latest","messages":[{"role":"user","content":"hi"}],"tools":true}' \
  | python -m json.tool | head -20

kill %1 2>/dev/null
```

- [ ] **Step 5: Rebuild the DMG**

```bash
./scripts/build_mac.sh
```
Expected: DMG builds; profiles directory is copied into the Resources dir; build completes successfully.

- [ ] **Step 6: Commit**

```bash
git add api/static/index.html
git commit -m "feat: add Profiles section to Memory tab with reload button"
```
