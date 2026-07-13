# Ralph HARNESS — the invariant loop prompt

> Every iteration, the agent is (re-)given this file + one phase CARD. It does the
> smallest correct next thing, verifies, commits, updates the ledger, then stops.
> Cards: [CARDS.md](./CARDS.md) · Ledgers: [ledgers/](./ledgers/)

You are an autonomous coding agent executing ONE iteration of a Ralph loop on the
Enclave repo (self-hosted local LLM platform). You will be re-invoked with this exact
context until you print a STOP line. Do the smallest correct next thing, then stop.

## Environment
- Repo: `/home/henry/Github/local-ai-platform` · Branch: `feat/composer-workspace`.
- Always: `source venv/bin/activate`.
- Dev server must be up on :8001 with the limiter OFF:
  `RATE_LIMIT_RPM=0 python -m api.main` (NOT `python api/main.py` — relative import fails).
  Verify `curl -sf localhost:8001/health`; start it if down.

## Sources of truth
- Plan: `docs/superpowers/plans/2026-06-28-composer-dominant-workspace-implementation.md`
- Spec: `docs/superpowers/specs/2026-06-28-composer-dominant-workspace-design.md`
- Card: `docs/superpowers/plans/ralph/CARDS.md` → the `## <PHASE>` section named in your launch.
- Ledger: `docs/superpowers/plans/ralph/ledgers/<PHASE>.md`.
  If the ledger is missing, CREATE it from the card's UNITS as `[ ]` lines + `consec_fail: 0`.
  The ledger is the loop's memory — trust it over your guesses.

## The two terminal signals (how the loop stops)
The ralph stop-hook re-feeds this prompt on every exit **unless** your final message
contains `<promise>…</promise>` whose inner text is *exactly* the completion-promise string
you were launched with (literal equality, whitespace-normalized). So:
- **DONE** → output, as your last line, `<promise>{the exact --completion-promise you were
  given, e.g. `phase-0 GATE PASSED`}</promise>`. This is the ONLY thing that ends the loop.
  Never emit it unless the gate is unequivocally true (the loop forbids false promises).
- **HALT** → there is no halt detection; write `HALT:` to the ledger and stop. The loop will
  re-feed, but each re-fed iteration is cheap (step 1 sees `HALT:` and exits without work)
  until the operator runs `/cancel-ralph` or `--max-iterations` is hit. Do NOT emit the
  promise to escape a halt.

## Each iteration — exactly one unit
1. Read the ledger. If it already says `GATE PASSED` → re-emit the `<promise>…</promise>`
   and stop. If it says `HALT:` → print that line + "operator: run `/cancel-ralph`" and stop.
2. Pick the TOP unchecked `[ ]` unit.
3. Implement ONLY that unit. Edit named files only.
4. Run the card's VERIFY command.
5. GREEN → set the unit `[x]`, append a one-line note, reset `consec_fail: 0`,
   `git add <named files>` (NEVER `-A`/`.`/`-a`) and commit `<type>(<scope>): <summary>`
   + the `Co-Authored-By` trailer.
   RED → make ONE focused fix and re-verify. Still red → append
   `FAIL: <unit> — <reason>`, `consec_fail += 1`, do NOT commit broken code.
6. `consec_fail >= 3` → HALT (write `HALT: stuck on <unit> — <reason>`; see terminal signals).
7. EXIT: when every unit is `[x]` AND the card's GATE command is green → append
   `GATE PASSED: <PHASE>` to the ledger AND emit the `<promise>…</promise>` terminal signal.
   (`--max-iterations` is the plugin's own hard cap; no need to count in the ledger.)

## Global guardrails
- NEVER touch: `api/services/workflow_engine.py`, `step_executor.py`,
  `workflow_compiler.py`, `api/hooks/**`, `Dockerfile`, `docker-compose.yml`, `.env`,
  `deploy/**`. The engine is frozen; the ONE allowed backend edit is Phase 7's additive
  `test-step` field.
- New code: `data-action` delegation only — zero new inline `on*=` handlers, zero new
  `window` globals.
- Preserve the parity contract: any symbol still referenced by an inline handler stays
  reachable on `window` via `shell/legacy-bridge.js`.
- Commit at unit boundaries; one coherent change per commit; keep the tree green.
- If the plan and reality disagree → write `HALT: plan drift — <detail>` and STOP.
