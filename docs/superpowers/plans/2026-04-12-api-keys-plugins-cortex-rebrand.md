# API Key Management, Plugin System & Cortex Rebrand — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-key API management, a unified plugin system (skills + tools), and rebrand the dashboard to the Cortex green palette.

**Architecture:** Three independent features built as modular services following the existing router/service pattern. API key service manages YAML-backed key storage with SHA-256 hashing. Plugin service discovers plugins from a `plugins/` directory convention. Color rebrand is a CSS variable swap in the single-file dashboard.

**Tech Stack:** Python 3, FastAPI, PyYAML, hashlib, secrets, importlib, pytest

**Spec:** `docs/superpowers/specs/2026-04-12-api-keys-plugins-cortex-rebrand-design.md`

---

## File Map

### New Files
| File | Responsibility |
|------|---------------|
| `api/services/api_key_service.py` | Key CRUD, hashing, validation, usage tracking, YAML persistence |
| `api/routers/api_keys.py` | REST endpoints for key management (protected by master key) |
| `api/services/plugin_service.py` | Plugin discovery, manifest parsing, skill/tool loading |
| `api/routers/plugins.py` | REST endpoints for plugin listing and tool invocation |
| `plugins/example-web-search/plugin.yaml` | Example plugin manifest |
| `plugins/example-web-search/skills/search-expert.md` | Example skill file |
| `plugins/example-web-search/tools/web_search.py` | Example tool implementation |
| `tests/test_api_keys.py` | Tests for API key service and router |
| `tests/test_plugins.py` | Tests for plugin service and router |

### Modified Files
| File | Change |
|------|--------|
| `api/main.py:18,86-88,100-106` | Import and register new routers, init plugin service in lifespan |
| `api/middleware.py:21-22,45-88` | Upgrade auth to use api_key_service for multi-key validation |
| `api/routers/chat.py:41-156` | Integrate plugin skills/tools into chat flow |
| `api/static/index.html:13-40,54-91` | Replace CSS variables with Cortex palette, remove grid/scanline |
| `.env.example:7-9` | Add MASTER_API_KEY, update auth docs |

---

## Task 1: API Key Service

**Files:**
- Create: `api/services/api_key_service.py`
- Test: `tests/test_api_keys.py`

- [ ] **Step 1: Write failing tests for key creation and validation**

Create `tests/test_api_keys.py`:

```python
#!/usr/bin/env python3
"""Tests for API Key Service"""

import os
import pytest
import tempfile
import shutil
from pathlib import Path


@pytest.fixture
def key_service():
    """API key service with temp directory for YAML storage"""
    tmpdir = tempfile.mkdtemp()
    os.environ["DATA_CONFIG_DIR"] = tmpdir

    # Import after setting env
    from api.services.api_key_service import APIKeyService
    svc = APIKeyService(config_dir=tmpdir)
    yield svc
    shutil.rmtree(tmpdir)


class TestKeyCreation:
    def test_create_key_returns_full_key(self, key_service):
        result = key_service.create_key(name="test-dev", scopes=["chat", "models"])
        assert result["key"].startswith("sk-test-dev-")
        assert len(result["key"]) > 40
        assert result["id"].startswith("key_")
        assert result["name"] == "test-dev"

    def test_create_key_persists_to_yaml(self, key_service):
        key_service.create_key(name="persist-test", scopes=["chat"])
        keys = key_service.list_keys()
        assert len(keys) == 1
        assert keys[0]["name"] == "persist-test"
        # Full key should NOT be in the listed output
        assert "key" not in keys[0]
        assert keys[0]["prefix"].startswith("sk-persist-test-")

    def test_create_key_with_rate_limit(self, key_service):
        result = key_service.create_key(
            name="limited", scopes=["chat"], rate_limit_rpm=30
        )
        keys = key_service.list_keys()
        assert keys[0]["rate_limit_rpm"] == 30


class TestKeyValidation:
    def test_validate_valid_key(self, key_service):
        result = key_service.create_key(name="valid", scopes=["chat", "completions"])
        meta = key_service.validate_key(result["key"])
        assert meta is not None
        assert meta["name"] == "valid"
        assert meta["scopes"] == ["chat", "completions"]

    def test_validate_invalid_key(self, key_service):
        assert key_service.validate_key("sk-fake-notreal") is None

    def test_validate_revoked_key(self, key_service):
        result = key_service.create_key(name="revokable", scopes=["chat"])
        key_service.revoke_key(result["id"])
        assert key_service.validate_key(result["key"]) is None

    def test_validate_expired_key(self, key_service):
        result = key_service.create_key(
            name="expired", scopes=["chat"],
            expires_at="2020-01-01T00:00:00Z"
        )
        assert key_service.validate_key(result["key"]) is None


class TestKeyManagement:
    def test_revoke_key(self, key_service):
        result = key_service.create_key(name="to-revoke", scopes=["chat"])
        key_service.revoke_key(result["id"])
        keys = key_service.list_keys()
        assert keys[0]["enabled"] is False

    def test_rotate_key(self, key_service):
        result = key_service.create_key(name="to-rotate", scopes=["chat", "models"])
        old_id = result["id"]
        new_result = key_service.rotate_key(old_id)
        # Old key is revoked
        keys = key_service.list_keys()
        old = [k for k in keys if k["id"] == old_id][0]
        assert old["enabled"] is False
        # New key works
        assert key_service.validate_key(new_result["key"]) is not None
        assert new_result["scopes"] == ["chat", "models"]

    def test_update_usage(self, key_service):
        result = key_service.create_key(name="usage-test", scopes=["chat"])
        key_service.update_usage(result["id"], tokens_used=150)
        key_service.update_usage(result["id"], tokens_used=50)
        keys = key_service.list_keys()
        assert keys[0]["usage"]["total_requests"] == 2
        assert keys[0]["usage"]["total_tokens"] == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/henry/Github/Github_desktop/local-ai-platform/.claude/worktrees/angry-dubinsky && python -m pytest tests/test_api_keys.py -v`
Expected: ImportError — `api.services.api_key_service` does not exist

- [ ] **Step 3: Implement the API key service**

Create `api/services/api_key_service.py`:

```python
#!/usr/bin/env python3
"""
API Key Service — CRUD, hashing, validation, YAML persistence
"""

import hashlib
import os
import secrets
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml


def _slug(name: str) -> str:
    """Convert name to URL-safe slug"""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of a raw API key"""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class APIKeyService:
    """Manages API keys with YAML file persistence"""

    def __init__(self, config_dir: Optional[str] = None):
        if config_dir:
            self._config_dir = Path(config_dir)
        else:
            self._config_dir = Path(
                os.getenv("DATA_CONFIG_DIR", "data/config")
            )
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._config_dir / "api_keys.yaml"

    def _load(self) -> list:
        if not self._file.exists():
            return []
        data = yaml.safe_load(self._file.read_text()) or {}
        return data.get("keys", [])

    def _save(self, keys: list) -> None:
        self._file.write_text(yaml.dump({"keys": keys}, default_flow_style=False))

    def create_key(
        self,
        name: str,
        scopes: list[str],
        rate_limit_rpm: Optional[int] = None,
        expires_at: Optional[str] = None,
    ) -> dict:
        """Create a new API key. Returns dict with full key (shown once)."""
        slug = _slug(name)
        random_part = secrets.token_hex(16)
        raw_key = f"sk-{slug}-{random_part}"
        prefix = f"sk-{slug}-"
        key_id = f"key_{secrets.token_hex(6)}"

        entry = {
            "id": key_id,
            "name": name,
            "key_hash": _hash_key(raw_key),
            "prefix": prefix,
            "last_four": raw_key[-4:],
            "created_at": _now_iso(),
            "last_used_at": None,
            "expires_at": expires_at,
            "rate_limit_rpm": rate_limit_rpm,
            "scopes": scopes,
            "enabled": True,
            "usage": {"total_requests": 0, "total_tokens": 0},
        }

        keys = self._load()
        keys.append(entry)
        self._save(keys)

        return {"id": key_id, "name": name, "key": raw_key, "scopes": scopes}

    def validate_key(self, raw_key: str) -> Optional[dict]:
        """Validate a raw key. Returns key metadata if valid, None otherwise."""
        key_hash = _hash_key(raw_key)
        keys = self._load()

        for k in keys:
            if k["key_hash"] == key_hash:
                if not k["enabled"]:
                    return None
                if k.get("expires_at"):
                    expires = datetime.fromisoformat(k["expires_at"])
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) > expires:
                        return None
                return {
                    "id": k["id"],
                    "name": k["name"],
                    "scopes": k["scopes"],
                    "rate_limit_rpm": k.get("rate_limit_rpm"),
                }
        return None

    def revoke_key(self, key_id: str) -> bool:
        """Disable a key by ID."""
        keys = self._load()
        for k in keys:
            if k["id"] == key_id:
                k["enabled"] = False
                self._save(keys)
                return True
        return False

    def rotate_key(self, key_id: str) -> dict:
        """Revoke old key, create new one with same settings."""
        keys = self._load()
        old = None
        for k in keys:
            if k["id"] == key_id:
                old = k
                break
        if not old:
            raise ValueError(f"Key not found: {key_id}")

        self.revoke_key(key_id)
        return self.create_key(
            name=old["name"],
            scopes=old["scopes"],
            rate_limit_rpm=old.get("rate_limit_rpm"),
            expires_at=old.get("expires_at"),
        )

    def list_keys(self) -> list[dict]:
        """List all keys with masked values (no hashes or full keys)."""
        keys = self._load()
        return [
            {
                "id": k["id"],
                "name": k["name"],
                "prefix": k["prefix"],
                "last_four": k.get("last_four", ""),
                "created_at": k["created_at"],
                "last_used_at": k.get("last_used_at"),
                "expires_at": k.get("expires_at"),
                "rate_limit_rpm": k.get("rate_limit_rpm"),
                "scopes": k["scopes"],
                "enabled": k["enabled"],
                "usage": k.get("usage", {"total_requests": 0, "total_tokens": 0}),
            }
            for k in keys
        ]

    def update_usage(self, key_id: str, tokens_used: int = 0) -> None:
        """Increment request count and token usage."""
        keys = self._load()
        for k in keys:
            if k["id"] == key_id:
                usage = k.setdefault("usage", {"total_requests": 0, "total_tokens": 0})
                usage["total_requests"] += 1
                usage["total_tokens"] += tokens_used
                k["last_used_at"] = _now_iso()
                self._save(keys)
                return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/henry/Github/Github_desktop/local-ai-platform/.claude/worktrees/angry-dubinsky && python -m pytest tests/test_api_keys.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/api_key_service.py tests/test_api_keys.py
git commit -m "feat: add API key service with YAML persistence and tests"
```

---

## Task 2: API Key Router

**Files:**
- Create: `api/routers/api_keys.py`
- Modify: `api/main.py:18,100-106`
- Modify: `.env.example:7-9`
- Test: `tests/test_api_keys.py` (append)

- [ ] **Step 1: Add router tests to `tests/test_api_keys.py`**

Append to `tests/test_api_keys.py`:

```python
import importlib
from fastapi.testclient import TestClient

# ── Router Tests ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def api_client():
    """Test client with master key set"""
    os.environ["ENABLE_API_AUTH"] = "true"
    os.environ["MASTER_API_KEY"] = "master-test-key-12345"
    os.environ["RATE_LIMIT_RPM"] = "0"
    # Force re-import to pick up new env
    import importlib
    import api.main
    importlib.reload(api.main)
    from api.main import app
    return TestClient(app)


class TestKeyRouter:
    MASTER_HEADER = {"Authorization": "Bearer master-test-key-12345"}

    def test_create_key_via_api(self, api_client):
        resp = api_client.post(
            "/api/keys",
            json={"name": "router-test", "scopes": ["chat"]},
            headers=self.MASTER_HEADER,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["key"].startswith("sk-router-test-")
        assert data["id"].startswith("key_")

    def test_list_keys_via_api(self, api_client):
        resp = api_client.get("/api/keys", headers=self.MASTER_HEADER)
        assert resp.status_code == 200
        keys = resp.json()
        assert isinstance(keys, list)
        assert len(keys) >= 1
        # Keys should be masked — no key_hash field
        for k in keys:
            assert "key_hash" not in k

    def test_create_key_requires_master_key(self, api_client):
        resp = api_client.post(
            "/api/keys",
            json={"name": "unauth", "scopes": ["chat"]},
        )
        assert resp.status_code == 401

    def test_revoke_key_via_api(self, api_client):
        # Create then revoke
        create_resp = api_client.post(
            "/api/keys",
            json={"name": "to-delete", "scopes": ["chat"]},
            headers=self.MASTER_HEADER,
        )
        key_id = create_resp.json()["id"]
        del_resp = api_client.delete(
            f"/api/keys/{key_id}", headers=self.MASTER_HEADER
        )
        assert del_resp.status_code == 200

    def test_usage_endpoint(self, api_client):
        create_resp = api_client.post(
            "/api/keys",
            json={"name": "usage-key", "scopes": ["chat"]},
            headers=self.MASTER_HEADER,
        )
        key_id = create_resp.json()["id"]
        resp = api_client.get(
            f"/api/keys/{key_id}/usage", headers=self.MASTER_HEADER
        )
        assert resp.status_code == 200
        assert resp.json()["total_requests"] == 0
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python -m pytest tests/test_api_keys.py::TestKeyRouter -v`
Expected: FAIL — router not registered

- [ ] **Step 3: Create the API keys router**

Create `api/routers/api_keys.py`:

```python
#!/usr/bin/env python3
"""
API Keys Router — Key management endpoints (master key protected)
"""

import os
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services.api_key_service import APIKeyService

router = APIRouter(prefix="/api/keys", tags=["api-keys"])
_service = APIKeyService()

MASTER_API_KEY = os.getenv("MASTER_API_KEY", "")


def _require_master(request: Request):
    """Check that the request carries the master API key."""
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    if not token or not MASTER_API_KEY or token != MASTER_API_KEY:
        raise HTTPException(status_code=401, detail="Master API key required")


class CreateKeyRequest(BaseModel):
    name: str = Field(..., description="Human-readable key name")
    scopes: List[str] = Field(..., description="Endpoint access scopes")
    rate_limit_rpm: Optional[int] = Field(None, description="Per-key rate limit")
    expires_at: Optional[str] = Field(None, description="ISO 8601 expiration")


@router.post("", status_code=201)
async def create_key(body: CreateKeyRequest, request: Request):
    """Create a new API key (master key required)"""
    _require_master(request)
    result = _service.create_key(
        name=body.name,
        scopes=body.scopes,
        rate_limit_rpm=body.rate_limit_rpm,
        expires_at=body.expires_at,
    )
    return result


@router.get("")
async def list_keys(request: Request):
    """List all API keys (masked)"""
    _require_master(request)
    return _service.list_keys()


@router.delete("/{key_id}")
async def revoke_key(key_id: str, request: Request):
    """Revoke an API key"""
    _require_master(request)
    if not _service.revoke_key(key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    return {"status": "revoked", "id": key_id}


@router.post("/{key_id}/rotate")
async def rotate_key(key_id: str, request: Request):
    """Rotate an API key (revoke old, create new with same settings)"""
    _require_master(request)
    try:
        result = _service.rotate_key(key_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Key not found")
    return result


@router.get("/{key_id}/usage")
async def get_usage(key_id: str, request: Request):
    """Get usage statistics for a key"""
    _require_master(request)
    keys = _service.list_keys()
    for k in keys:
        if k["id"] == key_id:
            return k["usage"]
    raise HTTPException(status_code=404, detail="Key not found")
```

- [ ] **Step 4: Register the router in `api/main.py`**

In `api/main.py`, add to the imports (line 18):
```python
from .routers import chat, completions, models, inventory, exports, graph, workflows, api_keys
```

Add after line 106:
```python
app.include_router(api_keys.router)
```

- [ ] **Step 5: Add `/api/keys` to PUBLIC_PATHS exclusion and master key support in middleware**

In `api/middleware.py`, update line 22 to also load the master key:
```python
MASTER_API_KEY = os.getenv("MASTER_API_KEY", "")
```

The key management endpoints use their own `_require_master` check, so the existing auth middleware should allow master key through. Update the `dispatch` method (line 76) to also accept the master key:

```python
        if provided_key != API_KEY and provided_key != MASTER_API_KEY:
```

- [ ] **Step 6: Update `.env.example`**

Replace lines 7-9 of `.env.example`:
```
# Authentication (set ENABLE_API_AUTH=true to require API keys)
API_KEY=your-api-key-here
MASTER_API_KEY=your-master-key-for-key-management
ENABLE_API_AUTH=false
```

- [ ] **Step 7: Run all tests to verify they pass**

Run: `python -m pytest tests/test_api_keys.py -v`
Expected: All 14 tests PASS (9 service + 5 router)

- [ ] **Step 8: Commit**

```bash
git add api/routers/api_keys.py api/main.py api/middleware.py .env.example tests/test_api_keys.py
git commit -m "feat: add API key management router with master key protection"
```

---

## Task 3: Upgrade Auth Middleware for Multi-Key Validation

**Files:**
- Modify: `api/middleware.py:45-88`
- Test: `tests/test_api_keys.py` (append)

- [ ] **Step 1: Add middleware integration tests**

Append to `tests/test_api_keys.py`:

```python
class TestMultiKeyAuth:
    """Test that created keys work for authenticating API requests"""

    MASTER_HEADER = {"Authorization": "Bearer master-test-key-12345"}

    def test_created_key_authenticates_chat(self, api_client):
        # Create a key with chat scope
        resp = api_client.post(
            "/api/keys",
            json={"name": "auth-test", "scopes": ["chat"]},
            headers=self.MASTER_HEADER,
        )
        raw_key = resp.json()["key"]

        # Use it to access /v1/models (should work — models is public-ish)
        resp = api_client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200

    def test_revoked_key_rejected(self, api_client):
        resp = api_client.post(
            "/api/keys",
            json={"name": "revoke-auth", "scopes": ["chat"]},
            headers=self.MASTER_HEADER,
        )
        raw_key = resp.json()["key"]
        key_id = resp.json()["id"]

        # Revoke it
        api_client.delete(f"/api/keys/{key_id}", headers=self.MASTER_HEADER)

        # Should be rejected
        resp = api_client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api_keys.py::TestMultiKeyAuth -v`
Expected: FAIL — middleware still uses simple string comparison

- [ ] **Step 3: Update middleware to use API key service**

Replace the `APIKeyAuthMiddleware.dispatch` method in `api/middleware.py` (lines 45-88):

```python
    async def dispatch(self, request: Request, call_next: Callable):
        # Skip if auth is disabled
        if not ENABLE_API_AUTH:
            return await call_next(request)

        # Skip public paths
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Extract key from header or query param
        auth_header = request.headers.get("Authorization", "")
        query_key = request.query_params.get("api_key", "")

        provided_key = ""
        if auth_header.startswith("Bearer "):
            provided_key = auth_header[7:]
        elif query_key:
            provided_key = query_key

        if not provided_key:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "API key required. Provide via 'Authorization: Bearer <key>' header.",
                        "type": "authentication_error",
                        "code": "missing_api_key",
                    }
                },
            )

        # Accept master key
        if MASTER_API_KEY and provided_key == MASTER_API_KEY:
            return await call_next(request)

        # Accept legacy single key (backward compat)
        if API_KEY and provided_key == API_KEY:
            return await call_next(request)

        # Try multi-key validation
        from api.services.api_key_service import APIKeyService
        svc = APIKeyService()
        meta = svc.validate_key(provided_key)
        if meta:
            # Store key metadata on request state for downstream use
            request.state.api_key_meta = meta
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "message": "Invalid API key.",
                    "type": "authentication_error",
                    "code": "invalid_api_key",
                }
            },
        )
```

Also add after line 22:
```python
MASTER_API_KEY = os.getenv("MASTER_API_KEY", "")
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/test_api_keys.py -v`
Expected: All 16 tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/middleware.py tests/test_api_keys.py
git commit -m "feat: upgrade auth middleware to support multi-key validation"
```

---

## Task 4: Plugin Service

**Files:**
- Create: `api/services/plugin_service.py`
- Create: `plugins/example-web-search/plugin.yaml`
- Create: `plugins/example-web-search/skills/search-expert.md`
- Create: `plugins/example-web-search/tools/web_search.py`
- Test: `tests/test_plugins.py`

- [ ] **Step 1: Create example plugin files**

Create `plugins/example-web-search/plugin.yaml`:

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
      - keyword: "look up"
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

Create `plugins/example-web-search/skills/search-expert.md`:

```markdown
---
name: Search Expert
description: Augments the LLM with web search best practices
inject: system
---

You have access to a web search tool called `web_search`.
When the user asks about current events, recent data, or anything
that benefits from live information, use the web_search tool before answering.

Always cite your sources with URLs when presenting search results.
```

Create `plugins/example-web-search/tools/web_search.py`:

```python
"""Example web search tool for the plugin system"""


def execute(query: str, max_results: int = 5) -> dict:
    """
    Search the web and return results.

    This is a placeholder implementation. Replace with actual search
    logic (e.g., calling the platform's search_service).
    """
    return {
        "results": [
            {
                "title": f"Result for: {query}",
                "url": f"https://example.com/search?q={query}",
                "snippet": f"This is a placeholder result for '{query}'. "
                "Replace this tool with a real search implementation.",
            }
        ],
        "query": query,
        "total": 1,
    }
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_plugins.py`:

```python
#!/usr/bin/env python3
"""Tests for Plugin Service"""

import os
import pytest
import tempfile
import shutil
from pathlib import Path

import yaml


@pytest.fixture
def plugin_dir():
    """Temp plugin directory with example plugin"""
    tmpdir = tempfile.mkdtemp()
    # Create a test plugin
    plugin_path = Path(tmpdir) / "test-plugin"
    plugin_path.mkdir()
    (plugin_path / "plugin.yaml").write_text(yaml.dump({
        "name": "Test Plugin",
        "id": "test-plugin",
        "version": "1.0.0",
        "description": "A test plugin",
        "author": "test",
        "skills": [{
            "id": "test-skill",
            "file": "skills/greeting.md",
            "triggers": [{"keyword": "hello"}, {"manual": True}],
        }],
        "tools": [{
            "id": "echo",
            "file": "tools/echo_tool.py",
            "function": "execute",
            "description": "Echoes input back",
            "parameters": {
                "text": {"type": "string", "required": True},
            },
        }],
    }))
    skills_dir = plugin_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "greeting.md").write_text(
        "---\nname: Greeting\ndescription: Says hello\ninject: system\n---\n\nAlways greet the user warmly."
    )
    tools_dir = plugin_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "echo_tool.py").write_text(
        'def execute(text: str) -> dict:\n    return {"echo": text}\n'
    )
    yield tmpdir
    shutil.rmtree(tmpdir)


@pytest.fixture
def plugin_service(plugin_dir):
    from api.services.plugin_service import PluginService
    return PluginService(plugins_dir=plugin_dir)


class TestPluginDiscovery:
    def test_scan_finds_plugins(self, plugin_service):
        plugins = plugin_service.scan_plugins()
        assert len(plugins) == 1
        assert plugins[0]["id"] == "test-plugin"

    def test_scan_skips_disabled_dir(self, plugin_dir):
        disabled = Path(plugin_dir) / "_disabled"
        disabled.mkdir()
        (disabled / "plugin.yaml").write_text(yaml.dump({
            "name": "Disabled", "id": "disabled", "version": "1.0.0",
            "description": "Should be skipped", "author": "test",
        }))
        from api.services.plugin_service import PluginService
        svc = PluginService(plugins_dir=plugin_dir)
        plugins = svc.scan_plugins()
        assert all(p["id"] != "disabled" for p in plugins)

    def test_list_plugins(self, plugin_service):
        plugin_service.scan_plugins()
        listing = plugin_service.list_plugins()
        assert len(listing) == 1
        assert listing[0]["name"] == "Test Plugin"
        assert len(listing[0]["skills"]) == 1
        assert len(listing[0]["tools"]) == 1


class TestPluginSkills:
    def test_get_skills_by_keyword(self, plugin_service):
        plugin_service.scan_plugins()
        skills = plugin_service.get_skills("hello world")
        assert len(skills) == 1
        assert "greet the user warmly" in skills[0]["content"]
        assert skills[0]["inject"] == "system"

    def test_get_skills_no_match(self, plugin_service):
        plugin_service.scan_plugins()
        skills = plugin_service.get_skills("weather forecast")
        assert len(skills) == 0


class TestPluginTools:
    def test_call_tool(self, plugin_service):
        plugin_service.scan_plugins()
        result = plugin_service.call_tool("test-plugin", "echo", {"text": "ping"})
        assert result == {"echo": "ping"}

    def test_call_tool_unknown_plugin(self, plugin_service):
        plugin_service.scan_plugins()
        with pytest.raises(ValueError, match="Plugin not found"):
            plugin_service.call_tool("nonexistent", "echo", {})

    def test_call_tool_unknown_tool(self, plugin_service):
        plugin_service.scan_plugins()
        with pytest.raises(ValueError, match="Tool not found"):
            plugin_service.call_tool("test-plugin", "nonexistent", {})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_plugins.py -v`
Expected: ImportError — `api.services.plugin_service` does not exist

- [ ] **Step 4: Implement the plugin service**

Create `api/services/plugin_service.py`:

```python
#!/usr/bin/env python3
"""
Plugin Service — Discovery, loading, skill matching, tool invocation
"""

import importlib.util
import sys
from pathlib import Path
from typing import Optional

import yaml

from ..logging_config import logger


def _parse_skill_md(path: Path) -> dict:
    """Parse a skill markdown file with YAML frontmatter."""
    text = path.read_text()
    if not text.startswith("---"):
        return {"name": "", "description": "", "inject": "none", "content": text}

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"name": "", "description": "", "inject": "none", "content": text}

    meta = yaml.safe_load(parts[1]) or {}
    content = parts[2].strip()
    return {
        "name": meta.get("name", ""),
        "description": meta.get("description", ""),
        "inject": meta.get("inject", "none"),
        "content": content,
    }


class PluginService:
    """Discovers and manages plugins from a directory convention"""

    def __init__(self, plugins_dir: Optional[str] = None):
        self._dir = Path(plugins_dir) if plugins_dir else Path("plugins")
        self._plugins: dict = {}  # id -> plugin data
        self._tools: dict = {}    # (plugin_id, tool_id) -> loaded module

    def scan_plugins(self) -> list[dict]:
        """Scan the plugins directory for valid plugins."""
        self._plugins.clear()
        self._tools.clear()

        if not self._dir.exists():
            logger.warning(f"Plugins directory not found: {self._dir}")
            return []

        found = []
        for child in sorted(self._dir.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith("_"):
                continue

            manifest_path = child / "plugin.yaml"
            if not manifest_path.exists():
                logger.warning(f"Skipping {child.name}: no plugin.yaml")
                continue

            try:
                manifest = yaml.safe_load(manifest_path.read_text())
            except yaml.YAMLError as e:
                logger.error(f"Invalid YAML in {manifest_path}: {e}")
                continue

            plugin_id = manifest.get("id", child.name)

            # Load skills
            skills = []
            for skill_def in manifest.get("skills", []):
                skill_path = child / skill_def["file"]
                if skill_path.exists():
                    parsed = _parse_skill_md(skill_path)
                    skills.append({
                        "id": skill_def["id"],
                        "triggers": skill_def.get("triggers", []),
                        **parsed,
                    })
                else:
                    logger.warning(f"Skill file not found: {skill_path}")

            # Pre-load tool modules
            tools = []
            for tool_def in manifest.get("tools", []):
                tool_path = child / tool_def["file"]
                if tool_path.exists():
                    module = self._load_tool_module(plugin_id, tool_def["id"], tool_path)
                    if module:
                        self._tools[(plugin_id, tool_def["id"])] = {
                            "module": module,
                            "function": tool_def.get("function", "execute"),
                        }
                    tools.append({
                        "id": tool_def["id"],
                        "description": tool_def.get("description", ""),
                        "parameters": tool_def.get("parameters", {}),
                    })
                else:
                    logger.warning(f"Tool file not found: {tool_path}")

            plugin_data = {
                "id": plugin_id,
                "name": manifest.get("name", plugin_id),
                "version": manifest.get("version", "0.0.0"),
                "description": manifest.get("description", ""),
                "author": manifest.get("author", "unknown"),
                "path": str(child),
                "skills": skills,
                "tools": tools,
            }
            self._plugins[plugin_id] = plugin_data
            found.append(plugin_data)
            logger.info(
                f"Loaded plugin: {plugin_id} "
                f"({len(skills)} skills, {len(tools)} tools)"
            )

        return found

    def _load_tool_module(self, plugin_id: str, tool_id: str, path: Path):
        """Dynamically load a Python tool module."""
        module_name = f"plugin_{plugin_id}_{tool_id}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            logger.error(f"Failed to load tool {plugin_id}/{tool_id}: {e}")
            return None

    def list_plugins(self) -> list[dict]:
        """List all discovered plugins."""
        return list(self._plugins.values())

    def get_skills(self, user_message: str) -> list[dict]:
        """Find skills whose keyword triggers match the user message."""
        matched = []
        msg_lower = user_message.lower()
        for plugin in self._plugins.values():
            for skill in plugin["skills"]:
                for trigger in skill.get("triggers", []):
                    kw = trigger.get("keyword", "")
                    if kw and kw.lower() in msg_lower:
                        matched.append(skill)
                        break
        return matched

    def call_tool(self, plugin_id: str, tool_id: str, params: dict) -> dict:
        """Execute a tool function and return its result."""
        if plugin_id not in self._plugins:
            raise ValueError(f"Plugin not found: {plugin_id}")

        key = (plugin_id, tool_id)
        if key not in self._tools:
            raise ValueError(f"Tool not found: {plugin_id}/{tool_id}")

        entry = self._tools[key]
        func = getattr(entry["module"], entry["function"])
        return func(**params)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_plugins.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add api/services/plugin_service.py tests/test_plugins.py plugins/
git commit -m "feat: add plugin service with skill matching and tool invocation"
```

---

## Task 5: Plugin Router & Main Integration

**Files:**
- Create: `api/routers/plugins.py`
- Modify: `api/main.py:18,50-67,100-106`
- Test: `tests/test_plugins.py` (append)

- [ ] **Step 1: Add router tests**

Append to `tests/test_plugins.py`:

```python
import importlib
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def plugin_client():
    """Test client with plugins loaded"""
    os.environ["ENABLE_API_AUTH"] = "false"
    os.environ["RATE_LIMIT_RPM"] = "0"
    # Point to the real plugins directory
    os.environ["PLUGINS_DIR"] = str(
        Path(__file__).parent.parent / "plugins"
    )
    import api.main
    importlib.reload(api.main)
    from api.main import app
    return TestClient(app)


class TestPluginRouter:
    def test_list_plugins(self, plugin_client):
        resp = plugin_client.get("/api/plugins")
        assert resp.status_code == 200
        plugins = resp.json()
        assert isinstance(plugins, list)
        # Should have at least the example plugin
        assert any(p["id"] == "web-search" for p in plugins)

    def test_get_plugin_detail(self, plugin_client):
        resp = plugin_client.get("/api/plugins/web-search")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "web-search"
        assert len(data["tools"]) >= 1

    def test_invoke_tool(self, plugin_client):
        resp = plugin_client.post(
            "/api/plugins/web-search/tools/web_search",
            json={"query": "test query", "max_results": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data

    def test_get_unknown_plugin(self, plugin_client):
        resp = plugin_client.get("/api/plugins/nonexistent")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_plugins.py::TestPluginRouter -v`
Expected: FAIL — router not registered

- [ ] **Step 3: Create the plugins router**

Create `api/routers/plugins.py`:

```python
#!/usr/bin/env python3
"""
Plugins Router — List plugins and invoke tools
"""

import os
from fastapi import APIRouter, HTTPException

from ..services.plugin_service import PluginService

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

_plugins_dir = os.getenv("PLUGINS_DIR", "plugins")
_service = PluginService(plugins_dir=_plugins_dir)


@router.on_event("startup")
async def _startup():
    _service.scan_plugins()


@router.get("")
async def list_plugins():
    """List all discovered plugins"""
    return _service.list_plugins()


@router.get("/{plugin_id}")
async def get_plugin(plugin_id: str):
    """Get plugin details"""
    plugins = _service.list_plugins()
    for p in plugins:
        if p["id"] == plugin_id:
            return p
    raise HTTPException(status_code=404, detail="Plugin not found")


@router.post("/{plugin_id}/tools/{tool_id}")
async def invoke_tool(plugin_id: str, tool_id: str, params: dict):
    """Invoke a plugin tool"""
    try:
        result = _service.call_tool(plugin_id, tool_id, params)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result
```

- [ ] **Step 4: Register the router and init plugins in `api/main.py`**

Update imports (line 18):
```python
from .routers import chat, completions, models, inventory, exports, graph, workflows, api_keys, plugins
```

Add after the api_keys router inclusion:
```python
app.include_router(plugins.router)
```

- [ ] **Step 5: Run all tests**

Run: `python -m pytest tests/test_plugins.py -v`
Expected: All 12 tests PASS

- [ ] **Step 6: Commit**

```bash
git add api/routers/plugins.py api/main.py tests/test_plugins.py
git commit -m "feat: add plugins router with tool invocation endpoint"
```

---

## Task 6: Chat Integration with Plugins

**Files:**
- Modify: `api/routers/chat.py:16-20,42-50`
- Test: `tests/test_plugins.py` (append)

- [ ] **Step 1: Add chat integration test**

Append to `tests/test_plugins.py`:

```python
class TestChatPluginIntegration:
    def test_skill_triggers_inject_system_prompt(self):
        """Verify that plugin skills are found for matching messages"""
        from api.services.plugin_service import PluginService
        svc = PluginService(plugins_dir=str(Path(__file__).parent.parent / "plugins"))
        svc.scan_plugins()

        # "search" should trigger the search-expert skill
        skills = svc.get_skills("please search for quantum computing")
        assert len(skills) >= 1
        assert any("web_search" in s["content"] for s in skills)

    def test_no_skill_for_unmatched_message(self):
        from api.services.plugin_service import PluginService
        svc = PluginService(plugins_dir=str(Path(__file__).parent.parent / "plugins"))
        svc.scan_plugins()

        skills = svc.get_skills("what is the meaning of life")
        assert len(skills) == 0
```

- [ ] **Step 2: Run tests to verify they pass (skills already work)**

Run: `python -m pytest tests/test_plugins.py::TestChatPluginIntegration -v`
Expected: PASS (plugin service already supports this)

- [ ] **Step 3: Integrate plugins into chat endpoint**

In `api/routers/chat.py`, add import after line 16:
```python
from ..services.plugin_service import PluginService
```

Add after line 20 (`ollama_service = OllamaService()`):
```python
_plugin_service = PluginService()
_plugin_service.scan_plugins()
```

In the `chat_completions` function, after the messages conversion (line 50), before the web search block (line 53), add:

```python
    # ── Plugin Skill Injection ────────────────────────────────────────
    last_user_content = ""
    for msg in reversed(messages):
        if msg["role"] == "user":
            last_user_content = msg["content"]
            break

    matched_skills = _plugin_service.get_skills(last_user_content)
    for skill in matched_skills:
        if skill["inject"] == "system":
            messages = [{"role": "system", "content": skill["content"]}] + messages
        elif skill["inject"] == "context":
            # Append as context after the last system message
            messages.append({"role": "system", "content": skill["content"]})
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/test_plugins.py -v`
Expected: All 14 tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/routers/chat.py tests/test_plugins.py
git commit -m "feat: integrate plugin skills into chat completions"
```

---

## Task 7: Cortex Color Rebrand

**Files:**
- Modify: `api/static/index.html:13-40,54-91`

- [ ] **Step 1: Replace CSS design tokens**

In `api/static/index.html`, replace lines 13-40 (the `:root` block) with:

```css
:root {
  /* Cortex Brand — dark mode palette */
  --bg-deep: #0a0a0a;
  --bg: #141414;
  --bg-panel: rgba(20, 20, 20, 0.9);
  --border: #2a2a2a;
  --border-glow: #00CC6618;
  --cyan: #00CC66;              /* Cortex Green — primary accent */
  --cyan-dim: #00CC6660;
  --cyan-ghost: #00CC6615;
  --amber: #19AA61;             /* Cortex Secondary Green */
  --amber-dim: #19AA6160;
  --green: #00CC66;             /* Cortex Green — success/status */
  --green-dim: #00CC6660;
  --red: #FA582D;               /* Cortex Orange — danger/error */
  --red-dim: #FA582D60;
  --purple: #00C0E8;            /* Cortex Cyan — info accent */
  --purple-dim: #00C0E860;
  --text: #e0e0e0;
  --text-dim: #8D8D8D;
  --text-muted: #555555;
  --mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;
  --sans: 'Space Grotesk', 'TT Hoves', system-ui, sans-serif;
  --glow-cyan: 0 0 12px #00CC6630, 0 0 4px #00CC6620;
  --glow-green: 0 0 12px #00CC6630, 0 0 4px #00CC6620;
  --glow-red: 0 0 12px #FA582D30, 0 0 4px #FA582D20;
  --glow-amber: 0 0 12px #19AA6130, 0 0 4px #19AA6120;
}
```

- [ ] **Step 2: Update ambient background gradient**

Replace the `body::before` background (lines 59-62) with:

```css
  background:
    radial-gradient(ellipse 80% 50% at 20% 20%, #00CC6606 0%, transparent 60%),
    radial-gradient(ellipse 60% 40% at 80% 80%, #19AA6104 0%, transparent 60%),
    linear-gradient(180deg, var(--bg-deep) 0%, #141414 100%);
```

- [ ] **Step 3: Remove grid overlay and scanline**

Remove the `body::after` block (lines 66-77, the grid pattern):
```css
/* DELETE the entire body::after block */
```

Remove the `@keyframes scanline` and `.scanline` blocks (lines 79-91):
```css
/* DELETE the scanline animation and class */
```

Also search for the scanline `<div>` in the HTML body and remove it:
```html
<!-- DELETE: <div class="scanline"></div> -->
```

- [ ] **Step 4: Verify the page loads correctly**

Start the dev server and confirm the dashboard renders with the new colors:

Run: `cd /Users/henry/Github/Github_desktop/local-ai-platform/.claude/worktrees/angry-dubinsky && python -m api.main &`
Then: `curl -s http://localhost:8000/ | head -50`
Expected: HTML with new Cortex color values in CSS

Kill the server after verification.

- [ ] **Step 5: Commit**

```bash
git add api/static/index.html
git commit -m "style: rebrand dashboard to Cortex green palette"
```

---

## Task 8: Final Integration Verification

**Files:** None (verification only)

- [ ] **Step 1: Run all tests**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests pass (existing + new)

- [ ] **Step 2: Verify API key flow end-to-end**

```bash
# Start server with auth enabled
ENABLE_API_AUTH=true MASTER_API_KEY=test-master python -m api.main &

# Create a key
curl -s -X POST http://localhost:8000/api/keys \
  -H "Authorization: Bearer test-master" \
  -H "Content-Type: application/json" \
  -d '{"name": "e2e-test", "scopes": ["chat", "models"]}'

# Use the returned key to list models
curl -s http://localhost:8000/v1/models \
  -H "Authorization: Bearer <key-from-above>"

# List keys
curl -s http://localhost:8000/api/keys \
  -H "Authorization: Bearer test-master"
```

Expected: Key creation returns full key, model listing works with that key, key list shows masked values.

- [ ] **Step 3: Verify plugin system**

```bash
curl -s http://localhost:8000/api/plugins | python -m json.tool

curl -s -X POST http://localhost:8000/api/plugins/web-search/tools/web_search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "max_results": 3}'
```

Expected: Plugin list shows web-search plugin, tool invocation returns results.

- [ ] **Step 4: Commit any remaining fixes and tag**

```bash
git add -A
git commit -m "chore: final integration verification"
```
