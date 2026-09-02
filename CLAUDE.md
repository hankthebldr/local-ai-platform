# CLAUDE.md

Guidance for Claude Code working on this repo.

## Project

Enclave — self-hosted local LLM platform. CPU-first inference, privacy-first, no telemetry by default (opt-in operator-owned error reporting). Fleet:
Mac M4 Pro 48GB (dev) · MS-01 64GB (API) · BD790i 96GB (flagship). Authoritative model catalog: [MODELS.md](./MODELS.md).

## Core workflow

1. **Always activate venv first:** `source venv/bin/activate`
2. Edit code → auto-formatter runs (`.claude/hooks/format-python.sh`) → commit (secret scanner runs).
3. Run API: `python api/main.py` (port 8000). Ollama: `ollama serve` (11434). Mac app: `python desktop/app.py`.
4. Run tests: `pytest tests/ --ignore=tests/e2e -v`

## Architecture

```
CLI / WebUI / Mac app → FastAPI (api/main.py) → routers/ → services/ → Ollama (CPU GGUF inference)
                                                              ↓
                                                    Workflow engine (DAG)
                                                              ↓
                                                    RAG (Chroma + chunker)
```

Key files by responsibility:
- `api/main.py` — FastAPI app, CORS, middleware, auth (off by default)
- `api/routers/*.py` — 16 endpoint groups (chat, completions, workflows, agents, a2a, graph, memory, …)
- `api/services/*.py` — 22 services (ollama, workflow_engine, workflow_compiler, step_executor, prompt_renderer, output_parsers, quality_gates, model_resolver, agent_service, graph_service, …)
- `api/models/*.py` — Pydantic v2 data models (workflow, agent, a2a, context)
- `api/services/workflow_engine.py` + `step_executor.py` — **multi-agent DAG orchestrator** (use `workflow-engine-expert` subagent)
- `models/download.py` — `MODEL_REGISTRY` (must stay in sync with `MODELS.md` — sync hook reminds you)
- `cli/` — Rich-based CLI tools (chat, workflow, benchmark)
- `workflows/*.yaml` — declarative workflow definitions (XSIAM data model rules, normalization pipeline, …)
- `agents/*.yaml` — custom agent personas (Gems-style)
- `desktop/` — macOS DMG via py2app + pywebview

## Don't touch without care

- `api/main.py` — production API surface, CORS/auth/middleware
- `api/services/workflow_engine.py`, `workflow_compiler.py`, `step_executor.py` — core engine (use subagent)
- `Dockerfile`, `docker-compose.yml` — deployment
- `desktop/setup_app.py`, `desktop/build.sh` — DMG build pipeline
- `.env` — **never commit** (secret scan hook blocks it)
- `MODELS.md` — authoritative model doc; update whenever `MODEL_REGISTRY` changes

## Common tasks

- **Add a model:** edit `MODEL_REGISTRY` in `models/download.py` → update `MODELS.md` (sync hook reminds you).
- **Add a workflow:** `workflows/<name>.yaml`. See `docs/plans/2026-04-06-multi-agent-workflow-engine-design.md` and existing XSIAM workflows for examples (DAG, Jinja2 prompts, output parsers, quality gates).
- **Add a custom agent:** `agents/<name>.yaml` — see `agents/xsiam-analyst.yaml` for context-source patterns.
- **Add a service:** `api/services/<name>_service.py`. Wire via `api/routers/<name>.py`. Register router in `api/main.py`.
- **Add a model-family adapter / built-in hook:** see workflow framework spec in `docs/superpowers/plans/2026-04-20-workflow-prompt-framework.md`.

## Release track

Current shipped: **`1.1.1`** — Cortex Console refresh (shipped 2026-05-15). Builds on `1.0.0` (first public release, 2026-04-18). Positioned as a **single-operator sovereign appliance**; multi-tenant / enterprise hardening is a deferred 2.x concern.

> **Note:** the console has since been **rebranded off PANW-Cortex to Enclave's own warm-charcoal + teal identity** on the in-flight `feat/chat-led-composer` branch (candidate `1.2.0`). References to a "Cortex Console" describe what `1.1.1` shipped, not the current branch — see *In flight* below.

What's shipped today (1.0.0 + 1.1.1):
- Core infra (Ollama + systemd + macOS DMG)
- 18-model registry · CLI chat · OpenAI-compatible API with streaming
- 16 routers / 22 services · API-key auth + rotation + plugins
- Multi-agent workflow engine (sequential DAG, Jinja2 prompts, parsers, quality gates, checkpoint/resume, 6-hook lifecycle)
- RAG pipeline (Chroma + chunker + document service)
- Cortex Console UI · BUILD / OPERATE / LIBRARY / ADMIN tab grouping
- CI on Python 3.12/3.13 · DMG release · Pages
- 46 test files (unit/integration/e2e/hooks/ui)

In flight (two independent workstreams; see [CHANGELOG.md](./CHANGELOG.md) `[Unreleased]` for the full inventory):
- **`1.2.0` candidate — Chat-led Composer + Enclave rebrand** (branch `feat/chat-led-composer`). The Composer goes chat-primary — "a workflow is crystallized conversation": a **"Boot Sequence"** affordance distills a conversation into an editable spec and scaffolds a local agentic DAG (`POST /api/composer/capture-spec` + `/scaffold`, backed by `spec_capture.py` + `scaffold_planner.py`; engine untouched). Full **design-system rebrand** off PANW-Cortex to Enclave's warm-charcoal + teal identity (vendored at `docs/design/`), in-shell **Chat↔Canvas pivot** + fluid layout, unified **asset deep-dives** (AssetPeek), **Runs reasoning drill-down** + calm analytics, **eval harness**, GitHub-backed **skills marketplace**, **model enrichment** endpoint. Now also **node-bound chat** (select a node → chat with/configure that agent; ratings → per-agent tuning), interactive **workflow drill-down**, and a vertical chat-top/canvas-bottom layout. The console-v2 backlog (thread switcher, pin-as-step, operator's-path ladder, compare grid, install wizard, Run lens) has **shipped**. Remaining gap-closure (provenance/citation, server-side persistence, composite-step-kind UI) is tracked in [docs/plans/2026-06-17-gap-closure-implementation.md](./docs/plans/2026-06-17-gap-closure-implementation.md) (audit: [docs/research/2026-06-17-flow-gap-audit.md](./docs/research/2026-06-17-flow-gap-audit.md)).
- **`1.3.0` — Architecture-aware orchestration** — `Architecture` + `Deployment` protocols (Apple unified / NVIDIA single / NVIDIA multi / x86 CPU), per-arch keep_alive defaults, parallel DAG dispatch driven by `arch.schedule_ready()`, pre-warm of next-step models during current step's inference, per-run telemetry summary (load duration, pressure delta, pre-warm hit/miss). PRs #88, #90, #91, #92, #93, #95 merged; UI summary (#97) draft.
- **`1.3.0` — Composite workflow step kinds** — `kind: parallel` (fan-out → gather) + `kind: loop` (body → until predicate). Four parallelism modes including `single_model_pseudo_parallel` for prompt-cache reuse. PRs #94, #96, #98.

Roadmap (single-operator-appliance track):
- **`1.2.0`** — chat-led Composer + the Enclave design-system rebrand (the frontend redesign). Cuts when the console-v2 backlog (thread rail, pin-as-step + scaffold modal, operator's-path ladder, model-compare grid, install wizard, Run lens) reaches the agreed MVP bar and the new UI surfaces (AssetPeek, Runs decisions panel, calm-analytics atoms, Cmd/Ctrl-K palette, `focus` mode) gain test coverage.
- **`1.3.0`** — ship the arch-aware + composite-step-kinds work above. Cuts when PR #97 (UI summary) lands and the Memory tab + Runs view reflect the full pipeline end-to-end.
- **`1.4.x`** — **fleet awareness.** Mac M4 (dev) + MS-01 (API) + BD790i (flagship) over Tailscale. One control plane, one operator, work routed to whichever box has the right RAM/VRAM. `HostRegistration` model, target-host selector on Composer, resume-on-other-host, opt-in Wake-on-LAN for the flagship.
- **`1.5.x`** — **pluggable inference engines.** vLLM + llama.cpp parity with Ollama via the existing OpenAI-compatible surface. Per-host engine choice in the fleet registry.
- **`1.x`** — UI module-split (the 30k-line `index.html` is overdue for ES-module fan-out), workflow YAML editor, plugin marketplace v1 (signed manifests), license-key surface beyond the current placeholder.
- **`2.0.0`** — **TBD; depends on commercial direction.** If Enclave stays a hacker-delight free appliance: 2.0 is mostly aesthetic (deliberate UX refresh, "the appliance you'd put in a magazine"). If a commercial team SKU lands: 2.0 carries RBAC, audit log, multi-tenant storage, observability stack. The seams (storage layer, API key scopes) are intentionally future-proofed in 1.x so the decision can be deferred without painful migration.

## Pointers

- Enterprise gaps: [ENTERPRISE_DEPLOYMENT_GAPS.md](./ENTERPRISE_DEPLOYMENT_GAPS.md)
- Workflow engine design: `docs/plans/2026-04-06-multi-agent-workflow-engine-design.md`
- Prompt framework plan: `docs/superpowers/plans/2026-04-20-workflow-prompt-framework.md`
- Claude Code config plan (this file's hooks): `docs/superpowers/plans/2026-04-22-claude-code-config.md`
- Hook library: `.claude/hooks/README.md`
- Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md
- **Architecture-aware orchestration (1.3.0 WIP):** design at `docs/plans/2026-05-19-architecture-aware-orchestration-design.md`; impl plan at `docs/plans/2026-05-19-architecture-aware-orchestration-implementation.md`. Introduces `Architecture` + `Deployment` abstractions, freshness-by-default eviction, sequential execution model.
- **MCP & Skills instrumentation (1.3.0 WIP):** design at `docs/plans/2026-05-19-mcp-skills-instrumentation-design.md`; impl plan at `docs/plans/2026-05-19-mcp-skills-instrumentation-implementation.md`. Step-scoped MCP runners, archetype registry, resource-maximization compiler.
- **Ollama version pinning:** `docs/deployment/ollama-version.md` documents the 0.23.4 baseline + upgrade procedure.
- **Enclave design system (Claude Design handoff, 2026-06-12):** `docs/design/` — tokens, brand assets, React component specs, and the canonical chat-led console prototype (`docs/design/project/ui_kits/console-v2/`). `docs/design/README.md` explains the bundle; `docs/design/chats/` holds the design-intent transcripts. The rebrand tokens + in-shell Chat↔Canvas pivot are implemented in `api/static/index.html`; the remaining console-v2 IA (thread rail, pin-as-step, EntityCard peeks, install wizard, dataviz band) is unimplemented roadmap — design from these files, don't reinvent.

## Conventions

- **Quantization:** Q4_K_M default · Q5_K_M for quality · Q3_K_M for 70B+.
- **Performance targets (CPU):** 7B≈40-50 t/s · 13B≈25-30 t/s · 34B≈10-15 t/s · 70B≈3-5 t/s.
- **Uncensored-first:** dolphin-mixtral, dolphin-mistral, nous-hermes2-mixtral, yi-34b, wizardlm-uncensored, mythomax.
- **OpenAI-compatible API:** clients switch between Ollama / vLLM / llama.cpp transparently.
- **CORS / Auth defaults:** CORS to `["*"]` only if `CORS_ORIGINS` unset (startup warning fires); auth off by default (`ENABLE_API_AUTH=false`) — set both before non-localhost exposure.
- **Ollama version pinned to `0.23.4`** (see `docs/deployment/ollama-version.md`). The architecture-aware orchestration code (1.3.0+) requires this floor. Detector at `api/services/architecture.py` enforces it at startup.
- **NVIDIA introspection:** `nvidia-ml-py` is a core dependency (in `setup/requirements-core.txt`). Imports cleanly on non-NVIDIA hosts; `pynvml.nvmlInit()` raises `NVMLError("Shared Library Not Found")` which the detector catches and treats as `cpu_x86` / `apple_unified` per platform.
- **Fail-safe persistence:** never write a model-failure sentinel (an `_… unavailable — …_` string) to a durable store, and never return HTTP 200 on a local-model exception. Surface a `503` with `X-Enclave-Error: model_unavailable` (see `_chat_or_503` in `api/routers/research.py`); mark worklist items `error`, not `done`; resolve everything a resume needs *before* flipping a persisted status, and restore the pre-flip snapshot if the resume blows up (`_load_resume_definition` / `_resume_or_restore` in `api/routers/workflows.py`).
- **No telemetry by default. No cloud inference. All data local.** Error reporting is **opt-in and off by default** (`ENABLE_ERROR_REPORTING=false`); when enabled it is **operator-owned** (reports go to *your* sink) and **redaction is mandatory**. Optional vendor phone-home is separate, explicit, and disabled by default. See `docs/superpowers/specs/2026-05-31-failure-auto-triage-design.md` and `docs/deployment/error-reporting.md`.
