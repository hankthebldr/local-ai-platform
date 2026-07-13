"""BU4 — Patterns bench: tab + cards, SIMPLE drop, COMPLEX scaffold.

The 6th workbench tab (data-bench="patterns", Actions-wired — no inline
onclick) renders dfPatternTemplates as draggable cards with SIMPLE/COMPLEX
badges. Drops are simulated via page.evaluate against the window-bridged
dfAddPatternFromTemplate / dfScaffoldPattern (HTML5 drag is flaky headless):
a SIMPLE pattern spawns one node stamping data.kind; the ralph COMPLEX
pattern scaffolds its wired sub-DAG (parent + plan/execute/verify/consolidate
editing proxies sharing the parent's nested body objects).
"""

from __future__ import annotations

PATTERNS_TAB = '.workbench-tab[data-bench="patterns"]'
SEED_SEL = "#drawflow-canvas .df-seed-node"


def _wait_canvas(page):
    """Canvas booted = the seed pill has spawned (debounced ~150 ms) and the
    bridge exposes the pattern spawners."""
    page.wait_for_selector(SEED_SEL, state="visible", timeout=10_000)
    page.wait_for_function(
        "() => typeof window.dfAddPatternFromTemplate === 'function'"
        " && typeof window.dfScaffoldPattern === 'function'",
        timeout=10_000,
    )


def test_patterns_tab_exists_and_renders_cards(signed_in_page):
    """The Patterns bench is the 6th tab, wired via data-action (no inline
    onclick), and renders one card per dfPatternTemplates preset with a
    SIMPLE/COMPLEX badge + a title tooltip."""
    page = signed_in_page
    _wait_canvas(page)
    tab = page.locator(PATTERNS_TAB)
    assert tab.count() == 1, "Patterns workbench tab missing"
    assert tab.get_attribute("onclick") is None, "new tab must not use inline onclick"
    assert tab.get_attribute("data-action") == "bench.switch"
    tab.click()
    pane = page.locator("#bench-patterns")
    pane.wait_for(state="visible", timeout=5_000)
    cards = page.locator("#patterns-palette .df-pattern-card")
    expected = page.evaluate("() => (window.dfPatternTemplates || []).length")
    assert expected >= 8, f"expected >=8 pattern presets, got {expected}"
    assert cards.count() == expected
    # Both complexity tiers are represented, and every card drags with the
    # pattern MIME + carries a tooltip.
    assert page.locator("#patterns-palette .df-pattern-badge.simple").count() >= 5
    assert page.locator("#patterns-palette .df-pattern-badge.complex").count() >= 3
    first = cards.first
    assert first.get_attribute("data-drag-mime") == "application/df-pattern"
    assert (first.get_attribute("title") or "").strip(), "card tooltip missing"
    # The Ralph card carries the budget-preset toggle (one card, two presets).
    ralph = page.locator('#patterns-palette [data-pattern="ralph_loop"]')
    assert ralph.locator(".df-pattern-preset-btn").count() == 2


def test_simple_pattern_drop_creates_one_kinded_node(signed_in_page):
    """Dropping a SIMPLE pattern (code sandbox) creates exactly one new node
    whose dfNodeData entry stamps data.kind + the kind config block and the
    pattern provenance fields."""
    page = signed_in_page
    _wait_canvas(page)
    before = page.evaluate("() => Object.keys(window.dfNodeData || {}).length")
    page.evaluate("() => window.dfAddPatternFromTemplate('code_sandbox', 320, 220)")
    page.wait_for_function(
        "n => Object.keys(window.dfNodeData || {}).length === n + 1",
        arg=before,
        timeout=5_000,
    )
    node = page.evaluate(
        "() => Object.values(window.dfNodeData || {})"
        ".find(d => d && d.pattern === 'code_sandbox')"
    )
    assert node, "code_sandbox node not registered in dfNodeData"
    assert node["kind"] == "code"
    assert node["complexity"] == "SIMPLE"
    assert node["code"]["language"] == "python"
    assert node["code"]["source"] == "inline"


def test_workbench_benches_stay_single_row_at_1600(signed_in_page):
    """MS-2 invariant re-asserted on the Patterns bench (PB-1 re-runs it at 7
    benches): at 1600px every workbench tab shares a single offsetTop — the tab
    strip scrolls horizontally (flex-wrap:nowrap) instead of wrapping to a
    second row, which the 6th (Patterns) tab used to trigger."""
    page = signed_in_page
    page.set_viewport_size({"width": 1600, "height": 900})
    _wait_canvas(page)
    tops = page.evaluate(
        "() => Array.from(document.querySelectorAll('.workbench-tabs .workbench-tab'))"
        ".map(t => t.offsetTop)"
    )
    assert len(tops) >= 6, f"expected >=6 workbench tabs, got {len(tops)}"
    assert len(set(tops)) == 1, f"workbench tabs wrapped to multiple rows: {tops}"


def test_complex_ralph_pattern_scaffolds_wired_sub_dag(signed_in_page):
    """Dropping the ralph COMPLEX pattern creates the composite parent plus
    its four body proxies (plan/execute/verify/consolidate), wired
    parent -> plan -> execute -> verify -> consolidate, with each proxy's
    data object shared with the parent's nested body entry."""
    page = signed_in_page
    _wait_canvas(page)
    page.evaluate("() => window.dfScaffoldPattern('ralph_loop', 380, 260)")
    page.wait_for_function(
        "() => Object.values(window.dfNodeData || {})"
        ".some(d => d && d.kind === 'ralph')",
        timeout=5_000,
    )
    result = page.evaluate(
        """() => {
            const entries = Object.entries(window.dfNodeData || {});
            const parent = entries.find(([, d]) => d && d.kind === 'ralph');
            if (!parent) return { ok: false, why: 'no ralph parent' };
            const [pid, pdata] = parent;
            const subs = entries.filter(([, d]) => d && d._sub_of === Number(pid));
            // Proxy data objects ARE the parent's nested body entries.
            const shared = subs.every(([, d]) => (pdata.body || []).includes(d));
            // Wiring: parent -> body[0], then a sequential body chain.
            const home = window.dfEditor.export().drawflow.Home.data;
            const outEdges = (id) => Object.values((home[id] || {}).outputs || {})
              .flatMap(o => (o.connections || []).map(c => Number(c.node)));
            const subIds = subs.map(([id]) => Number(id));
            let chained = outEdges(Number(pid)).includes(subIds[0]);
            for (let i = 0; i + 1 < subIds.length; i++) {
              chained = chained && outEdges(subIds[i]).includes(subIds[i + 1]);
            }
            return {
              ok: true,
              bodyIds: (pdata.body || []).map(b => b.id),
              subCount: subs.length,
              subRoles: subs.map(([, d]) => d._sub_role),
              shared,
              chained,
              journal: pdata.ralph && pdata.ralph.journal_path,
              maxIter: pdata.ralph && pdata.ralph.halt && pdata.ralph.halt.max_iterations,
            };
        }"""
    )
    assert result["ok"], result
    assert result["bodyIds"] == ["plan", "execute", "verify", "consolidate"]
    assert result["subCount"] == 4, f"expected 4 sub-DAG proxies: {result}"
    assert set(result["subRoles"]) == {"body"}
    assert result["shared"], "proxy data must share the parent's nested body objects"
    assert result["chained"], "sub-DAG not wired parent -> plan -> ... -> consolidate"
    assert result["journal"], "ralph.journal_path missing"
    # Default budget preset (standard) stamps its halt caps.
    assert result["maxIter"] == 25


def test_ralph_composite_survives_save_reload_save(signed_in_page):
    """GP-1a (P0-2): a scaffolded ralph composite survives
    Save → reload (composerLoadDefinition) → Save with its kind + nested
    body/ralph config intact. Before P0-2, composerLoadDefinition flattened
    every step to a plain llm node, so the reloaded workflow lost its ralph
    kind and re-saved as four disconnected top-level steps."""
    page = signed_in_page
    _wait_canvas(page)
    result = page.evaluate(
        """() => {
            const yaml = window.jsyaml;
            // 1. Scaffold a ralph composite onto the canvas.
            window.dfScaffoldPattern('ralph_loop', 380, 260);
            document.getElementById('df-wf-id').value = 'rt-ralph';
            document.getElementById('df-wf-name').value = 'RT Ralph';
            // 2. Serialize → parse (exactly what Save persists / load reads back).
            const defn1 = yaml.load(window.dfExportYaml());
            // 3. Reload the saved definition onto a fresh canvas (clears first).
            window.composerLoadDefinition(defn1);
            // 4. Re-serialize the reloaded canvas.
            const defn2 = yaml.load(window.dfExportYaml());
            const ralphOf = (d) => (d.steps || []).find(s => s && s.kind === 'ralph');
            const shape = (r) => r ? {
                kind: r.kind,
                body: (r.body || []).map(b => b.id),
                journal: r.ralph && r.ralph.journal_path,
                maxIter: r.ralph && r.ralph.halt && r.ralph.halt.max_iterations,
            } : null;
            return {
                loadedHydrated: !!(window.dfNodeData &&
                    Object.values(window.dfNodeData).some(d => d && d.kind === 'ralph')),
                bodyProxies: window.dfNodeData
                    ? Object.values(window.dfNodeData).filter(d => d && d._sub_role === 'body').length : 0,
                topLevelSteps: (defn2.steps || []).length,
                r1: shape(ralphOf(defn1)),
                r2: shape(ralphOf(defn2)),
            };
        }"""
    )
    assert result["r1"], "scaffolded ralph did not serialize as a composite"
    assert result["loadedHydrated"], "composite kind flattened on load (P0-2 regression)"
    assert result["bodyProxies"] == 4, f"expected 4 body proxies after reload: {result}"
    # The sub-DAG steps fold NESTED into the ralph parent — never as extra
    # top-level steps (that was the pre-P0-2 flatten failure).
    assert result["topLevelSteps"] == 1, f"body steps leaked to top level: {result}"
    assert result["r2"], "ralph composite lost its kind on reload+save (flattened)"
    assert result["r2"] == result["r1"], f"ralph not stable across round-trip: {result}"


def test_parallel_composite_survives_save_reload_save(signed_in_page):
    """GP-1a (P0-2): the parallel branch/gather hydration path round-trips too —
    research_fanout is an llm index step + a parallel fan-out; after reload the
    parallel step keeps its kind, branches and gather (branch proxies fold
    nested, never leaking as top-level steps)."""
    page = signed_in_page
    _wait_canvas(page)
    result = page.evaluate(
        """() => {
            const yaml = window.jsyaml;
            window.dfScaffoldPattern('research_fanout', 380, 260);
            document.getElementById('df-wf-id').value = 'rt-fanout';
            document.getElementById('df-wf-name').value = 'RT Fanout';
            const defn1 = yaml.load(window.dfExportYaml());
            window.composerLoadDefinition(defn1);
            const defn2 = yaml.load(window.dfExportYaml());
            const parOf = (d) => (d.steps || []).find(s => s && s.kind === 'parallel');
            const shape = (p) => p ? {
                kind: p.kind,
                branches: (p.branches || []).map(b => b.id),
                gather: p.gather && p.gather.id,
            } : null;
            return {
                loadedHydrated: !!(window.dfNodeData &&
                    Object.values(window.dfNodeData).some(d => d && d.kind === 'parallel')),
                branchProxies: window.dfNodeData
                    ? Object.values(window.dfNodeData).filter(d => d && d._sub_role === 'branch').length : 0,
                gatherProxies: window.dfNodeData
                    ? Object.values(window.dfNodeData).filter(d => d && d._sub_role === 'gather').length : 0,
                topLevelSteps: (defn2.steps || []).length,
                p1: shape(parOf(defn1)),
                p2: shape(parOf(defn2)),
            };
        }"""
    )
    assert result["p1"], "scaffolded research_fanout did not serialize a parallel step"
    assert result["loadedHydrated"], "parallel kind flattened on load (P0-2 regression)"
    assert result["branchProxies"] >= 2, f"expected >=2 branch proxies after reload: {result}"
    assert result["gatherProxies"] == 1, f"expected exactly one gather proxy: {result}"
    # index (llm) + fanout (parallel) = 2 top-level steps; branches/gather nest.
    assert result["topLevelSteps"] == 2, f"branch/gather leaked to top level: {result}"
    assert result["p2"] == result["p1"], f"parallel not stable across round-trip: {result}"
