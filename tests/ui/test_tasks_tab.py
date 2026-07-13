"""LB6 — Task Menu library tab + the non-regressive Composer bench feed.

Two layers, mirroring test_models_panel.py / test_skills_shell.py:

1. Static assertions (bs4 / served-JS corpus): the Tasks tab mounts on the
   LibraryShell with the full tasks.* action grammar; rows ride the LB0 row
   contract; NO inline handlers / NO new window globals. The bench feed is
   NON-DESTRUCTIVE — the frozen 13-entry `dfStepTemplates` array is never
   mutated (length 13, last key 'custom'), library tasks live in a
   module-scoped Map, get their OWN action id `bench.inspect-library-task`
   and their OWN drag MIME `application/df-library-task`, spawn via
   `dfAddNodeFromLibraryTask` (the dfAddPatternNode seam), sit under a
   "Library" divider AFTER the statics, dedupe with statics winning, and
   fail-soft to a byte-identical palette. Privacy: the bench feed and the
   adapter load hit GET /api/tasks (never a network refresh); the only egress
   is POST /api/tasks/discover/refresh behind the visible button.

2. Runtime (Playwright against the dev server, skipped when unreachable):
   the Composer palette renders exactly 13 static task rows first, any
   library rows sit after the divider, and the static rows keep their
   bench.inspect-template action id.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "api" / "static"
TASKS_JS = (STATIC / "js" / "library" / "tasks.js").read_text(encoding="utf-8")
MAIN_JS = (STATIC / "js" / "main.js").read_text(encoding="utf-8")
SHELL_JS = (STATIC / "js" / "library" / "shell.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


# ── 1. Action grammar + adapter contract ────────────────────────────────────


def test_tasks_ships_every_spec_action():
    for action in [
        "tasks.select", "tasks.new", "tasks.create-save", "tasks.create-cancel",
        "tasks.edit", "tasks.save", "tasks.cancel-edit", "tasks.delete",
        "tasks.render", "tasks.test", "tasks.send-to-composer", "tasks.open-ref",
        "tasks.discover-refresh", "tasks.install",
    ]:
        assert f"'{action}'" in TASKS_JS or action in MAIN_JS, f"missing action {action}"
    # send-to-composer is registered in main.js (needs the canvas internals).
    assert "'tasks.send-to-composer'" in MAIN_JS
    # the library-task bench card has its OWN mouseover action id.
    assert "'bench.inspect-library-task'" in MAIN_JS


def test_tasks_adapter_contract_fields():
    assert "kind: 'task'" in TASKS_JS
    assert "tabId: 'tasks'" in TASKS_JS
    assert "countBadgeId: 'tasks-count'" in TASKS_JS
    assert "auth: 'optional'" in TASKS_JS
    assert "LibraryShell.mount('task', 'tasks-shell')" in TASKS_JS


def test_no_inline_handlers_or_new_window_globals():
    # no on*= inline handlers introduced in the tasks module
    assert not re.search(r"\son[a-z]+=", TASKS_JS)
    # no new window.X = globals bridged from tasks.js or the LB6 main.js adds
    assert "window.TasksPanel" not in TASKS_JS
    assert "window.TasksPanel =" not in MAIN_JS
    assert "window.dfAddNodeFromLibraryTask" not in MAIN_JS


def test_rows_ride_the_lb0_row_contract():
    # installed rows carry provenance + blocks + chips/badges via the contract
    assert "provenance: t.source === 'builtin' ? 'oob' : 'user'" in TASKS_JS
    assert "blocks: ['context']" in TASKS_JS
    assert "pattern_affinity" in TASKS_JS


def test_test_slot_mounts_lb1_step_adapter():
    assert "TestPane.mount('step'" in TASKS_JS
    assert "stepData: _stepData(t)" in TASKS_JS


def test_open_ref_rides_libraryshell_open():
    assert "LibraryShell.open('prompt', el.dataset.ref)" in TASKS_JS


def test_create_is_wizard_backed():
    assert "LibraryWizard.open(" in TASKS_JS
    assert "data-wiz-key" in TASKS_JS


# ── 2. Privacy: reads never fetch; refresh is the only egress ───────────────


def test_bench_feed_and_load_read_only():
    # adapter.load + fetchComposerTasks GET /api/tasks (no network refresh)
    assert "LibraryShell.fetch('task', '/api/tasks')" in TASKS_JS
    assert "Net.call('/api/tasks', { silent: true, retries: 0 })" in TASKS_JS
    # the discover READ is a plain GET; egress lives ONLY in the refresh POST
    assert "'/api/tasks/discover'" in TASKS_JS
    assert "method: 'POST'" in TASKS_JS
    m = re.search(r"/api/tasks/discover/refresh['\"][^;]*method: 'POST'", TASKS_JS, re.S)
    assert m, "discover refresh must be a POST (operator-triggered egress)"


def test_writes_are_retries_zero():
    # every mutating POST/PUT/DELETE in the module rides retries:0
    for m in re.finditer(r"method: '(POST|PUT|DELETE)'", TASKS_JS):
        window = TASKS_JS[max(0, m.start() - 200): m.start() + 40]
        assert "retries: 0" in window, f"{m.group(1)} near offset {m.start()} not retries:0"


# ── 3. Bench feed is NON-DESTRUCTIVE (blocker F1) ───────────────────────────


def test_dfsteptemplates_frozen_length_13_ends_on_custom():
    block = MAIN_JS[MAIN_JS.index("const dfStepTemplates = ["):]
    block = block[: block.index("];") + 1]
    keys = re.findall(r"key:\s*'([a-z_]+)'", block)
    assert len(keys) == 13, f"dfStepTemplates must stay 13, got {len(keys)}"
    assert keys[-1] == "custom", "the length-1 fallback relies on 'custom' last"


def test_dfsteptemplates_never_mutated():
    # LB6 must not push/splice/pop into the frozen array
    for bad in [
        "dfStepTemplates.push", "dfStepTemplates.splice", "dfStepTemplates.unshift",
        "dfStepTemplates.pop",
    ]:
        assert bad not in MAIN_JS, f"frozen array mutated: {bad}"
    # no index/element assignment into the array
    assert not re.search(r"dfStepTemplates\[[^\]]*\]\s*=", MAIN_JS)
    # the ONLY `dfStepTemplates =` is the original const declaration
    assigns = re.findall(r"\bdfStepTemplates\s*=", MAIN_JS)
    assert len(assigns) == 1, "dfStepTemplates must only be assigned once (const decl)"
    assert "const dfStepTemplates = [" in MAIN_JS


def test_library_tasks_use_own_map_and_seam():
    # module-scoped Map (not window global) holds mapped library records
    assert "const dfLibraryTemplates = new Map()" in TASKS_JS
    # dedupe: static keys read from the DOM, statics win
    assert "data-template-key" in TASKS_JS
    assert "staticKeys.has(t.id)" in TASKS_JS
    # spawn mirrors dfAddNodeFromTemplate but registers via dfAddPatternNode
    assert "function dfAddNodeFromLibraryTask" in MAIN_JS
    assert "dfAddPatternNode(data, x, y)" in MAIN_JS


def test_library_tasks_have_distinct_mime_and_action():
    # own drag MIME — the static application/df-template path is untouched
    assert "application/df-library-task" in TASKS_JS
    assert "application/df-library-task" in MAIN_JS
    # the static handlers still exist unchanged
    assert "application/df-template" in MAIN_JS
    assert "'bench.inspect-template'" in MAIN_JS
    # library rows carry their own inspect action id
    assert "'bench.inspect-library-task'" in TASKS_JS


def test_bench_feed_is_failsoft_and_idempotent():
    # idempotence guard on the divider; single "Library" divider AFTER statics
    assert "data-lib-divider" in TASKS_JS
    assert "if (!r.ok) return" in TASKS_JS       # network miss → palette untouched
    assert "if (!tasks.length) return" in TASKS_JS
    # dfInitPalette calls the feed AFTER rendering the 13 statics, fail-soft
    palette_fn = MAIN_JS[MAIN_JS.index("function dfInitPalette()"):]
    palette_fn = palette_fn[: palette_fn.index("\n}\n")]
    assert "TasksPanel.fetchComposerTasks()" in palette_fn


def test_drop_handler_has_additive_library_branch():
    # the canvas drop handler routes the library MIME to the new spawn fn,
    # and the df-template branch stays first + untouched
    drop = MAIN_JS[MAIN_JS.index("container.addEventListener('drop'"):]
    drop = drop[:2000]
    assert "getData('application/df-template')" in drop
    assert "getData('application/df-library-task')" in drop
    assert "dfAddNodeFromLibraryTask(TasksPanel.libraryTask(" in drop


# ── 4. Tab markup + nav ─────────────────────────────────────────────────────


def test_tasks_tab_markup_present():
    assert 'id="tab-tasks"' in INDEX
    assert 'id="tasks-shell"' in INDEX
    assert 'id="tasks-count"' in INDEX
    assert 'data-tab-target="tasks"' in INDEX
    assert 'data-action="tasks.new"' in INDEX
    assert 'data-action="tasks.discover-refresh"' in INDEX


def test_switchtab_dispatches_tasks_activate():
    assert "TasksPanel.activate()" in MAIN_JS
    assert "name === 'tasks'" in MAIN_JS


def test_main_registers_tasks_router():
    main_py = (STATIC.parents[0] / "main.py").read_text(encoding="utf-8")
    assert "tasks" in main_py
    assert "_tasks_router.router" in main_py


# ── 5. Runtime (Playwright, skip when server down) ──────────────────────────

BASE_URL = os.environ.get("ENCLAVE_PLAYWRIGHT_BASE_URL", "http://localhost:8000")


def _server_up() -> bool:
    import requests

    try:
        return requests.get(f"{BASE_URL}/health", timeout=3).status_code == 200
    except Exception:
        return False


requires_server = pytest.mark.skipif(
    not _server_up(), reason=f"Enclave dev server not reachable at {BASE_URL}"
)


@pytest.fixture()
def shell_page(page):
    import requests

    key = requests.get(f"{BASE_URL}/api/setup/local-license", timeout=5).json().get("key", "")
    page.goto(f"{BASE_URL}/")
    page.evaluate(
        """(key) => {
            window.localStorage.setItem('enclave.licenseKey', key);
            window.localStorage.setItem('enclave.theme', 'dark');
        }""",
        key,
    )
    page.goto(f"{BASE_URL}/")
    page.wait_for_selector("#tab-dashboard", state="visible", timeout=10_000)
    return page


@requires_server
def test_palette_keeps_13_statics_first(shell_page):
    page = shell_page
    page.evaluate("() => switchTab('dashboard')")
    page.wait_for_selector("#df-palette .df-palette-item", timeout=10_000)
    state = page.evaluate(
        """() => {
            const items = Array.from(document.querySelectorAll('#df-palette .df-palette-item'));
            const statics = items.filter(el => el.dataset.templateKey);
            const libs = items.filter(el => el.dataset.taskId);
            const divider = document.querySelector('#df-palette [data-lib-divider]');
            const dividerIdx = divider ? Array.from(divider.parentElement.children).indexOf(divider) : -1;
            const firstLibIdx = libs.length ? Array.from(libs[0].parentElement.children).indexOf(libs[0]) : -1;
            return {
                staticCount: statics.length,
                staticActions: statics.map(el => el.dataset.action),
                hasDivider: !!divider,
                libsAfterDivider: firstLibIdx === -1 || firstLibIdx > dividerIdx,
            };
        }"""
    )
    # exactly the 13 frozen statics, each keeping bench.inspect-template
    assert state["staticCount"] == 13
    assert set(state["staticActions"]) == {"bench.inspect-template"}
    # any library rows sit AFTER the divider (statics untouched, first)
    assert state["libsAfterDivider"]


@requires_server
def test_tasks_tab_mounts_shell(shell_page):
    page = shell_page
    page.evaluate("() => switchTab('tasks')")
    page.wait_for_selector("#tab-tasks", state="visible", timeout=5_000)
    page.wait_for_selector("#tasks-shell .lib-shell", timeout=10_000)
    mounted = page.evaluate(
        "() => !!document.querySelector('#tasks-shell .plugins-layout')"
    )
    assert mounted
