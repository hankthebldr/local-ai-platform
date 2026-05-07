# CLAUDE.md

Guidance for Claude Code working on this repo.

## Project

Enclave by ohno llc — self-hosted local LLM platform, CPU-first, privacy-first. Fleet:
Mac M4 Pro 48GB (dev) · MS-01 64GB (API) · BD790i 96GB (flagship).
Authoritative model catalog: [MODELS.md](./MODELS.md).

## Core workflow

1. **Always activate venv first:** `source venv/bin/activate`
2. Edit code → auto-formatter runs (via hook) → commit.
3. Run API: `python api/main.py` (port 8000). Ollama: `ollama serve` (11434).
4. Run tests: `pytest tests/ --ignore=tests/e2e -v`

## Architecture boundaries

```
FastAPI (api/main.py, routers/, services/) → Ollama (or vLLM/llama.cpp later)
```

Key files by responsibility:
- `api/routers/` — HTTP surface, one file per concern (chat, completions, workflows, …)
- `api/services/` — business logic (ollama, workflow engine, prompt composer, model adapters)
- `api/services/step_executor.py` + `workflow_engine.py` — **multi-agent workflow engine** (see workflow-engine-expert subagent)
- `api/hooks/builtins/` — declarative workflow hooks (json_schema, retry, etc.)
- `api/hooks/custom/` — project-specific hooks, auto-discovered
- `models/download.py` — `MODEL_REGISTRY` (must stay in sync with MODELS.md)
- `cli/` — Rich-based CLI tools (chat, workflow, benchmark)
- `workflows/*.yaml` — declarative multi-agent workflow definitions

## Don't touch without care

- `api/main.py` — production API surface, CORS/middleware lives here
- `api/services/workflow_engine.py`, `step_executor.py` — core engine (use workflow-engine-expert agent)
- `Dockerfile`, `docker-compose.yml` — deployment
- `.env` — **never commit** (secret scan hook blocks it)
- `MODELS.md` — authoritative model doc; update whenever `MODEL_REGISTRY` changes

## Common tasks

- **Add a model:** edit `MODEL_REGISTRY` in `models/download.py` → update `MODELS.md` (sync hook will remind you).
- **Add a workflow:** `workflows/<name>.yaml` using `schema_version: 2`. See spec in `docs/superpowers/plans/2026-04-20-workflow-prompt-framework.md`.
- **Add a built-in hook:** new file in `api/hooks/builtins/<name>.py`. Declare `name`, `stage`, `__call__(ctx) -> HookResult`. Test in `tests/hooks/`.
- **Add a project-specific hook:** drop a `.py` in `api/hooks/custom/` using `@register_hook`. Auto-discovered.
- **Add a model-family adapter:** extend `api/services/model_adapters.py` and register a substring pattern.

## Release track

Current: **0.1.x** — Foundation. Workflow prompt framework shipped in PR #11.

Roadmap:
- `0.2.x` — streaming, vLLM/llama.cpp backends, Web UI
- `0.3.x` — fine-tuning (Axolotl/Unsloth)
- `0.4.x` — full RAG integration (langchain + chroma already partially in place)
- `1.0.0` — auth, ≥70% test coverage, Docker/K8s, Prometheus, structured logging

See [PROJECT_PLAN.md](./PROJECT_PLAN.md) for detail.

## Pointers

- Enterprise-readiness gaps: [ENTERPRISE_DEPLOYMENT_GAPS.md](./ENTERPRISE_DEPLOYMENT_GAPS.md)
- Workflow engine design: `docs/plans/2026-04-06-multi-agent-workflow-engine-design.md`
- Prompt framework plan: `docs/superpowers/plans/2026-04-20-workflow-prompt-framework.md`
- Claude Code config plan (this file's supporting hooks): `docs/superpowers/plans/2026-04-22-claude-code-config.md`
- Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md

## Conventions

- **Quantization:** Q4_K_M default, Q5_K_M for quality, Q3_K_M for 70B+.
- **Performance targets:** 7B≈40-50 t/s, 13B≈25-30 t/s, 34B≈10-15 t/s, 70B≈3-5 t/s on the fleet.
- **Uncensored-first:** dolphin-mixtral, dolphin-mistral, nous-hermes2-mixtral, yi-34b, wizardlm-uncensored, mythomax.
- **OpenAI-compatible API surface:** clients can switch between Ollama/vLLM/llama.cpp backends transparently.
- **No telemetry. No cloud. All data local.**
