# Enclave Code — Context & Skill Build-out

**Companion to:** `2026-05-16-enclave-code-additions.md`
**Date:** 2026-05-16

The previous doc said *what* to add. This one is the work tree: file-by-file
breakdown for skills + context, in dependency order, with LOC sketches and the
minimal loader changes required.

## Plugin loader — what's already there

From `api/services/plugin_service.py`:

- `plugin.yaml` declares `skills: [{id, file, triggers}]`.
- Markdown frontmatter supports `name`, `description`, `inject: system`.
- `get_skills(user_message)` does keyword trigger matching against the user turn.
- Path traversal is blocked.

**Gap for Enclave Code:** triggers are message-keyword-based. A coder agent runs in a
loop; we want skills active for the whole session, not gated on the user happening
to say a keyword. Two ways to handle this:

| Option | Change | Effort |
|--------|--------|--------|
| **A. Always-on skill flag** in plugin.yaml: `triggers: ["*"]` | Extend `get_skills` to treat `*` as match-all. ~5 LOC. | Trivial |
| **B. Inject by profile** — profile selects which skills | Plumb profile_id into `get_skills`, filter by allowlist. ~20 LOC. | Small |

Recommend **A for M1** (universal: all 9 skills always active in the `code` plugin),
**B for M2** when language packs ship and we need per-context activation.

## Skill build tree

### Directory shape

```
plugins/code/
  ├── plugin.yaml                  # manifest: 7 tools + 9 skills
  ├── tools/                       # (covered in the spec — not this doc)
  │   ├── read.py
  │   ├── write.py
  │   ├── ...
  └── skills/
      ├── read-before-edit.md
      ├── diff-driven-edits.md
      ├── match-existing-style.md
      ├── test-first-when-fixing-bugs.md
      ├── dont-disable-tests.md
      ├── stop-when-stuck.md
      ├── safe-bash.md
      ├── secrets-untouchable.md
      └── commit-message-hygiene.md
```

### Per-skill: file + body sketch

Every skill follows the same frontmatter pattern as
`plugins/example-web-search/skills/search-expert.md`. Bodies are ~50–150 words.

#### `read-before-edit.md`

```yaml
---
name: Read Before Edit
description: Force the agent to read a file before modifying it.
inject: system
---
```
Body:
> Before editing any file, read it first with `code.read`. Before reading a whole
> file, narrow the region using `code.search` (ripgrep). Do not propose edits to a
> file you have not read in this session — your model's training data is stale and
> the file may have changed.

#### `diff-driven-edits.md`

```yaml
---
name: Diff-Driven Edits
description: Prefer apply_patch over whole-file writes.
inject: system
---
```
Body:
> Use `code.apply_patch` (unified diff) for all edits. Reserve `code.write` for new
> files only. Keep patches narrow: one logical change per patch. If you must touch
> three unrelated lines, emit three patches, not one.

#### `match-existing-style.md`

Body:
> Before writing code, look for `.editorconfig`, `pyproject.toml` (`[tool.black]`,
> `[tool.ruff]`), `.eslintrc`, `tsconfig.json`, `rustfmt.toml`, `.prettierrc`. Match
> the project's conventions (indent width, quote style, line length, import order,
> trailing commas). Do not introduce a new style.

#### `test-first-when-fixing-bugs.md`

Body:
> When fixing a bug: (1) locate or write a test that reproduces the failure,
> (2) run the test with `code.bash` and confirm it fails, (3) edit the
> implementation, (4) re-run the test, (5) re-run the broader test file to catch
> regressions.

#### `dont-disable-tests.md`

Body:
> Never delete, skip, or weaken a test to make a build pass. Do not change a
> test's expected value to match wrong output. If a test is genuinely incorrect,
> stop and explain why before touching it — the user decides.

#### `stop-when-stuck.md`

Body:
> If you have tried three distinct approaches and none work, stop. Summarize what
> you tried, what failed, and what you would try next. Do not loop. Do not try
> a fourth speculative approach.

#### `safe-bash.md`

Body:
> Destructive shell commands require an explicit user instruction this turn. The
> forbidden default list: `rm -rf`, `git reset --hard`, `git push --force` /
> `--force-with-lease`, `git checkout --`, `dd`, `mkfs`, anything piping to `sh`
> or `bash` from a network source. Read-only inspection (`ls`, `cat`, `git diff`,
> `git log`, `pwd`) is always fine.

#### `secrets-untouchable.md`

Body:
> Do not read, echo, log, or commit: `.env`, `.env.*`, `secrets/`, `*.pem`,
> `id_rsa*`, `id_ed25519*`, `*.key`, `*.p12`. If a task requires a secret, tell
> the user the path involved and stop — do not attempt workarounds.

#### `commit-message-hygiene.md`

Body:
> Commit messages: one-line subject, imperative mood, ≤72 chars. Optional body
> after a blank line explaining the *why*, not the *what*. Reference issues only
> when present in this session's context. No emoji unless the repo's own history
> uses them.

### Skill build tasks (ordered)

| # | Task | Effort | Depends on |
|---|------|--------|------------|
| S1 | Extend `plugin_service.get_skills` to treat `triggers: ["*"]` as match-all | 30 min | — |
| S2 | Write the 9 skill markdown files | 2 hours | S1 |
| S3 | Add `plugins/code/plugin.yaml` listing the skills + their `triggers: ["*"]` | 30 min | S2 |
| S4 | Add a smoke test: load the code plugin, assert all 9 skills inject into a session's system prompt | 1 hour | S3 |
| S5 | Eval pass: run the M1 SWE-bench Lite subset twice, once with skills on, once off. Record any quality delta | 1 day (mostly compute) | S3, eval harness from spec |

**Skill build subtotal:** ~1.5 engineer-days excluding compute.

### M2 language packs (deferred)

Same shape, four files: `python.md`, `typescript.md`, `rust.md`, `go.md`. Activation
requires loader option **B** (profile + worktree-manifest detection). Defer to M2.

## Context build tree

Three concerns, three modules:

```
api/services/code_session.py        ← session lifecycle + auto-context (NEW)
api/services/code_indexer.py        ← session-scoped RAG indexes (NEW)
api/services/code_memory.py         ← thin wrapper over memory_service (NEW)
```

### C1. Auto-injected context (`code_session.py`)

The cheap one. Computed once at session start; results stored in the session record
and prepended to the planner's system prompt only.

**Module surface:**

```python
class CodeSession:
    def __init__(self, worktree_root: Path, ...): ...

    def build_initial_context(self) -> str:
        """Return a system-prompt block (~5K tokens budget)."""
        parts = [
            self._repo_identity(),       # 5 commits, branch, remote
            self._project_manifest(),    # pyproject.toml / package.json / etc.
            self._agent_guidance(),      # CLAUDE.md / AGENTS.md
            self._file_tree(),           # tree -L 3, truncated
            self._test_hint(),           # inferred test command
        ]
        return "\n\n".join(p for p in parts if p)
```

**Per-section work:**

| Section | Source | Truncation rule | LOC |
|---------|--------|-----------------|-----|
| `_repo_identity` | `git log -5 --format="%h %s"` + `git remote -v` + `git symbolic-ref HEAD` | none (small) | ~30 |
| `_project_manifest` | First file found from a fixed list. Read with `code.read`. Strip dependency lists if > 300 lines. | head + tail strategy | ~50 |
| `_agent_guidance` | `CLAUDE.md` → `AGENTS.md` → `.enclave/AGENTS.md`, first match | truncate at 2K tokens | ~30 |
| `_file_tree` | Shell out to `tree -L 3 -I 'node_modules\|venv\|.git'`. Fallback to `find` if `tree` missing. | truncate at 300 lines | ~40 |
| `_test_hint` | Parse the manifest for known test scripts: pyproject `[tool.pytest]`, package.json `scripts.test`, Cargo's default, Go's default | none | ~50 |

Total: ~200 LOC + ~100 LOC of tests.

**Edge cases the work has to handle:**

- Worktree is not a git repo → skip `_repo_identity` gracefully.
- Multi-language repo (pyproject.toml + package.json) → emit both manifests, label them.
- `CLAUDE.md` is 50K tokens (some teams write huge ones) → hard truncation + a note
  to the model: "this guidance was truncated; ask the user for specifics."
- File tree larger than budget → emit truncated tree + a flag the planner can use to
  decide it needs `code.search` instead of guessing.

### C2. Session-scoped RAG indexes (`code_indexer.py`)

The expensive one. Three indexes, lazy-built. Uses existing `EmbeddingService` +
`DocumentService` + `RAGService`, just scoped to a per-session Chroma collection.

**Module surface:**

```python
class CodeIndexer:
    def __init__(self, session_id: str, worktree_root: Path, rag: RAGService): ...

    def ensure_index(self, kind: Literal["code", "history", "docs"]) -> None:
        """Build the index on first call; idempotent."""

    def search(self, kind: str, query: str, top_k: int = 5) -> list[dict]:
        """Query a built index; build it if missing."""

    def refresh_code(self, paths: list[str]) -> None:
        """Re-index specific files (called after code.write / apply_patch)."""
```

**Per-index work:**

| Index | Source | Chunking | Refresh trigger | LOC |
|-------|--------|----------|-----------------|-----|
| `repo-code` | All source files in worktree (filtered by gitignore + extension allowlist) | 200-line windows with 30-line overlap. **M1 chooses windowing**, not AST — tree-sitter is a big dep we defer to M2. | After every `code.write` / `code.apply_patch`, incremental upsert for the touched paths | ~250 |
| `repo-history` | `git log -1000 --format='%H%n%s%n%b%n---'` + diff stats per commit | One chunk per commit (subject + body + diffstat) | Branch-pinned: rebuild only if `HEAD` moved beyond the indexed range | ~150 |
| `repo-docs` | `**/*.md` + docstrings extracted from source (simple regex for now, AST in M2) | 300-line windows | After every `code.write` to a `.md` or source file with docstrings | ~200 |

Total: ~600 LOC + ~250 LOC tests.

**Storage:** `~/.enclave/sessions/<id>/rag/{code,history,docs}.chroma`. Each index is
its own Chroma collection. Cleaned up on `enclave code rm <id>`.

**Tool surface:** one new tool, `code.search_index`, registered by the `code` plugin.
Wraps `CodeIndexer.search`. Schema:

```yaml
- id: search_index
  file: tools/search_index.py
  function: execute
  description: |
    Search a session-scoped index of the repo. Use when you need to find code,
    history, or documentation without reading whole files.
  parameters:
    kind: {type: string, enum: [code, history, docs], required: true}
    query: {type: string, required: true}
    top_k: {type: integer, default: 5}
```

**Cost / budget gate:** `repo-code` indexing on a 100K-line repo with
`nomic-embed-text` is ~3 minutes on the BD790i. Show progress in the CLI. Skip the
build if `--no-rag` is passed.

### C3. Memory (`code_memory.py`)

Thinnest of the three. Wraps `memory_service.py`. Scoped per-repo (key = absolute
worktree root).

**Three memory kinds:**

| Kind | Examples | When recorded |
|------|----------|---------------|
| `user_preference` | "user prefers single quotes" | After the user corrects the agent the same way twice in a session |
| `repo_fact` | "test runner is `make test`" | When the agent discovers a non-obvious project convention |
| `past_failure` | "tried X to fix Y, didn't work because Z" | At the end of a failed session (`verify.passed == false`) |

**Module surface:**

```python
class CodeMemory:
    def remember(self, kind: str, content: str): ...
    def recall(self, kind: str = None, limit: int = 10) -> list[dict]: ...
    def clear(self, kind: str = None): ...
```

**Tool surface:** two new tools — `code.remember`, `code.recall`. The agent decides
when to record; we don't auto-record (the auto-detection rules above are *suggestions
in the skill prompts*, not engine behavior). This keeps the surface small and
auditable.

**Privacy:** memory is off by default. Enabled with `enclave code memory on`.
Per-repo `clear` command. Stored in `~/.enclave/memory/<repo_fingerprint>.json`.

### C4. Library docs cache (M2)

Deferred. Sketch only:

- Use the context7 MCP for live fetches.
- Cache responses at `~/.enclave/cache/docs/<package>/<version>/`.
- `enclave code docs prebuild <package>...` for offline air-gapped use.
- Roughly ~150 LOC + a CLI subcommand.

Don't build in M1 — context7 MCP itself isn't pre-registered yet, and the value
depends on whether the planner reaches for it. Validate post-M1.

## Build order

Recommend executing in this sequence. Earlier tasks unblock later ones; nothing in
this list takes more than ~2 engineer-days.

| Day | Tasks | Output |
|-----|-------|--------|
| 1 | S1 (`get_skills` `*` support) + scaffolding `plugins/code/plugin.yaml` + tool stubs | Plugin loads, no skills yet |
| 1 | S2 + S3 (write the 9 skill markdowns, list them) | Skills inject into prompts |
| 2 | C1 `code_session.py` build_initial_context (all 5 sections) | Planner sees rich session context |
| 2 | C1 tests + edge cases | Robust to weird repos |
| 3 | C2 `code_indexer.py` — `repo-code` index only | First RAG index live |
| 4 | C2 — `repo-history` + `repo-docs` indexes | Three indexes |
| 4 | C2 — `code.search_index` tool wiring | Planner can query indexes |
| 5 | C2 — refresh-on-write logic + tests | Indexes stay fresh |
| 5 | C3 `code_memory.py` + `code.remember/recall` tools | Memory available, off by default |
| 6 | S4 + S5 — skill smoke test + eval pass (compute-bound) | Evidence skills help |
| 6 | Integration: run a real bug-fix task end-to-end with all of this on | Demo path for the spec sign-off |

**Total: ~6 engineer-days for skills + context + memory + indexes**, which fits
inside the 4–6 week M1 budget from the spec.

## What's intentionally not in this plan

- **AST-aware chunking** (tree-sitter). Big dep, big install footprint. Windowing
  is fine for M1.
- **Auto-recorded memory.** Too easy to record garbage. The agent decides what to
  remember via the tool.
- **Cross-session global RAG.** Per-session is simpler and avoids stale indexes
  across branches.
- **Skill personalization** (the user editing skills). Out of scope for M1; users
  who want different behavior can fork the plugin folder.
- **Skill quality eval.** S5 measures end-to-end task success, not individual skill
  effectiveness. A per-skill ablation study is M2+ work.

## Risks

| Risk | Mitigation |
|------|------------|
| Skills bloat the system prompt and degrade smaller-model performance | Make skill inclusion profile-driven (M2 option B); for M1 the 9 skills together are ~600 tokens, well under budget |
| `repo-code` indexing too slow on huge repos | `--no-rag` escape hatch; show progress; consider sampling for repos > 500K lines |
| `nomic-embed-text` quality insufficient for code | Swap to `bge-m3` is a one-line registry change once we see retrieval misses |
| Memory accumulates noise | `clear` command; cap at N most recent per kind |
| The 9 skill prompts conflict with each other | Lint pass: load all 9, run a "review your instructions" turn, look for contradiction signals. Fix before merge. |
