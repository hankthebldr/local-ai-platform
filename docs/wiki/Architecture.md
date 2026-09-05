# Architecture

How requests flow through Enclave, what runs where, and what to expect.

## Top-down view

```
CLI / WebUI / Mac app / pip embedder
            │
            ▼
   FastAPI (api/main.py, :8000)
   ├── routers/  16+ endpoint groups
   ├── middleware/  CORS, auth, request-id
   └── services/  22+ services
            │
            ├── ollama_service  ──►  Ollama (:11434)  ──►  GGUF inference
            │
            ├── workflow_engine  ──►  step_executor  ──►  ollama_service
            │   (1.3.0+: tick-based  │
            │    scheduler facade)   ├──►  prompt_renderer (Jinja2)
            │                        ├──►  output_parsers
            │                        ├──►  quality_gates
            │                        └──►  hook_bus (6-phase lifecycle)
            │
            ├── rag_service  ──►  Chroma (vector store) + chunker
            │
            └── architecture (detector)
                ├──►  arch_impl/{unified, nvidia_single, nvidia_multi}
                └──►  deployment_impl/{dmg, container, host_native}
```

## Process layout

The default deployment runs **two processes**:

| Process | Port | Purpose |
|---|---|---|
| `ollama serve` | 11434 | GGUF inference engine. CPU and GPU. Loads models from `~/.ollama/models/`. |
| `python -m api.main` (or `enclave-api`) | 8000 | FastAPI app. Talks to Ollama via HTTP, serves the dashboard, hosts the workflow engine. |

When you launch the DMG, both processes are managed by the desktop wrapper. The Docker compose stack runs them in two separate containers. On Linux you can use systemd units — see [Deployment](Deployment).

## Key code paths

| Concern | File | What it does |
|---|---|---|
| App boot | [`api/main.py`](https://github.com/hankthebldr/local-ai-platform/blob/main/api/main.py) | FastAPI app, CORS, middleware, auth bootstrap, arch detection, router registration. |
| OpenAI compat | `api/routers/chat.py`, `completions.py` | Drop-in `/v1/*` endpoints. |
| Workflow engine | [`api/services/workflow_engine.py`](https://github.com/hankthebldr/local-ai-platform/blob/main/api/services/workflow_engine.py) | DAG orchestrator. Tick-based scheduler (1.3.0+). |
| Step execution | [`api/services/step_executor.py`](https://github.com/hankthebldr/local-ai-platform/blob/main/api/services/step_executor.py) | Per-step model resolution, prompt render, Ollama call, parse, gate, hook fan-out. |
| Scheduler | [`api/services/scheduler.py`](https://github.com/hankthebldr/local-ai-platform/blob/main/api/services/scheduler.py) | Wraps `arch.schedule_ready()` + `arch.feasible()`; computes per-tick ready set. |
| Architecture detection | [`api/services/architecture.py`](https://github.com/hankthebldr/local-ai-platform/blob/main/api/services/architecture.py) | Detects memory + deployment topology at startup. Singleton accessor. |
| Model catalog | [`models/download.py`](https://github.com/hankthebldr/local-ai-platform/blob/main/models/download.py) | `MODEL_REGISTRY` — 18+ models, mirrors [`MODELS.md`](https://github.com/hankthebldr/local-ai-platform/blob/main/MODELS.md). |
| RAG | `api/services/rag_service.py`, `chunker_service.py` | Chroma vector store, semantic chunker, document ingestion. |

## Architecture-aware orchestration (1.3.0+)

At app startup the detector classifies the host into a `MemoryArchitecture` + `Deployment` pair:

| Memory architecture | Examples | Eviction strategy |
|---|---|---|
| `unified` | Apple Silicon, x86 CPU-only | Freshness-by-default; aggressive eviction since RAM is the bottleneck. |
| `nvidia_single` | One CUDA GPU | Keep loaded if VRAM available; evict on pressure. |
| `nvidia_multi` | Multiple CUDA GPUs | Layer-aware placement; per-step `gpu_affinity` hint. |

| Deployment | Detection |
|---|---|
| `dmg` | Sees `Enclave.app/Contents/Resources/...` in `sys.path` or `ENCLAVE_DEPLOYMENT=dmg`. |
| `container` | `/.dockerenv` exists OR `ENCLAVE_DEPLOYMENT=container`. |
| `host_native` | Default fallback. |

Live snapshots at:
- `GET /api/system/architecture` — consolidated triple (arch + deployment + ollama probe)
- `GET /api/system/pressure` — live VRAM/RAM pressure
- `POST /api/system/architecture/refresh` — re-detect

The workflow engine records Ollama load / prompt-eval / eval durations per step (Phase 2) and dispatches a per-tick ready set through `arch.schedule_ready()` (Phase 4b).

Design: [`docs/plans/2026-05-19-architecture-aware-orchestration-design.md`](https://github.com/hankthebldr/local-ai-platform/blob/main/docs/plans/2026-05-19-architecture-aware-orchestration-design.md).

## Read more

- [Workflows](Workflows) — YAML pipeline format
- [Agents](Agents) — YAML persona format
- [CLAUDE.md](https://github.com/hankthebldr/local-ai-platform/blob/main/CLAUDE.md) — developer entrypoint
