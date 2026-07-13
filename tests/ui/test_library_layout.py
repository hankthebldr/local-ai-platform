#!/usr/bin/env python3
"""Guard the uniform LibraryShell layout contract across ALL Library tabs.

Every Library kind (prompt/mcp/skill/model/plugin/agent/task/pattern) renders
through ONE shell — `api/static/js/library/shell.js` — into a two-pane
master-detail grammar (sidebar list + detail). The uniformity is the whole
point of the LB0-U1 "multiple formats → one shell" convergence: a kind
`register()`s an adapter, and the shell owns the sidebar (Installed|Discovered
side-tabs, `.lib-filter`, `.lib-row` rows), the detail subnav, and the actions
row. If an autonomous edit silently drops a required tab container, renames a
list/detail mount id an adapter points at, deletes the shared `.lib-*` CSS
grammar, or regresses a kind back onto a legacy bespoke panel, the layout
breaks with no test to catch it.

This is a STRUCTURAL contract test — fast bs4/regex parse of the LIVE static
assets, no browser, no pixel/text assertions. It reads each adapter's REAL
`kind`/`tabId`/`listElId`/`detailElId` out of the JS (rather than hard-coding
guessed ids) so the contract tracks the code, then pins:
  1. every library tab-content container exists,
  2. every two-pane list/detail (or mount host) container each adapter targets
     exists,
  3. the shared `.lib-*` shell CSS grammar is defined, and
  4. exactly the expected 8 kinds register on LibraryShell.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "api" / "static"
INDEX = STATIC / "index.html"
LIB = STATIC / "js" / "library"
APP_CSS = STATIC / "css" / "app.css"

# The 8 adapter modules that each register exactly one Library kind on the
# shell. `models.js` is the legacy panel; the model ADAPTER lives in
# models-panel.js (verified against the live shell.register() call sites).
ADAPTER_MODULES = {
    "prompt": "prompts.js",
    "mcp": "mcp.js",
    "skill": "skills.js",
    "model": "models-panel.js",
    "plugin": "plugins.js",
    "agent": "agents.js",
    "task": "tasks.js",
    "pattern": "patterns.js",
}

# The convergence invariant: exactly these kinds are the uniform Library set.
EXPECTED_KINDS = set(ADAPTER_MODULES)

INDEX_TEXT = INDEX.read_text(encoding="utf-8")


def _src(module):
    return (LIB / module).read_text(encoding="utf-8")


def _field(src, field):
    """Extract a single-quoted adapter field value (kind/tabId/listElId/…)."""
    m = re.search(rf"\b{field}\s*:\s*'([^']+)'", src)
    return m.group(1) if m else None


def _registered_kind(src):
    """Extract the adapter kind from INSIDE the LibraryShell.register({...})
    call — not any earlier `kind:` field (e.g. a step-data default)."""
    i = src.find("LibraryShell.register(")
    if i == -1:
        return None
    return _field(src[i:], "kind")


def _mount_host(src):
    """Extract the host container id from a `LibraryShell.mount('kind','host')`
    call (used by kinds that build their two-pane DOM at runtime)."""
    m = re.search(r"LibraryShell\.mount\(\s*'[^']+'\s*,\s*'([^']+)'", src)
    return m.group(1) if m else None


def _has_id(el_id):
    return f'id="{el_id}"' in INDEX_TEXT


def _lib_shell_css():
    """The dedicated <style id="lib-shell-styles"> block + app.css — where the
    shared `.lib-*` grammar is defined."""
    m = re.search(
        r'<style id="lib-shell-styles">(.*?)</style>', INDEX_TEXT, re.DOTALL
    )
    block = m.group(1) if m else ""
    css = APP_CSS.read_text(encoding="utf-8") if APP_CSS.exists() else ""
    return block + "\n" + css


# ── 1. Every library tab-content container exists ─────────────────────────
def test_every_library_tab_container_exists():
    """switchTab(name) resolves `#tab-<tabId>`; a missing tab container means a
    whole Library kind has no home to render into."""
    for kind, module in ADAPTER_MODULES.items():
        tab_id = _field(_src(module), "tabId")
        assert tab_id, f"{module}: adapter is missing a tabId field"
        container = f"tab-{tab_id}"
        assert _has_id(container), (
            f"{kind}: library tab container #{container} "
            f"(tabId='{tab_id}') missing from index.html"
        )


# ── 2. The two-pane list/detail (or mount host) containers exist ──────────
def test_two_pane_grammar_containers_exist():
    """Adapters with static panel DOM declare listElId/detailElId that MUST
    resolve in index.html; adapters that build their pane at runtime declare a
    `LibraryShell.mount('kind','host')` host container that must exist."""
    for kind, module in ADAPTER_MODULES.items():
        src = _src(module)
        list_id = _field(src, "listElId")
        detail_id = _field(src, "detailElId")
        if list_id or detail_id:
            assert list_id and _has_id(list_id), (
                f"{kind}: sidebar list container #{list_id} "
                f"(adapter.listElId) missing from index.html"
            )
            assert detail_id and _has_id(detail_id), (
                f"{kind}: detail container #{detail_id} "
                f"(adapter.detailElId) missing from index.html"
            )
        else:
            host = _mount_host(src)
            assert host, (
                f"{kind}: adapter declares no listElId/detailElId and no "
                f"LibraryShell.mount(...) host — cannot resolve a two-pane target"
            )
            assert _has_id(host), (
                f"{kind}: LibraryShell.mount host container #{host} "
                f"missing from index.html"
            )


# ── 3. The shared `.lib-*` shell CSS grammar is defined ───────────────────
def test_shell_css_grammar_classes_defined():
    """The sidebar rows, filter, Installed/Discovered side-tabs, and detail
    subnav all key off shared `.lib-*` classes rendered by shell.js. If those
    rules vanish, every Library tab renders unstyled."""
    css = _lib_shell_css()
    required = [
        "lib-shell",        # two-pane wrapper
        "lib-row",          # uniform sidebar row
        "lib-filter",       # client-side filter input
        "lib-side-tabs",    # Installed|Discovered container
        "lib-side-tab",     # Installed / Discovered side-tab
        "lib-group-label",  # collapsible group header
        "lib-subnav",       # detail subnav container
        "lib-subnav-pill",  # Overview/Config/… subnav pill
        "lib-actions-row",  # install/test/edit/promote/delete row
    ]
    for cls in required:
        assert re.search(rf"\.{re.escape(cls)}\b", css), (
            f"shared shell CSS class .{cls} is not defined in "
            f"<style id='lib-shell-styles'> or app.css"
        )


# ── 4. Exactly the expected 8 kinds register on LibraryShell ──────────────
def test_expected_eight_kinds_register_on_shell():
    """Pins the 'multiple formats → one shell' convergence: each of the 8
    modules must actually call LibraryShell.register with its expected kind, so
    a future edit can't silently drop a kind back to a legacy bespoke format."""
    registered = set()
    for kind, module in ADAPTER_MODULES.items():
        src = _src(module)
        assert "LibraryShell.register(" in src, (
            f"{kind}: {module} no longer calls LibraryShell.register — it may "
            f"have regressed to a legacy standalone panel"
        )
        actual_kind = _registered_kind(src)
        assert actual_kind == kind, (
            f"{module}: expected to register kind '{kind}', found '{actual_kind}'"
        )
        registered.add(actual_kind)
    assert registered == EXPECTED_KINDS, (
        f"Library kind set drifted: {registered} != {EXPECTED_KINDS}"
    )
