# Release-Cycle Gaps — Working Items Log

> **Status:** living doc · 2026-05-18 · owner: Henry
>
> **Purpose:** Everything I noticed while auditing the testing + publishing
> pipeline that isn't landed yet. Pick up at the Blackwell workstation and
> burn down item-by-item.

---

## What landed this batch (PR #81 + follow-ups)

| Layer | Deliverable |
|---|---|
| CI | `.github/workflows/docker-publish.yml` — auto Docker Hub push on tag + master, manual dispatch with validated tag input, Trivy scan, secure env-routed inputs |
| Tests | `tests/test_ootb_content.py` — every shipped workflow / agent / role / seed file parses, validates, and references resolvable context |
| Tests | `tests/playwright/test_release_ui_features.py` — 8 regression cases covering Catalog Models, mini-DAG silhouettes, chat persistence, composer description textarea, Clear button, runs progress chip position, brand `::selection`, click-to-add agent, composer chat response shape |
| Scripts | `scripts/publish-dockerhub.sh` — manual build+tag+push (pre-CI fallback) |
| Docker Hub | Image live at `hankthebldrr/local-ai-platfrom:{1.1.1, latest}` |
| Design | `docs/plans/2026-05-18-observability-perf-tracking.md` |
| Design | `docs/plans/2026-05-18-prompt-output-cicd.md` |

## Gaps still open (by category)

### A · CI / publishing

| # | Gap | Severity | Effort |
|---|---|---|---|
| A1 | **`docker-publish.yml` needs secrets** — `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN` must be added in the GitHub repo settings before the workflow can push. Until then it'll fail at the login step. | blocker | 2 min — Settings → Secrets and variables → Actions |
| A2 | **No Playwright suite in CI** — `ci.yml` excludes e2e tests entirely. The 19 Playwright specs (now 20 with `test_release_ui_features.py`) never run on PR. They need a `playwright` job that spins up the stack via `docker compose up -d` then runs `pytest tests/playwright -m e2e`. | high | 4-6 hours |
| A3 | **No coverage gate** — `ci.yml` measures coverage but doesn't enforce. CLAUDE.md cites a 70% bar for 2.0.0. Add `--cov-fail-under=50` now, ramp toward 70. | medium | 30 min |
| A4 | **Release notes are hand-curated** in `release.yml`. Should auto-generate from PR titles between tags (e.g. `release-please` or `git-cliff`). | medium | 2-3 hours |
| A5 | **No image SBOM / signing** — production deployments will eventually need Sigstore / Cosign signatures + an SBOM attached to the published image. | low (now) / high (enterprise) | 1 day |
| A6 | **`docker-publish.yml` builds on `ubuntu-latest`** — that's an x86_64 image only. The Mac M-series operator (you) can't run this image natively without Rosetta. Add `linux/arm64` to a multi-platform `platforms:` list once you have ARM CI runners. | medium | 1 hour (with runners), free with `buildx` cross-build but +30 min build time |
| A7 | **DMG release notes don't link to Docker image** — `release.yml`'s `prerelease` + `stable` body templates should mention `docker pull hankthebldrr/local-ai-platfrom:<version>` so operators know both distribution channels. | low | 5 min |
| A8 | **No "smoke test the published image" job** — after `docker-publish.yml` pushes, nothing pulls + boots the published artifact to verify it actually works. Trivy scans the layers but doesn't run `/health`. | medium | 1 hour |

### B · Tests

| # | Gap | Severity | Effort |
|---|---|---|---|
| B1 | **Eval-suite implementation** — `docs/plans/2026-05-18-prompt-output-cicd.md` defines it; no `scripts/eval-prompts.sh` or `agents/<id>.eval.yaml` files exist yet. Phase 1 is ~2 days. | high | ~6 days total / Phase 1 is ~2 days |
| B2 | **Trace producer** — `docs/plans/2026-05-18-observability-perf-tracking.md` Phase 1 hasn't started. `api/services/tracing.py` doesn't exist. | high | ~5 days total / Phase 1 is ~1 day |
| B3 | **No `Dockerfile` lint** — no `hadolint` job. Catches `COPY` ordering issues, missing `--no-cache-dir`, etc. | low | 15 min |
| B4 | **No Python type-check in CI** — `mypy` or `pyright` would catch the `APIError` import bug I fixed in PR #79 *statically*, before runtime. | medium | 2-3 hours setup, ongoing fix work |
| B5 | **No `ruff` --select F821** — undefined-name bug class (the same family as the APIError NameError). Would prevent that whole regression. | low (easy add) | 10 min |
| B6 | **Hooks test suite (`tests/hooks/`) isn't documented** — 7 files exist but nothing in the repo explains what they cover or when to add a new one. | low | 30 min |
| B7 | **No image-content test** — nothing asserts the BUILT image actually contains `/app/docs/seed/xql/*` (the regression that motivated PR #79's docs/seed COPY fix). Run `docker run --rm <image> ls /app/docs/seed/xql/` in CI. | medium | 30 min |

### C · OOTB content

| # | Gap | Severity | Effort |
|---|---|---|---|
| C1 | **`xsiam-detection-engineering` workflow** — moved to private overlay in commit 997d8f4; 26 zombie failed runs cleaned up. The workflow is mentioned in docs but isn't available in the public repo. Either document the absence prominently or restore a slimmer public version. | medium | 1 hour (write a slim variant) |
| C2 | **No "convert document to artifact" path** — the operator reported an error trying to convert from the Context tab; the actual button is "Convert to Agent" (different feature). Either add a "Convert to Artifact" affordance on doc-search results OR rename labels so expectations match. | low | 1-2 hours |
| C3 | **MODELS.md and `MODEL_REGISTRY` can drift** — there's a sync-reminder hook but no test that asserts equality. | low | 1 hour |
| C4 | **No shipped example data** — `data/projects/<id>/` is empty in fresh installs. A "Welcome to Enclave" project with a few sample Kanban tasks would teach the UI by example. | low | 1 hour |
| C5 | **No starter workflows for common roles** — content / research / data each have ~1 workflow. A "first 10 minutes" path needs a sample workflow per role surface. | medium | 4-8 hours of curation |

### D · Documentation

| # | Gap | Severity | Effort |
|---|---|---|---|
| D1 | **No RELEASE.md** — the release process (cut a tag → release.yml builds DMG → docker-publish.yml pushes image → CHANGELOG entry) isn't documented end-to-end. Operators learn it by reading `.github/workflows/*.yml`. | medium | 1 hour |
| D2 | **No CHANGELOG hygiene gate** — CHANGELOG.md exists but no PR template asks for entries, no CI checks it. | low | 15 min (PR template) |
| D3 | **Architecture docs scattered** — `docs/plans/` has 4 design docs (workflow engine, prompt framework, this one, observability, eval). A `docs/README.md` index would help newcomers. | low | 30 min |
| D4 | **No CONTRIBUTING.md** — onboarding a contributor requires reading CLAUDE.md (which is intentionally Henry-specific). | low | 1 hour |
| D5 | **No SECURITY.md** — Dependabot is finding 88 vulns; we need a public statement on the security stance + how to report issues. | medium | 30 min |

### E · Live-recording artifacts

| # | Gap | Severity | Effort |
|---|---|---|---|
| E1 | **Playwright `signed_in_page` forces dark theme** but the demo recorder script doesn't verify the recording actually came out in dark mode (cosmetic regression risk). Add a frame-color sample check. | low | 30 min |
| E2 | **No "comprehensive demo" output committed** — `playwright-results/videos/*.webm` is gitignored. A reference video URL or a release-attached artifact would help reviewers see what's working. | low | 30 min |
| E3 | **Mouse cursor missing from Playwright recordings** — addressed informally but no implementation. Adding a synthetic cursor overlay (CSS+JS) would make recordings look like real demos. | medium | 2-3 hours |

### F · Performance / observability (overlapping with the design doc)

| # | Gap | Severity | Effort |
|---|---|---|---|
| F1 | **No Ollama model-keep-alive default** — every chat after 5min idle pays the model-load cost again. Setting `OLLAMA_KEEP_ALIVE=24h` in docker-compose would eliminate it. | medium | 5 min |
| F2 | **No per-agent token-cost tracking** — observability doc covers it (B2), but as a quick win, `OllamaService.chat()` could emit a structured log line for every call with prompt_tokens + completion_tokens. | medium | 30 min |
| F3 | **Heartbeat doesn't show model status** — operator can't see at a glance whether a model is loaded vs. paged out. `/health` returns models, but the SPA heartbeat chip just shows green/amber. | low | 1 hour |
| F4 | **No alerting** — if Ollama crashes / OOMs, the API surfaces 503s but nothing pages anyone. A simple webhook on health check failures (Slack, ntfy) would close the loop. | medium (enterprise) | 2-3 hours |

---

## Recommended order on the Blackwell

1. **A1** — add Docker Hub secrets so the new workflow can run (2 min).
2. **A2** — Playwright in CI (the new `test_release_ui_features.py` should run on every PR before it can ever be useful).
3. **B7** — image-content test (cheap, catches the docs/seed regression class).
4. **F1** — OLLAMA_KEEP_ALIVE=24h (5-min win, huge UX impact on the Blackwell with its faster prefill anyway).
5. **B2** (Phase 1) — trace producer (1 day, unlocks debugging on the workstation).
6. **B1** (Phase 1) — eval runner (2 days, gates further prompt churn).

Items A3 + A8 + D1 + D5 are also quick wins (<1 hour each) and worth batching.

---

## Items intentionally out of scope

These came up while auditing but aren't on the critical path; recording so they don't get forgotten:

- **Marketplace publishing** (homebrew tap, Linux package repo, Microsoft Store) — significant work, not blocking for 1.x.
- **Multi-stage Dockerfile** to trim the 5.68 GB image to <2 GB. Big effort, big win, separate PR.
- **Web UI translations** (`i18n`) — Cortex Console is English-only; not on roadmap for 1.x.
- **GPU runtime detection** in the API to surface "CUDA / Metal / CPU only" in /health.

---

*Generated 2026-05-18. Refresh after each release cut.*
