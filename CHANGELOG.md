# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · SemVer: [semver.org](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.1] — 2026-05-15

### Added — Cortex Console rebrand (PR #57)
- Web console re-skinned to the PANW Cortex product family aesthetic
  (XSIAM / XDR / XSOAR). Slate-navy canvas, Cortex Green primary, cool-blue
  secondary, PANW orange reserved for the co-brand chip and critical alerts.
- Two-row Cortex command bar: brand-mark + health pip, env chip, clock /
  uptime, theme toggle, caps-tracked breadcrumb (Cortex › Mode › Context).
- Tabs regrouped into operator phases — BUILD (Composer · Workflow Index ·
  Agents · Skill Lab) / OPERATE (Runs) / LIBRARY (Models · Context · Memory)
  / ADMIN. All `data-tab` IDs preserved so `switchTab()` routing stays
  back-compatible.
- New status rail at the bottom: env+project / live model + queue + last run
  / version + co-brand. New element IDs (`rail-env`, `rail-project`,
  `rail-model`, `rail-queue`, `rail-last-run`, `rail-run-pip`) ready for the
  follow-up JS wiring; chrome works standalone with placeholders today.
- Engineered 32px grid + soft radial undertone replaces the bloom-style
  ambient. Reads as operator console, not dark-UI demo.

### Added — OOTB XQL/XDM bundle (PR #56)
- Five new workflows under [workflows/](workflows/): `data-model-rules`,
  `xsiam-data-model-rules`, `xdm-rule-from-log`, `xdm-bulk-onboarding`,
  `xsiam-normalization-pipeline`. End-to-end pipelines for authoring,
  validating, and onboarding Cortex XSIAM data model rules from raw vendor
  logs.
- Three new agents under [agents/](agents/): `xsiam-analyst`,
  `xql-data-model-engineer`, `xdm-schema-navigator`.
- New `xdm-toolkit` plugin under [plugins/xdm-toolkit/](plugins/xdm-toolkit/)
  with two callable tools (`validate_xql` static rule validator,
  `lookup_xdm_path` XDM path resolver) and two skills (rule-writer,
  validator) that auto-inject on XQL/XDM keyword triggers.
- Knowledge seed under [docs/seed/xql/](docs/seed/xql/) — Modelfile +
  Markdown knowledge for offline XQL operators.
- Sample data under [workflows/mock_data/](workflows/mock_data/) — Okta
  system log, PAN-OS traffic, Windows Security XML for fixture-style runs.

### Added — Documents drop-zone + Cloud Models registry (PR #55)
- Composer Documents pane accepts drag-drop PDFs and text files; routes
  through the existing RAG pipeline (Chroma + nomic-embed-text) without a
  separate upload page. Per-document delete + reindex.
- Admin → Cloud Models tab. UI to register external OpenAI-compatible
  providers (OpenAI, Anthropic, Together, OpenRouter, custom endpoint),
  store API keys on the host in `data/config/cloud_providers.json`
  (chmod 0600), and use them as workflow steps. The dashboard never echoes
  keys back; rotate / revoke is one click.
- "Discover" surface folded into Models — single page lists installed
  models, pullable models from the registry, and configured cloud
  providers in one operator view.

### Added — Composer canvas + admin tabs (PR #54)
- Composer canvas now supports zoom (button + scroll-wheel) and fullscreen.
  Pan-and-zoom transform is preserved across tab switches.
- New Admin → Skills tab — list, enable / disable, and preview the skill
  body of every skill discovered across installed plugins.
- `plugins/` directory now shipped in the docker image (was missing pre-#54,
  so the Plugins admin panel was empty in container deployments).

### Added — Composer system-model picker, Agents palette, Project modal (PR #53)
- Step inspector now exposes a system-model picker that overrides the
  workflow-level default for a single step. Picker enumerates installed
  models plus registered cloud providers.
- Agents palette on the composer: drag an existing agent (YAML-defined
  persona) onto the canvas as a step. The agent's pinned model and context
  sources travel with it.
- Step-engage chat: click a step on the canvas to open an inline chat that
  uses that step's exact system prompt + model. Lets operators iterate on
  step prompts without committing them.
- Project modal: cluster multiple workflows, documents, and runs under a
  named project. Project bar pinned in the header.

### Added — UI structural test fleet (PR #52)
- 47-test `pytest` fleet under [tests/ui/test_static_markup.py](tests/ui/test_static_markup.py)
  asserting structural invariants of the dashboard HTML (composer canvas,
  palette, admin panels, API keys UI, exports, plugin tool tester,
  self-hosted vendor libraries — no CDN). Catches regressions without
  needing a running stack; runs in <1 s.

### Added — Agent reliability (PR #48 + PR #50)
- Agents with a pinned model now fall back to role-based resolution when
  the pinned model isn't installed locally, instead of failing the chat.
  The dashboard surfaces a `model_fallback` banner in agent chat so the
  operator sees which model actually responded.

### Engine — plugin tool invocation + validator hardening
- New built-in hook `plugin_tool_invoker` at
  [api/hooks/builtins/plugin_tool_invoker.py](api/hooks/builtins/plugin_tool_invoker.py).
  Configurable via YAML `before_step` block — invokes any plugin tool with
  resolved workflow inputs and stores the result in step workspace.
  Supports `for_each` iteration with `param_template` substitution
  (e.g. `{{ item.rule }}`) for batch tool calls. Idempotent across the
  pre-compose / post-compose dispatch passes.
- `WorkflowEngine.validate()` now recognizes hook-provided virtual inputs:
  for every `before_step` hook with a `store_as` key, the resulting
  `<step_id>.<store_as>` is treated as a valid producer when checking the
  step's own `inputs:` list. Closes the structural hole that made the OOTB
  XQL workflows un-runnable.
- `StepExecutor.execute()` rewritten — `before_step` now dispatches BEFORE
  input resolution and prompt composition (so hooks like
  `plugin_tool_invoker` can populate workspace keys the step then reads).
  Re-dispatched once on attempt 0 post-compose to preserve `token_budget`
  semantics. All before_step hooks must be idempotent.
- `ModelResolver.ROLE_PATTERNS` updated: `qwen2.5-coder` is explicitly
  preferred for `coding` and `reasoning` roles ahead of the older
  `qwen3.5` / `deepseek-r1` patterns. Workflows declaring `role: coding`
  or `role: reasoning` now pick up an installed qwen2.5-coder build
  declaratively, not by accident via the "largest available" fallback.

### Fixed — OOTB workflow runtime parity
- `workflows/xdm-rule-from-log.yaml`: `before_step` hook renamed from
  the non-existent `invoke_validate_xql` to the new `plugin_tool_invoker`
  built-in. The `refuse_if_blockers` `validate_output` hook (also not
  implemented) is commented out with a forward-looking TODO; the workflow
  still emits its verdict line from the prompt side.
- `workflows/xdm-bulk-onboarding.yaml`: same hook rename. Added an
  `output_schema` to the `write_rules` step (`{rules: [{cluster_id,
  dataset, rule}]}`) so `JsonSchemaHook` parses the response into a real
  list — without this, `validate_all` saw a stringified blob and
  `plugin_tool_invoker for_each` correctly refused to iterate.

### Fixed — Docker first-boot (PR #42)
- Ollama healthcheck used `curl`, which isn't in the `ollama/ollama` image,
  so the check failed forever and blocked `depends_on: service_healthy` for
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
- Header subtitle no longer duplicates the footer attribution.
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

### Fixed — v1.1.x hotfix bundle
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
