---
name: enclave-design
description: Use this skill to generate well-branded interfaces and assets for Enclave, the self-hosted local-AI / workflow-first platform — either for production or throwaway prototypes/mocks/decks. Contains essential design guidelines, colors, type, fonts, assets, and UI-kit components for prototyping.
user-invocable: true
---

# Enclave Design Skill

Read `readme.md` in this skill first — it carries the full brand: product
context, the rebrand rationale (warm-charcoal + teal + deep emerald + sparing
ember), content/voice fundamentals, visual foundations, and iconography.

Then explore the other files:

- **`styles.css`** — the one stylesheet to link. It `@import`s the tokens and
  fonts. Everything downstream uses its CSS custom properties (`--accent` teal,
  `--accent-2` emerald, `--bg` warm charcoal, `--font-mono`, `--font-sans`, …).
- **`tokens/`** — colors, typography, spacing/radii/elevation, motion, base reset.
- **`fonts/`** — Space Grotesk + JetBrains Mono webfonts.
- **`assets/`** — logos (nested-square "enclave" mark, teal + original variants),
  app icons, recolored blueprint illustrations.
- **`guidelines/`** — foundation specimen cards (each is a tiny standalone HTML).
- **`components/`** — React primitives (`core/` + `workflow/`). Each has a
  `.jsx`, a `.d.ts` props contract, and a `.prompt.md` with usage.
- **`ui_kits/console/`** — the workflow-first operator console, a self-contained
  interactive prototype you can lift screens and patterns from.

## How to work

If you are creating **visual artifacts** (slides, mocks, throwaway prototypes,
landing pages): copy the assets you need out of `assets/`, link `styles.css` (or
inline the tokens), and produce static/interactive HTML for the user to view.
Reuse the `ui_kits/console/` CSS and component patterns rather than reinventing.

If you are working on **production code**: copy assets and read the rules here to
become an expert in the brand. The `components/*.jsx` are ready to adapt; the
tokens map cleanly onto a real stylesheet.

Non-negotiables to honor (see `readme.md` for the why):

- **Dark is the hero.** Warm-charcoal canvas, never pure black or blue slate.
- **Teal leads, emerald structures, ember is rare** (≤ 5% of a screen).
- **Two faces:** Space Grotesk (humane sans) + JetBrains Mono (the operator's
  voice — caps-tracked uppercase labels frame everything).
- **Workflow-first IA.** The Composer/DAG is the center of gravity.
- **Voice:** operator-to-operator, terse, technical, concrete numbers, no hype,
  no emoji in UI. Functional glyphs and thin Lucide line icons only.
- **Motion is calm:** quick hover lifts, focus rings, a single teal status pulse.
  No bounces, no decorative loops.

If the user invokes this skill without other guidance, ask what they want to
build or design, ask a few focused questions (surface, audience, production vs.
throwaway, how many variations), then act as an expert Enclave designer who
outputs HTML artifacts **or** production code depending on the need.
