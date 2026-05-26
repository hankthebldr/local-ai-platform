# Quickstart

Pick the install path that matches your situation. Each takes < 5 minutes.

## macOS app (DMG)

```bash
# 1. Download
open "https://github.com/hankthebldr/local-ai-platform/releases/latest"
# Drag Enclave.dmg → /Applications

# 2. First-run Gatekeeper bypass (the DMG is unsigned right now)
xattr -dr com.apple.quarantine /Applications/Enclave.app

# 3. Launch — the first-run wizard installs Ollama and pulls a starter model
open -a Enclave
```

Then point your browser at the native window. Dashboard at `/`, setup wizard at `/setup`, API docs at `/docs`.

## Docker

```bash
git clone https://github.com/hankthebldr/local-ai-platform.git
cd local-ai-platform
./run.sh   # brings up `ollama` + `api`, pulls llama3.2:3b on first run
```

Or pull the published image directly without cloning. Substitute `<version>` with the latest tag (or use `:latest`):

```bash
# Docker Hub
docker pull hankthebldrr/local-ai-platfrom:<version>
# Or GHCR mirror — no Hub account required
docker pull ghcr.io/hankthebldr/enclave:<version>
```

## pip

For embedding the engine inside another Python service:

```bash
pip install https://github.com/hankthebldr/local-ai-platform/releases/download/v<version>/enclave-<version>-py3-none-any.whl
enclave-api               # boots FastAPI on 127.0.0.1:8000
enclave version
```

You still need Ollama running and reachable at `OLLAMA_URL` (defaults to `http://localhost:11434`). The wheel does **not** install Ollama.

## From source

```bash
git clone https://github.com/hankthebldr/local-ai-platform.git
cd local-ai-platform
./setup/install.sh       # creates ./venv, installs core+dev deps, sets up systemd on Linux
./scripts/start.sh       # boots Ollama + API + opens dashboard
```

## First request

```bash
# OpenAI-compatible — drop-in for any SDK
curl -X POST http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "llama3.2:3b",
    "messages": [{"role": "user", "content": "hello"}]
  }'
```

## Where to next?

- [Architecture](Architecture) — what's running under the hood
- [Models](Models) — pick the right model for your hardware
- [Configuration](Configuration) — tune perf, auth, CORS
- [Troubleshooting](Troubleshooting) — common first-run issues
