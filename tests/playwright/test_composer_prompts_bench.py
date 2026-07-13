"""PB-1 — Composer Prompts palette bench + drag-attach to node config.

The 7th workbench tab (data-bench="prompts", Actions-wired — no inline onclick)
renders the merged (oob+user) saved prompts as draggable cap-cards. Dropping a
prompt onto an LLM step inlines the RESOLVED body into data.system_prompt as a
point-in-time snapshot (dfAttachPromptToNode) with a _from_prompt provenance
chip — NOT a live role_ref. Guards: LLM-only (seed + composite bail), a manual
textarea edit clears the provenance, hooks excluded. The MS-2 single-row bench
invariant is re-asserted at 7 benches.

Rate-limit note: the shipped 60 rpm limiter counts a cold SPA boot's API burst,
so a suite of many sequential page loads can transiently 429 the boot-time
bench fetch (the same harness artifact V5 hit — NOT a product defect). The
fetch-dependent tests self-heal: they re-fetch/re-render (renderPromptsWorkbench)
and retry the attach until the sliding window drains, rather than asserting a
single boot succeeded under saturation.
"""

from __future__ import annotations

PROMPTS_TAB = '.workbench-tab[data-bench="prompts"]'
SEED_SEL = "#drawflow-canvas .df-seed-node"
# python_developer.md ships in prompts/roles/ (oob layer) — a stable role id.
ROLE_ID = "role:python_developer"

# In-page helpers, prepended to each evaluate that needs the API. Both poll
# past a saturated rate window (no hard pytest timeout is configured).
_JS_HELPERS = """
const _sleep = ms => new Promise(r => setTimeout(r, ms));
// Re-fetch /api/prompts and repaint the bench until a card lands (self-heals a
// boot fetch that 429'd under the cold-boot burst). Returns true once painted.
const ensureBench = async (budgetMs = 90000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < budgetMs) {
    if (document.querySelector('#bench-prompts .cap-card')) return true;
    try {
      const r = await Net.call('/api/prompts');
      if (r.ok) window.renderPromptsWorkbench((r.data || []).filter(p => p && p.kind !== 'hook'));
    } catch (_) {}
    if (document.querySelector('#bench-prompts .cap-card')) return true;
    await _sleep(1500);
  }
  return false;
};
const fetchBody = async (ref, budgetMs = 90000) => {
  const kind = ref.split(':')[0], pid = ref.slice(kind.length + 1);
  const t0 = Date.now();
  while (Date.now() - t0 < budgetMs) {
    const r = await Net.call(`/api/prompts/${kind}/${pid}`);
    if (r.ok) return (r.data && r.data.body) || '';
    await _sleep(1500);
  }
  return null;
};
const attachWithRetry = async (nid, ref, budgetMs = 90000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < budgetMs) {
    await window.dfAttachPromptToNode(nid, ref);
    const d = window.dfNodeData[nid];
    if (d && d._from_prompt === ref) return true;
    await _sleep(1500);
  }
  return false;
};
"""


def _wait_canvas(page):
    """Canvas booted = the seed pill spawned and the bridge exposes the add +
    attach helpers this suite drives."""
    page.wait_for_selector(SEED_SEL, state="visible", timeout=10_000)
    page.wait_for_function(
        "() => typeof window.dfAddNodeFromTemplate === 'function'"
        " && typeof window.dfAttachPromptToNode === 'function'"
        " && typeof window.renderPromptsWorkbench === 'function'"
        " && typeof window.dfExportYaml === 'function'",
        timeout=10_000,
    )


def test_prompts_tab_wired_and_single_row(signed_in_page):
    """DOM-only invariants (no API needed, so 429-proof): Prompts is a
    delegated bench tab (data-action, no inline onclick), its pane shows on
    switch, and at 1600px all seven tabs share a single offsetTop (MS-2
    invariant re-asserted at 7 benches, flex-wrap:nowrap)."""
    page = signed_in_page
    page.set_viewport_size({"width": 1600, "height": 900})
    _wait_canvas(page)
    tab = page.locator(PROMPTS_TAB)
    assert tab.count() == 1, "Prompts workbench tab missing"
    assert tab.get_attribute("onclick") is None, "new tab must not use inline onclick"
    assert tab.get_attribute("data-action") == "bench.switch"
    tab.click()
    page.locator("#bench-prompts").wait_for(state="visible", timeout=5_000)
    tops = page.evaluate(
        "() => Array.from(document.querySelectorAll('.workbench-tabs .workbench-tab'))"
        ".map(t => t.offsetTop)"
    )
    assert len(tops) >= 7, f"expected >=7 workbench tabs after PB-1, got {len(tops)}"
    assert len(set(tops)) == 1, f"workbench tabs wrapped to multiple rows: {tops}"
    flex_wrap = page.evaluate(
        "() => getComputedStyle(document.querySelector('.workbench-tabs')).flexWrap"
    )
    assert flex_wrap == "nowrap", f"workbench-tabs must not wrap, got flex-wrap={flex_wrap}"


def test_prompts_bench_renders_draggable_cards(signed_in_page):
    """The bench renders draggable cap-cards carrying the df-prompt MIME + a
    `<kind>:<id>` value; hooks are excluded (engine presets, not system
    prompts). Self-heals a 429'd boot fetch via re-fetch + re-render."""
    page = signed_in_page
    _wait_canvas(page)
    page.locator(PROMPTS_TAB).click()
    painted = page.evaluate(_JS_HELPERS + "async () => await ensureBench()")
    assert painted, "Prompts bench never painted a card (even after retry)"
    card = page.locator("#bench-prompts .cap-card").first
    assert card.get_attribute("data-drag-mime") == "application/df-prompt"
    val = card.get_attribute("data-drag-value") or ""
    assert ":" in val, f"card drag value must be <kind>:<id>, got {val!r}"
    kinds = page.evaluate(
        "() => Array.from(document.querySelectorAll('#bench-prompts .cap-card'))"
        ".map(c => (c.dataset.dragValue || '').split(':')[0])"
    )
    assert kinds, "no prompt cards rendered"
    assert "hook" not in kinds, f"hooks must be excluded from the Prompts bench: {kinds}"


def test_prompt_attach_semantics(signed_in_page):
    """One page load exercises the full attach contract:
      1. attach a role to an LLM step → data.system_prompt == the resolved body
         (snapshot), data._from_prompt stamped, NO role_ref, serializes to YAML,
         provenance chip painted;
      2. a manual textarea edit clears data._from_prompt;
      3. attach to the seed node bails (no slot);
      4. attach to a composite (ralph) parent bails.
    """
    page = signed_in_page
    _wait_canvas(page)
    result = page.evaluate(
        _JS_HELPERS
        + """async (roleRef) => {
            const out = {};
            // (1) LLM attach round-trip.
            const nid = window.dfAddNodeFromTemplate('analyzer', 360, 220);
            out.expected = await fetchBody(roleRef);
            out.attached = await attachWithRetry(nid, roleRef);
            const d = window.dfNodeData[nid];
            out.system_prompt = d.system_prompt;
            out.from_prompt = d._from_prompt;
            out.role_ref = d.role_ref || (d.prompt && d.prompt.role_ref) || null;
            out.yaml_has_prompt = window.dfExportYaml().includes('system_prompt');
            window.dfRenderConfigPanel(nid);
            out.chip = !!document.querySelector('.df-provenance-chip');
            // (2) manual edit clears provenance.
            const ta = document.querySelector(
                '#df-config-panel textarea[data-field="system_prompt"], '
                + '#df-config-popup-body textarea[data-field="system_prompt"]');
            if (ta) {
                ta.value = 'You are a bespoke, hand-edited agent.';
                ta.dispatchEvent(new Event('change', { bubbles: true }));
            }
            out.cleared = window.dfNodeData[nid]._from_prompt === undefined;
            // (3) seed bail.
            const seed = Object.entries(window.dfNodeData || {}).find(([, x]) => x && x.is_seed);
            if (seed) {
                const [sid, sdata] = seed;
                const before = sdata.system_prompt;
                await window.dfAttachPromptToNode(Number(sid), roleRef);
                const s = window.dfNodeData[sid];
                out.seed_bailed = s._from_prompt === undefined && s.system_prompt === before;
            }
            // (4) composite bail.
            window.dfScaffoldPattern('ralph_loop', 700, 260);
            const par = Object.entries(window.dfNodeData || {}).find(([, x]) => x && x.kind === 'ralph');
            if (par) {
                const [pid, pdata] = par;
                const before = pdata.system_prompt;
                await window.dfAttachPromptToNode(Number(pid), roleRef);
                const p = window.dfNodeData[pid];
                out.composite_bailed = p._from_prompt === undefined && p.system_prompt === before;
            }
            return out;
        }""",
        ROLE_ID,
    )
    assert result["expected"], "precondition: role body must be non-empty"
    assert result["attached"], "attach never landed (even after retry)"
    assert result["system_prompt"] == result["expected"], "system_prompt not the resolved role body"
    assert result["from_prompt"] == ROLE_ID, f"provenance not stamped: {result['from_prompt']!r}"
    assert result["role_ref"] is None, "attach must be a snapshot, never a live role_ref"
    assert result["yaml_has_prompt"], "system_prompt did not serialize through dfExportYaml"
    assert result["chip"], "config-panel provenance chip missing after attach"
    assert result["cleared"], "manual edit did not clear provenance"
    assert result.get("seed_bailed"), "attach to seed did not bail"
    assert result.get("composite_bailed"), "attach to composite did not bail"


def test_synthetic_drop_df_prompt_attaches_to_node(signed_in_page):
    """The real drop handler reads the df-prompt MIME and routes to the attach
    seam: a synthetic drop onto a step node inlines the prompt (exercises
    wireWorkbenchDropHandlers, not just the bridged helper)."""
    page = signed_in_page
    _wait_canvas(page)
    result = page.evaluate(
        _JS_HELPERS
        + """async (roleRef) => {
            const nid = window.dfAddNodeFromTemplate('analyzer', 360, 220);
            const nodeEl = document.getElementById('node-' + nid);
            if (!nodeEl) return { ok: false, why: 'no node element' };
            const fire = () => {
                const r = nodeEl.getBoundingClientRect();
                const dt = new DataTransfer();
                dt.setData('application/df-prompt', roleRef);
                nodeEl.dispatchEvent(new DragEvent('drop', {
                    bubbles: true, cancelable: true, dataTransfer: dt,
                    clientX: r.left + r.width / 2, clientY: r.top + r.height / 2,
                }));
            };
            const t0 = Date.now();
            while (Date.now() - t0 < 90000) {
                fire();
                await _sleep(1500);
                if (window.dfNodeData[nid]._from_prompt === roleRef) break;
            }
            const d = window.dfNodeData[nid];
            return { ok: true, from_prompt: d._from_prompt, has_body: (d.system_prompt || '').length > 0 };
        }""",
        ROLE_ID,
    )
    assert result["ok"], result
    assert result["from_prompt"] == ROLE_ID, f"synthetic drop did not attach: {result}"
    assert result["has_body"], "synthetic drop attached empty system_prompt"
