# Enclave Dashboard — Figma Design Brief

> Paste this into a Figma plugin session, then run `/figma-generate-design`. The brief is structured as a build sheet: tokens → primitives → components → screens → states → motion. Feed it top-down.

**Source of truth in code:** [api/static/index.html](../api/static/index.html) (4798 LOC, single-file dashboard). Tokens defined at the top of `<style>`. **Public site companion** (Vault Terminal aesthetic, just shipped): [docs/pages/index.html](pages/index.html), [docs/pages/styles.css](pages/styles.css). Match it.

---

## 0 / Aesthetic

**Codename:** Vault Terminal.
**One-line:** A sovereign-AI ops console rendered as if the operator just SSH'd into the box. HUD chrome over real data. No marketing softness, no rounded-everything, no purple gradients. Pure black, single green accent, monospace anchored, Space Grotesk used surgically for headlines and metrics.

**Reference moods:** Bloomberg terminal, Frame.io v3 Inspector, Linear command bar, NASA flight ops MCC consoles, the Heretic's `git log --oneline` aesthetic.

**Anti-references (do NOT pull from):** Vercel landing pages, Stripe Atlas, Notion, generic SaaS dashboards with rounded `12px` cards on `#fafafa`.

---

## 1 / Tokens

Create a Figma local-variable collection named `enclave/dark` with these primitives. Treat them as the only legal values; component fills and strokes must reference these tokens by name.

### Color (mode: dark — the only mode for v1)

| Token | Hex | Use |
|---|---|---|
| `bg/void` | `#0A0A0A` | Page ground |
| `bg/base` | `#141414` | Panel surface (opaque) |
| `bg/panel` | `rgba(20,20,20,0.7)` | Panel surface (over scan-lines) |
| `bg/deep` | `#050505` | Code blocks, chat-message field |
| `border/base` | `#2A2A2A` | Default 1px stroke |
| `border/soft` | `#1C1C1C` | Hairline dividers |
| `border/glow` | `rgba(0,204,102,0.10)` | Panel glow seam |
| `accent/green` | `#00CC66` | Primary accent — single source |
| `accent/dim` | `rgba(0,204,102,0.38)` | Corner ticks, focus rings |
| `accent/ghost` | `rgba(0,204,102,0.08)` | Inline code background, hover wash |
| `accent/ink` | `#001A0D` | Text color on green button fills |
| `semantic/info` | `#00C0E8` | Info accents (install notes, links) |
| `semantic/warn` | `#F5A623` | Warnings only |
| `semantic/danger` | `#E54B4B` | Errors only |
| `text/primary` | `#E6E6E6` | Body text |
| `text/dim` | `#8D8D8D` | Secondary text |
| `text/muted` | `#555555` | Disabled / `//` glyph |

**Glow** is achieved with a duplicated layer of accent at 22% opacity, blur 12px, plus a tighter copy at 18% / 3px. Bake as effect styles `glow/sm` and `glow/lg`.

**Forbidden:** any hue outside this list. No `#1976d2`, no `#7c3aed`, no Tailwind defaults, no Material elevations.

### Type

Two families. No third.

- **Mono** — `JetBrains Mono` (400, 500, 600, 700). Default for everything: chrome, body, data, labels, code.
- **Sans** — `Space Grotesk` (300, 400, 500; italic 400/500). Reserved for: hero headline, section heads, metric values (the big numbers), and emotional callouts. Never for body or labels.

**Type ramp** (use as Figma text styles named `type/<scale>`):

| Style | Family | Size / Line | Weight | Tracking | Use |
|---|---|---|---|---|---|
| `display/hero` | Sans | 56–72 / 0.98 | 500 | -2.5% | Hero headline |
| `display/lg` | Sans | 32 / 1.05 | 500 | -1.5% | Section heads |
| `display/metric` | Sans | 24 / 1.1 | 500 | -1% | Big numbers in panels |
| `mono/eyebrow` | Mono | 11 / 1.4 | 600 | +28% | `// PANEL LABEL` |
| `mono/tab` | Mono | 11 / 1.5 | 500 | +20% | Tab labels |
| `mono/body` | Mono | 13 / 1.6 | 400 | 0 | Default body |
| `mono/data` | Mono | 13 / 1.5 | 500 | 0 | Tabular data |
| `mono/cta` | Mono | 11 / 1 | 600 | +22% | Button labels |
| `mono/micro` | Mono | 10 / 1.4 | 400 | +8% | Footer / micro copy |
| `mono/code` | Mono | 12 / 1.7 | 400 | 0 | Inline + block code |

**Italic green** (Space Grotesk italic + `accent/green`) is the brand's emotional accent. Use **once** per surface — for the word that earns the screen. Never two italics on one screen.

### Spacing

4-pt base. Approved steps: 4, 8, 12, 16, 20, 24, 32, 48, 72, 96, 120. Anything else is a bug.

### Radii

Sharp by default. `0` for panels, `2px` for buttons, `4px` for inputs, `50%` for status pips. **Never** ≥ 6px. The HUD aesthetic depends on hard corners.

### Effects

- `glow/sm` — `0 0 12px rgba(0,204,102,0.22), 0 0 3px rgba(0,204,102,0.18)`
- `glow/lg` — `0 0 24px rgba(0,204,102,0.35), 0 0 6px rgba(0,204,102,0.22)`
- `scan-lines` — repeating linear gradient, 3px period, white at 1.4% opacity. Apply as a fixed overlay layer on the page artboard, **not** per panel.

---

## 2 / Primitives

Build these as Figma components first; everything else composes from them.

### `Corner Tick`
- 14×14 vector, two strokes meeting at one corner, 1px, color `accent/dim`.
- Variants: `tl`, `tr`, `bl`, `br`. Used at panel and entry corners — never alone.

### `// Marker`
- Pure text node, `mono/eyebrow`, color `text/muted`, content `//`. Always followed by a 6px gap and a label in `accent/green`.
- Variants: `inline` (label inline) and `prefix` (label below).

### `Status Pip`
- 7×7 circle, `glow/sm`. Variants:
  - `online` — fill `accent/green`, pulse animation 2.4s.
  - `warn` — fill `semantic/warn`.
  - `offline` — fill `semantic/danger`, no pulse.
  - `idle` — fill `text/muted`, no pulse, no glow.

### `Caret`
- 4px-wide vertical bar, height = 1em, color `accent/green`. Blink animation 1.05s, 50% duty.

### `Boot Line`
- Horizontal layout: `Status Pip` + mono text + caret. Default copy: `> enclave.local — kernel ready [ OK ]`. Variants for: `booting`, `ready`, `degraded`, `offline`.

---

## 3 / Components

### `Panel`
The HUD frame. Every dashboard surface uses it.

- Auto-layout, vertical, padding 24, gap 14.
- Fill `bg/panel`, stroke `border/soft` 1px.
- Four `Corner Tick` instances pinned to corners (tl, tr, bl, br).
- Slot 1: `// Marker` + label (`mono/eyebrow`, color `accent/green`).
- Slot 2: body content.
- States: `default`, `hover` (stroke shifts to `accent/dim`), `loading` (body content swaps to `Loader`), `empty` (body content swaps to `Empty`).

### `Tab Nav`
- Horizontal auto-layout, gap 0, border-bottom 1px `border/soft`.
- Children = `Tab Btn` instances. **Recommended restructure:** group the 8 tabs under three section labels — `OPERATE` (Dashboard, Models, Memory), `KNOWLEDGE` (Discover, Research, Documents), `BUILD` (Workflows, Agents). Section labels are `mono/micro`, color `text/muted`, with a 14px gap before the next group's tabs. This is the single biggest UX delta from current.
- Mobile: collapses into a left drawer; design the drawer as a separate frame.

### `Tab Btn`
- Auto-layout, padding 12×24, gap 6.
- Default: text `mono/tab` color `text/dim`, transparent border-bottom.
- Hover: text `text/primary`, background `rgba(255,255,255,0.025)`.
- Active: text `accent/green`, border-bottom 2px `accent/green`, effect `glow/sm`.
- Optional `Tab Count` chip: text `mono/micro` color `text/muted`, +6px left margin. Active state colors it `accent/dim`.

### `Action Btn`
Three variants. **Default to ghost** for chrome; only one solid per surface.

- `solid` — fill `accent/green`, text `accent/ink`, padding 14×24, radius 2px, effect `glow/sm`. Hover lifts 1px and fires `glow/lg`. Prefix `▸`.
- `ghost` — transparent, stroke `border/base`, text `text/primary`, padding 14×24, radius 2px. Hover stroke → `accent/dim`, text → `accent/green`. Prefix `//`.
- `icon` — 32×32 square, transparent, stroke `border/base`. Hover stroke → `accent/dim`.

### `Metric Row`
- Horizontal auto-layout, justify space-between, padding 8×0, border-bottom 1px `rgba(255,255,255,0.04)`.
- Left: key in `mono/data` color `text/dim`.
- Right: value in `mono/data` color `text/primary`. Variant `highlight` colors value `accent/green`.

### `Gauge` (radial)
- 90×90 frame, two stacked SVG circles.
- Track: stroke 4px, color `border/base`.
- Fill: stroke 4px, `stroke-linecap: round`, color `accent/green`, effect `glow/sm`.
- Center stack: `display/metric` value + `mono/micro` label, both centered, color matches stroke.
- Document the conversion: `dashOffset = circumference * (1 - pct/100)` where `circumference ≈ 238.76` for r=38.

### `Status Card` (model card)
- Auto-layout, horizontal, justify space-between, padding 8×12.
- Background `rgba(255,255,255,0.025)`, stroke 1px `rgba(255,255,255,0.05)`, **left border 2px** `accent/dim` — the colored rail is the brand mark on the row.
- Hover: rail shifts to `accent/green`, background brightens slightly.
- Slots: model name (`mono/data`) + size badge (`mono/micro` color `text/dim`).

### `Chat Message`
Two flavors, distinguished by alignment, fill, and a 3-letter label prefix.

- `user`:
  - Background gradient `accent/green` 6% → 2%, left border 2px `accent/dim`.
  - Self-aligned right, max-width 85%.
  - Top-line label `YOU` in `mono/micro` color `accent/dim`, +6px gap.
- `assistant`:
  - Background gradient white 4% → 2%, left border 2px `accent/dim`.
  - Self-aligned left, max-width 85%.
  - Top-line label `AI` in `mono/micro` color `accent/dim`.
- `system`: centered, no fill, color `text/muted`, `mono/micro`.

### `Loader` (in-world)
Replaces `loading...` strings. Three variants:

- `boot-bar` — 6 cells, fills left-to-right, 80ms each. ASCII: `[ ████░░░░░░ ]`.
- `scan-line` — 1px horizontal line travelling top-to-bottom inside the panel body, `accent/green` with `glow/sm`, 1.6s loop.
- `dots` — three pips pulsing in sequence.

### `Empty`
For panels with no data. Centered stack: a 24×24 line-icon, label in `mono/micro` color `text/muted`, optional ghost CTA.

---

## 4 / Screens

Build at 1440×1024 desktop and 375×812 mobile. Both as full frames in the same page.

### Screen 01 — `Dashboard / Default`
1. Top bar, 67px tall: logo (Enclave mark + wordmark), spacer, `mono/micro` clock + uptime, `// Marker` separators.
2. Tab nav with three section labels (see `Tab Nav` above).
3. Grid 12 col, gutter 16:
   - **Row 1, span 12:** Chat panel (primary surface, the panel that earns the screen). Header has `// CHAT INTERFACE` label + model select + System / Export action btns. Body has scrolling messages, default 380px tall. Composer at bottom: textarea + send btn + retrieval toggle.
   - **Row 2 col 1–4:** System Status panel, 4 metric rows (API, Ollama, Models, Version), each with status pip.
   - **Row 2 col 5–8:** Loaded Models panel, 3–5 status cards.
   - **Row 2 col 9–12:** Performance panel, 2 gauges (CPU, MEM) + 2 metric rows (Cores, RAM).

### Screen 02 — `Dashboard / Loading`
Same layout, every panel body uses a different `Loader` variant. Goal: show the boot sequence as a designed event, not a vacuum.

### Screen 03 — `Dashboard / Mobile`
Header collapses to logo + hamburger. Tab nav becomes a left drawer overlay. Panels stack single-column. Chat takes 70vh.

### Screen 04 — `Models tab`
Toolbar with search + filter chips, then a vertical list of `Status Card` instances at row height 48px. Right rail (col 9–12) shows the selected model's detail panel.

### Screen 05 — `Workflows tab`
Drawflow canvas placeholder (just sketch the node aesthetic): nodes are `Panel` instances at 160×80 with 1.5px stroke, mono node title in `accent/green`, two ports per side rendered as 8px squares.

### Screen 06 — `Agents tab`
Card grid 3-up, agent cards built from `Panel` + `Status Card` patterns. Each card has: agent avatar (vector mark, not photo), name, role, current model, `// CONTEXT SOURCES` block.

### Screen 07 — `Settings & Permissions`
Two-column form layout. Left rail nav (Operate / Keys / Storage / Permissions). Right body uses stacked `Panel` groups, each with `// SECTION` markers and `Metric Row` for read-only values, inputs for editable.

---

## 5 / States to capture

For each interactive component, design these explicitly as variants — don't leave them implicit.

- **Default**
- **Hover** — usually stroke or text shifts toward `accent/green`.
- **Active / Pressed** — border becomes `accent/green` solid, fill brightens by 4–6% lightness.
- **Focus-visible** — 2px outline `accent/green`, offset 2px, radius 2px. Required for keyboard a11y.
- **Disabled** — text → `text/muted`, stroke → `border/soft`, no hover effect, cursor not-allowed.
- **Loading** — body swaps to a `Loader` variant.
- **Empty** — body swaps to an `Empty` variant.
- **Error** — left border becomes 2px `semantic/danger`, body shows error text in `text/primary`.

---

## 6 / Motion

Capture these as Figma Smart Animate transitions between named frames. Keep durations short — operators don't have time for theatre.

| Motion | Duration | Curve | Description |
|---|---|---|---|
| Tab change | 160ms | ease-out | Underline slides; body cross-fades 80ms. |
| Panel hover | 180ms | ease-out | Stroke `border/soft` → `accent/dim`. |
| Button hover (solid) | 180ms | ease-out | translateY -1px, glow `sm` → `lg`. |
| Boot sequence (page load) | 0–1.5s | staggered | Pip on (0ms), boot text fade (200ms), tag in (500ms), headline up (700ms), subtitle (950ms), CTAs (1150ms), specs (1350ms). |
| Status pip pulse | 2400ms | ease-in-out infinite | Opacity 1 → 0.35 → 1. |
| Gauge fill | 1000ms | ease | Stroke-dashoffset only; never fade in. |
| Caret blink | 1050ms | steps(2) infinite | Hard on/off. |

**Reduced-motion mode:** disable boot sequence, pulse, blink. Components appear in final state instantly. Document this as a separate frame variant.

---

## 7 / Iconography

- **Enclave mark** — already canonicalized in code: four nested rectangles, 80×80 viewBox, currentColor stroke. Bring it in as a Figma component, sized at 24, 32, 48.
- **Glyphs** — Lucide line icons at stroke 1.5px, color `text/dim`. No filled icons. No multi-color icons. No Material rounded.
- **No emoji.** The aesthetic doesn't tolerate them.

---

## 8 / Acceptance gate

Don't deliver until all of these pass:

1. ✅ Every component fill, stroke, and text color references a token by name. No hex literals on layers.
2. ✅ Every component has all eight states above where applicable.
3. ✅ Tab nav uses the three-section grouping (Operate / Knowledge / Build).
4. ✅ Loaders are designed; no `"loading..."` text strings remain.
5. ✅ Mobile screen doesn't horizontal-scroll at 375px.
6. ✅ Boot sequence motion is documented as a sequenced prototype.
7. ✅ Type styles match the ramp; no rogue sizes.
8. ✅ Italic green appears at most once per screen.
9. ✅ Reduced-motion variant exists and disables all infinites.
10. ✅ Public site (`docs/pages/`) and dashboard share `accent/green = #00CC66` exactly. Verify against the running landing page.

---

## 9 / Hand-off notes (for code generation)

When the Figma design is ready and you want it back into code:

- **Tokens** translate 1:1 to the existing CSS variables in [api/static/index.html:17-67](../api/static/index.html). Don't introduce a parallel token system; extend the existing one.
- **Inline styles must die.** Current dashboard has dozens of `style="..."` blocks (e.g. [api/static/index.html:1505](../api/static/index.html), [:1671](../api/static/index.html), [:4404](../api/static/index.html)). Hand-off should produce class-based replacements that reference `var(--*)`.
- **No new fonts.** Hand-off must use only `var(--mono)` and `var(--sans)`.
- **No new accent colors.** If a Figma layer uses an unlisted color, it's a bug in the design — fix it in Figma, don't import it.

---

*Brief author: design pass against [api/static/index.html](../api/static/index.html) as of 2026-05-07. Public-site companion shipped same day in [docs/pages/](pages/).*
