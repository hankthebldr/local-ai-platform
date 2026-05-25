# Models

The model catalog lives in [`models/download.py`](https://github.com/hankthebldr/local-ai-platform/blob/master/models/download.py) (`MODEL_REGISTRY`) and is documented in [`MODELS.md`](https://github.com/hankthebldr/local-ai-platform/blob/master/MODELS.md). The registry must stay in sync — a sync hook reminds developers on every PR that touches one without the other.

## Picking a model

| Goal | Pick |
|---|---|
| First-time setup (3 GB, ~50 tok/s) | `llama3.2:3b` |
| Coding day-to-day on a Mac M-series | `qwen2.5-coder:7b` or `deepseek-coder-v2:16b` |
| General chat with quality > speed | `qwen2.5:14b-instruct-q5_K_M` |
| Uncensored research / writing | `dolphin-mixtral:8x7b` or `wizardlm-uncensored:13b` |
| Long-context (32K+) | `qwen2.5:32k` or any model with `:32k` suffix |
| Embeddings (RAG) | `nomic-embed-text` |

## Quantization conventions

| Level | When |
|---|---|
| `Q4_K_M` (default) | Sweet spot for 7B–34B on CPU. ~4.5 GB for 7B. |
| `Q5_K_M` | Quality bump worth ~25% more RAM. Use when you have headroom. |
| `Q3_K_M` | 70B+ models on commodity hardware. Quality drops noticeably. |
| `Q8_0` | Almost lossless. Use when memory is plentiful and quality matters. |

## Throughput targets (CPU)

| Model size | Apple Silicon | x86 (Ryzen 9 7945HX) |
|---|---|---|
| 7B Q4_K_M | 40–50 tok/s | 25–35 tok/s |
| 13B Q4_K_M | 25–30 tok/s | 15–20 tok/s |
| 34B Q4_K_M | 10–15 tok/s | 6–10 tok/s |
| 70B Q4_K_M | 3–5 tok/s | 2–3 tok/s |

## Managing models

### From the dashboard

Models tab → Discover → click pull. Progress bar streams. Tab also lists registered cloud providers as pullable from a single surface.

### From the CLI

```bash
# List the registry
python models/download.py --list
# or
enclave-workflow --list-models      # 1.3.0+ console script

# Download
python models/download.py dolphin-mixtral

# Inspect what Ollama has
ollama list
```

### From Ollama directly

```bash
ollama pull llama3.2:3b
ollama rm llama3.2:3b
ollama show llama3.2:3b
```

## Cloud providers

Admin → Cloud Models lets you register external OpenAI-compatible providers (OpenAI, Anthropic, Together, OpenRouter, custom endpoint). API keys are stored in `data/config/cloud_providers.json` (`chmod 0600`). Once registered, they're selectable as workflow step models like any local model.

## Disk usage

Models live in `~/.ollama/models/`. Plan ~2 GB / GB-of-parameters at Q4_K_M:

| 18-model registry | ~140 GB |
| Starter only (`llama3.2:3b`) | ~3 GB |
| Pragmatic working set (5 models) | ~25–30 GB |

## See also

- [Architecture](Architecture) — how the engine picks a model per step
- [Workflows](Workflows) — role-based model selection in YAML
- [Configuration](Configuration) — `OLLAMA_KEEP_ALIVE` and per-step `keep_alive`
