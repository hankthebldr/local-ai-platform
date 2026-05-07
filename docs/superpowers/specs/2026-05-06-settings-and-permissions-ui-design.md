# Settings & Permissions UI

**Date:** 2026-05-06
**Status:** Approved (brainstorming complete; awaiting implementation plan)
**Author:** Henry Reed (with Claude)
**Targets:** master (post-PR #37)
**References:**
- Predecessor specs: `docs/superpowers/specs/2026-04-12-api-keys-plugins-cortex-rebrand-design.md` (backend for API keys + plugins, shipped)
- Predecessor plans: `docs/plans/2026-04-22-ui-week1-improvements.md` (Week-1 UI hygiene, shipped), `docs/plans/2026-04-23-workflow-observability-ui.md` (workflow v2 UI, shipped — explicitly defers "Plugins/API-keys/Context UIs (separate 'Settings & Permissions' PR)" — this spec is that PR)
- Salvage source: `claude/compose-ui-integration` branch, commits `7922db0`, `2ad708d`, `c51cca6`

---

## Overview

Three backend routers — `/api/keys`, `/api/plugins`, `/api/exports` — are live on master with full CRUD support but have **zero UI surface**. The `compose-ui-integration` branch built panels for them in the Memory tab, never merged, and has now drifted past mergeable rebase distance. This spec rewrites those panels under a new top-level "Admin" dropdown in the tab strip, hardens the master-key auth flow, and adds a Plugins tool tester that the original branch did not include.

**Goal:** make every shipped backend router reachable from the dashboard, with default-deny treatment for state-changing admin actions.

**Non-goal:** redesigning the dashboard's information architecture, splitting `index.html`, or adding UI for `agents` / `a2a` / Drawflow composer (each gets its own spec).

---

## Scope

| Surface | Backend status | Existing UI | Spec action |
|---|---|---|---|
| API Keys (`/api/keys`) | Shipped (PR #9) | None on master | Build under Admin → API Keys |
| Plugins catalog (`/api/plugins`) | Shipped (PR #9) | None on master | Build under Admin → Plugins |
| Plugins tool tester (`POST /api/plugins/.../tools/...`) | Shipped (PR #9) | None on master | Build (new — not in salvage source) |
| Exports (`/api/exports`) | Shipped (PR #15 era) | None on master | Build under Admin → Exports |
| Workflow v2 surfacing (hooks/retries/escalation/roles) | Shipped | ✓ Already present (verified by 21 passing UI tests) | Out of scope — done |
| Agents (`/api/agents`) | Shipped | None | Out of scope — separate brainstorm |
| Agent-to-Agent (`/api/a2a`) | Shipped | None | Out of scope — separate brainstorm |
| Drawflow no-code composer | Stranded on `claude/magical-payne` | Stranded | Out of scope — separate "rescue or abandon" decision |

---

## Architecture

### Navigation

A new `⚙ Admin ▾` control sits at the right of the existing tab strip, separated from operational tabs by a 1px divider. It opens a small menu with three items: **API Keys**, **Plugins**, **Exports**. Selecting an item swaps the visible `.tab-content` panel (using the existing `switchTab` machinery extended to recognize admin panel ids) and marks the dropdown trigger `.active`.

```
┌─ Tab strip ────────────────────────────────────────────────────────────────┐
│ Dashboard │ Models │ Memory │ Discover │ Research │ Workflows │ Documents  │  │ ⚙ Admin ▾
└────────────────────────────────────────────────────────────────────────────┘ │
                                                                               ├─ API Keys
                                                                               ├─ Plugins
                                                                               └─ Exports
```

The dropdown is keyboard-accessible (Enter/Space opens, Esc closes, ↑/↓ navigate items, Tab leaves), uses `role="menu"` and `role="menuitem"` for ARIA, and closes on outside click. Implementation lives in a single `(function AdminMenu(){…})()` IIFE module at the bottom of the existing `<script>` block — no framework, no build step, consistent with the current SPA.

### Auth gate

A new `AdminAuth` module wraps all three admin panels. Lifecycle:

1. **Panel activation** → check `sessionStorage.getItem('enclave.admin.masterKey')`.
2. **Key present** → attach `Authorization: Bearer <key>` to all `/api/keys`, `/api/plugins`, `/api/exports` requests originating from admin panels and load the panel.
3. **Key absent** → render a centered lock state: a small lock icon, the text "Admin actions require the master key", and a `[ Sign in as admin ]` button that opens a modal asking for the master key. On submit, store in `sessionStorage` (cleared on tab close, never `localStorage`) and load the panel.
4. **401 response** → clear `sessionStorage.enclave.admin.masterKey`, re-show the lock state with a "Master key rejected" banner, do not retry.
5. **Sign out** → a small `Signed in as admin · Sign out` pill appears in the dropdown menu when authenticated. Sign out clears `sessionStorage` and dismisses the panels back to lock state.

**Why `sessionStorage`, not `localStorage`:** the global rule "never paste credentials in chat" extends to never persisting them across browser restarts. `sessionStorage` survives navigations within the tab but dies on tab close. The desktop pywebview shell counts as a tab — closing the app clears the key, matching default-deny.

### Plugins endpoint guarding

The Plugins catalog endpoints (`GET /api/plugins`, `GET /api/plugins/{id}`) are currently unguarded. The tool-invocation endpoint (`POST /api/plugins/{id}/tools/{tool_id}`) executes plugin code in-process with full filesystem and env access. To match the UI's admin gating and to align with the default-deny posture, this spec adds a `Depends(_require_master)` to **all** Plugins endpoints — list and invoke alike. The UI will always send the master key when it talks to Plugins. Programmatic clients that need plugin discovery without the master key should be revisited in a separate spec.

---

## Component design

### Admin dropdown

```html
<div class="tab-dropdown" role="presentation">
  <button class="tab-btn admin-trigger" id="admin-trigger"
          aria-haspopup="menu" aria-expanded="false"
          onclick="AdminMenu.toggle(this)">
    ⚙ Admin <span class="caret">▾</span>
  </button>
  <div class="admin-menu" id="admin-menu" role="menu" hidden>
    <button class="admin-menu-item" role="menuitem" data-panel="admin-keys">API Keys</button>
    <button class="admin-menu-item" role="menuitem" data-panel="admin-plugins">Plugins</button>
    <button class="admin-menu-item" role="menuitem" data-panel="admin-exports">Exports</button>
    <div class="admin-menu-divider"></div>
    <div class="admin-menu-status" id="admin-menu-status">
      <span class="dot"></span> <span id="admin-menu-status-text">Locked</span>
      <button class="admin-menu-signout" hidden onclick="AdminAuth.signOut()">Sign out</button>
    </div>
  </div>
</div>
```

`.admin-trigger.active` lights green when any of the three admin panels are active. The `.admin-menu` floats under the trigger with `position: absolute` and the existing panel border treatment so it visually matches a `.panel`.

### API Keys panel

Layout:

```
┌─ panel: API KEYS ──────────────────────────────────────────────────────────┐
│ [+ New Key]                                                  [↻ Refresh]   │
├────────────────────────────────────────────────────────────────────────────┤
│ Name         | Key            | Scopes                | RPM   | Last used  │
│ ─────────────|────────────────|───────────────────────|───────|─────────── │
│ homelab      | sk-hl…d3a2     | chat, models          | 60    | 12m ago    │
│ ci-runner    | sk-ci…f001     | completions, models   | —     | never      │
│ DEPRECATED   | sk-old…aa11    | chat                  | —     | 3d ago     │
│ ↳ Usage: 1,542 req · 234,567 tokens · last 7d sparkline                    │
│ ↳ [Rotate] [Revoke]                                                        │
├─ Audit log (last 20) ──────────────────────────────────────────────────────┤
│ 2026-05-06 09:12  created  homelab                                         │
│ 2026-05-04 14:08  rotated  ci-runner                                       │
└────────────────────────────────────────────────────────────────────────────┘
```

- Click a row to expand the usage detail (sparkline rendered with the existing vendored d3).
- "New Key" opens a modal with: name (text), scopes (multi-select chips, populated from a new `GET /api/keys/scopes` endpoint), rate limit (number, optional), expiry (date, optional). On submit, response shows the full key once with a copy button and a red banner: *"This is the only time this key will be displayed. Copy it now."* The modal cannot be dismissed without an "I've copied it" confirmation while the key is visible.
- Revoke shows a confirm dialog naming the key; on confirm, strikes the row immediately.
- Rotate shows a confirm dialog explaining "the old key will stop working immediately"; on confirm, displays the new key in the same one-time-reveal modal.
- Audit log strip at the bottom lists the last 20 admin actions (create/rotate/revoke), pulled from a new `GET /api/keys/audit` endpoint backed by an in-memory ring buffer in `api_key_service` (capacity 200, lost on restart).

### Plugins panel

Two-pane layout (left 1/3 list, right 2/3 detail):

```
┌─ Plugins panel ────────────────────────────────────────────────────────────┐
│ ⚠ Tool invocations execute plugin code in-process with full filesystem      │
│   and environment access. Run only trusted plugins.                         │
├──────────────────────────┬─────────────────────────────────────────────────┤
│ ● web-search 1.0.0       │ Web Search · 1.0.0 · by local                   │
│   Search the web         │ plugins/example-web-search/                     │
│   ✓ 1 skill · 1 tool     │                                                 │
│                          │ Skills:                                         │
│ ● code-runner 1.0.0      │   ▾ search-expert (system inject)               │
│   Run Python code        │     [markdown body rendered]                    │
│   ✓ 1 skill · 1 tool     │                                                 │
│                          │ Tools:                                          │
│                          │   ▾ web_search                                  │
│                          │     query   [____________________]              │
│                          │     max_results [5]                             │
│                          │     [ Run ]                                     │
│                          │     ┌─ result (218 ms) ────────────────────────┐│
│                          │     │ {                                        ││
│                          │     │   "results": [...]                       ││
│                          │     │ }                                        ││
│                          │     └──────────────────────────────────────────┘│
└──────────────────────────┴─────────────────────────────────────────────────┘
```

**Tool tester rendering rules.** From the tool's declared `parameters` schema:

| Schema type | Form control |
|---|---|
| `string` | `<input type="text">` |
| `string` with `enum` | `<select>` |
| `integer` / `number` | `<input type="number">` (with `min`/`max` if present) |
| `boolean` | `<input type="checkbox">` |
| `array` | `<textarea>`, one item per line, parsed as JSON if first char is `[`/`{` else as strings |
| `object` | `<textarea>` accepting JSON, validated on submit |

Required params are marked with a `*` and validated client-side before the request. Unknown types fall back to a textarea with a "raw JSON" hint.

**Result panel.** JSON responses are pretty-printed and syntax-highlighted with a small (~40 LOC) custom highlighter — no vendor dep. Non-JSON responses are shown as `<pre>`. Errors render in a danger banner with the response status, the `detail` field if present, and the full traceback if the server included one (it currently does for `RuntimeError`). Each invocation is timestamped with duration; the last 5 invocations per tool are kept in memory for the panel session so the user can compare runs.

The persistent warning banner at the top of the Plugins panel is non-dismissable.

### Shared helper: `renderMarkdown(text)`

A ~60-line vanilla-JS renderer that handles the subset of CommonMark that appears in chat exports and plugin skill bodies:

| Construct | Renders to |
|---|---|
| `# H1` … `###### H6` | `<h1>` … `<h6>` |
| Blank-line-separated paragraphs | `<p>` |
| `` `inline` `` | `<code>` |
| Triple-backtick fenced code blocks | `<pre><code>` (no syntax highlighting) |
| `- item` / `* item` lists | `<ul><li>` |
| `1. item` lists | `<ol><li>` |
| `[text](url)` | `<a href rel="noopener" target="_blank">` |
| `**bold**` / `*italic*` | `<strong>` / `<em>` |
| Anything else | escaped text |

All output is HTML-escaped before substitution; the helper never produces script-executing markup. Lives at the top of the existing `<script>` block so both the Plugins panel and the Exports `View` modal can call it. Vendor markdown library is intentionally not used — the surface is small enough that 60 LOC beats the supply-chain footprint of `marked`/`markdown-it`.

### Exports panel

Single-pane list layout:

```
┌─ panel: EXPORTS ───────────────────────────────────────────────────────────┐
│ [☐ Select all]   [↻ Refresh]            Selected: 0   [Download zip] [Delete] │
├────────────────────────────────────────────────────────────────────────────┤
│ ☐  2026-05-04-1245-dolphin3.md     12 KB   May 4, 12:45                    │
│    > # Dolphin3 chat — system bring-up sequence …                          │
│    [View]  [Download]  [Delete]                                            │
│ ☐  2026-04-30-0900-mistral.md       4 KB   Apr 30, 09:00                   │
│    > Quick check on prompt latency variance.                               │
│    [View]  [Download]  [Delete]                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

- Each row has a checkbox; bulk actions appear when selection ≥ 1.
- `View` opens an in-app modal that renders the markdown using the in-house `renderMarkdown(text)` helper described below. Anything the helper doesn't recognize falls back to `<pre>`.
- `Download` triggers a browser download via a temporary `<a download>` link from a Blob URL.
- `Delete` confirms then removes the row; bulk delete confirms once with the count.
- `Download zip` POSTs `/api/exports/zip` with the selected names; backend streams a zip.
- Empty state: *"No exports yet — use 'Export session' from the Chat tab"* with a button that switches to Dashboard and focuses the chat panel.

---

## Backend additions

Four small, focused additions:

### 1. `GET /api/keys/scopes`

```python
@router.get("/scopes")
async def list_scopes(request: Request):
    _require_master(request)
    return {"scopes": list(SCOPE_MAP.keys())}
```

Returns the scope identifiers used by the middleware so the UI doesn't hardcode them. Master-key gated for consistency.

### 2. `GET /api/keys/audit`

A ring-buffered in-memory log on `APIKeyService`:

```python
class APIKeyService:
    def __init__(self):
        ...
        self._audit: collections.deque = collections.deque(maxlen=200)

    def _log(self, action: str, key_id: str, name: str | None = None):
        self._audit.append({
            "ts": datetime.utcnow().isoformat() + "Z",
            "action": action,
            "key_id": key_id,
            "name": name,
        })
```

Every `create_key`, `rotate_key`, `revoke_key` calls `self._log(...)`. The router exposes:

```python
@router.get("/audit")
async def get_audit(request: Request):
    _require_master(request)
    return list(_service._audit)
```

Persistence is explicitly out of scope. If the user wants durable audit, that's its own enterprise spec.

### 3. `GET /api/exports/zip?names=a,b,c`

```python
@router.get("/zip")
async def zip_exports(names: str):
    requested = [_safe_filename(n) for n in names.split(",") if n]
    paths = [EXPORTS_DIR / n for n in requested if (EXPORTS_DIR / n).is_file()]
    if not paths:
        raise HTTPException(status_code=404, detail="no matching exports")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=p.name)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": "attachment; filename=enclave-exports.zip"})
```

Path traversal is blocked by `_safe_filename` per name (already in the router). Listing failures (file deleted between selection and request) are silently dropped — only return 404 if zero files match.

### 4. Master-key dependency on `/api/plugins/*`

```python
# api/routers/plugins.py
from .api_keys import _require_master  # reuse the existing helper

@router.get("", dependencies=[Depends(_require_master)])
async def list_plugins(): ...

@router.get("/{plugin_id}", dependencies=[Depends(_require_master)])
async def get_plugin(plugin_id: str): ...

@router.post("/{plugin_id}/tools/{tool_id}", dependencies=[Depends(_require_master)])
async def invoke_tool(plugin_id: str, tool_id: str, params: dict): ...
```

The `_require_master` helper currently lives in `api_keys.py` as a private function. Extract it to `api/middleware.py` as `require_master_key(request)` (public) and import from both routers. One-line refactor, kept inside this spec's scope.

---

## File structure

**Modified:**
- `api/static/index.html` — admin dropdown, three panels, AdminAuth + AdminMenu modules, modal markup
- `api/routers/api_keys.py` — `/scopes`, `/audit` endpoints; calls into audit ring buffer
- `api/routers/plugins.py` — adds `Depends(require_master_key)` to all endpoints
- `api/routers/exports.py` — adds `/zip` endpoint
- `api/services/api_key_service.py` — ring-buffer audit log + `_log()` calls
- `api/middleware.py` — extracted `require_master_key(request)` helper

**Created:**
- `tests/test_api_keys.py` — extended (already exists)
- `tests/test_exports.py` — extended (already exists)
- `tests/test_plugins.py` — extended (already exists)
- `tests/ui/test_static_markup.py` — extended (already exists)

**No new files.** All code lands in existing modules. The single-file SPA constraint is preserved per the Week-1 plan's deferral of structural splits.

---

## Salvage strategy

The `claude/compose-ui-integration` branch contains a working implementation of much of this work in commits `7922db0`, `2ad708d`, `c51cca6`. The branch is divergent from master (predates `a2a`, predates the consolidated `agents` work) and conflicts on too many files to rebase cleanly.

**Strategy: rewrite using the branch as a reference.** The implementation plan will cite specific files and line ranges from the branch as inspiration so the proven patterns (master-key input, one-time key reveal, plugin card grid, export row layout) are preserved without inheriting the rebase pain. The branch can be deleted once this spec ships.

**Deviations from the salvage source, called out explicitly:**

| Aspect | Salvage source | This spec |
|---|---|---|
| Location | Memory tab | New Admin dropdown |
| Master-key storage | Plain input field, re-read on demand | `sessionStorage`, lock state when absent |
| Plugins panel | Catalog cards only | Catalog + per-tool tester |
| Exports `View` | New window with `<pre>` | In-app modal with rendered markdown |
| Bulk actions | None | Multi-select + zip download + bulk delete |
| Audit log | None | In-memory ring buffer surfaced via `/api/keys/audit` |
| Plugins endpoint auth | Unguarded | Master-key required |

---

## Test strategy

Three test surfaces — all extending existing infrastructure, no new harness needed.

### `tests/ui/test_static_markup.py` (BeautifulSoup-backed)

~10 new assertions following the same coarse-invariant pattern as the 21 existing tests:

```python
def test_admin_dropdown_present(index_soup): ...
def test_admin_panel_ids_exist(index_soup): ...
def test_admin_auth_uses_session_storage(index_html_text): ...
def test_admin_auth_does_not_use_local_storage(index_html_text): ...
def test_create_key_modal_has_one_time_reveal_warning(index_html_text): ...
def test_plugins_panel_has_tool_tester(index_html_text): ...
def test_plugins_panel_has_warning_banner(index_html_text): ...
def test_exports_panel_has_zip_action(index_html_text): ...
def test_exports_view_uses_modal_not_new_window(index_html_text): ...
def test_admin_dropdown_is_keyboard_accessible(index_soup): ...  # role=menu, aria-haspopup
```

### Router unit tests

- `tests/test_api_keys.py` — add `test_scopes_requires_master`, `test_scopes_returns_known_scopes`, `test_audit_requires_master`, `test_audit_records_create_rotate_revoke`, `test_create_returns_full_key_once`.
- `tests/test_exports.py` — add `test_zip_streams_selected_files`, `test_zip_rejects_path_traversal_per_name`, `test_zip_404_when_no_matches`.
- `tests/test_plugins.py` — add `test_list_requires_master`, `test_invoke_requires_master`, update existing tests to attach the master key header.

### What's deliberately not tested

- **No Playwright e2e.** Project has the dependency but no e2e infrastructure today. Adding it is its own setup task — would inflate this spec's scope.
- **No load test on the audit ring buffer.** `deque(maxlen=200)` is stdlib and trivial; behavioral correctness is covered by the create/rotate/revoke tests.
- **No CSS regression test.** The UI is loopback-only and the visual aesthetic has no automated coverage today; manual smoke is sufficient.

---

## Security considerations

- **Master key never persisted across tab close.** `sessionStorage` only.
- **Master key never logged.** No `console.log`, no telemetry, no inclusion in error messages.
- **One-time key reveal enforced UI-side and never sent back to the server.** Created keys are returned by the backend in the response body for the `POST /api/keys` request only; the modal stores the value in a local variable that is overwritten when the modal closes.
- **Plugins endpoints fully gated.** Even read endpoints require the master key. This is a behavior change from current master and will be noted in the changelog.
- **Path traversal blocked at the boundary** in `/api/exports/zip` (per-name `_safe_filename`).
- **Audit log retention is intentionally short** (200 events, in-memory). Persistent storage of admin actions belongs in an enterprise observability spec.
- **Plugins tool tester displays a non-dismissable warning** before any invocation: tools execute in-process with full filesystem and environment access.

---

## Out of scope (explicitly named)

| Item | Reason | Where it belongs |
|---|---|---|
| Agents tab UI | First-class product surface; deserves its own brainstorm | New spec |
| A2A tab UI | Same | New spec |
| Drawflow no-code workflow composer | Stranded on `claude/magical-payne`; needs rescue-or-abandon decision | New spec |
| Persistent audit log | Enterprise-grade work | `ENTERPRISE_DEPLOYMENT_GAPS.md` follow-up |
| Per-key rate limit enforcement | Schema field exists, enforcement does not | Listed in `ENTERPRISE_DEPLOYMENT_GAPS.md` |
| Plugin enable/disable lifecycle | Currently filesystem-managed; UI toggle requires new backend | Future plugins spec |
| Splitting `index.html` into modules | Constraint preserved by Week-1 plan | Month-1 UI plan |
| MCP transport adapter | Has design doc at `docs/plans/2026-04-27-mcp-transport-adapter-design.md` | That plan |

---

## Definition of done

- All three admin panels render and function under the Admin dropdown.
- Master-key sign-in flow works: lock state → modal → key entry → `sessionStorage` → panel loads. 401 clears the key and re-locks.
- Sign-out pill appears when authenticated; clicking it clears the key and dismisses panels.
- API Keys panel: list, create with one-time reveal, rotate, revoke, audit log strip — all functional.
- Plugins panel: catalog cards, plugin detail, per-tool tester with schema-driven form, JSON-pretty result, last-5 invocation history.
- Exports panel: list, view (modal markdown), download single, download zip (multi-select), delete single, bulk delete.
- All four backend additions implemented with tests passing.
- All `tests/ui/test_static_markup.py` assertions pass.
- All router tests pass.
- `compose-ui-integration` branch can be deleted with no data lost.

---

## Decisions log (from brainstorming)

| # | Question | Choice | Rationale |
|---|---|---|---|
| 1 | Spec scope | B — workflow v2 + orphaned routers | Workflow v2 turned out to be done; reduced to orphaned routers |
| 2 | Workflow surfacing depth | B — status + collapsible detail | Moot after audit; already shipped |
| 3 | Navigation layout | B — Admin dropdown | Preserves aesthetic, separates state-changing admin from operational work |
| 4 | Admin auth flow | A — `sessionStorage` with explicit Sign-in | Default-deny posture, no key in chat, no persistence across tab close |
| 5 | Plugins UI scope | B — catalog + tool tester | Tester is the primary debug path for plugin tools |
| 6 | Branch rescue | Rewrite using as reference | Branch is divergent past clean rebase distance |

---

## Appendix: routes audited

Verified the following routers exist in master and assessed UI coverage:

| Router | Lines | UI coverage on master | Action |
|---|---|---|---|
| `chat` | 284 | ✓ Dashboard chat panel | none |
| `completions` | 103 | (API-only, by design) | none |
| `models` | 37 | ✓ Dashboard system status | none |
| `inventory` | 581 | ✓ Models tab | none |
| `memory` | 107 | ✓ Memory tab | none |
| `documents` | 103 | ✓ Documents tab | none |
| `setup` | 104 | ✓ `/setup` wizard | none |
| `workflows` | 302 | ✓ Workflows tab | none |
| `roles` | 80 | ✓ Workflows tab subsection | none |
| `graph` | 162 | ✓ Research tab | none |
| `profiles` | 46 | ✓ Memory tab subsection | none |
| `context` | 51 | (debug-only, no UI by design) | none |
| `agents` | 192 | ✗ | Out of scope (separate spec) |
| `a2a` | 314 | ✗ | Out of scope (separate spec) |
| **`api_keys`** | **75** | **✗** | **In scope** |
| **`plugins`** | **43** | **✗** | **In scope** |
| **`exports`** | **107** | **✗** | **In scope** |

Three of eighteen routers are this spec's target. Five are out of scope by design. The remaining ten are already covered.
