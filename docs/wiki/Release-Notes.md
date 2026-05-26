# Release Notes

This page tracks every shipped release. The source of truth is [CHANGELOG.md](https://github.com/hankthebldr/local-ai-platform/blob/master/CHANGELOG.md) in the repo — this page is a summary with links.

## Unreleased — earmarked for v1.3.0

The defining release for **architecture-aware orchestration**. The workflow engine now understands the host it's running on and adapts dispatch to it.

### Headline

- **Phase 1** — `Architecture` + `Deployment` protocols, detection at startup, Ollama version floor pinned at 0.23.4 ([PR #88](https://github.com/hankthebldr/local-ai-platform/pull/88)).
- **Phase 2** — Per-step Ollama timings + arch pressure snapshot at `/api/system/architecture` and `/api/system/pressure` ([PR #90](https://github.com/hankthebldr/local-ai-platform/pull/90)).
- **Phase 3** — Four-tier `keep_alive` resolver with arch-detected defaults: `30m` on CPU, `0` on single-GPU NVIDIA, `5m` unknown ([PR #91](https://github.com/hankthebldr/local-ai-platform/pull/91)).
- **Phase 4a** — Scheduler facade + feasibility validation + preview endpoint.
- **Phase 4b** — Tick-based parallel DAG dispatcher. State mutations under a single lock; `OllamaService._LLM_SEMAPHORE` keeps actual model calls serialized.
- **Phase 5** — Composite step kinds (`kind: parallel`, `kind: loop`, `kind: a2a`), pre-warm hit/miss in the Runs view, page-cache awareness on unified architecture.
- **Phase 6** — Per-arch × per-deployment config validator, `gpu_affinity` placement hints on multi-GPU.

### Release engineering

- Python wheel + sdist (`enclave-<version>-py3-none-any.whl`) attached to every release.
- Docker Hub image mirrored to GHCR (`ghcr.io/hankthebldr/enclave`).
- Linux source tarball with SHA-256 + SHA-512 sidecars.
- n8n release-update workflow (`workflows/n8n/enclave-release-update.json`) drives changelog drafting through local Ollama.
- Wiki seed (this page is part of it).

### Skipped versions

`1.1.1` and `1.2.x` were prepared in CHANGELOG / docs but never cut as git tags. All of their work shipped together as 1.3.0. Pin to `v1.3.0` or later; earlier intermediate versions are not pullable.

[Full CHANGELOG entry →](https://github.com/hankthebldr/local-ai-platform/blob/master/CHANGELOG.md)

---

## v1.1.0 — 2026-04-22

Multi-agent workflow engine maturity, model registry expansion, plugin framework.

[CHANGELOG →](https://github.com/hankthebldr/local-ai-platform/blob/master/CHANGELOG.md#110--2026-04-22)

---

## v1.0.0 — 2026-04-18

First public release. Core inference stack, OpenAI-compatible API, 18-model registry, 16 routers / 22 services, multi-agent workflow engine, RAG pipeline.

[CHANGELOG →](https://github.com/hankthebldr/local-ai-platform/blob/master/CHANGELOG.md#100--2026-04-18)

---

## How releases happen

1. PR merges to `master` → CI runs → rolling `nightly` pre-release replaced with a fresh smoke-tested DMG.
2. A `vX.Y.Z` tag pushed to `master` → all build jobs run in parallel → a single `publish` job attaches DMG + wheel + sdist + Linux tarball + checksums to a GitHub Release.
3. The Docker Hub + GHCR images are published by a separate `docker-publish.yml` workflow on the same tag.
4. Pages site re-renders with the new version string.
5. Wiki sync workflow pushes the current `docs/wiki/` to the Wiki repo.

See [Deployment](Deployment) for how to pull each artifact.
