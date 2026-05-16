# CLAUDE.md

Guidance for Claude Code working on this repo.

## Project

Enclave — self-hosted local LLM platform. CPU-first inference, privacy-first, no telemetry. Fleet:
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

Current: **`1.0.0`** — first public Enclave release (shipped 2026-04-18). Initial product surface (API, CLI, Mac DMG, workflow engine, RAG); not yet enterprise-grade for multi-tenant production. See [ENTERPRISE_DEPLOYMENT_GAPS.md](./ENTERPRISE_DEPLOYMENT_GAPS.md).

What's in 1.0.0:
- Core infra (Ollama + systemd + macOS DMG)
- 18-model registry · CLI chat · OpenAI-compatible API with streaming
- 16 routers / 22 services · API-key auth + rotation + plugins
- Multi-agent workflow engine (DAG, Jinja2 prompts, parsers, quality gates, checkpoint/resume, 6-hook lifecycle)
- RAG pipeline (Chroma + chunker + document service)
- CI on Python 3.12/3.13 · Release (DMG) · Pages
- 46 test files (unit/integration/e2e/hooks/ui)

Roadmap:
- `1.1.x` — workflow refinements, backlog wins, docs hygiene
- `1.x` — additional inference engines (vLLM, llama.cpp), fine-tuning, Web UI polish
- `2.0.0` — enterprise hardening: ≥70% coverage, full RBAC, Prometheus + Grafana, K8s/HA, distributed tracing

## Pointers

- Enterprise gaps: [ENTERPRISE_DEPLOYMENT_GAPS.md](./ENTERPRISE_DEPLOYMENT_GAPS.md)
- Workflow engine design: `docs/plans/2026-04-06-multi-agent-workflow-engine-design.md`
- Prompt framework plan: `docs/superpowers/plans/2026-04-20-workflow-prompt-framework.md`
- Claude Code config plan (this file's hooks): `docs/superpowers/plans/2026-04-22-claude-code-config.md`
- Hook library: `.claude/hooks/README.md`
- Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md

## Conventions

- **Quantization:** Q4_K_M default · Q5_K_M for quality · Q3_K_M for 70B+.
- **Performance targets (CPU):** 7B≈40-50 t/s · 13B≈25-30 t/s · 34B≈10-15 t/s · 70B≈3-5 t/s.
- **Uncensored-first:** dolphin-mixtral, dolphin-mistral, nous-hermes2-mixtral, yi-34b, wizardlm-uncensored, mythomax.
- **OpenAI-compatible API:** clients switch between Ollama / vLLM / llama.cpp transparently.
- **CORS / Auth defaults:** CORS to `["*"]` only if `CORS_ORIGINS` unset (startup warning fires); auth off by default (`ENABLE_API_AUTH=false`) — set both before non-localhost exposure.
- **No telemetry. No cloud. All data local.**
