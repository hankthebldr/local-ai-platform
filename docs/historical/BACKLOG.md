# Local AI Platform — Product Backlog & Sprint Plan

> **Target Hardware:** Ryzen 9 7945HX (32 threads), 64-96GB DDR5 (MS-01 / BD790i)
> **Stack:** FastAPI + Ollama + Open WebUI + ChromaDB
> **Timeline:** 6 sprints, 12 weeks (layer-by-layer approach)

---

## Sprint 1 — Solid Foundation (Weeks 1-2)

**Goal:** Production-harden the API. Everything that exists today should be bulletproof.

| ID | Task | Size | Status |
|----|------|------|--------|
| B1 | API key authentication middleware | S | [ ] |
| B2 | Rate limiting middleware | S | [ ] |
| B3 | Structured logging (file + console) | S | [ ] |
| B5 | Custom error types and error responses | S | [ ] |
| B6+B7 | Wire up env vars + CORS from config | S | [ ] |
| B35 | Split requirements into core/dev/ml/rag | S | [ ] |
| B36 | Integration tests with real Ollama | M | [ ] |
| B37 | Streaming response tests | S | [ ] |

**Definition of Done:** API server is secure, observable, and fully tested. Can serve authenticated clients.

---

## Sprint 2 — Chat Experience (Weeks 3-4)

**Goal:** Web UI running, connected to our API. Full chat experience with history.

| ID | Task | Size | Status |
|----|------|------|--------|
| B16 | Open WebUI Docker setup | M | [ ] |
| B17 | Configure Open WebUI for our API endpoint | S | [ ] |
| B31a | Docker Compose: API + Ollama + Open WebUI | M | [ ] |
| B11 | Pull workstation models (dolphin-mixtral, qwen3.5-35b, deepseek-coder) | S | [ ] |
| B10 | Enhanced health check with system metrics | S | [ ] |
| B13 | Single-shot query CLI (cli/query.py) | S | [ ] |
| B14 | Model auto-detection (scan Ollama vs registry) | S | [ ] |

**Definition of Done:** `docker compose up` launches API + Ollama + Open WebUI. Chat works in browser with model switching and history.

---

## Sprint 3 — Knowledge Engine (Weeks 5-6)

**Goal:** RAG pipeline operational. Upload documents, ask questions against them.

| ID | Task | Size | Status |
|----|------|------|--------|
| B8 | /v1/embeddings endpoint | M | [ ] |
| B19 | ChromaDB vector store setup | M | [ ] |
| B21 | Embedding generation service | M | [ ] |
| B20 | Document ingestion pipeline (PDF, MD, TXT) | L | [ ] |
| B22 | RAG-augmented chat endpoint | L | [ ] |

**Definition of Done:** Can upload documents via API, they get chunked/embedded, and chat queries retrieve relevant context. Works through Open WebUI.

---

## Sprint 4 — Knowledge Management (Weeks 7-8)

**Goal:** Polish RAG, add document management, chunking options, benchmarking.

| ID | Task | Size | Status |
|----|------|------|--------|
| B23 | Document management API (upload, list, delete) | M | [ ] |
| B24 | Chunking strategies (fixed, semantic, recursive) | M | [ ] |
| B12 | Model benchmarking CLI (cli/benchmark.py) | M | [ ] |
| B15 | GGUF import from HuggingFace into Ollama | M | [ ] |
| B4+B9 | Input validation hardening + request timeout config | S | [ ] |

**Definition of Done:** Full document lifecycle (upload, list, delete). Multiple chunking strategies. Can benchmark model performance.

---

## Sprint 5 — Model Lab (Weeks 9-10)

**Goal:** Fine-tuning pipeline. Train, export, serve custom models.

| ID | Task | Size | Status |
|----|------|------|--------|
| B25 | Dataset preparation tools (JSON/JSONL conversion) | M | [ ] |
| B26 | LoRA fine-tuning pipeline (Unsloth/Axolotl) | L | [ ] |
| B27 | Training monitoring and metrics | M | [ ] |
| B28 | Model export (LoRA merge + GGUF conversion) | L | [ ] |
| B29 | Fine-tuning config templates (YAML) | S | [ ] |

**Definition of Done:** Can prepare a dataset, fine-tune a model with LoRA, export to GGUF, and serve through Ollama. Full cycle.

---

## Sprint 6 — Production Ready (Weeks 11-12)

**Goal:** Deployment automation, monitoring, CI. Ready for always-on workstation use.

| ID | Task | Size | Status |
|----|------|------|--------|
| B31b | Full Docker Compose (API + Ollama + WebUI + ChromaDB) | L | [ ] |
| B30 | Dockerfile for API server | M | [ ] |
| B32 | Systemd service files for workstation | S | [ ] |
| B33 | Startup/shutdown scripts | S | [ ] |
| B34 | Prometheus metrics endpoint | M | [ ] |
| B38 | Load/stress testing | M | [ ] |
| B39 | CI pipeline (GitHub Actions) | M | [ ] |

**Definition of Done:** Workstation runs the full stack as systemd services or Docker. Monitoring dashboard. Automated tests in CI.

---

## Full Backlog Reference

### API & Core Infrastructure
| ID | Item | Priority | Size |
|----|------|----------|------|
| B1 | API key authentication middleware | Critical | S |
| B2 | Rate limiting middleware | High | S |
| B3 | Structured logging (file + console) | High | S |
| B4 | Input validation beyond Pydantic schemas | Medium | S |
| B5 | Custom error types and error responses | Medium | S |
| B6 | CORS configuration from env vars (not wildcard) | Medium | XS |
| B7 | Wire up all unused env vars (.env parity) | Medium | S |
| B8 | /v1/embeddings endpoint | High | M |
| B9 | Request timeout configuration | Low | XS |
| B10 | Health check with model status + system metrics | Medium | S |

### Model Management
| ID | Item | Priority | Size |
|----|------|----------|------|
| B11 | Pull larger workstation models | High | S |
| B12 | Model comparison/benchmarking CLI tool | Medium | M |
| B13 | Single-shot query CLI tool (cli/query.py) | Low | S |
| B14 | Model auto-detection (Ollama vs registry) | Medium | S |
| B15 | GGUF import from HuggingFace into Ollama | Medium | M |

### Web UI
| ID | Item | Priority | Size |
|----|------|----------|------|
| B16 | Open WebUI integration (Docker or native) | High | M |
| B17 | Open WebUI configuration for our API endpoint | High | S |
| B18 | Conversation history persistence (via Open WebUI) | High | Free |

### RAG Pipeline
| ID | Item | Priority | Size |
|----|------|----------|------|
| B19 | ChromaDB vector store setup | High | M |
| B20 | Document ingestion pipeline (PDF, MD, TXT) | High | L |
| B21 | Embedding generation service | High | M |
| B22 | RAG-augmented chat endpoint | High | L |
| B23 | Document management API (upload, list, delete) | Medium | M |
| B24 | Chunking strategies (fixed, semantic, recursive) | Medium | M |

### Fine-Tuning
| ID | Item | Priority | Size |
|----|------|----------|------|
| B25 | Dataset preparation tools (JSON/JSONL conversion) | Medium | M |
| B26 | LoRA fine-tuning pipeline with Unsloth/Axolotl | Medium | L |
| B27 | Training monitoring and metrics | Medium | M |
| B28 | Model export (merge LoRA + convert to GGUF) | Medium | L |
| B29 | Fine-tuning config templates (YAML) | Low | S |

### DevOps & Deployment
| ID | Item | Priority | Size |
|----|------|----------|------|
| B30 | Dockerfile for API server | Medium | M |
| B31 | Docker Compose (API + Ollama + Open WebUI + ChromaDB) | Medium | L |
| B32 | Systemd service files for workstation | Medium | S |
| B33 | Startup/shutdown scripts | Low | S |
| B34 | Prometheus metrics endpoint | Low | M |
| B35 | Dependency cleanup (split requirements) | Medium | S |

### Testing & Quality
| ID | Item | Priority | Size |
|----|------|----------|------|
| B36 | Integration tests with real Ollama | High | M |
| B37 | Streaming response tests | Medium | S |
| B38 | Load/stress testing | Low | M |
| B39 | CI pipeline (GitHub Actions) | Low | M |

---

## Vision

**Local AI Command Center** — A single `docker compose up` that launches the entire AI stack: API server, chat UI, vector database, model manager. Running on the BD790i workstation, no cloud dependency, no telemetry, complete privacy.

**Multi-Model Orchestration** — Route tasks to specialized models automatically. Coding → DeepSeek, creative writing → MythoMax, research → Qwen 35B.

**Knowledge Base** — RAG pipeline indexing local documents, repos, notes. Ask questions against your own data using uncensored models.

**Model Lab** — Benchmark models head-to-head. Fine-tune on your data. Export to GGUF and serve immediately.

**Security Research Bridge** — Connect to cortex-syslog-generator for attack pattern analysis, detection rule creation, and threat narrative generation.

**Always-On Personal API** — Replace OpenAI API calls in VS Code, Obsidian, shell scripts — all pointing at `http://workstation:8000/v1/`.
