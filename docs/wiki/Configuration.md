# Configuration

Every knob Enclave exposes lives in an environment variable. Defaults are dev-friendly; **harden these before exposing the API beyond `localhost`.**

## Quick-reference table

| Variable | Default | What it does |
|---|---|---|
| `API_HOST` | `0.0.0.0` | Interface to bind. **Set to `127.0.0.1`** unless you intend network exposure. |
| `API_PORT` | `8000` | FastAPI port. |
| `OLLAMA_HOST` | `http://localhost:11434` | Where the inference daemon lives. Used by `ollama_service`. |
| `ENABLE_API_AUTH` | `true` | Default-on auth. Fresh installs auto-provision a master key on first boot. |
| `CORS_ORIGINS` | `["*"]` | JSON array or CSV. **Restrict before exposure.** |
| `RATE_LIMIT_RPM` | `60` | Requests-per-minute per API key. |
| `REQUEST_TIMEOUT` | `300` | Seconds for an upstream Ollama call. CPU prefill on big models can take longer. |
| `MAX_CONCURRENT_REQUESTS` | `4` | Engine semaphore cap. |
| `OLLAMA_KEEP_ALIVE` | (unset) | Model retention in Ollama after a call. Resolver fallback (1.3.0+). |
| `STRICT_ARCH_DETECTION` | `false` | If `true`, refuse to boot on Ollama < 0.23.4 or unknown arch. |
| `ENCLAVE_DEPLOYMENT` | (auto) | Force `dmg`, `container`, or `host_native`. Auto-detected at startup. |
| `ENCLAVE_RELOAD` | `false` | Set to `1` for uvicorn auto-reload (dev only). |
| `LOG_LEVEL` | `info` | One of `debug`, `info`, `warning`, `error`, `critical`. |
| `ENCLAVE_DEFAULT_MODEL` | `llama3.2:3b` | Starter model the wizard / `run.sh` pulls. |

## Auth

When `ENABLE_API_AUTH=true` (the default), Enclave auto-provisions a master API key on first boot and writes it once to:

```
data/config/first-run-key.txt        (chmod 0600)
```

Plus a one-line entry in the startup banner. **Save it immediately** — the raw value is never stored in the keystore (only a hash) and cannot be retrieved later. Rotate via the Admin → API keys tab in the dashboard.

If you set `ENABLE_API_AUTH=false`:

- A startup warning fires (`SECURITY: ...`)
- A louder warning fires if you also set `API_HOST` to a non-loopback (e.g. `0.0.0.0`)
- Every endpoint — including workflow execution, document ingestion, key management — is unauthenticated

**Production rule:** auth on, restricted CORS, no `*` origins.

## CORS

The default `CORS_ORIGINS=["*"]` is for dev convenience. Restrict for production:

```bash
export CORS_ORIGINS='["https://enclave.your-org.internal"]'
```

JSON arrays or comma-separated values both work. A startup warning fires when `*` is present.

## keep_alive (1.3.0+)

Per-step `keep_alive` lets you keep models in memory across workflow steps. Four-tier resolver, highest-priority wins:

1. `step.config.keep_alive` (in YAML) — explicit per-step override
2. `workflow.defaults.keep_alive` — workflow-level default
3. `arch.default_keep_alive()` — detected at startup:
   - `unified` (Mac M-series / x86 CPU) → `"30m"` (reload dominates)
   - `nvidia_single` → `"0"` (VRAM is scarce, evict aggressively)
   - `nvidia_multi` → `"5m"`
4. `OLLAMA_KEEP_ALIVE` env — deepest fallback (matches pre-1.3.0 behavior)

## CPU performance knobs

Surfaced in `/api/inventory/system`:

| Env var | Effect |
|---|---|
| `OLLAMA_NUM_PARALLEL` | Concurrent requests per loaded model. Default 4. |
| `OLLAMA_MAX_LOADED_MODELS` | Hard cap on simultaneously-loaded models. |
| `OLLAMA_FLASH_ATTENTION` | `1` to enable flash-attention. Speeds up long contexts on supported hardware. |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` shrinks KV cache 2× with minor quality loss. |

## Verifying current config

```bash
curl -fsS http://localhost:8000/api/info | jq
curl -fsS http://localhost:8000/api/system/architecture | jq   # 1.3.0+
curl -fsS http://localhost:8000/api/system/pressure | jq       # 1.3.0+
```

## See also

- [Deployment](Deployment) — how to wire env vars into systemd / Docker / DMG
- [Troubleshooting](Troubleshooting) — what each warning means
