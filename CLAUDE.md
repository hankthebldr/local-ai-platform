# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local AI Platform is a comprehensive self-hosted infrastructure for running uncensored local LLM models with CPU-optimized inference. Built for AMD Ryzen 9 7945HX (32 threads, 60GB RAM) with focus on privacy, performance, and customization.

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

### Testing
```bash
# Run tests (when implemented)
pytest tests/
pytest tests/test_api.py -v

# Test API endpoint
curl http://localhost:8000/health
curl http://localhost:8000/v1/models
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

**Current**: Phase 1 - Foundation Setup
- ✓ Core infrastructure (Ollama, FastAPI skeleton)
- ✓ Model download system with comprehensive registry
- ✓ CLI chat interface with rich formatting
- ✓ Basic API with OpenAI compatibility
- ⏳ Router/service layer implementation
- ⏳ Streaming support
- ⏳ RAG implementation

**Next Phases**:
- Phase 2: Multiple inference engines (vLLM, llama.cpp), Web UI
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

### API Endpoint Pattern
1. Define Pydantic model for request
2. Call Ollama API via requests
3. Convert response to OpenAI format
4. Handle errors with HTTPException

### CLI Tool Pattern (see `cli/chat.py`)
- Use Rich for formatting (Console, Panel, Markdown)
- Maintain conversation history
- Implement commands with `/` prefix
- Handle Ctrl+C gracefully

## Development Workflow

1. Always activate venv first: `source venv/bin/activate`
2. Make changes to code
3. Test manually with CLI/API
4. Format with black before committing
5. No CI/CD setup yet - manual testing only

## Known Limitations

- Router/service layers in `api/` are skeleton directories (not implemented)
- Streaming responses not yet implemented
- Fine-tuning pipeline planned but not built
- RAG system planned but not built
- No automated tests yet
- No Docker deployment yet

## References

- Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md
- OpenAI API: https://platform.openai.com/docs/api-reference
- See PROJECT_PLAN.md for detailed architecture and roadmap
- See README.md for user-facing documentation
