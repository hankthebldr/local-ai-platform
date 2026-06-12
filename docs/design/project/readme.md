# Enclave — Design System

> **Enclave** is a self-hosted local-AI platform: run LLMs on your own hardware
> with an OpenAI-compatible API, no telemetry, no cloud dependency. This design
> system captures the **rebranded, workflow-first** identity for Enclave's
> product surfaces — the operator console, marketing, and decks.

This is a *design* system: tokens, fonts, brand assets, reusable React
components, and high-fidelity UI-kit recreations of the product. An automated
compiler indexes everything here so other projects can design *as Enclave*.

---

## What Enclave is

Enclave runs LLMs on your machine. The pitch, in the product's own words:
*"Self-hosted LLM infrastructure with OpenAI-compatible API. CPU-optimized.
Source-available."* It ships three ways — a macOS DMG, a Docker stack, and a
pip-installable Python engine — and exposes a single SPA console at
`localhost:8000`.

The product's center of gravity has moved. Early on it was an **inventory** of
the AI ecosystem (models, agents, plugins, a knowledge graph). It is now about
the **workflow itself**: composing multi-agent DAGs, managing the context that
flows between steps, and exploring / tuning / running those pipelines. This
design system reflects that shift — **the Workflow Composer is the home
screen**, and everything else (Models, Context, Runs, Catalog) orbits it.

Core concepts in the product vocabulary:

| Term | Meaning |
|---|---|
| **Workflow** | A DAG of steps, authored on the Composer canvas, exported as YAML. |
| **Step** | One node in the DAG. Has a *role*, a model, a prompt, optional skills/tools. |
| **Role** | `reasoning · coding · fast · general · uncensored` — picks the model class. |
| **Agent** ("Gem") | A reusable persona: role + model + system prompt + pinned context. |
| **Skill** | A markdown prompt that auto-injects on trigger keywords. |
| **Plugin / MCP** | External tools made callable from steps (MCP = Model Context Protocol). |
| **Run** | One execution of a workflow; streamed live, checkpointed, resumable. |
| **Context** | Documents + a knowledge graph the workflow draws on (RAG). |
| **Project** | A named bundle that scopes workflows, agents, MCP refs, and chats. |

The fleet it targets: a Mac M4 Pro (dev), an MS-01 (API serving), and a BD790i
96 GB box (70B-class research). Single-operator, sovereign-appliance ethos.

## The rebrand (what changed and why)

The shipped product was skinned to **PANW Cortex** — Cortex green (`#00CC66`),
cool blue, and a sparing PANW orange on a cold blue-slate canvas. The owner
wants to move to **their own** thematics:

- **Dark, warm-charcoal background** with grey tones (not cold blue slate).
- **Teal** as the living primary signal (`--teal-400 #2BD4B4`).
- **Deep emerald** for structure and success (`--emerald-500 #149468`).
- **Soft, approachable "Ubuntu-grub" warmth** — a restrained **ember**
  (`--ember-400 #E08A4C`) used sparingly, like Ubuntu's terminal aubergine/orange.

The result keeps Enclave's terminal-adjacent, blueprint precision but makes it
**warmer and more humane** — a console you'd actually want to live in.

## Sources

Everything here was derived from the owner's repository. If you have access,
read it to design with higher fidelity:

- **GitHub:** [`hankthebldr/local-ai-platform`](https://github.com/hankthebldr/local-ai-platform)
  (branch `master`). Notable paths:
  - `api/static/index.html` — the 20k-line SPA console (token system, Composer,
    tabs, Drawflow canvas). The source of truth for the rebrand.
  - `assets/` — logos, icons, blueprint illustrations, brand palette (imported here).
  - `api/static/vendor/fonts/` — Space Grotesk + JetBrains Mono webfonts (imported here).
  - `README.md`, `CLAUDE.md`, `MODELS.md`, `CHANGELOG.md` — product context.
- **Product page:** https://hankthebldr.github.io/local-ai-platform/

You can explore that repository further to build richer, more accurate Enclave
designs than this snapshot captures.

---

## Content fundamentals

> *How Enclave writes. Match this voice in any copy you produce.*

**Register: operator-to-operator, terse, technical, unpretentious.** Enclave
talks to someone who runs their own infrastructure and respects their time.
No marketing fluff, no hype, no exclamation marks. Confidence comes from
precision, not adjectives.

- **Person.** Second-person imperative for instructions ("Point your existing
  code at `localhost:8000`", "Drag a role onto the canvas to add a step").
  Third-person for descriptions of the system ("The composer above is the
  design surface"). Rarely first-person; never "we're so excited".
- **Sentence shape.** Short. Often fragments. A colon then the payload:
  *"Three paths — pick one."* Em-dashes and bullets carry structure.
- **Casing.** Sentence case for body and most UI. **UPPERCASE + wide tracking**
  for section labels and metadata keys (`SYSTEM PROMPT`, `LOADED`, `CPU`) — the
  signature mono-label move. Tab names are Title Case single words
  (`Composer`, `Runs`, `Models`, `Context`).
- **Numbers are concrete.** "7B at 40-50 tok/s", "~6 GB free disk", "16 routers
  / 22 services". Specificity is the brand's flex — but never invent data slop;
  every number must mean something.
- **Code is first-class.** Inline `code`, shell snippets, YAML, and file paths
  appear inline in prose. Monospace is part of the voice, not decoration.
- **Honest about limits.** "currently **not signed/notarized**", "Paid-product
  activation will replace this flow in a future build." Enclave tells you what
  isn't done yet.
- **Emoji:** essentially none in product UI. Occasional functional glyphs
  (`⚡`, `▶`, `▾`, `⛶`, `☾`) act as icons, not decoration. Do not add emoji.
- **Vibe words:** *self-hosted, sovereign, local-first, operator, appliance,
  compose, orchestrate, workflow, context, run.* Avoid: *seamless, magical,
  revolutionary, unleash, supercharge.*

Examples (lifted from the product):
- > "The composer above is the design surface — the chat below is the
  > interaction surface for the agents you build."
- > "Drag an agent to spawn a step pre-configured with its role, model, and
  > system prompt."
- > "No data leaves your machine unless you opt in."

---

## Visual foundations

> *The look: a warm-charcoal operator console — blueprint precision, terminal
> calm, a teal pulse of life. Approachable, not clinical.*

**Color.** Dark is the hero; light is a courtesy scope. The canvas is a warm
charcoal with a faint green-grey undertone (`--bg #101413`), never pure black,
never blue slate. **Teal** (`#2BD4B4`) is the single primary — used for active
state, CTAs, focus, live signals, and the logotype. **Deep emerald**
(`#149468`/`#1FB983`) handles structure and success. **Ember** (`#E08A4C`) is
the warm spark, used *sparingly* — a co-brand mark, a highlight, the
"uncensored" node tint. Status: emerald = success, amber = warn, warm coral =
danger, soft cyan-teal = info. Accents always sit on dark surfaces; on a teal
fill, text is near-black (`--on-accent #06201B`).

**Type.** Two faces. **Space Grotesk** (300–700) is the humane geometric sans —
UI, headings, body; it's the "soft" in the brand. **JetBrains Mono** (300–700)
is the operator's voice — section labels, IDs, code, data, terminal output, the
logotype. The signature is the **caps-tracked mono label**: `text-xs`, uppercase,
`0.18em` tracking, muted color — it frames every panel and metadata row.
Headings are tight (`-0.02em`), balanced wrap. Base size is **14px** (dense
console); never below `--text-xs` (~9.6px) for labels.

**Spacing & layout.** 4px base grid, dense at the low end. Layout is rail-based:
a left navigation rail, a center canvas/content area, an optional right
inspector, and (on the Composer) a bottom **agent-chat dock**. Fixed top bar.
Generous internal padding inside panels; tight gaps between dense data rows.
Always lay rows/toolbars out with flex/grid + `gap`.

**Surfaces, borders, corners.** Elevation is built from layered charcoals
(`--surface-card #171C1A` → `--surface-overlay #1F2522`) plus soft dark shadows
with a 2%-white top highlight. **Panels are near-square and crisp** (radius
0–5px) — the mil-spec calm; **cards** take a small soft radius (`--radius-md 8px`);
modals 12px. Borders are a 1px warm-grey hairline (`--border #28302D`); active/
focused elements get a teal-tinted rule (`--border-glow`). A signature flourish:
**corner ticks** (`.corner-tr`/`.corner-bl`) — tiny L-shaped teal marks at panel
corners, a blueprint registration detail.

**Backgrounds & texture.** Mostly flat warm-charcoal fills. Hero/empty states
use the blueprint **illustrations** — dark gradient grounds (`#0a0a0a → #0d1520`),
monospace node-diagrams, nested containment rectangles (the *enclave* motif),
dashed boundary strokes. A faint dot-grid or subtle radial vignette is
acceptable on large empty canvases; avoid heavy gradients and never use
bluish-purple gradients.

**Glows & transparency.** Glows are *small, sharp halos*, not ambient bloom —
a 1px teal ring + ~14px soft shadow on live elements. Translucent panels
(`--surface-panel`, 86% alpha) use a `14px` backdrop blur — for the top bar,
popovers, and floating canvas controls. Use blur for floating-over-content
chrome; keep base surfaces opaque.

**Motion.** Calm and quick. The base UI is still; motion is a thin polish layer:
`--t-fast 140ms` micro hover lifts (`translateY(-1px/-2px)`), focus rings, tab
fade-ins (`ds-fade-in`), and a single **living pulse** on active status pips
(`ds-pip-pulse`, 2.4s teal heartbeat). Live workflow edges get a flowing dash
(`ds-flow-dash`). Easing is `--ease-out cubic-bezier(.16,1,.3,1)`. **No bounces,
no decorative infinite loops on content.** Everything degrades under
`prefers-reduced-motion`.

**Hover / press.** Hover: subtle lift + border warms to `--accent-dim` + faint
elevation shadow. Buttons brighten toward `--accent-bright`. Press: settles back
down (`translateY(0.5px)`), no color flash. Cards lift `-2px` on hover.

---

## Iconography

Enclave's shipped console is **icon-light**: it leans on the caps-tracked mono
labels and a handful of **functional Unicode glyphs** rather than a dense icon
set. That restraint is the brand — an operator console, not a consumer app.

- **Functional glyphs (in product today):** `⚡` engage-step, `▶` run, `▾`
  expand/collapse, `⛶` fullscreen, `⚙` admin, `☾` theme toggle, `⌘K` shortcuts,
  `⋮⋮` drag-grip, `×`/`✕` close, `▸` caret. These act as icons, never as
  decoration. No emoji appear in the UI.
- **Logo motif as icon:** the nested-square enclave mark doubles as the app/
  favicon (`assets/icons/`) and a watermark on empty states.
- **Line-icon set (this system's choice):** for richer surfaces (UI kit, decks)
  use **[Lucide](https://lucide.dev)** at **1.75 stroke**, `currentColor`, 20–22px.
  Lucide matches the product's thin, geometric, monochrome line language better
  than filled or duotone sets. Loaded from CDN
  (`unpkg.com/lucide`) — see `guidelines/brand-iconography.html`. **This is a
  substitution:** the repo ships no icon font or SVG icon library of its own
  (only blueprint *illustrations*), so Lucide is the recommended stand-in. If
  you adopt a different set later, keep the thin-stroke monochrome rule.
- **Illustrations, not icons, carry imagery:** `assets/illustrations/` holds
  blueprint node-diagrams (dark gradient ground, monospace labels, nested
  containment rectangles, dashed boundaries). Recolored here to teal/emerald/
  ember. Use them for hero and empty states; don't redraw them by hand.
- **Color:** icons inherit text color by default (`--text-dim`), warm to
  `--accent` (teal) when active/selected. Status icons take the semantic hue.

---

## Data visualization & analytics

> *Calm analytics: charts are instruments, not decoration. The test for any
> chart — which action does it change?*

- **Sparklines first.** The default viz is a sparkline beside the number it
  explains (`Sparkline`, `TrendStat`). Full charts (`UtilChart`) only when the
  *shape* of the series carries the decision — thresholds, spikes, drift.
- **Series colors are fixed:** accent teal → emerald → info, three series max.
  **Amber is reserved for thresholds, coral for failures.** Past three series,
  use a table.
- **Honest axes:** utilization/rate axes start at zero; hairline grid at
  0/50/100; mono labels on the right; no truncation to dramatize.
- **Thresholds, not alarms:** capacity limits are a dashed amber line in the
  chart — no flashing, no toasts.
- **Data ink only:** 8–10% area fills, ~1.5px strokes, latest-point dot only,
  no shadows/smoothing/3D. Deltas compare like periods; `deltaGood={false}`
  flips colors where up is bad (latency, memory pressure).
- **No dashboard pages.** Numbers render where decisions happen: composer
  (memory budget), run rows (throughput), model peeks (role fit), fleet flyout.
- Full guidance card: `guidelines/data-visualization.html`.

---

## Index — what's in this system

| Path | What |
|---|---|
| `styles.css` | **Global entry.** Import manifest only; link this one file. |
| `tokens/colors.css` | Raw color ramps + semantic aliases (teal/emerald/ember/charcoal). |
| `tokens/typography.css` | Font families, weights, type scale, tracking. |
| `tokens/spacing.css` | 4px grid, radii, elevation, layout rhythm vars. |
| `tokens/motion.css` | Easings, durations, keyframes. |
| `tokens/base.css` | Reset + element defaults (canvas, scrollbars, focus). |
| `fonts/` | Space Grotesk + JetBrains Mono webfonts + `fonts.css`. |
| `assets/logo/` | Enclave mark + lockup (nested-square "enclave" motif). |
| `assets/icons/` | App icons / favicons. |
| `assets/illustrations/` | Blueprint node-diagram art (recolored to teal/emerald). |
| `assets/brand/` | Color-palette specimen. |
| `guidelines/` | Foundation specimen cards (Design System tab). |
| `components/` | Reusable React primitives (see below). |
| `ui_kits/console-v2/` | **Canonical** chat-led operator console (interactive prototype). |
| `ui_kits/console/` | v1 workflow-first console — reference; v2 reuses its CSS/primitives. |
| `SKILL.md` | Agent-Skill manifest for use in Claude Code. |

**Components** (under `components/`): `core/` — Button, IconButton, Badge,
StatusPip, Panel, Input, Select, Toggle; `workflow/` — WorkflowNode, RoleChip,
RunStatus, MetricStat; `console/` — EntityCard, SeedChip, MaturityMeter,
FitBar, ActionChip, WizardStepper (the chat-led console atoms); `dataviz/` —
Sparkline, TrendStat, UtilChart (calm analytics). See each directory's
`*.prompt.md` and `@dsCard`.

**UI kit v1 (reference)** — `ui_kits/console/` is the earlier workflow-first
console with the Composer as home. Superseded by v2, but kept because v2 reuses
its stylesheets and primitives, and its canvas / palette / inspector patterns
remain the source for the workflow-mode UI. It is a self-contained interactive
prototype (lightweight cosmetic components on the real tokens — it does not load
`_ds_bundle.js`, so it runs standalone): a left icon rail (Compose · Runs ·
Library · Context · Models), a top system-impact strip, and the Composer's
palette / DAG canvas / step-inspector / agent-chat dock. Click a palette item to
add a step, select a node to edit it, and hit **Run** to watch the DAG execute
live. Files: `index.html` (boot), `data.js` (mock data), `console.css` +
`composer.css` (styling), `primitives.jsx` (cosmetic atoms), `Composer.jsx`
(home), `views.jsx` (Runs / Library / Models / Context + shell).

**UI kit (canonical)** — `ui_kits/console-v2/` is the **chat-led** operator
console. The thesis: *every object is born in a
conversation* — a thread is seeded (role + model + context), replies get pinned
as steps, and at 2+ pins the thread converts: a DAG is scaffolded and the
Composer canvas opens as an **in-shell pivot** (Chat ↔ Canvas on the same
thread), with the conversation docked as the test surface. Also in the kit: the
unified **EntityCard → peek panel** drill-down for every entity type, a model
**compare** strip that ends in "seed a chat", the 4-phase **install wizard**
(source → configure → verify → land; verify is always a conversation), per-step
**test benches** in the inspector, next-best-action nudges, and the
**operator's path** adoption ladder in the topbar. It reuses v1's stylesheets
and primitives — files: `index.html`, `data2.js`, `console2.css`, `parts2.jsx`,
`ChatHome.jsx`, `CanvasMode.jsx`, `Library2.jsx`, `shell2.jsx`. The wireframe
rationale behind it lives in `explorations/console-v2/`.

> Namespace for `@dsCard` HTML: `window.EnclaveDesignSystem_47ed55`.
