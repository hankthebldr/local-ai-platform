# Workflow Observability UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the already-shipped v2 workflow engine (hooks, role library, retry, escalation) legible to users in the web UI. No engine changes — only surface what's already present in `AgentStep.hooks`, `StepPrompt.role_ref`, and `StepResult.retries`/`model_used`.

**Architecture:** One new read-only router (`/api/roles`) serving `prompts/roles/*.md` content. All other data already comes back from `/api/workflows/{id}` (full workflow definition with hooks + role_ref) and `/api/workflows/runs/{id}` (step results with retry counts + final model). UI changes concentrated in `api/static/index.html` under the existing Workflows tab; add a new "Roles" subsection and extend `renderPipeline()` + `renderResults()` functions.

**Tech Stack:** FastAPI router, Pydantic response model, vanilla ES6 JS, CSS custom properties, pytest + httpx for router tests, pytest + BeautifulSoup for markup regression tests.

**Out of scope:** Live hook-execution tracing (requires engine instrumentation — separate plan). Workflow authoring/editing (covered by cherry-picking Drawflow composer from `claude/magical-payne` — separate PR). Plugins/API-keys/Context UIs (separate "Settings & Permissions" PR).

---

## File Structure

**New:**
- `api/routers/roles.py` — list roles and fetch role content
- `tests/test_roles_router.py` — unit tests for the new router
- `tests/ui/test_workflow_observability.py` — markup regression tests

**Modified:**
- `api/main.py` — register the roles router
- `api/static/index.html` — add Roles subsection + extend pipeline + extend results rendering

**Unchanged:** engine, hooks, prompt composer, step executor — nothing needs to change.

---

## Prerequisites

```bash
cd /Users/henry/Github/Github_desktop/local-ai-platform/.claude/worktrees/workflow-observability
/Users/henry/Github/Github_desktop/local-ai-platform/venv/bin/python -m pytest tests/ui/ -q
```

Expected baseline: `14 passed` (the Week-1 tests from PR #13 are already on master).

---

## Task 1: `/api/roles` router + tests

**Files:**
- Create: `api/routers/roles.py`
- Create: `tests/test_roles_router.py`
- Modify: `api/main.py` (register router)

- [ ] **Step 1: Write failing test**

`tests/test_roles_router.py`:

```python
"""Tests for the read-only /api/roles router."""
from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)
ROLES_DIR = Path(__file__).resolve().parents[1] / "prompts" / "roles"


def test_list_roles_returns_all_md_files():
    resp = client.get("/api/roles")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    ids = {r["id"] for r in data}
    # Three roles ship with the repo as of 2026-04-23.
    assert {"python_developer", "qa_engineer", "senior_data_architect"}.issubset(ids)
    for r in data:
        assert "id" in r and "name" in r and "summary" in r
        assert r["id"].replace("_", " ").title() or r["name"]  # non-empty


def test_get_role_returns_full_content():
    resp = client.get("/api/roles/senior_data_architect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "senior_data_architect"
    assert "senior data architect" in data["content"].lower()


def test_get_missing_role_returns_404():
    resp = client.get("/api/roles/does_not_exist")
    assert resp.status_code == 404


def test_path_traversal_rejected():
    # Must not escape prompts/roles/
    resp = client.get("/api/roles/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code in (400, 404)
    resp = client.get("/api/roles/../../etc/passwd")
    assert resp.status_code in (400, 404)
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest tests/test_roles_router.py -v
```

Expected: 4 failures ("404 Not Found" or "No module" for the router).

- [ ] **Step 3: Implement `api/routers/roles.py`**

```python
"""Read-only router exposing the role library at prompts/roles/.

Each role is a Markdown file whose filename (minus extension) is the ID
and whose first line is the name/summary. Path traversal is rejected.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/roles", tags=["roles"])

ROLES_DIR = (Path(__file__).resolve().parents[2] / "prompts" / "roles").resolve()


class RoleSummary(BaseModel):
    id: str
    name: str
    summary: str
    path: str


class Role(RoleSummary):
    content: str


def _id_to_path(role_id: str) -> Path:
    # Reject anything that isn't a plain identifier — blocks ../, /, \.
    if not role_id or not all(c.isalnum() or c in "_-" for c in role_id):
        raise HTTPException(status_code=400, detail="invalid role id")
    candidate = (ROLES_DIR / f"{role_id}.md").resolve()
    # Belt-and-suspenders: ensure the resolved path is inside ROLES_DIR.
    try:
        candidate.relative_to(ROLES_DIR)
    except ValueError:
        raise HTTPException(status_code=400, detail="path outside role library")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"role '{role_id}' not found")
    return candidate


def _summarize(text: str) -> str:
    # Use the first non-empty line as a 1-sentence summary.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            # Cap at ~140 chars to keep list view tidy.
            return stripped[:140]
    return ""


@router.get("", response_model=List[RoleSummary])
async def list_roles() -> List[RoleSummary]:
    if not ROLES_DIR.exists():
        return []
    out: List[RoleSummary] = []
    for p in sorted(ROLES_DIR.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        out.append(
            RoleSummary(
                id=p.stem,
                name=p.stem.replace("_", " ").title(),
                summary=_summarize(text),
                path=str(p.relative_to(ROLES_DIR.parent.parent)),
            )
        )
    return out


@router.get("/{role_id}", response_model=Role)
async def get_role(role_id: str) -> Role:
    path = _id_to_path(role_id)
    text = path.read_text(encoding="utf-8")
    return Role(
        id=path.stem,
        name=path.stem.replace("_", " ").title(),
        summary=_summarize(text),
        path=str(path.relative_to(ROLES_DIR.parent.parent)),
        content=text,
    )
```

- [ ] **Step 4: Register the router in `api/main.py`**

Grep for existing `app.include_router` calls and add `roles` in the same pattern.

```python
from api.routers import roles  # alongside existing router imports
# ...
app.include_router(roles.router)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_roles_router.py -v
```

Expected: 4 pass.

- [ ] **Step 6: Commit**

```bash
git add api/routers/roles.py tests/test_roles_router.py api/main.py
git commit -m "feat(roles): add read-only /api/roles router for the role library

Surfaces prompts/roles/*.md so the UI can browse and preview roles
referenced by v2 workflow steps' role_ref field. Path traversal is
rejected both by character allowlist and resolved-path containment.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Role-library UI under Workflows tab

**Files:**
- Modify: `api/static/index.html` — add Roles subsection above Recent Runs
- Modify: `tests/ui/test_static_markup.py` — markup regression

- [ ] **Step 1: Write failing test**

Append to `tests/ui/test_static_markup.py`:

```python
def test_workflows_tab_has_roles_subsection(index_html_text):
    """Workflows tab must expose a Roles subsection so role_ref is browseable."""
    # Look for the subsection panel label.
    assert 'id="wf-roles-list"' in index_html_text, (
        "roles list container missing from Workflows tab"
    )
    assert "/api/roles" in index_html_text, (
        "frontend does not call /api/roles"
    )
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest tests/ui/test_static_markup.py::test_workflows_tab_has_roles_subsection -v
```

Expected: FAIL.

- [ ] **Step 3: Add the Roles panel**

Inside `#tab-workflows`, before the Recent Runs panel (around line 1516), insert:

```html
<!-- Role Library (v2 prompt framework) -->
<div class="panel" style="margin-bottom:16px">
  <span class="corner-tr"></span><span class="corner-bl"></span>
  <div class="panel-label">// ROLE LIBRARY
    <span style="float:right;font-size:0.6rem;color:var(--text-muted);letter-spacing:0.1em">prompts/roles/</span>
  </div>
  <div id="wf-roles-list" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px;margin-top:10px"></div>
  <div id="wf-role-preview" style="display:none;margin-top:14px;padding:12px;background:var(--bg-deep);border-left:2px solid var(--accent-dim);font-family:var(--mono);font-size:0.72rem;line-height:1.6;white-space:pre-wrap;color:var(--text-dim)"></div>
</div>
```

- [ ] **Step 4: Wire the JS**

In the workflows section of the script (near `refreshWorkflows`), add:

```javascript
async function loadRoles() {
  const container = document.getElementById('wf-roles-list');
  if (!container) return;
  try {
    const resp = await fetch('/api/roles');
    const roles = await resp.json();
    if (!Array.isArray(roles) || roles.length === 0) {
      container.innerHTML = '<div class="model-empty">No roles defined in prompts/roles/</div>';
      return;
    }
    container.innerHTML = roles.map(r => `
      <div class="wf-role-card" onclick="previewRole('${esc(r.id)}')">
        <div class="wf-role-name">${esc(r.name)}</div>
        <div class="wf-role-summary">${esc(r.summary)}</div>
        <div class="wf-role-id">${esc(r.id)}</div>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<div class="model-empty">Failed to load roles: ${esc(e.message)}</div>`;
  }
}

async function previewRole(id) {
  const box = document.getElementById('wf-role-preview');
  if (!box) return;
  try {
    const resp = await fetch(`/api/roles/${encodeURIComponent(id)}`);
    if (!resp.ok) { box.style.display = 'none'; return; }
    const r = await resp.json();
    box.textContent = r.content;
    box.style.display = 'block';
    box.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  } catch (e) {
    box.textContent = 'Preview failed: ' + e.message;
    box.style.display = 'block';
  }
}
```

Also call `loadRoles()` when the Workflows tab activates — find the block in `switchTab` that already dispatches on `name === 'workflows'` (search `'workflows'` in the script region) and add `loadRoles();`.

- [ ] **Step 5: Add CSS for `.wf-role-card`**

Near the other `.wf-*` rules (around `:973-1090`):

```css
.wf-role-card {
  border: 1px solid var(--border);
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.wf-role-card:hover { border-color: var(--accent-dim); background: #00CC6608; }
.wf-role-name { color: var(--text); font-weight: 500; font-size: 0.78rem; }
.wf-role-summary {
  color: var(--text-dim); font-size: 0.68rem; margin-top: 4px;
  overflow: hidden; text-overflow: ellipsis; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.wf-role-id {
  color: var(--text-muted); font-size: 0.6rem; margin-top: 6px;
  letter-spacing: 0.12em; text-transform: uppercase;
}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/ui/test_static_markup.py -v
```

- [ ] **Step 7: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "feat(ui): role library browser under Workflows tab

Lists prompts/roles/*.md as cards; clicking previews the full role
markdown. Closes the P0 'v2 role_ref points at files no one can
browse' gap from the 2026-04-23 UI audit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Hook trace in pipeline view

**Files:**
- Modify: `api/static/index.html` — extend pipeline renderer
- Modify: `tests/ui/test_static_markup.py`

Inspect `loadWorkflowDetail` to see how `#wf-pipeline` is built. For each step, now also render a disclosure of the 5 hook slots pulled from `step.hooks`. When `prompt.role_ref` is set, render it as a clickable chip that calls `previewRole(id)`.

- [ ] **Step 1: Write failing test**

```python
def test_pipeline_renderer_references_hooks(index_html_text):
    """Pipeline renderer must look at step.hooks to render the hook chain."""
    # Loose check — confirm the renderer function reads step.hooks.
    assert "step.hooks" in index_html_text or 'step["hooks"]' in index_html_text, (
        "pipeline renderer does not reference step.hooks — hooks will not render"
    )
    # And references role_ref so it can render the role chip
    assert "role_ref" in index_html_text, (
        "pipeline renderer does not reference prompt.role_ref"
    )
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest tests/ui/test_static_markup.py::test_pipeline_renderer_references_hooks -v
```

Expected: FAIL.

- [ ] **Step 3: Locate the existing pipeline renderer**

```bash
grep -n "wf-pipeline\|wf-step" api/static/index.html | head -20
```

Find the block that maps `workflow.steps` to `.wf-step` HTML. Extend each step's HTML to include a `.wf-step-meta` disclosure containing:
- Role chip (`role_ref` if present — clickable to previewRole)
- Hook pills grouped by slot (`before_step`, `transform_prompt`, `validate_output`, `after_step`, `on_failure`)

- [ ] **Step 4: Implement the extension**

Inside the step-map function, replace the step HTML with:

```javascript
const hooks = step.hooks || {};
const hookPills = ['before_step', 'transform_prompt', 'validate_output', 'after_step', 'on_failure']
  .map(slot => {
    const entries = hooks[slot] || [];
    if (entries.length === 0) return '';
    return `<div class="wf-hook-slot"><span class="wf-hook-slot-label">${slot.replace('_',' ')}</span>${
      entries.map(h => `<span class="wf-hook-pill" title="${esc(JSON.stringify(h.config || {}))}">${esc(h.name)}</span>`).join('')
    }</div>`;
  }).filter(Boolean).join('');
const roleRef = step.prompt && step.prompt.role_ref;
const roleChip = roleRef
  ? `<span class="wf-role-chip" onclick="previewRole('${esc(roleRef)}')">role: ${esc(roleRef)}</span>`
  : (step.role ? `<span class="wf-role-chip inline">role: ${esc(step.role)}</span>` : '');
// …insert roleChip + (hookPills ? `<div class="wf-step-hooks">${hookPills}</div>` : '') into the step's box
```

(Exact integration depends on the current renderer; leave the existing pipeline arrows and status classes alone.)

- [ ] **Step 5: Add CSS**

```css
.wf-step-hooks { display: flex; flex-direction: column; gap: 4px; margin-top: 8px; }
.wf-hook-slot { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.wf-hook-slot-label {
  font-size: 0.55rem; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--text-muted); min-width: 110px;
}
.wf-hook-pill {
  font-size: 0.62rem; padding: 2px 8px; border: 1px solid var(--accent-dim);
  color: var(--accent); background: var(--accent-ghost);
  border-radius: 999px; cursor: help;
}
.wf-role-chip {
  display: inline-block; font-size: 0.62rem; padding: 2px 8px;
  border: 1px solid var(--accent-2-dim); color: var(--accent-2);
  border-radius: 999px; cursor: pointer; margin-top: 6px;
}
.wf-role-chip:hover { border-color: var(--accent-2); background: rgba(25,170,97,0.08); }
.wf-role-chip.inline { cursor: default; }
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/ui/test_static_markup.py::test_pipeline_renderer_references_hooks -v
```

- [ ] **Step 7: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "feat(ui): hook & role chips on workflow pipeline

For each step, renders the declared hook chain (5 slots: before_step,
transform_prompt, validate_output, after_step, on_failure) as pills
grouped by slot, and a clickable role chip that previews the role's
full markdown. Makes the v2 workflow engine's hook+role wiring
visible without changing the engine.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Attempts / retries / escalation in run results

**Files:**
- Modify: `api/static/index.html` — extend `renderResults` (or equivalent)
- Modify: `tests/ui/test_static_markup.py`

The `StepResult` already has `retries`, `model_used`, `duration_seconds`, `token_count`, and `error`. Currently results show only final status. Add a line "Attempt N · model · duration · tokens" per step, and if `retries > 0`, show a collapsible "Escalation trail" detail summarizing the retry.

- [ ] **Step 1: Write failing test**

```python
def test_results_renderer_shows_retries_and_model(index_html_text):
    """Results renderer must surface retries count and model_used."""
    assert "retries" in index_html_text, (
        "results renderer does not reference StepResult.retries"
    )
    assert "model_used" in index_html_text, (
        "results renderer does not reference StepResult.model_used"
    )
```

- [ ] **Step 2: Run test to verify failure**

Expected: FAIL — model_used absent.

- [ ] **Step 3: Locate the results renderer**

```bash
grep -n "wf-results-content\|renderResults\|step_results" api/static/index.html | head
```

Find the function that maps `run.step_results` and extend its template:

```javascript
const attemptCount = (sr.retries || 0) + 1;
const attemptBadge = attemptCount > 1
  ? `<span class="wf-attempt-badge">${attemptCount} attempts</span>`
  : '';
const escalationRow = (sr.retries || 0) > 0
  ? `<div class="wf-escalation">
       ↳ final attempt on <strong>${esc(sr.model_used || '—')}</strong>
       after ${sr.retries} retry${sr.retries === 1 ? '' : 'ies'}
     </div>`
  : '';
// …insert into the existing row HTML
```

- [ ] **Step 4: Add CSS**

```css
.wf-attempt-badge {
  font-size: 0.6rem; padding: 2px 8px; border-radius: 999px;
  border: 1px solid var(--warn-dim); color: var(--warn);
  margin-left: 8px;
}
.wf-escalation {
  font-size: 0.66rem; color: var(--text-dim);
  margin-top: 4px; padding-left: 12px; border-left: 2px solid var(--warn-dim);
}
.wf-escalation strong { color: var(--text); }
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/ui/ -v
```

- [ ] **Step 6: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "feat(ui): surface attempt count + escalation trail in run results

StepResult already carries retries and model_used; render them so users
can distinguish a clean first-pass from a 3rd-attempt escalation with
a model swap. Closes P0 gap from 2026-04-23 UI audit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Verification

After all four tasks:

```bash
pytest tests/ui/ tests/test_roles_router.py -v
```

Expected: all pass. Then live smoke-test:

```bash
API_PORT=8003 /Users/henry/Github/Github_desktop/local-ai-platform/venv/bin/python -m api.main &
sleep 3
curl -s http://localhost:8003/api/roles | python3 -m json.tool
# Open http://localhost:8003/ → Workflows tab → role cards render → click one → content shows
kill %1
```

Open PR, tagline: "Workflow observability UI — makes shipped hook/role/retry work legibly real."
