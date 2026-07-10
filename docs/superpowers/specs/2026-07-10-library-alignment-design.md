# Library alignment — design

**Date:** 2026-07-10 · **Branch:** `feat/composer-workspace` · **Status:** draft — pending operator approval
**Provenance:** 7-track design fan-out (LB0–LB6) → synthesis → 2 adversarial critics (33 issues: 2 blockers, 12 majors, 19 minors). All 33 folded in below — see the Critique resolutions table at the end.

## Overview

This spec merges the seven Library-alignment track designs (LB0 shell, LB1 test harness, LB2 Prompts+Hooks, LB3 Skills, LB4 Models, LB5 Plugins, LB6 Task Menu) into one coherent plan for Enclave's Library plane. The Library becomes the platform's **core inventory** (A1): every out-of-the-box asset and every asset the operator produces inside Enclave, organized around the four building blocks — **model, context, memory, tools** — in service of Enclave's purpose: build, manage, and operate local AI models with granular detail and optimized outputs.

**Locked operator decisions (unchanged by critique):**
1. Hooks are colocated in Prompts as a third prompt kind — no separate Hooks tab.
2. Discovery is operator-triggered fetch against a local digest allowlist — never background.
3. Recommender is hybrid: deterministic scorer always on, optional local-LLM "Ask Enclave" on demand.
4. Sequencing is fixed (A12): **LB0 → LB1 → LB2 → LB3 → LB4 → LB5 → LB6.** Each track lands as one or more independently verifiable gated build units (15 total, listed at the end).

**Hard constraints (apply to every unit):**
- Frozen engine: `api/services/workflow_engine.py`, `api/services/step_executor.py`, `api/models/workflow_models.py` are read-only. Hook/step models (`HookSpec`, `StepHooks` — `api/models/workflow_models.py:57/64` — and `AgentStep`) are consumed via read-only imports only.
- Zero new inline `on*=` handlers, zero new window globals. All new wiring goes through the delegated `Actions.click`/`Actions.on` registry (`js/shell/actions.js`); new modules are ES modules under `api/static/js/library/` or `js/admin/`, imported in `main.js`.
- ONLY ADD — never lose existing functionality. Frozen tab ids (`admin-plugins`, `admin-skills`, `admin-mcp`, `inventory`, `agents`, `prompts`), DOM-relocator ids (`#skills-tab-discover-mount`, `#inv-stats`/`#inv-grid`/`#discover-section`, Kanban), and existing action ids stay alive (old ids registered as aliases during migration).
- Parity baseline: `tests/parity`, `tests/ui`, and the non-slow e2e 14-failure set must not regress; container ids and row classes are kept stable (add classes, never rename).
- Privacy-first appliance: **no background egress.** Every external fetch is operator-triggered (visible Refresh button firing a master-key-gated `POST .../refresh`) against allowlisted, pinned sources. Read-GETs — including tab activation — serve only the last persisted digest plus a `fetched_at` staleness stamp; they never reach the network.
- Every new write route carries `Depends(require_master_key)` (`api/middleware.py:233`). Mutating/LLM POSTs from the UI use `Net.call({retries:0})`.
- Path-containment discipline on any id→path resolution: `_ID_RE`-style charset allowlist plus resolved-path containment check (the `skills.py:626-651` `_resolve_installed_skill_path` / `prompts.py:66-80` `_path` pattern). Atomic writes via tmp+replace. Secrets chmod-0600, masked on read, never logged or echoed.

Line anchors cited below are approximate (drift ±30 lines); verify at edit time.

## Conceptual model (A1)

The Library is the inventory of everything Enclave can compose a workflow from. Each item carries:

- **kind** — v1 migrates six kinds onto the shell: `prompt` (role|template|hook), `skill`, `model`, `plugin`, `mcp`, `task`. `agent` and `workflow` remain first-class concepts (they appear in relations and provenance) but their panels migrate in named follow-ups #1 and #2 — not silently, and not in v1.
- **provenance** — `oob` (shipped) vs `user` (operator-created or promoted), **physical where possible**: prompts → repo `prompts/` layer vs `user_storage_root/prompts/` layer; plugins → system/user layer; tasks → `api/config/tasks_catalog.json` seeds vs `user_storage_root/tasks/`; skills → bundled/marketplace state; models → `MODEL_REGISTRY` vs `extra`; MCP → catalog-installed vs manual; agents → `api/config/oob_manifest.json` shipped-seed ids (manifest-based, the one kind without a physical layer in v1).
- **building blocks** — which of model/context/memory/tools the item contributes to, rendered as dots on library rows.
- **relations** — cross-kind references (workflows referencing a model/skill, prompts feeding a task, hooks attached to steps), always derived from real data (workflow YAML scans, agent YAML scans, plugin manifests), never faked.

Every migrated kind gets the same experience (A5/A7): the same sidebar/drill-down shell, the same install/config wizard, the same Test pane, the same Installed/Discovered split, plus object-specific actions rendered from a per-kind adapter.

## Persistence architecture (two seams, both load-bearing)

The container ships only `api/`, `models/`, `agents/`, `workflows/`, `prompts/`, `plugins/`, `docs/seed/` (Dockerfile COPY lines 22-35); `/app/data` is the `api_data` named volume (docker-compose.yml:96) — image content never reaches it after first boot, and the Dockerfile does not COPY `data/` at all.

1. **Repo-shipped curated artifacts live in the COPY'd tree, never under `data/`.** New curated files land in `api/config/`: `api/config/oob_manifest.json` (agents seed ids), `api/config/model_meta.json` (per-arch-class perf expectations), `api/config/tasks_catalog.json` (13 builtin task seeds). These update with the code in the same commit and reach every deployment on image upgrade. (`data/discovery/mcp_catalog.json`, `skills_catalog.json`, `model_benchmarks.json` are pre-existing violations of this rule — they are git-tracked but not COPY'd; migrating them is named follow-up #16, out of scope here.)
2. **Runtime-mutable state lives under `data/` (== `user_storage_root` in containers, `deployment.py:120-122`).** Discovery digests (`data/discovery/prompt_digest.json`, `plugin_digest.json`, `tasks_digest.json`), operator config (`data/config/discovery_sources.json`, `model_tags.json`), and — new — **user-layer prompts** and **task schemas**.

**Prompts become two-layer (the plugins precedent):** repo `prompts/` = read-only oob layer; `user_storage_root/prompts/{roles,templates,hooks}/` = writable user layer. Listing merges both, user shadowing oob by id. **All writes target the user layer:** creates and digest installs write there directly; PATCH of an oob id performs copy-on-write into the user layer (auto-promote — the edit still works, provenance flips honestly to `user`); DELETE of an id with a user copy removes the user copy (reverting to oob), DELETE of a pure-oob id returns 403 with an explanatory detail. This is the one deliberate behavior change in the plan (today an oob repo file is edited/deleted in place, which a container rebuild silently reverts anyway) — flagged here for operator sign-off with the rest of the spec. `deployment.py ensure_dirs` gains `prompts/` and `tasks/`.

**Promote** is now physical: `POST /api/prompts/{kind}/{pid}/promote` copies the oob file into the user layer (409 if a user copy exists, atomic, master-key). Skills promote is real in v1 too: `POST /api/skills/{skill_id}/promote` copies the skill's SKILL.md + registration entry into a default `user-skills` user-layer plugin (`target_plugin_id` override offered; 409 on exists). **Version** is a display badge in v1 (plugin semver rendered as row/header metadata); there is **no `version` action verb** — history/rollback defers to follow-up #8.

## The uniform shell contract (LB0)

**Verdict:** new module `api/static/js/library/shell.js`, not an AssetPeek extension. AssetPeek stays as-is (quick-peek affordance); the shell is the in-tab master-detail grammar that PromptsLibrary/MCPPanel already prototype.

`LibraryShell.register(adapter)` + `LibraryShell.mount(kind, containerId)` + **`LibraryShell.open(kind, id)`** (programmatic cross-kind navigation: switchTab + select + subnav restore — `tasks.open-ref`, the recommend rail, and `plugins.goto-mcp` all ride it instead of bespoke wiring). The adapter contract (implemented per kind inside its existing module):

```
{ kind, tabId, countBadgeId,
  list():   [{id, title, meta, group, status, provenance:'oob'|'user', blocks:[...],
              icon?,                      // persona/AgentIcons key (LB3 calm cards)
              chips?: [{label, cls}],     // ≤3 trigger chips, task-tag chips (LB3/LB4)
              badges?: [{label, cls}],    // runner badge, layer chip, version, source (LB4/LB5)
              dot?: {cls, title}}],       // fit dot (LB4)
  renderRowExtras?(item): Node|null,      // escape hatch for anything the fields above can't express
  detail(id): {sections: {overview, config?, files?, examples?, relations?}},
              // each section value may be a static payload OR an async
              // (mountEl) => Promise render fn, invoked on first subnav
              // activation — this is how LB3's Files tab does per-node
              // fetches without a side channel
  actions(id): [{action, label, verb:'install'|'test'|'edit'|'promote'|'delete', enabled, reason?}],
  testPane?(id): renderFn,          // slot only in LB0; LB1 fills it; Test tab hidden when absent
  wizard?(mode): stepProviders,
  auth: 'none'|'optional'|'admin' } // Plugins hard gate preserved exactly
```

A contract test in `tests/ui/test_library_shell.py` renders a fixture adapter exercising **every** optional field (icon, chips, badges, dot, renderRowExtras, async sections) so LB3/LB4/LB5 cannot discover a missing seam after the contract is frozen.

**Anatomy.** Reuses the existing `plugins-layout` two-pane skeleton. Left sidebar: **Installed | Discovered** tabs, a **client-side filter input** (substring over title+tags — prompt digests and the 19-entry-plus model catalog need it, and every kind inherits it), collapsible group headers, `.lib-row` rows with provenance chip and building-block dots. Center pane: header (AgentIcons icon+tone, title, id, provenance), uniform subnav **Overview / Config / Files / Examples / Test / Relations** (absent sections hidden), uniform actions row from `actions(id)`. States use `core/ui.js` ErrorPanel/Skeleton/Confirm; escaping via `core/dom.js esc` (the local `esc()` shadows in skills.js/plugins.js are deleted as each migrates).

**Auth enforcement.** `adapter.auth` is enforced in the shell's fetch paths: `admin` → `AdminAuth.isSignedIn()/renderLock` + `AdminAuth.fetch`; `optional` → merged auth headers; `none` → plain `Net.call`. A ui test asserts the Plugins gate is not weakened and Prompts is not over-gated.

**Migration contract (precise, not "byte-identical"):** LB0-U1 migrates Prompts and MCP behind adapters **endpoint-and-action-identical** — every existing endpoint call, action id, and behavior preserved; container ids stable; the `.mcp-row` class **retained** on rows with `.lib-row` added alongside (never renamed); every selector used by `tests/playwright/test_prompts_library.py` (commit 17525ad: nav, seeded list, render preview) and `tests/ui` kept alive. Running the prompts playwright e2e is an explicit LB0-U1 verify item. Skills (LB3), Models (LB4), Plugins (LB5), Tasks (LB6) migrate in their own tracks; Agents migration is named follow-up #1. DOM relocators are preserved: LB0 deliberately does not touch the Skills/Models tabs.

**LibraryWizard** (`js/library/wizard.js`): uniform 4-step modal — Source → Configure → Secrets → Confirm/Result (empty steps skipped) — generalizing InstallWizard/builders.js, `.admin-modal` markup, submit always `retries:0`. Secrets never echo saved values (cloud_providers masking) and are never logged. **Wizard-backed flows, named per track (A5):** prompt digest install (LB2-U2), skills install/import-URL (LB3-U2), plugin forge + seed-from-digest (LB5-U3), task create (LB6), MCP marketplace env-key entry (LB1-U2, replacing its `window.prompt()`). Model pull keeps its existing progress flow in v1 — named follow-up #18, an explicit A5 carve-out rather than a silent thinning.

## Admin / Library seam (A3)

**Admin determines the SOURCE and system-level changes to library inventory; Library sets the behavior of particular library functions.** Concretely:

- New **Admin ▸ Sources** dropdown item (dropdown-only in v1) → `#tab-admin-sources` + `js/admin/sources.js`, copying the ApiKeysPanel gate (strictest: `isSignedIn`/`renderLock` before any fetch) and both activation paths (`adminPanelActivated` re-emit at main.js:229 + switchTab `admin-*`).
- Panel owns: provider list (GET `/api/discover/sources`), per-source Refresh (existing POST `/api/discover/{source}/refresh`, discover.py:51), editable repo allowlists, refresh cache TTLs, masked tokens.
- Backed by new **GET/PUT `/api/discover/config`** (require_master_key) persisting `data/config/discovery_sources.json` — file>env>default merge per the search_settings pattern, chmod 0600, tokens masked on read. **Route-ordering hazard:** `discover.py` already defines `GET /{source}` (line 39) — the `/config` routes MUST be registered before the `/{source}` catch-all (and `config` reserved in the source-name validator); a test asserts `GET /api/discover/config` returns the config document, not a provider-404.
- **Decision:** this one file governs *all* fetch-source knobs — agentic_discovery providers, `ENCLAVE_SKILLS_CATALOG_URL`/`ENCLAVE_MCP_CATALOG_URL` remote catalogs, plugin marketplace allowlists (config-file only — there is no `ENCLAVE_PLUGIN_MARKETPLACES` env var in the codebase and this plan does not invent one), prompt-digest sources, and the HF model-discovery **cache TTL** (defined as the max age applied to operator-triggered refreshes — it is not a poller and nothing fetches on a timer). Applied per-service **at fetch time** (never at import-time provider registration), so PUT changes take effect without restart.
- Admin never lists items. Per-item install/edit/test/uninstall stays in Library panels.

## Discovery architecture (A6) — ONE fetcher, per-kind normalizers

**Resolved overlap:** LB2's prompt digest and LB5's plugin digest (and future task/skill digests) share a single service, **`api/services/discovery_fetch.py`**, introduced in LB2 and reused by LB5:

- **Allowlist resolution** from `data/config/discovery_sources.json` (Admin ▸ Sources), read at fetch time. Pinned default sources: `anthropics/claude-cookbooks` (registry.yaml, verified at repo root), `openai/openai-cookbook` (registry.yaml, verified), `google-gemini/cookbook` (git trees), `anthropics/claude-plugins-official`, `anthropics/claude-code`, `anthropics/skills`, `anthropics/knowledge-work-plugins`. The hookify rule source is **cut from the v1 allowlist** — verified: the hookify plugin ships no `*.local.md` rule files (they are generated into end-user projects), so that digest branch would yield zero records. Engine-hook presets are seeded from the shipped xdm workflows instead (see LB2).
- **Manifest resolution ladder (plugins):** `.claude-plugin/marketplace.json` first, then per-plugin `.claude-plugin/plugin.json` enumeration as fallback (the knowledge-work-plugins shape) — verified: none of the four pinned sources expose a repo-root `marketplace.json`. Both shapes covered in the mocked-HTTP fixtures.
- **Manifest-first diff:** fetch each source's cheap authoritative index (registry.yaml / marketplace manifests / trees / llms.txt), diff against the stored digest, pull bodies only for added/changed records.
- **Sha-pinned raw fetches** from `raw.githubusercontent.com/<owner>/<repo>/<sha>/<path>`; official marketplace entries use their own per-entry sha pin.
- **Rate-limit posture:** unauthenticated GitHub API budget (60/hr) respected; fail-soft to partial digest with remaining-quota surfaced; optional token via Admin ▸ Sources (never env-inline, masked).
- **Atomic persistence** to `data/discovery/<kind>_digest.json`: the latest digest is written whole (tmp+replace) and added/changed/removed is computed against the prior file at refresh time. **No append-only log, no tombstones** — diff badges only need current-vs-previous (YAGNI cut per critique).
- **License gate:** per-record license captured (per-asset — anthropics/skills has proprietary entries, verified); `proprietary`/`unknown` → pointer-only, body-copy install hard-blocked with explanation; community-tier provenance ingests pointer-only.
- **Operator-triggered only:** refresh runs solely on `POST .../refresh` routes (master-key gated), fired by visible Refresh buttons. Read-GETs (`GET /api/prompts/discover`, `GET /api/tasks/discover`, Discovered-tab activation) serve the persisted digest + `fetched_at` staleness stamp and never touch the network. No daemons, no TTL-on-read, no background egress. *(Pre-existing TTL-on-read fetches — `skills.py:44`, `mcp.py:58`, HF discovery on `GET /api/inventory/discover` — predate this spec; migrating them onto the refresh-only pattern is named follow-up #15, so the platform-wide posture eventually holds.)*

**Per-kind normalizers** map fetched assets into the unified digest record `{id, kind, subkind, title, tags[], intended_output, license, token_estimate, source{origin, repo, path, ref, url, provenance: first-party|curated|community}, content_sha, body?|body_pointer, fetched_at, manifest_entry}`:
- **prompt normalizer** (LB2): cookbook notebooks → structural-operation parents + extracted prompt children; commands/agents `.md` → prompts; SKILL.md → templates.
- **plugin normalizer** (LB5): marketplace entries → pointer-only plugin records with component counts, version-resolution ladder (declared semver > pinned sha > unknown), added/changed diff badges. Implemented as a real `claude-marketplaces` provider registered via `agentic_discovery.register_provider` (`agentic_discovery.py:163`, replacing the stub) so it shows in `/api/discover/sources` and Admin ▸ Sources.
- Existing providers (skills marketplace, mcp-registry, HF model discovery) keep their pipelines but read allowlists/TTLs from the same config file.

Diff badges in the Library Discovered tabs compare digest `content_sha` vs installed provenance sha.

## Test harness (A2, LB1)

`api/static/js/library/test-pane.js` exports `TestPane` — fills the shell's Test subnav slot per selected component. `TestPane.register(kind, adapter)` for `prompt`, `model`, `skill`, `plugin-tool`, `mcp-tool`, `step` — six kinds, **every one with a live mount in v1**: prompt/mcp-tool via the LB0 shell (mcp.js wires `adapter.testPane` in LB1-U2 — its tester already exists and moves into the Test slot), skill via LB3-U2, model via LB4-U2, plugin-tool via LB1-U2, step via LB6. The `agent` adapter is **deferred to the Agents-migration follow-up (#1)** — no adapter ships without a reachable surface. Tool-kind adapters ride `AdminAuth.fetch` + `renderLock` (per-layer degradation, not a wall); model/prompt adapters use plain `Net.call`. Every run POST is `retries:0`.

**Layered config model** — the answer to "think through ALL layers of configuration" (A2). Four collapsible layers, each with a diff chip ("2 overrides") and per-field reset:
- **L0 Component config** — the component's own record; baseline snapshot at open; edits are session-local overrides.
- **L1 Attached skills/tools** — chips from `plugin.yaml` skills / `AgentTool`s / step `ToolRef`s; attach/detach via existing install endpoints.
- **L2 Model params** — model/role picker (`GET /api/models`), temperature, max_tokens; warm/cold badge from `GET /api/inventory/memory` + Warm button.
- **L3 Input sample** — schema-driven form (extracted `renderToolForm`/`_collectParams` from plugins.js; MCPTool.input_schema is JSON Schema) or plain message box for LLM kinds.

Run → normalized result strip `{content|result, usage?, model_fallback?, latency_ms, status}` (the test-step/agent-chat envelope is canonical; MCP/plugin raw JSON rendered beneath) + last-5 history with snapshot restore.

**Backend per kind:** prompt → `POST /api/prompts/{kind}/{pid}/render` then optional run through `POST /api/workflows/test-step` (workflows.py:352; labeled "model+prompt only" — tools/skills/parsers not exercised); model → `/v1/chat/completions`; plugin-tool → **new** `POST /api/plugins/{id}/tools/{tool_id}/test` ({params, config_overrides} merged over saved settings; sandbox=None divergence surfaced in response meta, never hidden); mcp-tool → the existing stateless `POST /api/mcp/servers/{id}/invoke` (mcp.py:229) — **the warm-session pool (MCPToolCall.session + TTL reaper) is cut** per YAGNI critique; stateless invokes serve the v1 pane, pooling rides follow-up #5 gated on measured latency pain; skill → **new** `POST /api/skills/test` trigger dry-run (matched skills, matched keywords, exact injected text); step → `/api/workflows/test-step` with the UI finally sending temperature/max_tokens and router-level `skills:[]` injection mirroring `skill_injector` semantics, pinned by a parity test against the builtin's output (engine untouched). Model warm via **new** `POST /api/inventory/warm` going through the **runner-service explicit-load path** (`Runner.load()`, runner.py:~222 — Ollama pre-warms, vLLM-pinned is a documented no-op) returning `{runner, load_duration_ms}`; TestPane disables the Warm button with a reason chip for runners where load is a no-op — the flagship NVFP4 model runs on vLLM and must not get a dead button.

**Secrets gate closed here:** `POST /api/inventory/settings/search` (inventory.py:901) persists `brave_api_key` and is currently ungated — and `test.promote` for the websearch worked example writes through exactly this route. LB1-U1 adds `require_master_key` to it (plus a 401-with-auth-on test). The UI already rides the global auth fetch wrapper (`installGlobalAuthFetch`, main.js:8925) with `retries:0`, so no frontend change is needed.

**Promote** (`test.promote`, Confirm-gated, shows the diff being written): prompt → PATCH (copy-on-write to user layer per the persistence seam); MCP → PATCH; websearch → merge-on-write search settings; step → `dfUpdateNodeData` canvas write-back. Model promote is disabled in v1 (no home for tuned params — follow-up #10). Saved input samples: localStorage v1; server-side test-case store is follow-up #5.

**Worked example (A2, Plugins > websearch):** Test tab loads search settings (L0, masked keys), lists the plugin's skills (L1, attach a discovered search-strategy skill), hides L2 (direct invoke), renders the query form from the tool schema (L3). Run → `POST /api/plugins/websearch/tools/{tool_id}/test {params, config_overrides:{max_results:3}}` → results + latency; iterate via history; Promote writes the override into search settings (now master-key gated). `config_overrides` never persist implicitly and never echo unmasked keys.

## LB2 — Prompts + Hooks (A8; A4 hook colocation)

**Hook kind (DECIDED: colocated in Prompts as third kind `role|template|hook` — no separate Hooks tab).** `hook` added to `PromptKind` (prompts.py:33) → user-layer `prompts/hooks/<id>.md`, YAML frontmatter (`stage`, `target` factory name, `config`, `tags`, `intended_output`) + markdown rationale. A library hook is a **configured preset of one of the 10 built-in engine hooks** (the closed `_instantiate_hook` factory, workflow_engine.py:1499; `api/hooks/builtins/` has exactly 10 modules). Save-time validation: `stage` must be one of the five step-scoped `StepHooks` fields (`before_step`, `transform_prompt`, `after_step`, `validate_output`, `on_failure` — workflow_models.py:64) and match the builtin's declared stage (read-only imports from `api/hooks/builtins/*`); `config` keys checked against `inspect.signature(cls.__init__)` (HookSpec.config is splatted as kwargs). V1 attach = "Copy hooks: YAML" action (paste into workflow YAML per `workflows/xdm-*.yaml`); Composer inspector attach + `_dfCleanStep` hooks serialization is follow-up #4. Hook Test pane: factory instantiation; `validate_output` hooks additionally dry-run pasted sample output through a synthetic HookContext showing `HookResult.action/feedback`. Custom `api/hooks/custom/` hooks appear as read-only "always-on" entries (transparency; they attach to every bus, not per-step). Seed presets ship in the repo oob layer, derived from the three shipped xdm workflow hook blocks (`workflows/xdm-vendor-pack.yaml`, `xdm-bulk-onboarding.yaml`, `xdm-rule-from-log.yaml` — all verified to carry `hooks:` blocks); the hookify remote source is cut (see Discovery).

**Tagging/classification (A8).** Roles/templates get sidecar `<id>.meta.json` next to the prompt file in whichever layer owns it (frontmatter would leak into PromptComposer output — `prompt_composer.py:40`); hooks carry meta in frontmatter. Fields: `tags[]`, `category` (task-type: code, analysis, extraction, classification, planning, review, writing, security), `technique[]` (few-shot, chain-of-thought, persona, structured-output, critique, guardrail), `intended_output` (mapped to intended output, e.g. Code — "update the readme"), `model_fit[]` (role classes reasoning/coding/fast/general/uncensored — same vocabulary as `dfRoleColors` (main.js:5217) and `data/discovery/model_benchmarks.json role_fit`, plus optional exact model-id pins), `input_scope`/`output_scope`, computed `token_estimate` (ceil(chars/3.6), presented as approximate). Output-type reuses `dfFmtDescs`. `PATCH /{kind}/{pid}/meta` writes atomically (to the user layer, copy-on-write for oob prompts); `delete_prompt` unlinks sidecars; prompt listing ignores `*.meta.json` (extension-scoped globs — roles `.md`, templates `.jinja` — plus an explicit guard test). This taxonomy is shared verbatim with LB4 (model task tags) and LB6 (task schemas) — one vocabulary across the platform.

**Size / I-O scoping (A8):** detail pane surfaces intended_output, token-estimate chip vs selected model context window (red/amber/green, approximate not a gate), and input/output scoping fields for granular context management.

**Discovery:** rides the shared fetcher (above); routes `GET /api/prompts/discover` (persisted digest + staleness stamp only), `POST /discover/refresh` (master-key, visible button), `POST /discover/{digest_id}/install` (copies body into the **user layer** `prompts/{kind}/`, writes provenance into the sidecar, license-gated, wizard-backed). All prompt **write** routes gain `require_master_key` (reads stay open; prompts.js already sends AdminAuth headers).

**Recommendation (A8, DECIDED hybrid):** see Recommender design below.

## LB3 — Skills (A9) — split into two units

`#tab-admin-skills` rebuilt on the shell. **Adapter auth tier: `admin`** — honest about the backend: every data source the panel needs (`GET /api/plugins`, `/api/skills/discover`, `/github`, `/source` — 10 `require_master_key` dependencies across skills.py) is already master-key gated server-side, so an "optional" tier claiming per-layer degradation would be indistinguishable from a wall. Matching the Plugins gate is the deliberate, tested decision; read-open annotations on skills reads are not in scope.

**LB3-U1 (backend):** three read endpoints + promote. Sidebar data: **Installed** (collapsible per-plugin groups from `GET /api/plugins`) and **Discovered** (Bundled / Marketplace / Remote groups from `GET /api/skills/discover` only in v1 — the agentic-discovery merge waits for an install bridge). Drill-down data: `GET /api/skills/tree/{skill_id}?plugin_id=` (registration entry + declared file + optional `skills/<skill_id>/` dir contents; single-file skills render an honest one-node tree), `GET /api/skills/file` (single body; charset allowlist on path segments + containment against the plugin dir), `GET /api/skills/relations/{skill_id}` (host plugin, workflows referencing `<plugin>.<skill>` in `step.skills` or `skill_injector` configs via a workflows/*.yaml scan with short TTL cache, chat trigger keywords; Agents section honestly says "none"). Plus `POST /api/skills/{skill_id}/promote` (see Persistence). All master-key gated, never 500 (empty lists on scan errors).

**LB3-U2 (panel):** visible Refresh re-hits `/api/skills/discover` + `POST /api/discover/skills-marketplace/refresh`. **Calm card (revamp of busy `.plugin-card`):** persona icon, name, one-line ellipsized description, ≤3 trigger chips + `+n`, one source badge — expressed through the LB0 row contract's `icon`/`chips`/`badges` fields. Status pip / role meta / inject mode / content preview all move to detail. **Drill-down tabs:** **Overview** (kv-grid + rendered SKILL.md); **Files** (tree + file endpoints, per-node async section renderers); **Relations ("works with XYZ")**; **Examples** (frontend-parsed `## Example(s)`/`## Usage` sections, empty-state prompts Edit); **Test** — the LB1 skill adapter mounted via `adapter.testPane` (dry-run: matched skills, matched keywords, exact injected text), with a `skills.test` data-action. **Actions preserved:** Edit source (PUT + plugin reload), Uninstall (Confirm), Seed chat, Install (target-plugin flow) and Import URL through **LibraryWizard** (endpoints byte-identical, `window.prompt()` retired), Browse GitHub repo, New Skill (SkillsBuilder), **Promote** (skills.promote → LB3-U1 route, Confirm-gated). **Composer seam:** shared `js/library/skills-data.js` loader feeds both the shell and the Composer Skills bench (drag/attach payload unchanged, covered by a ui test). `#skills-tab-discover-mount` + SkillsDiscoverShare/CatalogPage relocation stay alive in v1.

**Cut (named follow-ups):** per-skill enable/disable flag (plugin.yaml registration IS enablement, #11), multi-file external skill install (rides the LB5 fetcher work; tree endpoint already renders dirs, #7), AssetPeek `skill` kind (#3).

## LB4 — Models (A10)

`tab-inventory` gains `#models-shell` (new `js/library/models-panel.js`, prompts.js pattern) as **the single visible models surface**. The only-add conflict with the landed relocator is resolved structurally: `switchTab('inventory')` unconditionally calls `CatalogModelsShare.showInModelsTab()` (main.js:164), which re-appends `#inv-stats`/`#inv-grid`/`#discover-section` into `tab-inventory` (`_moveTo`, library/models.js:~119). LB4-U2 adds a **hidden holder div inside `tab-inventory`** and points `showInModelsTab()`'s home target at it — ids unchanged, so `showInCatalog()` still relocates the same nodes to the Catalog page and the Admin Catalog keeps binding, but the Models tab never shows two surfaces or double-fetches `/api/inventory`. A ui test asserts: exactly one visible models surface on tab-inventory, and legacy nodes still relocate to the Catalog page.

**List:** grouped Installed / Available / Discovered rows with fit dot (green/amber/red), runner badge (ollama/vllm), task-tag chips — all via the LB0 row contract. **Detail:** Summary (description, tags, license), **Weights architecture** (family, params, quant, context, size — registry fields joined with filtered `GET /api/inventory/model/{name}` model_info; the vLLM branch degrades to registry fields so the flagship NVFP4 view is never empty), Performance (tok/s expectations for the detected arch class), Hardware fit (score + per-pool breakdown), Relations (workflows via `_workflows_referencing` + new agents[] scan of `agents/*.yaml model`), and **Recommended prompts** — `GET /api/prompts/recommend?model=` (the LB2-U2 scorer; sequencing permits it) rendering the deterministic top hits with per-factor breakdowns and an open-in-Prompts jump via `LibraryShell.open`. This replaces the earlier draft's contradictory "cut prompt-effectiveness relations" line — the recommender claim is now built, not phantom.

**Metadata split (respects models-md-sync):** MODEL_REGISTRY (models/download.py:56) gains intrinsic fields (`quant`, `params_b`, `arch_family`, `context_tokens`, `size_gb`, `min_arch` incl. optional `min_compute_capability` for NVFP4/Blackwell, `task_tags[]`) on **every registry entry** (19 today — the test iterates `MODEL_REGISTRY.items()` asserting the fields exist; no count literal anywhere) mirrored into MODELS.md **in the same commit**. New repo-shipped curated sidecar **`api/config/model_meta.json`** (COPY'd tree per the persistence seam; privacy-first, no sync hook): per-arch-class perf expectations seeded from the BD790i 24GB Blackwell NVFP4 catalog, vram notes, per-intent configs — merged into `GET /api/inventory/enrichment`. Operator tag overrides: `data/config/model_tags.json` (runtime-mutable, correctly under data/) via `PATCH /api/inventory/model/{name}/tags` (master-key, atomic, `:path` converter + charset allowlist incl. `/ : .`, pure dict store — no filesystem resolution; overrides stay user-layer, curation into the registry is manual, follow-up #13).

**Task taxonomy (model→task mapping):** role tier = dfRoleColors vocabulary (scored by `role_fit` from model_benchmarks.json); task tier = dfStepTemplates keys. Task→model recommendation derives task→role→role_fit, overridable by explicit `task_tags`. Same strings as LB2/LB6.

**Hardware fit (match model to HARDWARE PROFILE):** pure service `api/services/model_fit.py`. **Named prerequisite deliverable:** the hardware-profile table currently lives in the router — `HARDWARE_PROFILES` (inventory.py:80), `_host_ram_gb()` (inventory.py:47), `detect_hardware()` (inventory.py:105) — and a pure service must not import from a router. LB4-U1 extracts them into `api/services/hardware_profile.py` with `api/routers/inventory.py` re-exporting/consuming the service (behavior-identical, covered by existing inventory tests). Fit math: budget = largest `per_pool_gb` from `detect_architecture()` (architecture.py:391, attribute at :209) for gpu classes, else the extracted `detect_hardware()["max_model_ram_gb"]`; required = `size_gb × (1 + KV_HEADROOM_PCT)` (co_scheduler.py:61); classes good ≤75% / tight ≤100% / no-fit (>100% or `min_arch` unmet — NVFP4 on cpu_x86 = no-fit). Never raises. Surfaced as `fit:{score,class,budget_gb,required_gb,basis}` on catalog entries (labeled *load-fit*, not a runtime guarantee; `fits_ram` retained). New `GET /api/inventory/recommendations?intent=` ranks by role_fit × fit-class and includes not-installed catalog models with a Pull affordance.

`require_master_key` added to inventory writes (`/pull`, `/remove`, `/unload`, `/discover/refresh`; `/settings/search` already gated in LB1-U1) — additive, no-op with auth off; parity/ui run before merge. **Cut:** registry write API; pre-warm button arrives via LB1's warm endpoint.

## LB5 — Plugins (A11)

**Inventory:** `#tab-admin-plugins` keeps its skeleton; sidebar gains Installed/Discovered sub-tabs. Installed rows show layer chip (`origin: system|user`) + version badge (metadata, not an action). AdminAuth hard gate preserved. Selection moves from title-text matching to data-id.

**Plugin-vs-MCP split (copying the Claude Code strategy):** detail header shows a **"LOCAL CAPABILITY BUNDLE"** kind banner — plugins add LOCAL functionality (filesystem, camera, local tools, skills, hooks) executed by the local runtime; MCP EXTENDS/INTEGRATES external functionality. A cross-link row "External integration? → MCP" rides `LibraryShell.open('mcp', …)` — cross-link, never merged.

**Digest Refresh:** the `claude-marketplaces` normalizer over the shared fetcher (see Discovery, incl. the `.claude-plugin/` manifest resolution ladder). Pointer-only records (name, description, category, repo+sha, component counts, per-record license surfaced before any import). Actions: **View manifest**, **Import skills** (bridges SKILL.md pointers through existing `POST /api/skills/import`), **Seed wizard**. **Cut:** no auto-conversion of Claude Code plugins into Enclave plugins in v1; community marketplace is follow-up #9.

**Creation wizard (build a plugin from scratch with the local AI system):** `PluginForgeService` (`api/services/plugin_forge.py`, spec_capture/scaffold_planner pattern: local `OllamaService` + `ModelResolver`, JSON-only system prompt, tolerant parse, deterministic fallback). Three master-key routes: `POST /api/plugins/scaffold/spec` (description → draft spec; fallback = one skill, zero tools), `/scaffold/generate` (spec → file set: plugin.yaml, skills/*.md, optional tools/*.py from a constrained template — **skills-only by default, tool code is an explicit opt-in** with a denylisted-imports lint, since tools run in-process), `/scaffold/install` (409 on existing id, `_ID_RE` charset allowlist on all ids, every path resolved+contained under `user_dir/<plugin_id>`, atomic writes, then `scan_plugins()`). The UI runs this through LibraryWizard with a **mandatory review/edit screen for every file** before install.

**Management plane, versioning, reload:** `GET /api/plugins/{id}/files`, `GET/PUT /api/plugins/{id}/files/{path}` — user layer only (403 system), containment, atomic; plugin.yaml edits YAML-validated on save (400 on malformed). `plugin.yaml version` is the single source of truth; **decision:** patch auto-bump on the *first* save since the last reload (dirty flag; explicit `version` in the body always honored) to avoid churn. PUT responses return `{version, reload_required:true}` → UI shows a Reload badge firing existing `POST /api/plugins/reload` (in-process rescan; chat + tester pick changes up next call). Tarball reinstall keeps silent replace (ONLY-ADD) but returns `{replaced_version}` for a UI downgrade confirm; 409-unless-force is deferred (#8). Delete stays Confirm-gated.

## LB6 — Task Menu (A4)

New core Library tab **Tasks**: manage, discover, create, edit agentic task schemas, feeding the Composer Task bench. Hooks are NOT a separate tab (colocated in Prompts, per decision) — task schemas *reference* them.

**TaskSchema** = persisted superset of a `dfStepTemplates` record: `{id, name, persona, role, instructions{system_prompt, blocks[]}, outputs[] (min 1 — AgentStep contract), format (dfFmtDescs), intended_output, pattern_affinity[] (subset of the closed 8-kind vocabulary; badge/filter only in v1), model_fit{preferred_role, models[]}, refs{role_ref?, template_ref?, hooks:[HookSpec-shaped, display-only badges]}, tags[], num_outputs?, is_decision?, source: builtin|user}`.

**Backend `api/routers/tasks.py`** (registered beside prompts in main.py): JSON-per-schema storage in **`user_storage_root/tasks/`** (mcp/plugins precedent — survives image rebuilds); there is **no repo `tasks/` fallback** (no such directory exists — the phantom clause is dropped; the oob layer IS the curated catalog below). `_ID_RE` + containment, atomic writes. CRUD with writes master-key gated, reads open. `POST /{id}/render` materializes refs via PromptComposer (pure library). Ref validation: prompt ids must exist (400); hook names checked against the 10-builtin factory (warning, not rejection — custom hooks legal; config shapes can only fail at run time, documented). **Discovery, refresh-only:** `GET /api/tasks/discover` merges curated **`api/config/tasks_catalog.json`** (repo-shipped, COPY'd; ships the 13 dfStepTemplates as `source: builtin` seeds — main.js statics untouched) + the last persisted remote digest (`data/discovery/tasks_digest.json`) with a `fetched_at` staleness stamp — **the GET never fetches**. The remote catalog URL (governed by discovery_sources.json) is fetched only by **`POST /api/tasks/discover/refresh`** (master-key, wired to the visible `tasks.discover-refresh` button, fail-soft to the persisted digest). `POST /discover/{id}/install` writes a user-layer copy.

**Frontend:** `js/library/tasks.js` on the shell (grouped by role, `#tasks-count` badge, detail kv + instruction pre + pattern-affinity/tag chips + clickable prompt/hook refs jumping to Prompts detail via `LibraryShell.open`, in-place edit, Confirm delete, **wizard-backed create**, ▶ render preview). **Test** = LB1 step adapter → `POST /api/workflows/test-step` (labeled prompt-only).

**Composer Task bench feed — the non-regression mechanism (blocker F1/C-series resolution).** The landed revamp (41d18e9..d42b070) renders the bench from the frozen 13-entry `dfStepTemplates` array (main.js:5189-5208, ends on `custom`) inside `dfInitPalette` (idempotence-guarded, main.js:5991), resolves drops via `dfAddNodeFromTemplate`'s array lookup (main.js:6030), hover-inspects via `bench.inspect-template` → array lookup (main.js:9622), uses `dfStepTemplates[length-1]` as the unknown-role fallback (main.js:7989), and restores by role scan (main.js:10012). **`dfStepTemplates` is therefore frozen — library tasks never enter it.** The mechanism:

- `js/library/tasks.js` keeps a **module-scoped `dfLibraryTemplates` Map** (schema id → mapped record: prompt ← rendered instructions, color ← `dfRoleColors[role]`).
- On composer activation, `fetchComposerTasks()` (ES-module import in main.js — no window global) GETs `/api/tasks` and appends library rows to `#df-palette` under a single **"Library" divider AFTER the 13 statics**, deduped by key with **statics winning**. Any failure — network, 404 because the tasks router is absent, empty list — leaves the palette byte-identical to today (fail-soft, non-blocking; graceful degrade doubles as the feature gate).
- Library rows carry **their own action id** `bench.inspect-library-task` (new mouseover registration resolving from the `dfLibraryTemplates` Map, feeding `ComposerWorkstream.inspectTemplate` a mapped record) and set a **distinct dragstart MIME** `application/df-library-task`. The static rows' `bench.inspect-template` handler and `application/df-template` payloads are untouched.
- The canvas drop handler (main.js:~5613) gains an additive branch: if the library MIME is present, call new **`dfAddNodeFromLibraryTask(schema, x, y)`**, which builds the node data object directly (mirroring `dfAddNodeFromTemplate`'s body) and registers it via the existing `dfAddPatternNode` seam (main.js:6160 — the established "register without a dfStepTemplates lookup" precedent). `tasks.send-to-composer` calls the same function.
- Save/restore is untouched: library-spawned nodes carry `role` values from the dfRoleColors vocabulary, so the existing role-scan restore (main.js:10012) resolves them to the same-role static or `custom` — pre-existing behavior, documented, acceptable for v1.
- **A ui test pins the invariants:** after the bench feed loads, `dfStepTemplates.length === 13`, its last key is `'custom'` (the main.js:7989 fallback), the 13 static rows render unchanged, library rows sit under the divider, and killing the tasks API renders the palette identical to pre-LB6.

**Cut:** `_dfCleanStep` hooks serializer / Composer hook authoring (follow-up #4), external cookbook ingestion into tasks (rides the LB2 digest later, #12), versioning/history.

## Recommender design (A8/A10, DECIDED hybrid)

**Deterministic layer (always on, pure):** `GET /api/prompts/recommend?task=&model=` scores installed prompts by (a) tags∩task-keyword overlap, (b) `model_fit` vs the model's role classes (registry tags + `model_benchmarks.json role_fit`), (c) size-fit (`token_estimate` ≤ context_window from `/api/models`). The same scorer powers prompt↔model effectiveness alignment in the prompt detail pane and the **model-side "Recommended prompts" section built in LB4-U2** (see LB4 — the earlier cut-list contradiction is resolved by building it); `GET /api/inventory/recommendations?intent=` is its model-side twin (role_fit × fit-class). Both are read-only, instant, explainable (per-factor score breakdown in the response).

**"Ask Enclave" layer (on-demand only):** `POST /api/prompts/recommend/explain` — top-8 deterministic candidates + task text → local model via ModelResolver + OllamaService (default role='fast', operator-selectable in the pane), returns ranked ids + one-line explanations. Button-triggered, `retries:0`, **nothing leaves the box.**

## New backend inventory (complete)

Auth: every route below is `Depends(require_master_key)` unless marked read-open.

| Unit | Route / service |
|---|---|
| LB0-U2 | GET/PUT `/api/discover/config` (registered BEFORE the `/{source}` catch-all; persists `data/config/discovery_sources.json`) |
| LB0-U3 | Layered prompts storage (repo oob + `user_storage_root/prompts/`); `layer` on plugin records, `origin` on prompt lists (read-open annotations); `api/config/oob_manifest.json` (agents); POST `/api/prompts/{kind}/{pid}/promote` |
| LB1-U1 | POST `/api/plugins/{id}/tools/{tool_id}/test`; POST `/api/skills/test`; POST `/api/inventory/warm` (runner `load()` path, `{runner, load_duration_ms}`); require_master_key on POST `/api/inventory/settings/search`; test-step `skills[]` router-side injection |
| LB2-U1 | hook PromptKind + validation; `api/services/prompt_meta.py`; PATCH `/{kind}/{pid}/meta`; POST `/api/prompts/hook/{pid}/test`; require_master_key on all prompt writes |
| LB2-U2 | `api/services/discovery_fetch.py` (shared); `api/services/prompt_digest.py`; prompts: GET `/discover` (read-open, digest+staleness only), POST `/discover/refresh`, POST `/discover/{id}/install`, GET `/recommend` (read-open), POST `/recommend/explain` |
| LB3-U1 | GET `/api/skills/tree/{id}`, GET `/api/skills/file`, GET `/api/skills/relations/{id}`; POST `/api/skills/{skill_id}/promote` |
| LB4-U1 | `api/services/hardware_profile.py` (extracted from inventory.py router); `api/services/model_fit.py`; catalog `fit` fields; GET `/api/inventory/recommendations` (read-open); PATCH `/api/inventory/model/{name}/tags`; `api/config/model_meta.json` enrichment merge; require_master_key on `/pull`, `/remove`, `/unload`, `/discover/refresh` |
| LB5-U1 | `api/services/discovery_providers/claude_marketplaces.py` (real provider, manifest ladder) |
| LB5-U2 | GET `/api/plugins/{id}/files`, GET/PUT `/api/plugins/{id}/files/{path}`; version-bump + `reload_required` |
| LB5-U3 | `api/services/plugin_forge.py` + `api/models/plugin_models.py`; POST `/api/plugins/scaffold/{spec,generate,install}` |
| LB6 | `api/routers/tasks.py`: CRUD (reads open, writes gated), POST `/{id}/render`, GET `/discover` (read-open, never fetches), POST `/discover/refresh`, POST `/discover/{id}/install`; `api/config/tasks_catalog.json` |

Digest artifacts (runtime, atomic whole-file replace): `data/discovery/prompt_digest.json`, `plugin_digest.json`, `tasks_digest.json`.

## Data-action inventory (complete; all via Actions.click/Actions.on, zero inline handlers)

- **Shell:** `lib.sidebar-tab`, `lib.filter`, `lib.group-toggle`, `lib.select`, `lib.subnav`, `lib.action` (generic verb dispatcher; delete wraps Confirm), `lib.refresh`, `lib.wizard.next/back/cancel/submit`.
- **Admin Sources:** `admin.sources.refresh-one`, `admin.sources.edit`, `admin.sources.save`.
- **Test pane:** `test.run`, `test.layer.toggle`, `test.field.reset`, `test.layer.reset`, `test.skill.attach/detach`, `test.tool.pick`, `test.model.warm`, `test.history.restore`, `test.promote`.
- **Prompts:** existing `prompts.select/edit/cancel/save/remove/render/new/refresh/create-close/create-submit` preserved verbatim; new `prompts.tab`, `prompts.discover-refresh`, `prompts.install`, `prompts.promote`, `prompts.meta-edit/meta-save`, `prompts.recommend`, `prompts.ask-enclave`, `prompts.test-run`, `prompts.hook-test`, `prompts.copy-hook-yaml`.
- **Skills:** `skills.side-tab`, `skills.group`, `skills.select`, `skills.dtab`, `skills.file`, `skills.test`, `skills.promote`, `skills.refresh-discovery`, `skills.install`, `skills.import`, `skills.browse-repo`, `skills.create`, `skills.edit/save/cancel`, `skills.uninstall`, `skills.seed-chat`.
- **Models:** `models.select`, `models.pull`, `models.remove`, `models.review`, `models.test`, `models.edit-tags`, `models.intent`, `models.refresh-discover`.
- **Plugins:** `plugins.sub-tab`, `plugins.refresh-digest`, `plugins.import-skills`, `plugins.seed-wizard`, `plugins.wizard-open/-spec/-generate/-install`, `plugins.file-open`, `plugins.file-save`, `plugins.reload`, `plugins.delete`, `plugins.goto-mcp`.
- **Tasks:** `tasks.select`, `tasks.new/create-save/create-cancel`, `tasks.edit/save/cancel-edit`, `tasks.delete`, `tasks.render`, `tasks.test`, `tasks.send-to-composer`, `tasks.open-ref`, `tasks.discover-refresh`, `tasks.install`; Composer: `bench.inspect-library-task` (mouseover, library rows only — `bench.inspect-template` untouched).

Existing `prompts.*`/`mcp.*` action ids stay registered as aliases during migration.

## Ask coverage (A1–A12)

- **A1** Library-as-core-inventory: conceptual model, physical oob/user layers, building-block dots, prompt+skill promote (LB0/LB3).
- **A2** Test everywhere + all config layers: LB1 TestPane L0–L3, per-kind backends, worked websearch example, promote-back; every registered TestPane kind has a live mount in v1.
- **A3** Admin/Library separation: Admin ▸ Sources owns sources + system-level knobs; Library owns per-item behavior (LB0).
- **A4** Task Menu core tab: LB6; hooks colocated in Prompts per decision (LB2).
- **A5** Uniform wizard: LibraryWizard 4-step; wizard-backed flows named per track (prompt install, skills install/import, forge, task create, MCP env keys); model pull is the one named carve-out (#18).
- **A6** Internal+external sources, latest-asset discovery: shared fetcher, allowlisted pinned sources, operator Refresh only, diff badges, offline/read = last digest + staleness stamp (LB0 config, LB2 fetcher, LB2/LB3/LB5/LB6 consumers).
- **A7** Uniform drill-down + kind-specific actions: shell subnav + adapter `actions()` (LB0, all tracks).
- **A8** Prompts library incl. hooks, external capture, tagging/classification, hybrid recommender, intended-output mapping, size/I-O scoping (LB2).
- **A9** Skills: sidebar+drill-down, Installed/Discovered, full file tree, calm cards, richer detail, works-with relations, Examples + Test tabs, promote (LB3).
- **A10** Models: shell adoption, relationships, task tagging, hardware-profile fit, summary + weights architecture, recommended prompts (LB4).
- **A11** Plugins: inventory build-out, public digests behind Refresh, Claude Code plugin strategy with local-vs-MCP separation, creation wizard via local AI, management plane, versioning + reload (LB5).
- **A12** Sequencing honored by the build-unit order below.

## Sequencing & verification discipline

15 build units, strictly ordered. Each unit: green `pytest` for its new tests, `tests/parity` + `tests/ui` green, non-slow e2e failure set **exactly** the existing 14 (no growth), plus a manual smoke listed in its verify string. A unit does not start until the prior unit's gate is met.

---

## Build units (final)

### LB0-U1 — Library shell + wizard core, Prompts/MCP adapters
**Deliverables:**
- `api/static/js/library/shell.js` — LibraryShell.register/mount/**open(kind,id)**; sidebar (Installed/Discovered tabs, **filter input**, collapsible groups, `.lib-row` rows added alongside retained `.mcp-row`); subnav Overview/Config/Files/Examples/Test/Relations (Test hidden when testPane absent; sections may be **async render fns** invoked on first activation); actions row (verbs install/test/edit/promote/delete — **no version verb**); per-adapter auth-tier enforcement (admin=AdminAuth gate, optional=merged headers, none=Net.call).
- Extended row contract: optional `icon`, `chips[]`, `badges[]`, `dot`, `renderRowExtras(item)` — contract test renders a fixture adapter using every optional field.
- `api/static/js/library/wizard.js` — LibraryWizard 4-step modal (Source/Configure/Secrets/Confirm, empty steps skipped), `.admin-modal` grammar, retries:0 submit, secrets never echoed.
- lib-shell CSS grammar in index.html extending plugins-layout; provenance chip + building-block dot styles.
- prompts.js and mcp.js wrapped as the first two adapters, **endpoint-and-action-identical** (every pre-existing endpoint/action/selector preserved; `#prompts-count`/`#mcp-count` intact; old action ids aliased).
- Shell data-actions registered: `lib.sidebar-tab`, `lib.filter`, `lib.group-toggle`, `lib.select`, `lib.subnav`, `lib.action`, `lib.refresh`, `lib.wizard.*`. Skills/Models/Plugins tabs and all DOM relocators untouched.

**Files:** `api/static/js/library/shell.js`, `api/static/js/library/wizard.js`, `api/static/js/library/prompts.js`, `api/static/js/library/mcp.js`, `api/static/index.html`, `api/static/js/main.js`, `tests/ui/test_library_shell.py`
**Verify:** pytest tests/ui tests/parity -q green; adapter-contract test exercises every optional row field + async sections + open(); auth tiers asserted (prompts not over-gated, mcp gate unchanged); `tests/playwright/test_prompts_library.py` green; non-slow e2e failure set unchanged at 14; manual: Prompts and MCP tabs render list+detail with every pre-existing action working.
**Commit:** `Add LibraryShell/LibraryWizard core and migrate Prompts+MCP adapters`

### LB0-U2 — Admin Sources panel + persisted discovery config
**Deliverables:**
- GET/PUT `/api/discover/config` (require_master_key) persisting `data/config/discovery_sources.json` — file>env>default merge, chmod 0600, tokens masked on read; governs agentic providers, skills/mcp catalog URLs, plugin marketplace allowlists (config-file only, no new env var), prompt-digest sources, HF discovery **cache TTL** (max age for operator-triggered refreshes — not a poller).
- `/config` routes registered **before** the `/{source}` catch-all (discover.py:39); `config` reserved in the source-name validator.
- agentic_discovery + skills_marketplace consult the config file at FETCH time (not import-time registration).
- `js/admin/sources.js` — Admin ▸ Sources panel: provider list from `/api/discover/sources`, per-source Refresh, allowlist/TTL/token editor modal (cloud.js grammar); ApiKeysPanel-strict gate (isSignedIn+renderLock before any fetch).
- `#tab-admin-sources` markup + Sources item in `#admin-menu`; admin-sources added to switchTab admin-* re-emit list; adminPanelActivated listener.
- data-actions: `admin.sources.refresh-one`, `admin.sources.edit`, `admin.sources.save`.

**Files:** `api/routers/discover.py`, `api/services/agentic_discovery.py`, `api/services/discovery_providers/skills_marketplace.py`, `api/static/js/admin/sources.js`, `api/static/index.html`, `api/static/js/main.js`, `tests/test_discover_config.py`, `tests/ui/test_admin_sources.py`
**Verify:** pytest tests/test_discover_config.py -q: GET /api/discover/config returns the config document (not a provider 404), PUT persists, tokens masked on GET, 401 with auth on and no key, file consulted at fetch time (PUT then refresh uses new allowlist without restart); ui test: lock screen when signed out; parity/ui baseline green.
**Commit:** `Add Admin Sources panel and persisted discovery source config`

### LB0-U3 — Prompt user layer, provenance + promote
**Deliverables:**
- Layered prompts storage: repo `prompts/` = read-only oob; `user_storage_root/prompts/{roles,templates}/` = writable user layer (`deployment.py ensure_dirs` extended); listing merges layers with user shadowing oob by id; creates/installs write user layer; PATCH of oob id = copy-on-write auto-promote; DELETE removes user copy (revert-to-oob) or 403 on pure-oob with explanation.
- `api/config/oob_manifest.json` listing shipped agent seed ids (hand-curated, in the COPY'd tree; test asserts all ids resolve); prompts derive provenance from layer, plugins expose `layer`, skills/mcp/models derive from existing state fields.
- Shell rows render prov-oob/prov-user chips + building-block dots from adapter list().
- POST `/api/prompts/{kind}/{pid}/promote` — copy oob file into user layer, 409 on exists, atomic tmp+replace, require_master_key; `prompts.promote` action.

**Files:** `api/routers/prompts.py`, `api/routers/plugins.py`, `api/services/deployment.py`, `api/config/oob_manifest.json`, `api/static/js/library/shell.js`, `api/static/js/library/prompts.js`, `tests/test_provenance.py`
**Verify:** pytest tests/test_provenance.py -q: layered listing merges + user shadows oob, create lands in user layer, oob PATCH copies-on-write, oob DELETE 403 / user DELETE reverts, promote 201 then 409, manifest agent ids resolve, plugin records carry layer; parity/ui green; manual: provenance chips visible on Prompts/MCP rows.
**Commit:** `Add layered prompt storage, provenance chips, and prompt promote`

### LB1-U1 — Test backend routes
**Deliverables:**
- POST `/api/plugins/{id}/tools/{tool_id}/test` — {params, config_overrides} merged over saved settings, returns {result, latency_ms, status}, sandbox=None divergence in response meta, require_master_key; overrides never persisted, keys never echoed.
- POST `/api/skills/test` — {message, plugin_id?, skill_id?} dry-run over plugin_service.get_skills/get_skill: matched skills + keywords + exact injected text, require_master_key.
- POST `/api/inventory/warm` — runner-service explicit-load path (`Runner.load()`), returns `{runner, load_duration_ms}`; vLLM-pinned reported as no-op capability so the UI can disable-with-reason; require_master_key.
- require_master_key on POST `/api/inventory/settings/search` (inventory.py:901 — secrets write, currently ungated; test.promote depends on it) + 401-with-auth-on test.
- StepTestRequest `skills[]` handling in routers/workflows.py — router-side injection mirroring skill_injector semantics; frozen engine files untouched; parity test pins injection text against `api/hooks/builtins/skill_injector.py` output.
- **Cut (was drafted):** MCPToolCall.session warm-pool + TTL reaper — stateless `/api/mcp/servers/{id}/invoke` serves the pane; pooling deferred (#5).

**Files:** `api/routers/plugins.py`, `api/routers/skills.py`, `api/routers/inventory.py`, `api/routers/workflows.py`, `api/services/runner.py` (consume only) , `tests/parity/test_skill_injection_parity.py`, `tests/test_test_routes.py`
**Verify:** pytest tests/test_test_routes.py tests/parity -q: all new routes 401 without key when auth on (incl. settings/search), plugin tool test merges overrides, skills dry-run returns exact injected text, warm returns runner+duration and reports no-op runners, skill-injection parity matches builtin output; git diff confirms workflow_engine.py/step_executor.py/workflow_models.py untouched.
**Commit:** `Add test backend routes and gate inventory search-settings write`

### LB1-U2 — TestPane module in the shell Test tab
**Deliverables:**
- `api/static/js/library/test-pane.js` — TestPane.register(kind, adapter) for **prompt/model/skill/plugin-tool/mcp-tool/step** (agent deferred to follow-up #1 with its panel); L0–L3 layered sections with diff chips + per-field/layer reset; normalized result strip; last-5 history with snapshot restore; localStorage saved samples.
- Schema form kit (renderToolForm/_collectParams/_renderHistory) extracted from plugins.js into test-pane.js; plugin tester DOM ids/classes preserved; local esc() shadow deleted.
- **mcp.js wires adapter.testPane** (existing tester moves into the Test slot — no orphaned adapter); MCP marketplace env-key `window.prompt()` replaced by the LibraryWizard Secrets step.
- Per-layer auth degradation: tool layers renderLock only, LLM layers stay usable.
- `test.promote` Confirm-gated write-back per kind (PATCH prompt / PATCH mcp / search-settings merge / dfUpdateNodeData for steps); model promote disabled with reason.
- `_sendStepMessage` sends temperature/max_tokens; Test subnav slot live via adapter.testPane.
- data-actions: `test.run`, `test.layer.toggle`, `test.field.reset`, `test.layer.reset`, `test.skill.attach/detach`, `test.tool.pick`, `test.model.warm` (disabled-with-reason on no-op runners), `test.history.restore`, `test.promote` — all runs retries:0.

**Files:** `api/static/js/library/test-pane.js`, `api/static/js/library/plugins.js`, `api/static/js/library/mcp.js`, `api/static/index.html`, `api/static/js/main.js`, `tests/ui/test_test_pane.py`
**Verify:** tests/ui green incl. new pane markup test and existing plugin-tester selectors; MCP Test tab renders via the shell slot; non-slow e2e set unchanged; manual worked example: Library>Plugins>websearch Test tab loads masked settings (L0), tool form from schema (L3), Run returns results+latency with '1 override' chip, Promote writes merged settings through the now-gated route; composer step test passes temperature/max_tokens.
**Commit:** `Add TestPane layered test harness wired into Library shell`

### LB2-U1 — Hook prompt kind, meta sidecars, gated prompt writes
**Deliverables:**
- `hook` added to PromptKind → user-layer `prompts/hooks/<id>.md`; frontmatter {stage, target, config, tags, intended_output}; save-time validation: stage ∈ the five StepHooks step-scoped stages and matches the builtin's declared stage; config keys vs inspect.signature (read-only imports from api/hooks/builtins — 10 builtins).
- `api/services/prompt_meta.py` — sidecar `<id>.meta.json` CRUD in the owning layer (tags, category, technique, intended_output, model_fit, input/output_scope, token_estimate); taxonomy constants shared with LB4/LB6; PATCH `/{kind}/{pid}/meta` atomic (copy-on-write for oob); delete unlinks sidecar; listing ignores sidecars (guard test).
- POST `/api/prompts/hook/{pid}/test` — factory instantiation + optional validate_output dry-run on sample text via synthetic HookContext.
- require_master_key on all existing prompt write routes (reads stay open).
- Seed hook presets in repo `prompts/hooks/` derived from the three shipped `workflows/xdm-*.yaml` hook blocks; custom api/hooks/custom hooks listed read-only as always-on.
- UI: Hooks group in prompts adapter, meta editor (`prompts.meta-edit/meta-save`), hook test pane (`prompts.hook-test`), copy-hooks-YAML action (`prompts.copy-hook-yaml`), token-estimate chip vs model context, intended_output + I/O scoping fields in detail.

**Files:** `api/routers/prompts.py`, `api/services/prompt_meta.py`, `prompts/hooks/`, `api/static/js/library/prompts.js`, `api/static/index.html`, `tests/test_prompts_hooks.py`
**Verify:** pytest tests/test_prompts_hooks.py -q: hook CRUD roundtrip in user layer, bad stage/config rejected 400, meta sidecar write/patch/delete-unlink, listing ignores sidecars, writes 401 with auth on, hook test returns HookResult action/feedback on sample; engine files untouched; parity/ui green.
**Commit:** `Add hook prompt kind, meta sidecars, and master-key prompt writes`

### LB2-U2 — Shared discovery fetcher, prompt digest, recommender
**Deliverables:**
- `api/services/discovery_fetch.py` — ONE shared fetcher: allowlist from discovery_sources.json read at fetch time, manifest-first diff, sha-pinned raw fetches, GitHub rate-budget fail-soft with remaining-quota surfaced, **whole-digest atomic replace with prior-file diff (no tombstones)**, license gate (proprietary/unknown/community ⇒ pointer-only).
- `api/services/prompt_digest.py` — prompt normalizer for anthropics/claude-cookbooks (registry.yaml), openai/openai-cookbook (registry.yaml), google-gemini/cookbook (git trees); **hookify source omitted** (no rule files ship in that repo); persists `data/discovery/prompt_digest.json`.
- Routes: GET `/api/prompts/discover` (read-open; persisted digest + `fetched_at` staleness stamp, never fetches), POST `/discover/refresh` (require_master_key, operator button), POST `/discover/{digest_id}/install` (wizard-backed; copies body into the user layer, writes provenance sha into the sidecar, hard-blocks non-permissive licenses).
- GET `/api/prompts/recommend` — deterministic scorer (tags∩task + model_fit vs role classes + size-fit vs context_window) with per-factor breakdown; POST `/api/prompts/recommend/explain` — Ask Enclave via ModelResolver+OllamaService, default role fast, operator-selectable, retries:0, local-only.
- UI: Discovered sidebar tab with diff badges (digest sha vs installed provenance), Refresh button, wizard install flow, recommend rail + Ask Enclave button, test-run through test-step (labeled model+prompt only); data-actions `prompts.tab/discover-refresh/install/recommend/ask-enclave/test-run`.

**Files:** `api/services/discovery_fetch.py`, `api/services/prompt_digest.py`, `api/routers/prompts.py`, `api/static/js/library/prompts.js`, `api/static/index.html`, `tests/test_prompt_digest.py`, `tests/test_discovery_fetch.py`
**Verify:** pytest tests/test_discovery_fetch.py tests/test_prompt_digest.py -q with mocked HTTP: manifest-diff fetches only changed bodies, GET /discover performs zero network calls and carries fetched_at, offline serves persisted digest, proprietary/unknown license install blocked 403, refresh 401 without key, recommend scorer deterministic and size-fit respects context_window; test asserts discovery_fetch.py is invoked ONLY from `*/refresh` route call sites (scoped to the new module — pre-existing skills/mcp/HF read-fetches are follow-up #15); parity/ui green.
**Commit:** `Add shared discovery fetcher, prompt digest, and hybrid recommender`

### LB3-U1 — Skills backend: tree, file, relations, promote
**Deliverables:**
- GET `/api/skills/tree/{skill_id}?plugin_id=` (registration entry + declared file + optional skills/<id>/ dir; _ID_RE + containment; single-file skills render an honest one-node tree).
- GET `/api/skills/file` (path-segment charset allowlist + containment against the plugin dir).
- GET `/api/skills/relations/{skill_id}` (host plugin, workflows scan of step.skills + skill_injector configs with short TTL cache, trigger keywords, honest empty agents).
- POST `/api/skills/{skill_id}/promote` — copy SKILL.md + registration into user-layer `user-skills` plugin (optional target_plugin_id), 409 on exists, atomic, then scan_plugins().
- All require_master_key, never 500 (empty lists on scan errors).

**Files:** `api/routers/skills.py`, `api/services/plugin_service.py`, `tests/test_skills_tree.py`
**Verify:** pytest tests/test_skills_tree.py -q: tree/file containment rejects traversal (../, absolute, bad charset), single-file skill renders one-node tree, relations returns referencing xdm workflows, promote 201 then 409 and promoted skill visible after scan; parity green.
**Commit:** `Add skills tree, file, relations, and promote backend routes`

### LB3-U2 — Skills library panel on the shell
**Deliverables:**
- `#tab-admin-skills` rebuilt on LibraryShell, adapter **auth:'admin'** (backend fully gated — honest tier): Installed (per-plugin groups) / Discovered (Bundled/Marketplace/Remote from /api/skills/discover) tabs; visible Refresh (skills/discover + skills-marketplace refresh, retries:0).
- Calm row-cards via the LB0 row contract (icon, name, one-line desc, ≤3 trigger chips +n, one source badge); container ids kept, classes added not renamed.
- Detail tabs Overview/Files/Relations/Examples/**Test** (LB1 skill adapter via adapter.testPane — dry-run matched skills/keywords/injected text; `skills.test` action).
- Install (target-plugin) and Import-URL flows through **LibraryWizard** (endpoints byte-identical, window.prompt() retired); Edit/Uninstall/Seed-chat/Browse/New preserved; **Promote** action (`skills.promote` → LB3-U1 route, Confirm-gated); explicit admin-auth headers pattern.
- `js/library/skills-data.js` shared loader feeding shell AND Composer skills bench (drag-attach payload unchanged, ui-tested); `#skills-tab-discover-mount` + SkillsDiscoverShare/CatalogPage relocation kept alive; local esc() shadow deleted.
- data-actions: `skills.side-tab/group/select/dtab/file/test/promote/refresh-discovery/install/import/browse-repo/create/edit/save/cancel/uninstall/seed-chat`.

**Files:** `api/routers/skills.py` (wiring only), `api/static/js/library/skills.js`, `api/static/js/library/skills-data.js`, `api/static/js/library/discover.js`, `api/static/js/main.js`, `api/static/index.html`, `tests/ui/test_skills_shell.py`
**Verify:** ui tests: calm cards render from the row contract, Test tab shows dry-run output, promote action Confirm-gates and calls the route, wizard replaces prompt() flows against identical endpoints, Catalog page discover relocation still binds, Composer bench drag-attach payload identical; parity + 14-failure e2e baseline unchanged.
**Commit:** `Rebuild Skills library on shell with test pane, promote, wizard`

### LB4-U1 — Hardware profile service, model metadata, fit scoring, gated writes
**Deliverables:**
- **Extract** `HARDWARE_PROFILES` / `_host_ram_gb()` / `detect_hardware()` from `api/routers/inventory.py` (:47/:80/:105) into new `api/services/hardware_profile.py`; router consumes the service, behavior-identical (existing inventory tests pin it).
- MODEL_REGISTRY field extensions (quant, params_b, arch_family, context_tokens, size_gb, min_arch incl. optional min_compute_capability, task_tags) for **every registry entry** (19 today; test iterates MODEL_REGISTRY.items(), no count literal); MODELS.md tables updated in the SAME commit (sync hook).
- `api/config/model_meta.json` curated sidecar (per-arch-class tok/s expectations seeded from the BD790i Blackwell NVFP4 catalog, vram notes, per-intent configs — repo-shipped, COPY'd tree) merged additively into GET `/api/inventory/enrichment`.
- `api/services/model_fit.py` — pure fit service: budget from `detect_architecture().per_pool_gb` (gpu classes) else `hardware_profile.detect_hardware()["max_model_ram_gb"]`; required = size_gb×(1+KV_HEADROOM_PCT); classes good/tight/no-fit incl. min_arch check; never raises; fit fields on `/api/inventory/catalog` (fits_ram retained).
- GET `/api/inventory/recommendations?intent=` — task→role→role_fit × fit-class ranking, includes not-installed catalog models flagged for Pull.
- PATCH `/api/inventory/model/{name}/tags` — :path converter, charset allowlist `^[A-Za-z0-9_.:/\-]{1,128}$`, flat dict store `data/config/model_tags.json`, atomic, require_master_key.
- require_master_key on `/api/inventory/{pull,remove,unload,discover/refresh}`; agents[] relations added to GET `/api/inventory/model/{name}` via agents/*.yaml scan.

**Files:** `api/services/hardware_profile.py`, `api/services/model_fit.py`, `api/routers/inventory.py`, `models/download.py`, `MODELS.md`, `api/config/model_meta.json`, `tests/test_model_fit.py`, `tests/test_inventory_meta.py`
**Verify:** pytest tests/test_model_fit.py tests/test_inventory_meta.py -q: NVFP4 on cpu_x86 = no-fit, good/tight thresholds, fit never raises on detection failure, every MODEL_REGISTRY entry carries the new fields (iteration, no literal), tags PATCH accepts nvidia/Qwen3-8B-NVFP4 and rejects bad charset, recommendations ranked, inventory writes 401 with auth on, hardware-profile extraction behavior-identical (existing inventory tests green); models-md-sync hook satisfied; full parity/ui run green.
**Commit:** `Extract hardware profiles, add model metadata and fit scoring`

### LB4-U2 — Models library master-detail panel
**Deliverables:**
- `api/static/js/library/models-panel.js` — `#models-shell` on tab-inventory via LibraryShell adapter: grouped Installed/Available/Discovered rows with fit dot, runner badge, task-tag chips (LB0 row contract); `#inv-count` fed.
- **Hidden legacy holder:** `#inv-stats`/`#inv-grid`/`#discover-section` parked in a hidden holder div inside tab-inventory (ids unchanged); `CatalogModelsShare.showInModelsTab()` retargeted to return nodes to the holder — Catalog-page relocation and Admin Catalog keep binding; exactly ONE visible models surface on the tab, no double `/api/inventory` load.
- Detail sections: Summary, Weights architecture (registry fields joined with filtered model_info; vLLM/NVFP4 degrades to registry fields, never empty), Performance (per detected arch class from api/config/model_meta.json), Hardware fit (score + per-pool breakdown, labeled load-fit), Relations (workflows + agents), **Recommended prompts** (GET /api/prompts/recommend?model= with per-factor breakdown + LibraryShell.open jump).
- Inline tag editor → PATCH tags (AdminAuth headers); intent dropdown → /recommendations highlights ranked rows with Pull affordance on not-installed; operator-triggered discover refresh button; pull/remove/review flows reused (retries:0, Confirm on remove); models.test seeds LB1 TestPane model adapter (Warm disabled-with-reason on vLLM-pinned).
- data-actions: `models.select/pull/remove/review/test/edit-tags/intent/refresh-discover`.

**Files:** `api/static/js/library/models-panel.js`, `api/static/js/library/models.js`, `api/static/js/main.js`, `api/static/index.html`, `tests/ui/test_models_panel.py`
**Verify:** tests/ui: exactly one visible models surface on tab-inventory, legacy nodes still relocate to the Catalog page and return to the hidden holder, NVFP4 detail shows populated Weights from registry fields, fit dot classes match /catalog fit payload, Recommended prompts section renders scorer output; parity + non-slow e2e baseline unchanged; manual: pull progress and remove Confirm work from both shell and Catalog grid.
**Commit:** `Add Models library panel with hidden legacy holder and fit UI`

### LB5-U1 — Claude marketplaces digest + Plugins Discovered tab
**Deliverables:**
- `api/services/discovery_providers/claude_marketplaces.py` — real provider over discovery_fetch (replaces stub): allowlisted pinned sources (claude-plugins-official, claude-code, skills, knowledge-work-plugins; discovery_sources.json is the only override), **manifest resolution ladder: `.claude-plugin/marketplace.json` → per-plugin `.claude-plugin/plugin.json` enumeration**, pointer-only records with per-record license + component counts + version-resolution ladder, persisted `data/discovery/plugin_digest.json`, added/changed sha diffing vs prior file; fetch only on POST `/api/discover/claude-marketplaces/refresh` (already gated).
- Plugins panel adopts LibraryShell: Installed (layer chip + version badge from existing records, data-id selection replacing title-includes matching) / Discovered sub-tabs; AdminAuth hard gate preserved.
- Discovered actions: View manifest, Import skills (license surfaced first, bridges via POST /api/skills/import), Seed wizard (pre-fills description); diff badges from persisted digest.
- LOCAL CAPABILITY BUNDLE kind banner + "External integration? → MCP" cross-link via LibraryShell.open; inline-onclick AssetPeek button replaced only on newly rendered rows.
- data-actions: `plugins.sub-tab`, `plugins.refresh-digest`, `plugins.import-skills`, `plugins.seed-wizard`, `plugins.goto-mcp`.

**Files:** `api/services/discovery_providers/claude_marketplaces.py`, `api/services/discovery_providers/stubs.py`, `api/services/discovery_providers/__init__.py`, `api/static/js/library/plugins.js`, `api/static/index.html`, `tests/test_plugin_digest.py`, `tests/ui/test_plugins_shell.py`
**Verify:** pytest tests/test_plugin_digest.py -q with mocked HTTP covering BOTH manifest shapes: digest persisted atomically, offline serves last digest, added/changed diff correct, malformed manifest fails soft to persisted digest, proprietary-licensed skill import surfaces license; ui: sub-tabs render behind AdminAuth gate, data-id selection works, cross-link opens MCP; parity/ui/e2e baselines green.
**Commit:** `Add Claude marketplaces digest provider and Plugins Discovered tab`

### LB5-U2 — Plugin file management, versioning, reload flow
**Deliverables:**
- GET `/api/plugins/{id}/files` (relative paths), GET/PUT `/api/plugins/{id}/files/{path}` — user layer only (403 system, mirroring uninstall), path containment, atomic writes, require_master_key.
- plugin_service list_files/write_file helpers with containment; plugin.yaml saves YAML-validated (400 on malformed) so scan_plugins cannot be broken by a bad edit.
- Version policy: plugin.yaml version is source of truth; patch auto-bump on FIRST save since last reload (dirty flag), explicit version in body always honored; PUT responses {version, reload_required:true}.
- UI: detail Files tab (async section renderer) with editor, Reload badge after edit/install firing POST /api/plugins/reload (toast counts, re-select current plugin); tarball reinstall response includes {replaced_version} for a downgrade confirm; Confirm-gated delete kept.
- data-actions: `plugins.file-open`, `plugins.file-save`, `plugins.reload`, `plugins.delete`.

**Files:** `api/routers/plugins.py`, `api/services/plugin_service.py`, `api/static/js/library/plugins.js`, `api/static/index.html`, `tests/test_plugin_files.py`
**Verify:** pytest tests/test_plugin_files.py -q: system-layer PUT 403, traversal rejected, malformed plugin.yaml save 400, version bumps once per reload cycle across multiple saves, explicit version honored, reload re-registers edited skill on live singleton; parity green; manual: edit a user skill file, badge appears, reload picks it up in chat tester.
**Commit:** `Add plugin file management, version bump, and reload flow`

### LB5-U3 — Plugin creation wizard (local-model forge)
**Deliverables:**
- `api/services/plugin_forge.py` — PluginForgeService: NL description → spec draft → file set via local OllamaService+ModelResolver (spec_capture pattern: JSON-only system prompt, tolerant parse, deterministic fallback = one skill zero tools); skills-only by default, tools/*.py generation behind explicit opt-in with denylisted-imports lint.
- `api/models/plugin_models.py` — PluginSpecDraft / PluginFileSet / PluginFileWrite schemas.
- POST `/api/plugins/scaffold/spec`, `/scaffold/generate`, `/scaffold/install` — all require_master_key; install: 409 on existing id, _ID_RE charset allowlist on plugin/tool/skill ids, every path resolved+contained under user_dir/<plugin_id>, atomic writes, then scan_plugins().
- LibraryWizard flow with MANDATORY per-file review/edit screen before install (tool code runs in-process); wizard seedable from digest records (plugins.seed-wizard).
- data-actions: `plugins.wizard-open/-spec/-generate/-install` (all retries:0).

**Files:** `api/services/plugin_forge.py`, `api/models/plugin_models.py`, `api/routers/plugins.py`, `api/static/js/library/plugins.js`, `api/static/index.html`, `tests/test_plugin_forge.py`
**Verify:** pytest tests/test_plugin_forge.py -q: fallback spec when model unavailable, install 409 on existing id, containment rejects escaping file paths, bad ids rejected, denylist lint flags forbidden imports, installed plugin visible after scan_plugins; manual: wizard end-to-end creates a skills-only plugin usable in chat after reload; parity/ui green.
**Commit:** `Add plugin creation wizard backed by local-model forge service`

### LB6 — Task Menu library + Composer bench feed
**Deliverables:**
- `api/routers/tasks.py` registered in main.py: TaskSchema CRUD over `user_storage_root/tasks/<id>.json` (no phantom repo fallback), _ID_RE + containment, atomic writes, writes require_master_key, reads open; GET supports ?tag=&pattern=.
- POST `/api/tasks/{id}/render` via PromptComposer (resolves refs.role_ref/template_ref); ref validation: missing prompt ids 400, hook names vs 10-builtin factory = non-fatal warning field.
- GET `/api/tasks/discover` (read-open, **never fetches**): merges curated `api/config/tasks_catalog.json` (13 dfStepTemplates as source:builtin seeds — main.js statics untouched) + last persisted `data/discovery/tasks_digest.json` with fetched_at staleness stamp; POST `/api/tasks/discover/refresh` (require_master_key, visible button) fetches the remote catalog URL governed by discovery_sources.json, fail-soft; POST `/discover/{id}/install` user-layer copy with installed annotation.
- Tasks nav tab + `#tab-tasks` on LibraryShell: `js/library/tasks.js` — role-grouped list, `#tasks-count` badge, detail (kv, instruction pre, pattern-affinity + tag chips, intended_output, clickable prompt/hook refs via LibraryShell.open), in-place edit, Confirm delete, **wizard-backed create**, render preview, LB1 step-adapter Test (labeled prompt-only); switchTab dispatch additive.
- **Composer bench feed (frozen-statics mechanism):** module-scoped `dfLibraryTemplates` Map; `fetchComposerTasks()` (ES-module import, no window global) appends library rows under a single "Library" divider AFTER the 13 statics, deduped with statics winning, fail-soft to a byte-identical palette on any error (incl. tasks API absent); library rows use `bench.inspect-library-task` (Map-resolved inspector) + `application/df-library-task` drag MIME; additive drop-handler branch + `tasks.send-to-composer` call new `dfAddNodeFromLibraryTask(schema,x,y)` (mirrors dfAddNodeFromTemplate's body, registers via the dfAddPatternNode seam); `dfStepTemplates`, `bench.inspect-template`, the length-1 'custom' fallback (main.js:7989), and the role-scan restore (main.js:10012) are untouched.
- data-actions: `tasks.select/new/create-save/create-cancel/edit/save/cancel-edit/delete/render/test/send-to-composer/open-ref/discover-refresh/install`; `bench.inspect-library-task`.

**Files:** `api/routers/tasks.py`, `api/main.py`, `api/config/tasks_catalog.json`, `api/static/index.html`, `api/static/js/library/tasks.js`, `api/static/js/main.js`, `tests/test_tasks_router.py`, `tests/ui/test_tasks_tab.py`
**Verify:** pytest tests/test_tasks_router.py -q: CRUD roundtrip, 409 on create-exists, containment rejects bad ids, writes 401 with auth on, render resolves refs and 400s on missing prompt id, hook warning non-fatal, GET /discover performs zero network calls and carries fetched_at, refresh 401 without key, install annotates; ui: dfStepTemplates.length === 13 with last key 'custom' after feed load, 13 static rows byte-identical, library rows under divider with their own action ids, API-down palette identical to pre-LB6, dedupe favors statics, drop of a library card creates a node via dfAddNodeFromLibraryTask; full parity + non-slow e2e 14-failure baseline unchanged — final gate for the whole Library program.
**Commit:** `Add Task Menu library with refresh-only discovery and bench feed`

---

## Critique resolutions (all 33)

IDs: F* = feasibility/parity critic, C* = completeness/half-baked critic.

| # | Issue | Resolution |
|---|---|---|
| F1 | BLOCKER: LB6 bench feed breaks dfStepTemplates invariants either way | dfStepTemplates frozen; module-scoped dfLibraryTemplates Map + dfAddNodeFromLibraryTask (via dfAddPatternNode seam), own action id `bench.inspect-library-task` + own drag MIME; ui test pins length===13, 'custom' fallback, and API-down byte-identical palette (LB6) |
| F2 | Models tab renders two surfaces (showInModelsTab vs #models-shell) | Legacy nodes parked in hidden holder inside tab-inventory, showInModelsTab retargeted to it (ids unchanged); ui test: one visible surface + Catalog relocation intact (LB4-U2) |
| F3 | POST /api/inventory/settings/search ungated secrets write | require_master_key added in LB1-U1 (test.promote depends on it) + 401 test; UI already on global auth fetch wrapper |
| F4 | LB6 TTL-on-read egress + unsatisfiable LB2-U2 verify grep | GET /api/tasks/discover never fetches; POST /discover/refresh gated behind visible button; LB2-U2 verify rescoped to discovery_fetch.py call sites; pre-existing skills/mcp/HF read-fetch migration = follow-up #15 |
| F5 | User prompt content written into repo prompts/ (wiped on rebuild) | Two-layer prompts: repo oob + user_storage_root/prompts/ user layer; all writes land user-side, oob PATCH = copy-on-write; promote gets a real target (LB0-U3) |
| F6 | Curated artifacts under data/ shadowed by the volume | oob_manifest.json, model_meta.json, tasks_catalog.json move to api/config/ (COPY'd tree); data/ reserved for runtime-mutable state; pre-existing data/discovery seeds gap = follow-up #16 |
| F7 | detect_hardware() cited as service API; lives in a router | Verified: detect_hardware() exists at api/routers/inventory.py:105 — extraction of HARDWARE_PROFILES/_host_ram_gb/detect_hardware into api/services/hardware_profile.py is a named LB4-U1 deliverable; model_fit stays pure |
| F8 | "all 18 entries" — registry has 19 | Reworded to "every MODEL_REGISTRY entry"; test iterates items(), no count literal (LB4-U1) |
| F9 | Phantom repo tasks/ legacy fallback | Dropped; user_storage_root/tasks/ + api/config/tasks_catalog.json cover both layers (LB6) |
| F10 | hookify *.local.md source yields zero records | hookify cut from v1 allowlist; hook presets seeded from the three shipped xdm workflow hook blocks (LB2) |
| F11 | "byte-identical" contradicts shell anatomy + pinned e2e selectors | Contract restated as endpoint-and-action-identical; .mcp-row retained with .lib-row added; test_prompts_library.py named in LB0-U1 verify |
| F12 | Skills "optional" auth tier claims degradation the backend forbids | Skills adapter marked auth:'admin' (backend fully master-key gated) — honest, tested (LB3-U2) |
| F13 | Repo-root marketplace.json 404s on all four sources | Manifest resolution ladder: .claude-plugin/marketplace.json → per-plugin .claude-plugin/plugin.json; both shapes in mocked fixtures (LB5-U1) |
| F14 | Phantom ENCLAVE_PLUGIN_MARKETPLACES env; stray models.js in LB3 files | Env var dropped — discovery_sources.json is the only plugin-marketplace override (LB0-U2); models.js removed from LB3 file list |
| C1 | BLOCKER: list() row shape can't express LB3/LB4/LB5 rows | Contract extended with optional icon/chips/badges/dot + renderRowExtras escape hatch; fixture contract test exercises every field before any dependent track (LB0-U1) |
| C2 | Skills Test pane missing — backend without UI | Test subnav via adapter.testPane (LB1 skill adapter) + skills.test action + verify line added (LB3-U2) |
| C3 | agent/mcp-tool TestPane adapters have no mount | mcp.js wires adapter.testPane in LB1-U2 (files list updated); agent adapter moved to Agents-migration follow-up #1 — no orphaned code ships |
| C4 | Recommender promises model-side "recommended prompts" that LB4 cuts | Built (option a): Recommended prompts section in LB4-U2 model detail via GET /api/prompts/recommend?model= — sequencing permits (LB2-U2 lands first); contradiction deleted |
| C5 | Skills promote promised in prose, absent from units | Built: POST /api/skills/{skill_id}/promote in LB3-U1 + skills.promote action/Confirm in LB3-U2 + tests |
| C6 | LibraryWizard reduced to one consumer (A5 thinned) | Wizard-backed flows named per track: prompt digest install (LB2-U2), skills install/import (LB3-U2), forge+seed (LB5-U3), task create (LB6), MCP env keys (LB1-U2); model pull = explicit named carve-out #18 |
| C7 | GET /api/tasks/discover egress on read; HF "interval" reads as poller | Same fix as F4; HF knob renamed/defined as cache TTL applied to operator-triggered refreshes only (LB0-U2) |
| C8 | 'workflow' kind silently dropped from "every kind" claim | Conceptual model scoped to the six v1-migrated kinds; "Workflows adapter on the shell" = named follow-up #2 |
| C9 | GET /api/discover/config shadowed by /{source} catch-all | /config registered before the catch-all + 'config' reserved + explicit test (LB0-U2) |
| C10 | Warm endpoint wraps OllamaService only — dead for flagship vLLM NVFP4 | Warm rides Runner.load() (runner.py:~222), returns {runner, load_duration_ms}; Warm button disabled-with-reason on no-op runners (LB1-U1/U2) |
| C11 | Registry count drift (18 vs 19) — duplicate of F8 | Same fix as F8: iterate, never count |
| C12 | Dead 'version' verb in actions enum | Removed from the v1 verb enum; version rendered as row/header metadata badge; verb returns with follow-up #8 |
| C13 | MCP marketplace env-key prompt() never migrates | Folded into LB1-U2: LibraryWizard Secrets step replaces it (MCP already on the shell) |
| C14 | detail(id) static payload contradicts lazy subnav + per-node fetches | Sections may be async (mountEl)=>render fns invoked on first activation — documented in LB0-U1; LB3 Files/LB5 Files ride it |
| C15 | No programmatic cross-kind navigation | LibraryShell.open(kind,id) added in LB0-U1; tasks.open-ref, plugins.goto-mcp, recommend rail ride it |
| C16 | YAGNI: MCP warm-session pool + TTL reaper | Cut from LB1-U1; stateless invoke serves v1; pooling deferred to follow-up #5 gated on measured latency |
| C17 | YAGNI: append-only digests with tombstones | Cut; whole-digest atomic replace + prior-file diff at refresh time (LB2-U2) |
| C18 | LB3 one oversized gated unit | Split: LB3-U1 backend (tree/file/relations/promote) + LB3-U2 panel |
| C19 | No sidebar filter for large lists | Client-side filter input in the LB0-U1 shell sidebar (lib.filter); every kind inherits |

## Deferred (named follow-ups)

1. **Agents panel migration** onto the shell (+ agent TestPane adapter registration + CatalogPage agent-tile de-duplication).
2. **Workflows adapter on the shell** (Kanban/workflow-index coexistence) — completes the A1 kind set.
3. AssetPeek kind extensions / retirement of bespoke overlays and DOM relocators.
4. Composer hook authoring: `_dfCleanStep` hooks serializer + inspector attach UI.
5. Server-side saved test suites (generalizing `/api/agents/{id}/evaluate` cases) + MCP warm-session pooling if latency measurements demand it.
6. Generic per-plugin config store (`GET/PUT /api/plugins/{id}/config`).
7. Multi-file external skill directory install (rides the LB5 fetcher; tree endpoint already renders dirs).
8. Plugin version history/rollback + signed-manifest marketplace; 409-unless-force reinstall; reintroduce the `version` action verb.
9. Community marketplace tier.
10. Model promote target (per-model overrides file) — until then model `test.promote` stays disabled.
11. Per-skill enable/disable flag (plugin.yaml registration IS enablement in v1).
12. Tasks external digest ingestion via the shared prompt/cookbook fetcher.
13. Registry curation loop for operator tag overrides (`model_tags.json` → MODEL_REGISTRY is manual until then).
14. Plugin data-dir (`PLUGIN_DATA`-style persistent state) adoption.
15. **Migrate pre-existing TTL-on-read fetches to refresh-only** (`skills.py:44`, `mcp.py:58`, HF discovery on `GET /api/inventory/discover`) so the no-background-egress posture holds platform-wide, not just for new code.
16. **Ship pre-existing curated seeds via the COPY'd tree** (`data/discovery/mcp_catalog.json`, `skills_catalog.json`, `model_benchmarks.json` are git-tracked but never reach containers — Dockerfile does not COPY `data/`).
17. Global read-route auth sweep.
18. Model pull flow onto LibraryWizard (the one named A5 carve-out in v1).
