# Platform hardening + research experience — design

**Date:** 2026-07-11 · **Branch:** `feat/composer-workspace` · **Status:** draft — pending operator approval
**Provenance:** merged draft spec (make-it-stick / research / drafts / composer-capability / gap-fixes / polish) → 58-finding gap ledger + P0-verify (some P0s REFUTED) + execution-verify (stuck-score forensics) → 3 adversarial critics (40 issues: 2 blockers, 22 majors, 16 minors). All 40 folded in below — see the Critique-resolutions table at the end. **Every code claim in this revision was re-verified against the live `feat/composer-workspace` tree at authoring time** (line anchors drift ±30 as the Library-alignment build lands on the same branch — verify at edit time). Where a prior draft shipped a fix its own P0-verify refuted, the fix has been corrected or re-scoped, not carried.

---

## Overview

One merged spec for `feat/composer-workspace`, sequenced into six gates. The through-line: **the operator's previous work must demonstrably STICK, and every surface must CHAIN into the next** — seed→compose→configure→test→run→observe→refine→re-run→save→draft→reload, plus chat→crystallize→run and research→save→build-upon. Today those loops close *within* a surface but many *between-surface* edges are broken links.

### Honest verdict on the low stuck-scores (read this first)

The 1–2/10 execution scores that motivated a "rip it up" reading of this branch are **dominated by two non-product artifacts, not by broad breakage**:

1. **The now-fixed ships-broken rate-limit bug (MS-1, P0-12).** A cold SPA load fires ~70–73 requests against the shipped `RATE_LIMIT_RPM=60`; the limiter did not exempt `/static/`, so the app **self-429'd its own boot** (`/v1/models`, `/api/agents`, `/api/roles`, `/api/plugins`), and `main.js`/ComposerSplit never loaded. Verifiers literally could not exercise the app without the `RATE_LIMIT_RPM=0` workaround (V1's env hack, V3's 7×429 cold-boot). This one-liner poisoned every downstream score. **It is now committed (26b1260) and this spec marks MS-1 DONE.**
2. **Test-harness artifacts, not defects.** V4's discover/refresh and recommend/explain routes were left un-probed on purpose to honor the privacy/no-egress and no-model rails (not failures). V5's 31 "ERROR" UI tests + several FAILs were a wrong-port artifact — the backend command defaults `ENCLAVE_PLAYWRIGHT_BASE_URL` to `:8000` while the dev server runs `:8001`; the identical files pass green in the fast loop at `:8001` (321 passed).

**The prior work largely LANDED and is committed/gated-green.** The composer agentic revamp is 14/14 e2e green (V1); the Library-alignment shell is landing with its UI suites green (V2). Do not overstate the damage.

**The genuinely real, new defects are bounded** and are what Gate A targets:
- Composer empty-state overlay stays painted *over* real nodes after a palette drop, and the 6th Patterns bench tab wraps to a second row (MS-2, verified live).
- Research capture 422 — untruncated title / empty synthesis body against `feedback.py` field limits, reproduced live (MS-3).
- Library **format divergence** — the operator's "multiple formats" complaint: Skills double-discovery + duplicate legacy filter selects, Models flanked by two non-shell surfaces, MCP inline-onclick toolbar, and Agents-tab-not-migrated (MS-4/MS-5).

Everything past Gate A is chaining/capability/hardening work on a fundamentally-working base, not triage of a broken one.

### Coordination baseline (three programs in motion — dedupe, do not fork)

1. **LANDED** — Composer agentic revamp (`docs/superpowers/specs/2026-07-10-composer-agentic-revamp-design.md`): Task/Patterns benches, seed node, per-step Logs, inspector, signals, safety rails, loop-wrap, starters. Verified green (V1: 14/14 e2e).
2. **LANDING NOW** — Library alignment (`.../2026-07-10-library-alignment-design.md`): LibraryShell/Wizard, Admin Sources, discovery digests, TestPane, hooks kind, recommender, skills/models rebuilds, plugin forge (LB5-U3 landed 48e595c), Task Menu (LB6 landed fd0e7c4).
3. **APPROVED + QUEUED (not building)** — Operate plane (`.../2026-07-10-operate-plane-design.md`): Workflows nav move (U1), Projects board (U2/U3/U12), scheduler backend (U4/U8), run index/health (U5/U6), shared step render (U7), Artifacts + Workspaces (U10/U11), context rail (U13/U14).

**Dedupe rule:** a gap is real only if NO landed code and NO approved Operate/Library unit covers it. Where Operate/Library covers it, this spec *routes* to that unit rather than rebuilding.

---

## Hard constraints (honored by construction in every unit)

- **Frozen engine — byte-clean.** NO edits to `api/services/workflow_engine.py`, `api/services/step_executor.py`, `api/models/workflow_models.py`. **This revision removes the one engine touch the prior draft carried:** the P0-9 layered-prompt fix moves *entirely* into `api/services/prompt_composer.py` (not in the frozen set). GP-2 now makes **zero** frozen-engine touches (prior "two additive engine touches" wording is retired).
- **Only-add**, with two pre-authorized exceptions (MS-5 replaces `#tab-agents` markup; CP-1 deletes malformed `<header>`/dead breadcrumb CSS/nav `aria-hidden`) whose parity-snapshot deltas are pre-approved in the parity suite.
- **No new inline `on*`/globals** for new affordances (Actions `data-action` registry); pre-existing inline handlers kept under only-add are migrated opportunistically, not required.
- **Parity baseline**; **privacy** (every fetch operator-initiated, no background egress; research follow-up `web_search` defaults OFF); **`require_master_key`/scope gating on writes**; **path containment**; **LibraryShell/Wizard reuse** for new library kinds.

---

## Gate ordering (six gates)

- **Gate A — MAKE-IT-STICK (MS-1…MS-5).** MS-1 is **DONE** (committed 26b1260). **The blanket "after the library gate" rule was wrong and is corrected:** MS-1/MS-2/MS-3 are **library-independent and go next, in that order**; only the **library-coupled** units are gated behind the library build. Order: MS-2 → MS-3, then MS-4 → MS-5 **after the library gate**.
- **Gate B — RESEARCH (RX-1, RX-2).** RX-1 = stateful conversation + reading surface. RX-2 = actionable results + Obsidian-like RAG store + exploratory graph rail. **RX-2 OWNS the shared context-node-rail** (see Blocker 2) and pins the `research` workspace slug (Operate U11/U14 amend to consume).
- **Gate C — DRAFTS KEYSTONE (DR-1).** Durable draft store, `draft_id` identity, In-Progress tab, restore-on-open. **Prototype-first on `dfEditor.import()` (see Collision bindings).**
- **Gate D — COMPOSER CAPABILITY (GP-1 P0-2 first, then PB-1, PT-1, CH-1).** **P0-2 (composite load hydration) is pulled to the front of Gate D** so composite Fix&Resume and safe pattern editing are live for the flagship object within the same gate.
- **Gate E — RESIDUAL GAP FIXES (GP-1 remainder, GP-2).** Serializer/launch residue (GP-1) + security/integrity/runtime-resolution (GP-2, split into 7 commits).
- **Gate F — POLISH (CP-1).** Consistency + onboarding + power-user, split into 3 commits.

Each gate is signed off before the next begins (CLAUDE.md phase-gating).

---

## Blocker resolutions

### Blocker 1 — GP-2 P0-9 must not touch the frozen engine (layered prompts move to `prompt_composer.py`)

**Verified seam.** `api/services/workflow_engine.py:166-168` constructs the sole runtime composer:

```python
self.composer = PromptComposer(
    roles_dir=project_root / "prompts" / "roles",
    templates_dir=project_root / "prompts" / "templates",
)
```

`PromptComposer.__init__` (`prompt_composer.py:43`) takes `(roles_dir, templates_dir)`; `_load_role` (`:101-115`) resolves `roles_dir/<ref>.md` with a `relative_to` containment check against a single oob root and caches in `_role_cache`. User-layer edits (LB0-U3 copy-on-write) are written to `user_storage_root/prompts/roles` (`deployment.ensure_dirs` creates `prompts/{roles,templates,hooks}`), consulted only by the CRUD/preview surface in `prompts.py` — never at run time. Hence the silent no-op.

**Fix (additive, `prompt_composer.py` only — engine line stays byte-clean):**
1. Add an additive constructor arg to `PromptComposer` — `user_roles_dir: Path | None = None` (default `None` preserves current behavior for every existing caller). The engine construction line is **not edited**; instead `PromptComposer.__init__` computes the user layer itself when the arg is `None` by calling the deployment resolver already used by `prompts.py` (`deployment.get_current().user_storage_root / "prompts" / "roles"`), guarded so a missing dir is a no-op.
2. Generalize `_load_role` into a **shared layered resolver** with **per-layer containment**: try `user_roles_dir/<ref>.md` first (containment-checked against the user root), fall back to `roles_dir/<ref>.md` (containment-checked against the oob root) — the same user-shadows-oob order `prompts.py::_resolve` already implements. Cache key stays `ref` (each engine builds a fresh `PromptComposer` per request via `workflows.py get_engine()`, so cross-run edit visibility holds; no stale-cache defeat).
3. Frozen-engine gate: `git diff` on `workflow_engine.py`/`step_executor.py`/`workflow_models.py` must be **empty**. GP-2's file list drops `workflow_engine.py` entirely.

**Co-resident-spec invariant honored:** both Library-alignment and Operate declare `workflow_engine.py` read-only and audit it. This revision keeps that audit byte-clean.

### Blocker 2 — RX-2 vs Operate U14 context-node-rail ownership: THIS spec ships first, so it OWNS the rail

**Verified:** no `context-node-rail` module exists in the tree today (`api/static/js/shell/` and `api/static/js/runs/` contain only `context-view.js`). Operate U14 lists the rail as a NEW file it owns; RX-2 (Gate B) lands long before U14. The prior "import if landed, else factor for U14" produces a guaranteed fork.

**Fix (single ownership, inverted dependency):**
1. RX-2 lands the rail as a **canonical neutral shell module: `api/static/js/shell/context-node-rail.js`** — kind-agnostic node-rail helpers (registration, adopt-existing-DOM, and the **single** pane-guard so a click in one surface never drives another surface's rail). RX-2's `research/research-node-rail.js` registers `kind:'research-node'` **into** this shared module; it does not reimplement rail plumbing.
2. **Formal amendment note (Operate U14):** *U14 must CONSUME `api/static/js/shell/context-node-rail.js` (import + register `kind:'context-node'`), NOT re-create it. The pane-guard is declared once, in the shared module. U14's file list changes from "NEW `runs/context-node-rail.js`" to "register into shared `shell/context-node-rail.js`."* Requires Operate sign-off before RX-2 ships; if it cannot be locked, sequence RX-2's node-rail after U14 instead of factoring ahead.
3. **`research` workspace slug pinned in both specs.** Pin the literal name `research` as a shared constant. **Amendment note (Operate U11):** *U11 must LIST/preset-launch the same-named `research` workspace ("same store, two views") rather than minting its own artifacts workspace.* Producer (RX-2) and consumer (U11) agree on the slug; sign-off required before RX-2 ships.

---

## Refuted-P0 corrections

### P0-6 (seed 422) — FALSE premise; re-scoped from P0 to P1 UX, 422 framing removed

**Verified at `workflow_engine.py:419-422`:**

```python
if input_ref not in available:
    if input_ref.startswith("seed.") and seed_keys is None:
        continue
```

`wfi.run` posts `seed:{}` → `run-async` maps empty dict to `seed_keys=None` → `validate()` **`continue`s past every `seed.*` ref**, so **no `WorkflowValidationError`, no 422**. The premise "Run › posts `seed:{}` → 422 for every seed-consuming workflow" is false; empty seed is precisely the input that universally passes seed validation.

**Correction:**
- **Drop the 422 justification** from the deliverable and verify. Remove the P0 label.
- **Re-scope to the real P1** ("Seed node has no per-key VALUE inputs; loaded workflows get no editable seed"): add per-key seed **VALUE** inputs and recreate a live seed node on load, so operators can supply seed values for loaded workflows.
- **No dependency on Operate "F13 helper" (unbuilt).** Build the seed-key **derivation locally from the existing `seed.*`-prefix scan** — verified precedent at `runs-tab.js:343` and `main.js:7603` (both `.filter(i => i.startsWith('seed.')).map(i => i.slice(5))`), with a JSON-textarea fallback for the zero-declared case. **Offer this derivation as the shared helper Operate F13 later adopts** (inverted dependency, same pattern as the rail).
- **Ledger corrected** from "P0 BUILT — GP-1" to "refuted; rebuilt as P1 seed-value UX (GP-1)."

### P0-5 (MCP tool-ref) — MISLOCATED; normalize at the DROP HANDLER, not the emitter

**Verified.** The drop handler stores an MCP bench-drag as `mcp__${serverId}__${toolName}` (double-underscore) at `main.js:9825`; the YAML emitter routes on `ref.startsWith('mcp:')` (colon) at `main.js:7835`. `'mcp__server__tool'.startsWith('mcp:')` is **false**, so it falls into the plugin `else` branch. Emitter-only normalization would emit a bogus `plugin: "mcp.server.tool"` (no plugin named "mcp"), diverging from the canonical `mcp:server.tool`/`pid.tid` forms other consumers (`dfFetchCompanions` assist, chip renderers, detach) already read.

**Correction:** Normalize at the **drop handler** (`main.js:9822-9826`) — store canonical `mcp:server.tool` (colon + dot) and `pid.tid` when `data.tools` is written, so the existing emitter mcp branch (`:7835`) and **every** other `data.tools` consumer see one representation unchanged. **Verify with an MCP-specific round-trip** (drop MCP tool → Save → reload → ref is `mcp:server.tool`, not `plugin:mcp...`), not just "Save returns 200" (any dotted string satisfies `ToolRef`, so a plugin-only test is blind to the MCP bug). Ledger entry annotated with the refutation.

### P0-13 (exports gating) — WRONG TIER; SCOPE_MAP entry only, drop `require_master_key`

**Verified.** `SCOPE_MAP` (`middleware.py:56-68`) gates data-action routers by prefix alone (`/api/documents`:`documents`, `/api/workflows`:`workflows`, `/api/memory`:`memory`) with **zero** `require_master_key` deps; admin routers use `require_master_key`. Exports is a data-action surface (save/list/read/zip/delete of chat-session markdown). `require_master_key` demands master or `keys` scope and runs **before** scope resolution, so a legitimately `exports`-scoped SPA key (used by `POST /api/exports/save`) is rejected 401, and the co-added SCOPE_MAP entry becomes dead config. Exports is already behind base auth (not in `PUBLIC_PATHS`); only scope enforcement is missing.

**Correction:** Add **only** `"/api/exports": "exports"` to `SCOPE_MAP` (parity with `/api/documents`,`/api/workflows`) and **drop `require_master_key`** from all 5 routes. Verify: an `exports`-scoped key succeeds; a key lacking that scope 401s; the SPA save/list flow still works. Ledger annotated.

---

## Collision bindings (explicit, not advisory)

- **MS-1 DONE.** Committed 26b1260 (`/static` rate-limit exemption at `middleware.py:201` via `path.startswith(PUBLIC_PREFIXES)`, `PUBLIC_PREFIXES=("/static/",)` at `:50`; `tests/test_rate_limit_static.py` present). **Binding:** hand MS-1 to the Library build so it can drop the `RATE_LIMIT_RPM=0` workaround from its own e2e suites. Library/Operate coordination note: `middleware.py` already carries the `/static` exemption line; their diffs rebase cleanly.
- **MS-2/MS-3 next, library-independent.** Neither touches LibraryShell/Wizard; they land ahead of the library gate.
- **MS-4/MS-5 gated behind the library build.** Both share files/surfaces with the in-flight skills/models/agents rebuild (`skills.js`, skills-tab DOM, `main.js:241-243`, `#tab-agents`). Stated in the gate table, not only in prose.
- **CH-1 ↔ Operate U5/U6/U7 (runs-tab.js contention) — BINDING.** CH-1 edits `runs-tab.js` (`openInComposer` ~:1144; resume rebind `_toggleActionButtons` ~:1378/:1391) which U5 (paging), U6 (Runs UI), U7 (shared step render) restructure. **Either sequence CH-1's `runs-tab.js` edits after U5–U7 land, or carve the resume-toolbar rebind + `openInComposer` into a helper both consume.** CH-1's un-defer of Operate §10.2 (Runs→Composer) must be **signed off in Operate before CH-1 builds it** (not a floating flag).
- **CH-1 ↔ Operate U4 (Gate D dependency) — RECORDED.** Operate U4 §3.1/L118 mis-cites `dfBuildWorkflowDefinition` as already building `{definition,seed}`. That function does not exist (P0-1); **CH-1 is what defines it** (extract `dfComposeYamlString()` out of `dfExportYaml` at `main.js:7852`). **Cross-spec ordering constraint:** Operate U4's `{definition,seed}` branch depends on CH-1 landing `dfBuildWorkflowDefinition` (Gate D); amend operate-plane §3.1/L118 to cite the real function + lines, signed off.
- **CH-1 composite Fix&Resume depends on GP-1 P0-2 — REORDERED.** CH-1 hard-blocks composite kinds until P0-2 (composite load flatten) lands. Patterns/ralph/loop workflows (created in the same Gate D via PT-1) are exactly those composites. **P0-2 is pulled to the front of Gate D**, ahead of CH-1, so composite load-hydration lands before composite resume is user-visible.
- **DR-1 `dfEditor.import()` prototype-first — REQUIRED.** `.import(` has **zero call sites** in the tree (grep confirms). Drawflow `import()` replays raw exported JSON and does **not** fire `connectionCreated`/`nodeCreated`, does not re-run `dfScheduleAnchorRefresh`, and does not reconcile composite sub-DAG proxy edges. **Prove an `import()` round-trip on a ralph+seed canvas (port counts, seed dynamic anchors, `dfNextId`, composite proxy edges) BEFORE committing the design.** Restore must **hard-clear canvas + `dfNodeData` + reset `dfNextId` to the snapshot value BEFORE import**, explicitly re-invoke `dfScheduleAnchorRefresh` + seed-anchor rebuild post-import, **suppress the boot seed whenever a draft is queued**, and **assert exactly one seed node** post-restore. If `import()` proves lossy, fall back to replaying `dfAddNodeFromTemplate`/`dfScaffoldPattern` from the snapshot.
- **DR-1 draft-vs-saved identity — SINGLE SOURCE.** On publish, **freeze/delete the draft** (no dual mutable identity); the In-Progress row becomes read-only "published" or is removed. **Edit-in-Composer of a published workflow loads the SAVED definition** (`composerLoadDefinition` path), never a post-publish draft blob. The "else `composerLoadDefinition` ONCE" first-edit path of a published composite is **guarded on `step.kind`** — hard-block/warn on composite until GP-1 P0-2 lands (mirror CH-1's block), so the P0-2 flatten risk is not silent in Gate C.
- **CP-1 ↔ Operate U1 exclusion list — EXTENDED.** CP-1 edits `library/workflow-index.js` (`WorkflowIndex.render` export + `#wfi-search` recursion fix) and `core/shortcuts.js` (keymap), **both owned by Operate U1** ("WorkflowIndex/deepDive symbols unchanged; `#wfi-*` ids unchanged"). **Add `workflow-index.js` and `core/shortcuts.js` to CP-1's Operate-coordination exclusion/sequencing list:** sequence CP-1 after U1, or move the `WorkflowIndex.render` export + `#wfi-search` fix into U1's scope. The `g`-chord map has a single owner.
- **RX-2 workspace writes gated — BINDING.** `PUT /api/workspaces/{name}/file` (`workspaces.py:151`) carries **no `require_master_key`** and `/api/workspaces` is **absent from SCOPE_MAP** (verified). RX-2's note/source writes are currently ungated, violating "gating on writes." **Add `/api/workspaces` to SCOPE_MAP (`"workspaces"` entry), or master-key on the write verbs (`PUT /{name}/file`, `POST /{name}/edit`, `POST /{name}/expand`, `POST`/`DELETE`).** Flag as a cross-build contract with Operate U11 (which also writes this workspace).

---

## GP-2 commit split (7 coherent commits, not one mega-commit)

The prior GP-2 rode one `fix(security): …` message across ~10 files / 7 unrelated concerns (the message didn't even mention agent-lifecycle, XSS, or mark-failed). Split:

1. **`fix(security): gate exports via SCOPE_MAP exports entry`** — add `"/api/exports":"exports"` to `middleware.py:56-68`; drop `require_master_key` from `exports.py` routes (P0-13 corrected).
2. **`fix(setup): trust loopback only for local-license handout`** — `setup.py:32-40` `_is_local_client` uses `ipaddress.ip_address(host).is_private` (guard the literal `"localhost"` → ValueError), refuse when a forwarding header (`X-Forwarded-For`/`Forwarded`/`X-Real-IP`) is present; preserve the Docker-bridge parity path (P0-14).
3. **`fix(prompts): layered user-shadows-oob role resolution at run time`** — `prompt_composer.py` additive arg + shared resolver (P0-9, Blocker 1; engine byte-clean).
4. **`fix(storage): atomic agent + workflow saves`** — tmp+`os.replace` for `agent_service.py:118` and `workflows.py:319`.
5. **`fix(agents): fork carries tools/context/temp/max; chat executes via /v1`** — `dfAddNodeFromAgent` maps `AgentTool`→`ToolRef` + copies context/temp/max; route `/api/agents/{id}/chat` through `/v1` (execute tools, honor `web_search`, OpenAI-shaped errors); refresh `#agent-select` after edit/delete; save-as-agent PUT branch; `ResearchFlow` reads `result.draft` + checks `res.ok`.
6. **`fix(xss): escAttr/safeUrl on untrusted attribute+href sinks`** — add `escAttr()`+`safeUrl()` to `core/dom.js`; apply **only** to the ~dozen untrusted attribute/href sinks (do NOT churn the 939 `esc()` calls).
7. **`fix(runs): persist mark-failed + config-integrity None-vs-empty`** — NEW `POST /api/runs/{id}/mark-failed` persists `run.json=failed`; config-integrity None-vs-empty (allowlist resurrection, token clear, wire-or-hide `catalog_urls`).

---

## Dedupe / routing (Operate + Library)

- **Route, don't fork, to Operate.** CH-1 `next.schedule`→U8, `next.promote`→U11/U14; RX-2 store is ONE `research` workspace via existing `/api/workspaces` CRUD (U11 lists it — amendment above); RX-2 graph rail is the **canonical shared `shell/context-node-rail.js`** (U14 consumes — amendment above); CH-1 `GET /{id}/runs` **defines the read-model seam U5 adopts** (U5's spec amends to consume this endpoint rather than re-implement `/runs`).
- **Sequence library-coupled units after the Library gate.** MS-4/MS-5 reuse LibraryShell/Wizard/TestPane; PT-1 clones LB6 Tasks-kind + `prompts.py` CRUD; PB-1 reuses `/api/prompts` verbatim.
- **MS-5 vs Library f/u #1.** MS-5 delivers the Agents **grammar migration only** (TestPane/provenance/re-sync/runtime execution stay OUT — frozen engine, Library f/u #2). **Rescope Library f/u #1 to "TestPane adapter + CatalogPage agent-tile dedup only — grammar migration delivered by MS-5."** Fold the CatalogPage agent-tile dedup into MS-5 or explicitly defer it (note so agents aren't shown two ways in the interim).

---

## Gap ledger — full disposition (58 findings)

**P0 (24) — BUILT / corrected / done:** P0-12 rate-limit (**DONE**, MS-1); MS-2 overlay+tab-wrap; P0-7 capture 422 + P0-8 RAG dead-code (MS-3); Skills double-discovery + Agents-not-migrated (MS-4/MS-5); R1/R2/R3 + P0-15 research dead-end (RX-1); R4/R5 sources+graph + R6 store (RX-2); P0-3/C2 drafts (DR-1); C1 prompts bench (PB-1); C3 patterns (PT-1); P0-1 live serializer + P0-11 resume + C4 chaining + J5/J10 return edge (CH-1); P0-2 composite load flatten + P0-4 model pins + **P0-5 (corrected: drop-handler)** + P0-10 chat dead-end (GP-1); **P0-6 (REFUTED → P1 seed-value UX, GP-1)**; P0-9 layered prompts (GP-2, `prompt_composer.py`); **P0-13 (corrected: SCOPE_MAP only)** + P0-14 local-client (GP-2).

**P1 (~20) — BUILT / deferred:** agent fork/chat/lifecycle (GP-2); `#wfi-search` recursion (CP-1); seed per-key values (GP-1); capture-buttons surfaced (MS-3/RX); `catalog_urls`/allowlist/token None-vs-empty (GP-2); zombie mark-failed persist (GP-2); `esc()` XSS → escAttr/safeUrl (GP-2); zero-model preflight + no-models banner (CP-1); atomic saves (GP-2); discovery false-success toasts + one Discover verb (MS-4 + CP-1); workbench empty/error/auth + admin pre-gate locks (CP-1); shell structural + stale copy + native confirm/prompt (CP-1); op-path false Save-done (CP-1); keymap dupes + chords (CP-1, coordinate with U1); dirty indicator + Ctrl-S + beforeunload (DR-1 + CP-1). **DEFERRED P1s:** test-in-chat seed/composite 400-guard → **committed as a hard CP-1 deliverable** (see below); AgentTuning honest-toast (CP-1 sweep; runtime injection out of scope, frozen engine); Runs zero-state CTA → Operate U5/U6 own `runs-tab.js` (hand off or 2-line CTA only if CP-1 lands first). **QUEUED:** deep-dive-into-hidden-Context-tab + docs 503 → Operate U13/U14.

**P2 (~11) — DEFERRED (named):** round-trip fidelity (`_from_agent`/Import-YAML/category-tags/`prompt.*` — partially Operate U11 sentinel); power-user undo/redo/multi-select/full-palette (CP-1 ships minimal Cmd-K + Escape guard; Projects bulk = Operate U3/U12); knowledge-loop bridges; agent-by-reference re-sync (**WONT-FIX this branch** — frozen engine, Library f/u #2); data-substrate refcount/migration/backup; accessibility cluster (CP-1 removes nav-label `aria-hidden` as a down-payment); distribution `.app`/codesign/reachability; admin-observability (a2a default drift worth pulling into GP-2 commit 7 if budget); Projects delete/rename/reorder/assignee (flag for Operate U2/U3 scope amendment); tool-io capture drill-down (**WONT-FIX** — composer f/u #3).

**DEDUPE rows:** Library-covered (LB6 Tasks, LB5 forge, Agents f/u #1/#2, model-pull, hooks attach) — do not rebuild; MS-5 delivers Agents grammar-only. Operate-covered (scheduler U4/U8, Artifacts/Workspaces U10/U11, context rail U13/U14, run index U5/U6, shared render U7, Projects U2/U3/U12, Workflows nav U1, docs 503 U13) — CH-1/RX route, do not fork.

---

## Build units (revised)

Format: **name — deliverables · files · verify · commit (≤72 chars)**. Gate A's MS-1 shown for completeness (DONE).

### Gate A — MAKE-IT-STICK

**MS-1 — Rate-limit static-asset exemption — ✅ DONE (committed 26b1260).**
Exempts `/static/` from `RateLimitMiddleware` (`middleware.py:201` `path.startswith(PUBLIC_PREFIXES)`). `tests/test_rate_limit_static.py` green. Hand to Library build to retire `RATE_LIMIT_RPM=0`.

**MS-2 — Composer canvas state fixes (empty-overlay + Patterns tab row).**
- Clear `#composer-canvas-empty` on manual adds: call `ComposerView.updateCanvasEmptyState()` at the drop-handler tail (~`main.js:5686`), in `composerAddAgentAtCenter` (~5693), and `dfAddSeedNode` (~6471); gate on **real-step count** so the boot seed doesn't falsely count as has-nodes; wrap in try/catch.
- Keep six bench tabs on one row: `.workbench-tabs` `flex-wrap:nowrap` + `overflow-x:auto` with a thin persistent scrollbar/fade; tighten `.workbench-tab` padding.
- Files: `main.js:5646-5700,6471`; `workspace-legacy/composer-view.js:28`; `css/app.css:5700`.
- Verify: after `dfAddNodeFromTemplate`, overlay `display:none` + panel `has-nodes`; at 1600px all six tabs share one `offsetTop`; add `test_composer_canvas_state.py` + assertions in `test_composer_patterns.py`.
- Commit: `fix(composer): clear empty overlay on add and keep bench tabs single-row`

**MS-3 — Research capture 422 + RAG ingest wire (shared seam).**
- Fix `ResearchArtifacts.captureRaw` (the ONE path Research + Operate U14 promote call): truncate title ≤200 at a word boundary (hard `slice(0,200)` fallback), full text in body, sentinel `(no synthesis was generated for this angle)` for empty body AND disable promote when body empty.
- NEW `api/services/rag_ingest.py::ingest_markdown` importing the **`documents.py` DocumentService singleton** function-local, None-guarded (fixes `feedback.py:147` dead code — `hasattr(module,'upload')` always False); `capture_artifact` calls it; set `rag_ingested` truthfully; graceful no-op when backend down; server-side clamp.
- Surface the 0.55rem capture buttons hidden in collapsed `<details>` into an action row (feeds RX-2).
- Files: `runs/research-artifacts.js:14,33-47`; `services/rag_ingest.py` (NEW); `routers/feedback.py:116-117,147-158`.
- Verify: `POST /api/feedback/artifacts` with 250-char title + empty body both return 200; `rag_ingested=True` when backend up, markdown still written when down; extend `test_feedback.py`; reproduce-then-confirm the live 422 gone.
- Commit: `fix(research): fix capture 422 truncation and wire real RAG ingest`

**MS-4 — Library skills/models discovery normalize + toolbar data-action (after library gate).**
- Skills dual-discovery collapse: stop `SkillsDiscoverShare.showInSkillsTab()+load()` on admin-skills activation (`main.js:241-243`) so the shell Discovered tab owns discovery; keep `#skills-tab-discover-mount` alive (Catalog `showInCatalog` untouched); delete legacy `#skills-filter-plugin/role` selects + `skills.js:107-108` reads.
- Models: keep the deliberate Installed-Locally memory-residency panel; only normalize its handler grammar.
- Migrate remaining inline `onclick` toolbars to `data-action` (MCP `index.html:2733-2735`, Plugins `:2550`, Models Installed-Locally `:1334`); keep window globals for parity.
- Fix false-success discovery toasts (early-return on non-ok/exception in `plugins.refresh-digest`, `skills.refresh-discovery`).
- Files: `index.html:2582,2589,2593,2733-2735,2550,1334`; `main.js:195,241-243`; `library/skills.js:107-108,516-534`; `library/plugins.js:763-780`.
- Verify: Skills tab renders ONE discovery surface + ONE filter; `#skills-tab-discover-mount` empty on admin-skills, populated on Catalog home; toolbars fire delegated; failed refresh shows no success toast; `test_skills_shell.py` green.
- Commit: `fix(library): single skills discovery surface, delegate toolbar actions`

**MS-5 — Agents LibraryShell grammar migration (complaint #1, after library gate).**
- Migrate `#tab-agents` onto the adapter contract: replace card grid + inline chat panel + `--cyan` + inline `on*` with the shell two-pane skeleton (`#agents-list` `rowClass:'agent-card'`, `#agents-detail`) adopting `.lib-row/.lib-side-tab/.lib-filter`.
- Add an Agents adapter (`kind:'agent'`, list `GET /api/agents`, detail `/{id}`, actions Chat/Edit→AgentGen/Delete Confirm-gated); re-point `loadAgentsTab` (8224), `openAgentChat` (8294), `showEditAgentModal` (8592), `deleteAgent` (8465), `_saveAgentModal` (8760) as callbacks; agent chat moves into the detail chat slot; `+New`/refresh → `agents.new`/`agents.refresh`.
- Grammar-only: TestPane/provenance/re-sync/runtime execution OUT (frozen engine, Library f/u #2); no backend change. **Pre-authorized only-add exception** (markup replacement, parity-snapshot delta pre-approved). Fold or defer CatalogPage agent-tile dedup with a note.
- Files: `index.html:2474-2505`; `library/agents.js`; `main.js:8224,8294,8465,8592,8760`; `library/shell.js` (reuse).
- Verify: `test_agents_shell.py` — uniform `.lib-row` list + subnav detail + Confirm-gated delete; create/edit round-trips through the Wizard; agent chat still sends; visual parity with the other six kinds.
- Commit: `feat(library): migrate Agents tab onto LibraryShell grammar`

### Gate B — RESEARCH

**RX-1 — Research session, dynamic chat, two-column reading layout.**
- NEW `research_session.py` (`data/research/sessions/<id>.json`, atomic, `{topic,model,source_ids,turns,moc_path}`); deep-dive gains optional `session_id`, mints session + writes session MOC into the `research` workspace, returns `session_id`.
- `POST /api/research/followup {session_id,question,web_search?}`: loads prior synthesis + saved sources, RAG-grounds over Chroma, optional operator-initiated search (**`web_search` OFF by default**), `ollama.chat` answer, appends turn + MOC; turns optionally mirrored to `ConversationStore kind:'research'`.
- `#tab-research` two columns: LEFT `#research-thread` (turns + sticky `#research-followup-input`, `data-action research.followup`); RIGHT `#research-surface` full-width reading view (`renderMarkdown`, no letterbox) + per-sub-question source cards; follow-ups append as reading cards.
- Files: `routers/research.py` (NEW); `services/research_session.py` (NEW); `routers/graph.py` (session_id shim); `main.js`; `index.html`; `css/app.css`.
- Verify: `test_research_session.py` (mint/persist/followup/MOC); `test_research_flow.py` (follow-up appends a turn + grounded reading card); `web_search` OFF by default, no background egress.
- Commit: `feat(research): stateful session, dynamic follow-up chat, reading layout`

**RX-2 — Actionable results + Obsidian RAG store + exploratory graph rail (owns the shared rail).**
- Per-source/per-result `.lib-actions-row` (`data-action`, no inline): `research.promote-artifact` (fixed `captureRaw`), `research.save-source` (`PUT /api/workspaces/research/file` → `sources/<slug>.md` + `ingest_markdown`), `research.cite` (`[[source:<slug>]]` into follow-up input).
- ONE `research` workspace = the Obsidian-like store (DEDUPE): idempotently ensure workspace `research` via existing `/api/workspaces` CRUD (`allowed_extensions:['md']`); tree `sessions/`+`sources/`+`notes/`; every note `ingest_markdown`'d; browsable `research/research-store.js` file-tree reusing the LB3 `.skills-tree` grammar with markdown preview (Store subnav).
- Graph rail: land the **canonical shared `api/static/js/shell/context-node-rail.js`** (Blocker 2), pane-guard declared once; `research/research-node-rail.js` registers `kind:'research-node'` (`auth:'optional'`) into it; verbs `research.node-read`, `research.compare-node` (`POST /compare-node`: fresh search + `ollama` structured comparison), `research.build-upon`; `research.graph-walk` (`POST /graph-walk`: resumable workspace worklist, compare per node, MOC report).
- **Gating:** add `/api/workspaces` to `SCOPE_MAP` (`"workspaces"`) or master-key the write verbs (Blocker binding). **Pin `research` slug**; Operate U11 amendment.
- Files: `routers/research.py` (compare-node, graph-walk); `main.js`; `research/research-store.js` (NEW); `research/research-node-rail.js` (NEW); `shell/context-node-rail.js` (NEW, canonical); `index.html`; `css/app.css`.
- Verify: `test_research_flow.py` — save-source writes note + ingests (`rag_ingested True`), store tree renders+previews, node-rail compare returns structured sections, graph-walk resumes via `/index/{name}/next`; pane-guard so Research clicks never drive the Context rail; workspace writes 401 without the `workspaces` scope; egress operator-initiated only.
- Commit: `feat(research): actionable results, Obsidian RAG store, shared node rail`

### Gate C — DRAFTS

**DR-1 — Composer draft store, identity, In-Progress tab, restore-on-open (prototype-first).**
- **PROTOTYPE-FIRST (blocking):** prove `dfEditor.import()` round-trip on a ralph+seed canvas (ports, seed anchors, `dfNextId`, composite proxy edges) before committing; if lossy, replay `dfAddNodeFromTemplate`/`dfScaffoldPattern` from the snapshot instead.
- Workflow identity: mint `draft_id` (uuid4 hex) **synchronously at canvas-dirty t0** (before any autosave), distinct from `workflow_id`; persist the lossless snapshot (`dfEditor.export()`+`dfNodeData`+`dfNextId`+`dfSeedSchema`+`meta` — let `export()` own zoom/pan, don't double-restore) as an opaque blob; restore **hard-clears canvas+`dfNodeData`+resets `dfNextId` to snapshot BEFORE import**, re-invokes `dfScheduleAnchorRefresh`+seed rebuild, **suppresses the boot seed when a draft is queued**, asserts exactly one seed.
- Server store `composer_draft_store.py` (atomic tmp+`os.replace`, filename-safe id + `relative_to`, ~2MB cap, NO engine validation) + localStorage WAL (debounced ~4s flush, beforeunload guard, reconciliation by `updated_at`; add a per-draft tab lock — BroadcastChannel/localStorage — to avoid two-tab clobber); draft CRUD on `composer.py`, writes gated.
- 'In Progress' 5th workstream pane (`data-action ws.switch`): rows (name, step count, dirty/last-saved, last-run dot); `drafts.open/rename/duplicate/delete` + `drafts.new`.
- **Single source after publish:** publish (`dfSave` 7779) relinks `workflow_id` and **freezes/deletes the draft** (no dual mutable identity); Edit-in-Composer of a **published** workflow loads the SAVED definition. First-edit `else composerLoadDefinition ONCE` path is **guarded on `step.kind`** — block/warn on composite until GP-1 P0-2 lands.
- Files: `routers/composer.py`; `services/composer_draft_store.py` (NEW); `main.js`; `workspace-legacy/composer-workstream.js`; `workspace-legacy/composer-view.js`; `index.html`.
- Verify: build ralph canvas → autosave → F5 → restored losslessly (connections/pos/composite config, exactly one seed); publish relinks + freezes draft; In-Progress CRUD; byte-for-byte on the no-draft path; `import()` fidelity proven on a composite.
- Commit: `feat(composer): durable draft store, workflow identity, In-Progress tab`

### Gate D — COMPOSER CAPABILITY (P0-2 first)

**GP-1a — Composite load hydration (P0-2, pulled to front of Gate D).**
- Branch `composerLoadDefinition` (`main.js:10102`) on `step.kind`; restore `data.kind` + composite config (body/branches/until/ralph/gather) via the scaffold-inverse (reuse `dfScaffoldPattern` 6305 / `dfAddPatternFromTemplate` 6286 primitives; children carrying `_sub_of` avoid top-level re-serialization).
- Gate = 24 `test_pattern_presets.py` round-trips; a ralph workflow survives save→reload→save. Unblocks CH-1 composite Fix&Resume + DR-1 first-edit + PT-1 editing.
- Files: `main.js:10102`. Engine untouched.
- Commit: `fix(composer): hydrate composite step kinds on workflow load`

**PB-1 — Composer Prompts palette bench.**
- Prompts as a 7th palette bench: tab `data-action bench.switch` (reuse 9627), cards `bench.drag` + hover inspect (new `application/df-prompt` branch in `_benchCapResolve` + `cap.kind==='prompt'` inspector branch).
- Drop-to-node: extend `wireWorkbenchDropHandlers` (9800) to read `application/df-prompt` → `dfAttachPromptToNode` setting `data.system_prompt` + `data._from_prompt`, commit via `dfUpdateNodeData({commit:true})`. Attach inlines the **RESOLVED text into `system_prompt` NOT `role_ref`** (point-in-time snapshot identical to the Agents fork; dodges even the now-fixed oob resolution).
- **Node-config prompt picker** (the second half of C1): a selector inside `dfRenderConfigPanel` reusing `GET /api/prompts` + the same `dfAttachPromptToNode` seam — OR explicitly deferred with rationale (choose at build; honest C1 coverage either way).
- Guards: llm-only drop (toast+bail on seed/composite); manual textarea edit clears `data._from_prompt`; hooks excluded; reuse existing `/api/prompts` + `/{kind}/{id}` + `/render`, no new route. **Re-assert the MS-2 single-row/overflow invariant at 7 benches (1600px).**
- Files: `index.html`; `main.js:9693,9800`; `workspace-legacy/composer-workstream.js:143`; `css/app.css`.
- Verify: drag a role onto an llm node → `data.system_prompt` + provenance chip; `dfExportYaml` serializes it; drop onto seed/composite toasts+bails; edit clears the chip; 7 tabs stay single-row.
- Commit: `feat(composer): add Prompts palette bench with drag-attach to nodes`

**PT-1 — Patterns drill-down inspector + Patterns library kind.**
- Drill-down: `dfRenderPatternStructure(tpl)` shared renderer (node list, ASCII wiring, config defaults incl. ralph.halt/budget/until.gate/seed.* inputs, provenance); card gains `bench.inspect-pattern` + `data-inspect-key` next to `bench.inspect-template` (9756), paints into `#df-config-panel` with node-selection-wins guard.
- Patterns LibraryShell kind: NEW `routers/patterns.py` mirroring `tasks.py`+`prompts.py` (oob `patterns_catalog.json` + user layer, merge/shadow, copy-on-write PATCH, 403 pure-oob DELETE, 409 dup, promote); **SAFETY RAIL:** every stored pattern round-trips `WorkflowDefinition(**...)` → 422 on un-scaffoldable DAG; path-containment + atomic + gated; `deployment.ensure_dirs` adds `patterns/`.
- `library/patterns.js` adapter (tasks.js clone): overview=`dfRenderPatternStructure`, source=JSON editor, actions Edit/Promote/Delete(disabled builtin)/Send-to-Composer; statics-untouched invariant.
- Bench feed: `fetchComposerPatterns()` appends user patterns after the 8 statics; resolver consults statics THEN `dfUserPatterns` (fail-soft); `composer.save-as-pattern` collects canvas via `_dfCleanStep`, `Confirm.ask`, `POST /api/patterns`.
- Files: `routers/patterns.py` (NEW); `main.py`; `config/patterns_catalog.json` (NEW); `services/deployment.py:164`; `library/patterns.js` (NEW); `index.html`; `main.js`.
- Verify: `test_patterns.py` (CRUD/403/409/reverted_to_oob/promote/path-containment/422-invalid-DAG); `test_patterns_shell.py`; extend `test_pattern_presets.py` (catalog==statics AND user shapes round-trip); bench inspect paints without opening the popup.
- Commit: `feat(patterns): drill-down inspector and first-class Patterns library kind`

**CH-1 — Iteration-chaining grammar: NextActions, round-trips, resume-from-failed, live serializer.**
- ONE `NextActions.render` component (`shell/next-actions.js`): persist-until-next-event `data-action next.*` strip after `run.finished.ok/failed`, `run.awaiting_gate`, `save.ok`; `research.done`+`chat.crystallized` rows declared as hooks for RX/GP-1.
- Live serializer: extract `dfComposeYamlString()` out of `dfExportYaml` (7852) minus the panel side-effect; `dfBuildWorkflowDefinition = jsyaml.load(dfComposeYamlString())` so `dfRunWorkflowLive` sends the live canvas (P0-1); correct the lying tooltip (`index.html:673`).
- Three pivots: `RunsTab.openInComposer(wfId,stepId)` wired `runs.open-in-composer` (un-defers Operate §10.2 — **signed off first**); `#df-run-progress`→`composer.open-active-run` (survives reload); `composerLoadById` fires `GET /api/workflows/{id}/runs` → last-run health chip + scoped History (`ws.history-open`).
- `POST /runs/{id}/resume-from-failed` (add-only, modeled on `resolve_approval` 735-811: flip status='running' then `engine._checkpoint`+`engine.resume`; 404/409-unless-failed, `model_validate`); **HARD-BLOCK composites until GP-1a P0-2 lands** (now same gate, ahead), default `definition=None` for plain-llm; fix inverted resume button + delete false toast; `GET /{workflow_id}/runs` read-model (**the seam Operate U5 adopts**).
- `dfApplyRunState` mounts NextActions on terminal-failed + awaiting_approval; `composerNewWorkflow` calls `clearRun+stopPolling`; route `next.promote`→U11/U14, `next.schedule`→U8.
- **Coordination:** sequence `runs-tab.js` edits after Operate U5–U7, or carve the resume-toolbar/`openInComposer` helper both consume (binding above).
- Files: `shell/next-actions.js` (NEW); `main.js:7766-7853,5808,10059,10086,10276`; `runs/runs-tab.js:1144,1378,1391`; `workspace-legacy/composer-workstream.js`; `index.html:673,806`; `routers/workflows.py`.
- Verify: failed run → chip 'Fix failing step' opens canvas at the step → edit → Save → 'Resume from failure' resumes at the failed step with earlier outputs preserved; Run›live sends the live canvas; composite Fix&Resume works (P0-2 landed same gate); engine untouched.
- Commit: `feat(composer): NextActions strip, round-trip pivots, resume-from-failed`

### Gate E — RESIDUAL GAP FIXES

**GP-1b — Serializer fidelity + launch residue (P0-4, P0-5 corrected, P0-6 re-scoped, P0-10).**
- P0-4 model-pin loss: emit `model` + StepConfig `temperature`/`max_tokens` in the llm branch (7744); restore in `composerLoadDefinition`; add temp/max inputs to `dfRenderConfigPanel` (6947). Engine untouched (fields already exist + engine-honored).
- **P0-5 (corrected):** normalize at the **drop handler** — store canonical `mcp:server.tool`/`pid.tid` in `data.tools` (main.js:9822-9826) so every consumer + the existing emitter mcp branch work unchanged. MCP round-trip assertion, not just Save=200.
- **P0-6 (re-scoped P1):** per-key seed VALUE inputs + recreate a live seed node on load; seed-key derivation from the local `seed.*`-prefix scan (`runs-tab.js:343`/`main.js:7603`) with JSON-textarea fallback. No 422 framing. No Operate F13 dependency.
- P0-10 chat crystallize dead-end: `switchTab('dashboard')` in `BootSequence.dispatch` before render; unskip `test_composer_chat_led.py`.
- Files: `main.js:10102,7744,6947,7749-7760,10217,9822-9826`; `library/workflow-index.js:363`; `workspace-legacy/boot-sequence.js:51-101`; `tests/playwright/test_composer_chat_led.py`.
- Verify: load-then-save preserves model pins; bench-drag MCP tool round-trips to `mcp:server.tool` + Save 200; `wfi.run` on a seed workflow shows editable seed values + succeeds; chat 'run with my agents' reaches confirm on the visible tab.
- Commit: `fix(composer): model/tool serialization, seed-value UX, chat dead-end`

**GP-2 — Security + integrity + runtime-resolution (7 commits, ZERO engine touches).** See the GP-2 commit-split section. Files: `middleware.py:56-68`; `exports.py`; `setup.py:32-40`; `prompt_composer.py` (P0-9, replaces the frozen-engine touch); `agent_service.py:118,249-266`; `agents.py:94-207`; `workflows.py:319`; `main.js:5719,11106,1013,9773`; `core/dom.js:6`; `agentic_discovery.py:117-181`; NEW `POST /api/runs/{id}/mark-failed`.
Verify: edited/promoted role changes an actual run's rendered prompt (fresh composer per request); exports scoped-key succeeds / unscoped 401s / SPA save works; local-license refused for proxied/`172.5.x`/X-Forwarded clients, loopback allowed; agent/workflow save survives mid-write crash; agent fork carries tools/context; agent-chat executes `web_search`; escAttr/safeUrl scoped to untrusted sinks only.

### Gate F — POLISH (CP-1, 3 commits)

**CP-1a — Consistency sweep.** Dead-control honesty (`composerTestStepInChat switchTab('chat')` + **hard `is_seed`/`kind` render-time guard** so the newly-reachable control never 400s on seed/composite — committed, not budget-gated); `dfRunWorkflowLive` tooltip truth; workbench empty/loading/error/auth via `EmptyState`/`ErrorPanel`/`Skeleton` + wire `renderWorkbenchAuthHint` on 401; one '⟳ Discover' verb across 5 tabs; admin auth-gate parity (CloudPanel/ExportsPanel pre-gate lock, `ApiKeysPanel.showCreate` try/catch); shell structural (`WorkflowIndex.render` export + `#wfi-search` recursion — **coordinate/sequence after Operate U1**; exempt `documents` in `router.js` guard; footer `target=_blank`; malformed `<header>` close; cut dead breadcrumb CSS; remove nav-label `aria-hidden`; stale-copy sweep; native confirm/prompt → `Confirm.ask`). **Pre-authorized only-add exception** for the markup deletions.
Commit: `polish(shell): consistency, dead-control honesty, structural fixes`

**CP-1b — Onboarding / first-run.** op-path Stage-4 reads a localStorage authored flag (set in `dfSave`) — fix the false Save✓ on virgin installs; empty-canvas overlay → live 3-step checklist; zero-model preflight (`window._chatModels`) before Run + starter toast; first-success handoff toast; dismissible 'no models' banner.
Commit: `polish(onboarding): op-path authored flag, zero-model preflight, banners`

**CP-1c — Power-user keymap/shortcuts.** Keymap fix (kill `g r`/`g c` dupe, add `g c`→Context + `g t/g j/g o/g b` — **coordinate `g`-chords with Operate U1, single owner**); composer-scoped 1–7 bench + `[`/`]` workstream keys; Ctrl/Cmd-S→`dfSave` + `beforeunload` reading DR-1's dirty flag; minimal Cmd-K keymap filter; Escape modal-stack cheap `defaultPrevented` guard; migrate inline `onkeydown=dfAddTool/dfAddSkill` (7005-7008) to `data-action`.
Files (CP-1 whole): `main.js:1251,9430-9582,10417,10514,7005-7008`; `workspace-legacy/composer-view.js`; `library/workflow-index.js`; `shell/router.js:20`; `admin/{cloud,exports,api-keys}.js`; `core/shortcuts.js:5-22`; `index.html`; `css/app.css`.
Commit: `polish(shortcuts): non-conflicting keymap, Ctrl-S, Cmd-K, Escape guard`

---

## Critique resolutions (all 40)

### feasibility-collision (18)

| # | Sev | Issue | Resolution |
|---|-----|-------|-----------|
| 1 | major | GP-2 P0-9 touches frozen `workflow_engine.py` | **Blocker 1** — moved entirely into `prompt_composer.py` (additive arg + shared resolver, per-layer containment); engine byte-clean. |
| 2 | major | Gate A "first" vs MS-4/5 "after library gate" | Gate split: MS-1(done)/MS-2/MS-3 library-independent first; MS-4/MS-5 gated behind library build — stated in the gate table. |
| 3 | major | RX-2 forks Operate U14 rail | **Blocker 2** — RX-2 owns canonical `shell/context-node-rail.js`; U14 amends to consume. |
| 4 | major | CH-1 `/runs` read-model forks Operate U5 | CH-1 defines the read-model **seam U5 adopts**; amendment recorded. |
| 5 | major | GP-1 P0-6 "reuse Operate F13" phantom | Build derivation locally from `seed.*`-prefix scan; offer as the helper F13 adopts. |
| 6 | major | GP-1 P0-6 non-gap (no 422) | **Refuted-P0 correction** — 422 framing dropped, re-scoped to P1 seed-value UX. |
| 7 | major | GP-1 P0-5 emitter-only fix wrong | **Refuted-P0 correction** — normalize at drop handler to canonical `mcp:server.tool`/`pid.tid`. |
| 8 | major | GP-2 P0-13 mis-tiered | **Refuted-P0 correction** — SCOPE_MAP `"/api/exports":"exports"` only; drop `require_master_key`. |
| 9 | major | DR-1 `dfEditor.import()` unproven | **Prototype-first** blocking note; re-invoke anchor refresh; fallback to replay. |
| 10 | major | DR-1 draft-vs-saved dual identity | Freeze/delete draft on publish; Edit-in-Composer of published loads SAVED. |
| 11 | major | DR-1 restore vs boot-seed collision | Hard-clear canvas+`dfNodeData`+reset `dfNextId` before import; suppress boot seed when draft queued; assert one seed. |
| 12 | major | RX-2 workspace writes ungated | Add `/api/workspaces` to SCOPE_MAP (or master-key writes); cross-contract with U11. |
| 13 | minor | U11 workspace-name only a prose note | Pin `research` slug constant + explicit U11 scope-amendment line. |
| 14 | minor | only-add churn (MS-5, CP-1) | Named as sanctioned exceptions; parity-snapshot deltas pre-authorized. |
| 15 | minor | "two engine touches" count mismatch | Reconciled to **zero** engine touches; wording retired. |
| 16 | minor | DR-1 autosave race / two-tab clobber | Mint `draft_id` synchronously at t0; per-draft tab lock (BroadcastChannel/localStorage). |
| 17 | minor | DR-1 redundant zoom/view snapshot | `export()` owns zoom/pan; keep only `dfSeedSchema`+`meta`. |
| 18 | minor | MS-1 vs Library/Operate middleware lines | MS-1 landed first; coordination note — later diffs rebase onto the `/static` exemption. |

### completeness-experience (8)

| # | Sev | Issue | Resolution |
|---|-----|-------|-----------|
| 19 | major | P0-5 ships refuted emitter fix | Drop-handler normalization + MCP round-trip assertion; ledger annotated. |
| 20 | major | P0-6 YAGNI + ledger dishonesty | Re-scoped to P1 seed-value UX; ledger corrected from "P0 BUILT" to "refuted → P1". |
| 21 | major | P0-13 over-gates SPA save | SCOPE_MAP-only fix; verify SPA save still works; ledger annotated. |
| 22 | major | CH-1 composite Fix&Resume vs P0-2 gate lag | **P0-2 (GP-1a) pulled to front of Gate D**, ahead of CH-1. |
| 23 | minor | DR-1 first-load composite flatten (P0-2 exposure) | Guard the `else composerLoadDefinition ONCE` branch on `step.kind` until P0-2; noted in DR-1. |
| 24 | minor | PB-1 node-config prompt picker dropped | Added to PB-1 (config-panel picker reusing `dfAttachPromptToNode`) or explicitly deferred with rationale. |
| 25 | minor | CP-1 budget-gated dead control | test-in-chat seed/composite render-time guard **committed as hard CP-1a deliverable**; Runs zero-state CTA decoupled → Operate. |
| 26 | — | (bundled: PB-1 tab-wrap regression) | PB-1 re-asserts MS-2 single-row invariant at 7 benches (also #38). |

### coherence-program (16)

| # | Sev | Issue | Resolution |
|---|-----|-------|-----------|
| 27 | blocker | GP-2 P0-9 frozen-engine invariant | **Blocker 1** — `prompt_composer.py` only; count reconciled to zero. |
| 28 | blocker | RX-2 vs U14 rail ownership | **Blocker 2** — canonical `shell/context-node-rail.js`; pane-guard declared once; U14 consumes. |
| 29 | major | MS-1 blanket "after library gate" wrong | Scoped to library-coupled units; MS-1/2/3 land independently; MS-1 handed to Library build. |
| 30 | major | CH-1 vs U5/U6/U7 runs-tab.js contention | Binding: sequence after U5–U7 or carve shared helper; §10.2 un-defer signed off in Operate first. |
| 31 | major | CP-1 Operate-exclusion incomplete | Add `workflow-index.js` + `core/shortcuts.js`; sequence after U1 or move `WorkflowIndex.render`/`#wfi-search` into U1. |
| 32 | major | GP-2 mega-commit | Split into 7 coherent commits (see GP-2 split). |
| 33 | major | GP-1 P0-6 premise + unbuilt dep | Re-scoped P1; local derivation, no Operate F13 dependency. |
| 34 | major | GP-2 P0-13 wrong tier / parity | SCOPE_MAP-only. |
| 35 | major | GP-1 P0-5 mislocated | Drop-handler canonicalization. |
| 36 | major | CH-1 → Operate U4 cross-spec dep | Ordering constraint recorded: U4 `{definition,seed}` branch depends on CH-1 (Gate D); amend U4 §3.1/L118, sign off. |
| 37 | major | RX-2 silently amends approved U11 | Formal U11 amendment (reserve/list `research` + preset-launch), signed off; slug pinned both specs. |
| 38 | minor | CP-1 commit boundary | Split into CP-1a/b/c (consistency / onboarding / power-user). |
| 39 | minor | PB-1 reintroduces MS-2 tab-wrap | PB-1 deliverable re-asserts single-row/overflow at 7 benches; "7th bench" wording reconciled. |
| 40 | minor | MS-5 vs Library f/u #1 overlap | Rescope f/u #1 to TestPane + CatalogPage dedup only; MS-5 delivers grammar; fold/defer tile-dedup with a note. |
| — | minor | Gate B Operate-coupling front-loaded | RX-1 self-contained stays Gate B; RX-2's Operate-coupled parts land with pinned amendments (U11/U14) signed off before ship, else sequence behind Operate. |

---

## Deferred (named, not built)

Agent TestPane/provenance/re-sync/agent-by-reference (frozen engine, Library f/u #2 — WONT-FIX this branch); tool-io capture drill-down (composer f/u #3 — WONT-FIX); Escape overlay full ModalStack (CP-1 ships cheap guard); full fuzzy command palette (CP-1 ships minimal filter); wholesale grandfathered inline→`data-action` migration (parity-pinned); accessibility cluster (canvas has no accessible representation — CP-1 removes nav-label `aria-hidden` as a down-payment); distribution `.app` codesign/notarize/reachability/bundle-assets; `schema_version` migration + reference-counting/cascade/orphan-detection + backup/restore; knowledge-loop bridges (facts↔$memory, session-summaries, message-rating, memory similarity); Models "Installed Locally" convergence (deliberate function); research-followup `web_search` default (privacy → OFF); wikilink resolution in store preview; Projects delete/rename/reorder/assignee (flag for Operate U2/U3 scope amendment); Runs zero-state CTA (Operate U5/U6 own `runs-tab.js`); admin-observability (a2a default-drift candidate for GP-2 commit 7 if budget); AgentTuning runtime injection (frozen engine — CP-1 ships honest toast only).
