# Branching, releases, and worktrees

The canonical branch model for this repo. `dev` is the default branch and the
integration trunk; `main` is the release surface. **A merge into `main` is a
release** — it is the event that drives tagging, artifact builds, Docker
publishing, Pages, and the wiki. Nothing else publishes.

Read this before cutting a branch. Day-to-day commands live in
[CONTRIBUTING.md](../CONTRIBUTING.md); this file explains the shape and the
reasons, so that a decision about where to branch from has an answer that
isn't taste.

---

## 1. The model

```
main    ──────●───────────────────────●──────────────────►  RELEASE SURFACE
              ▲                       ▲                     every merge = a release:
              │ PR: release           │ PR: release         tag vX.Y.Z · DMG · wheel ·
              │ (dev → main)          │ (hotfix → main)     tarball · Docker latest ·
              │                       │                     Pages · wiki
              │                  hotfix/1.2.1-tls
              │                       ▲                     cut from main, merges to
              │                       │                     main AND back to dev
dev     ──●───┴───●───────●───────●───┴──────────────────►  INTEGRATION TRUNK (default)
          ▲       ▲       ▲       ▲                         CI on every push + PR
          │       │       │       │                         nightly pre-release build
          │       │       │       │
          │       │       │   issue/214-yaml-cache          ← atomic fast path (patch)
          │       │       │
          │       │   feature/1.4-fleet-awareness           ← a minor scope
          │       │       ▲
          │       │       │  issue/1.4.2-host-registry      ← unit inside the feature
          │       │       │       ▲
          │       │       │       └── issue/1.4.2-host-registry--wol   ← sub-branch
          │       │
          │   release/v2                                    ← only while a major stabilizes
          │
      feature/1.3-composite-steps
```

Three invariants make the automation mechanical:

1. **Merges flow upward only** — sub → issue → feature → `dev` → `main`. The
   one downward movement is *merge-forward* (syncing `main` back into `dev`
   after a hotfix), which is a sync, not a delivery.
2. **Every merge is a PR, and every PR into `dev` squashes.** The squash
   message is the PR title, and the PR title is a Conventional Commit whose
   type matches the branch class. That single rule is what lets the version
   bump be derived rather than decided.
3. **`main` is only ever written by a release PR or a hotfix PR.** Never push
   to it, never merge a feature into it directly.

### Why `dev` exists here

Standard trunk-based development would drop `dev` and release straight off
`main`. This repo keeps it for one concrete reason: **release means publishing
a signed DMG, a wheel, a source tarball, Docker `latest`, Pages, and the
wiki.** Making that fire on every merged feature would mean either publishing
half-finished states or gating every merge on release-readiness. `dev` separates
"integrated and green" from "ready to ship," and lets concurrent workstreams
(today: 1.2.0 Composer and 1.3.0 orchestration) integrate against each other
before either is shippable.

The cost is real and paid deliberately: one extra PR per release, and a
merge-forward obligation after every hotfix. If the release surface ever
shrinks to "push a container," delete `dev` and go trunk-based — the model
should follow the cost, not the habit.

---

## 2. Branch grammar

| Class | Pattern | Cut from | Merges to | SemVer |
|---|---|---|---|---|
| Integration | `dev` | — | `main` | — |
| Release | `main` | — | — | tagged `vX.Y.Z` |
| Major train | `release/v{MAJOR}` | `dev` | `dev` | `vX.0.0` |
| Minor scope | `feature/{MAJOR}.{MINOR}-{slug}` | `dev` (or an open train) | its base | `vX.Y.0` |
| Patch unit | `issue/{MAJOR}.{MINOR}.{PATCH}-{slug}` | its feature | that feature | `vX.Y.Z` |
| Atomic fast path | `issue/{GH#}-{slug}` | `dev` | `dev` | patch |
| Sub-branch | `{parent}--{slug}` | its parent | that parent | — |
| Hotfix | `hotfix/{X.Y.Z}-{slug}` | `main` | `main` **and** `dev` | patch |

Rules that bite if ignored:

- **Sub-branches use `--`, never a third `/`.** Git refs are files in a
  directory tree: once `feature/1.4-fleet` exists as a ref, git cannot also
  create `feature/1.4-fleet/anything` — the path would have to be both file
  and directory. `--` keeps the lineage greppable
  (`git branch --list 'issue/1.4.2-*--*'`) without the collision.
- **Slugs are kebab-case and short**, taken from the issue or feature title.
- **The version segment is declared intent, not a promise.** If a feature
  slips from 1.4 to 1.5, renaming the branch is optional — the merge target
  and the PR title decide the bump.
- **Don't scaffold a train for a one-commit change.** A typo fix is
  `issue/{GH#}-{slug}` → `dev`. Depth follows scale, not ceremony.

### Which depth for which work

| Work | Path |
|---|---|
| Typo, small bug, config tweak | `issue/{GH#}-{slug}` → `dev` |
| One coherent capability | `feature/X.Y-{slug}` → `dev`; issues underneath only if it decomposes |
| Coordinated breaking change | `release/vN` train off `dev`, features underneath |
| Exploration, uncertain outcome | `--` sub-branches under the issue; winner merges, losers are deleted with their reasoning written to an ADR or `RESEARCH.md`, not left as zombie branches |
| Production is broken *now* | `hotfix/X.Y.Z-{slug}` off `main` (§4) |

---

## 3. What each merge triggers

| Event | CI | Nightly | Stable release | Docker | Pages | Wiki |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| PR → `dev` | ✅ | — | — | — | — | — |
| Push → `dev` | ✅ | ✅ | — | `dev-<sha>`, `edge` | — | — |
| PR → `main` | ✅ | — | — | — | — | — |
| **Push → `main`** | ✅ | — | ✅ **tag + full release** | `X.Y.Z`, `latest` | ✅ | ✅ |
| Push tag `v*.*.*` | — | — | ✅ | ✅ | ✅ | ✅ |

The `main` push path reads `__version__` from `api/__init__.py`, creates the
annotated tag `v$__version__` if it does not already exist, and publishes the
stable release. **If the tag already exists the release is skipped, not
overwritten** — so a docs-only merge to `main` cannot clobber a shipped
release, and forgetting the version bump fails loudly rather than silently
re-publishing.

This makes the release checklist short: bump `api/__init__.py`, update
`CHANGELOG.md`, open the `dev → main` PR. Merging it ships.

---

## 4. The hotfix path

A hotfix exists for one situation: something shipped is broken and `dev`
carries unreleasable work, so you cannot ship from `dev`.

```
main ──●──────────────────●────►   ← 2. merge (releases X.Y.Z+1)
        \                ▲
         hotfix/1.2.1-tls┘          ← 1. cut from main, fix, bump patch
                         │
dev  ────────────────────┴──────►   ← 3. merge main back into dev  ← DO NOT SKIP
```

Step 3 is the step people skip and regret. Without it the next `dev → main`
release reverts the hotfix, because `dev` never learned about it. Merge
forward as a **plain merge, not a squash** — it is a sync, and squashing it
would hide the hotfix commit from `dev`'s history and cause the same conflict
again at the next release.

CI enforces the shape by failing the `dev → main` PR when `main` contains
commits absent from `dev`.

---

## 5. Drift control

Long-lived branches drift. The discipline that keeps the tax payable:

- **Merge forward on a cadence.** `main → dev` after every release; `dev →
  feature/*` before opening the PR upward. Forward merges are plain merges.
- **Lifespan budget.** Issue branches live days; feature branches weeks;
  `release/*` only while a major is actually stabilizing. A feature branch
  older than a sprint is a smell — split it or land it.
- **Delete on merge.** Merged refs vanish; the squash commit and the tag are
  the record. The repo setting does this automatically.

The 2026-09 consolidation exists because this section did not. Seven branches
sat orphaned for months; two of them (`feat/onnx-embedding-substrate`,
`feat/run-event-substrate`) had been fully reimplemented on the trunk while
still appearing to hold unmerged work, and one genuine fix — API-key usage
tracking — sat unmerged for four months. **A branch with no open PR is
invisible.** Open the PR as a draft on day one.

---

## 6. Worktrees

Enclave work is naturally concurrent — a long inference run, a Playwright
suite, and a docs edit have no reason to contend for one checkout. Worktrees
give each branch its own directory against one shared object store, so
switching contexts costs nothing and no branch ever forces a stash.

### Layout

```
~/Github/Github_desktop/
├── local-ai-platform/                    ← primary clone, stays on `dev`
└── local-ai-platform.wt/                 ← sibling; never nested inside the clone
    ├── feature-1.4-fleet-awareness/
    ├── issue-214-yaml-cache/
    └── hotfix-1.2.1-tls/
```

The worktree directory is the branch name with `/` and `--` flattened to `-`.
Keep the `.wt/` root a **sibling** of the clone, not a child: nesting it puts
a second working tree inside the first, where the parent's tooling — pytest
collection, the formatter hook, Docker build context — will walk into it.

### Commands

```bash
# create a branch and its worktree in one step
git worktree add -b feature/1.4-fleet-awareness \
    ../local-ai-platform.wt/feature-1.4-fleet-awareness dev

# check out an existing remote branch into a worktree
git worktree add ../local-ai-platform.wt/issue-214-yaml-cache issue/214-yaml-cache

git worktree list                 # what's checked out where
git worktree remove ../local-ai-platform.wt/issue-214-yaml-cache
git worktree prune                # after deleting a directory by hand
```

### The three things that bite

1. **Each worktree needs its own venv.** A Python venv hardcodes absolute
   paths in `bin/activate` and its shims; copying or symlinking one across
   worktrees produces imports resolved against the wrong tree, which surfaces
   as test failures that make no sense. `venv/` is gitignored, so it is
   per-worktree by default — create it and move on:

   ```bash
   cd ../local-ai-platform.wt/feature-1.4-fleet-awareness
   python3 -m venv venv && source venv/bin/activate
   pip install -r setup/requirements-core.txt -r setup/requirements-dev.txt
   ```

2. **Runtime state is per-worktree, and that is the point.** `.env`,
   `data/config/api_keys.yaml`, the Chroma store, and downloaded models are
   untracked, so each worktree starts clean. Copy `.env` across deliberately
   (`cp ../../local-ai-platform/.env .`) — never symlink it, or a branch
   experimenting with `ENABLE_API_AUTH` silently reconfigures your main
   checkout. Two API servers cannot both hold port 8000; run the second with
   `--port 8001`.

   Ollama is the deliberate exception: one daemon on `:11434` serves every
   worktree, and models are downloaded once. Don't run a second one.

3. **A branch can only be checked out in one worktree.** `git worktree add`
   on a branch already checked out elsewhere fails by design — that error is
   the feature, not an obstacle. Use the existing worktree.

### Lifecycle

Remove the worktree when its PR merges — `git worktree remove <path>`, which
also drops its venv and scratch state. A `.wt/` directory that has outlived
its branch is the same smell as a stale branch, and `git worktree list` is
the fastest audit of what you actually have in flight.

---

## 7. Naming reference

```
dev                                     integration trunk (default branch)
main                                    release surface
release/v2                              major train
feature/1.4-fleet-awareness             minor scope
issue/1.4.2-host-registry               patch unit inside a feature
issue/214-yaml-cache                    atomic fast path (GitHub issue number)
issue/1.4.2-host-registry--wol          sub-branch (-- never a third /)
hotfix/1.2.1-tls-verify                 cut from main, merges to main and dev
archive/2026-04-08-openclaw-skills      annotated tag; not a branch
```

PR titles are Conventional Commits, and the type sets the bump:

| Branch class | PR title type | Effect at the next release |
|---|---|---|
| `issue/*`, `hotfix/*` | `fix:` (or `chore:` / `docs:`, which don't bump) | patch |
| `feature/*` | `feat:` | minor |
| `release/v{N}` | `feat!:` or a `BREAKING CHANGE:` footer | major |

---

## 8. Retired conventions

Superseded by this document. If you find one of these, it predates 2026-09:

| Old | New |
|---|---|
| `master` as trunk | `dev` integrates, `main` releases |
| `worktree-design+ohno-brand-refresh` (`+` as separator, purpose in the name) | `feature/X.Y-{slug}`; the worktree is a directory, not a branch-name prefix |
| `claude/angry-dubinsky` (generated names) | `issue/{GH#}-{slug}` — a branch name should say what it does |
| Long-lived branch with no PR | Draft PR opened on day one |
