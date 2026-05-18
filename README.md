<p align="center">
  <img src="assets/logo/enclave-mark.svg" width="80" alt="Enclave">
</p>

<h1 align="center">Enclave</h1>

<p align="center">
  Self-hosted LLM infrastructure with OpenAI-compatible API. CPU-optimized. Source-available.
</p>

<p align="center">
  <a href="https://github.com/hankthebldr/local-ai-platform/releases/latest"><img src="https://img.shields.io/github/v/release/hankthebldr/local-ai-platform?label=release&labelColor=1a1a2e&color=00E87B&style=flat" alt="Latest release"></a>
  <a href="https://github.com/hankthebldr/local-ai-platform/releases?q=prerelease%3Atrue&expanded=true"><img src="https://img.shields.io/github/v/release/hankthebldr/local-ai-platform?include_prereleases&label=nightly&labelColor=1a1a2e&color=FA582D&style=flat" alt="Nightly"></a>
  <a href="https://github.com/hankthebldr/local-ai-platform/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/hankthebldr/local-ai-platform/ci.yml?branch=master&labelColor=1a1a2e&color=00C0E8&style=flat&label=ci" alt="CI"></a>
  <img src="https://img.shields.io/badge/macOS%2012%2B-supported-1a1a2e?style=flat&labelColor=1a1a2e&color=00C0E8" alt="macOS">
  <img src="https://img.shields.io/badge/Linux-supported-1a1a2e?style=flat&labelColor=1a1a2e&color=00C0E8" alt="Linux">
  <img src="https://img.shields.io/badge/license-Source--Available%20%C2%B7%20Evaluation-1a1a2e?style=flat&labelColor=1a1a2e&color=888888" alt="License">
</p>

---

Enclave runs LLMs on your hardware. OpenAI-compatible API, Ollama backend, zero cloud dependencies. Source-available for evaluation and security review; a production license is on the roadmap.

## What it does

- **OpenAI-compatible API** — drop-in replacement. Point your existing code at `localhost:8000`
- **CPU-optimized inference** — GGUF quantized models via Ollama. 7B at 40-50 tok/s, 13B at 25-30 tok/s
- **Model management** — download, configure, and switch between 18+ models from the registry
- **Multi-agent workflows** — YAML-defined step pipelines with role-based model selection
- **Web dashboard** — monitor models, system health, and API status
- **macOS app** — native desktop wrapper with setup wizard
- **Zero telemetry** — no data leaves your machine. No internet required for inference

## Quick start

Three paths — pick one:

### macOS app (DMG) — for end users

1. Download **Enclave.dmg** from the [latest release](https://github.com/hankthebldr/local-ai-platform/releases/latest)
   *(Or grab the rolling [nightly build](https://github.com/hankthebldr/local-ai-platform/releases/tag/nightly) for the freshest master.)*
2. Open the DMG and drag **Enclave.app** to `/Applications`.
3. First launch: macOS Gatekeeper will warn — the app is currently **not signed/notarized**. Bypass once with:
   ```bash
   xattr -dr com.apple.quarantine /Applications/Enclave.app
   ```
   Then double-click **Enclave** in Launchpad.
4. The native window opens the **first-run setup wizard** (`/setup`) which installs Ollama if needed and pulls a starter model. After that you land on the dashboard.

> **Requirements:** macOS 12.0 (Monterey) or later. ~6 GB free disk for the bundled runtime + a small starter model. Ollama is installed automatically by the wizard if missing.

### Docker — any platform with Docker Desktop

For non-developers on Linux / Windows, or anyone who wants Enclave fully isolated in containers. No Python, no virtualenv, no manual Ollama install.

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine on Linux) and make sure the whale icon is running.
2. Clone or download this repo, open a terminal in the project folder, and run:
   ```bash
   ./run.sh
   ```
3. The script verifies Docker, brings up the stack (`ollama` + `api`), pulls a small starter model on first run (`llama3.2:3b`, ~2 GB), and opens the dashboard in your browser.

| | URL |
|---|---|
| **Enclave SPA** (the application) | `http://localhost:8000` |
| API docs                          | `http://localhost:8000/docs` |
| Open WebUI (opt-in)               | `http://localhost:8081` — `docker compose -f docker-compose.yml -f docker-compose.webui.yml up -d` |

To stop: `./stop.sh` (data preserved) — or `./stop.sh --reset` to wipe models and chat history.

> **Requirements:** ~4 GB free RAM and ~3 GB free disk for the starter model. Pick a different starter with `ENCLAVE_DEFAULT_MODEL=qwen2.5:3b ./run.sh`.

### From source — for developers

```bash
# Install (creates ./venv, installs core+dev deps, sets up systemd unit on Linux)
./setup/install.sh

# Boot Ollama + API + auto-open the dashboard in your browser
./scripts/start.sh

# Or, on macOS, exercise the same native pywebview window the DMG ships
./scripts/start_desktop.sh

# Verify everything boots and every UX route renders
./scripts/verify_local.sh
```

API at `http://localhost:8000` · Dashboard at `http://localhost:8000/` · Docs at `http://localhost:8000/docs` · First-run wizard at `http://localhost:8000/setup`.

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

## Code-level artifacts

What ships in this repo, and where to find it:

| Surface | Path | Notes |
|---|---|---|
| FastAPI server (OpenAI-compatible) | [api/main.py](api/main.py) | 16 routers under `api/routers/`, services under `api/services/` |
| Web dashboard + setup wizard | [api/static/](api/static/) | Served at `/` and `/setup` by the FastAPI app |
| CLI chat / query / workflow | [cli/](cli/) | Rich-formatted; `python -m cli.chat`, `cli/workflow.py` |
| Multi-agent workflow engine | [api/services/workflow_engine.py](api/services/workflow_engine.py) | YAML pipelines under [workflows/](workflows/) |
| Custom agents (Gems) | [agents/](agents/) + [api/routers/agents.py](api/routers/agents.py) | YAML-defined personas with pinned context |
| Model registry | [models/download.py](models/download.py) | 18+ models — see [MODELS.md](MODELS.md) |
| macOS desktop wrapper | [desktop/app.py](desktop/app.py) | pywebview window around the FastAPI server |
| DMG builder | [scripts/build_mac.sh](scripts/build_mac.sh) | Bundles a self-contained `.app` + dmg |
| Local dev scripts | [scripts/](scripts/) | `start.sh`, `start_desktop.sh`, `verify_local.sh`, `status.sh`, `test.sh` |

### Build the DMG yourself

The same script CI uses on tag pushes:

```bash
brew install librsvg create-dmg     # one-time
./scripts/generate-icons.sh         # regenerate icns from SVG
./scripts/build_mac.sh              # produces dist/Enclave.app + dist/Enclave.dmg
open dist/Enclave.app               # smoke-test the bundle
```

The build script reads `ENCLAVE_VERSION` (or falls back to `git describe`) and stamps it into `Info.plist`. Override for a one-off custom build:

```bash
ENCLAVE_VERSION=v1.2.3-local ./scripts/build_mac.sh
```

### Release pipeline

| Trigger | Workflow | Artifact |
|---|---|---|
| Tag push `v*.*.*` | [release.yml](.github/workflows/release.yml) | Stable GitHub Release with signed DMG |
| Push to `master` | [release.yml](.github/workflows/release.yml) | Rolling `nightly` pre-release (replaced each merge) |
| PR / push to `master` | [ci.yml](.github/workflows/ci.yml) | pytest + lint + macOS `.app` smoke build (boots and probes UX routes) |
| Tag push or release publish | [pages.yml](.github/workflows/pages.yml) | Updates [hankthebldr.github.io/local-ai-platform](https://hankthebldr.github.io/local-ai-platform/) with the latest release version |

Every master merge re-publishes a freshly smoke-tested DMG to the [`nightly`](https://github.com/hankthebldr/local-ai-platform/releases/tag/nightly) release. Stable releases are cut by pushing a `vX.Y.Z` tag.

## Hardware targets

| Machine | RAM | Role | Throughput |
|---------|-----|------|------------|
| Mac M4 Pro | 48GB | Development | 7B @ 50 tok/s |
| MS-01 (Ryzen 9 7945HX) | 64GB | API serving | 34B @ 12 tok/s |
| BD790i (Ryzen 9 7945HX) | 96GB | Research | 70B @ 5 tok/s |

## Licensing

Enclave is source-available proprietary software by [ohno llc](https://github.com/hankthebldr). The current license permits source review and personal non-production evaluation; production and commercial use require a license that has not yet been published.

A commercial production license is on the roadmap. To register interest and be notified when it's available, open a thread on [Discussions](https://github.com/hankthebldr/local-ai-platform/discussions).

See [LICENSE](LICENSE) for the full terms.

## Documentation

- [MODELS.md](MODELS.md) — model registry and selection
- [CLAUDE.md](CLAUDE.md) — developer guide
- [docs/](docs/) — architecture, deployment, and API reference

---

<sub>by ohno llc</sub>
