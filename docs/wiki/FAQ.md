# FAQ

## What is Enclave?

A self-hosted LLM platform with an OpenAI-compatible API. You run it on your own boxes. Inference happens locally via Ollama. No telemetry, no cloud, no subscription.

## How is this different from running Ollama directly?

Ollama gives you a model server. Enclave gives you:

- **OpenAI-compatible API** on top of Ollama (drop-in for any SDK)
- A **multi-agent workflow engine** with declarative YAML DAGs
- A **web dashboard** for model management, workflow composer, agent personas, document RAG, API key admin
- A **macOS native app** wrapping the whole stack with a first-run wizard
- **Architecture-aware orchestration** (1.3.0+) that adapts dispatch to your hardware
- Curated **agents and workflows** for security use cases (XSIAM, XDM, XQL) and productivity

## Is it free?

Yes. Source-available, no fee. See the [LICENSE](https://github.com/hankthebldr/local-ai-platform/blob/main/LICENSE) for terms.

## What hardware do I need?

| Model size | Minimum RAM | Reasonable performance |
|---|---|---|
| 3B | 6 GB free | Any laptop from the last 5 years |
| 7B | 8–12 GB free | Modern x86 / Apple Silicon |
| 13B | 16+ GB free | Mac M2/M3/M4 or Ryzen 5+ |
| 34B | 24+ GB free | Mac M-series with 32GB+, or Ryzen 9 with 32GB+ |
| 70B | 48+ GB free | Workstation territory |

See [Models](Models) for throughput targets per architecture.

## Does this work on Windows?

Yes, via Docker Desktop. There is no native Windows installer right now — Docker is the supported path. See [Deployment › Docker](Deployment#docker-compose).

## Does this work on Linux?

Yes — three paths:

1. Docker (same as Windows)
2. `pip install` of the wheel + bring-your-own Ollama
3. Source install via `./setup/install.sh`, which writes a systemd unit

## Is the API really OpenAI-compatible?

Yes. The `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, and `/v1/models` endpoints match the OpenAI shape. Streaming, function-calling, and seed parameters all work. SDKs:

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="<your-enclave-key>")
client.chat.completions.create(model="llama3.2:3b", messages=[...])
```

## Can I use cloud models too?

Yes. Admin → Cloud Models lets you register OpenAI, Anthropic, Together, OpenRouter, or any custom OpenAI-compatible endpoint. Once registered, they're selectable as workflow step models alongside local models. API keys are stored in `data/config/cloud_providers.json` (`chmod 0600`) and never echoed back through the UI.

## How do I add my own model?

```bash
# Pull any Ollama-published model
ollama pull <model:tag>

# Or add it to the curated registry
# edit MODEL_REGISTRY in models/download.py, then update MODELS.md
```

The sync hook will remind you to keep both in sync.

## How do I add my own workflow?

Drop a YAML file under `workflows/`. See [Workflows](Workflows) and the existing examples for the schema.

## How do I add my own agent?

Drop a YAML file under `agents/`. See [Agents](Agents).

## Does it really not phone home?

Correct. No analytics, no crash reports, no usage telemetry. The only outbound calls are model pulls (which you initiate) and cloud-provider calls (only if you've configured a cloud provider and a workflow uses it). The egress paths are auditable in source — `api/routers/*` and `api/services/cloud_*`.

## Why "Enclave"?

A sovereign sub-territory inside a larger one. Your data stays inside your enclave; the larger commercial-AI territory doesn't get to see it.

## Why is the Docker Hub repo `local-ai-platfrom` (with the typo)?

That's how it was created. Renaming would orphan published tags. The `ghcr.io/hankthebldr/enclave` mirror uses the corrected name.

## What's the relationship between Enclave and PANW Cortex?

Enclave is independent. The Cortex Console aesthetic on the web dashboard and the bundled XSIAM/XDM workflows + agents reflect the operator's day job in Cortex pre-sales — they're examples of what's possible in the workflow engine, not a Cortex product integration. There's no PANW affiliation, no shared codebase, no shared data flow.

## How do I report a bug?

[Open an issue](https://github.com/hankthebldr/local-ai-platform/issues/new). The [Troubleshooting](Troubleshooting) page has a list of diagnostics to attach.

## How do I contribute?

PRs welcome. Read [CLAUDE.md](https://github.com/hankthebldr/local-ai-platform/blob/main/CLAUDE.md) first — it documents the conventions and gotchas.
