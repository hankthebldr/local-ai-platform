# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · SemVer: [semver.org](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Two independent workstreams in flight; either can cut first. **Chat-led
Composer + the Enclave design-system rebrand** (branch `feat/chat-led-composer`)
— a candidate `1.2.0` UX cut — and **Architecture-aware orchestration**
earmarked for `1.3.0`.

### Fixed — Fail-safe persistence & resume (next-wave Theme A)

> Retires the top continuous-improvement finding of the 2026-07-12 next-wave
> backlog (`docs/roadmap/2026-07-12-next-wave-backlog.md`): three surfaces
> persisted a local-model **failure sentinel as durable success**. One
> convention now holds everywhere (see CLAUDE.md → Conventions): *never write
> a failure sentinel to a durable store; never return HTTP 200 on a
> local-model exception.*

- **Composer `resume-from-failed` zombie + 500 (P1).** The route flipped the
  run to `running` and checkpointed *before* the engine tried to reload
  `workflows/<id>.yaml`; for an unsaved Composer run that raised
  `FileNotFoundError` (an `OSError`, not the `ValueError` being caught) →
  HTTP 500 with the run stranded neither failed nor resumable. Now the
  definition is resolved **first** (`_load_resume_definition`: saved yaml,
  private overlay first, else the new inline sidecar), a run with none is a
  clean 404 that leaves the snapshot untouched, an invalid one is 422, and if
  `engine.resume` itself blows up the pre-flip snapshot is restored
  (`_resume_or_restore`). `resolve_approval` gets the identical treatment (a
  missing definition leaves the gate pending + undecided).
- **Inline definition sidecar.** `prepare_run` now persists the originating
  inline definition as `data/workflows/<run_id>/definition.json` (atomic,
  best-effort, next to `origin.json`) so unsaved "Run ▶ live" runs can be
  Fix&Resume'd; `read_definition_sidecar` is the resume-side reader. Runs
  started from a saved yaml write no sidecar.
- **Research `graph-walk` persist-error-as-success (P1).** On a model outage
  the claimed node was marked `done`, the failure string written as a store
  note + MOC section + RAG-ingested, and `requeue_stale` (in_progress only)
  could never retry it. Now the item is set to `error`, nothing durable is
  written, the call surfaces the model's 503, and a new `retry_errors`
  request flag (backed by additive `WorkspaceIndex.requeue_errors()`)
  requeues errored items once the box is healthy — no hot-loop on a
  persistently failing node.
- **Research `followup` / `compare-node` error persistence (P2).** A model
  exception returned 200 with `_Answer unavailable — …_` / `_Comparison
  unavailable — …_`, appended as a durable session turn (+ MOC +
  ConversationStore mirror) or saved/ingested as a note. Both now raise
  `503` with `X-Enclave-Error: model_unavailable` via a shared
  `_chat_or_503` helper; nothing is persisted; the existing UI handlers
  already toast on non-2xx.
- **`/api/research` scope gate.** The prefix had no `SCOPE_MAP` entry, so any
  valid key could write the shared `research` workspace + trigger the
  operator-ticked web egress when auth was on. Now rides the `workspaces`
  scope, parity with `/api/workspaces` (which writes the same store).
- Tests: `tests/test_resume_from_failed.py` (rewritten around the load-first
  contract; sidecar round-trip; restore-on-blow-up), failure-path coverage in
  `tests/test_research_rx2.py` / `tests/test_research_session.py`, the scope
  gate, and `WorkspaceIndex.requeue_errors` in `tests/test_workspace_index.py`.

### Added — Gap-closure: provenance, persistence & capabilities (`feat/chat-led-composer`)

> Closes the highest-priority findings from the 88-gap flow audit
> (`docs/research/2026-06-17-flow-gap-audit.md`). Plan:
> `docs/plans/2026-06-17-gap-closure-implementation.md`.

- **Provenance & citation rail (the #1 gap).** Every grounded chat answer now
  records *what* it was grounded on. New `ProvenanceEdge` / `ResponseProvenance`
  models (`api/models/provenance_models.py`), a durable
  `provenance_store.py` (atomic header JSON + append-only edge JSONL under
  `data/provenance/`), emission at the chat response site for RAG chunks /
  web sources / activated skills / plugin tools (`api/routers/chat.py` — each
  response now carries a unique `chatcmpl-…` id + a `provenance` summary, and
  streamed replies emit a `provenance` SSE event), `GET /api/provenance/
  response/{id}` + `/responses` (`api/routers/provenance.py`), a chip-rail UI
  under each chat message (`renderProvenanceRail`), and response→source
  grounding edges (`grounded_on` / `activated_skill` / `invoked_tool`) in the
  knowledge graph (`graph_service._build_provenance_nodes`).
- **Durable chat threads.** The Threads switcher persists server-side and
  survives reload: `SavedConversation` model + `conversation_store.py`
  (one JSON per thread under `data/conversations/`) + `POST/GET/DELETE
  /api/conversations` (`api/routers/conversations.py`). The UI Threads module
  autosaves the live thread, hydrates transcripts lazily on switch, and adds
  thread delete — localStorage stays as the offline fallback.
- **Server-side agent tuning.** Up/down message ratings that tune a composer
  agent now persist + aggregate across sessions via `POST/GET
  /api/feedback/agent-tuning` (keyed `data/feedback/agent_tuning.json`); the
  client `AgentTuning` mirrors to the server and adopts the server map on load.
- **Composer ↔ capabilities.** Node config gains a Tools & Skills section
  (plugin/MCP tool + skill chips that round-trip through the YAML export),
  inline archetype **companion suggestions** (`/api/workflows/composer/assist`)
  with one-click add, agent tool-reachability validation
  (`AgentService._validate_tools` reusing the workflow extension-preflight, 422
  on missing plugin/MCP), and an Ollama-down banner that disables dispatch.
- **Run observability.** Composite runs (parallel / loop / ralph / orchestrator)
  now render a kind badge + a workspace-derived summary (iteration / branch /
  worker counts, ralph halt reason + consecutive-failure + goal signals) and
  an `ext overhead` chip in the run-step detail. (MCP `invoke_tool(scope=)` and
  the ralph hard-cap safety rails were already wired in the engine — this
  surfaces them; composite **authoring** on the canvas remains in the YAML
  editor, deferred because the strict container validators can't be satisfied
  from a single flat node.)
- **Runner field on the model registry.** `MODEL_REGISTRY` entries may declare
  an optional `runner` (`ollama` default; `vllm` for the GPU path), surfaced on
  the inventory catalog so the resolver can route per-model.

### Added — Chat-led Composer & Enclave design-system rebrand (`feat/chat-led-composer`)

> "A workflow is crystallized conversation." The Composer becomes chat-primary:
> converse to solve a problem, then promote the thread into a local agentic
> workflow. Plus a full rebrand off the PANW-Cortex skin to Enclave's own
> warm-charcoal + teal identity (design system vendored at `docs/design/`).

- **Chat-led "Boot Sequence" (composer).** An in-message affordance
  (`▸ run this with my agents`) distills the thread into an editable spec and
  scaffolds a runnable DAG on the dormant spine. New
  `POST /api/composer/capture-spec` + `POST /api/composer/scaffold`
  (`api/routers/composer.py`) backed by `spec_capture.py` + `scaffold_planner.py`
  (hybrid: curated-template match, else local LLM plan); reuses `OllamaService`
  + `ModelResolver`, never touches the engine. Scaffolded step inputs are
  normalized to real producers so plans actually run.
- **Enclave design-system rebrand.** Cortex green / blue-slate → warm-charcoal
  `#101413` + teal `#2BD4B4` primary + deep emerald + sparing ember; dark +
  light scopes; role palette (reasoning=teal, coding=sky, fast=amber,
  general=emerald, uncensored=ember). Full handoff bundle (tokens, brand assets,
  React component specs, canonical console-v2 prototype) vendored at
  `docs/design/`.
- **In-shell Chat↔Canvas pivot + fluid layout.** `Chat | Canvas | Focus`
  segmented control (`ComposerSplit.setMode`); viewport-fit split; Boot Sequence
  confirm auto-pivots to canvas. Per-step `▶ test in chat` bench in the node
  inspector.
- **Unified asset deep-dives (AssetPeek).** One slide-over drill-down for
  models / agents / plugins — every dive ends in "seed a chat". Models pull
  curated benchmarks from `data/discovery/model_benchmarks.json` via the new
  `GET /api/inventory/enrichment` catalog-enrichment endpoint.
- **Runs reasoning drill-down + calm analytics.** Per-step decisions panel
  (timing anatomy, tokens, pressure, skills/MCP/tools chips) over the telemetry
  the engine already persists; a calm-analytics perf band
  (`enclSparkline` / `enclTrendStat` / `enclUtilChart`) fed by a `_sysHistory`
  ring buffer.
- **Eval harness (`api/services/eval_harness.py`).** Agent/workflow regression
  suites reusing the gate grammar; sample suites under `evals/`.
- **Skills marketplace + installable skills.** GitHub-backed skills.sh discovery
  provider (`api/services/discovery_providers/skills_marketplace.py`);
  installable skills in external discover; Skills tab unified with the Catalog.
- **Composer UX.** Native auto-wire (dropped role/agent pieces chain onto the
  flow), always-present editable Start/End, toolbar Stop control, New-Workflow
  creation wizard, brainstorm→decision starter workflow.
- **Runner attribution.** `/health` and `/v1/models` attribute each model to
  its serving runner (Ollama / vLLM).
- **Tier-3 OpenShell sandbox backend (opt-in).** Extends the code-exec sandbox
  (below) with an OpenShell agent-runtime backend prototype (ADR:
  `docs/plans/2026-06-07-openshell-agent-runtime-decision.md`).

> **Console-v2 backlog — now SHIPPED:** thread switcher, message-level
> pin-as-step + scaffold-preview modal + maturity meter, operator's-path ladder
> + nudges, model-compare grid, 4-phase install wizard, Run lens (scrub +
> node plates + as-executed inspector), node-bound chat (select a node → chat
> with/configure that agent; ratings → per-agent tuning), interactive workflow
> drill-down, vertical chat-top/canvas-bottom layout. Frontend test coverage
> added (tests/ui/, 160 markup tests).
>
> **Remaining gap-closure (in progress, see docs/plans/2026-06-17-gap-closure-implementation.md):**
> provenance edges + citation rail (the #1 gap), server-side persistence
> (conversations + agent tuning), composite-step-kind UI renderers
> (parallel/loop/orchestrator/ralph) + ralph safety signals, node tools/skills
> editing, `runner` field on MODEL_REGISTRY. Deliberate later-cuts: fleet /
> HostRegistration (1.4.x), license entitlement, RBAC/audit-persistence (2.x).

Earmarked for `1.3.0` — Architecture-aware orchestration. The workflow engine
went from "execute steps in YAML order, blind to the hardware" to "schedule a
DAG tick-by-tick on the detected arch, pre-warm next-step models during the
current step's inference, and report hit/miss in the Runs view." Telemetry
(`load_duration_ms`, `pressure_before/after`, per-step `keep_alive_used`) is
captured on every run and aggregated into `RunTelemetrySummary`.

### Added — Run event substrate + dynamic plan

- **Run event substrate (L1).** New in-process `RunEventBus`
  (`api/services/run_event_bus.py`) with an append-only per-run event log
  (`data/workflows/<run_id>/events.jsonl`, monotonic `seq`) and a sync→async
  bridge (`bind_loop` + `call_soon_threadsafe`) so the synchronous, threaded
  engine can publish events that async SSE subscribers tail. `RunEvent`
  envelope + `EventType` taxonomy in `api/models/run_event.py`
  (`run.status`, `step.started`/`step.completed`, `plan.updated`,
  `gate.pending`/`gate.resolved`, `tool.called`, …). Log writes are
  degraded-not-fatal — observability never crashes a run.
- **SSE run stream.** `GET /api/workflows/runs/{run_id}/stream`
  (`text/event-stream`) replays the event log then tails live, with
  `Last-Event-ID` / `?since=` resume and a terminal `stream.end`. Polling
  (`GET /runs/{id}`) is retained as a fallback.
- **First-class dynamic plan (L2, observable).** `WorkflowPlan` / `PlanItem`
  on `WorkflowRun`, projected over the event stream via `plan.updated`
  full-snapshot events (`api/services/run_plan.py`). Seeded from the compiled
  DAG and enriched live as the orchestrator spawns workers and Ralph iterates
  — the implicit plan becomes a visible, revisable structure. The current plan
  is always reconstructable from the log.
- **Live Runs view.** The Cortex Console Runs view subscribes to the stream via
  `EventSource` and renders the live plan + step timeline + run status, falling
  back to polling on stream error.
- _Inspired by OpenWork / OpenCode's session + todo-plan + `/event` model;
  absorbed as native Enclave architecture. Deferred fast-follows: executable
  dynamic planning, cross-run chaining, and a `kind: opencode` event producer._

### Added — Architecture-aware orchestration (Phases 1–5)

- **Phase 1: Detection + abstractions (PR #88).** `Architecture` and
  `Deployment` protocols + per-arch impls: `unified.py` (Apple Silicon /
  x86 CPU), `nvidia_single.py`, `nvidia_multi.py`. Deployment impls cover
  `host_native`, `container`, `dmg`. Detection runs at startup; results
  exposed via `GET /api/system/architecture` (consolidated triple),
  `GET /api/system/pressure`, `POST /api/system/architecture/refresh`.
- **Phase 2: Step telemetry (PR #90).** `StepResult` gains eight optional
  fields: `load_duration_ms`, `prompt_eval_duration_ms`, `eval_duration_ms`,
  `total_duration_ms`, `arch_name`, `pressure_before`, `pressure_after`,
  `keep_alive_used`. Runs view renders a per-step `warm` / `N.Ns load`
  chip. Memory tab gains an Architecture & Pressure card with live VRAM
  / RAM pressure polled every 5s and a "Re-detect" button.
- **Phase 3: Per-step `keep_alive` (PR #91).** Four-tier resolver:
  step.config → workflow.defaults → arch default → env var. Arch-detected
  defaults: unified `"30m"`, NVIDIA `"0"`, unknown `"5m"`.
- **Phase 4a: Scheduler facade + feasibility (PR #91).** `Scheduler`
  wraps `arch.schedule_ready()` + `arch.feasible()`; `AgentStep.est_size_gb`
  optional; validate-time feasibility raises `WorkflowValidationError` on
  oversize steps; new `GET /api/workflows/<id>/schedule-preview` returns
  the per-tick dispatch plan.
- **Phase 4b: Parallel DAG dispatch (PR #92).** Engine's
  `_execute_steps` rewritten as a tick loop. Non-deferred steps in each
  tick run concurrently via `ThreadPoolExecutor`; `OllamaService._LLM_SEMAPHORE`
  serializes at the model layer. Workflows without `depends_on` behave
  identically to pre-Phase-4b.
- **Phase 5: Pre-warm (PR #93).** `OllamaService.pre_warm(model, keep_alive)`
  bypasses `_LLM_SEMAPHORE` and POSTs `/api/generate` with empty prompt +
  `num_predict=0`. Engine fires daemon-thread pre-warms for next-tick models
  between `submit()` and `as_completed`; gated by `arch.transition_plan().pre_warm_next`.
- **Phase 5b: Pre-warm telemetry + opt-out (PR #95).** New `PreWarmEvent`
  model recorded on `WorkflowRun.pre_warm_events`. Hit/miss resolved at
  run completion by matching consuming step's `load_duration_ms < 100`.
  `RunTelemetrySummary` gains `pre_warm_count`, `pre_warm_hits`,
  `pre_warm_misses`, `total_pre_warm_load_ms`. `WorkflowDefaults.disable_pre_warm`
  lets operators turn pre-warm off per workflow.
- **Phase 5c: Pre-warm summary UI (PR #97 — draft).** Colored panel in
  the Runs view between status header and step rows, showing hit ratio +
  overlap cost.

### Added — Composite workflow step kinds

- **`kind: parallel` + `kind: loop` (PR #96).** Fan-out / loop step kinds
  with recursive `branches`, `gather` synthesis step, `body` + `until`
  predicate. Workspace namespacing: `workspace.{parent.id}.branches.{branch.id}`,
  iteration history at `workspace.{loop.id}.iterations.{n}`.
- **Single-model parallelism modes (PR #98).** `ParallelExecutionConfig.mode`:
  `auto`, `multi_model_concurrent`, `single_model_concurrent`,
  `single_model_pseudo_parallel`. Runtime validation that single-model modes
  resolve to one model name. `auto` picks pseudo-parallel for same-model
  branches (prompt-cache reuse), concurrent otherwise.
- **`kind: a2a` (PR #100).** Outbound delegation to external A2A-protocol
  agents via `api/services/a2a_client.py` — fetch the remote Agent Card,
  validate the skill, POST `tasks/send`, poll `tasks/get` to terminal, map
  artifacts onto declared outputs. Bearer-token auth resolved from an env
  var at request time (never in YAML). Enclave's own workflows are already
  advertised symmetrically at `/a2a/.well-known/agent.json`.
- **`kind: orchestrator` (PR #101).** Dynamic lead-agent delegation. The
  planner emits JSON-fenced directives (`spawn_worker` / `complete`) parsed
  by `api/services/orchestrator_protocol.py`; the engine runs each spawned
  worker in an isolated child context and feeds the result back. Budget caps
  (`max_workers_spawned`, `max_planner_turns`, `max_total_tokens`,
  `max_wall_seconds`) + soft-recovery on parse errors / unknown workers /
  missing output keys. Text protocol works on any local model without
  native function-calling.
- **`kind: consolidate` + durable memory (PR #105).** Dreaming-style
  cross-run memory. New `api/services/memory_store.py` with three file-backed
  stores under `MEMORY_DATA_DIR`: `playbooks/<name>.md`,
  `memory/semantic/<concept>.md`, `memory/episodic/<key>.jsonl`. Merge
  strategies `replace` / `append` / `append_with_dedup`. New `$memory.*`
  input accessor (`$memory.playbook.<name>` etc.) readable by any step kind;
  empty store resolves to `""`. `WorkflowContext` carries a non-serialized
  memory handle attached at run start + on resume.
- **`kind: ralph` autonomous loop (PR #106).** Plan → execute → verify →
  reflect, repeated until a halt condition, self-learning via a playbook the
  body reads/writes (`reflect` = a `consolidate` step; `plan` reads it back
  via `$memory.*`). `RalphHalt`: `max_iterations`, `max_wall_seconds`,
  `max_total_tokens`, `max_consecutive_failures` (failure), `halt_file`
  (graceful brake), `goal_gate` (success predicate). Append-only JSONL
  journal enables resume-past-completed-iterations across restarts. Engine
  enforces halt-file / consecutive-failure / hard-budget rails; branch
  isolation + read-only-until-promoted are enclave-code tool-layer concerns.
- **Spec doc (PR #94).** `docs/plans/2026-05-23-multi-agent-workflow-patterns-spec.md`
  documents the full parallel / loop / orchestrator / a2a / consolidate /
  ralph taxonomy. All six step kinds are now implemented (rows 1–15 of the
  spec's plan); remaining items are polish (sharded mode, prompt-prefix
  locking, A2A streaming, composer UI renderers).

### Added — Code-execution sandbox (PR #165)

A `kind: code` workflow step + a `code_exec` chat tool run agent-authored
Python in a tiered, host-detected isolation sandbox — realizing the
"enclave-code tool-layer" / "read-only-until-promoted" concerns flagged in the
ralph/composite work above. Off by default (`CODE_EXEC_ENABLED=false`).
Design: `docs/superpowers/specs/2026-06-03-code-exec-sandbox-design.md`.

- **Backend registry.** `SandboxBackend` protocol + host detection
  (`detect_sandboxes()` → `SandboxRegistry`, down-only tier resolution),
  mirroring the `runner.py` / `runner_registry.py` idiom; initialized in the
  app lifespan alongside `detect_runners()`.
- **Tier-1 subprocess** (everywhere incl. the DMG): child process with
  `setrlimit` (CPU/AS/FSIZE/NOFILE), allowlist-only env scrub, process-group
  SIGKILL on timeout, best-effort network deny. Weakest ceiling →
  gate-mandatory.
- **Tier-2 hardened container** (Podman-first, Docker fallback): non-root,
  `--read-only` + tmpfs, `--cap-drop=ALL`, `--security-opt=no-new-privileges`,
  `--network=none` (v1; egress allowlist deferred), pids/mem/cpu caps,
  `--cidfile` timeout-kill. Image at `setup/sandbox/Dockerfile`.
- **Three-zone workspace.** `files_in` (read-only) → per-step scratch →
  declared `files_out` promoted to the canonical workspace only on policy
  (`gated` / `auto_on_green` / `never`); stale scratch reaped on a TTL.
- **Run-level HITL gate.** An approval-required code step pauses the run
  (`status="awaiting_approval"` + serialized `WorkflowRun.pending_gate`),
  checkpoints, and resumes after
  `POST /api/workflows/runs/{run_id}/approvals/{gate_id}` records
  approve / edit / reject (idempotent — 409 on double-resolve).
- **Models.** `AgentStep.kind` gains `"code"` + a `CodeStepConfig` block;
  `StepResult` gains `code_exit_code` / `tier_used` / `peak_rss_mb` /
  `files_produced` / `approval_status` / `promoted`; new `GatePending`.
- **UI.** Runs view renders a per-step code panel (tier / exit / peak RSS /
  files / promoted / approval) + an inline approve/reject gate bar.

### Added — MCP & Skills instrumentation (PRs #116–127, all merged)

Twelve-PR series that landed the [MCP & Skills design plan](docs/plans/2026-05-19-mcp-skills-instrumentation-design.md).
Turns the plugin / MCP / skills subsystems into a first-class operator
surface with deployment-aware storage, a warm-runner pool, validate-time
pre-flight, per-step instrumentation, and security hardening.

- **Phase 1 — deployment-aware extension storage (PR #116).** Plugin
  registry + MCP `servers.json` moved into the writable user layer
  (`~/.enclave/mcp` / `~/Library/Application Support/Enclave/mcp` /
  `/app/data/mcp`) so they survive DMG reinstall and container rebuild.
  Legacy `data/config/mcp_servers.json` auto-migrates on first init.
  `POST /api/plugins/install` (tarball, traversal-guarded) +
  `DELETE /api/plugins/{id}` (system-layer protected).
- **Phase 2 — warm MCPRunnerPool (PR #117).** Long-lived stdio runners
  + HTTP sessions keyed on `(run_id, server_id)`. One initialize
  handshake serves many `tools/call` invocations; per-runner stats
  (requests / errors / peak RSS / avg response). Cross-workflow isolation;
  `release_server` / `release_workflow` decide step- vs workflow-scope.
- **Phase 3 — circuit breaker + health monitor (PR #118).** N consecutive
  failures trip a per-runner breaker; subsequent calls fast-fail without
  hitting the wire. `runner.health_check()` re-closes on `tools/list`
  success; opt-in `pool.start_health_monitor(interval_s)` daemon thread
  sweeps every live runner periodically.
- **Phase 5 — declarative pre-flight + `tools[]`/`skills[]` schema
  (PR #119).** `ToolRef` Pydantic model; `AgentStep.tools` /
  `.skills` / `.archetype`; `WorkflowDefaults.required_plugins` /
  `.required_mcps` / `.skill_injection`. `api/services/extension_preflight.py`
  walks every leaf step recursively; missing plugin/MCP/tool → 422;
  registered-but-unreachable MCP → warning. `STRICT_VALIDATION=true`
  promotes warnings to errors.
- **Phase 7.1 — `/api/system/extensions` (PR #120).** One-stop GET
  surfaces deployment-resolved plugin paths, MCP registry path +
  binaries dir, live runner-pool state (count + total RSS + per-runner
  snapshot), and cache paths.
- **Phase 6 — arch-scheduler integration (PR #121).** Every
  `Deployment.effective_memory_gb()` impl now subtracts live pool RSS
  (`mcp_overhead_gb()` helper in `api/services/deployment.py`); clamped
  at 0; surfaced in `/api/system/architecture`'s deployment block.
- **Phase 4.1 + 4.4 — instrumentation schema + run rollup (PR #122).**
  New `SkillActivation` / `MCPCall` / `PluginToolCall` models;
  `StepResult.{skills_activated, mcp_calls, plugin_tools_called,
  extension_overhead_ms}` fields; `WorkflowRun.{skills_activated_total,
  mcp_invocations_total, plugin_tools_invoked_total, mcp_servers_used,
  extension_overhead_seconds}` aggregates. `aggregate_extension_stats(run)`
  rollup; `workflow_engine._persist_run` calls it before serializing.
- **Phase 2c — lightweight role + archetypes + composer assist (PR #123).**
  New `lightweight` entry in `ROLE_PATTERNS` (sub-3B candidates).
  `api/services/archetypes.py` ships 9 built-in archetypes
  (`bash_script`, `code_review`, `documentation`, `research_brief`,
  `extraction`, `synthesis`, `data_lookup`, `xsiam_analysis`, `triage`);
  `infer_archetype` scores MCP triggers × 2 + skill triggers + role
  bonus. `POST /api/workflows/composer/assist` returns inferred archetype
  + companion suggestions.
- **Phase 2b — co-scheduler / resource-maximization compiler pass
  (PR #124).** `api/services/co_scheduler.py` computes per-step pressure
  (`model footprint × 1.15 KV + MCP RSS estimate`) against
  `deployment.effective_memory_gb() × 85%`; flags contention steps;
  picks action per priority: **archetype-aware substitution → split →
  reorder → block**. `WorkflowDefaults.co_scheduling_policy` literal
  (`off` / `recommend` / `warn_strict` / `reject` / `auto_substitute`).
  Recommendations surfaced in the validate response body.
- **Engine-side pool lifecycle (PR #125).** `_safe_drain_mcp_pool(run)`
  helper called by `_persist_run` (normal path) and by `run()`/`resume()`
  try-except (exception path) so warm runners never leak. Drained stats
  attach to `WorkflowRun.mcp_runners`.
- **Phase 7.2 + 7.3 — security defaults (PR #126).** `docker-compose.yml`
  api service drops all Linux capabilities, forbids privilege escalation,
  mounts `/tmp` as bounded tmpfs. `desktop/entitlements.plist` explicitly
  declares the sandbox posture + JIT / unsigned-executable-memory /
  network entitlements. New `docs/deployment/dmg-mcp-security.md`
  documents the trust boundary.
- **Phase 4.2 — plugin tool capture (PR #127).** `HookContext.step_result`
  field; `step_executor` passes it. `plugin_tool_invoker` records a
  `PluginToolCall` (ok / error + `error_class`) on every
  `service.call_tool` invocation; `for_each` mode emits one record per
  iteration; `extension_overhead_ms` accumulates.
- **Phase 4.3 — MCP tool capture (PR #128).** New
  `api/hooks/builtins/mcp_tool_invoker.py` (mirrors `plugin_tool_invoker`)
  routes invocations through `MCPService.invoke_tool(run_id=…, scope=…)`
  so calls share the warm pool; records `MCPCall` (ok / error / timeout
  + request/response sizes) on `ctx.step_result.mcp_calls`. Engine
  factory + workflow validator recognize the new hook.
- **Phase 4.2 — skill activation capture (this PR).** New
  `api/hooks/builtins/skill_injector.py` at `transform_prompt` stage.
  Honors the mode literal (`off` / `auto` / `explicit` / `manual`):
  explicit `step.skills` refs always inject; auto mode also runs the
  `PluginService.get_skills(prompt.user)` keyword match. Per-skill
  injection site (`inject: system` prepends to `prompt.system`;
  `inject: messages` appends to `prompt.user`). New
  `PluginService.get_skill(plugin_id, skill_id)` lookup helper.
  `max_skills` cap (default 3) prevents prompt bloat. Each activation
  records a `SkillActivation` (trigger / trigger_match / injected_into
  / injected_chars) on `ctx.step_result.skills_activated`. **All Phase
  4 capture sites — plugin tools, MCP tools, skills — are now wired.**

### Added — Platform UX refresh (PRs #69–72, #89)

- Dedicated **Runs tab** with first-class run inspector, dark-mode demo
  recorder, mini-DAG silhouette stacks (vertical for parallel ranks).
- **Composer chat** in addition to the canvas — click-to-add agents,
  multi-line description input, persisted chat in localStorage, explicit
  Clear button with confirmation.
- **Knowledge-graph zoom** + Models / Catalog tab fixes.
- BD790i migration runbook at `docs/BD790I_MIGRATION.md`; E2E testing guide
  at `docs/E2E_TESTING.md`; private overlay convention documented.

### Added — Infrastructure

- **Docker Hub publish CI (PR #82, #83).** `.github/workflows/docker-publish.yml`
  reads `DOCKERHUB_USERNAME` from `vars.*` with `secrets.*` fallback.
  `docker-compose.gpu.yml` + `docker-compose.webui.yml` variants ship.
- **Playwright E2E harness** under `tests/playwright/` — 18 new scenarios
  covering boot, chat, composer, kanban, RAG roundtrip, workflow execution,
  release UI features.
- **Ollama perf config** surfaced via `/api/inventory/system` (PR #85);
  Memory tab shows LLM concurrency, keep-alive, request timeout, model
  list TTL at a glance.
- **REQUEST_TIMEOUT bumped 300 → 900s** (PR #79) — CPU prefill on 34B+
  models was exceeding the old timeout.
- **Workflow LLM-call serialization + per-step cache** (PR #84) — single
  `_LLM_SEMAPHORE` prevents accidental two-model concurrency on
  CPU/single-GPU hosts; cache eliminates redundant lookups on retry.

### Added — Failure auto-triage & opt-in error reporting (PRs #130, #131)

- **CI failure triage (#130).** New self-contained `triage/` package (no
  FastAPI dependency) that turns pytest failures into GitHub-native output:
  inline `::error` annotations, a `$GITHUB_STEP_SUMMARY` table, and
  **deduplicated** auto-filed issues (one per stable fingerprint; recurrences
  comment instead of duplicating). Runs via `python -m triage ci` — annotations
  + summary every run, issues only on `master` pushes; fork PRs skip issue
  creation (read-only token). Issue emitter is rate-limit-safe: one
  `gh issue list` per run, a per-run cap, throttling, and a hard stop on the
  first API error.
- **Runtime error capture (#131).** Catch-all exception handler in
  `api/exceptions.py` (existing `APIError` responses unchanged) that captures
  unhandled exceptions and — **opt-in, off by default**
  (`ENABLE_ERROR_REPORTING=false`) — reports to an **operator-owned** sink
  (`github` / `webhook` / `sentry`) on a fire-and-forget daemon thread.
  Best-effort local-Ollama enrichment (`qwen2.5:14b`); mandatory redaction of
  prompts, secrets, and `$HOME` paths.
- **Telemetry stance revised (#131).** From absolute "no telemetry" to **"no
  telemetry by default; opt-in, operator-owned error reporting."** Non-opt-in
  behavior is unchanged — fully local, zero egress. Vendor phone-home is a
  separate, deferred, off-by-default capability. See
  `docs/deployment/error-reporting.md`.

### Changed — Engine internals

- `_execute_steps` is no longer a `for step in steps` loop — it's a tick
  driver. The previous behavior is preserved for workflows without
  `depends_on` (arch's `schedule_ready` returns head + deferred-rest).
- `Scheduler()` falls back to `UnknownArchitecture` when detection didn't
  run (tests, degraded boot) instead of returning `None`. Avoids
  false-positive deadlock detection.

### Fixed

- **`xdm-toolkit` relative imports + `model_list_ttl` surfacing + seed
  placeholder** (PR #87).
- **Composer chat agent response shape** (PR #81).
- **Models tab empty after Catalog DOM relocation** (PR #73).
- **Composer harsh-red on failed nodes / uncensored-role accents** (PR #76).
- **Workflow-progress chip** moved from canvas → panel header → top-right
  (PRs #78, #80) — three iterations to get the placement right.
- **Agent chat persistence** — chats now survive tab nav + reloads via
  localStorage (PR #74).

### Endpoints removed

- **`GET /api/system/deployment`** — verified-redundant subset of
  `/api/system/architecture`'s `.deployment` field. Removed in PR #90.

## [1.1.1] — 2026-05-15

### Added — Cortex Console rebrand (PR #57)
- Web console re-skinned to the PANW Cortex product family aesthetic
  (XSIAM / XDR / XSOAR). Slate-navy canvas, Cortex Green primary, cool-blue
  secondary, PANW orange reserved for the co-brand chip and critical alerts.
- Two-row Cortex command bar: brand-mark + health pip, env chip, clock /
  uptime, theme toggle, caps-tracked breadcrumb (Cortex › Mode › Context).
- Tabs regrouped into operator phases — BUILD (Composer · Workflow Index ·
  Agents · Skill Lab) / OPERATE (Runs) / LIBRARY (Models · Context · Memory)
  / ADMIN. All `data-tab` IDs preserved so `switchTab()` routing stays
  back-compatible.
- New status rail at the bottom: env+project / live model + queue + last run
  / version + co-brand. New element IDs (`rail-env`, `rail-project`,
  `rail-model`, `rail-queue`, `rail-last-run`, `rail-run-pip`) ready for the
  follow-up JS wiring; chrome works standalone with placeholders today.
- Engineered 32px grid + soft radial undertone replaces the bloom-style
  ambient. Reads as operator console, not dark-UI demo.

### Added — OOTB XQL/XDM bundle (PR #56)
- Five new workflows under [workflows/](workflows/): `data-model-rules`,
  `xsiam-data-model-rules`, `xdm-rule-from-log`, `xdm-bulk-onboarding`,
  `xsiam-normalization-pipeline`. End-to-end pipelines for authoring,
  validating, and onboarding Cortex XSIAM data model rules from raw vendor
  logs.
- Three new agents under [agents/](agents/): `xsiam-analyst`,
  `xql-data-model-engineer`, `xdm-schema-navigator`.
- New `xdm-toolkit` plugin under [plugins/xdm-toolkit/](plugins/xdm-toolkit/)
  with two callable tools (`validate_xql` static rule validator,
  `lookup_xdm_path` XDM path resolver) and two skills (rule-writer,
  validator) that auto-inject on XQL/XDM keyword triggers.
- Knowledge seed under [docs/seed/xql/](docs/seed/xql/) — Modelfile +
  Markdown knowledge for offline XQL operators.
- Sample data under [workflows/mock_data/](workflows/mock_data/) — Okta
  system log, PAN-OS traffic, Windows Security XML for fixture-style runs.

### Added — Documents drop-zone + Cloud Models registry (PR #55)
- Composer Documents pane accepts drag-drop PDFs and text files; routes
  through the existing RAG pipeline (Chroma + nomic-embed-text) without a
  separate upload page. Per-document delete + reindex.
- Admin → Cloud Models tab. UI to register external OpenAI-compatible
  providers (OpenAI, Anthropic, Together, OpenRouter, custom endpoint),
  store API keys on the host in `data/config/cloud_providers.json`
  (chmod 0600), and use them as workflow steps. The dashboard never echoes
  keys back; rotate / revoke is one click.
- "Discover" surface folded into Models — single page lists installed
  models, pullable models from the registry, and configured cloud
  providers in one operator view.

### Added — Composer canvas + admin tabs (PR #54)
- Composer canvas now supports zoom (button + scroll-wheel) and fullscreen.
  Pan-and-zoom transform is preserved across tab switches.
- New Admin → Skills tab — list, enable / disable, and preview the skill
  body of every skill discovered across installed plugins.
- `plugins/` directory now shipped in the docker image (was missing pre-#54,
  so the Plugins admin panel was empty in container deployments).

### Added — Composer system-model picker, Agents palette, Project modal (PR #53)
- Step inspector now exposes a system-model picker that overrides the
  workflow-level default for a single step. Picker enumerates installed
  models plus registered cloud providers.
- Agents palette on the composer: drag an existing agent (YAML-defined
  persona) onto the canvas as a step. The agent's pinned model and context
  sources travel with it.
- Step-engage chat: click a step on the canvas to open an inline chat that
  uses that step's exact system prompt + model. Lets operators iterate on
  step prompts without committing them.
- Project modal: cluster multiple workflows, documents, and runs under a
  named project. Project bar pinned in the header.

### Added — UI structural test fleet (PR #52)
- 47-test `pytest` fleet under [tests/ui/test_static_markup.py](tests/ui/test_static_markup.py)
  asserting structural invariants of the dashboard HTML (composer canvas,
  palette, admin panels, API keys UI, exports, plugin tool tester,
  self-hosted vendor libraries — no CDN). Catches regressions without
  needing a running stack; runs in <1 s.

### Added — Agent reliability (PR #48 + PR #50)
- Agents with a pinned model now fall back to role-based resolution when
  the pinned model isn't installed locally, instead of failing the chat.
  The dashboard surfaces a `model_fallback` banner in agent chat so the
  operator sees which model actually responded.

### Engine — plugin tool invocation + validator hardening
- New built-in hook `plugin_tool_invoker` at
  [api/hooks/builtins/plugin_tool_invoker.py](api/hooks/builtins/plugin_tool_invoker.py).
  Configurable via YAML `before_step` block — invokes any plugin tool with
  resolved workflow inputs and stores the result in step workspace.
  Supports `for_each` iteration with `param_template` substitution
  (e.g. `{{ item.rule }}`) for batch tool calls. Idempotent across the
  pre-compose / post-compose dispatch passes.
- `WorkflowEngine.validate()` now recognizes hook-provided virtual inputs:
  for every `before_step` hook with a `store_as` key, the resulting
  `<step_id>.<store_as>` is treated as a valid producer when checking the
  step's own `inputs:` list. Closes the structural hole that made the OOTB
  XQL workflows un-runnable.
- `StepExecutor.execute()` rewritten — `before_step` now dispatches BEFORE
  input resolution and prompt composition (so hooks like
  `plugin_tool_invoker` can populate workspace keys the step then reads).
  Re-dispatched once on attempt 0 post-compose to preserve `token_budget`
  semantics. All before_step hooks must be idempotent.
- `ModelResolver.ROLE_PATTERNS` updated: `qwen2.5-coder` is explicitly
  preferred for `coding` and `reasoning` roles ahead of the older
  `qwen3.5` / `deepseek-r1` patterns. Workflows declaring `role: coding`
  or `role: reasoning` now pick up an installed qwen2.5-coder build
  declaratively, not by accident via the "largest available" fallback.

### Fixed — OOTB workflow runtime parity
- `workflows/xdm-rule-from-log.yaml`: `before_step` hook renamed from
  the non-existent `invoke_validate_xql` to the new `plugin_tool_invoker`
  built-in. The `refuse_if_blockers` `validate_output` hook (also not
  implemented) is commented out with a forward-looking TODO; the workflow
  still emits its verdict line from the prompt side.
- `workflows/xdm-bulk-onboarding.yaml`: same hook rename. Added an
  `output_schema` to the `write_rules` step (`{rules: [{cluster_id,
  dataset, rule}]}`) so `JsonSchemaHook` parses the response into a real
  list — without this, `validate_all` saw a stringified blob and
  `plugin_tool_invoker for_each` correctly refused to iterate.

### Fixed — Docker first-boot (PR #42)
- Ollama healthcheck used `curl`, which isn't in the `ollama/ollama` image,
  so the check failed forever and blocked `depends_on: service_healthy` for
- Ollama healthcheck used `curl`, which isn't in the `ollama/ollama` image,
  so the check failed forever and blocked `depends_on: service_healthy` for
  `api` and `webui`. Replaced with `ollama list`.
- `/static/*` 401'd under default docker auth because `PUBLIC_PATHS` was
  exact-match. Added `PUBLIC_PREFIXES` for `/static/` plus exact entries
  for `/setup.html` and `/favicon.ico`.
- JS escape `won\\'t` inside a template-literal single-quoted string aborted
  parsing of the entire dashboard inline `<script>` block, leaving
  `switchTab` and every handler undefined. Fixed to `won\'t`.

### Fixed — Docker runtime data + RAG + admin gate (PR #43)
- Dockerfile only COPY'd `api/`. The `models/`, `agents/`, `workflows/`, and
  `prompts/` dirs are read at runtime; without them the Models tab 500'd
  (`ModuleNotFoundError`), Agents/Workflows tabs returned empty arrays, and
  the roles router served no templates.
- The image installed `requirements-core.txt` only, leaving `chromadb` and
  `sentence-transformers` absent and the Documents tab returning 503
  (`RAG pipeline unavailable`). Install `requirements-rag.txt` instead.
- `run.sh` now pulls `nomic-embed-text` on first boot alongside the chat
  starter, so the RAG pipeline binds Ollama embeddings on startup instead
  of falling back to the heavy sentence-transformers path at request time.
- `require_master_key` is now a no-op when `ENABLE_API_AUTH=false` (the
  admin gate respects the global auth flag for consistency) and accepts
  keystore keys holding the `keys` scope (the auto-provisioned first-run
  master qualifies — was previously rejected because the function only
  consulted the legacy `MASTER_API_KEY` env var).

### Added — Light theme + UI cleanup (PR #44)
- `:root[data-theme="light"]` token block, header toggle button (☀/☾),
  `Theme` controller persisting choice to `localStorage`, and a synchronous
  `<head>` bootstrap to resolve theme before paint (no flash of wrong
  theme). Initial precedence: localStorage > `prefers-color-scheme` > dark.
- Header subtitle no longer duplicates the footer attribution.
- Latent state bug fixed: `AdminMenu.showPanel()` set inline `display:block`
  on admin subtab panels, but `switchTab()` never reset the inline display.
  Once you opened an admin subtab, that panel bled through under every
  operational tab. `switchTab` now mirrors `AdminMenu.showPanel`'s
  symmetric reset.

### Added — Packaging parity (PR #45)
- `scripts/build_mac.sh` now COPYs `agents/`, `workflows/`, `prompts/` into
  the bundled `.app` and installs `requirements-rag.txt` in the bundled
  venv. Without this the shipped DMG had the same broken Documents/Agents/
  Workflows tabs the docker image had pre-#43.
- New `scripts/setup_linux.sh` — distro-detecting bootstrap (Debian /
  Ubuntu / Parrot / Fedora / Arch) for native dev on a Linux host. Picks
  Python ≥3.12, creates `./venv`, installs `requirements-rag.txt`, pulls
  `llama3.2:3b` + `nomic-embed-text` via Ollama if available, smoke-imports
  `api.main` as the final gate. Flags: `--venv-only`, `--no-models`.

### Fixed — v1.1.x hotfix bundle
- **Version unification.** Introduced `api/__init__.py:__version__` as the
  single source of truth, wired `api/main.py` to import it (was hardcoded
  to `0.1.0` in four places), and bumped the dashboard footer string from
  `v0.1.0` to `v1.1.0`. `/health`, `/api/info`, `/`, and the OpenAPI
  metadata now all surface the same version that the CHANGELOG and git
  tag record.
- **Keystore + workflow runs persisted.** `docker-compose.yml` now mounts
  the whole `/app/data` dir as a named volume (`local-ai-api-data`), with
  `/app/data/logs` keeping its dedicated log volume via nested-mount
  precedence. Issued API keys, completed workflow runs, and the RAG
  Chroma store all survive `docker compose build` / `--force-recreate`.
- **`/api/documents/query` route alias.** Added a `POST /api/documents/query`
  endpoint that proxies to `/search`. Both spellings now work; `/search`
  remains canonical.

## [1.1.0] — 2026-04-22

### Added — Workflow prompt framework (PR #11)
- Six-hook step lifecycle: `before_step`, `transform_prompt`, `validate_output`,
  `after_step`, `on_failure`, plus a `HookBus` with ordered dispatch,
  short-circuit, and `@register_hook` auto-discovery from `api/hooks/`.
- `PromptComposer` with 5-part Jinja templating and a seed role library.
- Six built-in hooks: `json_schema`, `refusal_detector`, `token_budget`,
  `output_logger`, `few_shot_injector`, `retry_with_feedback` (with optional
  model escalation on retry).
- Six model-family adapters (dolphin, llama3, mistral, qwen, yi, uncensored)
  over a `ModelAdapter` base + registry.
- `StepExecutor` rewritten around the 6-hook lifecycle; `WorkflowEngine`
  wires a per-step `HookBus` and `PromptComposer`.
- `workflows upgrade` CLI: converts v1 YAML to v2 schema.
- Extended workflow models with v2 fields (`StepPrompt`, `HookSpec`,
  `schema_version`, `context`, I/O `schemas`).
- Integration test fleet: happy-path pipeline, retry-with-feedback recovery,
  token-budget truncation semantics, v1 legacy regression, custom-hook
  auto-discovery, model-escalation surfacing, E2E smoke (skipped without live
  Ollama), `FakeOllamaClient` fixture.

### Added — Context & memory graph
- Context models for conversation tracking and facts.
- `MemoryService` with YAML persistence for sessions and facts.
- Per-conversation `ContextStore`.
- `SessionManager` with explicit close and auto-cleanup.
- `/context` and `/memory` routers (full CRUD).
- Tool-executor and chat-router wiring for automatic context capture.
- Dashboard "Memory" tab (sessions, facts, stats).

### Added — Profiles & sandbox
- `ProfileService` for YAML-declared agent permissions; seeded built-ins
  (`default`, `research`, `unrestricted`).
- `SandboxedFS` per-conversation filesystem boundary, auto-injected into
  tools that declare a `__sandbox` param.
- Profile enforcement in the tool executor; profile + sandbox wired into
  the chat router and `SessionManager`.
- `/profiles` router with list / detail / reload endpoints.
- Dashboard "Profiles" section (with reload).

### Added — RAG pipeline
- `Chunker` wrapping LangChain `RecursiveCharacterTextSplitter`.
- `EmbeddingService` with pluggable backend (Ollama or
  `sentence-transformers`).
- `DocumentService`: upload → parse → chunk → embed → store.
- `RAGService`: retrieval and context formatting.
- `/documents` router: upload, list, delete, stats, search.
- Auto-retrieval wired into the chat router with profile gating.
- `rag__search` plugin tool and profile integration.
- Dashboard "Documents" tab (upload, list, search preview).
- `pypdf` added for PDF parsing.

### Added — Packaging
- Enclave icon bundled into the macOS DMG.

### Fixed
- Workflow retry no longer accumulates feedback across attempts
  (`prompt.user` / `prompt.system` reset per retry).
- Path traversal rejected in `role_ref` and few-shot `step_id` inputs.
- `escalate_to` now actually switches models on retry (wired through
  `model_resolver`).
- CI: `jinja2` and `jsonschema` added to `requirements-core.txt` so CI
  dependencies match runtime.
- CI: RAG tests skipped cleanly when LangChain isn't installed.

### Security
- `.gitignore` tightened for runtime secrets and user data.
- DMG build no longer packages local secrets or user state.

### Changed
- `CLAUDE.md` baseline corrected to reflect the 1.0.0 surface: populated
  routers/services, auth middleware, streaming, RAG, tests, Docker, CI.
  Removed stale "0% coverage" / "empty skeletons" / "1.0.0 reserved" claims
  and reshaped the roadmap around `1.x` / `2.0.0`.
- `.claude/worktrees` and `.worktrees` added to `.gitignore`.
- Runtime `data/logs/*.jsonl` (from `output_logger` hook) added to
  `.gitignore`.

## [1.0.0] — 2026-04-18

Initial public release of Enclave.
See the [v1.0.0 release](https://github.com/hankthebldr/local-ai-platform/releases/tag/v1.0.0)
for details.

[Unreleased]: https://github.com/hankthebldr/local-ai-platform/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/hankthebldr/local-ai-platform/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/hankthebldr/local-ai-platform/releases/tag/v1.0.0
