# phase-0 ledger — re-baseline the goldens

Card: CARDS.md → `## phase-0` · Harness: HARNESS.md · type/scope=test(parity) · CAP=6
GOAL: parity harness green on the UNTOUCHED monolith; goldens captured pre-split.

consec_fail: 0

## Units
- [x] U1: Run `python scripts/capture_parity_goldens.py`; confirm golden diff is ONLY these 17 adds, 0 removals: AssetPeek, Compare, ComposerSplit, DfSeedSchema, InstallWizard, Pins, ResearchFlow, RunLens, ScaffoldModal, Threads, WorkflowBuilder, composerSeedAgent, composerStopRun, composerTestStepInChat, loadStatus, onChatModelChanged, openWorkflowInComposer. Anything else → HALT.
- [x] U2: Commit refreshed `tests/parity/golden/{inline_handlers,window_globals}.json`.
- [ ] U3: Ensure a runtime parity Playwright test exists (`Object.keys(window)` ⊇ golden + zero console errors on boot) against the served page; add it if missing.

VERIFY: `pytest tests/parity -q` (+ runtime parity test with server up)
GATE: `pytest tests/parity -q` fully green with ZERO changes to `api/static/index.html`.

## Notes
- U1 (iter 1): inline_handlers golden diff = EXACTLY the 17 expected adds, 0 removals (verified programmatically pre-write). Re-ran capture → 229 handler attrs / 98 symbols. `pytest tests/parity -q` = 3 passed, 1 skipped (post-split window-bridge test inert until js/ exists). index.html UNTOUCHED.
- U2 (iter 1): window_globals re-baselined via live Chromium capture on :8001 (0 boot console/page errors). Raw `Object.keys(window) − about:blank` leaked 14 browser-native secure-context APIs (caches, cookieStore, showOpenFilePicker, getScreenDetails, …) from newer Chromium vs the 2026-06-29 capture; filtered to app-declared globals (index.html `window.X=`/top-level const|fn) ∪ old golden. Result: 269→314 app globals, +46 genuine app adds (the workspace features), 0 removals. Stored functions+objects only (matched original convention; excluded the 1 typeof-'other' boolean `_dfFullscreenEscBound`). Committed both goldens.
