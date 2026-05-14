# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · SemVer: [semver.org](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed — Docker first-boot (PR #42)
- Ollama healthcheck used `curl`, which isn't in the `ollama/ollama` image,
  so the check failed forever and blocked `depends_on: service_healthy` for
  `api` and `webui`. Replaced with `ollama list`.
- `/static/*` 401'd under default docker auth because `PUBLIC_PATHS` was
  exact-match. Added `PUBLIC_PREFIXES` for `/static/` plus exact entries
  for `/setup.html` and `/favicon.ico`.
- JS escape `won\\'t` inside a template-literal single-quoted string aborted
  parsing of the entire dashboard inline `<script>` block, leaving
  `switchTab` and every handler undefined. Fixed to `won\'t`.

### Fixed — Docker runtime data + RAG + admin gate (PR #43)
- Dockerfile only COPY'd `api/`. The `models/`, `agents/`, `workflows/`, and
  `prompts/` dirs are read at runtime; without them the Models tab 500'd
  (`ModuleNotFoundError`), Agents/Workflows tabs returned empty arrays, and
  the roles router served no templates.
- The image installed `requirements-core.txt` only, leaving `chromadb` and
  `sentence-transformers` absent and the Documents tab returning 503
  (`RAG pipeline unavailable`). Install `requirements-rag.txt` instead.
- `run.sh` now pulls `nomic-embed-text` on first boot alongside the chat
  starter, so the RAG pipeline binds Ollama embeddings on startup instead
  of falling back to the heavy sentence-transformers path at request time.
- `require_master_key` is now a no-op when `ENABLE_API_AUTH=false` (the
  admin gate respects the global auth flag for consistency) and accepts
  keystore keys holding the `keys` scope (the auto-provisioned first-run
  master qualifies — was previously rejected because the function only
  consulted the legacy `MASTER_API_KEY` env var).

### Added — Light theme + UI cleanup (PR #44)
- `:root[data-theme="light"]` token block, header toggle button (☀/☾),
  `Theme` controller persisting choice to `localStorage`, and a synchronous
  `<head>` bootstrap to resolve theme before paint (no flash of wrong
  theme). Initial precedence: localStorage > `prefers-color-scheme` > dark.
- Header subtitle no longer duplicates the footer attribution. The footer
  retains `Enclave vX.Y.Z — by ohno llc`.
- Latent state bug fixed: `AdminMenu.showPanel()` set inline `display:block`
  on admin subtab panels, but `switchTab()` never reset the inline display.
  Once you opened an admin subtab, that panel bled through under every
  operational tab. `switchTab` now mirrors `AdminMenu.showPanel`'s
  symmetric reset.

### Added — Packaging parity (PR #45)
- `scripts/build_mac.sh` now COPYs `agents/`, `workflows/`, `prompts/` into
  the bundled `.app` and installs `requirements-rag.txt` in the bundled
  venv. Without this the shipped DMG had the same broken Documents/Agents/
  Workflows tabs the docker image had pre-#43.
- New `scripts/setup_linux.sh` — distro-detecting bootstrap (Debian /
  Ubuntu / Parrot / Fedora / Arch) for native dev on a Linux host. Picks
  Python ≥3.12, creates `./venv`, installs `requirements-rag.txt`, pulls
  `llama3.2:3b` + `nomic-embed-text` via Ollama if available, smoke-imports
  `api.main` as the final gate. Flags: `--venv-only`, `--no-models`.

### Fixed — v1.1.x hotfix bundle (this PR)
- **Version unification.** Introduced `api/__init__.py:__version__` as the
  single source of truth, wired `api/main.py` to import it (was hardcoded
  to `0.1.0` in four places), and bumped the dashboard footer string from
  `v0.1.0` to `v1.1.0`. `/health`, `/api/info`, `/`, and the OpenAPI
  metadata now all surface the same version that the CHANGELOG and git
  tag record.
- **Keystore + workflow runs persisted.** `docker-compose.yml` now mounts
  the whole `/app/data` dir as a named volume (`local-ai-api-data`), with
  `/app/data/logs` keeping its dedicated log volume via nested-mount
  precedence. Issued API keys, completed workflow runs, and the RAG
  Chroma store all survive `docker compose build` / `--force-recreate`.
- **`/api/documents/query` route alias.** Added a `POST /api/documents/query`
  endpoint that proxies to `/search`. Both spellings now work; `/search`
  remains canonical.

## [1.1.0] — 2026-04-22

### Added — Workflow prompt framework (PR #11)
- Six-hook step lifecycle: `before_step`, `transform_prompt`, `validate_output`,
  `after_step`, `on_failure`, plus a `HookBus` with ordered dispatch,
  short-circuit, and `@register_hook` auto-discovery from `api/hooks/`.
- `PromptComposer` with 5-part Jinja templating and a seed role library.
- Six built-in hooks: `json_schema`, `refusal_detector`, `token_budget`,
  `output_logger`, `few_shot_injector`, `retry_with_feedback` (with optional
  model escalation on retry).
- Six model-family adapters (dolphin, llama3, mistral, qwen, yi, uncensored)
  over a `ModelAdapter` base + registry.
- `StepExecutor` rewritten around the 6-hook lifecycle; `WorkflowEngine`
  wires a per-step `HookBus` and `PromptComposer`.
- `workflows upgrade` CLI: converts v1 YAML to v2 schema.
- Extended workflow models with v2 fields (`StepPrompt`, `HookSpec`,
  `schema_version`, `context`, I/O `schemas`).
- Integration test fleet: happy-path pipeline, retry-with-feedback recovery,
  token-budget truncation semantics, v1 legacy regression, custom-hook
  auto-discovery, model-escalation surfacing, E2E smoke (skipped without live
  Ollama), `FakeOllamaClient` fixture.

### Added — Context & memory graph
- Context models for conversation tracking and facts.
- `MemoryService` with YAML persistence for sessions and facts.
- Per-conversation `ContextStore`.
- `SessionManager` with explicit close and auto-cleanup.
- `/context` and `/memory` routers (full CRUD).
- Tool-executor and chat-router wiring for automatic context capture.
- Dashboard "Memory" tab (sessions, facts, stats).

### Added — Profiles & sandbox
- `ProfileService` for YAML-declared agent permissions; seeded built-ins
  (`default`, `research`, `unrestricted`).
- `SandboxedFS` per-conversation filesystem boundary, auto-injected into
  tools that declare a `__sandbox` param.
- Profile enforcement in the tool executor; profile + sandbox wired into
  the chat router and `SessionManager`.
- `/profiles` router with list / detail / reload endpoints.
- Dashboard "Profiles" section (with reload).

### Added — RAG pipeline
- `Chunker` wrapping LangChain `RecursiveCharacterTextSplitter`.
- `EmbeddingService` with pluggable backend (Ollama or
  `sentence-transformers`).
- `DocumentService`: upload → parse → chunk → embed → store.
- `RAGService`: retrieval and context formatting.
- `/documents` router: upload, list, delete, stats, search.
- Auto-retrieval wired into the chat router with profile gating.
- `rag__search` plugin tool and profile integration.
- Dashboard "Documents" tab (upload, list, search preview).
- `pypdf` added for PDF parsing.

### Added — Packaging
- Enclave icon bundled into the macOS DMG.

### Fixed
- Workflow retry no longer accumulates feedback across attempts
  (`prompt.user` / `prompt.system` reset per retry).
- Path traversal rejected in `role_ref` and few-shot `step_id` inputs.
- `escalate_to` now actually switches models on retry (wired through
  `model_resolver`).
- CI: `jinja2` and `jsonschema` added to `requirements-core.txt` so CI
  dependencies match runtime.
- CI: RAG tests skipped cleanly when LangChain isn't installed.

### Security
- `.gitignore` tightened for runtime secrets and user data.
- DMG build no longer packages local secrets or user state.

### Changed
- `CLAUDE.md` baseline corrected to reflect the 1.0.0 surface: populated
  routers/services, auth middleware, streaming, RAG, tests, Docker, CI.
  Removed stale "0% coverage" / "empty skeletons" / "1.0.0 reserved" claims
  and reshaped the roadmap around `1.x` / `2.0.0`.
- `.claude/worktrees` and `.worktrees` added to `.gitignore`.
- Runtime `data/logs/*.jsonl` (from `output_logger` hook) added to
  `.gitignore`.

## [1.0.0] — 2026-04-18

Initial public release of Enclave.
See the [v1.0.0 release](https://github.com/hankthebldr/local-ai-platform/releases/tag/v1.0.0)
for details.

[Unreleased]: https://github.com/hankthebldr/local-ai-platform/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/hankthebldr/local-ai-platform/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/hankthebldr/local-ai-platform/releases/tag/v1.0.0
