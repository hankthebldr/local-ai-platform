# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local AI Platform is a comprehensive self-hosted infrastructure for running uncensored local LLM models with CPU-optimized inference. Built for a three-machine fleet: Mac M4 Pro 48GB (dev), MS-01 64GB DDR5 (API serving), BD790i 96GB DDR5 (research/flagship) with focus on privacy, performance, and customization.

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

## Project Status & Phase

**Current**: Phase 1 - Foundation Setup (Mostly Complete)
- ✓ Core infrastructure (Ollama + systemd service)
- ✓ Model download system with comprehensive registry (18 models in catalog — see MODELS.md)
- ✓ CLI chat interface with modern color scheme
- ✓ Functional API with OpenAI compatibility (chat/completions endpoints working)
- ✓ Installation automation via `setup/install.sh`
- ⏳ Router/service layer implementation (directories created, not populated)
- ⏳ Streaming support (API structure ready, not implemented)
- ⏳ RAG implementation
- ⏳ Automated tests

**Next Phases**:
- Phase 2: Streaming responses, multiple inference engines (vLLM, llama.cpp), Web UI
- Phase 3: Fine-tuning pipeline (Axolotl/Unsloth)
- Phase 4: RAG with Chroma, LangChain integration
- Phase 5: Docker deployment, optimization

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
- `api/main.py` has working endpoints but uses inline logic (no routers/services separation)
- Router/service layers in `api/` are empty skeleton directories
- Streaming responses not implemented (request model has stream parameter but not used)
- No actual token counting (returns 0 in usage metrics)
- No API key authentication implemented (env var defined but not enforced)

**Features Not Yet Built**:
- Fine-tuning pipeline (dependencies installed but no implementation)
- RAG system (ChromaDB/LangChain installed but not integrated)
- No automated tests (pytest installed, `tests/` directory empty)
- No Docker deployment (Dockerfile/compose files planned but not created)
- Web UI integration (Open WebUI installable but not configured)

**Data Persistence**:
- CLI conversation history is in-memory only (lost on exit)
- No conversation logging/export
- No metrics/usage tracking

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

## References

- Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md
- OpenAI API: https://platform.openai.com/docs/api-reference
- See PROJECT_PLAN.md for detailed architecture and roadmap
- See README.md for user-facing documentation
