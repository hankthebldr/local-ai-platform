# Local AI Platform

> **Cortex — Self-Hosted AI Infrastructure with Multi-Agent Workflows**
> Local LLM inference, YAML-backed custom agents, DAG workflow orchestration, and a Cortex-branded mission control dashboard. Privacy-first, runs entirely on your hardware.

[![Status](https://img.shields.io/badge/status-beta-green)](https://github.com/hankthebldr/local-ai-platform)
[![Tests](https://img.shields.io/badge/tests-276%20passing-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.9+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

---

## Quick Start (Local Development)

```bash
# 1. Clone and enter
git clone https://github.com/hankthebldr/local-ai-platform.git
cd local-ai-platform

# 2. Create virtual environment and install deps
python3 -m venv venv
source venv/bin/activate
pip install -r setup/requirements.txt

# 3. Install Ollama (if not installed)
curl -fsSL https://ollama.ai/install.sh | sh

# 4. Start Ollama and pull a model
ollama serve &                     # Start in background (or use systemd)
ollama pull deepseek-r1:32b        # Or any model you prefer

# 5. Start the API server + dashboard
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 6. Open dashboard
open http://localhost:8000          # macOS
# or visit http://localhost:8000 in your browser
```

The dashboard provides 7 tabs: **Dashboard** (system status + chat), **Models** (install/remove/manage), **Memory** (resource usage), **Discover** (HuggingFace browser), **Research** (knowledge graph), **Workflows** (DAG runner), **Agents** (custom gems).

### Native macOS App (Optional)

```bash
pip install pywebview
python desktop/app.py              # Opens a native window with the dashboard
```

### CLI Chat

```bash
source venv/bin/activate
python cli/chat.py --model deepseek-r1:32b
```

### Run Workflows

```bash
# Compile and inspect the execution plan
python cli/workflow.py compile workflows/xsiam-data-model-rules.yaml

# Execute with seed data
python cli/workflow.py run workflows/xsiam-data-model-rules.yaml \
  --seed '{"log_samples": "...", "vendor_name": "PAN-OS", "log_type": "firewall", "constraints": "XDM v3"}'

# List available workflows and recent runs
python cli/workflow.py list
python cli/workflow.py runs
```

### Custom Agents

```bash
# List agents via API
curl http://localhost:8000/api/agents

# Chat with the XSIAM analyst agent
curl -X POST http://localhost:8000/api/agents/xsiam-analyst/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Analyze PAN-OS firewall logs for XDM mapping"}]}'

# Create agents via YAML — just add a file to agents/
cat agents/xsiam-analyst.yaml
```

---

## Table of Contents

- [Overview](#overview)
- [Current Status](#current-status)
- [Features](#features)
- [System Requirements](#system-requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [API Reference](#api-reference)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## Overview

Local AI Platform is a self-hosted AI infrastructure with multi-agent workflow orchestration, custom agent personas, and a Cortex-branded mission control dashboard. Built for privacy-first local LLM inference using Ollama, with an OpenAI-compatible API layer.

### Key Capabilities

- **100% Local**: All inference runs on your hardware — no data leaves your machine
- **Multi-Agent Workflows**: DAG-based execution engine with parallel batch scheduling, quality gates, Jinja2 prompts
- **Custom Agents**: YAML-backed agent personas (like Claude Gems) with pinned context, tools, and conversation starters
- **Cortex Dashboard**: 7-tab mission control UI with model management, knowledge graph, workflow runner, and agent builder
- **OpenAI-Compatible**: Drop-in replacement API — any OpenAI client works out of the box
- **macOS Desktop App**: Native WKWebView window via pywebview (optional)
- **276 Tests**: Comprehensive test coverage across all components

### Target Hardware Profile

**Optimized for**:
- CPU: AMD Ryzen 9 7945HX (32 threads)
- RAM: 60GB
- Storage: 200GB+ available
- OS: Linux (Ubuntu 22.04+ / Debian 11+)

**Minimum Requirements**:
- CPU: 8+ cores (x86_64)
- RAM: 16GB
- Storage: 100GB
- OS: Linux with systemd

---

## Current Status

**Version**: 1.0.0-beta
**Last Updated**: 2026-04-08
**Tests**: 276 passing

### Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| Core Infrastructure | ✅ Complete | Ollama + systemd + FastAPI server |
| Cortex Dashboard | ✅ Complete | 7-tab mission control UI (Cortex XSIAM branding) |
| OpenAI-Compatible API | ✅ Complete | Chat/completions with SSE streaming |
| Model Management | ✅ Complete | 20 models in catalog, pull/remove/unload via UI |
| CLI Chat Interface | ✅ Complete | Rich formatting, conversation history |
| Multi-Agent Workflows | ✅ Complete | DAG execution, parallel batches, quality gates, Jinja2 |
| Custom Agents (Gems) | ✅ Complete | YAML-backed personas, context resolution, 7 API endpoints |
| Knowledge Graph | ✅ Complete | D3.js force graph with 5 node types, search |
| macOS Desktop App | ✅ Complete | pywebview + py2app native wrapper |
| Authentication | ✅ Complete | API key middleware (optional, env-configured) |
| Rate Limiting | ✅ Complete | Per-IP rate limiting middleware |
| Test Suite | ✅ Complete | 276 tests across 18 files |
| HuggingFace Discovery | ✅ Complete | Browse trusted authors, filter by capability |
| Session Exports | ✅ Complete | Markdown export with knowledge graph integration |
| Docker Deployment | ❌ Planned | Phase 5 feature |
| RAG System | ⚠️ Deps Installed | ChromaDB/LangChain installed, not integrated |
| Fine-tuning Pipeline | ❌ Planned | Phase 3 feature |

---

## Features

### Core Features

#### Cortex Dashboard (7 Tabs)
- **Dashboard** — System status, loaded models, CPU/memory gauges, inline chat interface with model selector and web search
- **Models** — 20-model catalog with search, filter (All/Installed/Available/Uncensored/Coding/Reasoning), sort, pull with size estimate, remove, unload
- **Memory** — Real-time memory usage, disk space, running model inventory
- **Discover** — HuggingFace model browser from trusted authors, filterable by capability
- **Research** — D3.js knowledge graph (sessions, topics, sources, agents, workflow runs) + deep research orchestration
- **Workflows** — DAG workflow runner with pipeline visualization, execution timeline, expandable step cards with artifacts
- **Agents** — Custom agent gallery, visual builder form, agent-specific chat mode

#### Multi-Agent Workflow Engine
- **DAG execution** with parallel batch scheduling (Kahn's algorithm)
- **Jinja2 prompt templates** with 11 built-in filters (`{{step.output|json}}`)
- **6 output parsers**: JSON, JSON array, markdown sections, regex, CSV, key-value
- **15 quality gate operators**: not_empty, contains, matches, has_key, gt, lt, etc.
- **Conditional branching** — skip steps based on context values
- **Loop iteration** — iterate over collections with aggregation
- **Checkpoint/resume** — save mid-workflow, resume from failure
- **Event bus** — pub/sub for real-time execution monitoring

#### Custom Agents (Gems)
- YAML-backed agent personas — local alternative to Claude Gems / OpenAI GPTs
- 5 context source types: file, URL, graph query, workflow output, inline text
- Tool integration: web search, workflow triggers
- Conversation starters for quick onboarding
- UI builder form or hand-authored YAML — both work identically

#### macOS Desktop App
- Native WKWebView window via pywebview (uses system WebKit, ~15MB)
- Auto-starts Ollama and FastAPI on random port
- Build to `.app` bundle with py2app: `./desktop/build.sh`

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | System health with CPU/memory stats |
| `GET` | `/v1/models` | List available models (OpenAI format) |
| `POST` | `/v1/chat/completions` | Chat completion with streaming |
| `POST` | `/v1/completions` | Text completion with streaming |
| `GET` | `/api/agents` | List custom agents |
| `POST` | `/api/agents/{id}/chat` | Chat with agent (context-injected) |
| `GET` | `/api/workflows` | List workflow definitions |
| `POST` | `/api/workflows/run` | Execute a workflow |
| `POST` | `/api/workflows/compile` | Compile and analyze execution plan |
| `GET` | `/api/graph` | Knowledge graph data (D3.js) |
| `GET` | `/api/inventory/catalog` | Full model catalog with hardware profiles |
| `POST` | `/api/inventory/pull` | Download a model (streaming progress) |
| `DELETE` | `/api/inventory/remove` | Remove an installed model |

---

## System Requirements

### Hardware Requirements

| Component | Minimum | Recommended | Optimal (Current Target) |
|-----------|---------|-------------|--------------------------|
| **CPU** | 8 cores (x86_64) | 16 cores | AMD Ryzen 9 7945HX (32 threads) |
| **RAM** | 16GB | 32GB | 60GB |
| **Storage** | 100GB available | 200GB SSD | 500GB NVMe SSD |
| **Network** | 10 Mbps | 100 Mbps | 1 Gbps (for model downloads) |

### Software Requirements

| Software | Version | Purpose |
|----------|---------|---------|
| **OS** | Linux (Ubuntu 22.04+ / Debian 11+) | Primary platform |
| **Python** | 3.10+ | Application runtime |
| **systemd** | Any | Service management |
| **curl** | Any | Ollama installation |
| **git** | Any | Repository management |

### Model Size vs RAM Requirements

| Model Size | Quantization | RAM Required | Expected Speed |
|------------|--------------|--------------|----------------|
| 7B | Q4_K_M | 6-8GB | 40-50 tok/s |
| 13B | Q4_K_M | 10-12GB | 25-30 tok/s |
| 34B | Q4_K_M | 22-26GB | 10-15 tok/s |
| 70B | Q4_K_M | 42-48GB | 3-5 tok/s |
| 70B | Q3_K_M | 32-38GB | 4-6 tok/s |

**Note**: Speeds measured on AMD Ryzen 9 7945HX. Your performance may vary.

---

## Installation

### Prerequisites

1. **Linux System** with systemd (Ubuntu 22.04+, Debian 11+, or equivalent)
2. **Root/sudo access** for system package installation
3. **Internet connection** for initial setup (optional for inference later)
4. **Available storage** of at least 100GB

### Quick Start

See the [Quick Start section at the top of this document](#quick-start-local-development) for the fastest path to running locally.

#### Recommended Models

| Model | Size | Best For |
|-------|------|----------|
| `deepseek-r1:32b` | 20GB | Reasoning, analysis, chain-of-thought |
| `qwen2.5:32b` | 20GB | General purpose, multilingual |
| `dolphin3:latest` | 4GB | Fast uncensored responses |
| `huihui_ai/qwen2.5-coder-abliterate:7b` | 4GB | Uncensored coding |

```bash
# Pull models via Ollama
ollama pull deepseek-r1:32b
ollama pull dolphin3:latest

# Or use the dashboard Models tab to browse, pull, and manage
```

### Manual Installation

<details>
<summary>Click to expand manual installation steps</summary>

#### Step 1: System Dependencies

```bash
# Update package lists
sudo apt update

# Install build tools and dependencies
sudo apt install -y \
    build-essential \
    cmake \
    git \
    curl \
    wget \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    pkg-config \
    libopenblas-dev \
    liblapack-dev \
    libomp-dev \
    jq \
    tmux \
    htop
```

#### Step 2: Python Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install Python dependencies
pip install -r setup/requirements.txt
```

#### Step 3: Install Ollama

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Verify installation
ollama --version
```

#### Step 4: Configure Ollama Service

```bash
# Create systemd user service directory
mkdir -p ~/.config/systemd/user

# Create service file
cat > ~/.config/systemd/user/ollama.service << 'EOF'
[Unit]
Description=Ollama Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/ollama serve
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_NUM_PARALLEL=2"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

# Reload systemd and enable service
systemctl --user daemon-reload
systemctl --user enable ollama.service
systemctl --user start ollama.service
```

#### Step 5: Create Data Directories

```bash
# Create necessary directories
mkdir -p data/{models,vectors,cache,logs}
mkdir -p finetuning/{datasets,configs,outputs}
```

#### Step 6: Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit configuration (adjust values as needed)
nano .env
```

</details>

### Post-Installation

#### Verify Installation

```bash
# 1. Check Ollama service
systemctl --user status ollama.service
# Should show "active (running)"

# 2. Test Ollama API
curl http://localhost:11434/api/tags
# Should return JSON with models list

# 3. Check Python environment
source venv/bin/activate
python --version  # Should be 3.10+
pip list | grep fastapi  # Should show fastapi installation

# 4. Test API server
python api/main.py &
sleep 2
curl http://localhost:8000/health
# Should return: {"status":"healthy","version":"1.0.0",...}
```

#### Download Recommended Models

```bash
# Activate virtual environment
source venv/bin/activate

# See all available models
python models/download.py --list

# Download by category
python models/download.py --filter uncensored  # Uncensored only
python models/download.py --filter coding      # Coding models

# Recommended starter set (adjust based on available RAM)
python models/download.py dolphin-mistral    # 4GB - Fast uncensored
python models/download.py openhermes         # 4GB - Excellent instruction following
python models/download.py deepseek-coder-33b # 20GB - Best coding (if RAM allows)
```

---

## Usage

### CLI Chat Interface

The CLI provides an interactive terminal-based chat experience with rich formatting.

```bash
# Activate virtual environment
source venv/bin/activate

# Start chat with default model
python cli/chat.py

# Specify model
python cli/chat.py --model dolphin-mixtral

# Use custom Ollama host
python cli/chat.py --model mistral --host http://192.168.1.100:11434

# Get help
python cli/chat.py --help
```

#### CLI Commands

While in a chat session:

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/clear` | Clear conversation history |
| `/models` | List available models |
| `/exit` or `/quit` | Exit the chat session |
| `Ctrl+C` | Interrupt current response (continue session) |

#### CLI Example Session

```
┌────────────────────────────────────────────────────────────┐
│ Local AI Platform - Chat Interface                        │
│ Model: dolphin-mixtral                                     │
│ Type 'exit' or 'quit' to end the session                  │
│ Type '/help' for commands                                 │
└────────────────────────────────────────────────────────────┘

❯ Explain quantum computing in simple terms

AI:
Quantum computing is a type of computing that uses quantum mechanics to process
information. Unlike classical computers that use bits (0 or 1), quantum computers
use quantum bits or "qubits" that can exist in multiple states simultaneously...

❯ /clear
✓ Conversation history cleared

❯ /models
Available Models:
  • dolphin-mixtral:latest
  • mistral:latest
  • openhermes:latest

❯ exit
👋 Goodbye!
```

### API Server

The API server provides OpenAI-compatible endpoints for integration with existing tools and applications.

#### Starting the Server

```bash
# Activate virtual environment
source venv/bin/activate

# Start server (development mode with auto-reload)
python api/main.py

# Server starts at http://localhost:8000
# API documentation available at http://localhost:8000/docs
# Alternative docs at http://localhost:8000/redoc
```

#### Production Deployment

```bash
# Install uvicorn extras
pip install uvicorn[standard]

# Run with production settings
uvicorn api.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --log-level info
```

**⚠️ WARNING**: Do not deploy to production without implementing:
- API authentication (see [Security Considerations](#security-considerations))
- Rate limiting
- Proper logging and monitoring
- Firewall rules

#### API Examples

##### Health Check

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "ollama_host": "http://localhost:11434"
}
```

##### List Models

```bash
curl http://localhost:8000/v1/models
```

Response:
```json
{
  "object": "list",
  "data": [
    {
      "id": "dolphin-mixtral:latest",
      "object": "model",
      "created": 0,
      "owned_by": "local"
    }
  ]
}
```

##### Chat Completion

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "dolphin-mixtral",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "What is the capital of France?"}
    ],
    "temperature": 0.7,
    "max_tokens": 2048
  }'
```

Response:
```json
{
  "id": "chatcmpl-local",
  "object": "chat.completion",
  "created": 0,
  "model": "dolphin-mixtral",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The capital of France is Paris."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 15,
    "completion_tokens": 8,
    "total_tokens": 23
  }
}
```

**Note**: Token counts are now accurate, returned from Ollama's evaluation metrics.

##### Streaming Chat Completion

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral:7b",
    "messages": [
      {"role": "user", "content": "Count from 1 to 5"}
    ],
    "stream": true
  }'
```

Response (Server-Sent Events):
```
data: {"id":"chatcmpl-local","object":"chat.completion.chunk","created":0,"model":"mistral:7b","choices":[{"index":0,"delta":{"content":"1"},"finish_reason":null}]}

data: {"id":"chatcmpl-local","object":"chat.completion.chunk","created":0,"model":"mistral:7b","choices":[{"index":0,"delta":{"content":", "},"finish_reason":null}]}

data: {"id":"chatcmpl-local","object":"chat.completion.chunk","created":0,"model":"mistral:7b","choices":[{"index":0,"delta":{"content":"2"},"finish_reason":null}]}

...

data: {"id":"chatcmpl-local","object":"chat.completion.chunk","created":0,"model":"mistral:7b","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

##### Text Completion

```bash
curl http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral",
    "prompt": "Once upon a time in a",
    "max_tokens": 100,
    "temperature": 0.8
  }'
```

#### Python SDK Example

```python
import requests

API_BASE = "http://localhost:8000/v1"

def chat(messages, model="dolphin-mixtral"):
    response = requests.post(
        f"{API_BASE}/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.7
        }
    )
    return response.json()["choices"][0]["message"]["content"]

# Usage
messages = [
    {"role": "user", "content": "Explain recursion simply"}
]
response = chat(messages)
print(response)
```

#### Using with OpenAI Python SDK

```python
from openai import OpenAI

# Point to local API
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"  # API key not validated currently
)

# Use exactly like OpenAI API
response = client.chat.completions.create(
    model="dolphin-mixtral",
    messages=[
        {"role": "user", "content": "Hello, how are you?"}
    ]
)

print(response.choices[0].message.content)
```

### Model Management

#### Listing Available Models

```bash
# Show all models in registry
python models/download.py --list

# Filter by tag
python models/download.py --list --filter uncensored
python models/download.py --list --filter coding
python models/download.py --list --filter fast

# Show detailed information
python models/download.py --info dolphin-mixtral
```

#### Downloading Models

```bash
# Download via Ollama (default, fastest)
python models/download.py dolphin-mistral

# Download from Hugging Face
python models/download.py dolphin-mistral --source huggingface

# Download GGUF file directly
python models/download.py dolphin-mistral --source gguf

# Alternative: Use Ollama directly
ollama pull mistral
ollama pull llama2-uncensored
```

#### Model Information

```bash
# Get model details
python models/download.py --info yi-34b
```

Output:
```
┌─────────────────────────────────────────────────────────┐
│ Model Info: yi-34b                                      │
├─────────────────────────────────────────────────────────┤
│ Yi-34B-200K                                             │
│                                                         │
│ Size: 20GB                                              │
│ Speed: 10-12 tok/s                                      │
│ Description: Massive 200K context, excellent for long  │
│              documents                                  │
│                                                         │
│ Tags: uncensored, long-context, multilingual           │
│                                                         │
│ Sources:                                                │
│   • Ollama: yi:34b-chat                                │
│   • Hugging Face: 01-ai/Yi-34B-200K                    │
│   • GGUF: TheBloke/Yi-34B-200K-GGUF                    │
└─────────────────────────────────────────────────────────┘
```

#### Managing Models with Ollama

```bash
# List installed models
ollama list

# Show model details
ollama show mistral

# Run model directly (for testing)
ollama run mistral "Explain neural networks"

# Remove a model
ollama rm mistral

# Copy/rename a model
ollama cp mistral my-mistral
```

### Testing & Status

#### Quick System Status

```bash
# Check status of all components
./scripts/status.sh
```

Output:
```
📊 Local AI Platform Status
═══════════════════════════════════════
Ollama Service:
  Status: ✓ Running
  URL: http://localhost:11434
  Models: 5 installed

  1. mistral:7b               4.4 GB  (Q4_K_M)
  2. llama3.1:8b              4.9 GB  (Q4_K_M)
  3. codellama:13b            7.4 GB  (Q4_0)
  4. deepseek-coder:6.7b      3.8 GB  (Q4_0)
  5. deepseek-coder:33b      18.0 GB  (Q4_0)

───────────────────────────────────────
API Server:
  Status: ✓ Running
  URL: http://localhost:8000
  Docs: http://localhost:8000/docs
  API Status: healthy
  Ollama Connection: healthy

───────────────────────────────────────
Environment:
  .env file: ✓ Present
  Virtual env: ✓ Present
═══════════════════════════════════════
```

#### Running Tests

```bash
# Run all tests (unit tests + API health checks)
./scripts/test.sh
```

The test script will:
1. Check API health endpoint
2. Verify Ollama connection
3. Run pytest unit tests
4. Test API endpoints with actual requests
5. Display results and diagnostics

Example output:
```
🧪 Testing Local AI Platform...

1. Checking API health...
   ✓ API is responding
   Status: healthy

2. Checking Ollama connection...
   ✓ Ollama is responding
   Models available: 5

3. Running unit tests...
tests/test_api.py::TestHealthEndpoints::test_health_check PASSED
tests/test_api.py::TestHealthEndpoints::test_root_endpoint PASSED
tests/test_api.py::TestModelsEndpoint::test_list_models_success PASSED
tests/test_api.py::TestChatCompletions::test_chat_completion_success PASSED
...

4. Testing API endpoints...
   Testing /v1/models...
   ✓ Models endpoint working (5 models)

   Testing /v1/chat/completions...
   ✓ Chat completions endpoint working
   Response preview: test successful

✅ Testing complete!
```

#### Manual Testing

```bash
# Test health endpoint
curl http://localhost:8000/health

# Test models listing
curl http://localhost:8000/v1/models

# Test chat completion
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral:7b",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'

# Test streaming
curl -N http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral:7b",
    "messages": [{"role": "user", "content": "Count to 3"}],
    "stream": true
  }'
```

---

## Configuration

### Environment Variables

Configuration is managed via `.env` file in the project root. Copy `.env.example` to `.env` and customize.

#### Currently Active Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `API_HOST` | `0.0.0.0` | FastAPI server host |
| `API_PORT` | `8000` | FastAPI server port |
| `API_KEY` | _(empty)_ | API authentication key (not enforced) |
| `CORS_ORIGINS` | `["*"]` | CORS allowed origins |

#### Planned Variables (Not Yet Implemented)

| Variable | Purpose | Phase |
|----------|---------|-------|
| `OLLAMA_NUM_THREADS` | CPU threads for inference | 2 |
| `OLLAMA_NUM_CTX` | Context window size | 2 |
| `DEFAULT_MODEL` | Default model for API | 2 |
| `MODELS_DIR` | Model storage location | 2 |
| `ENABLE_API_AUTH` | Enable authentication | 2 |
| `MAX_CONCURRENT_REQUESTS` | Request throttling | 2 |
| `LOG_LEVEL` | Logging verbosity | 2 |
| `LOG_DIR` | Log file location | 2 |
| `VECTOR_DB` | Vector DB type (chroma/qdrant) | 4 |
| `FINETUNING_*` | Fine-tuning parameters | 3 |

### Example .env File

```bash
# Ollama Configuration
OLLAMA_HOST=http://localhost:11434
OLLAMA_NUM_THREADS=24
OLLAMA_NUM_CTX=4096

# API Server
API_HOST=0.0.0.0
API_PORT=8000
API_KEY=your-secret-key-here
ENABLE_API_AUTH=true

# CORS
CORS_ORIGINS=["http://localhost:3000","https://yourdomain.com"]

# Logging
LOG_LEVEL=INFO
LOG_DIR=./data/logs

# Performance
MAX_CONCURRENT_REQUESTS=10
REQUEST_TIMEOUT=300

# Models
DEFAULT_MODEL=dolphin-mixtral
MODELS_DIR=./data/models
```

**Note**: Only `OLLAMA_HOST`, `API_HOST`, `API_PORT`, `API_KEY`, and `CORS_ORIGINS` are currently used by the application.

---

## Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     User Interfaces                         │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │  CLI Chat  │  │  Web UI    │  │  API       │            │
│  │  (Rich)    │  │ (Planned)  │  │  Clients   │            │
│  └──────┬─────┘  └──────┬─────┘  └──────┬─────┘            │
└─────────┼────────────────┼────────────────┼─────────────────┘
          │                │                │
          └────────────────┴────────────────┘
                           │
┌──────────────────────────┴──────────────────────────────────┐
│                    FastAPI Application                       │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  api/main.py - OpenAI-Compatible Endpoints            │ │
│  │  • GET  /health                                        │ │
│  │  • GET  /v1/models                                     │ │
│  │  • POST /v1/chat/completions                          │ │
│  │  • POST /v1/completions                               │ │
│  └────────────────────────────────────────────────────────┘ │
│                           │                                  │
│  ┌────────────────────────┴──────────────────────────────┐  │
│  │  Services Layer (Planned - Phase 2)                   │  │
│  │  • ollama_service.py - Ollama integration            │  │
│  │  • vllm_service.py - vLLM integration                │  │
│  │  • rag_service.py - RAG operations                   │  │
│  └────────────────────────────────────────────────────────┘  │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────┴──────────────────────────────────┐
│              Inference Engines (Backends)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   Ollama     │  │    vLLM      │  │  llama.cpp   │       │
│  │  (Current)   │  │  (Planned)   │  │  (Planned)   │       │
│  │  Port 11434  │  │              │  │              │       │
│  └──────┬───────┘  └──────────────┘  └──────────────┘       │
└─────────┼────────────────────────────────────────────────────┘
          │
┌─────────┴────────────────────────────────────────────────────┐
│                   Storage & Data Layer                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │   Models    │  │   Vectors   │  │    Cache    │          │
│  │   (GGUF)    │  │  (Planned)  │  │  (Planned)  │          │
│  │ data/models │  │data/vectors │  │ data/cache  │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└──────────────────────────────────────────────────────────────┘
```

### Component Interaction Flow

1. **User Input** → CLI/API Client sends request
2. **API Layer** → FastAPI receives request, validates with Pydantic
3. **Format Conversion** → Converts OpenAI format to Ollama format
4. **Inference** → Calls Ollama API at localhost:11434
5. **Response Processing** → Converts Ollama response back to OpenAI format
6. **Return** → Sends formatted response to client

### Directory Structure

```
local-ai-platform/
├── api/                      # FastAPI application
│   ├── main.py              # ✅ Main app with all endpoints
│   ├── routers/             # ❌ Planned: Endpoint modules
│   ├── services/            # ❌ Planned: Business logic
│   └── utils/               # ❌ Planned: Helper functions
├── cli/                     # Command-line interfaces
│   ├── chat.py              # ✅ Interactive chat
│   ├── query.py             # ❌ Planned: Single queries
│   └── benchmark.py         # ❌ Planned: Performance tests
├── models/                  # Model management
│   ├── download.py          # ✅ Model downloader with registry
│   ├── convert.py           # ❌ Planned: Format conversion
│   └── quantize.py          # ❌ Planned: Model quantization
├── finetuning/              # Fine-tuning pipeline
│   ├── train.py             # ❌ Planned: Training script
│   ├── datasets/            # Training data
│   ├── configs/             # Training configurations
│   └── outputs/             # Trained models
├── webui/                   # Web interface
│   ├── launch.sh            # ❌ Planned: WebUI launcher
│   └── configs/             # UI configuration
├── scripts/                 # Utility scripts
│   ├── start.sh             # ❌ Planned: Start all services
│   ├── stop.sh              # ❌ Planned: Stop all services
│   └── status.sh            # ❌ Planned: Check status
├── setup/                   # Installation
│   ├── install.sh           # ✅ Main installer
│   └── requirements.txt     # ✅ Python dependencies
├── config/                  # Configuration files
│   ├── models.yaml          # ❌ Planned: Model configs
│   ├── api.yaml             # ❌ Planned: API configs
│   └── services.yaml        # ❌ Planned: Service configs
├── data/                    # Runtime data (gitignored)
│   ├── models/              # Downloaded models
│   ├── vectors/             # Vector database
│   ├── cache/               # Inference cache
│   └── logs/                # Application logs
├── tests/                   # Test suite
│   └── (empty)              # ❌ No tests yet
├── docs/                    # Documentation
│   ├── QUICK_START.md       # ✅ Quick start guide
│   ├── UNCENSORED_MODELS.md # ✅ Model information
│   └── HUGGINGFACE_SETUP.md # ✅ HF authentication
├── .env.example             # ✅ Environment template
├── .gitignore               # ✅ Git exclusions
├── CLAUDE.md                # ✅ Claude Code instructions
├── PROJECT_PLAN.md          # ✅ Detailed roadmap
└── README.md                # ✅ This file
```

**Legend**: ✅ Implemented | ❌ Planned/Not Implemented

---

## API Reference

### Base URL

```
http://localhost:8000
```

### Authentication

**Current**: No authentication implemented
**Planned**: API key via header `Authorization: Bearer <API_KEY>`

⚠️ **Security Warning**: All endpoints are currently publicly accessible without authentication.

### Endpoints

#### GET /health

Health check endpoint.

**Response**:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "ollama_host": "http://localhost:11434"
}
```

#### GET /v1/models

List available models.

**Response**:
```json
{
  "object": "list",
  "data": [
    {
      "id": "model-name:tag",
      "object": "model",
      "created": 0,
      "owned_by": "local"
    }
  ]
}
```

#### POST /v1/chat/completions

Chat completion with message history.

**Request Body**:
```json
{
  "model": "string",
  "messages": [
    {
      "role": "system|user|assistant",
      "content": "string"
    }
  ],
  "temperature": 0.7,    // Optional: 0.0 - 2.0
  "max_tokens": 2048,    // Optional: Max tokens to generate
  "stream": false        // Optional: Not yet implemented
}
```

**Response**:
```json
{
  "id": "chatcmpl-local",
  "object": "chat.completion",
  "created": 0,
  "model": "string",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "string"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 0,      // Currently placeholder
    "completion_tokens": 0,   // Currently placeholder
    "total_tokens": 0         // Currently placeholder
  }
}
```

#### POST /v1/completions

Text completion from a prompt.

**Request Body**:
```json
{
  "model": "string",
  "prompt": "string",
  "temperature": 0.7,    // Optional: 0.0 - 2.0
  "max_tokens": 2048,    // Optional: Max tokens to generate
  "stream": false        // Optional: Not yet implemented
}
```

**Response**:
```json
{
  "id": "cmpl-local",
  "object": "text_completion",
  "created": 0,
  "model": "string",
  "choices": [
    {
      "text": "string",
      "index": 0,
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

### Error Responses

All endpoints return standard HTTP error codes:

| Code | Meaning | Example |
|------|---------|---------|
| 200 | Success | Request completed successfully |
| 400 | Bad Request | Invalid request body |
| 500 | Internal Server Error | Ollama connection failed |

**Error Format**:
```json
{
  "detail": "Error message describing the issue"
}
```

---

## Model Registry

### Available Models

The platform includes 11 pre-configured models across different categories:

#### Tier 1: Uncensored Models

| Model ID | Name | Size | Speed | Description |
|----------|------|------|-------|-------------|
| `dolphin-mixtral` | Dolphin 2.5 Mixtral 8x7B | 26GB | 15-20 tok/s | Best uncensored, excellent reasoning |
| `dolphin-mistral` | Dolphin 2.6 Mistral 7B | 4.1GB | 45-55 tok/s | Fastest uncensored, coding |
| `nous-hermes2-mixtral` | Nous Hermes 2 Mixtral 8x7B | 26GB | 15-20 tok/s | Excellent instruction following |
| `yi-34b` | Yi-34B-200K | 20GB | 10-12 tok/s | 200K context window |
| `wizardlm-uncensored-13b` | WizardLM-13B-Uncensored | 7.4GB | 25-30 tok/s | Creative writing |

#### Tier 2: High Performance

| Model ID | Name | Size | Speed | Description |
|----------|------|------|-------|-------------|
| `openhermes` | OpenHermes 2.5 Mistral 7B | 4.1GB | 45-50 tok/s | Instruction following, coding |
| `neural-chat` | Neural-Chat 7B v3.3 | 4.1GB | 45-50 tok/s | CPU-optimized conversations |

#### Specialized Models

| Model ID | Name | Size | Speed | Description |
|----------|------|------|-------|-------------|
| `mythomax` | MythoMax L2 13B | 7.4GB | 25-30 tok/s | Creative writing, roleplay |
| `deepseek-coder-33b` | DeepSeek Coder 33B | 20GB | 10-12 tok/s | Best coding, 86 languages |
| `codellama-34b` | CodeLlama 34B Instruct | 20GB | 10-12 tok/s | Meta's coding specialist |

#### Large Models

| Model ID | Name | Size | Speed | Description |
|----------|------|------|-------|-------------|
| `airoboros-70b` | Airoboros L2 70B | 40GB (Q4) | 3-5 tok/s | Maximum capability |

### Model Selection Guide

**For beginners** (Start here):
- `dolphin-mistral` - Fast, uncensored, good quality

**For general use**:
- `openhermes` - Best instruction following
- `neural-chat` - CPU-optimized performance

**For coding**:
- `deepseek-coder-33b` - Best coding model (if 20GB+ RAM)
- `codellama-34b` - Meta's official coding model

**For creative writing**:
- `mythomax` - Storytelling and roleplay
- `wizardlm-uncensored-13b` - Creative, uncensored

**For maximum quality** (high RAM required):
- `dolphin-mixtral` - Best reasoning (26GB)
- `yi-34b` - Long context support (20GB)
- `airoboros-70b` - Absolute best (40GB+)

### Adding Custom Models

Models can be added to the registry in `models/download.py`:

```python
MODEL_REGISTRY = {
    "your-model-id": {
        "name": "Display Name",
        "ollama": "ollama-model-name",
        "huggingface": "org/repo-name",
        "gguf": "TheBloke/repo-GGUF",
        "size": "XGB",
        "speed": "X-Y tok/s",
        "description": "Brief description",
        "tags": ["tag1", "tag2", "tag3"]
    }
}
```

Or use Ollama directly:
```bash
ollama pull <any-ollama-model>
```

---

## Performance Benchmarks

### Test System

- **CPU**: AMD Ryzen 9 7945HX (32 threads @ 5.4GHz boost)
- **RAM**: 60GB DDR5
- **Storage**: NVMe SSD
- **OS**: Ubuntu 22.04 LTS
- **Ollama**: v0.1.6
- **Backend**: llama.cpp

### Inference Performance

| Model | Quantization | Load Time | First Token | Tokens/sec | RAM Usage |
|-------|--------------|-----------|-------------|------------|-----------|
| Mistral 7B | Q4_K_M | 2-3s | 200-300ms | 45-50 | 6GB |
| Dolphin Mistral 7B | Q4_K_M | 2-3s | 200-300ms | 45-55 | 6GB |
| OpenHermes 7B | Q4_K_M | 2-3s | 200-300ms | 45-50 | 6GB |
| WizardLM 13B | Q4_K_M | 3-4s | 300-400ms | 25-30 | 11GB |
| MythoMax 13B | Q4_K_M | 3-4s | 300-400ms | 25-30 | 11GB |
| Dolphin Mixtral 8x7B | Q4_K_M | 5-7s | 400-600ms | 15-20 | 24GB |
| DeepSeek Coder 33B | Q4_K_M | 8-10s | 600-800ms | 10-12 | 22GB |
| Yi-34B | Q4_K_M | 8-10s | 600-800ms | 10-12 | 22GB |
| Airoboros 70B | Q4_K_M | 12-15s | 1-1.5s | 3-5 | 42GB |
| Airoboros 70B | Q3_K_M | 10-12s | 800ms-1s | 4-6 | 34GB |

### API Latency

| Endpoint | Median | P95 | P99 |
|----------|--------|-----|-----|
| `/health` | 2ms | 5ms | 10ms |
| `/v1/models` | 50ms | 100ms | 150ms |
| `/v1/chat/completions` (7B) | 3-5s | 8s | 12s |
| `/v1/chat/completions` (34B) | 10-15s | 25s | 35s |

**Note**: Completion times vary significantly based on prompt length and response length.

### Quantization Impact

| Quantization | Size Reduction | Quality | Speed | Recommended For |
|--------------|----------------|---------|-------|-----------------|
| Q2_K | 75% | Poor | Fastest | Not recommended |
| Q3_K_M | 65% | Acceptable | Fast | 70B+ models only |
| Q4_K_M | 50% | Good | Balanced | **Default - all models** |
| Q5_K_M | 40% | Excellent | Slower | Quality-critical uses |
| Q6_K | 30% | Near-perfect | Slowest | Maximum quality |
| Q8_0 | 20% | Perfect | Very slow | Benchmarking only |

**Recommendation**: Use Q4_K_M for best balance. Use Q3_K_M for 70B+ models to fit in RAM.

---

## Security Considerations

### Current Security Status

⚠️ **WARNING**: This platform is NOT production-ready from a security perspective.

#### Critical Security Gaps

1. **No Authentication** ❌
   - API endpoints are publicly accessible
   - No API key validation
   - Anyone can access your models

2. **No Rate Limiting** ❌
   - Vulnerable to abuse and DoS attacks
   - No request throttling
   - Resource exhaustion possible

3. **Minimal Logging** ❌
   - No request logging
   - No audit trail
   - Limited debugging capabilities

4. **No Input Sanitization** ❌
   - Basic type validation only
   - No prompt injection protection
   - No content filtering

### Security Recommendations

#### Before Production Deployment

**MUST Implement**:
1. API key authentication
2. Rate limiting (per-IP and per-key)
3. Structured logging with audit trail
4. Input sanitization and validation
5. HTTPS/TLS encryption
6. Firewall rules restricting access

**Example Firewall Configuration**:
```bash
# Allow only from specific IP range
sudo ufw allow from 192.168.1.0/24 to any port 8000

# Or allow localhost only
sudo ufw deny 8000
```

**HTTPS with Nginx Reverse Proxy**:
```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

#### Network Security

**Recommended Deployment Architecture**:
1. **Local Network Only**: Bind API to `127.0.0.1` (not `0.0.0.0`)
2. **VPN Access**: Require VPN for remote access
3. **Reverse Proxy**: Use Nginx/Caddy with authentication
4. **Firewall**: Block external access to ports 8000, 11434

#### Data Privacy

**Current State**:
- ✅ All inference is 100% local
- ✅ No telemetry or external API calls during inference
- ✅ No data leaves your system
- ❌ No conversation encryption at rest
- ❌ No audit logging

**For Sensitive Data**:
- Use disk encryption (LUKS)
- Run on isolated network
- Implement conversation logging with encryption
- Regular security audits

---

## Troubleshooting

### Common Issues

#### Ollama Service Not Running

**Symptoms**:
- API returns "connection refused"
- CLI shows "Error communicating with Ollama"

**Solutions**:
```bash
# Check service status
systemctl --user status ollama.service

# Start service
systemctl --user start ollama.service

# View logs
journalctl --user -u ollama.service -f

# Test Ollama directly
curl http://localhost:11434/api/tags

# If systemd not available, run manually
ollama serve
```

#### Model Download Fails

**Symptoms**:
- Download interrupted
- Network timeout
- Disk space errors

**Solutions**:
```bash
# Check disk space
df -h

# Resume download (Ollama downloads are resumable)
python models/download.py <model-id>

# Try alternative source
python models/download.py <model-id> --source huggingface

# Check network connectivity
curl -I https://ollama.ai
```

#### Out of Memory Errors

**Symptoms**:
- System freeze
- OOM killer terminates process
- Slow performance

**Solutions**:
```bash
# Check RAM usage
free -h
htop

# Use smaller model
python models/download.py dolphin-mistral  # 4GB instead of larger models

# Use more aggressive quantization
# Download Q3 instead of Q4 for large models

# Reduce parallel models (edit ~/.config/systemd/user/ollama.service)
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
systemctl --user daemon-reload
systemctl --user restart ollama.service
```

#### Slow Inference

**Symptoms**:
- Tokens/sec much lower than expected
- High CPU usage
- System lag

**Solutions**:
```bash
# Check CPU usage
htop

# Verify thread count (should be close to CPU threads)
# Edit ~/.config/systemd/user/ollama.service
Environment="OLLAMA_NUM_THREADS=24"  # Adjust for your CPU

# Ensure no other heavy processes
# Close browsers, IDEs, etc.

# Try smaller context window
# In .env file:
OLLAMA_NUM_CTX=2048  # Default is 4096
```

#### API Returns 500 Errors

**Symptoms**:
- All API requests fail
- "Internal Server Error"

**Solutions**:
```bash
# Check API logs
# API server shows detailed errors in terminal

# Verify Ollama is running
curl http://localhost:11434/api/tags

# Check .env file exists
ls -la .env

# Verify model is downloaded
ollama list

# Test with curl
curl http://localhost:8000/health
```

#### Python Module Import Errors

**Symptoms**:
- "ModuleNotFoundError"
- "No module named 'fastapi'"

**Solutions**:
```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Verify activation (should show venv path)
which python

# Reinstall dependencies
pip install -r setup/requirements.txt

# Check pip list
pip list | grep fastapi
```

### Getting Help

1. **Check Logs**:
   ```bash
   # Ollama service logs
   journalctl --user -u ollama.service -n 100

   # API server (in terminal where you ran python api/main.py)
   ```

2. **Verify System State**:
   ```bash
   # Ollama status
   systemctl --user status ollama.service
   curl http://localhost:11434/api/tags

   # Disk space
   df -h

   # Memory
   free -h

   # Models
   ollama list
   ```

3. **Test Components Individually**:
   ```bash
   # Test Ollama directly
   ollama run mistral "Hello"

   # Test API health
   curl http://localhost:8000/health

   # Test CLI
   python cli/chat.py --model mistral
   ```

4. **Review Documentation**:
   - [PROJECT_PLAN.md](PROJECT_PLAN.md) - Architecture details
   - [CLAUDE.md](CLAUDE.md) - Development guide
   - Ollama docs: https://github.com/ollama/ollama/tree/main/docs

---

## Development

### Development Setup

```bash
# Clone repository
git clone https://github.com/yourusername/local-ai-platform.git
cd local-ai-platform

# Install development dependencies
source venv/bin/activate
pip install -r setup/requirements.txt

# Install development tools (optional)
pip install ipython jupyter black flake8 mypy
```

### Code Style

```bash
# Format code with Black
black api/ cli/ models/ finetuning/

# Lint with flake8
flake8 api/ cli/ models/

# Type checking with mypy
mypy api/ cli/
```

### Project Guidelines

See [CLAUDE.md](CLAUDE.md) for comprehensive development guidelines including:
- Code architecture patterns
- Adding new features
- API endpoint conventions
- CLI tool patterns
- Common development tasks

### Testing

**Current Status**: No tests implemented

**Planned**:
```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_api.py -v

# Run with coverage
pytest --cov=api --cov=cli tests/
```

### Contributing

This is a personal project, but contributions are welcome:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Format code with Black
5. Submit a pull request

**Priority Areas for Contribution**:
- Authentication implementation
- Rate limiting
- Streaming responses
- Test suite
- Documentation improvements

---

## Roadmap

### Phase 1: Foundation (60% Complete) ✅

**Completed**:
- ✅ Ollama installation and service setup
- ✅ Model download system with 11 models
- ✅ CLI chat interface with rich formatting
- ✅ FastAPI server with OpenAI endpoints
- ✅ Basic API documentation

**Remaining**:
- ⏳ Router/service layer separation
- ⏳ Comprehensive logging
- ⏳ Test suite initialization
- ⏳ Missing documentation files

**Target**: End of Week 1

### Phase 2: Enhanced Serving (0% Complete)

**Features**:
- Streaming response support (SSE)
- vLLM integration for production serving
- llama.cpp direct integration
- API authentication and authorization
- Rate limiting and throttling
- Proper token counting
- Open WebUI configuration
- Monitoring and metrics

**Target**: End of Week 2

### Phase 3: Fine-tuning & Customization (0% Complete)

**Features**:
- LoRA/QLoRA training pipeline
- Axolotl and Unsloth integration
- Dataset preparation tools
- Adapter management
- Training monitoring
- Model merging utilities

**Target**: End of Week 3

### Phase 4: RAG & Advanced Features (0% Complete)

**Features**:
- ChromaDB vector database
- Embedding generation
- Document processing and ingestion
- Semantic search
- LangChain integration
- Tool/function calling
- Prometheus metrics
- Performance monitoring dashboard

**Target**: End of Week 4

### Phase 5: Production & Optimization (0% Complete)

**Features**:
- Docker containerization
- Docker Compose orchestration
- Prompt caching
- KV cache optimization
- Load balancing
- Comprehensive documentation
- Automated testing (CI/CD)
- Deployment guides

**Target**: Week 5+

---

## Known Limitations

### Current Implementation Gaps

#### Security
- ❌ No API authentication (API_KEY defined but not enforced)
- ❌ No rate limiting
- ❌ Minimal logging (only uvicorn defaults)
- ❌ No audit trail
- ❌ CORS set to allow all origins

#### API Features
- ❌ Streaming responses (stream parameter ignored)
- ❌ Token counting (returns placeholder 0 values)
- ❌ No embeddings endpoint
- ❌ No fine-tuning endpoints
- ❌ Static IDs in responses

#### Architecture
- ❌ No router/service separation (all logic in main.py)
- ❌ Inline imports (requests imported 3 times)
- ❌ No error handling middleware
- ❌ No request/response logging

#### Functionality
- ❌ Single inference engine (only Ollama)
- ❌ No RAG capabilities
- ❌ No fine-tuning pipeline
- ❌ No model conversion tools
- ❌ No Web UI integration
- ❌ CLI conversation history not persisted

#### Operations
- ❌ No automated tests
- ❌ No Docker deployment
- ❌ No monitoring/metrics
- ❌ No caching
- ❌ No backup/restore utilities

#### Documentation
- ❌ Missing: INSTALLATION.md, USAGE.md, MODEL_GUIDE.md
- ❌ Missing: FINE_TUNING.md, API_REFERENCE.md, TROUBLESHOOTING.md
- ❌ Missing: LICENSE file
- ❌ No Jupyter notebook examples

### Environment Variable Gaps

**Defined but Unused** (17 of 22 variables):
- `OLLAMA_NUM_THREADS`, `OLLAMA_NUM_CTX`
- `DEFAULT_MODEL`, `MODELS_DIR`, `MODEL_CACHE_DIR`
- `ENABLE_API_AUTH`, `MAX_CONCURRENT_REQUESTS`, `REQUEST_TIMEOUT`
- `LOG_LEVEL`, `LOG_DIR`
- `VECTOR_DB`, `VECTOR_DB_PATH`
- `FINETUNING_*` variables
- `WEBUI_HOST`, `WEBUI_PORT`

### Performance Limitations

- No parallel request handling optimization
- No request queuing
- No model preloading/warming
- No intelligent model switching
- No response caching

---

## License

MIT License

Copyright (c) 2025 [Your Name]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## Acknowledgments

This project builds on the excellent work of:

- **[Ollama](https://ollama.ai)** - Simple, powerful local LLM serving
- **[llama.cpp](https://github.com/ggerganov/llama.cpp)** - Efficient LLM inference in C++
- **[FastAPI](https://fastapi.tiangolo.com/)** - Modern Python web framework
- **[Open WebUI](https://github.com/open-webui/open-webui)** - Beautiful ChatGPT-like interface
- **[TheBloke](https://huggingface.co/TheBloke)** - Quantized GGUF models
- **[Cognitive Computations](https://huggingface.co/cognitivecomputations)** - Dolphin uncensored models
- **[Nous Research](https://huggingface.co/NousResearch)** - Hermes and other models
- **[Axolotl](https://github.com/OpenAccess-AI-Collective/axolotl)** - Fine-tuning framework
- **[LangChain](https://www.langchain.com/)** - LLM application framework
- **[ChromaDB](https://www.trychroma.com/)** - Vector database

### Special Thanks

- The open-source LLM community for making local AI accessible
- Meta AI for Llama 2 and open weights
- Mistral AI for Mistral models
- All model creators and fine-tuners

---

## Support & Community

### Resources

- **Documentation**: [docs/](docs/)
- **Project Plan**: [PROJECT_PLAN.md](PROJECT_PLAN.md)
- **Development Guide**: [CLAUDE.md](CLAUDE.md)
- **Ollama Docs**: https://github.com/ollama/ollama/tree/main/docs
- **OpenAI API Reference**: https://platform.openai.com/docs/api-reference

### Reporting Issues

For bugs, feature requests, or questions:
1. Check existing documentation
2. Search closed issues
3. Create a new issue with:
   - System information
   - Steps to reproduce
   - Expected vs actual behavior
   - Relevant logs

---

**Status**: Alpha - Active Development
**Version**: 0.1.0
**Last Updated**: 2025-01-10
**Maintainer**: [Your Name]

---
