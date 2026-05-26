# Troubleshooting

Common failure modes and how to diagnose them. Search this page first — most issues land in the same dozen buckets.

## Boot-time

### `Architecture detection failed`

The startup banner shows the warning and falls back to degraded mode. Causes:

- **Ollama unreachable.** Check `ollama serve` is running and `OLLAMA_HOST` is correct.
- **Ollama version too old.** The detector pins the floor at `0.23.4`. Upgrade with `brew upgrade ollama` (macOS) or pull a newer container.
- **nvidia-ml-py import error on Linux.** Expected on CPU-only hosts — the detector catches `NVMLError("Shared Library Not Found")` and treats it as `cpu_x86`. If it's a hard crash, your `nvidia-ml-py` install is corrupt; reinstall via `pip install --force-reinstall nvidia-ml-py`.

If you need a hard failure instead of degraded boot:

```bash
export STRICT_ARCH_DETECTION=true
```

### `Ollama: NOT responding`

The lifespan probe couldn't reach the daemon. Check:

```bash
ollama list                                  # should list installed models
curl -fsS http://localhost:11434/api/tags    # should return JSON
sudo systemctl status ollama                 # if installed via package
```

### `SECURITY: API_HOST=0.0.0.0 ... ENABLE_API_AUTH=false`

You've turned auth off and bound to a non-loopback. Fix one of:

```bash
export API_HOST=127.0.0.1
# or
export ENABLE_API_AUTH=true
```

See [Configuration › Auth](Configuration#auth) for the auto-provisioned master key flow.

## Workflow / runtime

### `WorkflowValidationError: step 'X' requests N GB but arch budget is M GB` (1.3.0+)

The feasibility validator caught a step whose `est_size_gb` exceeds your hardware budget. Either:

1. Reduce the step's model (e.g., `qwen2.5:14b` → `qwen2.5:7b`) and update `est_size_gb`
2. Run on bigger hardware
3. Override the budget (advanced — see [Architecture](Architecture#architecture-aware-orchestration-130))

### A step hangs forever

Most likely Ollama is loading a big model on CPU and your `REQUEST_TIMEOUT` is too low. The 1.1.x bump set the default to 900s for exactly this reason:

```bash
export REQUEST_TIMEOUT=1800    # 30 minutes
```

### `model_fallback` banner in agent chat

The agent's pinned model isn't installed. Either pull it (`ollama pull <model>`) or accept the fallback — the dashboard tells you which model actually responded.

## RAG

### Documents added but queries return nothing

Two likely causes:

1. **Chunker hasn't run yet.** Wait a few seconds after upload. Check `/api/documents/` for status.
2. **Embedding model missing.** Pull it:

   ```bash
   ollama pull nomic-embed-text
   ```

### Chroma "could not connect" error

Check `data/chroma/` exists and is writable. If not, ensure the API process owns the parent dir.

## Performance

### "It's slow on a Mac M-series"

7B Q4_K_M should be 40–50 tok/s. If you're seeing < 20:

- Confirm Activity Monitor shows Ollama using the **Apple GPU** (Metal). If it's CPU-only, restart `ollama serve`.
- Disable other memory-hungry apps. Unified memory means GPU work shares with everything else.
- Try `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0`.

### CPU pegged on x86

Expected. CPU inference is by definition CPU-bound. Tune:

```bash
export OLLAMA_NUM_PARALLEL=2          # default is 4
export OLLAMA_MAX_LOADED_MODELS=2
```

## Docker

### `Cannot connect to the Docker daemon`

```bash
open -a Docker                # macOS — wait for the whale icon
sudo systemctl start docker   # Linux
```

### Stack boots but model never pulls

Check container logs:

```bash
docker compose logs -f ollama
docker compose logs -f api
```

Usually a network issue or a typo'd `ENCLAVE_DEFAULT_MODEL`.

## macOS DMG

### "Enclave can't be opened because Apple cannot check it for malware"

The DMG is unsigned today. Clear the quarantine flag once:

```bash
xattr -dr com.apple.quarantine /Applications/Enclave.app
```

### Setup wizard hangs at "Installing Ollama"

The bundled installer uses `brew install ollama`. If brew isn't on PATH, the wizard surfaces an error. Install brew first, then re-launch.

## Filing an issue

Before opening an issue, attach:

```bash
curl -fsS http://localhost:8000/api/info > info.json
curl -fsS http://localhost:8000/api/system/architecture > arch.json   # 1.3.0+
curl -fsS http://localhost:8000/api/system/pressure > pressure.json   # 1.3.0+
journalctl -u enclave-api -n 200 > api.log                            # Linux + systemd
ollama list > ollama-models.txt
```

[Open an issue](https://github.com/hankthebldr/local-ai-platform/issues/new).
