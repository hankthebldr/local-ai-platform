# Parity harness — no feature loss across the `index.html` ES-module split

This is the safety net for the [composer-dominant workspace + ES-module
fan-out](../../docs/superpowers/specs/2026-06-28-composer-dominant-workspace-design.md).
It proves the 21k-line single-file UI can be split into `api/static/js/**`
modules **without dropping any behavior**.

## The invariant

The monolith is a **classic `<script>`**: top-level `function foo(){}` becomes
`window.foo`, and top-level `const Bar = (...)` is a global *lexical* binding.
Inline `on*=` handlers in the static markup (e.g. `onclick="dfSave()"`) reach
both. Under **ES modules**, top-level declarations are module-scoped and
invisible to inline handlers — so every symbol a handler references must be
re-exposed on `window` by `js/shell/legacy-bridge.js`, or the handler silently
no-ops.

## Goldens (captured from the PRE-split app — never regenerate post-split)

| file | what | how |
|---|---|---|
| `golden/window_globals.json` | runtime `Object.keys(window)` minus native baseline (270 app globals) | browser capture |
| `golden/inline_handlers.json` | 81 symbols invoked by 196 static inline handlers, each classified `window` / `lexical` / `unknown`; **57 `must_bridge`** (lexical-only → break under modules) | `scripts/capture_parity_goldens.py` |

The `must_bridge` list is the exact `legacy-bridge.js` checklist for Stage 1.

## Tests

- `test_parity.py` (pure-Python, always-on in the normal suite):
  - **no handler drift** — handler symbol set matches golden.
  - **every handler symbol reachable** — defined somewhere in the served JS
    corpus (`index.html` + `js/**`); catches an extraction dropping a symbol.
  - **post-split window-bridged** — *skipped until `js/` exists*, then becomes a
    hard gate: every handler symbol must have `window.X =` in the corpus.
  - **golden self-consistency**.
- Runtime gate (added with Stage 1, Playwright): `Object.keys(window) ⊇ golden`,
  every handler symbol global-reachable in a booted page, zero console errors on
  module boot. `pytest-playwright` is available; runs against a live server.

## Regenerate (only with intentional handler changes, pre-split)

```bash
python scripts/capture_parity_goldens.py        # rewrites inline_handlers.json
python scripts/capture_parity_goldens.py --check # preview, no write
```
