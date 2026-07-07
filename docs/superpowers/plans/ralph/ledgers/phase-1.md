# phase-1 ledger — extract CSS

Card: CARDS.md → `## phase-1` · Harness: HARNESS.md · type/scope=refactor(ui) · CAP=6
GOAL: `<style>` → `api/static/css/app.css` VERBATIM, linked; zero visual/behavior change.

consec_fail: 0

## Units
- [x] U1: Capture baseline screenshots @1440/1024/768 into scratchpad (reference set).
- [x] U2: Move the main `<style>` block verbatim into `api/static/css/app.css`.
- [x] U3: Add `<link rel="stylesheet" href="/static/css/app.css">` in `<head>`; KEEP the head theme-bootstrap script inline classic (must run before paint — no flash).
- [x] U4: Screenshot-compare @3 widths vs baseline; assert visually identical.

VERIFY: `pytest tests/ui -q` + screenshot diff clean + 0 console errors + no x-overflow.
GATE: pixel-parity @3 widths AND `pytest tests/ui -q` green.

GATE PASSED: phase-1

## Facts (resolved at iter 1)
- Card's `~36–5679` line hint is STALE (branch drift → index.html now 25362 lines). The
  MAIN `<style>` block is lines **36–6443**. There are ALSO 5 component-scoped
  `<style id=...>` blocks at 6444–6607 (enclave-journey/pins/threads/library/runlens-styles)
  — those are deliberately separate injected styles; phase-1 moves the ONE main block only.
- Baseline reference set: `playwright-results/phase1-baseline/` (gitignored, persists across iters).

## Notes
- U1 (iter 1): shot `composer-{1440,1024,768}.png` full-page of the default booted Composer into `playwright-results/phase1-baseline/`. All 3 widths: **0 boot console errors, 0 x-overflow**. Verified 1440 render = fully-styled dark/teal Composer (not blank). This is the pre-CSS-move reference set for U4. Capture script: `$CLAUDE_JOB_DIR/tmp/shoot_baseline.py`.
- U2 (iter 2): extracted inner CSS (index.html lines 37–6442, i.e. the main `<style>`…`</style>` at 36/6443) into `api/static/css/app.css` — **6406 lines, byte-exact verbatim** (round-trip assert vs the index region passed). **index.html left UNTOUCHED this unit** so the served page stays byte-identical to baseline (screenshot parity trivially preserved); the actual DOM swap (link-in + inline-out, atomic — no unstyled intermediate) is U3, screenshot-diff is U4. VERIFY: `pytest tests/ui -q` = **160 passed**. Committed app.css + ledger.
- U3 RISK NOTE: the 160 tests/ui are static-markup assertions over index.html. Before removing the inline `<style>` in U3, grep them for any that assert CSS-rule/selector presence inside index.html (would flip RED once the block moves to app.css). If found, re-point them at app.css.
- U4 (iter 4): re-shot @1440/1024/768 post-move into `playwright-results/phase1-after/` (0 boot errors, 0 x-overflow all widths). Threshold diff (per-channel >30) vs baseline: **dimensions match exactly at all 3 widths** (no layout shift); changed pixels = 152/136/82 (**0.01%**), bbox entirely within the top HUD strip (y56–342). Heatmap (`phase1-diff/`) confirms the ONLY deltas are the live clock digits + CPU/MEM/RAM stats row — everything else pixel-identical. GATE: `pytest tests/ui -q`=160 passed AND pixel-parity @3 widths → both TRUE. Parity regression guard still green (3 passed/1 skipped). **GATE PASSED: phase-1.**
- U3 (iter 3): ATOMIC swap in one commit (no unstyled intermediate). (a) index.html: replaced the main `<style>`…`</style>` (36–6443) with `<link rel="stylesheet" href="/static/css/app.css">` at line 36; theme-bootstrap script (19–35) kept inline; 5 component `<style id=...>` blocks kept inline. 25363→18956 lines. **Proved zero CSS loss**: reconstructing index.html with the removed block == original byte-for-byte. (b) The risk materialized — `test_static_markup`/`test_design_tokens`/`test_composer_vertical_layout` assert `:root{}`, `@media(max-width:800px)`, `--accent` teal, `.composer-mode-toggle` rules that now live in app.css. Fix: `tests/ui/conftest.py` `index_html_text` now resolves any `/static/css/*.css` `<link>` back inline (`_inline_local_css`) — models the effective cascade, keeps all CSS-rule tests working, DOM unaffected; visual parity proven separately at U4. VERIFY: `pytest tests/ui -q`=**160 passed**, `pytest tests/parity -q`=3 passed/1 skipped. Live check: `GET /static/css/app.css` → 200 text/css 258190 B, `--accent:` present. Committed index.html+conftest+ledger.
