# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · SemVer: [semver.org](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
