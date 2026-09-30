# Enclave — Teal Palette Refresh (Color Tokens)

- **Date:** 2026-05-29
- **Status:** Shipped — superseded in detail by the delivered palette (see note below)
- **Author:** Henry + Claude (brainstorming session)

> **Provenance.** This spec was written on the `worktree-design+ohno-brand-refresh`
> branch and never merged; it is recovered here during the 2026-09 branch
> consolidation so the teal rebrand has a decision record on the trunk. The
> rebrand itself shipped — but the delivered tokens were tuned during
> implementation and differ from the values proposed here (for example the
> primary accent landed at `#2BD4B4` / `#0E9C82` in `api/static/css/app.css`,
> not the `#14B8A6` / `#0E8C7E` proposed below).
>
> **Read this for the *why* — the rationale, the goals, and the surface
> inventory. For the *what*, `api/static/css/app.css` and `docs/design/` are
> authoritative.** The checklists below are historical, not open work.

## Summary

Move Enclave's visual accent off the PANW **Cortex** identity (bright lime-green `#00CC66`
+ PANW orange `#FA582D`) onto an **Oh NO LLC** palette: a **teal-led** scheme with cobalt
as the functional blue and emerald reserved for success. The dark blue-grey foundation —
already where we want it — is kept. This is a **tokens-only** change: we redefine the CSS
custom-property values (and sweep the hardcoded stragglers), nothing else.

The change is high-leverage because the UI is already token-driven — the file's own header notes
**800+** token references rebrand transparently when the values change. Critically, the dark theme
already has the exact structure we want: a **primary accent** (`--accent`, green today) and a
**secondary accent** (`--accent-2`, "Cortex Cool Blue", blue today). Teal→primary and cobalt→secondary
map straight onto it. The work is (a) redefine ~24 token values in the `:root` blocks, (b) sweep the
raw hex usages that bypass the tokens, and (c) propagate to the landing page, CLI, and README, which
keep their own copies.

## Goals

- Replace the accent palette so the product no longer reads as "PANW Cortex."
- Retire the PANW orange entirely; leave no orphaned references.
- Give `--success` its own emerald identity (today it is literally the same green as `--accent`).
- Keep the dark foundation, typography, glow *treatment*, naming, and layout untouched.
- Land a single coherent palette across all surfaces (console, setup, landing, CLI, README).

## Non-goals (explicitly out of scope)

- Typography (`JetBrains Mono` + `Space Grotesk` stay).
- Renaming "Cortex Console" or any logo/wordmark work.
- Layout, component structure, or the glow *mechanic* (glow color follows the accent; the effect stays).
- A multi-product Oh NO LLC design system, or extracting a shared `tokens.css` (noted as future, below).
- Light/dark behavior changes — both themes keep working; only their accent values move.

## The palette — canonical token values (dark `:root`)

Foundation is **kept verbatim**. Accent family, semantics, glows, and the retired orange change.

| Token | Today (Cortex) | New (teal-led) | Role |
|---|---|---|---|
| `--bg-deep` | `#070A0F` | `#070A0F` (keep) | outer canvas |
| `--bg` | `#0B0F14` | `#0B0F14` (keep) | primary surface |
| `--bg-elev` | `#11161D` | `#11161D` (keep) | elevated card |
| `--bg-elev-2` | `#161D26` | `#161D26` (keep) | modals / popovers |
| `--bg-panel` | `rgba(17,22,29,.92)` | keep | panel scrim |
| `--border` | `#1F2933` | `#1F2933` (keep) | default rule |
| `--border-strong` | `#2A3441` | `#2A3441` (keep) | emphasised rule |
| `--border-glow` | `#00CC661F` | `#14B8A61F` | accent-tinted rule |
| `--accent` | `#00CC66` | **`#14B8A6`** | CTA / active — **teal** |
| `--accent-bright` | `#52E89E` | **`#2DD4BF`** | hover / focus / accent text |
| `--accent-dim` | `#00CC6660` | `#14B8A660` | — |
| `--accent-ghost` | `#00CC6612` | `#14B8A612` | — |
| `--accent-trace` | `#00CC6608` | `#14B8A608` | near-invisible wash |
| `--accent-2` | `#5EB3FF` | **`#4C8DFF`** | secondary — **cobalt** (nav / info) |
| `--accent-2-bright` | `#8DCBFF` | **`#6E9FFF`** | cobalt hover |
| `--accent-2-dim` | `#5EB3FF55` | `#4C8DFF55` | — |
| `--accent-2-ghost` | `#5EB3FF12` | `#4C8DFF12` | — |
| `--success` | `#00CC66` *(= accent)* | **`#1FBE74`** | success — **emerald, now distinct** |
| `--success-dim` | `#00CC6660` | `#1FBE7460` | — |
| `--info` | `#5EB3FF` | **`#4C8DFF`** | info / links — **cobalt** (= `--accent-2`) |
| `--info-dim` | `#5EB3FF60` | `#4C8DFF60` | — |
| `--warn` | `#FFB020` | **`#F5B544`** | warning — softened amber |
| `--warn-dim` | `#FFB02060` | `#F5B54460` | — |
| `--danger` | `#F23E3E` | **`#F2555F`** | error — rose-red |
| `--danger-dim` | `#F23E3E60` | `#F2555F60` | — |
| `--text` | `#E8ECEF` | keep | primary text |
| `--text-dim` | `#9AA3AD` | keep | secondary text |
| `--text-muted` | `#5B6470` | keep | muted |
| `--text-faint` | `#3A424D` | keep | faint |
| `--panw-orange` (+ `-dim`, `-ghost`) | `#FA582D…` | **deleted** | retired |

Cobalt hover is the existing `--accent-2-bright` token (`#8DCBFF → #6E9FFF`) — no new token needed.
No pale sky-blue (`#7FB0FF`, `#38BDF8`) anywhere — that was the "lighter blue" we rejected. Note the
old secondary blue `#5EB3FF`/`#8DCBFF` is *deepened* to cobalt, not kept.

### Glows (follow their source color)

| Token | New value |
|---|---|
| `--glow-accent` | `0 0 10px #14B8A640, 0 0 2px #14B8A680` |
| `--glow-info` | `0 0 10px #4C8DFF38, 0 0 2px #4C8DFF70` |
| `--glow-warn` | `0 0 10px #F5B54438, 0 0 2px #F5B54470` |
| `--glow-danger` | `0 0 10px #F2555F38, 0 0 2px #F2555F70` |
| `--glow-orange` | **deleted** → callers use `--glow-danger` |

## Light theme (`:root[data-theme="light"]` block)

The light block only **overrides** the accent/secondary/success/info families + their glows; it does
**not** redefine `--warn`/`--danger` (those inherit `:root`). We preserve that — so light warn/danger
inherit the new amber/rose. Values re-tuned for ≥4.5:1 on white. Foundation (white bg, light borders) kept.

| Token | Today | New |
|---|---|---|
| `--accent` | `#00A352` | **`#0E8C7E`** (deeper teal) |
| `--accent-bright` | `#18C46E` | **`#14B8A6`** |
| `--accent-dim / -ghost / -trace` | `#00A352·xx` | `#0E8C7E·xx` |
| `--accent-2` | `#2F86E5` | **`#2563EB`** (cobalt) |
| `--accent-2-bright` | `#4FA0F0` | **`#4C8DFF`** |
| `--accent-2-dim / -ghost` | `#2F86E5·xx` | `#2563EB·xx` |
| `--success` (+ `-dim`) | `#00A352` | **`#059669`** (emerald) |
| `--info` (+ `-dim`) | `#2F86E5` | **`#2563EB`** (= `--accent-2`) |
| `--border-glow` | `#00A35221` | `#0E8C7E21` |
| `--glow-accent` | `#00A35221` | `#0E8C7E21` |
| `--glow-info` | `#2F86E521` | `#2563EB21` |
| `--glow-orange` | `#FA582D21` | **deleted** → `--glow-danger` |

`--warn`/`--danger` (and their glows) are **not** overridden in light today and stay that way.
**Light theme to be eyeballed before sign-off.**

## Token remapping rules

1. **Orange retirement.** Delete `--panw-orange*`. Audit the ~10 raw `#FA582D` usages + any
   `var(--panw-orange…)` references; reassign each by *intent* — failure/alert → `--danger`,
   decorative highlight → `--accent`. Acceptance: zero `#FA582D` and zero `--panw-orange` left.

2. **Legacy aliases repoint, don't break.** `--cyan/--amber/--green/--red/--purple` stay so
   existing references keep resolving. They follow the new palette:
   - `--cyan → --accent` (now genuinely teal — alias becomes accurate)
   - `--green → --success` (now emerald)
   - `--purple → --info` (now cobalt)
   - `--red → --danger` ⚠️ **repointed** off the retired orange (finally an actual red)
   - `--amber → --warn` ⚠️ **repointed** — see risk below

3. **`--success` split from `--accent`.** They are identical today (`#00CC66`). Splitting
   success to emerald `#1FBE74` is the one genuinely new token; audit `--success` usages to
   confirm none silently relied on "success == accent."

## Surfaces & rollout

| # | Surface | What changes |
|---|---|---|
| 1 | `api/static/index.html` | Dark `:root` + light block per tables above; sweep raw hex that bypasses tokens — ~28 `#00CC66`, ~10 `#FA582D`, plus old secondary blue `#5EB3FF`/`#8DCBFF` (count TBD). Primary surface. |
| 2 | `api/static/setup.html` | Align any local accent usage to the new tokens. |
| 3 | `docs/pages/styles.css` | Landing keeps its own copy: `--accent #00CC66→#14B8A6`, `--info #00C0E8→#4C8DFF`, `--warn #F5A623→#F5B544`, `--danger #E54B4B→#F2555F`, `--accent-ink #001a0d→#04140f`, glow → teal. |
| 4 | `cli/COLOR_SCHEME.md` + Rich CLI | Map accent/success/info to teal/emerald/cobalt (Rich accepts hex). |
| 5 | `README.md` | shields.io badge color params → teal `14B8A6`. |
| 6 | CSS comments | Reword brand-name comments (e.g. `/* signature Cortex section-label tracking */`) to neutral language. Trivial. |

Rollout order: **1 → validate → 2,3,4,5 in parallel**. Commit per surface (named files) at sensible boundaries.

## Acceptance criteria

- [ ] All dark `:root` tokens match the palette table; light block matches the light table.
- [ ] `--panw-orange*` and `--glow-orange` deleted; `--red`/`--glow-red` repointed to danger.
- [ ] **Grep guard (hard):** `0` occurrences of `#00CC66` (any case) and `#FA582D` across `index.html`, `setup.html`, `docs/pages/styles.css` — these two are the Cortex tells and must be gone.
- [ ] **Sweep (soft):** old secondary blue `#5EB3FF`/`#8DCBFF` and the old warn/danger literals `#FFB020`/`#F23E3E`/`#52E89E` reassigned to their new values except where intentionally retained.
- [ ] **WCAG:** `--accent #14B8A6`, `--info #4C8DFF`, `--success #1FBE74` each clear **≥4.5:1** as text on `#0B0F14`; UI elements ≥3:1. (Teal computes ~7.8:1; all three pass — to be re-verified.)
- [ ] **Visual pass** on the running console: BUILD/OPERATE/LIBRARY/ADMIN tabs, run summary panel, primary + ghost buttons, status pills (running/ready/failed), links, glows.
- [ ] Landing page, CLI, and README read as one palette with the console.

## Risks & open questions

- **Alias misnomer (highest-risk).** `--amber` and `--cyan` currently *both alias the green
  accent* — they render green despite their names. Repointing `--amber → --warn` will flip any
  green element using `var(--amber)` to amber. **Audit `--amber`/`--cyan` usages before repointing**;
  if a usage wants the brand color, leave it on `--accent`.
- **`success == accent` assumption.** Confirm no component depends on success being the same hex as accent.
- **Light theme sign-off.** Light values are proposed, not yet eyeballed.
- **Landing background un/ify (optional).** Landing uses `--void #0a0a0a` / `--bg #141414`; console
  uses `#070A0F` / `#0B0F14`. Aligning them is optional polish, not required for this change.
- **Success glow (optional).** `--glow-green` aliases `--glow-accent` (teal). If a true-emerald
  success glow is wanted, define `--glow-success` from `#1FBE74`. Non-blocking.

## Future (deferred, not this change)

- Extract one shared `tokens.css` consumed by console + landing, killing the duplicate palette copy (the split-brain risk).
- Full Oh NO LLC identity: typography, "Cortex Console" naming/logo, multi-product design system.
