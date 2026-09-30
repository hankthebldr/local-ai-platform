# Contributing to Enclave

The shape of the branch model and the reasoning behind it live in
[docs/BRANCHING.md](docs/BRANCHING.md). This file is the command reference.

**The two facts that matter most:** `dev` is the default branch — branch from
it and target it. `main` is the release surface — a merge into it publishes a
release, so it is only ever written by a release or hotfix PR.

---

## Setup

```bash
git clone https://github.com/hankthebldr/local-ai-platform
cd local-ai-platform                       # you are on `dev`
python3 -m venv venv && source venv/bin/activate
pip install -r setup/requirements-core.txt -r setup/requirements-dev.txt
cp .env.example .env                       # never commit .env
```

Always activate the venv first — the formatter and secret-scan hooks in
`.claude/hooks/` assume it.

Optional extras: `requirements-rag.txt` (Chroma + embeddings),
`requirements-onnx.txt` (ONNX encoder), `requirements-playwright.txt` (UI
tests), `requirements-ml.txt`.

---

## The loop

```bash
git switch dev && git pull                            # start from current dev

git switch -c issue/214-yaml-cache                    # or feature/1.4-slug
#   ... edit; the format hook runs on save ...

source venv/bin/activate
pytest tests/ --ignore=tests/e2e -v                   # must be green

git commit                                            # secret scan runs here
git push -u origin issue/214-yaml-cache
```

Then open a **draft PR against `dev` immediately** — before the work is
finished. An orphaned branch with no PR is invisible, and that is precisely
how this repo accumulated seven stale branches and lost four months of a
working fix. The draft PR costs nothing and makes the work findable.

Naming, in one line each:

```
issue/{GH#}-{slug}                 small standalone fix          → dev
feature/{MAJOR}.{MINOR}-{slug}     one coherent capability       → dev
issue/{X.Y.Z}-{slug}               a unit inside a feature       → that feature
{parent}--{slug}                   sub-branch (-- never a /)     → its parent
hotfix/{X.Y.Z}-{slug}              production is broken now      → main AND dev
```

---

## Pull requests

The PR title is a Conventional Commit — it becomes the squash message and it
decides the version bump:

```
fix(keys): count authenticated requests against their key    → patch
feat(fleet): host registry + target-host selector            → minor
feat!: pluggable inference engines                           → major
docs: …   chore: …   test: …   refactor: …                   → no bump
```

Before requesting review:

- [ ] `pytest tests/ --ignore=tests/e2e -v` green
- [ ] Touched `MODEL_REGISTRY`? Update [MODELS.md](MODELS.md) — the sync hook checks.
- [ ] Touched the workflow engine? Say so; that area uses the `workflow-engine-expert` subagent.
- [ ] User-visible change? Add a `CHANGELOG.md` entry under `[Unreleased]`.
- [ ] No `.env`, keys, or model blobs in the diff.

PRs into `dev` **squash**. Merge-forward syncs (`main → dev`) are plain merges
— never squash a sync, or `dev` loses the hotfix commit and re-conflicts at
the next release.

---

## Releasing

Releases are cut from `dev`, and merging the PR is what ships:

1. Bump `__version__` in `api/__init__.py` (the single source of truth —
   `pyproject.toml` reads it dynamically).
2. Move `CHANGELOG.md`'s `[Unreleased]` entries under the new version heading.
3. Open a PR `dev → main` titled `release: vX.Y.Z`.
4. Merge it. CI tags `vX.Y.Z` and publishes the DMG, wheel, tarball, Docker
   `X.Y.Z` + `latest`, Pages, and the wiki.

If the tag already exists the release is **skipped, not overwritten** — so
forgetting step 1 fails loudly instead of clobbering a shipped release.

### Hotfixes

```bash
git switch main && git pull
git switch -c hotfix/1.2.1-tls-verify
#   ... fix, bump the patch version, add a CHANGELOG entry ...
git push -u origin hotfix/1.2.1-tls-verify
```

Open the PR into `main`. After it merges, **merge `main` back into `dev`** —
a plain merge, not a squash. Skipping this reverts the hotfix at the next
release, and CI will fail the next `dev → main` PR until you do it.

---

## Worktrees

One branch per directory, one shared object store — no stashing to switch
context. Full guidance, including the failure modes, is in
[docs/BRANCHING.md §6](docs/BRANCHING.md#6-worktrees).

```bash
git worktree add -b feature/1.4-fleet-awareness \
    ../local-ai-platform.wt/feature-1.4-fleet-awareness dev

cd ../local-ai-platform.wt/feature-1.4-fleet-awareness
python3 -m venv venv && source venv/bin/activate       # each worktree needs its own
pip install -r setup/requirements-core.txt -r setup/requirements-dev.txt

git worktree list
git worktree remove ../local-ai-platform.wt/feature-1.4-fleet-awareness   # when the PR merges
```

Three things that will cost you an hour if you skip them: **each worktree
needs its own venv** (a venv hardcodes absolute paths — a copied one imports
from the wrong tree); **copy `.env`, never symlink it** (a shared symlink lets
a branch's `ENABLE_API_AUTH` experiment reconfigure your main checkout); and
**run the second API server on `--port 8001`**. Ollama is the exception —
one daemon on `:11434` serves every worktree.

---

## Running things

```bash
source venv/bin/activate
python api/main.py            # API on :8000
ollama serve                  # inference on :11434
python desktop/app.py         # macOS app shell

pytest tests/ --ignore=tests/e2e -v      # the standard suite
pytest tests/ui -v                       # Playwright (needs requirements-playwright)
```

Tests that need Ollama or the RAG extras fail without them; that is expected
locally, and CI installs the full set.

---

## Conventions worth knowing before you write code

These are load-bearing — see [CLAUDE.md](CLAUDE.md) for the full set.

- **Fail-safe persistence.** Never write a model-failure sentinel to a durable
  store, and never return HTTP 200 on a local-model exception — surface a
  `503` with `X-Enclave-Error: model_unavailable`. Resolve everything a resume
  needs *before* flipping a persisted status.
- **No telemetry, no cloud inference, all data local.** Error reporting is
  opt-in, off by default, operator-owned, and redaction is mandatory. A
  feature that phones home by default will not be merged.
- **Auth and CORS default open for localhost.** Don't change those defaults
  without updating the startup warning and the deployment docs together.
