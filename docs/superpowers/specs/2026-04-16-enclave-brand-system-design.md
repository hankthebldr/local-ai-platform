# Enclave Brand System Design

**Date:** 2026-04-16
**Product:** Enclave (formerly "Local AI Platform")
**Company:** ohno llc
**Status:** Approved for implementation

---

## 1. Product Identity

**Name:** Enclave
**Tagline:** Self-hosted AI inference. CPU-optimized. One price. Forever.
**Bundle identifier:** `com.ohno.enclave`
**Domain concept:** An enclave is a distinct territory enclosed within foreign territory — self-hosted AI in a cloud-dominated world.

### Naming Conventions

| Context | Format | Example |
|---------|--------|---------|
| Logo/wordmark | All-caps monospace | `ENCLAVE` |
| Running text | Title case | Enclave |
| CLI commands | Lowercase | `enclave status` |
| File/URL slugs | Lowercase hyphenated | `enclave-installer` |
| macOS app | Title case with space | `Enclave` |
| DMG file | PascalCase | `Enclave.dmg` |
| Bundle ID | Reverse domain | `com.ohno.enclave` |

### Rename Scope

All references to "Local AI Platform" and "Cortex" in the codebase must be updated to "Enclave":

- `api/main.py` — FastAPI app title
- `api/static/index.html` — dashboard title, CSS variable names (Cortex → Enclave)
- `api/static/setup.html` — setup wizard title
- `desktop/app.py` — window title
- `desktop/setup_py2app.py` — CFBundleName, CFBundleDisplayName, CFBundleIdentifier
- `scripts/build_mac.sh` — Info.plist fields, DMG volume name
- `cli/chat.py` — welcome banner, prompt text
- `README.md` — full rewrite with new branding
- `CLAUDE.md` — update project overview section
- `cli/COLOR_SCHEME.md` — update references

---

## 2. Visual Direction: Fortress

Terminal-native. Hacker aesthetic. The tool speaks for itself.

The Fortress direction evolves the existing "Cortex" design system already present in the web UI CSS. This minimizes disruption — the palette is largely the same, with refinement and formal naming.

---

## 3. Color System

### Core Palette (Backgrounds & Surfaces)

| Token | Name | Hex | Usage |
|-------|------|-----|-------|
| `--color-void` | Void | `#0a0a0a` | Page/app background |
| `--color-deep` | Deep | `#1a1a2e` | Secondary background, borders with depth |
| `--color-surface` | Surface | `#141414` | Cards, panels, elevated surfaces |
| `--color-border` | Border | `#222222` | Default border color |

### Accent Palette (Interactive & Semantic)

| Token | Name | Hex | Usage |
|-------|------|-----|-------|
| `--color-green` | Terminal Green | `#00E87B` | Primary accent, success, active states, logo |
| `--color-cyan` | Signal Cyan | `#00C0E8` | Info, links, secondary accent |
| `--color-orange` | Alert Orange | `#FA582D` | Errors, warnings, destructive actions |

### Text Hierarchy

| Token | Name | Hex | Usage |
|-------|------|-----|-------|
| `--color-text-primary` | Primary Text | `#E0E0E0` | Headings, body text |
| `--color-text-secondary` | Secondary | `#888888` | Descriptions, labels |
| `--color-text-muted` | Muted | `#555555` | Captions, placeholders, disabled |

### Semantic Mapping

- **Success:** Terminal Green `#00E87B`
- **Info:** Signal Cyan `#00C0E8`
- **Warning:** Alert Orange `#FA582D`
- **Error:** Alert Orange `#FA582D`
- **Active/Selected:** Terminal Green `#00E87B` at 15% opacity background + full opacity border

---

## 4. Typography

### Font Stack

| Role | Font | Weights | Fallback |
|------|------|---------|----------|
| Primary (headings, UI, code) | JetBrains Mono | 400, 500, 700 | `'SF Mono', 'Fira Code', monospace` |
| Secondary (body, descriptions) | Space Grotesk | 300, 400, 500 | `'Inter', 'Helvetica Neue', sans-serif` |

### Scale

| Element | Font | Size | Weight | Tracking |
|---------|------|------|--------|----------|
| Page title (h1) | JetBrains Mono | 28px | 700 | 2px |
| Section heading (h2) | JetBrains Mono | 20px | 700 | 1px |
| Subsection (h3) | JetBrains Mono | 16px | 500 | 0.5px |
| Body text | Space Grotesk | 14px | 400 | 0 |
| UI label | JetBrains Mono | 12px | 500 | 1px |
| Caption | Space Grotesk | 12px | 300 | 0 |
| Code/data | JetBrains Mono | 13px | 400 | 0 |

---

## 5. Logo

### Mark

Nested rectangles symbolizing enclosure, containment, and layered security. Four concentric rounded rectangles with decreasing opacity toward center, innermost filled.

**Construction:**
- Outer: 68×68, rx=6, stroke Terminal Green, weight 2.5
- Second: 44×44, rx=3, stroke Terminal Green at 50% opacity, weight 1.5
- Third: 24×24, rx=2, fill Terminal Green at 20% opacity
- Inner: 12×12, rx=1, fill Terminal Green at 60% opacity

### Lockup (Mark + Wordmark)

Mark left, wordmark right. Wordmark set in JetBrains Mono Bold, all-caps, letter-spacing 3px, Terminal Green.

### Variants

| Variant | Background | Mark Color | Wordmark Color |
|---------|------------|------------|----------------|
| Primary | Dark (`#0a0a0a`) | Terminal Green | Terminal Green |
| Light | Light (`#f0f0f0`+) | `#0a0a0a` | `#0a0a0a` |
| Monochrome | Any | `#666666` | `#666666` |

### Clear Space

Minimum clear space around the mark equals the width of the innermost rectangle on all sides. Do not place other elements within this zone.

### Minimum Size

- Mark only: 16×16px (favicon), 24×24px (inline UI)
- Full lockup: 120px wide minimum

---

## 6. Voice & Copy

### Tone

Technical, matter-of-fact. State what it does, not how it feels. Respect the reader's time. No hype words ("revolutionary", "game-changing", "unleash"). No emojis in docs or copy.

### Copy Examples

**GitHub repo description:**
> Self-hosted LLM infrastructure with OpenAI-compatible API. CPU-optimized. Buy once, run forever.

**README opening paragraph:**
> Enclave runs LLMs on your hardware. OpenAI-compatible API, Ollama backend, zero cloud dependencies. Individual and Teams licenses.

**Installer welcome text:**
```
Installing Enclave v1.0.0
CPU-optimized LLM inference
by ohno llc
```

**CLI welcome banner:**
```
┌─────────────────────────────────┐
│ ▣ ENCLAVE  v1.0.0              │
│ Self-hosted AI inference        │
│ by ohno llc                     │
└─────────────────────────────────┘

Models: 3 loaded │ API: ● running
Type /help for commands
```

### Tone Rules

- Spec-forward, not hype
- State what it does, not how it feels
- Respect the reader's time
- No "revolutionary" / "game-changing" / "unleash the power"
- No emojis in docs or copy
- Numbers over adjectives ("40 tok/s" not "blazing fast")
- Imperative for instructions ("Run `enclave status`" not "You can run...")

---

## 7. Licensing Model

Commercial software. Not open source. Source-available with commercial license. No subscription.

### Tiers

| Tier | Model | Includes |
|------|-------|----------|
| Individual | One seat, one-time purchase | All updates, personal and commercial use |
| Teams | Volume discount per seat | Shared infrastructure, priority support channel |

### LICENSE File

A `LICENSE` file must be created at the repository root. Currently missing entirely. Content should be a proprietary/commercial license stating:
- Software is owned by ohno llc
- Individual and Teams license tiers available for purchase
- Source code is viewable but not redistributable
- No warranty; provided as-is

Exact legal text should be reviewed by counsel before public release.

### License Badge (for README)

```
License: Commercial (Individual / Teams)
```

---

## 8. Touchpoints

### 8.1 macOS App Icon

- 1024×1024 master, exported to `.icns` for macOS
- Background: linear gradient 135deg from Void (`#0a0a0a`) to Deep (`#1a1a2e`)
- Foreground: Enclave mark (nested rectangles) centered
- macOS rounded-rect mask applied by OS
- Drop shadow: `0 4px 12px rgba(0,0,0,0.5)`
- Replaces empty placeholder at `desktop/icon.icns`

### 8.2 DMG Installer Background

- Dimensions: 660×400 (standard macOS DMG background)
- Background: linear gradient 135deg from Void through `#0d1520` to Deep
- Top center: ENCLAVE wordmark in Terminal Green, 14px JetBrains Mono Bold, letter-spacing 2px
- Below wordmark: "Drag to Applications to install" in Muted text
- Center: App icon (left) → arrow → Applications folder icon (right)
- Subtle grid pattern overlay at low opacity for texture

### 8.3 GitHub Social Preview

- Dimensions: 1280×640 (GitHub OG image spec)
- Background: same gradient as DMG
- Center: Enclave mark + wordmark lockup
- Below: tagline in Space Grotesk, Secondary text color
- Bottom: "by ohno llc" in Muted text
- File: `assets/social-preview.png`

### 8.4 README Header

- Inline SVG or image: Enclave mark (small, 24px) + "Enclave" in h1
- Below: one-line description
- Badge row: version, platform (macOS/Linux), license type
- Badge style: flat, using Enclave color palette (Deep background, Green/Cyan text)

### 8.5 CLI Branding

- Welcome banner: box-drawing characters in Terminal Green (see section 6 copy example)
- User prompt symbol: `▣` (filled square with inner square — echoes the nested rectangle mark)
- Color scheme: unchanged from current (bright_magenta user, bright_blue AI, bright_cyan commands — already documented in `cli/COLOR_SCHEME.md`)
- Update `cli/chat.py` header text from "Local AI Platform" to "Enclave"

### 8.6 Web Dashboard

- Update `api/static/index.html`:
  - Replace "LOCAL AI PLATFORM" title with "ENCLAVE"
  - Rename CSS variables from `Cortex *` comments to `Enclave *`
  - Update favicon to Enclave mark
  - Add Enclave mark SVG inline in header bar
- Update `api/static/setup.html`:
  - Same title/branding updates

### 8.7 Favicon & PWA Icons

- Favicon: 32×32 and 16×16 `.ico`, Enclave mark (outer + inner rectangles only at small sizes)
- Apple touch icon: 180×180 `.png`
- PWA manifest icons: 192×192, 512×512 `.png`
- All on transparent background with Terminal Green mark

---

## 9. Feature Header Illustrations

Eight SVG illustrations for documentation headers, each mapping to a product feature. All share the same visual language: dark gradient backgrounds, SVG line art, green/cyan/orange palette, JetBrains Mono labels.

### Visual Language

- **Background:** Linear gradient 135deg, Void → Deep
- **Line art:** Thin strokes (0.5–2px), primarily Terminal Green and Signal Cyan
- **Nodes/endpoints:** Small circles (r=2–4), filled at varying opacity
- **Labels:** JetBrains Mono, 7–9px, Secondary or Muted text color
- **Aspect ratio:** 16:9 for all headers
- **Glow effects:** Radial gradient of Terminal Green at 3–6% opacity for focal points

### Illustration Set

| ID | Title | Feature | Usage |
|----|-------|---------|-------|
| `art-cpu-inference` | CPU Inference | Multi-core die grid with active thread highlights, pin traces to system bus | Getting Started, performance docs, README hero |
| `art-privacy` | Privacy & Data Sovereignty | Nested containment layers, blocked external connections (orange ✕), lock icon center | Privacy policy, security docs, "Why Enclave" |
| `art-api` | OpenAI-Compatible API | Client → Enclave API layer (3 endpoints) → backend (Ollama/vLLM/llama.cpp) | API docs, integration guide, architecture overview |
| `art-models` | Model Registry & Management | Stacked model rows with name, size, status badges, download progress bar | Model docs, MODELS.md header, download guide |
| `art-fleet` | Multi-Machine Fleet | Three-node topology (Mac M4 48GB, MS-01 64GB, BD790i 96GB) with model assignments, network backbone | Deployment guide, fleet management, hardware setup |
| `art-workflows` | Multi-Agent Workflows | Step pipeline with role-tagged agents (reasoning/coding/fast), workspace context layer, seed input | Workflow engine docs, YAML reference, agent architecture |
| `art-quantization` | Quantization & GGUF | FP16 dense block → Q4_K_M sparse block with quality/speed/RAM metric bars | Model format docs, quantization guide, performance tuning |
| `art-rag` | RAG & Vector Search | Document → chunk → embed → vector space scatter plot → nearest-neighbor cluster → LLM | RAG docs, ChromaDB setup, knowledge base feature |

### Production Rendering

Each illustration is authored as inline SVG (viewBox 320×180). For production:
- Export as standalone `.svg` files in `assets/illustrations/`
- Generate `.png` rasters at 2x (640×360) for contexts that don't support SVG (GitHub README images, social sharing)
- File naming: `{art-id}.svg` and `{art-id}@2x.png`

---

## 10. Asset File Structure

```
assets/
├── logo/
│   ├── enclave-mark.svg          # Mark only
│   ├── enclave-lockup.svg        # Mark + wordmark
│   ├── enclave-mark-light.svg    # Light background variant
│   ├── enclave-mark-mono.svg     # Monochrome variant
│   └── enclave-lockup-light.svg
├── icons/
│   ├── icon.icns                 # macOS app icon
│   ├── icon-1024.png             # Master raster
│   ├── icon-512.png              # PWA
│   ├── icon-192.png              # PWA
│   ├── icon-180.png              # Apple touch
│   ├── icon-32.png               # Favicon
│   ├── icon-16.png               # Favicon
│   └── favicon.ico
├── installer/
│   ├── dmg-background.png        # 660×400 DMG background
│   └── dmg-background@2x.png    # 1320×800 Retina
├── illustrations/
│   ├── art-cpu-inference.svg
│   ├── art-cpu-inference@2x.png
│   ├── art-privacy.svg
│   ├── art-privacy@2x.png
│   ├── art-api.svg
│   ├── art-api@2x.png
│   ├── art-models.svg
│   ├── art-models@2x.png
│   ├── art-fleet.svg
│   ├── art-fleet@2x.png
│   ├── art-workflows.svg
│   ├── art-workflows@2x.png
│   ├── art-quantization.svg
│   ├── art-quantization@2x.png
│   ├── art-rag.svg
│   └── art-rag@2x.png
├── social/
│   └── social-preview.png        # 1280×640 GitHub OG image
└── brand/
    └── color-palette.svg         # Reference swatch sheet
```

---

## 11. Implementation Priority

1. **Logo & mark SVGs** — everything else depends on having the mark
2. **LICENSE file** — legal prerequisite for any public distribution
3. **macOS app icon** — replaces the empty placeholder, unblocks app builds
4. **README rewrite** — public-facing, first impression
5. **Codebase rename** — "Local AI Platform" / "Cortex" → "Enclave" across all files
6. **GitHub social preview** — immediate visibility improvement
7. **Web dashboard rebrand** — update index.html and setup.html
8. **CLI banner update** — update chat.py welcome text
9. **DMG installer background** — polish for distribution
10. **Favicon & PWA icons** — web UI completeness
11. **Feature illustrations** — documentation polish (can ship incrementally)

---

## 12. Out of Scope (This Round)

- Marketing/landing page for selling licenses
- Pricing page design
- License key infrastructure / activation system
- Email templates
- Light mode theme (dark-only for now)
- Animation / motion design
- Print materials
- ohno llc parent brand design (Sovereign direction saved as reference for future)
