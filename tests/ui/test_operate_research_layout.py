#!/usr/bin/env python3
"""Guard the STRUCTURAL layout contract of the Operate + Research surfaces.

These surfaces (Runs, Workflows-in-Operate, Projects, Artifacts, Context,
Research) are wired by delegated `data-action` handlers and by JS modules that
resolve mounts by *id* at runtime (RunsTab, ArtifactsTab, ContextNodeRail,
ResearchStore, …). An autonomous edit that renames an id, drops a container,
or unnests a region silently severs that wiring — the tab still "renders" but
the picker paints nothing, the rail never mounts, or a golden filter chip stops
filtering. Pixel/text assertions are too brittle to catch this; these tests pin
the DOM STRUCTURE (ids, containers, chip contracts) only.

Fast bs4 parse of api/static/index.html — NO browser, NO pixel/text asserts.
Mirrors tests/ui/test_shell_layout.py. Every id asserted here was verified
against the live markup + the JS that resolves it.
"""

from pathlib import Path

from bs4 import BeautifulSoup

INDEX = Path(__file__).resolve().parents[2] / "api" / "static" / "index.html"


def _soup():
    return BeautifulSoup(INDEX.read_text(encoding="utf-8"), "html.parser")


# ── RUNS (#tab-runs) ────────────────────────────────────────────────────────


def test_runs_tab_list_and_detail_regions_exist():
    """RunsTab renders the recent-runs list + the run-detail region by class;
    both must exist inside #tab-runs, each with its live inner mount id."""
    runs = _soup().find(id="tab-runs")
    assert runs is not None, "#tab-runs container missing (RunsTab has nowhere to mount)"

    lst = runs.find(class_="runs-tab-list")
    assert lst is not None, ".runs-tab-list (recent-runs list container) missing from #tab-runs"
    assert runs.find(id="runs-tab-rows") is not None, "#runs-tab-rows list mount missing"

    detail = runs.find(class_="runs-tab-detail")
    assert detail is not None, ".runs-tab-detail (run detail region) missing from #tab-runs"
    assert runs.find(id="runs-tab-detail-head") is not None, "#runs-tab-detail-head missing"
    assert runs.find(id="runs-tab-canvas") is not None, "#runs-tab-canvas (mini-DAG mount) missing"


def test_runs_perf_band_container_exists():
    """The calm-analytics perf band (#runs-perf-band) is where operating
    decisions surface; RunsTab fills its child chart/gauge mounts by id."""
    runs = _soup().find(id="tab-runs")
    band = runs.find(id="runs-perf-band")
    assert band is not None, "#runs-perf-band (runs dashboard / perf band) missing from #tab-runs"
    assert "runs-perf-band" in (band.get("class") or [])


def test_runs_four_legacy_setfilter_chips_are_golden_pinned():
    """F3: the four inline RunsTab.setFilter chips (all/running/completed/failed)
    are GOLDEN-PINNED — they must keep their inline onclick=setFilter contract.
    A delegated rewrite of these four would be a silent regression."""
    row = _soup().find(class_="runs-tab-filter-row")
    assert row is not None, ".runs-tab-filter-row (run filter chips row) missing"

    for flt in ("all", "running", "completed", "failed"):
        chip = row.find("button", attrs={"data-filter": flt})
        assert chip is not None, f"legacy setFilter chip data-filter='{flt}' missing (golden-pinned)"
        onclick = chip.get("onclick") or ""
        assert f"RunsTab.setFilter('{flt}')" in onclick, (
            f"chip '{flt}' lost its inline RunsTab.setFilter('{flt}') handler "
            f"(golden-pinned contract — must NOT be re-delegated)"
        )


def test_runs_newer_health_and_type_chips_exist():
    """Alongside the four golden chips: the delegated Degraded (health) chip and
    the orthogonal Type-axis chip row — both route through data-action, not inline."""
    runs = _soup().find(id="tab-runs")
    row = runs.find(class_="runs-tab-filter-row")
    degraded = row.find("button", attrs={"data-action": "runs.filter-health", "data-health": "degraded"})
    assert degraded is not None, "delegated Degraded health chip (data-action=runs.filter-health) missing"

    type_row = runs.find(class_="runs-tab-type-row")
    assert type_row is not None, ".runs-tab-type-row (type-axis chip row) missing"
    type_chips = type_row.find_all("button", attrs={"data-action": "runs.filter-type"})
    assert len(type_chips) >= 2, "expected the delegated type-axis chips (data-action=runs.filter-type)"


# ── WORKFLOWS (moved into the Operate nav group) ────────────────────────────


def _nav_children_with_section(soup):
    """Walk .tab-nav in document order, tagging each .tab-btn with the
    nav-section label that most recently preceded it."""
    nav = soup.find(class_="tab-nav")
    assert nav is not None, ".tab-nav rail missing"
    section = None
    out = []
    for child in nav.find_all(recursive=False):
        classes = child.get("class") or []
        if "nav-section" in classes:
            section = child.get_text(strip=True)
        elif "tab-btn" in classes:
            out.append((section, child))
    return out


def test_workflows_nav_button_lives_in_operate_group():
    """U1: the Workflows nav button (data-tab='workflow-index') was relocated
    into the Operate section — after the 'Operate' divider, grouped with
    Projects/Runs/Context. Guards the IA move from silent regrouping."""
    tagged = _nav_children_with_section(_soup())
    by_tab = {btn.get("data-tab"): (sec, btn) for sec, btn in tagged}

    assert "workflow-index" in by_tab, "Workflows nav button (data-tab='workflow-index') missing"
    section, btn = by_tab["workflow-index"]
    assert "Workflows" in btn.get_text(strip=True), "workflow-index button is no longer labeled 'Workflows'"
    assert section == "Operate", (
        f"Workflows button must sit under the Operate nav-section, found under '{section}'"
    )
    # Grouped with its Operate siblings (guards the whole group moving together).
    for sibling in ("projects", "runs", "context"):
        assert by_tab.get(sibling, (None,))[0] == "Operate", (
            f"expected '{sibling}' nav button in the Operate group beside Workflows"
        )


# ── PROJECTS (#tab-projects) ────────────────────────────────────────────────


def test_projects_kanban_board_has_at_least_three_columns():
    """The kanban board (#kanban-board, relocated into Projects at runtime) is
    the board surface. The Operate build extended it to 5 columns; pin >=3 with
    the canonical todo/doing/done lanes present so a shrink can't pass silently."""
    soup = _soup()
    assert soup.find(id="tab-projects") is not None, "#tab-projects container missing"
    assert soup.find(id="projects-seg-board") is not None, "#projects-seg-board (Board segment) missing"

    board = soup.find(id="kanban-board")
    assert board is not None, "#kanban-board container missing"
    cols = board.find_all(class_="kanban-col")
    assert len(cols) >= 3, f"kanban board must keep >=3 columns, found {len(cols)}"

    col_keys = {c.get("data-column") for c in cols}
    for lane in ("todo", "doing", "done"):
        assert lane in col_keys, f"kanban board missing the '{lane}' column (data-column='{lane}')"


# ── ARTIFACTS (#tab-artifacts) ──────────────────────────────────────────────


def test_artifacts_tab_has_three_panes():
    """U11/O5: Artifacts is three LibraryShell-adapter panes — outputs /
    workspaces / format-sets. ArtifactsTab resolves each mount + shell host by
    id; all three panes and the pane switch buttons must exist."""
    art = _soup().find(id="tab-artifacts")
    assert art is not None, "#tab-artifacts container missing"

    for pane_id in ("artifacts-pane-outputs", "artifacts-pane-workspaces", "artifacts-pane-formats"):
        assert art.find(id=pane_id) is not None, f"#{pane_id} pane missing from #tab-artifacts"

    for host_id in ("artifacts-outputs-shell", "artifacts-workspaces-shell", "artifacts-formats-shell"):
        assert art.find(id=host_id) is not None, f"#{host_id} shell mount missing"

    for pane in ("outputs", "workspaces", "formats"):
        btn = art.find("button", attrs={"data-action": "artifacts.pane", "data-pane": pane})
        assert btn is not None, f"Artifacts pane button data-pane='{pane}' missing"


# ── CONTEXT (#tab-context) ──────────────────────────────────────────────────


def test_context_graph_and_node_rail_mount_exist():
    """S4/U14: the Context tab hosts its OWN run/provenance graph (#context-graph-svg,
    kept distinct from Research's #graph-svg) plus the node rail. context-view.js
    registers kind:'context-node' with pane='context', mount='context-detail-actions';
    that mount + the #context-node-list picker must exist or the rail never paints."""
    ctx = _soup().find(id="tab-context")
    assert ctx is not None, "#tab-context container missing"

    assert ctx.find("svg", id="context-graph-svg") is not None, (
        "#context-graph-svg (Context's own run/provenance graph) missing"
    )
    assert ctx.find(id="context-node-list") is not None, "#context-node-list node picker missing"
    # ContextNodeRail.register('context-node', { mount: 'context-detail-actions' })
    assert ctx.find(id="context-detail-actions") is not None, (
        "#context-detail-actions missing — the context-node rail mount "
        "(shell/context-node-rail.js pane-guard target) has no home"
    )


# ── RESEARCH (#tab-research) ────────────────────────────────────────────────


def test_research_session_thread_and_reading_surface_exist():
    """RX-1: the stateful research session — LEFT conversational thread
    (#research-thread) + RIGHT reading surface (#research-surface) inside
    #research-session. main.js renderResearchSession resolves all three by id."""
    res = _soup().find(id="tab-research")
    assert res is not None, "#tab-research container missing"

    session = res.find(id="research-session")
    assert session is not None, "#research-session (stateful session container) missing"
    assert res.find(id="research-thread") is not None, "#research-thread (session/thread container) missing"
    assert res.find(id="research-surface") is not None, "#research-surface (reading surface) missing"


def test_research_store_file_browser_containers_exist():
    """RX-2: the ResearchStore Obsidian-like file browser — research-store.js
    resolves #research-store-tree + #research-store-preview by id under the
    #research-store-panel host. All three must exist for the browser to mount."""
    res = _soup().find(id="tab-research")
    assert res.find(id="research-store-panel") is not None, "#research-store-panel host missing"
    assert res.find(id="research-store-tree") is not None, "#research-store-tree (file tree) missing"
    assert res.find(id="research-store-preview") is not None, "#research-store-preview (note preview) missing"


def test_research_node_rail_mount_exists():
    """RX-2: research-node-rail.js registers kind:'research-node' with
    pane='research', mount='research-node-rail'; that mount id must exist inside
    the session detail panel or the exploratory rail never paints."""
    res = _soup().find(id="tab-research")
    assert res.find(id="research-node-rail") is not None, (
        "#research-node-rail mount missing (research/research-node-rail.js target)"
    )
