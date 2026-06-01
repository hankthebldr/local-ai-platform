# vLLM inference backend (Linux / NVIDIA)

> Status: gpu-runner-abstraction **Phase 2** — `VllmRunner` + `detect_runners()`
> wiring. The runner registry is live; per-model dispatch flows through
> `MODEL_REGISTRY.runner`. Full live chat-path routing through the registry is
> Phase 4 (tracked separately).

On the **BD790i Blackwell** box (and any Linux + NVIDIA host), Ollama's
llama.cpp runner leaves throughput on the table: it serializes requests and
runs GGUF weights. **vLLM** is the performance path here —

- **NVFP4 / FP8** weights the RTX PRO 4000 Blackwell accelerates in hardware,
- **paged-attention** KV cache, and
- **continuous batching** that keeps the GPU saturated under concurrent load.

Enclave talks to vLLM over its **OpenAI-compatible HTTP API** — the same
surface Enclave itself exposes. The `VllmRunner` is a thin HTTP client, so
**vLLM never enters the Enclave venv**; you only need a reachable server URL.

## Architecture

```
Enclave API ──HTTP /v1/chat/completions──▶ vLLM server (:8000)  ← GPU, NVFP4
     │                                          (pinned model, continuous batch)
     └──HTTP /api/chat──────────────────▶ Ollama daemon (:11434) ← fallback
```

Two runners coexist in the `RunnerRegistry`:

| Runner  | Role                         | keep_alive | hot-swap | batching |
|---------|------------------------------|:----------:|:--------:|:--------:|
| ollama  | universal GGUF fallback      | yes        | yes      | no       |
| vllm    | NVIDIA performance path      | no (pinned)| no       | **yes**  |

`detect_runners()` (called from `api/main.py` startup) always registers Ollama
and registers vLLM when `ENCLAVE_VLLM_BASE_URLS` is set.

## 1. Install + serve vLLM (out-of-band)

vLLM pulls a heavy CUDA stack — keep it in its **own** environment:

```bash
python3 -m venv ~/vllm-env && source ~/vllm-env/bin/activate
pip install vllm
```

Launch it with the helper (serves a Blackwell-native NVFP4 model by default):

```bash
scripts/vllm-serve.sh                              # default NVFP4 model on :8000
VLLM_MODEL=nvidia/Qwen3-Coder-30B-A3B-NVFP4 \
  VLLM_PORT=8000 scripts/vllm-serve.sh             # explicit model
```

> **Port note:** the BD790i runs the Enclave API on **:8001** and vLLM on
> **:8000** (see `docs/deployment/bd790i-testing.md`). Make sure nothing else
> (a stale benchmark, another vLLM) is holding the GPU first: `nvidia-smi`.

## 2. Point Enclave at it

In `.env`:

```bash
ENCLAVE_VLLM_BASE_URLS=http://localhost:8000   # comma-separated; first is used
# ENCLAVE_VLLM_API_KEY=                         # if vLLM was started with --api-key
# ENCLAVE_VLLM_MAX_CONCURRENT=256               # scheduler dispatch cap
# ENCLAVE_PREFERRED_RUNNER=vllm                 # dev escape hatch (reporting)
# STRICT_RUNNER_DETECTION=true                  # fail startup if vLLM unreachable
```

Restart the API, then confirm both runners are live:

```bash
curl -s localhost:8001/api/system/runner | python3 -m json.tool
```

```json
{
  "runners": [
    { "name": "ollama", "base_url": "http://localhost:11434", ... },
    { "name": "vllm",   "base_url": "http://localhost:8000/v1",
      "supports_continuous_batching": true,
      "health": { "reachable": true, "version": "0.6.3",
                  "loaded_models": ["nvidia/Qwen3-Coder-30B-A3B-NVFP4"],
                  "extras": { "gpu_cache_usage_perc": 0.0 } } }
  ],
  "preferred_runner": "vllm"
}
```

## 3. Route a model to vLLM

Per-model dispatch reads the `runner` field on a `MODEL_REGISTRY` entry
(`models/download.py`); it defaults to `ollama` for every existing entry, so
nothing changes until you opt a model in:

```python
"qwen3-coder-30b-a3b-nvfp4": {
    "name": "Qwen3-Coder-30B-A3B (NVFP4)",
    "hf_repo": "nvidia/Qwen3-Coder-30B-A3B-NVFP4",
    "runner": "vllm",          # ← dispatch to the vLLM runner
    "quant": "nvfp4",
},
```

`ModelResolver.resolve_with_runner()` then returns the `VllmRunner` for that
id and the Ollama runner for everything else.

## Behaviour notes

- **Pinned server.** vLLM loads its model at launch. `load()` / `unload()` are
  no-ops (`reason="vllm_pinned_server"`); `keep_alive` is ignored (logged). To
  change models, restart the server.
- **Unreachable at startup.** By default the runner is registered optimistically
  so a server that comes up late still works — dispatch surfaces a clear
  connection error rather than `RunnerNotConfigured`. Set
  `STRICT_RUNNER_DETECTION=true` to fail fast instead.
- **Metrics.** `health().extras` scrapes `vllm:num_requests_running`,
  `num_requests_waiting`, and `gpu_cache_usage_perc` from `/metrics` when present.

## Benchmarking Ollama vs vLLM

Quick A/B once both are serving a comparable model:

```bash
# vLLM (continuous batching shines under concurrency)
hey -n 100 -c 8 -m POST -T application/json \
  -d '{"model":"<vllm-model>","messages":[{"role":"user","content":"Write a haiku"}]}' \
  http://localhost:8000/v1/chat/completions

# Ollama
hey -n 100 -c 8 -m POST -T application/json \
  -d '{"model":"qwen2.5:7b","messages":[{"role":"user","content":"Write a haiku"}]}' \
  http://localhost:11434/v1/chat/completions
```

Compare tokens/sec and p95 latency. vLLM's advantage grows with concurrency
(`-c`); at `-c 1` the gap narrows to raw kernel efficiency.
