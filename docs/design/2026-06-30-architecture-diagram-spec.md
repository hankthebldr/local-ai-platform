# Enclave — Architecture Diagram Spec (for Claude Design)

**Date:** 2026-06-30
**Owner:** hankthebldr
**Status:** Brief — ready to hand to Claude Design
**Source of truth:** This document is reconstructed from the live codebase (29 routers, ~60 services), not the marketing summary. Where the code and the README disagree, the code wins. Cross-check against `CLAUDE.md`, `api/main.py`, and `api/services/`.

---

## 0. What I want you to make

A set of **architecture diagrams** for Enclave, a self-hosted local-LLM platform. The diagrams will live in the repo (`docs/design/` and `docs/wiki/`), appear in the README and the in-app **About/Architecture** panel, and be shown to technical evaluators. They must be **brand-accurate** (use the Enclave palette below — these renders should look like they belong to the product) and **technically precise** (every box maps to a real module path given here).

Deliver **five diagrams** (detailed in §7). If you can only do one first, do **Diagram A (C4 Container view)** — it's the hero.

Format: vector (SVG preferred, or Figma frames). Dark theme is the hero; ship a light variant of Diagram A only. Each diagram needs a legend and a one-line caption.

**Audience:** technically literate operators and evaluators — homelab/self-hoster aesthetic, not enterprise-cloud. The vibe is "a sovereign appliance you'd put in a magazine," not an AWS reference architecture.

---

## 1. Product in one paragraph (context for tone)

Enclave is a **single-operator sovereign appliance** for running LLMs locally. CPU-first inference, privacy-first, **no telemetry by default**, no cloud inference, all data local. It exposes an **OpenAI-compatible API**, a **multi-agent workflow engine** (YAML-defined DAGs), **RAG**, **agents/personas**, and an **architecture-aware orchestrator** that schedules model load/evict across the hardware it happens to be running on. It targets a small personal **fleet**: a Mac (dev), a mini-PC (API), and a GPU flagship. The current in-flight UI is a **chat-led console** ("a workflow is crystallized conversation") on the Enclave warm-charcoal + teal brand.

Diagrams should feel **calm, structured, blueprint-like** — this is infrastructure software for people who care about provenance and control.

---

## 2. Brand & visual system (USE THESE EXACT TOKENS)

Pull from `docs/design/project/tokens/`. The palette is **warm charcoal with a green-grey undertone** — never pure black, never blue slate. Teal is the "live signal" accent; emerald is structure/success; ember is a sparing warm co-mark.

### Core surfaces (dark — the hero)
| Role | Token | Hex |
|---|---|---|
| Outermost void / page | `--ink-990` / `--ink-950` | `#090B0A` / `#0B0E0D` |
| Primary surface (canvas) | `--bg` (`--ink-900`) | `#101413` |
| Sunken well | `--ink-840` | `#141A18` |
| Elevated card (boxes) | `--surface-card` (`--ink-800`) | `#171C1A` |
| Raised / hover | `--ink-750` | `#1B2220` |
| Modal / popover | `--ink-700` | `#1F2522` |
| Default border | `--border` (`--ink-600`) | `#28302D` |
| Strong border | `--ink-500` | `#36413B` |

### Accents
| Role | Token | Hex |
|---|---|---|
| **Primary — teal (live signal, primary data flow)** | `--accent` (`--teal-400`) | `#2BD4B4` |
| Teal hover/focus | `--teal-300` | `#5DE9CE` |
| Deep teal | `--teal-600` | `#128A78` |
| **Secondary — emerald (structure, success)** | `--accent-2` (`--emerald-500`) | `#149468` |
| Emerald success | `--emerald-400` | `#1FB983` |
| **Warm — ember (sparing co-mark / external)** | `--accent-warm` (`--ember-400`) | `#E08A4C` |
| Warning | `--amber-400` | `#E0A33C` |
| Danger (warm, not harsh red) | `--coral-400` | `#E5685A` |
| Info (soft cyan-teal) | `--sky-400` | `#57C4D2` |

### Text
| Role | Hex |
|---|---|
| Primary text | `#ECEFEC` (`--ink-50`) |
| Headings | `#F6F8F6` (`--ink-0`) |
| Secondary / labels | `#9CA8A1` (`--ink-200`) |
| Muted / captions | `#6B776F` (`--ink-300`) |

### Type
- **Space Grotesk** (300–700) — titles, box labels, body. Humane geometric sans.
- **JetBrains Mono** (300–700) — "operator voice": module paths, ports, env vars, code, metrics. **Set every `api/...` path, port number, and env var in mono.**

### Signature details (use these to make it look like Enclave, not a generic diagram)
- **Corner ticks** — small teal L-marks at the corners of major group containers (blueprint registration marks).
- **Scan-line / hairline accents** — thin teal rules (`--border-glow: rgba(43,212,180,0.22)`) to separate zones.
- Soft, *small* glows only (`--glow-accent`), not ambient bloom. Boxes are flat charcoal cards with 1px borders.
- Blueprint-grid illustration ground is acceptable behind the canvas at very low opacity.
- **No emoji. No drop-shadow-heavy "cloud" clip-art.** Icons: Lucide line-icon style, stroke ~1.5px.
- 4px spacing grid; radii small (4–8px). Corners are crisp, not pill-round.

### Color semantics for the diagram (define once in the legend)
- **Teal** = primary request/inference data flow (the "live" path).
- **Emerald** = internal service-to-service / structural wiring.
- **Ember** = anything that touches *outside the box* (external/optional/opt-in: HuggingFace, A2A peers, optional cloud providers, opt-in error sink).
- **Sky/Amber/Coral** = info/warn/danger states only (e.g., memory-pressure levels), not structure.
- **Dashed stroke** = optional / not-on-by-default / roadmap. **Solid** = shipped & default.

---

## 3. The system as layers (top-to-bottom mental model)

This is the spine for **Diagram A**. Six horizontal bands, top (clients) to bottom (hardware/data).

```
┌─ CLIENTS ───────────────────────────────────────────────────────────────┐
│  Web Console (SPA)   ·   CLI (enclave)   ·   macOS Desktop App            │
│  Optional: Open WebUI   ·   OpenAI-compatible API clients   ·   A2A peers │
└───────────────────────────────────────────────────────────────────────────┘
                                   │  HTTP / SSE (OpenAI-compatible /v1, /api/*, /a2a)
┌─ API EDGE (FastAPI · api/main.py · :8000) ───────────────────────────────┐
│  Middleware: RateLimit → APIKeyAuth → CORS                               │
│  29 routers grouped: /v1 · /api/* · /a2a · /health · / (console)         │
└───────────────────────────────────────────────────────────────────────────┘
                                   │
┌─ SERVICES (api/services/ · ~60 modules) ─────────────────────────────────┐
│  Inference · Workflow Engine · Agents/A2A · RAG/Memory · MCP/Skills ·     │
│  Architecture-aware Orchestration · Sandbox · Discovery · Security        │
└───────────────────────────────────────────────────────────────────────────┘
                                   │
┌─ INFERENCE SUBSTRATE ────────────────────────────────────────────────────┐
│  Ollama (:11434, GGUF, default)  ·  vLLM (:8000, GPU, opt-in)  ·          │
│  llama.cpp (roadmap)  ·  ONNX Runtime (embeddings, CPU)                   │
└───────────────────────────────────────────────────────────────────────────┘
                                   │
┌─ PERSISTENCE (file-based · data/) ───────────────────────────────────────┐
│  Chroma vectors · JSON runs/conversations · JSONL logs · Markdown memory ·│
│  YAML config/keys.  NO database.                                          │
└───────────────────────────────────────────────────────────────────────────┘
                                   │
┌─ HARDWARE / FLEET ───────────────────────────────────────────────────────┐
│  Mac M4 Pro (dev) · MS-01 (API) · BD790i (GPU flagship) — over Tailscale  │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Component inventory (every box you may draw, with real paths)

Set all paths/ports/env-vars in **JetBrains Mono**. Bracketed `[dashed]` = draw with a dashed border (optional/roadmap). Bracketed `[ember]` = external-touching.

### 4.1 Clients (top band)
- **Web Console (SPA)** — `api/static/index.html`. Single ~24k-line vanilla-JS/CSS SPA (no React at runtime), served by FastAPI at `/`. Vendor libs: **D3** (dataviz), **Drawflow** (DAG canvas), **Dagre** (graph layout), **js-yaml**. Inline module groups: journey/routing, threads, library, run-lens, components, flow5 (canvas). Note as sub-affordances: *Chat ↔ Canvas pivot*, *Composer*, *Inspector*, *Agent Chat Dock*, tabs **BUILD / OPERATE / LIBRARY / ADMIN**.
- **CLI — `enclave`** — `cli/dispatcher.py` routes to `chat.py`, `query.py`, `workflow.py`, `eval.py`. Rich-based TUI. Pipe-friendly.
- **macOS Desktop App** — `desktop/app.py`. **PyWebView** native window wrapping an **embedded uvicorn** server (FastAPI in a background thread on `:8000`). Packaged via **py2app** → `.app` + optional **DMG**. First-run routes to `/setup`.
- `[dashed][ember]` **Open WebUI** — `docker-compose.webui.yml`, `:8081`. Optional generic OpenAI-compatible chat client.
- `[ember]` **OpenAI-compatible API clients** — any third-party tool pointing at `/v1`.
- `[ember]` **A2A peer agents** — external agents speaking Google **Agent-to-Agent** JSON-RPC at `/a2a`.

### 4.2 API edge (FastAPI — `api/main.py`, `:8000`)
- **App:** "Enclave API", OpenAI-compatible, lifespan-managed startup/shutdown, static mount `/static`.
- **Middleware (outer→inner request order): CORS → APIKeyAuth → RateLimit.** Auth toggle `ENABLE_API_AUTH` (default on in container, off in dev); `RATE_LIMIT_RPM`; `CORS_ORIGINS`.
- **Public:** `GET /health` (runner status + memory metrics), `GET /` (console), `GET /api/info`.
- **Routers (29)** — group them in the diagram by domain, don't draw 29 boxes:
  - **OpenAI surface** `/v1`: `chat`, `completions`, `models`
  - **Workflows** `/api/workflows`, `/api/workflow-index`, `/api/composer`, `/api/graph`
  - **Agents & A2A**: `/api/agents`, `/a2a`
  - **Knowledge/RAG**: `/api/documents`, `/api/memory`, `/api/context`, `/api/conversations`, `/api/provenance`, `/api/inventory`
  - **Extensibility**: `/api/mcp`, `/api/skills`, `/api/plugins`, `/api/discover`, `/api/roles`
  - **Platform/Admin**: `/api/system` (arch orchestration), `/api/keys`, `/api/profiles`, `/api/projects`, `/api/cloud-providers` `[ember]`, `/api/setup`, `/api/exports`, `/api/feedback`

### 4.3 Services (`api/services/` — group into clusters)
Draw as **labeled clusters**, with 2–4 key modules named inside each:

1. **Inference & Models** — `ollama_service.py`, `model_resolver.py`, `model_adapters.py`, `runner_registry.py` + `runner_detection.py` + `runner_impl/{ollama,vllm}.py`. (Process-wide `_LLM_SEMAPHORE`, default `MAX_CONCURRENT_LLM=1` — serialized on CPU.)
2. **Workflow Engine (the crown jewel)** — `workflow_engine.py`, `step_executor.py`, `scheduler.py`, `hook_bus.py`, `prompt_composer.py`, `scaffold_planner.py`, `spec_capture.py`. Step executors: `engine_executors/{parallel,loop,orchestrator,consolidate,ralph,a2a,code,code_promote}.py`.
3. **Architecture-aware Orchestration** — `architecture.py` (+ `arch_impl/{unified,nvidia_single,nvidia_multi,_nvml}.py`), `deployment.py` (+ `deployment_impl/{container,dmg,host_native}.py`), `orchestrator_protocol.py`, `co_scheduler.py`.
4. **Agents & A2A** — `agent_service.py`, `agent_generator.py`, `agentic_discovery.py`, `a2a_service.py`, `a2a_client.py` `[ember]`.
5. **RAG & Knowledge** — `rag_service.py`, `document_service.py`, `chunker.py`, `embedding_service.py` (+ `onnx/` encoders).
6. **Memory, Context & Provenance** — `memory_service.py`/`memory_store.py`, `context_store.py`, `conversation_store.py`, `provenance_store.py`.
7. **MCP & Skills & Discovery** — `mcp_service.py`, `mcp_runner_pool.py`, `tool_executor.py`, `plugin_service.py`, `discovery_service.py` (+ `discovery_providers/{mcp_registry,skills_marketplace}.py`) `[ember]`.
8. **Sandbox (code execution)** — `sandbox.py`, `sandbox_registry.py`, `sandbox_detection.py`, `sandbox_reaper.py`, `sandbox_fs.py` (+ `sandbox_impl/{container,subprocess,openshell}.py`).
9. **Security & Platform** — `api_key_service.py`, `config_validator.py`, `session_manager.py`, `project_service.py`, `profile_service.py`, `search_service.py` `[ember]`, `cloud_provider_service.py` `[ember]`, `eval_harness.py`.

### 4.4 Inference substrate
- **Ollama** — `:11434`, **GGUF**, **version-pinned `0.23.4`**. Default engine. Endpoints `/api/chat`, `/api/generate`, `/api/tags`, `/api/show`, `/api/version`. Keep-alive default `10m`.
- `[dashed]` **vLLM** — `:8000`, GPU, opt-in via `ENCLAVE_VLLM_BASE_URLS`. NVFP4/AWQ quant, continuous batching, paged-attention KV cache (BD790i).
- `[dashed]` **llama.cpp** — roadmap (`RunnerKind.LLAMA_CPP` reserved).
- **ONNX Runtime** — `onnx/` embeddings/rerank (CPU, torch-free fallback chain: Ollama → ONNX → sentence-transformers).
- **Model registry** — `models/download.py` (`MODEL_REGISTRY`, 4 tiers, GGUF q3/q4/q5_K_M). Authoritative doc `MODELS.md`.

### 4.5 Persistence (`data/` — file-based, **no DB**)
Atomic writes (tmp + `os.replace`) or append-only JSONL. Draw as labeled cylinders/folders:
- `data/vectors/` — **Chroma** vector DB (RAG embeddings)
- `data/conversations/*.json` — chat threads · `data/workflows/{run_id}/run.json` — run records + artifacts
- `data/memory/semantic/*.md` + `data/memory/episodic/*.jsonl` + `data/playbooks/*.md` — memory
- `data/provenance/responses/*.json` + `edges/*.jsonl` — citation/grounding chains
- `data/config/api_keys.yaml` (chmod 0600), `search_settings.json`, `mcp_servers.json`
- `data/cache/discovered_models.json`, `data/discovery/*`, `data/profiles/*.yaml`, `data/logs/`

### 4.6 Hardware / Fleet (roadmap 1.4.x — draw dashed)
| Host | Silicon | RAM | Role | Arch class |
|---|---|---|---|---|
| **Mac M4 Pro** | M4 Pro (Apple) | 48 GB unified | Dev / iteration | `apple_unified` |
| **MS-01** | Intel i9-13900H | 64 GB | API serving | `cpu_x86` |
| **BD790i** | Ryzen 9 7945HX + RTX 4000 Blackwell | 96 GB + GPU | Research flagship | `gpu_nvidia_single` |
Connected over **Tailscale**, one control plane, work routed to the box with the right RAM/VRAM. `[dashed]` for the whole band (1.4.x).

---

## 5. Key data flows to depict (annotate the arrows)

These are the "verbs" of the system — make the primary ones teal, label each arrow.

1. **Chat/inference (the live path):** Client → `POST /v1/chat/completions` → middleware → `chat` router → `ollama_service` (`_LLM_SEMAPHORE`) → Ollama/vLLM → **SSE stream** back. Optional branches off the router: RAG retrieval, web search `[ember]`, tool calling.
2. **RAG retrieval:** query → `embedding_service` → Chroma top-k → `rag_service` formats grounded context → injected into prompt → **provenance edges written** (`data/provenance/`).
3. **Workflow run:** YAML (`workflows/*.yaml`) → `workflow_engine` builds DAG → `scheduler.ready_steps()` per tick → `step_executor` dispatches by `kind` (llm/parallel/loop/orchestrator/consolidate/ralph/a2a/code) → Jinja2 prompt via `prompt_composer` → inference → `parser` + `quality_gate` → `run.json` + artifacts. `hook_bus` fires the 6-hook lifecycle around each step.
4. **Architecture-aware scheduling (the differentiator):** at startup `detect_architecture()` + `detect_deployment()` pick singletons. Per tick: `snapshot()` (memory pressure @1Hz) → `schedule_ready()` (placement + defer) → `transition_plan()` (evict prev / **pre-warm next model during current inference** to hide cold-load) → `co_scheduler` may substitute/split. Show the **pre-warm overlap** as the signature visual.
5. **Orchestrator step:** lead agent emits JSON directives (`spawn_worker` / `complete`) → engine spawns workers in child contexts under a budget (max workers/turns/tokens/wall-seconds) → results fed back to lead.
6. **A2A (external agents):** `[ember]` inbound `/a2a` JSON-RPC + SSE, discovery at `/.well-known/agent.json`; outbound via `a2a_client`.
7. **Consolidate → memory:** workflow `consolidate` step distills outputs into durable playbook/semantic/episodic memory under `data/memory/`.

---

## 6. Deployment topology (for Diagram D)

- **Base CPU stack** — `docker-compose.yml`: `ollama` (`0.23.4`, `:11434`) + `api` (FastAPI, `:8000`) + optional Open WebUI (`:8081`). Volumes `ollama_data`, `api_data`, `api_logs`. Auth on by default; first-run key → `data/config/first-run-key.txt`.
- **GPU override** — `docker-compose.gpu.yml` patches Ollama with NVIDIA device reservation (`OLLAMA_GPU_LAYERS=-1`, `FLASH_ATTENTION=1`).
- **BD790i flagship** — `docker-compose.bd790i.yml`: `network_mode: host`, API on `:8001`, **vLLM sidecar** (nvidia runtime, `Qwen3-8B-NVFP4`, fp8 KV cache) owns `:8000`.
- **Image** — `Dockerfile`: `python:3.11-slim`, non-root `appuser`, RAG deps (chromadb/langchain/sentence-transformers), bakes `api/ models/ agents/ workflows/ prompts/ plugins/ docs/seed/`, `EXPOSE 8000`, healthcheck `/health`.
- **MCP hardening** — stdio MCP subprocesses run with `cap_drop: [ALL]`, `no-new-privileges`, tmpfs `/tmp`.
- **Lifecycle** — `run.sh` (launch), `stop.sh` (teardown), `setup/install.sh` (venv). Requirements split: `requirements-core/-rag/-onnx/-ml/-dev/-playwright.txt`.

---

## 7. The five diagrams to produce

### Diagram A — **C4 Container view (HERO)**
The §3 six-band stack rendered properly. Group services (§4.3) into the 9 clusters, don't draw every module. Teal primary flow from a client all the way down to Ollama and back. Legend defines the color/stroke semantics from §2. Ship **both dark and light**. This is the one that goes in the README.

### Diagram B — **Request lifecycle / sequence (chat with RAG)**
Swimlane sequence: Client → Middleware → `chat` router → (`rag_service`→Chroma) → `ollama_service`→Ollama → SSE stream back → provenance write. Show the streaming token path distinctly. Mono for endpoints.

### Diagram C — **Workflow engine internals**
A small example DAG on the Drawflow-style canvas + the engine control loop beside it: `workflow_engine` → `scheduler` (ready-set) → `step_executor` (dispatch by `kind`) → `prompt_composer`/parser/quality-gate → `hook_bus` (6 hooks) → `run.json`. Call out the step kinds (llm/parallel/loop/orchestrator/consolidate/ralph/a2a/code). Node tints from `--node-*` tokens.

### Diagram D — **Deployment topology**
Three compose variants (§6) as stacked container groups, ports labeled, plus the dashed **fleet band** (Mac/MS-01/BD790i over Tailscale, 1.4.x). Show which engine each host runs (Ollama vs vLLM).

### Diagram E — **Architecture-aware orchestration (the differentiator)**
Conceptual diagram of `detect_architecture()` → the four arch classes (`apple_unified`, `cpu_x86`, `gpu_nvidia_single`, `gpu_nvidia_multi`) → the per-tick loop (pressure snapshot → schedule → transition plan) with the **pre-warm-next-while-current-runs overlap** as the centerpiece visual (a timeline showing the cold-load hidden under inference). Use amber/coral only for pressure levels.

---

## 8. Hard constraints & gotchas (so the diagram stays true)

- **No database.** Don't draw Postgres/Redis/SQLite. Persistence is files under `data/`.
- **No telemetry / no cloud inference by default.** Error reporting is **opt-in, off by default, operator-owned** — if you show it, make it dashed/ember and labeled "opt-in". Cloud providers `/api/cloud-providers` are also optional/ember.
- **Ports:** API `:8000` (or `:8001` on BD790i where vLLM takes `:8000`), Ollama `:11434`, Open WebUI `:8081`.
- **The console is one vanilla-JS file, not a React app** at runtime. The React component bundle in `docs/design/project/` is the *design source*, not what ships. Don't draw a Node/React build server in the runtime diagram.
- **vLLM / llama.cpp / fleet are dashed** (opt-in or roadmap). Ollama is the solid default.
- **CPU-first:** inference is serialized by default (`MAX_CONCURRENT_LLM=1`). The arch-aware scheduler is what makes multi-model DAGs feasible despite that — that's the story Diagram E tells.
- Keep module paths exact and in mono. If you need to abbreviate, abbreviate the *label* but keep one true path per cluster.

---

## 9. Reference files (read these if you want ground truth)
- `api/main.py` — app, middleware, router registration, lifespan
- `api/services/` — the ~60 service modules (clusters in §4.3)
- `api/services/workflow_engine.py`, `step_executor.py`, `engine_executors/` — Diagram C
- `api/services/architecture.py`, `deployment.py`, `co_scheduler.py` — Diagram E
- `docs/design/project/tokens/` — the exact CSS tokens (palette/type/motion/spacing)
- `docs/design/project/ui_kits/console-v2/` — canonical console look (match its texture)
- `docs/design/README.md` + `docs/design/chats/` — design intent
- `docker-compose*.yml`, `Dockerfile` — Diagram D
- `MODELS.md`, `models/download.py` — model registry
- `CLAUDE.md`, `CHANGELOG.md` — roadmap / what's shipped vs in-flight
