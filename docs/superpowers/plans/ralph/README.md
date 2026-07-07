# Ralph loops — composer-dominant workspace rework

Autonomous execution harness for the [implementation plan](../2026-06-28-composer-dominant-workspace-implementation.md).
One loop per phase; each loop re-feeds [HARNESS.md](./HARNESS.md) + the phase's
[card](./CARDS.md) until it prints `GATE PASSED:` or `HALT:`.

- **Harness** (invariant loop contract): [HARNESS.md](./HARNESS.md)
- **Cards** (per-phase goal/units/verify/gate): [CARDS.md](./CARDS.md)
- **Ledgers** (loop memory, one per phase): `ledgers/<phase>.md` — created by the loop on
  first run; do not hand-edit while a loop is live.

## Prerequisites (once)
```bash
git checkout feat/composer-workspace                     # already cut
source venv/bin/activate
RATE_LIMIT_RPM=0 python -m api.main &                     # dev server, limiter OFF, :8001
curl -sf localhost:8001/health                            # confirm 200
```

## Launch a phase
`--completion-promise` is the phase-specific done-string; the agent ends the loop by
outputting `<promise>{that exact string}</promise>` (the stop-hook matches it literally).
`--max-iterations` = the card's CAP.

```
/ralph-loop --completion-promise 'phase-0 GATE PASSED' --max-iterations 6 Run one iteration of Ralph phase-0. Read docs/superpowers/plans/ralph/HARNESS.md and the ## phase-0 section of docs/superpowers/plans/ralph/CARDS.md, follow the harness exactly, and update docs/superpowers/plans/ralph/ledgers/phase-0.md. When the gate is unequivocally true, emit <promise>phase-0 GATE PASSED</promise>.
```

Swap `phase-0` and the promise/CAP per phase (CAPs: 0→6, 1→6, 2→20, 3→6, 4→8, 5→10, 6→8,
7→10, 8→8, 9→6, 10→10). Keep the promise string and the `<promise>` tag identical.

## Order & gates
Stage 1: **phase-0 → phase-1 → phase-2 → phase-3**, then **STOP at the 🚦 parity gate**
for human sign-off. Stage 2: **phase-4 → … → phase-10**. Advance only when the prior
ledger says `GATE PASSED`.

- **Completion** ends the loop only via `<promise>…</promise>` (exact match). A bare
  "GATE PASSED" in prose does nothing.
- **Halt / stuck**: the loop has no halt detection — it re-feeds until `/cancel-ralph` or
  `--max-iterations`. On any `HALT:` in a ledger, read its last line, intervene, then
  relaunch that phase.

> Phase 0 is safe to run first — it touches only the parity goldens, never `index.html`.
> Phase 7 carries the single allowed backend edit (additive `test-step messages[]`);
> every other phase is frontend/test-only.
