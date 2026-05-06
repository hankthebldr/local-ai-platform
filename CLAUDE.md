# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Enclave (by ohno llc) is a comprehensive self-hosted infrastructure for running uncensored local LLM models with CPU-optimized inference. Built for a three-machine fleet: Mac M4 Pro 48GB (dev), MS-01 64GB DDR5 (API serving), BD790i 96GB DDR5 (research/flagship) with focus on privacy, performance, and customization.

> **Model Strategy & Lifecycle**: See [MODELS.md](./MODELS.md) — authoritative source for
> flagship model selection, per-machine assignments, and install/remove sequences.

**Core Architecture**: Python-based platform with Ollama as the primary inference engine, FastAPI for OpenAI-compatible API, and modular design supporting multiple LLM backends (vLLM, llama.cpp).

## Key Commands

### Environment Setup
```bash
# Activate virtual environment (REQUIRED before all Python commands)
source venv/bin/activate

# Install/update dependencies
pip install -r setup/requirements.txt

# Initial setup
./setup/install.sh
```

### Running the Platform
```bash
# Start Ollama service (systemd)
systemctl --user start ollama.service
systemctl --user status ollama.service

# Or manually
ollama serve

# Start API server
python api/main.py
# API available at http://localhost:8000
# Docs at http://localhost:8000/docs

# CLI chat interface
python cli/chat.py --model mistral
python cli/chat.py --model dolphin-mixtral --host http://localhost:11434
```

### Model Management
```bash
# List available models in registry
python models/download.py --list

# Show model info
python models/download.py --info dolphin-mixtral

# Download via Ollama (default, fastest)
python models/download.py dolphin-mixtral

# Download from Hugging Face
python models/download.py dolphin-mixtral --source huggingface

# List installed models
ollama list

# Test a model
ollama run mistral "Explain quantum computing"
```

### Testing & Verification
```bash
# Health check
curl http://localhost:8000/health

# List available models
curl http://localhost:8000/v1/models

# Test chat completion
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'

# Test text completion
curl http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral",
    "prompt": "Once upon a time"
  }'

# Check Ollama status
systemctl --user status ollama.service
curl http://localhost:11434/api/tags

# Run tests (when implemented)
pytest tests/ -v
```

### Development
```bash
# Code formatting
black api/ cli/ models/ finetuning/

# Linting
flake8 api/ cli/ models/

# Type checking
mypy api/ cli/
```

## Architecture

### Component Interaction Flow
```
User → CLI/WebUI → FastAPI → Ollama/vLLM/llama.cpp → Local Models
                    ↓
                 Services Layer (api/services/)
                    ↓
                 Vector DB (Chroma) / RAG
```

### Key Design Patterns

**1. Inference Engine Abstraction**
- Primary: Ollama (GGUF models, best CPU performance)
- Secondary: vLLM (production serving), llama.cpp (direct C++ inference)
- All exposed via OpenAI-compatible API in `api/main.py`

**2. Model Registry System**
- Centralized in `models/download.py` → `MODEL_REGISTRY`
- Contains metadata: sources (Ollama/HF/GGUF), size, speed, tags
- Supports multiple download sources for same model

**3. API Layer**
- `api/main.py`: Main FastAPI app with OpenAI-compatible endpoints
- `/v1/chat/completions`: Chat interface
- `/v1/completions`: Text completion
- `/v1/models`: List available models
- Converts OpenAI format ↔ Ollama format

**4. Configuration**
- Environment-based via `.env` file
- Key vars: `OLLAMA_HOST`, `API_HOST`, `API_PORT`, `API_KEY`
- Model configs in `config/` (YAML-based when implemented)

### Directory Structure
- `api/`: FastAPI server (OpenAI-compatible API)
  - `routers/`: Endpoint definitions (to be implemented)
  - `services/`: Business logic for Ollama/vLLM/RAG (to be implemented)
  - `utils/`: Helper functions (to be implemented)
- `cli/`: Command-line tools
  - `chat.py`: Interactive chat with rich formatting
  - `query.py`: Single-shot queries (to be implemented)
  - `benchmark.py`: Performance testing (to be implemented)
- `models/`: Model management
  - `download.py`: Model download/registry manager
- `finetuning/`: Training scripts and configs (to be implemented)
- `setup/`: Installation scripts
  - `install.sh`: Master installer
  - `requirements.txt`: Python dependencies
- `data/`: Runtime data (gitignored)
  - `models/`: Downloaded model files
  - `vectors/`: Vector database storage
  - `cache/`: Inference cache
  - `logs/`: Application logs

## Important Conventions

### Model Quantization Strategy
- **Q4_K_M**: Default - best quality/speed balance for most models
- **Q5_K_M**: Higher quality, slightly slower
- **Q3_K_M**: For large 70B+ models to fit in memory
- Context: 60GB RAM supports up to 70B Q4, 120B Q3

### Performance Targets
- 7B models: 40-50 tokens/sec
- 13B models: 25-30 tokens/sec
- 34B models: 10-15 tokens/sec
- 70B models: 3-5 tokens/sec

### Uncensored Model Focus
Primary model tier in registry emphasizes uncensored models:
- dolphin-mixtral, dolphin-mistral (Cognitive Computations)
- nous-hermes2-mixtral, yi-34b
- wizardlm-uncensored-13b, mythomax

### API Response Format
All API endpoints convert between OpenAI format (for client compatibility) and native Ollama format. This abstraction allows switching backends without client changes.

## Release Track (SemVer)

All planning, features, and build artifacts follow semantic versioning. `1.0.0`
shipped 2026-04-18 as the first public Enclave release — it marks the initial
product surface (API, CLI, Mac DMG, workflow engine, RAG) rather than enterprise-
grade production readiness. The enterprise hardening bar (auth maturity,
observability, HA, ≥70% coverage) is still the target, tracked separately in
[ENTERPRISE_DEPLOYMENT_GAPS.md](./ENTERPRISE_DEPLOYMENT_GAPS.md).

**Current release**: `1.0.0` — initial public Enclave release
- ✓ Core infrastructure (Ollama + systemd service + macOS DMG)
- ✓ Model registry and downloader (18 models — see MODELS.md)
- ✓ CLI chat with Rich formatting
- ✓ OpenAI-compatible API (chat, completions, models) with streaming
- ✓ Router/service layer (populated: 15 routers, 22 services)
- ✓ API-key authentication with rotation + plugin system
- ✓ Multi-agent workflow engine (6-hook lifecycle, retry/escalation, v2 YAML)
- ✓ RAG pipeline (Chroma + chunker + document service)
- ✓ CI (pytest on 3.12/3.13 matrix), Release (DMG build + GitHub Release), Pages
- ✓ Automated tests (46 files across unit / integration / e2e / hooks / ui)

**Roadmap**:
- `1.1.0` — ongoing work since `1.0.0`: workflow engine refinements, backlog wins, docs hygiene
- `1.x` — incremental features: additional inference engines (vLLM, llama.cpp), fine-tuning pipeline, Web UI polish
- `2.0.0` — enterprise hardening bar: ≥70% coverage, full authz, Prometheus + Grafana, Docker/K8s production topology, HA, distributed tracing
- `1.x.y` — patch releases for bug fixes and doc updates

## Critical Context

### Why CPU-Focused
AMD integrated GPU has limited ROCm support. Design optimizes for CPU inference with GGUF quantized models via llama.cpp backend (used by Ollama).

### Ollama as Primary Backend
Chosen for:
- Best CPU performance
- Built-in model management
- OpenAI-compatible API
- GGUF format support
- Dead simple to use

### Privacy & Local-First
- No internet required for inference
- All data stays local
- No telemetry by default
- Designed for complete autonomy

## Common Patterns

### Adding a New Model to Registry
Edit `models/download.py` → `MODEL_REGISTRY`:
```python
"model-id": {
    "name": "Display Name",
    "ollama": "ollama-model-name",
    "huggingface": "org/repo",
    "gguf": "TheBloke/repo-GGUF",
    "size": "XGB",
    "speed": "X-Y tok/s",
    "description": "Brief description",
    "tags": ["tag1", "tag2"]
}
```

### API Endpoint Pattern (current implementation in `api/main.py`)
Current approach (inline, not using routers):
1. Define Pydantic models for request/response
2. Import `requests` inside endpoint (not at module level - could be improved)
3. For chat: Build prompt from messages array → call Ollama `/api/generate` → convert to OpenAI format
4. For completions: Direct pass-through to Ollama with format conversion
5. Handle errors with HTTPException and 500 status

Future refactoring should:
- Move business logic to `api/services/ollama_service.py`
- Move endpoints to `api/routers/chat.py` and `api/routers/completions.py`
- Import requests at module level for better performance
- Add proper token counting
- Implement streaming support

### CLI Tool Pattern (see `cli/chat.py`)
- Use Rich library for formatting (Console, Panel, Markdown)
- Modern color scheme: bright_magenta for user, bright_blue for AI, bright_cyan for commands
- Maintain conversation history in memory (not persisted)
- Implement commands with `/` prefix (`/help`, `/clear`, `/models`, `/exit`)
- Handle Ctrl+C gracefully (continue session, not exit)
- Markdown rendering for AI responses

## Development Workflow

1. Always activate venv first: `source venv/bin/activate`
2. Make changes to code
3. Test manually with CLI/API
4. Format with black before committing: `black api/ cli/ models/`
5. No CI/CD setup yet - manual testing only

### Workflow Engine

Best-in-class multi-agent DAG orchestrator. Executes step-based workflows defined in YAML with parallel batch scheduling, Jinja2 prompt templating, structured output parsing, quality gates, conditional branching, and checkpoint/resume.

**Architecture:**
- `api/models/workflow_models.py` — Pydantic v2 models with enums (StepStatus, RunStatus, OutputFormat, GateOperator)
- `api/services/workflow_compiler.py` — DAG validation, cycle detection, parallel batch scheduling (Kahn's algorithm)
- `api/services/workflow_engine.py` — Orchestrator: compile → execute batches → persist. ThreadPoolExecutor for parallel steps.
- `api/services/step_executor.py` — Single step: conditions → prompt render → LLM → parse → gates → context
- `api/services/prompt_renderer.py` — Jinja2/simple template engine with 11 built-in filters
- `api/services/output_parsers.py` — Structured extraction: JSON, JSON array, markdown sections, regex, CSV, key-value
- `api/services/quality_gates.py` — 15 gate operators: not_empty, contains, matches, has_key, all_keys, gt, lt, etc.
- `api/services/workflow_events.py` — Pub/sub event bus with typed events (workflow/batch/step/gate lifecycle)
- `api/services/model_resolver.py` — Role-based model selection via Ollama inventory
- `api/routers/workflows.py` — REST API endpoints
- `cli/workflow.py` — Rich CLI with DAG tree visualization

**Running workflows:**
```bash
# CLI
python cli/workflow.py run workflows/xsiam-data-model-rules.yaml \
  --seed '{"log_samples": "...", "vendor_name": "PAN-OS", "log_type": "firewall", "constraints": "XDM v3"}'
python cli/workflow.py compile workflows/xsiam-data-model-rules.yaml
python cli/workflow.py list
python cli/workflow.py runs
python cli/workflow.py status <run_id>

# API
curl -X POST http://localhost:8000/api/workflows/run \
  -H "Content-Type: application/json" \
  -d '{"workflow_id": "xsiam-data-model-rules", "seed": {"log_samples": "...", "vendor_name": "PAN-OS"}}'
curl -X POST http://localhost:8000/api/workflows/compile \
  -d '{"workflow_id": "xsiam-data-model-rules", "seed_keys": ["log_samples", "vendor_name"]}'
```

**Key features:**
- **DAG execution** — Steps declare `depends_on` + implicit deps from input refs. Compiler builds parallel batches.
- **Jinja2 prompts** — `system_prompt: "Analyze {{seed.data|json}}"` with filters: json, truncate, keys, count, join, etc.
- **Output parsers** — `output_parser: {format: json}` — auto-extracts structured data from LLM responses
- **Quality gates** — `quality_gates: [{name: check, field: data, operator: not_empty}]` — validate outputs before downstream
- **Conditions** — `condition: {ref: step_a.status, operator: equals, value: completed}` — skip steps conditionally
- **Loops** — `loop: {over: seed.files, as_var: file}` — iterate steps over collections
- **Checkpoint/resume** — `engine.run(defn, seed, resume_from="checkpoint_name")`
- **Event bus** — Subscribe to step.started, step.completed, gate.failed, etc. for real-time monitoring

**Context model (three layers):**
- `seed` — immutable user input
- `workspace` — namespaced per-step outputs (dot-walk: `step_id.key.nested.path`)
- `shared` — mutable cross-cutting state

**Model selection:** `role: reasoning|fast|coding|uncensored|general` (resolved via inventory) or `model: "exact-name"`.

**XSIAM workflow:** `workflows/xsiam-data-model-rules.yaml` — 5-step pipeline aligned with PANW normalization methodology (raw → parsed → XDM → enriched) with NICE Framework analytics mapping.

**Design doc:** `docs/plans/2026-04-06-multi-agent-workflow-engine-design.md`

### Custom Agents (Gems)

YAML-backed reusable agent personas — local alternative to Claude Gems / OpenAI GPTs.

**Architecture:**
- `api/models/agent_models.py` — Pydantic models: ContextSource (5 types), AgentTool (3 types), AgentDefinition
- `api/services/agent_service.py` — CRUD, context resolution (file/url/graph_query/workflow_output/text), message building
- `api/routers/agents.py` — REST API: list, get, create, update, delete, chat, context preview
- `agents/*.yaml` — Agent definitions (YAML files on disk, UI creates/edits via API)

**Usage:**
```bash
# API
curl http://localhost:8000/api/agents                    # List agents
curl -X POST http://localhost:8000/api/agents/{id}/chat  # Chat with agent
curl http://localhost:8000/api/agents/{id}/context        # Preview resolved context
```

**Context sources:** Agents can pin files, URLs, graph queries, workflow outputs, or inline text as context — resolved at chat time so agents always have fresh data.

**Example:** `agents/xsiam-analyst.yaml` — XSIAM data model specialist with workflow integration.

### Context Graph

D3.js force-directed knowledge graph with five node types: sessions, topics, sources, agents, workflow runs.

**Key files:**
- `api/services/graph_service.py` — Builds graph from exports, agents, and workflow runs. Includes `search_nodes(query)` for agent context resolution.
- `api/routers/graph.py` — Graph data endpoints + deep research orchestration

**Node types:** session (green), topic (grey), source (blue), agent (orange), workflow_run (purple)

### macOS Desktop App

Native macOS app wrapping the dashboard in a WKWebView window via pywebview.

**Files:**
- `desktop/app.py` — Launcher: starts Ollama → starts FastAPI on random port → opens native window
- `desktop/setup_app.py` — py2app build configuration
- `desktop/build.sh` — One-command build: `./desktop/build.sh` → `desktop/dist/Local AI Platform.app`
- `desktop/entitlements.plist` — Code signing entitlements

**Run in dev mode:** `python desktop/app.py` — opens native window with dashboard.

### Common Development Tasks

**Adding a streaming endpoint**:
- Ollama supports streaming via `"stream": true` in request
- Response comes as newline-delimited JSON (NDJSON)
- Use FastAPI's `StreamingResponse` with generator function
- See Ollama API docs for response format

**Adding a new inference backend**:
1. Create service in `api/services/<backend>_service.py`
2. Implement same interface: `generate(prompt, model, **kwargs)`
3. Add backend selection logic in API endpoints or create new router
4. Update configuration to specify which backend to use

**Implementing router/service separation**:
1. Create `api/services/ollama_service.py` with business logic from `api/main.py`
2. Create routers in `api/routers/` (e.g., `chat.py`, `completions.py`, `models.py`)
3. Update `api/main.py` to include routers: `app.include_router(chat_router)`
4. Move Pydantic models to `api/models.py` or keep in routers

## Known Limitations & Implementation Status

**API Layer**:
- Router/service separation is in place; new endpoints should follow the existing pattern rather than the legacy inline style in `api/main.py`
- Token counts in OpenAI-compatible usage metrics come straight from Ollama (`eval_count`/`prompt_eval_count`); when the upstream omits them the response reports `0`
- CORS defaults to `["*"]` if `CORS_ORIGINS` is unset. The shipped `.env.example` and `docker-compose.yml` restrict it to localhost; `api/main.py` emits a startup warning if the wildcard survives or auth is off while bound to a non-localhost host
- Authentication is off by default (`ENABLE_API_AUTH=false`); operators must set it to `true` and provision `API_KEY` before any non-localhost exposure

**Features Not Yet Built**:
- Fine-tuning pipeline (dependencies installed but no implementation)
- Additional inference backends beyond Ollama (vLLM, llama.cpp — scaffolding only)
- Rate limiting per API key (scopes enforced; per-key RPM field stored but not rate-limited yet)
- MCP transport adapter (design doc at `docs/plans/2026-04-27-mcp-transport-adapter-design.md`)

**Data Persistence**:
- CLI conversation history is in-memory only (lost on exit)
- `/api/context` endpoints expose active in-memory conversation state; no persistent store

**UI Coverage**:
- All 16 routers are registered and have UI surfaces in `api/static/index.html`
- `GET /api/context` and `GET /api/agents/{id}/context` are debug endpoints without UI panels (by design)

## Troubleshooting

### Ollama Service Issues
```bash
# Check if Ollama is running
systemctl --user status ollama.service

# Start Ollama manually (for debugging)
ollama serve

# Check Ollama logs
journalctl --user -u ollama.service -f

# Test Ollama directly
curl http://localhost:11434/api/tags
```

### API Connection Errors
- Verify Ollama is running: `curl http://localhost:11434/api/tags`
- Check OLLAMA_HOST in `.env` matches Ollama's actual host/port
- Ensure no firewall blocking port 11434 or 8000
- For "connection refused": Start Ollama service first

### Model Download Issues
- Large models require significant disk space (check `df -h`)
- Network interruptions: Ollama downloads are resumable, re-run same command
- For Hugging Face: May need to authenticate with `huggingface-cli login`

### Performance Issues
- CPU-bound inference: Ensure `OLLAMA_NUM_PARALLEL` not set too high (default: 2)
- Memory issues: Use smaller models or more aggressive quantization (Q3 vs Q4)
- Check system load: `htop` or `top` to see CPU/RAM usage

## Enterprise Deployment

**⚠️ IMPORTANT**: Enclave `1.0.0` shipped as the first public product release. It is
**not** yet enterprise-grade for multi-tenant production deployment. See
[ENTERPRISE_DEPLOYMENT_GAPS.md](./ENTERPRISE_DEPLOYMENT_GAPS.md) for the gap analysis;
the `2.0.0` roadmap line targets that bar.

**What's already in place (updated 1.0.0)**:
- API-key authentication + middleware + rotation
- CI pipeline (pytest matrix on 3.12/3.13, lint, release DMG build)
- Automated test suite (~30 test files, unit + integration + e2e)
- Docker + docker-compose for local/single-host deployment
- Streaming API endpoints
- Structured workflow engine with hook lifecycle

**Still required for enterprise-grade deployment**:
1. Tighten CORS (currently `allow_origins=["*"]`)
2. Add rate limiting per API key
3. Increase test coverage to ≥70% and wire coverage reporting in CI
4. Implement Prometheus metrics + Grafana dashboards (client installed but unused)
5. Kubernetes manifests / Helm chart for HA topology
6. Liveness / readiness health checks beyond the existing `/health`
7. Structured logging with correlation IDs
8. Automated backups and disaster recovery runbook
9. Authorization (RBAC) on top of authentication
10. Distributed tracing (OpenTelemetry)

**Recommended Path**: Follow the phased roadmap in [ENTERPRISE_DEPLOYMENT_GAPS.md](./ENTERPRISE_DEPLOYMENT_GAPS.md); target is the `2.0.0` release line.

## References

- Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md
- OpenAI API: https://platform.openai.com/docs/api-reference
- See PROJECT_PLAN.md for detailed architecture and roadmap
- See README.md for user-facing documentation
- See ENTERPRISE_DEPLOYMENT_GAPS.md for production deployment requirements
