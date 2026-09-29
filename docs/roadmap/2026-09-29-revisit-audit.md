# Revisit audit — 2026-09-29

**HEAD:** `d9efdfe` (`origin/master`) · **Reviewed on:** `review/2026-09-29` · **Method:** structural survey + suite run + four read-only audits (backend, frontend, planned-vs-shipped, hardening). Every finding carries a `file:line` anchor; the two marked **[verified]** were re-read first-hand, the rest are agent-anchored — spot-check before acting.

**BLUF.** The code is healthy — 2,506 tests green, 80% coverage, deps current. The *repo* is stuck: publishing has been frozen since 2026-09-11 by a half-run branch migration, 126 commits sit unreleased behind `__version__ = 1.1.1`, and one unauthenticated route pipes a remote script into `sh`. Fix those three this week; everything else is ordinary debt.

Scoring: `priority = (impact + risk) × (6 − effort)`, each 1–5. Effort: 1 = hours · 2 = a day · 3 = 2–3 days · 4 = 1–2 weeks · 5 = longer.

---

## 1. State

| Surface | Now | Note |
|---|---|---|
| Version | `1.1.1` in `api/__init__.py` | 126 commits since `v1.1.1`; CHANGELOG `[Unreleased]` is 560 lines |
| Trunk | `master` only on remote | `ci.yml` runs on `[dev, main, master]`; **release / docker-publish / pages / wiki-sync run on `dev`/`main` only** → last publish 2026-09-11, #190 (pages) never deployed |
| Suite | 2,506 passed · 46 skipped · 71s · 80% cov | `-m "not rag and not integration and not slow"`, no Ollama |
| CI | tests + lint (non-blocking) + release-readiness | 0 lines of JS execute in CI; coverage measured, not enforced; mypy installed, never run |
| Deps | core+dev resolve to current (2 minor outdated) | `setup/requirements.txt` = Jan-2024 exact pins, still what `install.sh`/`setup_auto.sh`/QUICK_START install; 7 dependabot PRs target it |
| Routers / services | 37 / 98 (all mounted, all referenced) | CLAUDE.md + README say 16 / 22 |
| Frontend | `index.html` 3,541 · `css/app.css` 7,480 · `js/main.js` 13,662 · 36 modules | Stage 1 phase 3 unbuilt; parity gate unsigned; main.js grew ~4.4k after the split |
| Ollama | pin `0.23.4` (compose) · dev Mac runs `0.34.4` · upstream `0.34.3` | MLX is the default Apple-Silicon engine since 0.30 (2026-05) — GGUF models get none of it |
| Repo weight | `.git` 43 MB · 27 MB of tracked `.webm` | `playwright-results/videos/` tracked despite the gap doc saying gitignored |
| Governance | `LICENSE` **missing** (pyproject: "see LICENSE") · no `SECURITY.md` · no `dependabot.yml` · no `docs/README.md` | `RESEARCH.md` flagged LICENSE + version lag on 2026-06-28; unfixed |
| Local checkout | `master` 1 stray commit (`ba38332`, backed up at `backup/ba38332-parity-golden`) · 3 stale worktrees · 5 squash-merged local branches | needs operator cleanup (destructive) |

---

## 2. Tier 0 — unblock (this week)

| # | Task | I | R | E | Pri | Anchor |
|---|---|---|---|---|---|---|
| 0.1 | **Run `scripts/migrate-branches.sh --apply`** from a machine with repo-admin `gh`. Renames `master→main`, creates `dev`, archive-tags + deletes 7 stale branches, strips `master` from `ci.yml`. Until then nothing publishes. | 5 | 5 | 1 | 50 | `scripts/migrate-branches.sh`, `docs/BRANCHING.md` |
| 0.2 | **Gate `/api/setup/*` writes** — `install-ollama` runs `bash -c "curl … ollama.com/install.sh \| sh"` behind base auth only; `/api/setup` has no `SCOPE_MAP` entry, no `require_master_key`. Add master + `_is_local_client`. **[verified]** | 4 | 5 | 1 | 45 | `api/routers/setup.py:158-189`, `api/middleware.py` SCOPE_MAP |
| 0.3 | **Cut the release.** Bump `__version__` → `1.3.0` (both tracks are complete on trunk; 1.2.0 never shipped separately — fold it), promote `[Unreleased]`, update CLAUDE.md "Current" + `footer-version`, merge `dev→main`. `release.yml` tags on the `__version__` read. | 5 | 4 | 2 | 36 | `api/__init__.py:1-16`, `CHANGELOG.md:6-560` |
| 0.4 | **`SCOPE_MAP` sweep** — ungated writes: `/api/workflow-index/import` (writes `workflows/*.yaml` with `?overwrite`, bypasses the `workflows` scope on `/save`), `/api/projects` CRUD+import, `/api/feedback/*`, `/api/graph/rebuild`, `/api/system/architecture/refresh`. Ride nearest sibling: workflow-index/projects→`workflows`, feedback→`exports`, graph→`workspaces`, setup/system→`keys`. | 3 | 4 | 1 | 35 | `api/routers/workflow_index.py:44`, `projects.py:23-75`, `feedback.py:110-224` |
| 0.5 | **Add `LICENSE`.** Packaging and README point at a file that does not exist; source-available with no text is all-rights-reserved. **Decision: which license.** | 3 | 4 | 1 | 35 | `pyproject.toml:11` |
| 0.6 | **Runs-dir env drift** — engine writes `WORKFLOW_DATA_DIR`; reaper + `_should_cancel` hardcode `data/workflows`; SSE bus reads `ENCLAVE_RUNS_DIR`; research/workspace read `ENCLAVE_DATA_DIR`. Setting one silently disables cancel/reap/streaming. One resolver. | 3 | 4 | 1 | 35 | `workflow_engine.py:35,243,332`, `run_event_bus.py:21`, `research_session.py:150` |
| 0.7 | **Bind Ollama to loopback** in compose — `11434:11434` publishes an unauthenticated model server to the LAN, bypassing Enclave. | 2 | 4 | 1 | 30 | `docker-compose.yml:16-17` |
| 0.8 | **Upload cap** — `await file.read()` with no limit. | 2 | 3 | 1 | 25 | `api/routers/documents.py:121-123` |
| 0.9 | **Local cleanup (operator, destructive):** `git worktree remove` ×3 (`.claude/worktrees/*`, all merged), delete `fix/chat-singletons` + the 4 squash-merged locals, reset `master` to `origin/master` (stray golden re-baseline is superseded by #178's; backup branch exists). | 2 | 2 | 1 | 20 | `git worktree list` |

---

## 3. Tier 1 — correctness, perf, dependencies (next two weeks)

| # | Task | I | R | E | Pri | Anchor |
|---|---|---|---|---|---|---|
| 1.1 | **Streaming blocks the event loop.** `async def chat_stream` acquires a `threading.BoundedSemaphore(1)` then iterates `requests.post(stream=True)` with no `await` — a second concurrent chat stalls every endpoint, `/health` included. Move to `httpx.AsyncClient` + `asyncio.Semaphore`, or `to_thread` the iterator. | 5 | 4 | 3 | 27 | `ollama_service.py:58,530-541,692-730` |
| 1.2 | **Retire `setup/requirements.txt`.** 2024 pins (`fastapi==0.109`, `aiohttp==3.9.1`, `python-multipart==0.0.6`, `pypdf==4.3.1` are on the runtime path), `torch 2.1.2` has no 3.12 wheel, `pywebview` pinned twice (pip rejects). Point `install.sh`/`setup_auto.sh`/QUICK_START at `-core`+`-rag`; move ML to `-ml`. Add `defusedxml` to pyproject (`triage/collectors/junit.py:6` imports it → wheel `python -m triage` ImportErrors). `Dockerfile` `3.11-slim` → `3.12-slim` (CI never tests 3.11). Add `.github/dependabot.yml` (pip: `setup/`, root; github-actions; grouped). Close the 7 dependabot PRs as superseded. | 4 | 4 | 2 | 32 | `setup/install.sh:131`, `setup_auto.sh:84`, `Dockerfile:1`, `pyproject.toml:10,117` |
| 1.3 | **Ten more sync calls in async handlers** — `requests.*` in inventory (Ollama), skills (up to 30 sequential GitHub fetches), tasks, setup. Wrap in `asyncio.to_thread`. | 3 | 3 | 1 | 30 | `inventory.py:596,618,788`, `skills.py:608-687`, `tasks.py:320` |
| 1.4 | **HITL self-approval + tier-1 gaps.** `/save`, `/run`, `/runs/{id}/approvals/{gate}` all ride `workflows` — one key authors `kind: code` and approves its own gate; `approval: auto` on tier-1 only warns. Approvals → `require_master_key`; reject `auto` when `isolation_tier == 1`. | 3 | 4 | 2 | 28 | `workflows.py:273,949`, `engine_executors/code.py:45-48`, `sandbox_impl/subprocess.py:38-59` |
| 1.5 | **MCP spawn surface.** `POST /api/mcp/servers` accepts any `command/args/env/cwd`; children get `{**os.environ, …}` → `MASTER_API_KEY` + cloud keys leak into every MCP child; remote catalog is an unpinned `requests.get` whose `command` flows into `register`. Env allowlist (the sandbox already has one), command allowlist or bin-dir, sha256-pin the catalog. | 3 | 4 | 2 | 28 | `mcp_service.py:329-390`, `mcp_runner_pool.py:206-215`, `routers/mcp.py:79-190` |
| 1.6 | **Tar extraction** — only `..`/absolute rejected; no `filter="data"`, symlink/hardlink members not vetted; installed plugins hot-load in-process. Also clears the Py3.14 tarfile deprecation. | 3 | 4 | 1 | 35 | `plugin_service.py:310-316,581-587` |
| 1.7 | **Bump Ollama pin** `0.23.4` → `0.34.x`; re-run `probe_ollama_version` + `apple_unified` against the MLX engine; update `docs/deployment/ollama-version.md`. | 3 | 3 | 2 | 24 | `docker-compose.yml:14`, `architecture.py:534` |
| 1.8 | **`datetime.utcnow()` ×104** → `datetime.now(UTC)` (84 deprecation warnings per run; scheduled removal). | 2 | 3 | 1 | 25 | `grep -rn 'utcnow()' api` |
| 1.9 | **Workspace `edit()` skips `_check_extension`** (write/expand enforce it); `create()` accepts any host root and `mkdir -p`s it. | 2 | 3 | 1 | 25 | `workspace.py:83,207-222,352-371` |
| 1.10 | **Cloud-provider shell** — 5 CRUD routes storing cleartext keys for a proxy "deferred to a follow-up PR"; zero callers, zero tests. Finish or hide the tab and stop persisting keys. | 2 | 3 | 1 | 25 | `cloud_provider_service.py:9-12,151`, `routers/cloud_providers.py:34-78` |
| 1.11 | **Shared `atomic_write_text/json`.** Seven named `_write_atomic` (two pairs byte-identical) + ~22 inline `tmp→replace` copies, none fsync. | 3 | 2 | 2 | 20 | `routers/tasks.py:100`, `patterns.py:96`, `skills.py:849`, `memory_store.py:53` … |
| 1.12 | **Dead / lying config** — `MAX_CONCURRENT_REQUESTS` read, never used; `REQUEST_TIMEOUT` banner says 300, code uses 900; dead `ENABLE_API_AUTH` module constant says `false` while every real gate defaults `true`; `network: allowlist` validates then is forced to `none`; `api_keys.yaml` written with default umask. | 2 | 2 | 1 | 20 | `main.py:66-67`, `middleware.py:24`, `sandbox_impl/container.py:41-50`, `api_key_service.py:61` |
| 1.13 | **Registered stubs** — 8 discovery providers `implemented=False` returning "coming soon"; `OllamaRunner.generate_stream` raises `NotImplementedError` (unreachable only by accident). Drop from registry / implement. | 2 | 2 | 1 | 20 | `discovery_providers/stubs.py`, `runner_impl/ollama.py:140-147` |
| 1.14 | **JSON-RPC frame helpers duplicated** between pool and service. | 1 | 2 | 1 | 15 | `mcp_runner_pool.py:688-724`, `mcp_service.py:435-470` |

---

## 4. Tier 2 — CI, tests, repo hygiene

| # | Task | I | R | E | Pri |
|---|---|---|---|---|---|
| 2.1 | `--cov-fail-under=75` in `ci.yml` (sitting at 80%; the 2.0 bar is 70). Free. | 3 | 3 | 1 | 30 |
| 2.2 | **CI executes zero JS.** Add a job: `uvicorn` without Ollama → `pytest tests/parity tests/playwright/test_parity_runtime.py` + non-slow subset. Without it the parity gate is unenforceable and 42 Playwright specs are decoration. | 4 | 4 | 3 | 24 |
| 2.3 | Make lint blocking: `ruff` (`F821` at minimum), `mypy` on `api/services` subset. B4/B5 from the release-gaps doc. | 3 | 3 | 2 | 24 |
| 2.4 | `git rm` the 27 MB of `.webm`; attach to a release instead; gitignore. History purge is optional (force-push → operator decision). | 2 | 2 | 1 | 20 |
| 2.5 | Governance files: `SECURITY.md`, `docs/README.md` index, fold release steps into `BRANCHING.md` or add `RELEASE.md`; move `ENTERPRISE_DEPLOYMENT_GAPS.md` + `docs/GAP_ANALYSIS.md` (both self-marked superseded) to `docs/historical/`. | 2 | 2 | 1 | 20 |
| 2.6 | **CLAUDE.md / README drift:** auth is default-**on** (CLAUDE.md says off); 37 routers / 98 services; PR #97 merged (not draft); 1.3.0 complete; "chat-led Composer" became a separate Chat tab in #178; `cli/benchmark.py` does not exist; Ollama pin. | 3 | 2 | 1 | 25 |
| 2.7 | CLI drift: `cli/chat.py` talks to `:11434` directly (no auth, semaphore, runner); `cli/eval.py` not in `dispatcher.py` or `[project.scripts]`; v1→v2 schema migrator still ships. | 2 | 1 | 1 | 15 |
| 2.8 | Module seams: `routers/workflows.py` (1,208) → `runs.py` + memory proxies to `memory.py`; `routers/inventory.py` (1,147) is the only router hitting Ollama with raw `requests` — needs a service; `workflow_engine._execute_steps` is one 412-line method, pre-warm trio is a `PreWarmer` class waiting to exist. | 3 | 2 | 3 | 15 |

---

## 5. Tier 3 — unfinished features, by stranded value

| Thread | Status | Missing | E |
|---|---|---|---|
| **Frontend Stage 1 close** (`docs/superpowers/plans/2026-06-28-…`) | Ph 0–2 done; **Ph 3 not; gate unsigned** | (a) re-baseline `window_globals.json` to real consumers — 100–140 of 263 bridges are golden-only; (b) `canvas.js` via a `state` accessor for the 5 reassigned lets (~410 read sites); (c) `shell/boot.js` sequencing 16 `DOMContentLoaded` + 28 IIFEs + 70 `Actions.*` sites; fold 24 `switchTab` handlers into `data-action`. New `df*` feature code keeps landing in `main.js` until (b) lands. | 4 |
| **Stage 2 (Ph 4–10)** | not started, **superseded in parts** | Phase 4 `core/state.js` duplicates the draft/WAL store already at `main.js:7683-8070`; Phase 8 conflicts with the shipped BUILD/OPERATE/LIBRARY/ADMIN IA; the 7 legacy IIFEs *are* the console-v2 features, shipped as `var` blobs. **Rewrite the cards against the current surface before any Ralph loop runs them.** | — |
| **Subsystem C — autonomous research loop** (`specs/2026-06-29`) | 0 of 6 built | `vault_writer.py`, `kind: record`, `max_consecutive_dry` / `max_vault_notes_per_run`, reaper `long_runner`, ralph `_should_cancel`, `autonomous-research.yaml`. Small, fully specced, high value for research runs. | 3 |
| **Fusion C1 UI + C4 seam** (`plans/2026-07-09`) | C1–C3 backend shipped (#178) | no per-run engine/model selector (`wf-runner-controls` is an empty div); HITL only for `kind: code`, not workspace ops; **C4 decision open** (de-facto Option B). | 2 + decision |
| **GPU runner Ph 4–6** (`plans/2026-05-23-gpu-runner`) | Ph 1–3 | `recommended_runner()`, runner-aware `keep_alive`/concurrency, vLLM pre-warm + `VLLM_MANAGED_LIFECYCLE`, validator rules, Memory-tab runner card. Also: re-test vLLM ≥0.24 on SM120 (pinned `v0.17.1` for an NVFP4 regression). | 3 |
| **Provenance M1.2** | M1.0–1.1 | emission at `agent_step`/`memory_fact`/`auto_context`; `/conversation`, `/source`, `/usage`, `/audit/docs`, `DELETE`; retention. | 3 |
| **Eval PR gate** (`plans/2026-05-18-prompt-output-cicd`) | harness + 2 suites | per-agent golden cases, judge, `eval-prompts.yml` CI job, drift baselines. | 3 |
| **Gap-closure Phase 6** | Ph 1–5 | error-reporting opt-in UI (0 hits in JS), audit log is an in-memory `deque(200)`, persistent deployment-config store. | 2 |
| **Enclave Code** (roadmap B, `plans/2026-05-16-enclave-code-spec`) | zero code | the 1.2 thesis's flagship; sandbox + Workspace + ralph make it mostly assembly now. **Go / no-go decision.** | 5 |
| **1.4.x fleet** | not started | `HostRegistration` 0 hits. Do 1.5 (MCP env scrub) and 1.9 first — fleet widens both. | 5 |

---

## 6. New functionality — highest leverage per day

1. **MLX-native Apple-Silicon path.** Ollama ≥0.30 defaults to MLX on Mac (~1.6× prefill, ~2× decode) — but only for MLX-format weights; the 19 GGUF registry entries get nothing. Add MLX variants to `MODEL_REGISTRY`/`MODELS.md`, teach `apple_unified` to report the engine, benchmark on the M4 Pro. E=3.
2. **Per-run engine/model selector** (Fusion C1 UI) — the backend endpoint exists; wire the empty `wf-runner-controls` div. E=2.
3. **Autonomous research loop** (Subsystem C) — six surgical items above. E=3.
4. **`enclave doctor`** (roadmap A5, 0 hits) — venv/Ollama/version-floor/ports/scopes in one command; pairs with 1.2. E=1.
5. **CI e2e job** (2.2) — enabling work for everything frontend. E=3.
6. **Welcome project + starter workflow per role** (release-gaps C4/C5) — first-ten-minutes path. E=2.

---

## 7. Sequence

```
week 1   0.1 migrate ─► 0.2 setup gate ─► 0.4 SCOPE_MAP ─► 0.5 LICENSE ─► 0.3 cut 1.3.0 ─► 0.9 local cleanup
                                          0.6 runs-dir · 0.7 compose port · 0.8 upload cap  (same PR as 0.4)
week 2–3 1.2 deps/dependabot ─► 1.1 async streaming ─► 1.3 to_thread ─► 1.4–1.6 HITL/MCP/tar ─► 2.1/2.3 CI gates
         1.7 Ollama bump + §6.1 MLX (dev box) · 1.8 utcnow · 1.11 atomic helper · 2.6 CLAUDE.md
week 4+  2.2 CI e2e ─► Stage 1 close (a→b→c) ─► rewrite Stage 2 cards ─► Subsystem C ─► C1 UI + C4 decision
```

Every Tier 0/1 row is a `fix(...)` PR into `dev` per `BRANCHING.md`; none touch the frozen engine except 0.6 (path resolution only).

---

## 8. Decisions needed (operator)

| Decision | Options | Default if silent |
|---|---|---|
| License text | PolyForm Noncommercial · BSL 1.1 · Elastic 2.0 · proprietary notice | blocks 0.5 |
| Release number | `1.3.0` (fold 1.2.0) · `1.2.0` then `1.3.0` | `1.3.0` |
| `master` reset + worktree removal | do · keep | do (backup branch exists) |
| Stage 2 | rewrite cards · run as written | rewrite |
| Fusion C4 seam | native (Option B, de facto) · compile-to-LangGraph | native |
| Enclave Code | build · shelve | shelve until Stage 1 closes |
| `.webm` history purge | force-push rewrite · leave history | leave |

---

## 9. What this audit did not cover

- `docs/roadmap/2026-07-12-next-wave-backlog.md` and `docs/design/2026-07-09-master-roadmap-and-audit.md` — the session's permission classifier blocked two read-only `git show` calls on them as "Git Destructive" (false positive). The backlog's per-row done-marks were not cross-checked; Themes A/B are known done from #187/#189.
- Playwright / e2e not run (no stack up); no live Ollama exercised; no visual check of the console.
- `desktop/` DMG pipeline not exercised (release.yml was green on 2026-09-11).
