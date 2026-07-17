#!/usr/bin/env python3
"""Guard the Enclave Composer's structural LAYOUT contract.

The Composer (#tab-dashboard) is a nest of pure-CSS grids that ONLY work
because specific parent/child relationships hold. These are the relationships
that, if silently rewired by an autonomous edit, break the layout *visibly*
while every functional / parity test still passes:

  * `.composer-split` is a 2-row grid whose child-combinator rules
    (`.composer-split > .composer-grid`, `> .composer-workstream`,
    `> #composer-spine-dormant`) match NOTHING if those regions get nested
    one level deeper — the whole split collapses.
  * `.composer-grid` is a 2-column grid (palette | canvas). Move `.composer-left`
    or `.composer-center` out and a column vanishes.
  * `.workbench-tabs { display:flex; flex-wrap:nowrap; overflow-x:auto }` keeps
    the 7 bench tabs on ONE scrolling row. If a tab stops being a sibling of
    the others (lands outside `.workbench-tabs`), it wraps / drops — the
    classic "6th tab jumps to a 2nd row" regression, caught here structurally.
  * `.workstream-tabs` is the same single-row contract for the 5 sub-tabs.
  * `#composer-canvas-empty` is `position:absolute; inset:0` and is toggled by
    `.composer-canvas-panel.has-nodes .composer-canvas-empty { display:none }`.
    It and `#drawflow-canvas` must COEXIST under the (position:relative) canvas
    panel — they are NOT mutually exclusive in markup; JS/CSS hides the overlay.

Fast bs4 parse of the shipped index.html. No browser, no pixels — pure
structure: element presence + parent/child + sibling relationships.
"""

from pathlib import Path

from bs4 import BeautifulSoup

INDEX = Path(__file__).resolve().parents[2] / "api" / "static" / "index.html"


def _soup():
    return BeautifulSoup(INDEX.read_text(encoding="utf-8"), "html.parser")


def _has_class(el, cls):
    return el is not None and cls in (el.get("class") or [])


def _direct_children(el):
    return el.find_all(recursive=False) if el is not None else []


# ── The Composer region + its top-level grid regions ──────────────────────


def test_composer_region_present():
    """The Composer lives under the (back-compat) #tab-dashboard region."""
    dash = _soup().find(id="tab-dashboard")
    assert dash is not None, "#tab-dashboard (the Composer tab) is missing"
    assert dash.find(class_="composer-split") is not None, (
        "the Composer split is missing from #tab-dashboard"
    )


def test_split_holds_grid_and_workstream_as_direct_children():
    """`.composer-split` is a 2-row grid. Its child-combinator rules
    (`.composer-split > .composer-grid` / `> .composer-workstream`) only match
    when these regions are DIRECT children — nesting them breaks the split."""
    split = _soup().find(id="composer-split")
    assert _has_class(split, "composer-split"), "#composer-split[.composer-split] missing"

    direct = _direct_children(split)

    assert any(_has_class(c, "composer-grid") for c in direct), (
        ".composer-grid must be a DIRECT child of .composer-split "
        "(grid child-combinator `.composer-split > .composer-grid` matches "
        "nothing otherwise) — found it nested or absent."
    )
    assert any(c.get("id") == "composer-workstream" for c in direct), (
        "#composer-workstream must be a DIRECT child of .composer-split "
        "(row-2 grid placement `.composer-split > .composer-workstream`) — "
        "found it nested or absent."
    )


def test_three_regions_coexist():
    """Left palette/workbench + canvas + bottom workstream all present."""
    s = _soup()
    # left palette / workbench
    assert s.find(class_="composer-left") is not None, ".composer-left (palette rail) missing"
    assert s.find(class_="workbench-tabs") is not None, ".workbench-tabs (bench bar) missing"
    # canvas
    assert s.find(id="drawflow-canvas") is not None, "#drawflow-canvas missing"
    assert s.find(id="composer-canvas-panel") is not None, "#composer-canvas-panel missing"
    # bottom workstream
    assert s.find(id="composer-workstream") is not None, "#composer-workstream missing"


# ── The palette | canvas 2-column grid ────────────────────────────────────


def test_grid_holds_left_and_center_columns():
    """`.composer-grid` is `grid-template-columns: <rail> 1fr`. Both columns —
    `.composer-left` (palette) and `.composer-center` (canvas host) — must be
    its DIRECT children or a whole column disappears."""
    grid = _soup().find(class_="composer-grid")
    assert grid is not None, ".composer-grid missing"
    direct = _direct_children(grid)
    assert any(_has_class(c, "composer-left") for c in direct), (
        ".composer-left must be a direct child of .composer-grid (column 1)"
    )
    assert any(_has_class(c, "composer-center") for c in direct), (
        ".composer-center must be a direct child of .composer-grid (column 2)"
    )


# ── Workbench bench tabs: one row, all siblings ───────────────────────────

EXPECTED_BENCHES = {"steps", "agents", "skills", "plugins", "mcps", "patterns", "prompts"}


def test_workbench_tabs_all_present_and_are_one_row_of_siblings():
    """Every bench tab (Task/Agents/Skills/Plugins/MCPs/Patterns/Prompts) must
    exist AND share the single `.workbench-tabs` parent. `.workbench-tabs` is
    `flex-wrap:nowrap; overflow-x:auto` — a tab that is not a sibling of the
    rest wraps to a second row (the "6th tab wraps" class of bug). Pin the
    contract at the sibling level so that regression can't land uncaught."""
    s = _soup()
    tabs = s.find_all("button", class_="workbench-tab")
    benches = {t.get("data-bench") for t in tabs}
    assert EXPECTED_BENCHES.issubset(benches), (
        f"missing bench tab(s): {EXPECTED_BENCHES - benches}"
    )

    parents = {id(t.parent) for t in tabs if t.get("data-bench") in EXPECTED_BENCHES}
    assert len(parents) == 1, (
        "all workbench tabs must be siblings under ONE .workbench-tabs bar; "
        f"found them split across {len(parents)} parent containers "
        "(a tab escaped the single-row flex bar → it wraps/drops)."
    )

    (bar,) = {t.parent for t in tabs if t.get("data-bench") in EXPECTED_BENCHES}
    assert _has_class(bar, "workbench-tabs"), (
        "the shared bench-tab parent must be .workbench-tabs (the single-row "
        f"flex bar), got classes={bar.get('class')}"
    )


def test_each_bench_tab_has_its_pane():
    """Each bench tab addresses a `#bench-<name>` pane under `.workbench-body`;
    keep the tab↔pane pairing intact so switching benches has a target."""
    s = _soup()
    body = s.find(class_="workbench-body")
    assert body is not None, ".workbench-body (pane host) missing"
    for bench in EXPECTED_BENCHES:
        assert body.find(id=f"bench-{bench}") is not None, (
            f"#bench-{bench} pane missing from .workbench-body"
        )


# ── Workstream sub-tabs: one row, all siblings ────────────────────────────

EXPECTED_WS = {"step", "run", "history", "logs", "in-progress"}


def test_workstream_subtabs_all_present_and_are_siblings():
    """Step Config / Active Run / History / Logs / In-Progress sub-tabs must
    exist and share one `.workstream-tabs` bar (same single-row contract as the
    bench tabs)."""
    s = _soup()
    tabs = s.find_all("button", class_="workstream-tab")
    wss = {t.get("data-ws") for t in tabs}
    assert EXPECTED_WS.issubset(wss), f"missing workstream sub-tab(s): {EXPECTED_WS - wss}"

    parents = {id(t.parent) for t in tabs if t.get("data-ws") in EXPECTED_WS}
    assert len(parents) == 1, (
        "all workstream sub-tabs must be siblings under ONE .workstream-tabs "
        f"bar; found them split across {len(parents)} parents."
    )
    (bar,) = {t.parent for t in tabs if t.get("data-ws") in EXPECTED_WS}
    assert _has_class(bar, "workstream-tabs"), (
        f"shared sub-tab parent must be .workstream-tabs, got {bar.get('class')}"
    )


def test_each_workstream_subtab_has_its_pane():
    """Each sub-tab points at a `#ws-pane-<name>` under `.workstream-body`."""
    s = _soup()
    body = s.find(class_="workstream-body")
    assert body is not None, ".workstream-body missing"
    for ws in EXPECTED_WS:
        assert body.find(id=f"ws-pane-{ws}") is not None, (
            f"#ws-pane-{ws} missing from .workstream-body"
        )


# ── Empty-state overlay + canvas coexist under the canvas panel ───────────


def test_empty_overlay_and_canvas_coexist_under_panel():
    """`#composer-canvas-empty` (the seed/getting-started overlay) is
    `position:absolute; inset:0` and is hidden via a CSS class toggle
    (`.composer-canvas-panel.has-nodes .composer-canvas-empty`), NOT by removal.
    So the overlay and `#drawflow-canvas` must BOTH live inside the same
    (position:relative) `.composer-canvas-panel` — they are not mutually
    exclusive in markup. If the overlay leaves the panel it loses its
    positioning context and mis-renders; if it replaces the canvas the DAG
    never mounts."""
    s = _soup()
    panel = s.find(id="composer-canvas-panel")
    assert _has_class(panel, "composer-canvas-panel"), "#composer-canvas-panel missing"

    canvas = panel.find(id="drawflow-canvas")
    empty = panel.find(id="composer-canvas-empty")
    assert canvas is not None, (
        "#drawflow-canvas must live inside #composer-canvas-panel (the DAG mount)"
    )
    assert empty is not None, (
        "#composer-canvas-empty overlay must live inside #composer-canvas-panel "
        "(shares its position:relative context; coexists with the canvas)"
    )


def test_canvas_panel_is_inside_the_center_column():
    """The canvas panel must sit in `.composer-center` (column 2 of the grid).
    That parent chain is what places the canvas in the grid — losing it drops
    the canvas out of the layout."""
    s = _soup()
    panel = s.find(id="composer-canvas-panel")
    center = panel.find_parent(class_="composer-center")
    assert center is not None, (
        "#composer-canvas-panel must be nested under .composer-center "
        "(the grid's canvas column)"
    )
    assert center.find_parent(class_="composer-grid") is not None, (
        ".composer-center must itself live under .composer-grid"
    )


def test_workstream_defaults_minimized_and_auto_expands():
    """The bottom workstream defaults to MINIMIZED (tabs-only preview) to free
    canvas space, and a deliberate selection re-expands it for detail:
      * #composer-workstream ships with the `collapsed` class,
      * its ▴/▾ toggle reports the collapsed state via aria-expanded="false",
      * ComposerWorkstream.switchTab (tab click) and focusStep (node select)
        both call _ensureExpanded() so switching a hidden pane isn't a dead-end.
    Background updates (polling, bench-hover inspectors) use _setActive directly
    and must NOT force-expand, so a manual collapse sticks."""
    s = _soup()
    ws = s.find(id="composer-workstream")
    assert ws is not None and _has_class(ws, "collapsed"), (
        "#composer-workstream must default to the minimized (collapsed) state"
    )
    btn = s.find(id="workstream-collapse-btn")
    assert btn is not None and btn.get("aria-expanded") == "false", (
        "collapse toggle must advertise the collapsed state via aria-expanded=false"
    )

    js = (Path(__file__).resolve().parents[2] / "api" / "static" / "js"
          / "workspace-legacy" / "composer-workstream.js").read_text(encoding="utf-8")
    assert "function _ensureExpanded()" in js
    # Both deliberate-selection entry points expand; _setActive itself does not.
    switch_fn = js[js.index("function switchTab("): js.index("function focusStep(")]
    assert "_ensureExpanded()" in switch_fn, "switchTab must expand on tab click"
    focus_fn = js[js.index("function focusStep("): js.index("function focusStep(") + 400]
    assert "_ensureExpanded()" in focus_fn, "focusStep must expand on node select"
    setactive_fn = js[js.index("function _setActive("): js.index("function _ensureExpanded(")]
    assert "_ensureExpanded" not in setactive_fn, (
        "_setActive must stay expand-neutral so background/hover updates don't "
        "fight a manual collapse"
    )
