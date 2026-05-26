# Deployment

Five supported install paths. Pick by audience:

| Path | Audience | Maintenance |
|---|---|---|
| [macOS DMG](#macos-dmg) | End users on a Mac | Wizard-driven; auto-update on next DMG download |
| [Docker compose](#docker-compose) | Linux/Windows/Mac; isolated runtime | `docker compose pull && docker compose up -d` |
| [GHCR-only Docker](#ghcr-only) | Anyone — no Docker Hub account | Same as Docker compose, different registry |
| [pip wheel](#pip-wheel) | Python developers embedding the engine | `pip install --upgrade <wheel-url>` |
| [Source + systemd](#source--systemd) | Linux operators on bare metal | `git pull && ./setup/install.sh && systemctl restart enclave-api` |

## macOS DMG

1. Download `Enclave.dmg` from the [latest release](https://github.com/hankthebldr/local-ai-platform/releases/latest).
2. Drag to `/Applications`.
3. **First-run Gatekeeper bypass:**
   ```bash
   xattr -dr com.apple.quarantine /Applications/Enclave.app
   ```
4. Launch. The first-run wizard installs Ollama (via `brew install ollama` or direct binary) and pulls `llama3.2:3b` as a starter.

**Where data lives:**
- App: `/Applications/Enclave.app`
- Ollama models: `~/.ollama/models/`
- Workflow runs, RAG store, config: `~/Library/Application Support/Enclave/`

## Docker compose

The repo ships [`docker-compose.yml`](https://github.com/hankthebldr/local-ai-platform/blob/master/docker-compose.yml) with two services (`ollama` + `api`). The wrapper script:

```bash
./run.sh
# Verifies Docker is running, brings up the stack, pulls a starter model
# on first run, opens the dashboard.
```

To stop: `./stop.sh` (data preserved) or `./stop.sh --reset` (wipes models + chat history).

### Optional: Open WebUI sidecar

```bash
docker compose -f docker-compose.yml -f docker-compose.webui.yml up -d
# Open WebUI now on http://localhost:8081
```

### Pinning to a stable image

```yaml
# docker-compose.override.yml
services:
  api:
    image: hankthebldrr/local-ai-platfrom:<version>   # never the rolling `:latest`
```

## GHCR-only

If you can't pull from Docker Hub (corp firewall, no account):

```bash
docker pull ghcr.io/hankthebldr/enclave:<version>
docker tag ghcr.io/hankthebldr/enclave:<version> hankthebldrr/local-ai-platfrom:<version>
docker compose up -d   # docker-compose.yml references the Hub image name
```

Same digest, same Trivy scan, same release cycle. Both registries published by [`.github/workflows/docker-publish.yml`](https://github.com/hankthebldr/local-ai-platform/blob/master/.github/workflows/docker-publish.yml).

## pip wheel

```bash
# Latest stable wheel, no PyPI required
pip install \
  https://github.com/hankthebldr/local-ai-platform/releases/download/v<version>/enclave-<version>-py3-none-any.whl

# Optional extras
pip install 'enclave[rag] @ https://github.com/.../enclave-<version>-py3-none-any.whl'
pip install 'enclave[desktop] @ ...'    # macOS only — py2app + pywebview
pip install 'enclave[dev] @ ...'        # pytest, black, mypy
```

You **must** provide Ollama separately. The wheel imports cleanly on any platform but every inference call goes to `OLLAMA_URL` (default `http://localhost:11434`).

Run the API:

```bash
enclave-api               # uvicorn against api.main:app
enclave api               # same, via the unified dispatcher
ENCLAVE_RELOAD=1 enclave-api    # dev mode with auto-reload
```

## Source + systemd

```bash
git clone https://github.com/hankthebldr/local-ai-platform.git
cd local-ai-platform
./setup/install.sh           # creates ./venv, installs core+dev deps
                             # on Linux: writes /etc/systemd/system/enclave-api.service
sudo systemctl enable --now enclave-api
sudo systemctl status enclave-api
```

The systemd unit boots `enclave-api` against the venv. Logs: `journalctl -u enclave-api -f`.

## Configuration

Env vars + auth + CORS: see [Configuration](Configuration).

## Verifying a deployment

```bash
# Health (200 OK)
curl -fsS http://localhost:8000/health

# Architecture snapshot (1.3.0+)
curl -fsS http://localhost:8000/api/system/architecture | jq
curl -fsS http://localhost:8000/api/system/pressure | jq

# OpenAI compat round-trip
curl -fsS http://localhost:8000/v1/models | jq
```

If anything 5xx's, see [Troubleshooting](Troubleshooting).
