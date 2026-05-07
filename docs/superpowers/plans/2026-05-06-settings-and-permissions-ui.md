# Settings & Permissions UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Admin dropdown plus three new panels (API Keys, Plugins, Exports) so the three orphaned routers — `/api/keys`, `/api/plugins`, `/api/exports` — become reachable from the dashboard with default-deny master-key auth.

**Architecture:** Backend gets four small additions (refactor `_require_master` to middleware, add `/api/keys/scopes`, `/api/keys/audit`, `/api/exports/zip`, gate all `/api/plugins/*` endpoints). All UI work lands in the existing single-file SPA `api/static/index.html` as named IIFE modules at the bottom of the script block. Tests follow the existing pattern: BeautifulSoup-backed markup assertions in `tests/ui/test_static_markup.py` plus FastAPI `TestClient` router unit tests.

**Tech Stack:** FastAPI, Pydantic, vanilla ES6 (no build step), CSS custom properties, pytest + httpx + BeautifulSoup4, existing vendored d3 v7 (for usage sparklines).

**Spec:** `docs/superpowers/specs/2026-05-06-settings-and-permissions-ui-design.md` (commit `4ef88de`).

---

## File Structure

**Modified:**
- `api/main.py` — no changes if routers stay registered the same way (verify after Task 4)
- `api/middleware.py` — add `require_master_key(request)` helper extracted from `api/routers/api_keys.py`
- `api/routers/api_keys.py` — replace `_require_master` with import; add `/scopes` and `/audit` endpoints
- `api/routers/plugins.py` — add `Depends(require_master_key)` to all endpoints
- `api/routers/exports.py` — add `/zip` streaming endpoint
- `api/services/api_key_service.py` — add `_audit` ring buffer + `_log()` calls in create/rotate/revoke
- `api/static/index.html` — admin dropdown, three panels, AdminMenu + AdminAuth + renderMarkdown modules, modal markup, ~600 lines added
- `tests/ui/test_static_markup.py` — extend with ~12 new assertions
- `tests/test_api_keys.py` — extend with scopes/audit/key-reveal tests
- `tests/test_exports.py` — extend with zip endpoint tests
- `tests/test_plugins.py` — extend with master-key gate tests; existing tests need master-key header

**Created:**
- None. All new code lands in existing modules per the single-file SPA constraint.

---

## Prerequisites

Before Task 1 verify the working baseline:

```bash
cd /Users/henry/Github/Github_desktop/local-ai-platform
source venv/bin/activate
pytest tests/ -q --ignore=tests/e2e 2>&1 | tail -10
```

Expected: ~21 UI tests pass; ~250 total tests pass (a few may be skipped without live Ollama).

Take note of the baseline pass count — you'll compare against it at the end of every task to make sure you didn't break anything.

---

## Phase 1: Backend additions

These four backend changes ship first because the UI work depends on them. Each is small (≤80 lines) and independently testable.

---

### Task 1: Extract `require_master_key` to middleware

**Why first:** Both `api_keys.py` and `plugins.py` need this helper. Extracting it removes a circular-import risk and gives Plugins a clean dependency to import.

**Files:**
- Modify: `api/middleware.py`
- Modify: `api/routers/api_keys.py:18-24` — replace local `_require_master` with import
- Test: `tests/test_api_keys.py` (existing tests must still pass)

- [ ] **Step 1: Add the helper to `api/middleware.py`**

Append to `api/middleware.py` (after the existing `SCOPE_MAP` block):

```python
def require_master_key(request: Request) -> None:
    """Validate that the request carries the master API key.

    Raises HTTPException(401) if the key is missing or doesn't match.
    Use as a FastAPI dependency:

        @router.get("", dependencies=[Depends(require_master_key)])
    """
    import hmac
    master_key = os.getenv("MASTER_API_KEY", "")
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    if not token or not master_key or not hmac.compare_digest(token, master_key):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Master API key required")
```

Make sure `Request` is imported at the top of `api/middleware.py` (it already is via FastAPI; verify with `grep -n "from fastapi" api/middleware.py`).

- [ ] **Step 2: Replace `_require_master` in `api/routers/api_keys.py`**

At `api/routers/api_keys.py:1-24`, change:

```python
import hmac
import os
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services.api_key_service import APIKeyService

router = APIRouter(prefix="/api/keys", tags=["api-keys"])
_service = APIKeyService()

def _require_master(request: Request):
    """Check that the request carries the master API key."""
    master_key = os.getenv("MASTER_API_KEY", "")
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    if not token or not master_key or not hmac.compare_digest(token, master_key):
        raise HTTPException(status_code=401, detail="Master API key required")
```

to:

```python
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..middleware import require_master_key as _require_master
from ..services.api_key_service import APIKeyService

router = APIRouter(prefix="/api/keys", tags=["api-keys"])
_service = APIKeyService()
```

Keep the `_require_master` alias so the existing endpoint bodies (`_require_master(request)`) keep working without further edits.

- [ ] **Step 3: Run existing tests to verify nothing broke**

```bash
pytest tests/test_api_keys.py -v
```

Expected: all existing tests still pass.

- [ ] **Step 4: Smoke-test the dependency form**

Append a one-shot test to `tests/test_api_keys.py` (any place after the existing fixtures):

```python
def test_require_master_helper_lives_in_middleware():
    """Smoke: helper is importable from middleware so plugins.py can use it."""
    from api.middleware import require_master_key
    assert callable(require_master_key)
```

Run:

```bash
pytest tests/test_api_keys.py::test_require_master_helper_lives_in_middleware -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/middleware.py api/routers/api_keys.py tests/test_api_keys.py
git commit -m "$(cat <<'EOF'
refactor(auth): extract require_master_key to middleware

Hoists the master-key check out of api_keys.py so plugins.py (next
commit) can depend on it without a router-to-router import. Existing
endpoints keep working via an aliased import.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Add `/api/keys/scopes` endpoint

**Files:**
- Modify: `api/routers/api_keys.py`
- Modify: `tests/test_api_keys.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_keys.py`:

```python
class TestScopesEndpoint:
    def test_scopes_requires_master(self, client_no_master):
        # client_no_master fixture defined below — TestClient with MASTER_API_KEY unset.
        resp = client_no_master.get("/api/keys/scopes")
        assert resp.status_code == 401

    def test_scopes_returns_known_scopes(self, client_with_master):
        resp = client_with_master.get(
            "/api/keys/scopes",
            headers={"Authorization": "Bearer test-master"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "scopes" in data
        # The scopes used by SCOPE_MAP today.
        for required in ["chat", "completions", "models", "memory", "documents"]:
            assert required in data["scopes"], f"missing scope {required}"
```

If `client_no_master` and `client_with_master` fixtures don't already exist, add them at the top of the file (right after the `key_service` fixture):

```python
@pytest.fixture
def client_with_master(monkeypatch):
    """TestClient with MASTER_API_KEY set to 'test-master'."""
    monkeypatch.setenv("MASTER_API_KEY", "test-master")
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    import importlib, api.middleware, api.main
    importlib.reload(api.middleware)
    importlib.reload(api.main)
    from api.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def client_no_master(monkeypatch):
    """TestClient with MASTER_API_KEY unset."""
    monkeypatch.delenv("MASTER_API_KEY", raising=False)
    monkeypatch.setenv("ENABLE_API_AUTH", "false")
    import importlib, api.middleware, api.main
    importlib.reload(api.middleware)
    importlib.reload(api.main)
    from api.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api_keys.py::TestScopesEndpoint -v
```

Expected: 2 FAILS — endpoint not registered yet (404).

- [ ] **Step 3: Implement the endpoint**

Add to `api/routers/api_keys.py` (after the existing endpoints, before any private helpers at the bottom):

```python
@router.get("/scopes")
async def list_scopes(request: Request):
    """Return the scope identifiers known to the middleware.

    Master-key gated for consistency with the rest of /api/keys/*.
    """
    _require_master(request)
    from ..middleware import SCOPE_MAP
    # SCOPE_MAP values are scope names; deduplicate while preserving insertion order.
    scopes = list(dict.fromkeys(SCOPE_MAP.values()))
    return {"scopes": scopes}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_api_keys.py::TestScopesEndpoint -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routers/api_keys.py tests/test_api_keys.py
git commit -m "$(cat <<'EOF'
feat(api-keys): add /api/keys/scopes endpoint

Returns the scope identifiers known to the middleware so the upcoming
Settings & Permissions UI can render scope chips without hardcoding the
list. Master-key gated for consistency.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Audit ring buffer + `/api/keys/audit` endpoint

**Files:**
- Modify: `api/services/api_key_service.py`
- Modify: `api/routers/api_keys.py`
- Modify: `tests/test_api_keys.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_api_keys.py`:

```python
class TestAuditLog:
    def test_audit_requires_master(self, client_no_master):
        resp = client_no_master.get("/api/keys/audit")
        assert resp.status_code == 401

    def test_audit_starts_empty(self, client_with_master):
        resp = client_with_master.get(
            "/api/keys/audit",
            headers={"Authorization": "Bearer test-master"},
        )
        assert resp.status_code == 200
        # New process — should be empty unless the test order changes.
        assert isinstance(resp.json(), list)

    def test_audit_records_create(self, key_service):
        key_service.create_key(name="audited", scopes=["chat"])
        events = list(key_service._audit)
        assert any(e["action"] == "created" and e["name"] == "audited" for e in events)

    def test_audit_records_revoke(self, key_service):
        created = key_service.create_key(name="to-revoke", scopes=["chat"])
        key_service.revoke_key(created["id"])
        events = list(key_service._audit)
        actions = [e["action"] for e in events if e["key_id"] == created["id"]]
        assert "created" in actions
        assert "revoked" in actions

    def test_audit_records_rotate(self, key_service):
        created = key_service.create_key(name="to-rotate", scopes=["chat"])
        key_service.rotate_key(created["id"])
        events = list(key_service._audit)
        # rotate is a revoke + create; both events recorded.
        actions_for_old = [e["action"] for e in events if e["key_id"] == created["id"]]
        assert "rotated" in actions_for_old or "revoked" in actions_for_old

    def test_audit_caps_at_200(self, key_service):
        for i in range(250):
            key_service._log("test", f"key_{i}", f"name_{i}")
        assert len(key_service._audit) == 200
        # Oldest entries dropped: key_0 should be gone, key_249 retained.
        ids = [e["key_id"] for e in key_service._audit]
        assert "key_0" not in ids
        assert "key_249" in ids
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api_keys.py::TestAuditLog -v
```

Expected: 6 FAILS — `_audit`, `_log`, `/api/keys/audit` don't exist.

- [ ] **Step 3: Add the ring buffer to `api_key_service.py`**

At the top of `api/services/api_key_service.py`, add the import:

```python
import collections
```

In `APIKeyService.__init__` (around line 30-39), append after the existing initialization:

```python
        # Audit ring buffer — capacity 200, lost on restart. Persistent storage
        # is intentionally out of scope (see ENTERPRISE_DEPLOYMENT_GAPS.md).
        self._audit: collections.deque = collections.deque(maxlen=200)
```

Add the `_log` method right below `__init__`:

```python
    def _log(self, action: str, key_id: str, name: Optional[str] = None) -> None:
        """Append an admin-action event to the in-memory audit ring buffer."""
        self._audit.append({
            "ts": _now_iso(),
            "action": action,
            "key_id": key_id,
            "name": name,
        })
```

- [ ] **Step 4: Wire `_log` calls into create/rotate/revoke**

In `create_key` (line 61), after `self._save(keys)` add:

```python
        self._log("created", key_id, name)
```

In `revoke_key` (find the method — search for `def revoke_key`), after the disabled flag is set / save, add:

```python
        self._log("revoked", key_id, entry.get("name"))
```

(Replace `entry` with whatever variable holds the key dict in that method.)

In `rotate_key`, after the rotation completes, add:

```python
        self._log("rotated", new_key_id, name)
```

(`new_key_id` and `name` may have different local names — adapt to the existing code. Consult the function signature.)

- [ ] **Step 5: Add the audit endpoint**

Append to `api/routers/api_keys.py` (after `/scopes`):

```python
@router.get("/audit")
async def get_audit(request: Request):
    """Return the in-memory audit log (last 200 events). Master-key gated."""
    _require_master(request)
    return list(_service._audit)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/test_api_keys.py::TestAuditLog -v
```

Expected: 6 PASS.

- [ ] **Step 7: Commit**

```bash
git add api/services/api_key_service.py api/routers/api_keys.py tests/test_api_keys.py
git commit -m "$(cat <<'EOF'
feat(api-keys): in-memory audit log + /api/keys/audit endpoint

Adds a 200-event deque on APIKeyService and a master-key-gated
endpoint that returns it. Persistent audit storage is intentionally
out of scope — captured in ENTERPRISE_DEPLOYMENT_GAPS.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Master-key gate on `/api/plugins/*`

**Files:**
- Modify: `api/routers/plugins.py`
- Modify: `tests/test_plugins.py` — existing tests need the auth header; add new gate tests

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plugins.py`:

```python
class TestPluginsAuthGate:
    def test_list_requires_master(self, monkeypatch):
        monkeypatch.delenv("MASTER_API_KEY", raising=False)
        import importlib, api.middleware, api.main
        importlib.reload(api.middleware); importlib.reload(api.main)
        from api.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        assert client.get("/api/plugins").status_code == 401

    def test_list_passes_with_master(self, monkeypatch):
        monkeypatch.setenv("MASTER_API_KEY", "test-master")
        import importlib, api.middleware, api.main
        importlib.reload(api.middleware); importlib.reload(api.main)
        from api.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.get("/api/plugins", headers={"Authorization": "Bearer test-master"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_invoke_requires_master(self, monkeypatch):
        monkeypatch.delenv("MASTER_API_KEY", raising=False)
        import importlib, api.middleware, api.main
        importlib.reload(api.middleware); importlib.reload(api.main)
        from api.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        assert client.post("/api/plugins/some-id/tools/some-tool", json={}).status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_plugins.py::TestPluginsAuthGate -v
```

Expected: 3 FAILS — endpoints currently return 200/404, not 401.

- [ ] **Step 3: Add the dependency**

Modify `api/routers/plugins.py` — top of file, replace:

```python
from fastapi import APIRouter, HTTPException
```

with:

```python
from fastapi import APIRouter, Depends, HTTPException

from ..middleware import require_master_key
```

Then add `dependencies=[Depends(require_master_key)]` to all three route decorators:

```python
@router.get("", dependencies=[Depends(require_master_key)])
async def list_plugins():
    ...

@router.get("/{plugin_id}", dependencies=[Depends(require_master_key)])
async def get_plugin(plugin_id: str):
    ...

@router.post("/{plugin_id}/tools/{tool_id}", dependencies=[Depends(require_master_key)])
async def invoke_tool(plugin_id: str, tool_id: str, params: dict):
    ...
```

- [ ] **Step 4: Update existing Plugins tests to attach the auth header**

Find every `client.get("/api/plugins…")` or `client.post("/api/plugins…")` in `tests/test_plugins.py` and add `headers={"Authorization": "Bearer test-master"}`. Wrap each test or fixture with the `monkeypatch.setenv("MASTER_API_KEY", "test-master")` pattern.

If the file has many tests, factor a fixture:

```python
@pytest.fixture
def plugins_client(monkeypatch):
    monkeypatch.setenv("MASTER_API_KEY", "test-master")
    import importlib, api.middleware, api.main
    importlib.reload(api.middleware); importlib.reload(api.main)
    from api.main import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer test-master"})
    yield c
```

and replace `client` with `plugins_client` in each test.

- [ ] **Step 5: Run all plugin tests to verify they pass**

```bash
pytest tests/test_plugins.py -v
```

Expected: all PASS (existing + new gate tests).

- [ ] **Step 6: Commit**

```bash
git add api/routers/plugins.py tests/test_plugins.py
git commit -m "$(cat <<'EOF'
feat(plugins): require master key on all /api/plugins endpoints

Aligns the Plugins router with the default-deny posture used by
/api/keys. List and invoke endpoints now require the master key.
Behavior change: programmatic clients that previously called these
endpoints unauthenticated must now attach Authorization: Bearer
\$MASTER_API_KEY.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `/api/exports/zip` endpoint

**Files:**
- Modify: `api/routers/exports.py`
- Modify: `tests/test_exports.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_exports.py`:

```python
import io, zipfile

class TestZipEndpoint:
    def test_zip_streams_selected_files(self, client, tmp_path, monkeypatch):
        # Point EXPORTS_DIR at a fresh temp dir.
        from api.routers import exports as exports_router
        monkeypatch.setattr(exports_router, "EXPORTS_DIR", tmp_path)
        (tmp_path / "a.md").write_text("# A\nhello")
        (tmp_path / "b.md").write_text("# B\nworld")

        resp = client.get("/api/exports/zip?names=a.md,b.md")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        assert set(z.namelist()) == {"a.md", "b.md"}
        assert z.read("a.md").decode() == "# A\nhello"

    def test_zip_rejects_path_traversal(self, client, tmp_path, monkeypatch):
        from api.routers import exports as exports_router
        monkeypatch.setattr(exports_router, "EXPORTS_DIR", tmp_path)
        (tmp_path / "real.md").write_text("ok")
        # The ../etc/passwd attempt should be sanitized to a safe filename
        # which then doesn't match any real file → request silently drops it.
        resp = client.get("/api/exports/zip?names=../../../etc/passwd,real.md")
        assert resp.status_code == 200
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        assert "real.md" in z.namelist()
        assert all("passwd" not in n for n in z.namelist())

    def test_zip_404_when_no_matches(self, client, tmp_path, monkeypatch):
        from api.routers import exports as exports_router
        monkeypatch.setattr(exports_router, "EXPORTS_DIR", tmp_path)
        resp = client.get("/api/exports/zip?names=does-not-exist.md")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_exports.py::TestZipEndpoint -v
```

Expected: 3 FAILS — endpoint not implemented.

- [ ] **Step 3: Implement the endpoint**

Modify `api/routers/exports.py`. Add to the imports at the top:

```python
import io
import zipfile

from fastapi.responses import StreamingResponse
```

Append at the end of the file:

```python
@router.get("/zip")
async def zip_exports(names: str):
    """Stream a zip of the named exports. Path traversal is blocked per name.

    Files that fail validation or don't exist are silently dropped — only
    return 404 when zero files match.
    """
    requested = [_safe_filename(n) for n in names.split(",") if n.strip()]
    paths = [EXPORTS_DIR / n for n in requested if (EXPORTS_DIR / n).is_file()]
    if not paths:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="no matching exports")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=p.name)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=enclave-exports.zip"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_exports.py::TestZipEndpoint -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routers/exports.py tests/test_exports.py
git commit -m "$(cat <<'EOF'
feat(exports): add /api/exports/zip streaming endpoint

Lets the upcoming Exports panel offer a "Download zip" bulk action.
Per-name path-traversal blocked via the existing _safe_filename helper.
Returns 404 if zero requested names match a real file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Phase 1 verification

```bash
pytest tests/test_api_keys.py tests/test_exports.py tests/test_plugins.py tests/ui/ -v --tb=short 2>&1 | tail -30
```

Expected: all router tests pass + the original 21 UI tests still pass (no UI changes yet). If anything red, halt and diagnose before Phase 2.

---

## Phase 2: UI scaffolding

These three tasks build the chassis. The Admin dropdown, the auth flow, and a shared markdown helper. Each panel in Phase 3-5 hangs off this scaffolding.

---

### Task 6: Admin dropdown — markup, CSS, JS module

**Files:**
- Modify: `api/static/index.html`
- Modify: `tests/ui/test_static_markup.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/ui/test_static_markup.py`:

```python
def test_admin_dropdown_present(index_soup):
    """An Admin dropdown trigger must exist in the tab strip."""
    trigger = index_soup.find(id="admin-trigger")
    assert trigger is not None, "#admin-trigger missing from tab strip"
    assert trigger.get("aria-haspopup") == "menu"
    assert trigger.get("aria-expanded") == "false"


def test_admin_menu_has_three_items(index_soup):
    """Admin menu must list API Keys, Plugins, Exports."""
    menu = index_soup.find(id="admin-menu")
    assert menu is not None
    items = menu.find_all(attrs={"role": "menuitem"})
    panels = {i.get("data-panel") for i in items}
    assert {"admin-keys", "admin-plugins", "admin-exports"}.issubset(panels)


def test_admin_panel_containers_exist(index_soup):
    """Three .tab-content panels must exist (initially hidden)."""
    for pid in ("tab-admin-keys", "tab-admin-plugins", "tab-admin-exports"):
        el = index_soup.find(id=pid)
        assert el is not None, f"#{pid} container missing"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/ui/test_static_markup.py::test_admin_dropdown_present tests/ui/test_static_markup.py::test_admin_menu_has_three_items tests/ui/test_static_markup.py::test_admin_panel_containers_exist -v
```

Expected: 3 FAILS.

- [ ] **Step 3: Add the dropdown markup**

Locate the tab strip in `api/static/index.html` (around line 1086). After the Documents tab button, insert:

```html
    <span class="tab-divider" aria-hidden="true"></span>
    <div class="tab-dropdown" role="presentation">
      <button class="tab-btn admin-trigger" id="admin-trigger"
              type="button" aria-haspopup="menu" aria-expanded="false"
              onclick="AdminMenu.toggle(this)">
        <span class="admin-icon" aria-hidden="true">⚙</span> Admin
        <span class="caret" aria-hidden="true">▾</span>
      </button>
      <div class="admin-menu" id="admin-menu" role="menu" hidden>
        <button class="admin-menu-item" role="menuitem" type="button"
                data-panel="admin-keys" onclick="AdminMenu.select('admin-keys')">API Keys</button>
        <button class="admin-menu-item" role="menuitem" type="button"
                data-panel="admin-plugins" onclick="AdminMenu.select('admin-plugins')">Plugins</button>
        <button class="admin-menu-item" role="menuitem" type="button"
                data-panel="admin-exports" onclick="AdminMenu.select('admin-exports')">Exports</button>
        <div class="admin-menu-divider" aria-hidden="true"></div>
        <div class="admin-menu-status" id="admin-menu-status">
          <span class="dot" id="admin-status-dot"></span>
          <span id="admin-menu-status-text">Locked</span>
          <button class="admin-menu-signout" id="admin-menu-signout" type="button"
                  hidden onclick="AdminAuth.signOut()">Sign out</button>
        </div>
      </div>
    </div>
```

- [ ] **Step 4: Add the three empty panel containers**

After the existing `tab-content` blocks (search for the last `<div class="tab-content"` and add after it):

```html
  <!-- ═══ ADMIN PANELS ═════════════════════════════════════════════ -->
  <div class="tab-content" id="tab-admin-keys" style="display:none">
    <!-- populated by Task 9-11 -->
  </div>

  <div class="tab-content" id="tab-admin-plugins" style="display:none">
    <!-- populated by Task 12-13 -->
  </div>

  <div class="tab-content" id="tab-admin-exports" style="display:none">
    <!-- populated by Task 14-15 -->
  </div>
```

- [ ] **Step 5: Add CSS**

Find the existing `.tab-btn` rules in the stylesheet and append:

```css
/* === Admin dropdown ============================================= */
.tab-divider {
  display: inline-block;
  width: 1px;
  height: 22px;
  background: var(--border);
  margin: 0 6px;
  vertical-align: middle;
}

.tab-dropdown {
  position: relative;
  display: inline-block;
}

.admin-trigger {
  /* visually identical to .tab-btn when inactive; .active painted by JS */
}

.admin-trigger .caret {
  margin-left: 4px;
  font-size: 0.6rem;
}

.admin-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 200px;
  background: var(--bg-panel, var(--bg));
  border: 1px solid var(--border);
  border-radius: 4px;
  box-shadow: 0 6px 18px rgba(0,0,0,0.4);
  padding: 6px 0;
  z-index: 100;
}

.admin-menu[hidden] { display: none; }

.admin-menu-item {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  color: var(--text);
  padding: 8px 14px;
  font-family: var(--mono);
  font-size: 0.74rem;
  cursor: pointer;
}

.admin-menu-item:hover,
.admin-menu-item:focus-visible {
  background: var(--accent-ghost, rgba(0,204,102,0.08));
  color: var(--accent);
}

.admin-menu-divider {
  height: 1px;
  background: var(--border);
  margin: 6px 0;
}

.admin-menu-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  font-size: 0.66rem;
  color: var(--text-dim);
}

.admin-menu-status .dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--text-muted);
  display: inline-block;
}

.admin-menu-status.unlocked .dot { background: var(--accent); }

.admin-menu-signout {
  margin-left: auto;
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-dim);
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 0.64rem;
  cursor: pointer;
}
.admin-menu-signout:hover { color: var(--accent); border-color: var(--accent-dim); }
```

- [ ] **Step 6: Add the AdminMenu JS module**

At the bottom of the existing `<script>` block (before the closing `</script>`), add:

```javascript
// ── AdminMenu ─────────────────────────────────────────────────────────────
window.AdminMenu = (function () {
  const trigger = () => document.getElementById('admin-trigger');
  const menu = () => document.getElementById('admin-menu');

  function open() {
    menu().hidden = false;
    trigger().setAttribute('aria-expanded', 'true');
    document.addEventListener('click', onOutsideClick, true);
    document.addEventListener('keydown', onKeydown);
    // Focus first menu item for keyboard users.
    const first = menu().querySelector('.admin-menu-item');
    if (first) first.focus();
  }

  function close() {
    menu().hidden = true;
    trigger().setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', onOutsideClick, true);
    document.removeEventListener('keydown', onKeydown);
  }

  function toggle(_el) {
    if (menu().hidden) open(); else close();
  }

  function onOutsideClick(e) {
    if (!menu().contains(e.target) && !trigger().contains(e.target)) close();
  }

  function onKeydown(e) {
    if (e.key === 'Escape') { close(); trigger().focus(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const items = Array.from(menu().querySelectorAll('.admin-menu-item'));
      const i = items.indexOf(document.activeElement);
      const next = e.key === 'ArrowDown'
        ? items[(i + 1) % items.length]
        : items[(i - 1 + items.length) % items.length];
      next.focus();
    }
  }

  function select(panelId) {
    close();
    showPanel(panelId);
  }

  function showPanel(panelId) {
    // Hide every .tab-content (operational + admin).
    document.querySelectorAll('.tab-content').forEach(t => {
      t.classList.remove('active');
      t.style.display = '';
    });
    // De-active every .tab-btn.
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));

    const target = document.getElementById('tab-' + panelId);
    if (target) {
      target.classList.add('active');
      target.style.display = 'block';
    }
    trigger().classList.add('active');

    // Notify panels so they can lazy-load.
    window.dispatchEvent(new CustomEvent('adminPanelActivated', {detail: {panel: panelId}}));
  }

  // Reset Admin trigger active state when an operational tab is chosen.
  document.addEventListener('click', function (e) {
    if (e.target.classList.contains('tab-btn') && e.target.id !== 'admin-trigger') {
      trigger().classList.remove('active');
    }
  }, true);

  return { toggle, select, open, close, showPanel };
})();
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
pytest tests/ui/test_static_markup.py -v 2>&1 | tail -25
```

Expected: original 21 tests still pass + 3 new tests pass = 24 passing.

- [ ] **Step 8: Smoke-test in the browser**

```bash
python api/main.py &
sleep 2
open http://localhost:8000/
# Click ⚙ Admin — menu opens. Click outside — menu closes.
# Tab to it; press Enter — opens. ↓/↑ navigates. Esc closes and refocuses trigger.
# Click any menu item — corresponding empty panel appears (will be empty until later tasks).
kill %1
```

- [ ] **Step 9: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "$(cat <<'EOF'
feat(ui): Admin dropdown in tab strip + 3 empty panel containers

Adds the navigation chassis for the Settings & Permissions UI.
Keyboard-accessible (Enter/Space opens, Esc closes, arrow keys
navigate). Three empty panels (admin-keys, admin-plugins,
admin-exports) get populated by subsequent commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: AdminAuth module (sessionStorage, lock state, sign-in modal, sign-out)

**Files:**
- Modify: `api/static/index.html`
- Modify: `tests/ui/test_static_markup.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/ui/test_static_markup.py`:

```python
def test_admin_auth_uses_session_storage(index_html_text):
    """Auth state must be in sessionStorage, never localStorage."""
    assert "sessionStorage" in index_html_text, "AdminAuth missing"
    assert "enclave.admin.masterKey" in index_html_text, (
        "expected sessionStorage key 'enclave.admin.masterKey'"
    )


def test_admin_auth_does_not_persist_in_local_storage(index_html_text):
    """Master key must never be written to localStorage."""
    # Crude but effective: there should be NO 'localStorage.setItem' anywhere
    # near the master-key wiring. Refine if false positives appear.
    import re
    matches = re.findall(r"localStorage\.setItem\([^)]*master[^)]*\)", index_html_text, re.I)
    assert not matches, f"master key written to localStorage: {matches}"


def test_admin_signin_modal_present(index_soup):
    """A modal for entering the master key must exist."""
    modal = index_soup.find(id="admin-signin-modal")
    assert modal is not None
    pwd = modal.find("input", attrs={"type": "password"})
    assert pwd is not None, "modal must include a <input type=password>"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/ui/test_static_markup.py::test_admin_auth_uses_session_storage tests/ui/test_static_markup.py::test_admin_auth_does_not_persist_in_local_storage tests/ui/test_static_markup.py::test_admin_signin_modal_present -v
```

Expected: 3 FAILS.

- [ ] **Step 3: Add the sign-in modal markup**

After the three empty admin panel containers (added in Task 6 Step 4), append:

```html
  <!-- ── Admin sign-in modal ───────────────────────────────────────── -->
  <div id="admin-signin-modal" class="admin-modal" hidden role="dialog"
       aria-modal="true" aria-labelledby="admin-signin-title">
    <div class="admin-modal-card">
      <h3 id="admin-signin-title">Sign in as admin</h3>
      <p class="admin-modal-sub">
        Enter the <code>MASTER_API_KEY</code> set on the server. The key
        is held in <code>sessionStorage</code> for this tab only and is
        cleared when the tab closes.
      </p>
      <input id="admin-signin-input" type="password" autocomplete="off"
             placeholder="MASTER_API_KEY" />
      <div id="admin-signin-error" class="admin-modal-error" hidden>
        Master key rejected.
      </div>
      <div class="admin-modal-actions">
        <button type="button" class="admin-modal-btn"
                onclick="AdminAuth._cancelSignIn()">Cancel</button>
        <button type="button" class="admin-modal-btn primary"
                onclick="AdminAuth._submitSignIn()">Sign in</button>
      </div>
    </div>
  </div>
```

Add the modal CSS (next to the AdminMenu CSS from Task 6):

```css
/* === Admin modal (shared by sign-in, create-key, etc.) ========== */
.admin-modal {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}
.admin-modal[hidden] { display: none; }

.admin-modal-card {
  background: var(--bg-panel, var(--bg));
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 22px 24px;
  width: 420px;
  max-width: 90vw;
  box-shadow: 0 12px 28px rgba(0,0,0,0.55);
}

.admin-modal-card h3 {
  margin: 0 0 6px 0;
  color: var(--accent);
  font-size: 0.95rem;
}

.admin-modal-sub {
  font-size: 0.72rem;
  color: var(--text-dim);
  line-height: 1.5;
  margin: 0 0 14px 0;
}

.admin-modal-card input[type="password"],
.admin-modal-card input[type="text"],
.admin-modal-card input[type="number"],
.admin-modal-card input[type="date"],
.admin-modal-card textarea {
  width: 100%;
  box-sizing: border-box;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 8px 10px;
  border-radius: 4px;
  font-family: var(--mono);
  font-size: 0.78rem;
}

.admin-modal-error {
  background: rgba(229,75,75,0.12);
  border: 1px solid var(--danger, #e54b4b);
  color: var(--danger, #e54b4b);
  padding: 6px 10px;
  border-radius: 3px;
  font-size: 0.7rem;
  margin-top: 8px;
}

.admin-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

.admin-modal-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-dim);
  padding: 6px 14px;
  border-radius: 3px;
  font-size: 0.72rem;
  cursor: pointer;
}

.admin-modal-btn.primary {
  background: var(--accent);
  color: #000;
  border-color: var(--accent);
  font-weight: 600;
}
.admin-modal-btn:hover { color: var(--accent); border-color: var(--accent-dim); }
.admin-modal-btn.primary:hover { background: var(--accent); color: #000; opacity: 0.85; }

/* ── Lock state (shown inside admin panels when not signed in) ── */
.admin-lock {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 280px;
  border: 1px dashed var(--border);
  border-radius: 6px;
  color: var(--text-dim);
  gap: 12px;
}
.admin-lock .lock-icon { font-size: 2rem; opacity: 0.55; }
.admin-lock .lock-msg { font-size: 0.82rem; }
.admin-lock .lock-btn {
  background: var(--accent);
  color: #000;
  border: none;
  padding: 8px 20px;
  border-radius: 4px;
  font-weight: 600;
  font-size: 0.78rem;
  cursor: pointer;
}
```

- [ ] **Step 4: Add the AdminAuth JS module**

At the bottom of the `<script>` block, AFTER the AdminMenu IIFE from Task 6:

```javascript
// ── AdminAuth ─────────────────────────────────────────────────────────────
window.AdminAuth = (function () {
  const STORAGE_KEY = 'enclave.admin.masterKey';
  // After successful sign-in, the panel that triggered the modal gets reloaded.
  let pendingPanel = null;

  function getKey() {
    return sessionStorage.getItem(STORAGE_KEY) || '';
  }

  function isSignedIn() {
    return !!getKey();
  }

  function setKey(key) {
    sessionStorage.setItem(STORAGE_KEY, key);
    _refreshStatus();
  }

  function clearKey() {
    sessionStorage.removeItem(STORAGE_KEY);
    _refreshStatus();
  }

  function authHeaders() {
    const key = getKey();
    return key ? { 'Authorization': 'Bearer ' + key } : {};
  }

  /** Wrap a fetch with master-key handling. Returns fetch's Response promise.
   *  If the response is 401, clears the key and re-renders the lock state for
   *  the panel identified by panelId (so the user can re-auth). */
  async function fetch(url, opts, panelId) {
    opts = opts || {};
    opts.headers = Object.assign({}, opts.headers || {}, authHeaders());
    const r = await window.fetch(url, opts);
    if (r.status === 401) {
      clearKey();
      if (panelId) renderLock(panelId, 'Master key rejected — sign in again.');
    }
    return r;
  }

  /** Render a lock state into the named panel container. */
  function renderLock(panelId, banner) {
    const host = document.getElementById('tab-' + panelId);
    if (!host) return;
    host.innerHTML = `
      <div class="admin-lock">
        <div class="lock-icon" aria-hidden="true">🔒</div>
        <div class="lock-msg">Admin actions require the master key.</div>
        ${banner ? `<div class="admin-modal-error" style="margin:0">${banner}</div>` : ''}
        <button class="lock-btn" onclick="AdminAuth.signIn('${panelId}')">Sign in as admin</button>
      </div>
    `;
  }

  function signIn(panelId) {
    pendingPanel = panelId;
    document.getElementById('admin-signin-error').hidden = true;
    document.getElementById('admin-signin-input').value = '';
    document.getElementById('admin-signin-modal').hidden = false;
    setTimeout(() => document.getElementById('admin-signin-input').focus(), 0);
  }

  function _cancelSignIn() {
    document.getElementById('admin-signin-modal').hidden = true;
    pendingPanel = null;
  }

  async function _submitSignIn() {
    const input = document.getElementById('admin-signin-input');
    const errBox = document.getElementById('admin-signin-error');
    const candidate = input.value.trim();
    if (!candidate) { errBox.hidden = false; errBox.textContent = 'Enter the master key.'; return; }

    // Validate by hitting an endpoint we know is master-key gated.
    const r = await window.fetch('/api/keys/scopes', {
      headers: { 'Authorization': 'Bearer ' + candidate },
    });
    if (r.status !== 200) {
      errBox.hidden = false;
      errBox.textContent = 'Master key rejected.';
      return;
    }
    setKey(candidate);
    document.getElementById('admin-signin-modal').hidden = true;
    if (pendingPanel) {
      // Re-render the originating panel.
      window.dispatchEvent(new CustomEvent('adminPanelActivated', {detail: {panel: pendingPanel}}));
    }
    pendingPanel = null;
  }

  function signOut() {
    clearKey();
    // Re-render any visible admin panel as locked.
    document.querySelectorAll('.tab-content[id^="tab-admin-"]').forEach(el => {
      const id = el.id.replace(/^tab-/, '');
      if (el.classList.contains('active')) renderLock(id);
    });
  }

  function _refreshStatus() {
    const status = document.getElementById('admin-menu-status');
    const text = document.getElementById('admin-menu-status-text');
    const so = document.getElementById('admin-menu-signout');
    if (!status || !text || !so) return;
    if (isSignedIn()) {
      status.classList.add('unlocked');
      text.textContent = 'Signed in as admin';
      so.hidden = false;
    } else {
      status.classList.remove('unlocked');
      text.textContent = 'Locked';
      so.hidden = true;
    }
  }

  // Initial paint after DOM is ready.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _refreshStatus);
  } else {
    _refreshStatus();
  }

  // Listen for Enter in the sign-in input.
  document.addEventListener('keydown', function (e) {
    const modal = document.getElementById('admin-signin-modal');
    if (!modal || modal.hidden) return;
    if (e.key === 'Enter') { e.preventDefault(); _submitSignIn(); }
    if (e.key === 'Escape') { e.preventDefault(); _cancelSignIn(); }
  });

  return { isSignedIn, getKey, authHeaders, fetch, renderLock,
           signIn, signOut, _cancelSignIn, _submitSignIn };
})();
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/ui/test_static_markup.py -v 2>&1 | tail -10
```

Expected: 27 passing (24 from before + 3 new).

- [ ] **Step 6: Smoke-test**

```bash
python api/main.py &
sleep 2
open http://localhost:8000/
# Click ⚙ Admin → API Keys. Panel is empty (next task) but lock state should
# render once any panel calls AdminAuth.renderLock(); for now, confirm modal
# opens via console: AdminAuth.signIn('admin-keys'). Type any key → "Master
# key rejected" since /api/keys/scopes returns 401 without a real master key.
# Set MASTER_API_KEY=test in env, restart, type "test" → modal closes,
# Admin status pill flips to "Signed in as admin · Sign out".
kill %1
```

- [ ] **Step 7: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "$(cat <<'EOF'
feat(ui): AdminAuth module + sign-in modal + lock state

Holds the master key in sessionStorage (never localStorage), validates
candidates against /api/keys/scopes before storing, attaches the Bearer
header to admin-panel fetches, and re-renders panels as locked on 401.
Sign-out clears the key and re-locks any visible admin panel.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: `renderMarkdown(text)` shared helper

**Files:**
- Modify: `api/static/index.html`
- Modify: `tests/ui/test_static_markup.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/ui/test_static_markup.py`:

```python
def test_render_markdown_helper_present(index_html_text):
    """A renderMarkdown helper must be defined in the script block."""
    assert "function renderMarkdown" in index_html_text or \
           "renderMarkdown =" in index_html_text or \
           "window.renderMarkdown" in index_html_text, \
        "renderMarkdown helper missing"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/ui/test_static_markup.py::test_render_markdown_helper_present -v
```

Expected: FAIL.

- [ ] **Step 3: Add the helper**

At the top of the existing `<script>` block (right after the opening `<script>`), insert:

```javascript
// ── renderMarkdown(text) — shared CommonMark subset renderer ─────────────
//
// Handles: H1–H6, paragraphs, fenced code blocks, inline code, ul/ol lists,
// links (rel=noopener target=_blank), bold, italic. Anything else falls
// through as escaped text.  Output is always HTML-escaped before substitution
// so it cannot produce executable markup.
//
// Used by the Plugins panel (skill bodies) and the Exports panel (View modal).
window.renderMarkdown = function renderMarkdown(text) {
  if (text == null) return '';
  const esc = s => String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  // Pull fenced code blocks out first so their contents aren't mangled.
  const codeBlocks = [];
  text = text.replace(/```([\w-]*)\n([\s\S]*?)```/g, (_, lang, body) => {
    codeBlocks.push(`<pre class="md-code"><code>${esc(body)}</code></pre>`);
    return ` CODE${codeBlocks.length - 1} `;
  });

  // Escape the rest, then apply inline + block patterns.
  let html = esc(text);

  // Headings (H1..H6).
  for (let n = 6; n >= 1; n--) {
    const re = new RegExp('^#{' + n + '} +(.*)$', 'gm');
    html = html.replace(re, (_, t) => `<h${n} class="md-h${n}">${t}</h${n}>`);
  }

  // Lists: collapse consecutive list lines into <ul>/<ol>.
  html = html.replace(/(?:^|\n)((?:[*-] .+\n?)+)/g, (_, block) => {
    const items = block.trim().split(/\n/).map(l => l.replace(/^[*-] /, '').trim());
    return '\n<ul class="md-ul">' + items.map(i => `<li>${i}</li>`).join('') + '</ul>';
  });
  html = html.replace(/(?:^|\n)((?:\d+\. .+\n?)+)/g, (_, block) => {
    const items = block.trim().split(/\n/).map(l => l.replace(/^\d+\. /, '').trim());
    return '\n<ol class="md-ol">' + items.map(i => `<li>${i}</li>`).join('') + '</ol>';
  });

  // Inline: code, links, bold, italic.
  html = html.replace(/`([^`\n]+)`/g, '<code class="md-inline-code">$1</code>');
  html = html.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, t, u) => {
    if (!/^https?:\/\//.test(u) && !u.startsWith('/')) return m; // safety: only allow http(s) or root-relative
    return `<a href="${esc(u)}" rel="noopener" target="_blank">${t}</a>`;
  });
  html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');

  // Paragraphs: split on blank lines, wrap non-block chunks.
  html = html.split(/\n{2,}/).map(chunk => {
    const t = chunk.trim();
    if (!t) return '';
    if (/^<(h[1-6]|ul|ol|pre|div)/.test(t)) return t;
    return `<p>${t.replace(/\n/g, '<br>')}</p>`;
  }).join('\n');

  // Restore code blocks.
  html = html.replace(/ CODE(\d+) /g, (_, i) => codeBlocks[+i]);

  return html;
};
```

Add minimal CSS (next to the other admin CSS):

```css
/* === renderMarkdown output styling ============================== */
.md-h1, .md-h2, .md-h3, .md-h4, .md-h5, .md-h6 { color: var(--text); margin: 14px 0 6px; }
.md-h1 { font-size: 1.1rem; }  .md-h2 { font-size: 1.0rem; }
.md-h3 { font-size: 0.92rem; } .md-h4 { font-size: 0.85rem; }
.md-h5 { font-size: 0.78rem; } .md-h6 { font-size: 0.72rem; }
.md-code {
  background: var(--bg); border: 1px solid var(--border);
  border-radius: 4px; padding: 10px 12px; font-size: 0.74rem;
  overflow-x: auto;
}
.md-inline-code {
  background: var(--bg); border: 1px solid var(--border);
  padding: 1px 5px; border-radius: 2px; font-size: 0.78em;
}
.md-ul, .md-ol { padding-left: 22px; margin: 6px 0; }
.md-ul li, .md-ol li { margin-bottom: 2px; font-size: 0.78rem; line-height: 1.5; }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/ui/test_static_markup.py::test_render_markdown_helper_present -v
```

Expected: PASS.

- [ ] **Step 5: Smoke-test in the browser console**

```javascript
renderMarkdown("# Hi\n\nA `paragraph` with **bold** and a [link](https://example.com).\n\n```\ncode\n```")
// Should return well-formed HTML with <h1>, <p>, <code>, <strong>, <a>, <pre>.
```

- [ ] **Step 6: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "$(cat <<'EOF'
feat(ui): renderMarkdown(text) — shared CommonMark-subset renderer

60-line vanilla-JS renderer for the Plugins panel (skill bodies) and
the Exports panel (View modal). Handles H1-H6, paragraphs, lists,
fenced + inline code, links (http/root-relative only), bold, italic.
All output HTML-escaped at the boundary; no script-executing markup
can be produced. Vendor markdown library intentionally avoided —
the surface is small enough that 60 LOC beats a supply-chain dep.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Phase 2 verification

```bash
pytest tests/ui/ -v --tb=short 2>&1 | tail -10
```

Expected: 28 passing (21 original + 7 new from Tasks 6-8).

---

## Phase 3: API Keys panel

Three tasks. Each delivers a self-contained slice of the panel.

---

### Task 9: API Keys panel — list view

**Files:**
- Modify: `api/static/index.html`
- Modify: `tests/ui/test_static_markup.py`

- [ ] **Step 1: Write failing test**

Append:

```python
def test_api_keys_panel_has_list_container(index_html_text):
    """The API Keys panel must include a list container and a refresh button."""
    assert 'id="api-keys-list"' in index_html_text
    assert "loadApiKeysPanel" in index_html_text


def test_api_keys_panel_has_new_key_button(index_html_text):
    assert "showCreateKeyModal" in index_html_text or \
           "showNewKeyModal" in index_html_text, \
        "expected a 'New Key' trigger function"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/ui/test_static_markup.py::test_api_keys_panel_has_list_container tests/ui/test_static_markup.py::test_api_keys_panel_has_new_key_button -v
```

Expected: 2 FAILS.

- [ ] **Step 3: Replace the empty `tab-admin-keys` panel**

Find the `<div class="tab-content" id="tab-admin-keys"...>` block from Task 6 and replace its contents:

```html
  <div class="tab-content" id="tab-admin-keys" style="display:none">
    <div class="panel">
      <span class="corner-tr"></span><span class="corner-bl"></span>
      <div class="panel-label">// API KEYS
        <span style="float:right">
          <button class="action-btn" onclick="ApiKeysPanel.showCreate()"
            style="color:var(--accent);border-color:var(--accent-dim)">+ New Key</button>
          <button class="action-btn" onclick="ApiKeysPanel.refresh()">Refresh</button>
        </span>
      </div>
      <div id="api-keys-list" style="margin-top:12px;font-size:0.78rem"></div>
    </div>
  </div>
```

- [ ] **Step 4: Add the ApiKeysPanel module (list-only for now)**

At the bottom of the `<script>` block, AFTER AdminAuth:

```javascript
// ── ApiKeysPanel ──────────────────────────────────────────────────────────
window.ApiKeysPanel = (function () {

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function load() {
    if (!AdminAuth.isSignedIn()) {
      AdminAuth.renderLock('admin-keys');
      return;
    }
    const list = document.getElementById('api-keys-list');
    list.innerHTML = '<div style="color:var(--text-muted);font-size:0.78rem">Loading…</div>';

    const r = await AdminAuth.fetch('/api/keys', {}, 'admin-keys');
    if (!r.ok) {
      // 401 already handled by AdminAuth.fetch.
      list.innerHTML = `<div class="admin-modal-error" style="margin:0">Failed to load keys (HTTP ${r.status})</div>`;
      return;
    }
    const keys = await r.json();
    if (!Array.isArray(keys) || keys.length === 0) {
      list.innerHTML = '<div style="color:var(--text-muted);padding:10px 0">No keys yet. Click "+ New Key" to create one.</div>';
      return;
    }

    // Header + rows.
    list.innerHTML = `
      <table class="api-keys-table" role="table">
        <thead>
          <tr>
            <th>Name</th><th>Key</th><th>Scopes</th>
            <th>RPM</th><th>Last used</th><th>Status</th><th></th>
          </tr>
        </thead>
        <tbody>
          ${keys.map(rowHtml).join('')}
        </tbody>
      </table>
    `;
  }

  function rowHtml(k) {
    const enabled = k.enabled !== false;
    const last = k.last_used_at
      ? new Date(k.last_used_at).toLocaleString()
      : '<span style="color:var(--text-muted)">never</span>';
    const scopes = (k.scopes || []).map(s =>
      `<span class="scope-chip">${esc(s)}</span>`).join(' ');
    const masked = `${esc(k.prefix || '')}…${esc(k.last_four || '')}`;
    return `
      <tr class="${enabled ? '' : 'key-disabled'}">
        <td>${esc(k.name)}</td>
        <td><code>${masked}</code></td>
        <td>${scopes || '<span style="color:var(--text-muted)">—</span>'}</td>
        <td>${k.rate_limit_rpm ?? '<span style="color:var(--text-muted)">—</span>'}</td>
        <td>${last}</td>
        <td>${enabled
          ? '<span style="color:var(--accent)">enabled</span>'
          : '<span style="color:var(--text-muted)">revoked</span>'}</td>
        <td class="row-actions">
          ${enabled ? `
            <button class="action-btn small" onclick="ApiKeysPanel.rotate('${esc(k.id)}','${esc(k.name)}')">Rotate</button>
            <button class="action-btn small danger" onclick="ApiKeysPanel.revoke('${esc(k.id)}','${esc(k.name)}')">Revoke</button>
          ` : ''}
        </td>
      </tr>
    `;
  }

  function refresh() { load(); }

  // Stubs — implemented in Task 10/11.
  function showCreate() { /* Task 10 */ }
  function rotate(id, name) { /* Task 11 */ }
  function revoke(id, name) { /* Task 11 */ }

  // Auto-load when this admin panel is activated.
  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-keys') load();
  });

  return { load, refresh, showCreate, rotate, revoke };
})();
```

Add the table CSS:

```css
/* === API Keys table ============================================ */
.api-keys-table {
  width: 100%; border-collapse: collapse; font-size: 0.74rem;
}
.api-keys-table th {
  text-align: left; color: var(--text-dim);
  font-weight: 500; letter-spacing: 0.1em; text-transform: uppercase;
  font-size: 0.6rem; padding: 6px 8px; border-bottom: 1px solid var(--border);
}
.api-keys-table td {
  padding: 8px; border-bottom: 1px solid var(--border);
  color: var(--text); vertical-align: top;
}
.api-keys-table tr.key-disabled td { opacity: 0.5; }
.api-keys-table tr:hover td { background: rgba(255,255,255,0.02); }
.api-keys-table .row-actions { white-space: nowrap; text-align: right; }
.scope-chip {
  display: inline-block; font-size: 0.62rem;
  background: var(--accent-ghost, rgba(0,204,102,0.1));
  color: var(--accent); padding: 1px 7px; border-radius: 999px;
  margin-right: 2px;
}
.action-btn.small { padding: 3px 9px; font-size: 0.66rem; }
.action-btn.danger { color: var(--danger, #e54b4b); border-color: rgba(229,75,75,0.4); }
.action-btn.danger:hover { background: rgba(229,75,75,0.08); }
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/ui/test_static_markup.py -v 2>&1 | tail -8
```

Expected: 30 passing (28 + 2 new).

- [ ] **Step 6: Smoke-test**

```bash
MASTER_API_KEY=test python api/main.py &
sleep 2
open http://localhost:8000/
# Click ⚙ Admin → API Keys → "Sign in as admin" → enter "test"
# Empty state: "No keys yet."
# Use curl to add a key:
curl -X POST http://localhost:8000/api/keys -H "Authorization: Bearer test" \
  -H "Content-Type: application/json" \
  -d '{"name":"smoke","scopes":["chat","models"]}'
# Click Refresh — table renders with one row, name/scopes/etc shown.
kill %1
```

- [ ] **Step 7: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "$(cat <<'EOF'
feat(ui): API Keys panel — list view

ApiKeysPanel.load() fetches /api/keys with the master-key bearer,
renders a table with name, masked key, scope chips, rate limit, last
used, status, and per-row Rotate/Revoke buttons (stubbed until
Task 11). Locked panel renders the AdminAuth lock state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: API Keys panel — create modal with one-time reveal

**Files:**
- Modify: `api/static/index.html`
- Modify: `tests/ui/test_static_markup.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
def test_create_key_modal_present(index_soup):
    modal = index_soup.find(id="create-key-modal")
    assert modal is not None
    name = modal.find(id="new-key-name")
    scopes_field = modal.find(id="new-key-scopes")
    assert name is not None and scopes_field is not None


def test_create_key_modal_has_one_time_reveal_warning(index_html_text):
    """The reveal area must say the key is shown once."""
    needle = "only time"
    assert needle in index_html_text.lower(), (
        "expected one-time-reveal warning copy in create-key modal"
    )


def test_create_key_modal_has_copy_button(index_html_text):
    assert "navigator.clipboard.writeText" in index_html_text or \
           "copyKey" in index_html_text, \
        "expected a clipboard copy mechanism"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/ui/test_static_markup.py::test_create_key_modal_present tests/ui/test_static_markup.py::test_create_key_modal_has_one_time_reveal_warning tests/ui/test_static_markup.py::test_create_key_modal_has_copy_button -v
```

Expected: 3 FAILS.

- [ ] **Step 3: Add the create-key modal markup**

Place this immediately after the `admin-signin-modal` block from Task 7:

```html
  <!-- ── Create API key modal ──────────────────────────────────────── -->
  <div id="create-key-modal" class="admin-modal" hidden role="dialog"
       aria-modal="true" aria-labelledby="create-key-title">
    <div class="admin-modal-card" style="width:480px">
      <h3 id="create-key-title">Create API key</h3>
      <div id="create-key-form">
        <label class="admin-modal-label">Name</label>
        <input id="new-key-name" type="text" placeholder="e.g. homelab-client" autocomplete="off">

        <label class="admin-modal-label">Scopes</label>
        <div id="new-key-scopes" class="scope-picker"></div>

        <label class="admin-modal-label">Rate limit (requests / minute) — optional</label>
        <input id="new-key-rpm" type="number" min="1" placeholder="leave blank for unlimited">

        <label class="admin-modal-label">Expires — optional</label>
        <input id="new-key-expires" type="date">

        <div id="create-key-error" class="admin-modal-error" hidden></div>

        <div class="admin-modal-actions">
          <button type="button" class="admin-modal-btn"
                  onclick="ApiKeysPanel._closeCreate()">Cancel</button>
          <button type="button" class="admin-modal-btn primary" id="create-key-submit"
                  onclick="ApiKeysPanel._submitCreate()">Create key</button>
        </div>
      </div>

      <div id="create-key-reveal" hidden>
        <div class="admin-modal-error" style="background:rgba(245,166,35,0.12);border-color:#F5A623;color:#F5A623;margin-bottom:12px">
          This is the only time this key will be displayed. Copy it now.
        </div>
        <label class="admin-modal-label">Your new key</label>
        <div style="display:flex;gap:8px">
          <code id="new-key-value" style="flex:1;background:var(--bg);border:1px solid var(--accent);color:var(--accent);padding:8px 10px;border-radius:4px;font-size:0.78rem;word-break:break-all"></code>
          <button class="admin-modal-btn primary" onclick="ApiKeysPanel._copyKey()">Copy</button>
        </div>
        <div id="copy-confirm" style="display:none;color:var(--accent);font-size:0.7rem;margin-top:6px">Copied to clipboard.</div>
        <div class="admin-modal-actions" style="margin-top:18px">
          <label style="display:flex;align-items:center;gap:6px;font-size:0.72rem;color:var(--text-dim);cursor:pointer">
            <input type="checkbox" id="new-key-confirm-copied"
                   onchange="document.getElementById('create-key-close-btn').disabled = !this.checked">
            I've copied this key
          </label>
          <button type="button" class="admin-modal-btn primary" id="create-key-close-btn"
                  onclick="ApiKeysPanel._closeCreate()" disabled>Close</button>
        </div>
      </div>
    </div>
  </div>
```

CSS additions:

```css
.admin-modal-label {
  display: block; margin: 10px 0 4px;
  font-size: 0.7rem; color: var(--text-dim);
  letter-spacing: 0.06em;
}
.scope-picker {
  display: flex; flex-wrap: wrap; gap: 6px;
  border: 1px solid var(--border); border-radius: 4px;
  padding: 8px; min-height: 38px; background: var(--bg);
}
.scope-picker .scope-chip { cursor: pointer; opacity: 0.5; }
.scope-picker .scope-chip.selected { opacity: 1; }
```

- [ ] **Step 4: Wire `showCreate`/`_submitCreate` in ApiKeysPanel**

Replace the `showCreate` stub from Task 9 and add the submit/close/copy methods inside the same IIFE:

```javascript
  let _knownScopes = null;     // cached list from /api/keys/scopes
  let _selectedScopes = new Set();
  let _newKeyValue = '';

  async function _ensureScopes() {
    if (_knownScopes) return _knownScopes;
    const r = await AdminAuth.fetch('/api/keys/scopes', {}, 'admin-keys');
    if (!r.ok) throw new Error('failed to load scopes');
    _knownScopes = (await r.json()).scopes || [];
    return _knownScopes;
  }

  async function showCreate() {
    if (!AdminAuth.isSignedIn()) { AdminAuth.renderLock('admin-keys'); return; }
    document.getElementById('create-key-form').hidden = false;
    document.getElementById('create-key-reveal').hidden = true;
    document.getElementById('create-key-error').hidden = true;
    document.getElementById('new-key-name').value = '';
    document.getElementById('new-key-rpm').value = '';
    document.getElementById('new-key-expires').value = '';
    document.getElementById('new-key-confirm-copied').checked = false;
    document.getElementById('create-key-close-btn').disabled = true;

    _selectedScopes = new Set();
    const scopes = await _ensureScopes();
    const picker = document.getElementById('new-key-scopes');
    picker.innerHTML = scopes.map(s =>
      `<span class="scope-chip" data-scope="${esc(s)}"
        onclick="ApiKeysPanel._toggleScope('${esc(s)}', this)">${esc(s)}</span>`
    ).join('');

    document.getElementById('create-key-modal').hidden = false;
    setTimeout(() => document.getElementById('new-key-name').focus(), 0);
  }

  function _toggleScope(s, el) {
    if (_selectedScopes.has(s)) {
      _selectedScopes.delete(s);
      el.classList.remove('selected');
    } else {
      _selectedScopes.add(s);
      el.classList.add('selected');
    }
  }

  async function _submitCreate() {
    const name = document.getElementById('new-key-name').value.trim();
    const rpmRaw = document.getElementById('new-key-rpm').value.trim();
    const expRaw = document.getElementById('new-key-expires').value.trim();
    const errBox = document.getElementById('create-key-error');

    if (!name) { errBox.hidden = false; errBox.textContent = 'Name is required.'; return; }
    if (_selectedScopes.size === 0) {
      errBox.hidden = false; errBox.textContent = 'Pick at least one scope.'; return;
    }

    const body = {
      name,
      scopes: Array.from(_selectedScopes),
      rate_limit_rpm: rpmRaw ? Number(rpmRaw) : null,
      expires_at: expRaw ? expRaw + 'T00:00:00Z' : null,
    };

    const r = await AdminAuth.fetch('/api/keys', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    }, 'admin-keys');

    if (!r.ok) {
      const detail = await r.json().catch(() => ({}));
      errBox.hidden = false;
      errBox.textContent = detail.detail || `Failed (HTTP ${r.status})`;
      return;
    }

    const result = await r.json();
    _newKeyValue = result.key || '';
    document.getElementById('new-key-value').textContent = _newKeyValue;
    document.getElementById('create-key-form').hidden = true;
    document.getElementById('create-key-reveal').hidden = false;
    document.getElementById('copy-confirm').style.display = 'none';
    load(); // refresh the table behind the modal
  }

  function _copyKey() {
    if (!_newKeyValue || !navigator.clipboard) return;
    navigator.clipboard.writeText(_newKeyValue).then(() => {
      const c = document.getElementById('copy-confirm');
      c.style.display = 'block';
      setTimeout(() => { c.style.display = 'none'; }, 1500);
    });
  }

  function _closeCreate() {
    _newKeyValue = '';
    document.getElementById('new-key-value').textContent = '';
    document.getElementById('create-key-modal').hidden = true;
  }
```

Add these to the returned object: `_toggleScope, _submitCreate, _copyKey, _closeCreate`.

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/ui/test_static_markup.py -v 2>&1 | tail -8
```

Expected: 33 passing (30 + 3 new).

- [ ] **Step 6: Smoke-test**

```bash
MASTER_API_KEY=test python api/main.py &
sleep 2
open http://localhost:8000/
# Sign in. Click + New Key. Fill name + select scopes. Create.
# Reveal panel shows the full key with red one-time-reveal warning.
# Copy works. Close button is disabled until "I've copied this key" is checked.
# After close, row appears in the table.
kill %1
```

- [ ] **Step 7: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "$(cat <<'EOF'
feat(ui): API Keys panel — create modal with one-time reveal

Multi-step modal: name, scope chip picker (populated from
/api/keys/scopes), optional rate limit, optional expiry. After
successful POST, switches to a reveal pane that shows the full
key once with a red one-time warning, a copy button, and a
"Close" gated by an "I've copied this key" checkbox.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: API Keys panel — rotate, revoke, audit log strip

**Files:**
- Modify: `api/static/index.html`
- Modify: `tests/ui/test_static_markup.py`

- [ ] **Step 1: Write failing tests**

```python
def test_api_keys_panel_has_audit_strip(index_html_text):
    """Audit log strip must be present and call /api/keys/audit."""
    assert 'id="api-keys-audit"' in index_html_text
    assert "/api/keys/audit" in index_html_text


def test_api_keys_panel_has_rotate_and_revoke_handlers(index_html_text):
    assert "ApiKeysPanel.rotate" in index_html_text
    assert "ApiKeysPanel.revoke" in index_html_text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/ui/test_static_markup.py::test_api_keys_panel_has_audit_strip tests/ui/test_static_markup.py::test_api_keys_panel_has_rotate_and_revoke_handlers -v
```

Expected: 2 FAILS (the audit strip doesn't exist yet; rotate/revoke handlers exist as stubs but the substring check passes — only the audit one fails for sure).

- [ ] **Step 3: Append the audit strip to the panel**

Modify `tab-admin-keys` (from Task 9) — add after the closing `</div>` of the keys table panel:

```html
    <div class="panel" style="margin-top:14px">
      <span class="corner-tr"></span><span class="corner-bl"></span>
      <div class="panel-label">// AUDIT — last 20 admin actions
        <span style="float:right">
          <button class="action-btn" onclick="ApiKeysPanel.refreshAudit()">Refresh</button>
        </span>
      </div>
      <div id="api-keys-audit" style="margin-top:10px;font-size:0.72rem"></div>
    </div>
```

- [ ] **Step 4: Implement rotate / revoke / audit**

Replace the stubs in ApiKeysPanel:

```javascript
  async function rotate(id, name) {
    if (!confirm(`Rotate key "${name}"?\n\nThe old key will stop working immediately.`)) return;
    const r = await AdminAuth.fetch(`/api/keys/${encodeURIComponent(id)}/rotate`, {
      method: 'POST',
    }, 'admin-keys');
    if (!r.ok) {
      alert(`Rotate failed (HTTP ${r.status})`);
      return;
    }
    const result = await r.json();
    _newKeyValue = result.key || '';
    document.getElementById('new-key-value').textContent = _newKeyValue;
    document.getElementById('create-key-form').hidden = true;
    document.getElementById('create-key-reveal').hidden = false;
    document.getElementById('new-key-confirm-copied').checked = false;
    document.getElementById('create-key-close-btn').disabled = true;
    document.getElementById('copy-confirm').style.display = 'none';
    document.getElementById('create-key-modal').hidden = false;
    load();
    refreshAudit();
  }

  async function revoke(id, name) {
    if (!confirm(`Revoke key "${name}"?\n\nThis cannot be undone via the UI.`)) return;
    const r = await AdminAuth.fetch(`/api/keys/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }, 'admin-keys');
    if (!r.ok) {
      alert(`Revoke failed (HTTP ${r.status})`);
      return;
    }
    load();
    refreshAudit();
  }

  async function refreshAudit() {
    const host = document.getElementById('api-keys-audit');
    if (!host) return;
    const r = await AdminAuth.fetch('/api/keys/audit', {}, 'admin-keys');
    if (!r.ok) {
      host.innerHTML = `<div class="admin-modal-error" style="margin:0">Audit unavailable (HTTP ${r.status})</div>`;
      return;
    }
    const events = await r.json();
    if (!Array.isArray(events) || events.length === 0) {
      host.innerHTML = '<div style="color:var(--text-muted)">No admin actions recorded yet.</div>';
      return;
    }
    // Last 20, newest first.
    const recent = events.slice(-20).reverse();
    host.innerHTML = recent.map(e => `
      <div style="display:flex;gap:14px;padding:4px 0;border-bottom:1px dashed var(--border)">
        <span style="color:var(--text-muted);min-width:170px">${esc(new Date(e.ts).toLocaleString())}</span>
        <span style="color:var(--accent);min-width:90px">${esc(e.action)}</span>
        <span style="color:var(--text-dim)">${esc(e.name || '')}</span>
        <span style="color:var(--text-muted);font-family:var(--mono)">${esc(e.key_id)}</span>
      </div>
    `).join('');
  }
```

Update the auto-load handler to refresh audit alongside list:

```javascript
  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-keys') {
      load();
      refreshAudit();
    }
  });
```

Add `rotate, revoke, refreshAudit` to the returned object.

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/ui/test_static_markup.py -v 2>&1 | tail -8
```

Expected: 35 passing (33 + 2 new).

- [ ] **Step 6: Smoke-test**

```bash
MASTER_API_KEY=test python api/main.py &
sleep 2
open http://localhost:8000/
# Create a key, rotate it (reveal modal pops), revoke it. Watch the audit
# strip update with three events: created, rotated, revoked.
kill %1
```

- [ ] **Step 7: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "$(cat <<'EOF'
feat(ui): API Keys panel — rotate, revoke, audit log strip

Rotate reuses the create-modal reveal pane to show the new key once.
Revoke confirms then strikes the row. Audit strip pulls from
/api/keys/audit and renders the last 20 events newest-first.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4: Plugins panel

---

### Task 12: Plugins panel — catalog + plugin detail

**Files:**
- Modify: `api/static/index.html`
- Modify: `tests/ui/test_static_markup.py`

- [ ] **Step 1: Write failing tests**

```python
def test_plugins_panel_has_warning_banner(index_html_text):
    """Plugins panel must show a non-dismissable warning about in-process exec."""
    assert "execute plugin code" in index_html_text.lower(), (
        "expected warning copy about in-process plugin execution"
    )


def test_plugins_panel_has_two_pane_layout(index_html_text):
    assert 'id="plugins-list"' in index_html_text
    assert 'id="plugin-detail"' in index_html_text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/ui/test_static_markup.py::test_plugins_panel_has_warning_banner tests/ui/test_static_markup.py::test_plugins_panel_has_two_pane_layout -v
```

Expected: 2 FAILS.

- [ ] **Step 3: Replace the empty `tab-admin-plugins` panel**

```html
  <div class="tab-content" id="tab-admin-plugins" style="display:none">
    <div class="admin-modal-error" style="background:rgba(245,166,35,0.12);border-color:#F5A623;color:#F5A623;margin-bottom:14px">
      ⚠ Tool invocations execute plugin code in-process with full filesystem
      and environment access. Run only trusted plugins.
    </div>

    <div class="plugins-layout">
      <div class="panel plugins-list-panel">
        <span class="corner-tr"></span><span class="corner-bl"></span>
        <div class="panel-label">// PLUGINS
          <span style="float:right">
            <button class="action-btn" onclick="PluginsPanel.refresh()">Refresh</button>
          </span>
        </div>
        <div id="plugins-list" style="margin-top:10px"></div>
      </div>

      <div class="panel plugins-detail-panel">
        <span class="corner-tr"></span><span class="corner-bl"></span>
        <div class="panel-label" id="plugin-detail-label">// SELECT A PLUGIN</div>
        <div id="plugin-detail" style="margin-top:10px;color:var(--text-muted);font-size:0.78rem">
          Select a plugin from the left to see its skills and tools.
        </div>
      </div>
    </div>
  </div>
```

CSS:

```css
/* === Plugins panel ============================================== */
.plugins-layout {
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: 14px;
  align-items: start;
}
.plugin-card {
  border: 1px solid var(--border);
  padding: 10px 12px;
  cursor: pointer;
  margin-bottom: 6px;
  border-radius: 4px;
  transition: border-color 0.15s, background 0.15s;
}
.plugin-card:hover { border-color: var(--accent-dim); background: var(--accent-ghost, rgba(0,204,102,0.05)); }
.plugin-card.selected { border-color: var(--accent); background: var(--accent-ghost, rgba(0,204,102,0.08)); }
.plugin-card-title { font-size: 0.84rem; color: var(--text); font-weight: 500; }
.plugin-card-meta { font-size: 0.66rem; color: var(--text-dim); margin-top: 2px; }
.plugin-card-desc { font-size: 0.7rem; color: var(--text-dim); margin-top: 4px;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.plugin-status-pip {
  display: inline-block; width: 6px; height: 6px;
  border-radius: 50%; background: var(--accent); margin-right: 6px;
}
.plugin-status-pip.error { background: var(--danger, #e54b4b); }
.plugin-section-h {
  color: var(--text); font-size: 0.78rem; margin: 14px 0 6px;
  border-bottom: 1px solid var(--border); padding-bottom: 4px;
}
.skill-accordion, .tool-accordion {
  border: 1px solid var(--border); border-radius: 4px;
  margin-bottom: 6px; overflow: hidden;
}
.skill-accordion summary, .tool-accordion summary {
  list-style: none; cursor: pointer; padding: 8px 12px;
  font-size: 0.74rem; color: var(--text);
  display: flex; gap: 10px; align-items: center;
}
.skill-accordion summary::-webkit-details-marker,
.tool-accordion summary::-webkit-details-marker { display: none; }
.skill-accordion summary::before, .tool-accordion summary::before {
  content: '▸'; color: var(--text-muted); transition: transform 0.15s;
}
details[open] > summary::before { transform: rotate(90deg); }
.skill-accordion .body, .tool-accordion .body { padding: 10px 14px;
  border-top: 1px solid var(--border); }
.inject-badge {
  background: var(--accent-ghost, rgba(0,204,102,0.1));
  color: var(--accent); font-size: 0.6rem; padding: 1px 6px; border-radius: 999px;
}
```

- [ ] **Step 4: Add the PluginsPanel module (catalog + detail; tester in Task 13)**

```javascript
// ── PluginsPanel ──────────────────────────────────────────────────────────
window.PluginsPanel = (function () {
  let _selectedId = null;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function load() {
    if (!AdminAuth.isSignedIn()) {
      AdminAuth.renderLock('admin-plugins');
      return;
    }
    const list = document.getElementById('plugins-list');
    list.innerHTML = '<div style="color:var(--text-muted);font-size:0.78rem">Loading…</div>';

    const r = await AdminAuth.fetch('/api/plugins', {}, 'admin-plugins');
    if (!r.ok) {
      list.innerHTML = `<div class="admin-modal-error" style="margin:0">Failed (HTTP ${r.status})</div>`;
      return;
    }
    const plugins = await r.json();
    if (!Array.isArray(plugins) || plugins.length === 0) {
      list.innerHTML = '<div style="color:var(--text-muted);font-size:0.78rem">No plugins found in plugins/ directory.</div>';
      return;
    }

    list.innerHTML = plugins.map(p => `
      <div class="plugin-card ${p.id === _selectedId ? 'selected' : ''}"
           onclick="PluginsPanel.select('${esc(p.id)}')">
        <div class="plugin-card-title">
          <span class="plugin-status-pip ${p.error ? 'error' : ''}"></span>${esc(p.name || p.id)}
          <span style="color:var(--text-muted);font-size:0.66rem;margin-left:6px">${esc(p.version || '')}</span>
        </div>
        <div class="plugin-card-meta">
          ${(p.skills || []).length} skill${(p.skills || []).length === 1 ? '' : 's'}
          · ${(p.tools || []).length} tool${(p.tools || []).length === 1 ? '' : 's'}
        </div>
        <div class="plugin-card-desc">${esc(p.description || '')}</div>
      </div>
    `).join('');

    // Auto-select first if none selected.
    if (!_selectedId && plugins.length) select(plugins[0].id);
  }

  async function select(id) {
    _selectedId = id;
    document.querySelectorAll('.plugin-card').forEach(c => c.classList.remove('selected'));
    const cards = document.querySelectorAll('.plugin-card');
    // Re-mark; the click handler already added selected via load()'s next call,
    // but we render details independently of the next load().
    const r = await AdminAuth.fetch(`/api/plugins/${encodeURIComponent(id)}`, {}, 'admin-plugins');
    if (!r.ok) {
      document.getElementById('plugin-detail').innerHTML =
        `<div class="admin-modal-error" style="margin:0">Failed to load plugin (HTTP ${r.status})</div>`;
      return;
    }
    const p = await r.json();
    renderDetail(p);
    // mark the matching card.
    cards.forEach(c => {
      if (c.querySelector('.plugin-card-title').textContent.includes(p.name || p.id)) {
        c.classList.add('selected');
      }
    });
  }

  function renderDetail(p) {
    document.getElementById('plugin-detail-label').innerHTML =
      `// ${esc((p.name || p.id).toUpperCase())}`;
    const skillsHtml = (p.skills || []).map(s => `
      <details class="skill-accordion">
        <summary>
          <span style="flex:1">${esc(s.id)}</span>
          ${s.inject ? `<span class="inject-badge">${esc(s.inject)}</span>` : ''}
        </summary>
        <div class="body">${renderMarkdown(s.body || '*(no body)*')}</div>
      </details>
    `).join('');

    const toolsHtml = (p.tools || []).map(t => renderToolAccordion(p.id, t)).join('');

    document.getElementById('plugin-detail').innerHTML = `
      <div style="font-size:0.72rem;color:var(--text-dim);margin-bottom:8px">
        <code>${esc(p.path || '')}</code> · ${esc(p.author || 'unknown author')}
      </div>
      <div style="font-size:0.78rem;color:var(--text);margin-bottom:8px">
        ${esc(p.description || '')}
      </div>
      ${(p.skills || []).length ? `<div class="plugin-section-h">Skills</div>${skillsHtml}` : ''}
      ${(p.tools || []).length ? `<div class="plugin-section-h">Tools</div>${toolsHtml}` : ''}
    `;
  }

  // Stub — implemented in Task 13.
  function renderToolAccordion(pluginId, tool) {
    return `
      <details class="tool-accordion">
        <summary><span style="flex:1">${esc(tool.id)}</span></summary>
        <div class="body" style="color:var(--text-muted);font-size:0.7rem">
          Tester arrives in Task 13.
        </div>
      </details>
    `;
  }

  function refresh() { load(); }

  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-plugins') load();
  });

  return { load, refresh, select, renderDetail, renderToolAccordion };
})();
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/ui/test_static_markup.py -v 2>&1 | tail -8
```

Expected: 37 passing (35 + 2 new).

- [ ] **Step 6: Smoke-test**

```bash
MASTER_API_KEY=test python api/main.py &
sleep 2
# Make sure plugins/ has at least one example plugin.
ls plugins/
open http://localhost:8000/
# Sign in. Click ⚙ Admin → Plugins. Cards render on left. Detail on right.
# Skill accordions expand and render markdown body.
# Tool accordions show "Tester arrives in Task 13".
kill %1
```

- [ ] **Step 7: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "$(cat <<'EOF'
feat(ui): Plugins panel — catalog + plugin detail

Two-pane layout. Left: cards for each plugin with status pip, skill
and tool counts. Right: selected plugin's manifest, skill accordions
(rendered with renderMarkdown), and tool accordions (tester stubbed
until Task 13). Persistent warning banner about in-process execution
sits at the top.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Plugins panel — tool tester

**Files:**
- Modify: `api/static/index.html`
- Modify: `tests/ui/test_static_markup.py`

- [ ] **Step 1: Write failing tests**

```python
def test_plugins_panel_has_tool_tester(index_html_text):
    """Each tool accordion must contain a Run button + result container."""
    assert "tool-tester-run" in index_html_text or \
           "PluginsPanel.runTool" in index_html_text, (
        "expected a tool-tester run handler"
    )


def test_plugins_panel_has_param_form_renderer(index_html_text):
    assert "renderToolForm" in index_html_text or \
           "buildToolForm" in index_html_text, (
        "expected a tool-form renderer"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: 2 FAILS.

- [ ] **Step 3: Replace `renderToolAccordion` and add tester helpers**

In the PluginsPanel IIFE, replace `renderToolAccordion` and add the supporting functions:

```javascript
  // Per-tool last-5 invocations kept in memory for this panel session.
  const _runHistory = new Map(); // key: `${pluginId}:${toolId}` → array of {ts, ms, status, body}

  function renderToolAccordion(pluginId, tool) {
    const key = `${pluginId}:${tool.id}`;
    return `
      <details class="tool-accordion">
        <summary>
          <span style="flex:1">${esc(tool.id)}</span>
          <span style="color:var(--text-muted);font-size:0.66rem">${esc(tool.description || '')}</span>
        </summary>
        <div class="body">
          <form id="tool-form-${esc(key)}" onsubmit="event.preventDefault(); PluginsPanel.runTool('${esc(pluginId)}','${esc(tool.id)}')">
            ${renderToolForm(tool)}
            <div style="display:flex;justify-content:flex-end;margin-top:10px">
              <button type="submit" id="tool-tester-run-${esc(key)}"
                class="admin-modal-btn primary" style="padding:6px 18px">Run</button>
            </div>
          </form>
          <div id="tool-result-${esc(key)}" style="margin-top:10px"></div>
          <div id="tool-history-${esc(key)}" style="margin-top:10px"></div>
        </div>
      </details>
    `;
  }

  function renderToolForm(tool) {
    const params = tool.parameters || {};
    if (typeof params !== 'object' || Array.isArray(params)) {
      return '<div style="color:var(--text-muted);font-size:0.7rem">No parameter schema declared.</div>';
    }
    return Object.entries(params).map(([name, spec]) => {
      const required = spec && spec.required === true;
      const type = (spec && spec.type) || 'string';
      const def = spec && spec.default;
      const id = `tool-param-${name}`;
      const label = `<label class="admin-modal-label">${esc(name)}${required ? ' *' : ''}
        <span style="color:var(--text-muted);font-size:0.62rem">(${esc(type)})</span></label>`;
      let input;
      if (type === 'boolean') {
        input = `<input type="checkbox" id="${id}" ${def === true ? 'checked' : ''}>`;
      } else if (type === 'integer' || type === 'number') {
        input = `<input type="number" id="${id}" value="${esc(def ?? '')}" ${type === 'integer' ? 'step="1"' : ''}>`;
      } else if (Array.isArray(spec.enum)) {
        input = `<select id="${id}">${spec.enum.map(o =>
          `<option value="${esc(o)}" ${o === def ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
      } else if (type === 'array' || type === 'object') {
        input = `<textarea id="${id}" rows="3" placeholder="JSON or one item per line"></textarea>`;
      } else {
        input = `<input type="text" id="${id}" value="${esc(def ?? '')}">`;
      }
      return label + input;
    }).join('');
  }

  function _collectParams(tool) {
    const out = {};
    const params = tool.parameters || {};
    for (const [name, spec] of Object.entries(params)) {
      const el = document.getElementById('tool-param-' + name);
      if (!el) continue;
      const type = (spec && spec.type) || 'string';
      let v;
      if (type === 'boolean') v = el.checked;
      else if (type === 'integer') v = el.value === '' ? null : parseInt(el.value, 10);
      else if (type === 'number') v = el.value === '' ? null : parseFloat(el.value);
      else if (type === 'array' || type === 'object') {
        const raw = el.value.trim();
        if (!raw) { v = type === 'array' ? [] : {}; }
        else if (raw[0] === '[' || raw[0] === '{') {
          try { v = JSON.parse(raw); } catch (e) { throw new Error(`${name}: invalid JSON`); }
        } else {
          v = raw.split(/\n/).map(s => s.trim()).filter(Boolean);
        }
      } else {
        v = el.value;
      }
      if (spec && spec.required && (v === null || v === undefined || v === '')) {
        throw new Error(`${name} is required`);
      }
      if (v !== null && v !== undefined && v !== '') out[name] = v;
    }
    return out;
  }

  async function runTool(pluginId, toolId) {
    const key = `${pluginId}:${toolId}`;
    const resultBox = document.getElementById('tool-result-' + key);
    const runBtn = document.getElementById('tool-tester-run-' + key);

    // Re-fetch the tool spec to pick up any param schema we cached.
    const detailR = await AdminAuth.fetch(`/api/plugins/${encodeURIComponent(pluginId)}`, {}, 'admin-plugins');
    if (!detailR.ok) { resultBox.innerHTML = `<div class="admin-modal-error" style="margin:0">Cannot load plugin (HTTP ${detailR.status})</div>`; return; }
    const plugin = await detailR.json();
    const tool = (plugin.tools || []).find(t => t.id === toolId);
    if (!tool) { resultBox.innerHTML = '<div class="admin-modal-error" style="margin:0">Tool not found.</div>'; return; }

    let params;
    try { params = _collectParams(tool); }
    catch (e) { resultBox.innerHTML = `<div class="admin-modal-error" style="margin:0">${esc(e.message)}</div>`; return; }

    runBtn.disabled = true;
    runBtn.textContent = 'Running…';
    const t0 = performance.now();
    let r, body, status;
    try {
      r = await AdminAuth.fetch(`/api/plugins/${encodeURIComponent(pluginId)}/tools/${encodeURIComponent(toolId)}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(params),
      }, 'admin-plugins');
      const ms = Math.round(performance.now() - t0);
      status = r.status;
      const ct = r.headers.get('content-type') || '';
      if (ct.includes('application/json')) {
        body = await r.json();
        resultBox.innerHTML = `
          <div style="font-size:0.66rem;color:var(--text-dim);margin-bottom:4px">
            ${ms} ms · status ${status}
          </div>
          <pre class="md-code" style="font-size:0.72rem;max-height:280px;overflow:auto">${esc(JSON.stringify(body, null, 2))}</pre>
        `;
      } else {
        body = await r.text();
        resultBox.innerHTML = `
          <div style="font-size:0.66rem;color:var(--text-dim);margin-bottom:4px">${ms} ms · status ${status}</div>
          <pre class="md-code">${esc(body)}</pre>
        `;
      }
      if (!r.ok) {
        resultBox.querySelector('pre').classList.add('error');
      }

      const hist = _runHistory.get(key) || [];
      hist.push({ts: Date.now(), ms, status, summary: typeof body === 'object' ? JSON.stringify(body).slice(0,80) : String(body).slice(0,80)});
      while (hist.length > 5) hist.shift();
      _runHistory.set(key, hist);
      _renderHistory(key);
    } catch (e) {
      resultBox.innerHTML = `<div class="admin-modal-error" style="margin:0">${esc(e.message)}</div>`;
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = 'Run';
    }
  }

  function _renderHistory(key) {
    const host = document.getElementById('tool-history-' + key);
    if (!host) return;
    const hist = _runHistory.get(key) || [];
    if (!hist.length) { host.innerHTML = ''; return; }
    host.innerHTML = `
      <div style="font-size:0.62rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.1em;margin-top:8px">Last invocations</div>
      ${hist.slice().reverse().map(h => `
        <div style="display:flex;gap:10px;font-size:0.66rem;color:var(--text-dim);padding:2px 0">
          <span style="color:var(--text-muted);min-width:130px">${new Date(h.ts).toLocaleTimeString()}</span>
          <span style="color:${h.status >= 200 && h.status < 300 ? 'var(--accent)' : 'var(--danger,#e54b4b)'};min-width:40px">${h.status}</span>
          <span style="min-width:50px">${h.ms} ms</span>
          <span style="opacity:0.85">${esc(h.summary)}…</span>
        </div>
      `).join('')}
    `;
  }
```

Add `runTool, renderToolForm, _collectParams` to the returned object.

Add a CSS rule for error result `<pre>`:

```css
.md-code.error {
  border-color: var(--danger, #e54b4b);
  color: var(--danger, #e54b4b);
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/ui/test_static_markup.py -v 2>&1 | tail -8
```

Expected: 39 passing (37 + 2 new).

- [ ] **Step 5: Smoke-test**

```bash
MASTER_API_KEY=test python api/main.py &
sleep 2
open http://localhost:8000/
# Plugins → expand a tool → fill params → Run.
# Result renders with timing + status + JSON body.
# Run again — history grows (last 5 retained).
# Pass invalid params (e.g. invalid JSON in array) — error banner appears.
kill %1
```

- [ ] **Step 6: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "$(cat <<'EOF'
feat(ui): Plugins panel — tool tester with schema-driven form

Each tool accordion gets a form rendered from its declared parameter
schema (string/integer/number/boolean/array/object/enum). On Run,
POSTs to /api/plugins/{id}/tools/{tool}, pretty-prints the JSON
response, shows timing + status, and keeps the last 5 invocations
per tool in memory for the panel session.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5: Exports panel

---

### Task 14: Exports panel — list, view modal, single download/delete

**Files:**
- Modify: `api/static/index.html`
- Modify: `tests/ui/test_static_markup.py`

- [ ] **Step 1: Write failing tests**

```python
def test_exports_panel_has_list(index_html_text):
    assert 'id="exports-list"' in index_html_text
    assert "ExportsPanel.refresh" in index_html_text


def test_exports_panel_has_view_modal(index_html_text):
    assert 'id="export-view-modal"' in index_html_text
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: 2 FAILS.

- [ ] **Step 3: Replace the empty `tab-admin-exports` panel**

```html
  <div class="tab-content" id="tab-admin-exports" style="display:none">
    <div class="panel">
      <span class="corner-tr"></span><span class="corner-bl"></span>
      <div class="panel-label">// EXPORTS
        <span style="float:right">
          <span id="exports-bulk-bar" hidden style="margin-right:14px;font-size:0.7rem;color:var(--text-dim)">
            <span id="exports-selected-count">0</span> selected
            <button class="action-btn small" onclick="ExportsPanel.downloadZip()">Download zip</button>
            <button class="action-btn small danger" onclick="ExportsPanel.bulkDelete()">Delete</button>
          </span>
          <button class="action-btn" onclick="ExportsPanel.refresh()">Refresh</button>
        </span>
      </div>
      <div id="exports-list" style="margin-top:10px"></div>
    </div>
  </div>

  <!-- ── Export view modal ───────────────────────────────────────── -->
  <div id="export-view-modal" class="admin-modal" hidden role="dialog" aria-modal="true">
    <div class="admin-modal-card" style="width:760px;max-width:92vw;max-height:80vh;overflow:auto">
      <h3 id="export-view-title" style="margin-bottom:14px">Export</h3>
      <div id="export-view-body" style="font-size:0.78rem"></div>
      <div class="admin-modal-actions">
        <button type="button" class="admin-modal-btn"
                onclick="ExportsPanel._closeView()">Close</button>
      </div>
    </div>
  </div>
```

- [ ] **Step 4: Add the ExportsPanel module**

```javascript
// ── ExportsPanel ──────────────────────────────────────────────────────────
window.ExportsPanel = (function () {
  let _selected = new Set();
  let _items = [];

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function load() {
    const list = document.getElementById('exports-list');
    list.innerHTML = '<div style="color:var(--text-muted);font-size:0.78rem">Loading…</div>';
    // Exports endpoint is not master-key gated today, but we still attach the
    // header for future-proofing (cheap, harmless, consistent with other admin panels).
    const r = await fetch('/api/exports', {headers: AdminAuth.authHeaders()});
    if (!r.ok) {
      list.innerHTML = `<div class="admin-modal-error" style="margin:0">Failed (HTTP ${r.status})</div>`;
      return;
    }
    const data = await r.json();
    _items = data.exports || [];
    if (!_items.length) {
      list.innerHTML = '<div style="color:var(--text-muted);padding:14px 0">No exports yet — use "Export session" from the Chat tab.</div>';
      _refreshBulkBar();
      return;
    }
    list.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;font-size:0.66rem;color:var(--text-dim);margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid var(--border)">
        <input type="checkbox" id="exports-select-all" onchange="ExportsPanel._toggleSelectAll(this.checked)">
        <span>Select all</span>
      </div>
      ${_items.map(rowHtml).join('')}
    `;
    _refreshBulkBar();
  }

  function rowHtml(e) {
    const kb = (e.size / 1024).toFixed(1);
    const date = new Date(e.modified * 1000).toLocaleString();
    const checked = _selected.has(e.filename) ? 'checked' : '';
    return `
      <div class="export-row" id="export-row-${esc(e.filename)}" style="display:flex;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)">
        <input type="checkbox" data-filename="${esc(e.filename)}" ${checked}
               onchange="ExportsPanel._toggle('${esc(e.filename)}', this.checked)" style="margin-top:3px">
        <div style="flex:1;min-width:0">
          <div style="font-size:0.8rem;color:var(--text);font-weight:500">${esc(e.filename)}</div>
          <div style="font-size:0.66rem;color:var(--text-dim);margin-top:2px">${date} · ${kb} KB</div>
          <div style="font-size:0.7rem;color:var(--text-muted);margin-top:3px;white-space:pre-wrap;max-height:48px;overflow:hidden">${esc((e.preview || '').trim())}</div>
        </div>
        <div style="display:flex;gap:6px;flex-shrink:0;align-self:flex-start">
          <button class="action-btn small" onclick="ExportsPanel.view('${esc(e.filename)}')">View</button>
          <button class="action-btn small" onclick="ExportsPanel.download('${esc(e.filename)}')">Download</button>
          <button class="action-btn small danger" onclick="ExportsPanel.deleteOne('${esc(e.filename)}')">Delete</button>
        </div>
      </div>
    `;
  }

  function _toggle(name, on) {
    if (on) _selected.add(name); else _selected.delete(name);
    _refreshBulkBar();
  }

  function _toggleSelectAll(on) {
    _selected = on ? new Set(_items.map(e => e.filename)) : new Set();
    document.querySelectorAll('#exports-list input[type=checkbox][data-filename]')
      .forEach(c => { c.checked = on; });
    _refreshBulkBar();
  }

  function _refreshBulkBar() {
    const bar = document.getElementById('exports-bulk-bar');
    if (!bar) return;
    const count = _selected.size;
    bar.hidden = count === 0;
    document.getElementById('exports-selected-count').textContent = count;
  }

  async function view(filename) {
    const r = await fetch('/api/exports/' + encodeURIComponent(filename), {headers: AdminAuth.authHeaders()});
    if (!r.ok) { alert('Export not found.'); return; }
    const text = await r.text();
    document.getElementById('export-view-title').textContent = filename;
    document.getElementById('export-view-body').innerHTML = renderMarkdown(text);
    document.getElementById('export-view-modal').hidden = false;
  }

  function _closeView() {
    document.getElementById('export-view-modal').hidden = true;
  }

  function download(filename) {
    const url = '/api/exports/' + encodeURIComponent(filename);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  async function deleteOne(filename) {
    if (!confirm(`Delete "${filename}"?`)) return;
    const r = await fetch('/api/exports/' + encodeURIComponent(filename), {
      method: 'DELETE',
      headers: AdminAuth.authHeaders(),
    });
    if (!r.ok) { alert(`Delete failed (HTTP ${r.status})`); return; }
    _selected.delete(filename);
    load();
  }

  // Stubs for Task 15.
  function downloadZip() { /* Task 15 */ }
  function bulkDelete() { /* Task 15 */ }

  function refresh() { load(); }

  window.addEventListener('adminPanelActivated', e => {
    if (e.detail && e.detail.panel === 'admin-exports') load();
  });

  // Esc closes the view modal.
  document.addEventListener('keydown', e => {
    const m = document.getElementById('export-view-modal');
    if (m && !m.hidden && e.key === 'Escape') _closeView();
  });

  return { load, refresh, view, download, deleteOne, downloadZip, bulkDelete,
           _toggle, _toggleSelectAll, _closeView };
})();
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/ui/test_static_markup.py -v 2>&1 | tail -8
```

Expected: 41 passing (39 + 2 new).

- [ ] **Step 6: Smoke-test**

```bash
MASTER_API_KEY=test python api/main.py &
sleep 2
# Add a test export so the panel has content.
mkdir -p data/exports
printf "# Test export\n\nHello *world* with `code`.\n" > data/exports/2026-05-06-smoke.md
open http://localhost:8000/
# Sign in. Click ⚙ Admin → Exports.
# Row appears. Click View — modal renders the markdown nicely.
# Click Download — file downloads.
# Click Delete — row removed after confirm.
kill %1
```

- [ ] **Step 7: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "$(cat <<'EOF'
feat(ui): Exports panel — list, view modal, download, delete

Lists exports with selection checkboxes, view (in-app modal with
renderMarkdown), per-row download (Blob URL trick) and delete.
Bulk actions appear as soon as any row is selected (handlers
stubbed until Task 15).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: Exports panel — bulk select, zip download, bulk delete

**Files:**
- Modify: `api/static/index.html`
- Modify: `tests/ui/test_static_markup.py`

- [ ] **Step 1: Write failing tests**

```python
def test_exports_panel_has_zip_action(index_html_text):
    assert "/api/exports/zip" in index_html_text
    assert "ExportsPanel.downloadZip" in index_html_text


def test_exports_panel_has_bulk_delete(index_html_text):
    assert "ExportsPanel.bulkDelete" in index_html_text
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: probably PASS for the substrings (they appear in the stubs added in Task 14). If they pass already, ADD a stronger test:

```python
def test_exports_zip_uses_get_with_names_param(index_html_text):
    """Zip endpoint takes a comma-separated names param via GET."""
    import re
    # Look for fetch('/api/exports/zip?names=...') or similar.
    assert re.search(r"/api/exports/zip\?names=", index_html_text), (
        "expected zip request to use ?names= query"
    )
```

Run only that test; if it's new and fails, proceed.

- [ ] **Step 3: Implement bulk actions**

Replace the stubs in ExportsPanel:

```javascript
  function downloadZip() {
    if (_selected.size === 0) return;
    const names = Array.from(_selected).join(',');
    const url = '/api/exports/zip?names=' + encodeURIComponent(names);
    // We can't easily set Authorization on a window navigation, but the
    // exports zip endpoint is not master-key gated. Use anchor click.
    const a = document.createElement('a');
    a.href = url;
    a.download = 'enclave-exports.zip';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  async function bulkDelete() {
    const count = _selected.size;
    if (count === 0) return;
    if (!confirm(`Delete ${count} export${count === 1 ? '' : 's'}?`)) return;
    // Fire deletes in parallel.
    const names = Array.from(_selected);
    const results = await Promise.all(names.map(n =>
      fetch('/api/exports/' + encodeURIComponent(n), {
        method: 'DELETE',
        headers: AdminAuth.authHeaders(),
      })
    ));
    const failed = names.filter((_, i) => !results[i].ok);
    if (failed.length) alert(`Delete failed for: ${failed.join(', ')}`);
    _selected.clear();
    load();
  }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/ui/test_static_markup.py -v 2>&1 | tail -8
```

Expected: 42+ passing.

- [ ] **Step 5: Smoke-test**

```bash
MASTER_API_KEY=test python api/main.py &
sleep 2
mkdir -p data/exports
for i in 1 2 3; do printf "# Test $i\n\nbody $i" > "data/exports/2026-05-06-smoke-$i.md"; done
open http://localhost:8000/
# Sign in. Exports panel: select-all → "Download zip" button → enclave-exports.zip downloads.
# Select-all → Delete → all three rows gone.
kill %1
```

- [ ] **Step 6: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "$(cat <<'EOF'
feat(ui): Exports panel — bulk zip download + bulk delete

Bulk bar shows when ≥1 row is selected. "Download zip" hits
/api/exports/zip?names=... and triggers a browser download.
"Delete" fires concurrent DELETEs and reports any failures.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Run the full test suite**

```bash
pytest tests/ -v --tb=short --ignore=tests/e2e 2>&1 | tail -25
```

Expected: 21 original UI tests + ~17 new UI tests = ~38 UI passing; all router tests pass; total greater than the baseline by ~25 tests.

- [ ] **Live walk-through (~5 min)**

```bash
MASTER_API_KEY=test python api/main.py
# In another terminal: open http://localhost:8000/
# 1. Click ⚙ Admin → API Keys → Sign in as admin → enter "test"
# 2. + New Key → name "smoke" → pick scopes "chat", "models" → Create
#    → reveal pane shows full key → Copy → check "I've copied" → Close
#    → row appears in table → Audit strip shows "created"
# 3. Click Rotate → reveal pane → Close → audit shows "rotated"
# 4. Click Revoke → row strikes → audit shows "revoked"
# 5. Sign out (top-right of dropdown) → status pill goes back to "Locked"
#    → click ⚙ Admin → API Keys → lock state renders
# 6. Sign back in → ⚙ Admin → Plugins → catalog renders → expand a tool
#    → fill params → Run → result renders → run again → history grows
# 7. ⚙ Admin → Exports → select all → Download zip → file downloads
#    → bulk delete → list empties
# Ctrl-C the server.
```

- [ ] **Open the PR**

```bash
git push -u origin <your-branch-name>
gh pr create --title "Settings & Permissions UI: API Keys + Plugins + Exports under Admin dropdown" --body "$(cat <<'EOF'
## Summary
Closes the gap where `/api/keys`, `/api/plugins`, and `/api/exports`
shipped on master with no UI surface. Adds an Admin dropdown to the
tab strip with three new panels:

- API Keys: list / create (one-time reveal) / rotate / revoke / audit
- Plugins: catalog cards + per-tool tester with schema-driven form
- Exports: list / view (markdown modal) / download / zip / bulk delete

Plus four small backend additions: `/api/keys/scopes`,
`/api/keys/audit`, `/api/exports/zip`, master-key gate on all
`/api/plugins/*` endpoints. Master-key auth uses `sessionStorage`
(never `localStorage`).

Spec: `docs/superpowers/specs/2026-05-06-settings-and-permissions-ui-design.md`
Plan: `docs/superpowers/plans/2026-05-06-settings-and-permissions-ui.md`

## Test plan
- [x] `pytest tests/ -v --ignore=tests/e2e` — all router + UI tests pass
- [ ] Manual: full Admin walk-through (create / rotate / revoke / audit
      / sign out / sign in / plugin tester / export zip)
- [ ] Manual: Esc / Tab / arrow-key navigation through Admin dropdown
- [ ] Manual: refresh page mid-session → sessionStorage retains key,
      panels reload correctly

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Delete the salvage branch**

Once the PR merges, the `claude/compose-ui-integration` branch can be removed:

```bash
git branch -D claude/compose-ui-integration   # local
git push origin --delete claude/compose-ui-integration   # remote, if present
```

---

## Self-review notes

**Spec coverage:**
- Admin dropdown (spec §1) → Task 6.
- AdminAuth (spec §2) → Task 7.
- API Keys panel (spec §3) → Tasks 9–11 (list / create+reveal / rotate+revoke+audit).
- Plugins panel + tester (spec §4) → Tasks 12–13.
- Exports panel + bulk (spec §5) → Tasks 14–15.
- Backend additions (spec §6) → Tasks 1 (refactor), 2 (/scopes), 3 (audit), 4 (plugins gate), 5 (/zip).
- File structure (spec §7) → mirrored in this plan's File Structure.
- Salvage strategy (spec §9) → "Delete the salvage branch" step in Final verification.
- Test strategy (spec §10) → every task ships its own UI tests; router tests in Phase 1.
- Out-of-scope items (spec §8) → none added.

**Placeholder scan:** None found. The "Tester arrives in Task 13" string in Task 12 is a deliberate stub that gets replaced in Task 13.

**Type / name consistency:**
- `AdminAuth.authHeaders` / `AdminAuth.fetch` used identically across all panel modules.
- `AdminMenu.showPanel(panelId)` and `adminPanelActivated` event payload `{panel: id}` consistent.
- `_safe_filename` reused in `/api/exports/zip` matches the existing helper in `api/routers/exports.py`.
- `require_master_key` (extracted in Task 1) imported as `_require_master` alias in `api_keys.py` and as itself in `plugins.py` — naming intentional to minimize diff in `api_keys.py`.
- `renderMarkdown` defined in Task 8 is consumed in Tasks 12 (skill bodies) and 14 (export view).
