# Historical planning documents

These files captured the pre-1.0 product plan, sprint backlog, and a milestone
optimization recap. They are kept here because they're useful context for
"how did we get from a CPU-inference prototype to where the codebase is now,"
but they should **not** be read as current direction.

## Current sources of truth

| For… | See… |
|------|------|
| What's in flight + the release track | [`CHANGELOG.md`](../../CHANGELOG.md) and [`CLAUDE.md`](../../CLAUDE.md) |
| Architecture-aware orchestration design | [`docs/plans/2026-05-19-architecture-aware-orchestration-design.md`](../plans/2026-05-19-architecture-aware-orchestration-design.md) |
| Multi-agent workflow taxonomy | [`docs/plans/2026-05-23-multi-agent-workflow-patterns-spec.md`](../plans/2026-05-23-multi-agent-workflow-patterns-spec.md) |
| Hardware bring-up | [`docs/BD790I_MIGRATION.md`](../BD790I_MIGRATION.md) |

## What's in this directory

- **`PROJECT_PLAN.md`** — the original product plan written against a 60 GB
  RAM Ryzen target. Largely superseded; current hardware is the BD790i
  (96 GB) plus the MS-01 / M4 fleet.
- **`BACKLOG.md`** — a 6-sprint 12-week product backlog from the same era.
  The current release planning lives in `CLAUDE.md`'s "Release track"
  section plus the `CHANGELOG.md` `[Unreleased]` block.
- **`OPTIMIZATION_SUMMARY.md`** — a milestone recap dated 2025-12-13 covering
  the early optimization wave that brought the codebase to "0.1.0
  foundation milestone, ~85% complete." Useful as a baseline if anyone ever
  benchmarks against pre-1.0 behavior.

If you find yourself referencing one of these from new work, copy the
relevant fragment forward into a current doc instead — they will keep
drifting out of date.
