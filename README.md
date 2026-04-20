<p align="center">
  <img src="assets/logo/enclave-mark.svg" width="80" alt="Enclave">
</p>

<h1 align="center">Enclave</h1>

<p align="center">
  Self-hosted LLM infrastructure with OpenAI-compatible API. CPU-optimized. Buy once, run forever.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-1a1a2e?style=flat&labelColor=1a1a2e&color=00E87B" alt="Version">
  <img src="https://img.shields.io/badge/macOS-supported-1a1a2e?style=flat&labelColor=1a1a2e&color=00C0E8" alt="macOS">
  <img src="https://img.shields.io/badge/Linux-supported-1a1a2e?style=flat&labelColor=1a1a2e&color=00C0E8" alt="Linux">
  <img src="https://img.shields.io/badge/license-Commercial-1a1a2e?style=flat&labelColor=1a1a2e&color=888888" alt="License">
</p>

---

Enclave runs LLMs on your hardware. OpenAI-compatible API, Ollama backend, zero cloud dependencies. Individual and Teams licenses.

## What it does

- **OpenAI-compatible API** — drop-in replacement. Point your existing code at `localhost:8000`
- **CPU-optimized inference** — GGUF quantized models via Ollama. 7B at 40-50 tok/s, 13B at 25-30 tok/s
- **Model management** — download, configure, and switch between 18+ models from the registry
- **Multi-agent workflows** — YAML-defined step pipelines with role-based model selection
- **Web dashboard** — monitor models, system health, and API status
- **macOS app** — native desktop wrapper with setup wizard
- **Zero telemetry** — no data leaves your machine. No internet required for inference

## Quick start

```bash
# Install
./setup/install.sh

# Start Ollama
ollama serve

# Start API
source venv/bin/activate
python -m api.main

# Verify
curl http://localhost:8000/health
```

API is at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

## Models

```bash
# List available models
python models/download.py --list

# Download a model
python models/download.py dolphin-mixtral

# List installed
ollama list
```

Default quantization: Q4_K_M (best quality/speed balance). See [MODELS.md](MODELS.md) for the full registry.

## API usage

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

Compatible with any OpenAI SDK client.

## Hardware targets

| Machine | RAM | Role | Throughput |
|---------|-----|------|------------|
| Mac M4 Pro | 48GB | Development | 7B @ 50 tok/s |
| MS-01 (Ryzen 9 7945HX) | 64GB | API serving | 34B @ 12 tok/s |
| BD790i (Ryzen 9 7945HX) | 96GB | Research | 70B @ 5 tok/s |

## Licensing

Enclave is commercial software by [ohno llc](https://github.com/hankthebldr).

| Tier | Model |
|------|-------|
| **Individual** | One seat, one-time purchase. All updates included. |
| **Teams** | Volume discount per seat. Priority support. |

See [LICENSE](LICENSE) for terms.

## Documentation

- [MODELS.md](MODELS.md) — model registry and selection
- [CLAUDE.md](CLAUDE.md) — developer guide
- [docs/](docs/) — architecture, deployment, and API reference

---

<sub>by ohno llc</sub>
