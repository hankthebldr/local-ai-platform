# Enclave Code — Models, MCP, Skills & Context

**Companion to:** `2026-05-16-enclave-code-spec.md`
**Date:** 2026-05-16

What to add to the existing platform to support Enclave Code. Concrete, sized for our
fleet (Mac M4 Pro 48GB / MS-01 64GB / BD790i 96GB) and the conventions already in the
repo (`MODEL_REGISTRY` in `models/download.py`, `agents/*.yaml` for personas,
`plugins/*/skills/*.md` for behavioral skills, `MCPService` for MCP registrations).

## 1. Models

Three roles from the spec → three model tiers. Plus embeddings for code RAG.

### Coding role (workhorse) — `code.apply_patch`, `code.write`

| Model | Size (Q4_K_M) | Tier | Why |
|-------|---------------|------|-----|
| `qwen2.5-coder:32b` | ~20 GB | **primary** (MS-01/BD790i) | Best open coder + tool use that fits 24 GB RAM with context. Default for `--role coding`. |
| `qwen2.5-coder:14b` | ~9 GB | Mac M4 Pro default | The only credible coder model that fits the dev laptop tier. |
| `qwen2.5-coder:7b` | ~5 GB | fast-iteration / preview | For `--fast` mode and CI eval runs. |
| `deepseek-coder-v2:16b` | ~9 GB (MoE) | alternative | Lite-MoE, strong on tool-call format; pin as the fallback if Qwen toolcalls regress. |
| `huihui_ai/qwen2.5-coder-abliterate:7b` | ~5 GB | uncensored variant | Already in our catalog (MODELS.md). For users who want the uncensored coder. |

### Reasoning role (planner / verifier)

| Model | Size | Tier | Why |
|-------|------|------|-----|
| `qwen2.5:14b` | ~9 GB | **default planner/verifier** | Fast (~25 t/s CPU), reliable JSON output, supports tools via the existing Qwen adapter. |
| `qwen2.5:32b` | ~20 GB | heavyweight planner | When the task is architecturally complex; opt-in via `--plan-model`. |
| `deepseek-r1:14b` | ~9 GB | reasoning-heavy alternative | For hard plans where chain-of-thought matters. Already in our catalog. |
| `llama3.2:3b` | ~2 GB | tight-RAM fallback | Used by the dashboard's "starter model" path; reuse as planner-of-last-resort. |

### Embedding role (code RAG)

| Model | Size | Why |
|-------|------|-----|
| `nomic-embed-text:latest` | ~270 MB | **default**. 768-dim, 8K context, runs on all three boxes. Already widely used with Ollama. |
| `bge-m3` | ~570 MB | upgrade path: 8K context, cross-lingual, dense+sparse retrieval. Add when code-snippets-in-multiple-languages becomes a pain point. |

### Adapter additions

`api/services/model_adapters.py` already has a `QwenAdapter` (sets `format: json`,
temperature floor 0.2). For coder models:

- **Confirm Qwen adapter applies to `qwen2.5-coder`.** The regex `qwen` matches it
  today — leave alone unless eval shows the coder variant needs different params.
- **Add `DeepseekCoderAdapter`** if we ship deepseek-coder-v2 as a default option —
  v2's tool-call format differs subtly from v1. Easy to add (~20 LOC).

### Registry diff

```diff
# models/download.py — MODEL_REGISTRY adds
+ "qwen2.5-coder:32b":   { tier: 3, role: coding,    ram_gb: 24, default_for: ["MS-01","BD790i"] }
+ "qwen2.5-coder:14b":   { tier: 2, role: coding,    ram_gb: 12, default_for: ["Mac M4 Pro"] }
+ "qwen2.5-coder:7b":    { tier: 1, role: coding,    ram_gb: 6,  default_for: [] }
+ "deepseek-coder-v2:16b":{tier: 2, role: coding,    ram_gb: 10, default_for: [] }
+ "nomic-embed-text":    { tier: 1, role: embedding, ram_gb: 1 }
```

(Plus the `MODELS.md` sync — the existing hook will remind us.)

## 2. MCP servers

We have `MCPService` (stdio + HTTP transports, JSON-RPC, persisted catalog). What's
missing is *which* MCPs we ship pre-registered or recommend in the docs. None of these
are *required* for Enclave Code to work — the built-in `code` plugin covers the core
loop — but each closes a real gap.

### Recommended (ship pre-registered, disabled by default)

| MCP | Transport | Why for Enclave Code |
|-----|-----------|----------------------|
| **git-mcp** (read-only) | stdio | The agent's planner needs `git log`, `git blame`, `git show` against history. Built-in `code.git_status` is enough for the inner loop; the planner benefits from richer history. |
| **github-mcp** (official) | stdio | When the task references a PR/issue. Auth-gated, optional. Closes the "fix the bug in issue #123" loop. |
| **sequential-thinking** (Anthropic) | stdio | Local models plan worse than frontier models. A scratchpad MCP that forces "think → revise → conclude" measurably helps `qwen2.5:14b` as a planner. |
| **context7** (or equivalent docs MCP) | http | Fetches up-to-date library docs on demand. Critical because local coder models have a stale knowledge cutoff and hallucinate APIs. |
| **playwright-mcp** | stdio | The verifier runs UI smoke tests for frontend tasks. Optional; enable per-project. |

### Recommended (off by default, easy to enable)

| MCP | Why |
|-----|-----|
| **sentry-mcp** | "Read the error from Sentry → propose fix" workflow. |
| **postgres-mcp** (or sqlite/mysql equivalents) | Schema introspection for ORM and migration tasks. |
| **memory-mcp** (official) | Cross-session memory. We have `memory_service.py` internally; the official MCP makes this *interoperable* with non-Enclave clients. |

### Explicitly not in M1

- **Filesystem MCP** — redundant with our `code.read`/`code.write`. Adding it would
  bypass our sandbox profile checks. If a user wants FS via MCP, they can register it
  manually and accept the risk.
- **Shell MCP** — same reasoning. `code.bash` enforces the allowlist; an MCP shell
  doesn't.

### Configuration

Pre-registrations go in `data/config/mcp_servers.json` as `disabled: true` entries the
user toggles on. The setup wizard offers a one-click "enable github + context7" path.

## 3. Skills

In this repo, "skills" = markdown files in `plugins/*/skills/*.md` with `inject:
system` front-matter (see `plugins/example-web-search/skills/search-expert.md`).
They're system-prompt fragments injected when the plugin is active.

For Enclave Code, ship a `plugins/code/skills/` folder. These are *not* tools — they
are behavioral nudges that compose with the agent persona.

### Required (M1)

| Skill file | What it injects |
|------------|-----------------|
| `read-before-edit.md` | "Before editing a file, read it. Before reading a whole file, use `code.search` for the relevant region." |
| `diff-driven-edits.md` | "Prefer `code.apply_patch` (atomic, smaller diffs) over `code.write` (overwrite). Keep patches narrow — one logical change per patch." |
| `match-existing-style.md` | "Before writing code, look for `.editorconfig`, `pyproject.toml`, `.eslintrc`, `tsconfig.json`, `rustfmt.toml`. Match the project's conventions (indent, quote style, line length, import order). Do not introduce a new style." |
| `test-first-when-fixing-bugs.md` | "When fixing a bug, first write or extend a failing test that reproduces it. Run the test, see it fail, then edit the implementation." |
| `dont-disable-tests.md` | "Never delete, skip, or weaken a test to make a build pass. If a test is wrong, explain why before touching it." |
| `stop-when-stuck.md` | "If you've tried three approaches and none work, stop and summarize what you tried. Ask the user before continuing." |
| `safe-bash.md` | "Never run destructive shell commands (`rm -rf`, `git reset --hard`, `git push --force`, `dd`) without an explicit user instruction in this turn. Read-only inspection (`ls`, `cat`, `git diff`) is fine." |
| `secrets-untouchable.md` | "Do not read, echo, or commit `.env`, `secrets/`, `*.pem`, `id_*`, `*.key`. If a task requires secrets, tell the user and stop." |
| `commit-message-hygiene.md` | "Commit messages: one-line subject (≤72 chars), imperative mood, optional body explaining the *why*. Reference issues only when present in context." |

### Per-language packs (M2)

Same skill shape, scoped to a language. Active when the worktree has the relevant
manifest:

- `python.md` (active on `pyproject.toml` / `setup.py`) — "Type hint new public APIs.
  Use `pathlib` over `os.path`. Match the project's formatter — `black`, `ruff`,
  `autopep8` — by reading config."
- `typescript.md` (active on `package.json` + `tsconfig.json`) — "Prefer narrow types
  over `any`. Match the project's import style (relative vs. alias)."
- `rust.md` (active on `Cargo.toml`) — "Prefer `?` over `unwrap()`. Match the
  project's error type."
- `go.md` (active on `go.mod`) — "Prefer table-driven tests. Match the project's
  error-wrapping conventions."

Active-when logic is just a glob check in the plugin manifest; skills system already
supports per-context activation via the plugin loader.

### Skill activation profile

`code-default` activates all required skills. `--profile readonly` activates
read-before-edit + safe-bash + secrets-untouchable only. `--profile auto-accept` adds
no extra skills — risk shifts to the user.

## 4. Context

Two flavors: per-agent context blocks (file-injected at start of session, like
`agents/xsiam-analyst.yaml`) and RAG indexes (queried by the planner via tools).

### Auto-injected context (every session)

Computed on session start by `code_session.py` and prepended to the planner's system
prompt (NOT every step — keeps context tight):

| Context | Source | Size budget |
|---------|--------|------------|
| **Repo identity** | repo root path, current branch, last 5 commit subjects | ~200 tokens |
| **Project manifest** | `pyproject.toml` / `package.json` / `Cargo.toml` / `go.mod` (whichever exists, truncated) | ~500 tokens |
| **Agent guidance** | `CLAUDE.md`, `AGENTS.md`, or `.enclave/AGENTS.md` if present | ~2000 tokens |
| **File tree** | output of `tree -L 3 -I node_modules` (or equivalent), truncated to ~300 lines | ~1500 tokens |
| **Test command hint** | parsed from manifest: `pytest`, `npm test`, `cargo test`, `go test ./...` | ~50 tokens |

Total budget: ~4–5K tokens injected once per session. Cheap on local models.

### RAG indexes (queried via `code.search_index`)

A new tool that wraps `rag_service.py`. Three indexes, built lazily on first query:

| Index | Built from | Updated | Use case |
|-------|-----------|---------|----------|
| **`repo-code`** | All source files in the worktree, chunked by AST when possible (tree-sitter), else by 200-line windows. | On session start; incremental on `code.write` | Planner: "find where authentication is handled" without reading 40 files. |
| **`repo-history`** | `git log` of the last 1000 commits — subject + body + diff stat. | On session start; reuse if branch unchanged | Planner: "has this been fixed before? what did we try?" |
| **`repo-docs`** | All `*.md` files + docstrings extracted from source. | On session start | Planner: "what does the project say about how X works?" |

Storage: `~/.enclave/sessions/<id>/rag/` (Chroma local). Indexes are session-scoped,
not global — keeps disk under control and avoids stale indexes across branches.

### Library docs (lazy, on-demand)

Not pre-indexed. Fetched via the **context7 MCP** when the planner asks. Caches in
`~/.enclave/cache/docs/<package>/`. Manual prebuild: `enclave code docs cache
fastapi pydantic` for offline air-gapped use.

### Memory (cross-session, opt-in)

The existing `memory_service.py` already stores key-value records. For Enclave Code,
record:

- **User preferences** inferred from corrections: "user prefers single quotes",
  "user dislikes f-strings inside f-strings".
- **Repo facts** the agent had to discover: "the test runner is `make test` not
  `pytest`", "this repo uses `uv` not `pip`".
- **Past failures** at the session level: "tried Y, didn't work because Z".

Scope: per-repo (key = `repo_root + path_fingerprint`). The user can clear with
`enclave code memory clear`. Off by default — opt in to avoid surprise.

## Cross-cutting: what we explicitly defer

| Want                                    | Why deferred from M1                                 |
|-----------------------------------------|------------------------------------------------------|
| Tree-sitter AST chunking for RAG        | Big dependency; window chunking is good enough for M1 |
| Cross-repo / monorepo workspace context | Out of scope per the spec's non-goals                |
| Fine-tuned coder model for our use case | We *select* models in v1, not train                  |
| Long-context summarization              | Open question in the spec — pick a strategy in M2    |
| Skill auto-discovery (LLM picks skills) | Static activation by profile is fine for M1          |

## Summary — what to add, in priority order

1. **Models:** `qwen2.5-coder:32b`, `qwen2.5-coder:14b`, `qwen2.5:14b`,
   `nomic-embed-text`. Optional: `deepseek-coder-v2:16b`, `qwen2.5-coder:7b`.
   **+5 entries** in `MODEL_REGISTRY` (+ `MODELS.md` sync).
2. **MCP:** pre-register `git-mcp`, `github-mcp`, `sequential-thinking`, `context7`
   as disabled. Setup wizard enables `github + context7` with one click.
3. **Skills:** ship 9 required skills in `plugins/code/skills/`. Add 4 language packs
   in M2.
4. **Context:** auto-injected project context (~5K tokens), three lazy RAG indexes
   (`repo-code`, `repo-history`, `repo-docs`), library docs via context7, opt-in
   memory.

This is roughly **+10 files of code/yaml, +9 skill markdowns, +5 registry entries,
+4 pre-registered MCPs**. No engine changes; everything composes on top of the M1
infrastructure already specified.
