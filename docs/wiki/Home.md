# Enclave Wiki

Welcome. This wiki is the canonical operator-facing documentation for **Enclave** — self-hosted LLM infrastructure with an OpenAI-compatible API.

Pages are version-controlled under [`docs/wiki/`](https://github.com/hankthebldr/local-ai-platform/tree/main/docs/wiki) in the main repo and synced to this Wiki on every `vX.Y.Z` tag. If you find a mistake, open a PR against `docs/wiki/<page>.md` — do not edit the Wiki directly, your edit will be overwritten on the next release.

## Start here

| Page | Read this if … |
|---|---|
| [Quickstart](Quickstart) | You just want it running in 60 seconds. |
| [Architecture](Architecture) | You want to understand how requests flow through the system. |
| [Deployment](Deployment) | You're putting it on a real box (DMG / Docker / pip / source / systemd). |
| [Configuration](Configuration) | You need to tune env vars, CORS, auth, perf. |
| [Models](Models) | You're picking models, quantizations, throughput targets. |
| [Workflows](Workflows) | You want to author multi-agent YAML pipelines. |
| [Agents](Agents) | You're building Gems-style personas. |
| [Troubleshooting](Troubleshooting) | Something broke. |
| [FAQ](FAQ) | Common questions. |
| [Release-Notes](Release-Notes) | What changed in each release. |

## Three-second pitch

- **OpenAI-compatible API** on `localhost:8000`. Point your existing SDKs at it.
- **CPU-first inference** via Ollama (GGUF quantized models). 7B at ~40–50 tok/s on a modern x86 box.
- **Zero telemetry, zero cloud.** No outbound calls except model pulls you initiate. Source-available, auditable.
- **Multi-agent workflows** via declarative YAML DAGs with role-based model selection, Jinja2 prompts, output parsers, quality gates, and checkpoint/resume.
- **Architecture-aware orchestration** (1.3.0+) — the engine adapts dispatch and `keep_alive` to your hardware.
- **Native macOS DMG · Docker · pip · source** — pick whichever install path fits.

## Current release

See [Release-Notes](Release-Notes) for the running list. The repo's [CHANGELOG.md](https://github.com/hankthebldr/local-ai-platform/blob/main/CHANGELOG.md) is the source of truth.

## External links

- [Product page](https://hankthebldr.github.io/local-ai-platform/)
- [Source on GitHub](https://github.com/hankthebldr/local-ai-platform)
- [Releases](https://github.com/hankthebldr/local-ai-platform/releases)
- [CHANGELOG](https://github.com/hankthebldr/local-ai-platform/blob/main/CHANGELOG.md)
- [Docker Hub](https://hub.docker.com/r/hankthebldrr/local-ai-platfrom)
- [GHCR](https://github.com/hankthebldr/local-ai-platform/pkgs/container/enclave)
- [Discussions](https://github.com/hankthebldr/local-ai-platform/discussions)
