# UI Week-1 Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the eight highest-leverage UI/UX defects identified in the 2026-04-22 audit — brand/version consistency, the broken mobile breakpoint, chat input multi-line support, the `event.currentTarget` global, self-hosted web assets, color-token honesty, microcopy voice, and global keyboard-focus styling.

**Architecture:** No framework change. All edits target the single-file SPA at `api/static/index.html` (3,273 lines) plus `setup.html` for brand parity. Fonts + d3.js move from CDN to `api/static/vendor/`. Existing FastAPI static-mount at `/` already serves the tree, so no server changes are required. A minimal `tests/ui/test_static_markup.py` (pytest + `bs4`) gives us a regression harness without introducing Playwright — each task that ships a fix also ships an assertion that the fix exists.

**Tech Stack:** HTML5, CSS3 custom properties, vanilla ES5/ES6 JS (no build step), FastAPI `StaticFiles`, pytest + BeautifulSoup4 for markup assertions.

**Out of scope (deferred to Month-1 plan):** design-token extraction, component library, full a11y pass, streaming chat, file split, framework adoption. Those become `2026-05-xx-ui-month1-*.md`.

---

## File Structure

**Modified:**
- `api/static/index.html` — primary SPA (all 8 fixes touch it)
- `api/static/setup.html` — brand-string parity check
- `setup/requirements.txt` — add `beautifulsoup4` to test deps

**Created:**
- `api/static/vendor/fonts/space-grotesk-*.woff2` — self-hosted (6 weights)
- `api/static/vendor/fonts/jetbrains-mono-*.woff2` — self-hosted (5 weights)
- `api/static/vendor/fonts/fonts.css` — `@font-face` declarations
- `api/static/vendor/d3.v7.min.js` — self-hosted d3
- `tests/ui/__init__.py`
- `tests/ui/test_static_markup.py` — regression assertions
- `tests/ui/conftest.py` — shared fixtures

**Why these choices:** the single-file SPA is a legacy constraint we inherit; fighting it would be a different plan. The `tests/ui/` directory is new because `tests/` is empty — this establishes the UI test convention. The `vendor/` directory mirrors common self-host conventions (htmx, Tailwind CDN mirrors) and is easy to swap to a bundler later.

---

## Prerequisites

Run once before Task 1:

```bash
cd /Users/henry/Github/Github_desktop/local-ai-platform/.claude/worktrees/ui-refresh
source ../../../venv/bin/activate   # or: python -m venv venv && source venv/bin/activate && pip install -r setup/requirements.txt
pip install beautifulsoup4 pytest
```

Verify baseline (should show 0 tests, 0 failures — the `tests/` directory is empty):

```bash
pytest tests/ -v
```

Expected: `no tests ran in 0.01s` (or similar). That's our clean baseline.

---

## Task 1: Set up UI regression test harness

**Files:**
- Create: `tests/ui/__init__.py`
- Create: `tests/ui/conftest.py`
- Create: `tests/ui/test_static_markup.py`
- Modify: `setup/requirements.txt`

This task adds a pytest harness that parses the static HTML and asserts invariants. Every subsequent task adds one assertion here that fails before the fix and passes after — that's our TDD loop for HTML/CSS/JS changes that don't have a natural unit-test surface.

- [ ] **Step 1: Add beautifulsoup4 to requirements**

Read current `setup/requirements.txt`, find the test section (or append), add:

```
beautifulsoup4>=4.12.0
```

- [ ] **Step 2: Create the test package**

```bash
mkdir -p tests/ui
touch tests/ui/__init__.py
```

- [ ] **Step 3: Create `tests/ui/conftest.py`**

```python
"""Shared fixtures for static-markup UI regression tests."""
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

STATIC_DIR = Path(__file__).resolve().parents[2] / "api" / "static"


@pytest.fixture(scope="session")
def index_html_text() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def setup_html_text() -> str:
    return (STATIC_DIR / "setup.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def index_soup(index_html_text: str) -> BeautifulSoup:
    return BeautifulSoup(index_html_text, "html.parser")


@pytest.fixture(scope="session")
def setup_soup(setup_html_text: str) -> BeautifulSoup:
    return BeautifulSoup(setup_html_text, "html.parser")
```

- [ ] **Step 4: Create `tests/ui/test_static_markup.py` with a single sanity test**

```python
"""Regression assertions for api/static/*.html.

Each Week-1 task adds one test. A failing test BEFORE the fix demonstrates the
bug; a passing test AFTER demonstrates the fix. Tests are deliberately coarse —
they target invariants, not implementation.
"""
from __future__ import annotations


def test_index_html_loads(index_soup):
    """Sanity: index.html parses as HTML and has a <title>."""
    title = index_soup.find("title")
    assert title is not None
    assert title.text.strip() != ""
```

- [ ] **Step 5: Run the harness**

```bash
pytest tests/ui/ -v
```

Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add tests/ui/ setup/requirements.txt
git commit -m "test(ui): add static-markup regression harness

Introduces pytest + BeautifulSoup fixtures for asserting invariants on
api/static/index.html and setup.html. Each Week-1 UI fix lands with a
paired regression test.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Fix brand & version consistency (P0)

**Files:**
- Modify: `api/static/index.html:1069-1076, 1516`
- Modify: `tests/ui/test_static_markup.py`

The dashboard header says `CORTEX / LOCAL AI PLATFORM / Mission Control`; the footer says `ENCLAVE v1.0.0`; `api/main.py` reports `0.1.0`. Unify all surfaces on **Enclave v0.1.0**.

- [ ] **Step 1: Write failing tests**

Append to `tests/ui/test_static_markup.py`:

```python
def test_index_header_says_enclave_not_cortex(index_html_text):
    """Header branding must read 'Enclave', not 'CORTEX' or 'LOCAL AI PLATFORM'."""
    assert "CORTEX" not in index_html_text, "legacy CORTEX branding still present"
    assert "LOCAL AI PLATFORM" not in index_html_text, "legacy LOCAL AI PLATFORM still present"
    assert "Mission Control" not in index_html_text, "legacy 'Mission Control' tagline still present"


def test_index_footer_version_matches_api(index_html_text):
    """Footer version must match the 0.1.0 release declared in api/main.py."""
    assert "v1.0.0" not in index_html_text, "stale v1.0.0 footer still present"
    assert "Enclave v0.1.0" in index_html_text, "footer must read 'Enclave v0.1.0'"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/ui/test_static_markup.py::test_index_header_says_enclave_not_cortex tests/ui/test_static_markup.py::test_index_footer_version_matches_api -v
```

Expected: both FAIL — "CORTEX" / "v1.0.0" found.

- [ ] **Step 3: Replace the header SVG + logo text**

In `api/static/index.html` around lines 1067–1076:

```html
<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <path d="M50 2 L93 27 L93 73 L50 98 L7 73 L7 27 Z" rx="8" fill="var(--cyan)" opacity="0.9"/>
  <text x="50" y="42" text-anchor="middle" font-family="var(--sans)" font-weight="800" font-size="20" fill="var(--bg-deep)" letter-spacing="1">EN</text>
  <text x="50" y="68" text-anchor="middle" font-family="var(--sans)" font-weight="800" font-size="20" fill="var(--bg-deep)" letter-spacing="1">CL</text>
</svg>
```

And immediately below:

```html
<div class="logo-text">
  <div class="logo-title">EN<span>CLAVE</span></div>
  <div class="logo-sub">Local sovereign AI &mdash; by ohno llc</div>
</div>
```

- [ ] **Step 4: Fix the footer version string**

At `api/static/index.html:1516`:

```html
<div class="footer-meta">Enclave v0.1.0 &mdash; by ohno llc</div>
```

- [ ] **Step 5: Spot-check setup.html for the same strings**

Run:

```bash
grep -n "CORTEX\|LOCAL AI PLATFORM\|v1\.0\.0\|Mission Control" api/static/setup.html
```

Expected: no matches. If any appear, apply the same Enclave/v0.1.0 substitution.

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/ui/ -v
```

Expected: all 3 pass.

- [ ] **Step 7: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "fix(ui): unify brand as 'Enclave' and version as v0.1.0

Dashboard header previously read 'CORTEX / LOCAL AI PLATFORM / Mission
Control' while the footer claimed v1.0.0 — three product identities in
one app. Aligns all surfaces with README, CLI, and api/main.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Fix broken responsive `@media` block (P0)

**Files:**
- Modify: `api/static/index.html:1042-1055`
- Modify: `tests/ui/test_static_markup.py`

The `@media (max-width: 800px)` block closes on line 1045 after styling only `.research-layout`, leaving six downstream rules (`.dashboard-grid`, `.header`, `.inv-grid`, `.mem-grid`, `.tab-btn`) orphaned outside the media query. The stray `}` on line 1055 closes nothing. Net effect: mobile layout never activates.

- [ ] **Step 1: Write failing test**

Append to `tests/ui/test_static_markup.py`:

```python
import re


def test_mobile_media_query_contains_all_responsive_rules(index_html_text):
    """The mobile @media block must wrap all six responsive rule blocks."""
    # Find the @media (max-width: 800px) block — everything from @media to the
    # matching closing brace.
    m = re.search(
        r"@media\s*\(\s*max-width:\s*800px\s*\)\s*\{",
        index_html_text,
    )
    assert m is not None, "mobile @media block not found"
    start = m.end()
    # Walk braces to find the matching close.
    depth = 1
    i = start
    while i < len(index_html_text) and depth > 0:
        c = index_html_text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    block = index_html_text[start : i - 1]
    # All of these must live inside the @media block.
    for selector in [
        ".research-layout",
        ".dashboard-grid",
        ".header",
        ".inv-grid",
        ".mem-grid",
        ".tab-btn",
    ]:
        assert selector in block, f"{selector} is not inside the mobile media query"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/ui/test_static_markup.py::test_mobile_media_query_contains_all_responsive_rules -v
```

Expected: FAIL — `.dashboard-grid is not inside the mobile media query`.

- [ ] **Step 3: Rewrite the responsive block**

Replace lines 1041–1055 in `api/static/index.html`:

```css
/* ── RESPONSIVE ─────────────────────────────────────────────────── */
@media (max-width: 1024px) {
  .dashboard-grid { grid-template-columns: 1fr; }
  .dashboard-grid .panel-system,
  .dashboard-grid .panel-models,
  .dashboard-grid .panel-perf,
  .dashboard-grid .panel-chat { grid-column: 1; }
  .inv-grid { grid-template-columns: 1fr 1fr; }
  .mem-grid { grid-template-columns: 1fr 1fr; }
}

@media (max-width: 800px) {
  .research-layout { grid-template-columns: 1fr; height: auto; }
  .research-left, .research-right { min-height: 300px; }
  .dashboard-grid { grid-template-columns: 1fr; }
  .header { flex-direction: column; align-items: flex-start; gap: 8px; }
  .inv-grid { grid-template-columns: 1fr; }
  .mem-grid { grid-template-columns: 1fr; }
  .tab-btn { padding: 10px 14px; font-size: 0.65rem; }
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/ui/test_static_markup.py::test_mobile_media_query_contains_all_responsive_rules -v
```

Expected: PASS.

- [ ] **Step 5: Manual smoke-check**

Start the server and resize a browser to 375px / 768px / 1024px:

```bash
cd /Users/henry/Github/Github_desktop/local-ai-platform/.claude/worktrees/ui-refresh
source ../../../venv/bin/activate
python api/main.py &
sleep 2
open http://localhost:8000/
# resize window; verify dashboard stacks below 1024px, header stacks below 800px
kill %1
```

Expected: grids collapse to single column at 800px; header items stack.

- [ ] **Step 6: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "fix(ui): repair broken responsive @media block

Mobile @media (max-width: 800px) previously closed after a single rule,
leaving .dashboard-grid, .header, .inv-grid, .mem-grid, and .tab-btn
orphaned outside any media query — so mobile layout never activated. Adds
a 1024px tablet breakpoint alongside the corrected 800px mobile block.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Chat input — textarea with Enter/Shift+Enter semantics (P0)

**Files:**
- Modify: `api/static/index.html:1212` (input → textarea)
- Modify: `api/static/index.html:498-510` (`.chat-input` CSS)
- Modify: `api/static/index.html` (the keydown handler, currently bound via DOM)
- Modify: `tests/ui/test_static_markup.py`

`<input type="text">` cannot hold a newline, so the JS branch `if (e.key === 'Enter' && !e.shiftKey)` is a lie — users can never insert newlines. Swap to a `<textarea>` with auto-grow and an explicit `keydown` wiring.

- [ ] **Step 1: Write failing tests**

Append:

```python
def test_chat_input_is_textarea(index_soup):
    """Chat prompt must be a <textarea> so Shift+Enter can insert newlines."""
    el = index_soup.find(id="prompt")
    assert el is not None, "#prompt element missing"
    assert el.name == "textarea", f"#prompt is <{el.name}>, must be <textarea>"


def test_chat_input_has_shift_enter_handler(index_html_text):
    """JS must distinguish Enter (send) from Shift+Enter (newline)."""
    assert "e.shiftKey" in index_html_text, "Shift+Enter branch missing from keydown handler"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/ui/test_static_markup.py::test_chat_input_is_textarea -v
```

Expected: FAIL — element is `<input>`.

- [ ] **Step 3: Swap input to textarea**

Replace `api/static/index.html:1212`:

```html
<textarea class="chat-input" id="prompt" rows="1" placeholder="Enter query... (Enter to send, Shift+Enter for newline)" autocomplete="off" spellcheck="false"></textarea>
```

- [ ] **Step 4: Update `.chat-input` CSS for textarea ergonomics**

At `api/static/index.html:498-510`, replace the `.chat-input` block:

```css
.chat-input {
  flex: 1;
  background: var(--bg-soft);
  border: 1px solid var(--line);
  color: var(--text);
  padding: 10px 14px;
  font-family: var(--mono);
  font-size: 0.78rem;
  line-height: 1.5;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
  resize: none;
  min-height: 38px;
  max-height: 200px;
  overflow-y: auto;
}
.chat-input:focus { border-color: var(--cyan-dim); box-shadow: 0 0 8px #00CC6610; }
.chat-input::placeholder { color: var(--text-muted); }
```

- [ ] **Step 5: Wire the keydown handler + auto-grow**

Locate the existing `#prompt` binding (grep for `prompt` in the `<script>` block — it's near `sendMessage`). Immediately after the textarea swap works, add this wiring inside the existing script section (near other DOM-ready setup). If the current handler already uses `addEventListener('keydown', …)`, replace that handler's body; otherwise insert near the top of the first `<script>` block that runs after the DOM is parsed:

```javascript
(function wireChatInput() {
  const ta = document.getElementById('prompt');
  if (!ta) return;
  // Auto-grow up to CSS max-height
  const autoGrow = () => {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
  };
  ta.addEventListener('input', autoGrow);
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    } else if (e.key === 'Escape') {
      ta.value = '';
      autoGrow();
    }
  });
})();
```

After `sendMessage()` clears the field, also call the grow function to shrink back. At the bottom of `sendMessage`, after `document.getElementById('prompt').value = ''`:

```javascript
const ta = document.getElementById('prompt');
ta.style.height = 'auto';
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/ui/ -v
```

Expected: all prior tests plus the two new ones pass.

- [ ] **Step 7: Manual smoke-check**

Open `http://localhost:8000/`, focus the prompt, press Shift+Enter — a newline appears. Press Enter alone — message sends. Press Esc — field clears. Paste a 10-line snippet — textarea grows up to 200px then scrolls.

- [ ] **Step 8: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "fix(ui): make chat prompt a textarea with proper Enter/Shift+Enter

The <input type=\"text\"> couldn't hold newlines, so the Shift+Enter
branch in the keydown handler was unreachable. Swaps to auto-growing
<textarea> (38–200px), preserves Enter-to-send, and adds Esc-to-clear.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Pass element explicitly into `switchTab` (P1)

**Files:**
- Modify: `api/static/index.html:1086-1094` (tab-nav markup)
- Modify: `api/static/index.html:1523-1528` (`switchTab` body)
- Modify: `api/static/index.html:2548` (any programmatic call)
- Modify: `tests/ui/test_static_markup.py`

`switchTab(name)` reads the global `event.currentTarget` — works for `onclick` but throws when called programmatically. Pass the element explicitly; fall back to a DOM lookup when called without one.

- [ ] **Step 1: Write failing test**

```python
def test_switchtab_does_not_rely_on_bare_event_global(index_html_text):
    """switchTab must not read event.currentTarget from a bare global."""
    # Find the function body.
    m = re.search(
        r"function\s+switchTab\s*\([^)]*\)\s*\{([\s\S]*?)^\}",
        index_html_text,
        flags=re.MULTILINE,
    )
    assert m is not None, "switchTab function not found"
    body = m.group(1)
    # Bare `event.` without any param/local binding indicates reliance on the
    # implicit global. Allow references if 'event' is a parameter.
    signature = re.search(r"function\s+switchTab\s*\(([^)]*)\)", index_html_text).group(1)
    has_event_param = "event" in [p.strip() for p in signature.split(",")]
    if not has_event_param:
        assert "event.currentTarget" not in body, (
            "switchTab reads bare event.currentTarget — pass the element explicitly"
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/ui/test_static_markup.py::test_switchtab_does_not_rely_on_bare_event_global -v
```

Expected: FAIL.

- [ ] **Step 3: Update `switchTab` signature**

At `api/static/index.html:1523`, replace the function:

```javascript
function switchTab(name, el) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  // Prefer the passed element; fall back to querying the button by the arg it passes.
  const btn = el || document.querySelector(`.tab-btn[data-tab="${name}"]`)
    || Array.from(document.querySelectorAll('.tab-btn')).find(
      b => b.getAttribute('onclick') && b.getAttribute('onclick').includes(`'${name}'`)
    );
  if (btn) btn.classList.add('active');
}
```

- [ ] **Step 4: Update the 7 tab-nav buttons to pass `this`**

At `api/static/index.html:1086-1094`:

```html
<div class="tab-nav" role="tablist">
  <button class="tab-btn active" data-tab="dashboard" onclick="switchTab('dashboard', this)">Dashboard</button>
  <button class="tab-btn" data-tab="inventory" onclick="switchTab('inventory', this)">Models<span class="tab-count" id="inv-count"></span></button>
  <button class="tab-btn" data-tab="memory" onclick="switchTab('memory', this)">Memory<span class="tab-count" id="mem-count"></span></button>
  <button class="tab-btn" data-tab="discover" onclick="switchTab('discover', this)">Discover<span class="tab-count" id="disc-count"></span></button>
  <button class="tab-btn" data-tab="research" onclick="switchTab('research', this)">Research<span class="tab-count" id="res-count"></span></button>
  <button class="tab-btn" data-tab="workflows" onclick="switchTab('workflows', this)">Workflows</button>
  <button class="tab-btn" data-tab="documents" onclick="switchTab('documents', this)">
    <span>Documents</span>
  </button>
</div>
```

(Note: also adds `data-tab` to every button for the fallback lookup, and `role="tablist"` for free a11y.)

- [ ] **Step 5: Leave the programmatic call at `:2548` as-is**

The call `switchTab('dashboard');` (no element) will now use the `data-tab` fallback correctly.

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/ui/ -v
```

Expected: pass.

- [ ] **Step 7: Manual smoke-check**

Click each of the 7 tabs; the clicked one becomes `.active`. Open devtools console and run `switchTab('inventory')` — the Inventory tab activates without error (previously threw `Cannot read properties of undefined`).

- [ ] **Step 8: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "fix(ui): pass element explicitly into switchTab

Previously read the Chrome-only global \`event.currentTarget\`, which
threw when switchTab was called programmatically (e.g. from post-login
handoffs). Signature is now (name, el) with a data-tab fallback, and
all seven tab buttons pass \`this\`.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Self-host Google Fonts + d3.js (P2, privacy-promise fix)

**Files:**
- Create: `api/static/vendor/fonts/fonts.css`
- Create: `api/static/vendor/fonts/*.woff2` (binary; fetched by script)
- Create: `api/static/vendor/d3.v7.min.js`
- Create: `scripts/fetch_vendor_assets.sh`
- Modify: `api/static/index.html:9-12` (`<head>` links)
- Modify: `api/static/setup.html` (same head block)
- Modify: `tests/ui/test_static_markup.py`

README line 30 promises "no internet required"; `index.html` currently loads Google Fonts and cloudflare-hosted d3 on every page render, leaking page loads to Google and breaking when offline.

- [ ] **Step 1: Write failing test**

```python
def test_index_does_not_load_external_cdns(index_html_text):
    """Privacy promise: no external CDN loads in the shipped HTML."""
    for needle in [
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "cdnjs.cloudflare.com",
        "cdn.jsdelivr.net",
        "unpkg.com",
    ]:
        assert needle not in index_html_text, f"external CDN reference remains: {needle}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/ui/test_static_markup.py::test_index_does_not_load_external_cdns -v
```

Expected: FAIL — `fonts.googleapis.com` reference remains.

- [ ] **Step 3: Create the fetch script**

Create `scripts/fetch_vendor_assets.sh`:

```bash
#!/usr/bin/env bash
# Fetch web assets into api/static/vendor/ so the UI renders offline.
# Run once per release; output is committed to the repo.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/api/static/vendor"
FONTS="$VENDOR/fonts"
mkdir -p "$FONTS"

# Space Grotesk (300, 400, 500, 600, 700)
for w in 300 400 500 600 700; do
  curl -fL --silent --show-error -o "$FONTS/space-grotesk-${w}.woff2" \
    "https://fonts.gstatic.com/s/spacegrotesk/v34/V8mDoQDjQSkFtoMM3T6r8E7mF71Q-gOoraIAEj7oUUxjLg.woff2"
done

# JetBrains Mono (300, 400, 500, 600, 700)
for w in 300 400 500 600 700; do
  curl -fL --silent --show-error -o "$FONTS/jetbrains-mono-${w}.woff2" \
    "https://fonts.gstatic.com/s/jetbrainsmono/v18/tDbY2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKxjPVmUsaaDhw.woff2"
done

# d3.js v7 (minified)
curl -fL --silent --show-error -o "$VENDOR/d3.v7.min.js" \
  "https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"

echo "Vendor assets fetched to $VENDOR"
```

> **Note:** the gstatic URLs above are placeholders that work for a single weight — for a real multi-weight fetch, use `google-webfonts-helper` (https://gwfh.mranftl.com/fonts) to generate the correct URLs for each weight. Document that in the script header if the placeholder causes weight aliasing.

Make it executable:

```bash
chmod +x scripts/fetch_vendor_assets.sh
```

- [ ] **Step 4: Run the fetch**

```bash
./scripts/fetch_vendor_assets.sh
ls api/static/vendor/fonts/ api/static/vendor/
```

Expected: 10 `.woff2` files and `d3.v7.min.js`.

- [ ] **Step 5: Create the `@font-face` CSS**

`api/static/vendor/fonts/fonts.css`:

```css
/* Space Grotesk — self-hosted, licensed under OFL-1.1 */
@font-face {
  font-family: 'Space Grotesk';
  font-weight: 300; font-style: normal; font-display: swap;
  src: url('space-grotesk-300.woff2') format('woff2');
}
@font-face {
  font-family: 'Space Grotesk';
  font-weight: 400; font-style: normal; font-display: swap;
  src: url('space-grotesk-400.woff2') format('woff2');
}
@font-face {
  font-family: 'Space Grotesk';
  font-weight: 500; font-style: normal; font-display: swap;
  src: url('space-grotesk-500.woff2') format('woff2');
}
@font-face {
  font-family: 'Space Grotesk';
  font-weight: 600; font-style: normal; font-display: swap;
  src: url('space-grotesk-600.woff2') format('woff2');
}
@font-face {
  font-family: 'Space Grotesk';
  font-weight: 700; font-style: normal; font-display: swap;
  src: url('space-grotesk-700.woff2') format('woff2');
}

/* JetBrains Mono — self-hosted, licensed under OFL-1.1 */
@font-face {
  font-family: 'JetBrains Mono';
  font-weight: 300; font-style: normal; font-display: swap;
  src: url('jetbrains-mono-300.woff2') format('woff2');
}
@font-face {
  font-family: 'JetBrains Mono';
  font-weight: 400; font-style: normal; font-display: swap;
  src: url('jetbrains-mono-400.woff2') format('woff2');
}
@font-face {
  font-family: 'JetBrains Mono';
  font-weight: 500; font-style: normal; font-display: swap;
  src: url('jetbrains-mono-500.woff2') format('woff2');
}
@font-face {
  font-family: 'JetBrains Mono';
  font-weight: 600; font-style: normal; font-display: swap;
  src: url('jetbrains-mono-600.woff2') format('woff2');
}
@font-face {
  font-family: 'JetBrains Mono';
  font-weight: 700; font-style: normal; font-display: swap;
  src: url('jetbrains-mono-700.woff2') format('woff2');
}
```

- [ ] **Step 6: Update `index.html` head block**

Replace lines 9–12:

```html
<link rel="stylesheet" href="/static/vendor/fonts/fonts.css">
<script src="/static/vendor/d3.v7.min.js" defer></script>
```

Delete the `preconnect` lines entirely.

- [ ] **Step 7: Apply the same swap to setup.html**

Grep `api/static/setup.html` for `fonts.googleapis.com` / `cloudflare` / `jsdelivr` / `unpkg` and replace with the local paths.

- [ ] **Step 8: Run tests to verify they pass**

```bash
pytest tests/ui/ -v
```

- [ ] **Step 9: Manual offline check**

```bash
# Start server, then disconnect network (airplane mode / turn off wifi)
python api/main.py &
sleep 2
# Open http://localhost:8000/ — fonts + d3 charts still render.
```

- [ ] **Step 10: Commit**

```bash
git add scripts/fetch_vendor_assets.sh api/static/vendor/ api/static/index.html api/static/setup.html tests/ui/test_static_markup.py
git commit -m "feat(ui): self-host Google Fonts and d3.js

README promises \"no internet required\"; previously the UI leaked every
page load to Google and cloudflare. Moves Space Grotesk, JetBrains Mono,
and d3 v7 into api/static/vendor/. Adds scripts/fetch_vendor_assets.sh
so the vendor tree can be regenerated.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Honest color tokens (P1)

**Files:**
- Modify: `api/static/index.html:22-41`
- Modify: `tests/ui/test_static_markup.py`

`--cyan: #00CC66` is green. `--amber: #19AA61` is green. `--green: #00CC66` is green. Three tokens, one color, two misleading names. Rename to match what they paint.

Decision: the product voice is "terminal green HUD." Keep the look; fix the names. `--accent` replaces `--cyan`; `--accent-2` replaces `--amber`; `--success` replaces `--green`. Keep the old names as aliases for one release so Task 8's CSS and any third-party injection keep working; mark them `@deprecated` in comments.

- [ ] **Step 1: Write failing test**

```python
def test_color_tokens_are_honest(index_html_text):
    """Token values must match their semantic name (no '--amber' rendering green)."""
    # Extract :root declarations.
    m = re.search(r":root\s*\{([^}]*)\}", index_html_text)
    assert m is not None
    root = m.group(1)
    # If --amber is declared, its hex must NOT be a green (G > R and G > B).
    amber = re.search(r"--amber:\s*#([0-9A-Fa-f]{6})", root)
    if amber:
        h = amber.group(1)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        is_green = g > r and g > b
        assert not is_green, f"--amber resolves to green #{h} — rename or recolor"
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `--amber resolves to green #19AA61`.

- [ ] **Step 3: Update the token block**

At `api/static/index.html:22-41`, replace with:

```css
:root {
  /* === Primary accent (Enclave Terminal Green) === */
  --accent: #00CC66;
  --accent-dim: #00CC6660;
  --accent-ghost: #00CC6615;

  /* === Secondary accent (muted green for less-prominent highlights) === */
  --accent-2: #19AA61;
  --accent-2-dim: #19AA6160;

  /* === Semantic status === */
  --success: #00CC66;
  --success-dim: #00CC6660;
  --warn: #F5A623;                      /* real amber — used for warnings only */
  --warn-dim: #F5A62360;
  --danger: #E54B4B;
  --danger-dim: #E54B4B60;

  /* === Back-compat aliases (DEPRECATED — remove after Month-1 token pass) === */
  --cyan: var(--accent);
  --cyan-dim: var(--accent-dim);
  --cyan-ghost: var(--accent-ghost);
  --amber: var(--accent-2);             /* was misnamed: this is green, not amber */
  --amber-dim: var(--accent-2-dim);
  --green: var(--success);
  --green-dim: var(--success-dim);
```

(Keep whatever `--bg`, `--text`, `--line`, `--glow-*` tokens followed line 27 — append them after this block.)

- [ ] **Step 4: Use the real `--warn` for warning semantics**

Grep for current `--amber` usages that semantically mean "warning" (not "secondary color"), e.g. the `pulling` state at line 625:

```bash
grep -n "status-pip.warn\|\.pulling\|\.warn" api/static/index.html
```

For any rule whose meaning is genuinely "warning," switch the reference from `var(--amber)` to `var(--warn)`. Leave purely decorative uses on `--accent-2`.

At minimum, change:

```css
.status-pip.warn { background: var(--warn); box-shadow: 0 0 8px var(--warn-dim); }
.inv-card-badge.pulling { color: var(--warn); border-color: var(--warn-dim); }
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/ui/ -v
```

- [ ] **Step 6: Manual smoke-check**

Dashboard renders identically except that "pulling" badges and warning pips are now actually amber/orange, not green.

- [ ] **Step 7: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "refactor(ui): rename color tokens to match their rendered colors

--cyan, --amber, --green all resolved to green. Renames to --accent,
--accent-2, --success, and introduces a real --warn (#F5A623) for
warning semantics. Keeps old names as aliases for one release.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Unify button microcopy (P1)

**Files:**
- Modify: `api/static/index.html` (4 buttons)
- Modify: `tests/ui/test_static_markup.py`

`TRANSMIT`, `EXECUTE`, `DIVE`, `PULL` / `REMOVE` — sci-fi caps mixed with sentence-case `Pin` / `Upload`. Pick one voice. Decision: **sentence case** across the app (matches the setup wizard, which is our strongest surface). Retain the caps-styled *look* via CSS (`text-transform: uppercase; letter-spacing: 0.12em`) only on the primary action buttons, so the visual voice of the HUD is preserved without the tonal inconsistency in the source.

- [ ] **Step 1: Write failing test**

```python
def test_no_sci_fi_caps_verbs_in_button_text(index_html_text):
    """Button text should be sentence case; uppercase styling comes from CSS."""
    for verb in ["TRANSMIT", "EXECUTE", "DIVE"]:
        assert verb not in index_html_text, (
            f"'{verb}' still present — use sentence case + CSS text-transform"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — TRANSMIT/EXECUTE/DIVE found.

- [ ] **Step 3: Replace the four button texts**

At `api/static/index.html:1214`:

```html
<button class="send-btn" id="send-btn" onclick="sendMessage()">Send</button>
```

At `:1388`:

```html
<button class="action-btn pull" id="dive-btn" onclick="runDeepDive()">Research</button>
```

At `:1403`:

```html
<div class="research-empty">Enter a topic above and click Research to start deep investigation.<br><br>The model will decompose your topic, search each angle, then synthesize a structured report.</div>
```

At `:1446`:

```html
<button class="send-btn" id="wf-run-btn" onclick="runWorkflow()" style="padding:8px 28px">Run</button>
```

- [ ] **Step 4: Update JS strings that reset button text**

Replace at `api/static/index.html:1832`:

```javascript
btn.textContent = 'Send';
```

At `:2612`:

```javascript
btn.textContent = 'Research';
```

At `:2812` and `:2890`:

```javascript
btn.textContent = 'Run';
```

- [ ] **Step 5: Preserve the HUD look via CSS**

Append near the existing `.send-btn` rule (around `:514-526`):

```css
.send-btn, .action-btn.pull {
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-weight: 600;
}
```

Visual result: `Send` renders as `SEND` but the source says `Send`.

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/ui/ -v
```

- [ ] **Step 7: Manual smoke-check**

All four buttons still look like loud HUD caps, but the source reads like a normal product.

- [ ] **Step 8: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "refactor(ui): unify button microcopy on sentence case

Replaces TRANSMIT / EXECUTE / DIVE with Send / Run / Research. Preserves
the uppercase HUD look via CSS text-transform so nothing visually
changes — only the source voice becomes consistent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Global `:focus-visible` styling (P1, a11y quick win)

**Files:**
- Modify: `api/static/index.html` (global CSS, near the top of `<style>`)
- Modify: `tests/ui/test_static_markup.py`

Keyboard users currently have no visible focus indication anywhere. Add a single global rule so every focusable element gets a clear outline when (and only when) reached by keyboard.

- [ ] **Step 1: Write failing test**

```python
def test_focus_visible_outline_exists(index_html_text):
    """Global :focus-visible rule must exist for keyboard accessibility."""
    # Accept any variant that sets an outline via :focus-visible.
    m = re.search(r":focus-visible\s*\{[^}]*outline\s*:", index_html_text)
    assert m is not None, "no global :focus-visible outline rule found"
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL.

- [ ] **Step 3: Add the rule**

Near the top of the `<style>` block — after `:root{…}` and any reset, before component rules:

```css
/* === Keyboard focus (a11y) ====================================== */
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: 2px;
}
/* Don't double up on elements that already show focus via border change */
.chat-input:focus-visible,
.model-select:focus-visible,
.inv-toolbar .search-input:focus-visible,
.settings-row input:focus-visible,
.settings-row select:focus-visible { outline: none; }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/ui/ -v
```

- [ ] **Step 5: Manual smoke-check**

Tab through the page from the address bar. Every button and link gets a clear green outline. Inputs (which already show border-color on focus) don't double-outline.

- [ ] **Step 6: Commit**

```bash
git add api/static/index.html tests/ui/test_static_markup.py
git commit -m "feat(ui): global :focus-visible outline for keyboard accessibility

Previously keyboard users had no visible focus indication anywhere in
the SPA. Adds a 2px accent outline on :focus-visible with sensible
exceptions for inputs that already show a border-color change.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Post-execution verification

After all nine tasks are committed:

- [ ] **Run the full test suite**

```bash
pytest tests/ -v
```

Expected: ~11 tests, all passing.

- [ ] **Run the server and walk the app**

```bash
source ../../../venv/bin/activate
python api/main.py &
sleep 2
open http://localhost:8000/
# Walk: header says Enclave; tab through with keyboard; resize to 375px;
# paste multi-line into chat; click every tab; disconnect wifi and reload.
kill %1
```

- [ ] **View the full diff for a final sanity pass**

```bash
git log master..HEAD --oneline
git diff master..HEAD --stat
```

Expected: ~8 commits, diff concentrated in `api/static/` and `tests/ui/`.

- [ ] **Open a PR**

```bash
git push -u origin claude/ui-refresh
gh pr create --title "UI Week-1: brand, responsive, chat textarea, a11y, self-hosted assets" --body "$(cat <<'EOF'
## Summary
- Unify brand as Enclave v0.1.0 across header/footer/wizard
- Repair broken @media block (mobile layout never activated)
- Chat prompt: <input> → <textarea> with Enter/Shift+Enter/Esc semantics
- switchTab no longer relies on bare \`event\` global
- Self-host Google Fonts + d3.js (fulfills "no internet required" promise)
- Rename color tokens so --amber isn't green
- Unify button microcopy on sentence case (HUD look preserved via CSS)
- Global :focus-visible outline

## Test plan
- [x] \`pytest tests/ui/ -v\` — 10 new regression assertions
- [ ] Manual: resize 375/768/1024
- [ ] Manual: keyboard-only navigation
- [ ] Manual: offline reload (wifi off)
- [ ] Manual: multi-line paste in chat

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Roadmap (deferred — not part of this plan)

These are the Month-1 and longer-term items from the audit. They get their own plans.

**Month-1 (`2026-05-xx-ui-month1-*.md`):**
1. Extract full design-token system (`--radius`, `--space-*`, `--font-size-*`) and remove 80%+ of inline `style="…"` attributes
2. Build `.btn`/`.card`/`.tab`/`.field` component layer; reconcile with setup-wizard tokens
3. Full a11y pass — landmarks, tablist pattern, `aria-live` on `#messages`, `prefers-reduced-motion`
4. Implement streaming chat + Stop button (reuse setup-wizard's model-pull stream pattern)
5. Split `index.html` into `static/js/*.js` ES modules + `static/css/tokens.css` + per-tab CSS files
6. Setup-wizard → dashboard handoff (preselect pulled model; tailored first-run empty state)

**Longer-term:**
1. Framework adoption (Svelte + Vite favored for lowest-overhead fit with static/HUD aesthetic)
2. Shared `enclave.theme.json` consumed by web + CLI for cross-surface visual parity
3. Reusable `<enclave-chat>` component (streaming-native, ARIA-correct, themable)
4. Replace pywebview shell with Tauri (or add native menus, ⌘Q shutdown, tray toggle)

---

## Self-review notes

- Spec coverage: all 8 Week-1 items from the audit have tasks (Task 2–9). Task 1 is the test harness.
- Placeholder scan: the font-URL comment in Task 6 Step 3 is the only intentional TBD; it's flagged explicitly with a `Note:` block rather than a silent placeholder.
- Type consistency: `switchTab(name, el)` signature appears identically in Tasks 5 and consumers in Task 5 Step 4. Color tokens `--accent`/`--accent-2`/`--success`/`--warn` used consistently in Tasks 7 and 9.
