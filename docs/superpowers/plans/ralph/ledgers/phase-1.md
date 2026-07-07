# phase-1 ledger — extract CSS

Card: CARDS.md → `## phase-1` · Harness: HARNESS.md · type/scope=refactor(ui) · CAP=6
GOAL: `<style>` → `api/static/css/app.css` VERBATIM, linked; zero visual/behavior change.

consec_fail: 0

## Units
- [x] U1: Capture baseline screenshots @1440/1024/768 into scratchpad (reference set).
- [ ] U2: Move the main `<style>` block verbatim into `api/static/css/app.css`.
- [ ] U3: Add `<link rel="stylesheet" href="/static/css/app.css">` in `<head>`; KEEP the head theme-bootstrap script inline classic (must run before paint — no flash).
- [ ] U4: Screenshot-compare @3 widths vs baseline; assert visually identical.

VERIFY: `pytest tests/ui -q` + screenshot diff clean + 0 console errors + no x-overflow.
GATE: pixel-parity @3 widths AND `pytest tests/ui -q` green.

## Facts (resolved at iter 1)
- Card's `~36–5679` line hint is STALE (branch drift → index.html now 25362 lines). The
  MAIN `<style>` block is lines **36–6443**. There are ALSO 5 component-scoped
  `<style id=...>` blocks at 6444–6607 (enclave-journey/pins/threads/library/runlens-styles)
  — those are deliberately separate injected styles; phase-1 moves the ONE main block only.
- Baseline reference set: `playwright-results/phase1-baseline/` (gitignored, persists across iters).

## Notes
- U1 (iter 1): shot `composer-{1440,1024,768}.png` full-page of the default booted Composer into `playwright-results/phase1-baseline/`. All 3 widths: **0 boot console errors, 0 x-overflow**. Verified 1440 render = fully-styled dark/teal Composer (not blank). This is the pre-CSS-move reference set for U4. Capture script: `$CLAUDE_JOB_DIR/tmp/shoot_baseline.py`.
