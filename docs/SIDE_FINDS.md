# Side-finds — open items for the next PR

A running list of issues, partial features, and rough edges noticed
while landing the session-recovery commit + the B/C round. Each item
is small (sub-day work) and standalone. Triage before picking up.

## High value

### 1. Decision-node runtime routing (engine-side)
**Where:** `api/services/workflow_engine.py`, `api/services/workflow_compiler.py`, `api/models/workflow_models.py`, `api/services/step_executor.py`
**What's there:** Canvas spawns 2-output decision nodes with editable
branch labels; the node renders a `DECISION` pill and branch chips.
**What's missing:** The engine still runs steps in YAML order. There's
no skip-set logic to honour a decision step's `branch_taken` against
downstream steps tagged with the *other* branch.
**Approach:**
- Add to `AgentStep`: optional `branch_from: str` (id of decision step
  it depends on) + `branch_label: str` (which branch this step belongs to)
- In the decision step's output parser, expect
  `{"branch": "<label>", "reason": "..."}` and stash `branch` in
  `workflow_run.workspace[f"{step_id}.branch_taken"]`
- In `_execute_steps`, before running each step check
  `step.branch_from` — if the parent's `branch_taken` doesn't match
  this step's `branch_label`, mark it `skipped` and move on
- Composer's "Save YAML" needs to emit `branch_from` + `branch_label`
  from the canvas connection topology (output port index → label)
**Why deferred:** ~4-file change, touches the YAML compiler. Worth a
dedicated commit so it can be reviewed in isolation.

### 2. Composer state persistence across reloads
**Where:** SPA `dfNodeData` / `dfEditor.export()`
**What's there:** Composer canvas state lives in memory only; reloading
the page loses every node + connection.
**What's missing:** Save canvas state to `localStorage` (keyed by
workflow id, or "draft" when un-named) and rehydrate on load. Also
needs a "discard draft" affordance.
**Approach:** Hook into the drawflow editor's `addNodeCreated`,
`nodeRemoved`, `connectionCreated`, `connectionRemoved`, plus
`dfUpdateNodeData` — debounce 400ms and persist. On boot, if a draft
exists, prompt to restore or discard.

### 3. Workflow run failures don't surface in the SPA toast
**Where:** SPA `ComposerWorkstream.startPolling` poller
**What's there:** Toast.danger fires on terminal `failed`, but only
when the polling loop is the one that observes the transition. If the
operator already left the Composer tab and the run failed in the
background, no toast appears.
**Fix:** Move the terminal-state notification into a module that runs
regardless of which tab is active. Tie into the `Heartbeat` or a new
`RunNotifier` that polls active runs from any page.

## Medium value

### 4. Decision-node config panel: branch count edit
**Where:** SPA `dfRenderConfigPanel` decision-node branch section
**What's there:** Branch labels are editable but the array length is
locked because drawflow can't safely resize ports live.
**What's missing:** A "+ Add branch" button that recreates the node
in-place at the same coords with `num_outputs+1`, preserving existing
connections by output index. Same for delete.
**Approach:** `dfRecreateNode(nodeId, {num_outputs})` — read current
data + connections, `removeNodeId`, `addNode` with new shape, replay
connections from the saved map.

### 5. Skills Discover: install dialog needs plugin picker
**Where:** SPA `SkillsDiscover.install()`
**What's there:** Uses `prompt()` for target plugin id.
**What's missing:** A small dialog with a `<select>` populated from
`/api/plugins` so the operator can't typo a plugin id. Also surface
the per-plugin skill count so the operator picks an obvious target.

### 6. Knowledge-graph link semantics: link weight from explicit overlap
**Where:** `api/services/graph_service.py::_build_structural_links`
**What's there:** `shares_tag` counts shared tags but `ran_role` only
substring-matches the workflow id.
**What's missing:** Make `ran_role` deterministic by reading each
run's `step_results[].step_id` + matching against agent ids/roles
properly. Drop links where the overlap score is below a threshold so
the graph doesn't get noisy at scale.

### 7. Graph legend chips overlap the graph at small viewport widths
**Where:** SPA `.graph-link-filter`, `.graph-sizing-picker`
**What's there:** New filter row + sizing picker positioned
`bottom: 36px / 62px`. On narrow viewports these overlap each other.
**Fix:** Make the picker docked to the top-right (next to the
existing zoom buttons) instead of stacked at the bottom.

### 8. Hardware-profile fallback when no `ENCLAVE_HOST_*` is set
**Where:** `api/routers/inventory.py::detect_hardware`
**What's there:** If the operator runs the API without
`scripts/host-preset.sh`, the inventory.cpu falls through to
`platform.processor()` which returns an empty string on most macOS
Pythons.
**Fix:** When falling through, also try `subprocess.run(["uname", "-m"])`
and report the architecture as a last-resort label
("aarch64 (unknown CPU brand)").

## Low value / polish

### 9. Run-pane "Cancel" button copy
**Where:** SPA `startPolling` initial paint
**What's there:** Button reads "Cancel" while running, "Clear" while
idle. Now that cancel is real-wire, the live label should say
"Cancel Run" and clear should say "Clear Output" — fewer ambiguous
verbs.

### 10. `xql-rules-reviewer` agent test
**Where:** `tests/playwright/test_skill_registration.py` or new file
**What's missing:** A regression test that `GET /api/agents/xql-rules-reviewer`
returns 200 — the AgentTool plugin-id shape was an unguarded foot-gun.

### 11. AgentIcons fallback for unrecognised personas in legacy agent YAMLs
**Where:** SPA `AgentIcons.resolve`
**What's there:** Falls through to `general` glyph.
**Polish:** When an agent has an `icon:` field that doesn't match any
known key or alias, log once to console + fall back to `general`.
Currently the fallback is silent which makes typos hard to catch.

### 12. SkillsDiscover icon-explorer: persona grouping vs category grouping
**Where:** SPA `_renderIconExplorer`
**Design question for next PR:** Currently groups by `persona`. Some
operators may prefer grouping by `category` (writing / code / data /
ops / security) since that matches how the catalog is authored.
Consider a toggle.

### 13. Workflow card private-overlay chip click
**Where:** SPA `renderWorkflowIndex` `.wfi-card-source`
**What's missing:** The "internal" chip is informational but not
clickable. Click could open `docs/PRIVATE_OVERLAY.md` in a modal to
explain why some workflows aren't in the public repo.

### 14. Composer's auto-layout button doesn't redraw the connections
**Where:** SPA `dfAutoLayout`
**What's there:** Calls `dfEditor.updateConnectionNodes(...)` per node
after layout.
**Polish:** Occasionally the SVG connection paths render briefly at
the *old* coordinates before snapping. A `requestAnimationFrame`
between the position write and `updateConnectionNodes` should fix.

### 15. Skills catalog freshness
**Where:** `data/discovery/skills_catalog.json`
**What's missing:** Catalog is hand-curated and frozen at v1.0.0.
For v1.1 wire a `last_seen` field per entry so the UI can warn when a
skill goes stale (e.g. "this skill body hasn't been refreshed since
2026-05-18").
