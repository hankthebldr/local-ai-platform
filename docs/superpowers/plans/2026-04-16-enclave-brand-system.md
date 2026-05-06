# Enclave Brand System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebrand the product from "Local AI Platform" to "Enclave" with full visual identity — logo SVGs, app icon, CLI/web/installer branding, LICENSE file, feature illustrations, and README rewrite.

**Architecture:** This is a branding/rename task. No new business logic. All changes are to static assets, string literals, HTML/CSS, and documentation. SVG assets are hand-authored (no build tool). PNG rasters are generated from SVGs using `rsvg-convert` (librsvg) or `sips` (macOS built-in). The `.icns` icon is generated from PNGs using `iconutil`.

**Tech Stack:** SVG (hand-authored), `rsvg-convert` or `sips` for PNG raster export, `iconutil` for macOS `.icns`, Bash for asset pipeline script.

**Spec:** `docs/superpowers/specs/2026-04-16-enclave-brand-system-design.md`

---

## File Map

### New files to create

| File | Purpose |
|------|---------|
| `assets/logo/enclave-mark.svg` | Logo mark (nested rectangles), primary dark variant |
| `assets/logo/enclave-lockup.svg` | Mark + "ENCLAVE" wordmark |
| `assets/logo/enclave-mark-light.svg` | Mark for light backgrounds |
| `assets/logo/enclave-mark-mono.svg` | Monochrome mark |
| `assets/logo/enclave-lockup-light.svg` | Lockup for light backgrounds |
| `assets/icons/icon-1024.png` | Master raster icon |
| `assets/icons/icon-512.png` | PWA icon |
| `assets/icons/icon-192.png` | PWA icon |
| `assets/icons/icon-180.png` | Apple touch icon |
| `assets/icons/icon-32.png` | Favicon source |
| `assets/icons/icon-16.png` | Favicon source |
| `assets/icons/favicon.ico` | Multi-size favicon |
| `assets/icons/icon.icns` | macOS app icon |
| `assets/social/social-preview.svg` | GitHub OG image source |
| `assets/social/social-preview.png` | GitHub OG image (1280x640) |
| `assets/illustrations/art-cpu-inference.svg` | CPU inference header art |
| `assets/illustrations/art-privacy.svg` | Privacy/data sovereignty header art |
| `assets/illustrations/art-api.svg` | OpenAI-compatible API header art |
| `assets/illustrations/art-models.svg` | Model registry header art |
| `assets/illustrations/art-fleet.svg` | Multi-machine fleet header art |
| `assets/illustrations/art-workflows.svg` | Multi-agent workflow header art |
| `assets/illustrations/art-quantization.svg` | Quantization/GGUF header art |
| `assets/illustrations/art-rag.svg` | RAG/vector search header art |
| `assets/brand/color-palette.svg` | Reference swatch sheet |
| `assets/installer/dmg-background.svg` | DMG background source |
| `assets/installer/dmg-background.png` | DMG background (660x400) |
| `assets/installer/dmg-background@2x.png` | DMG background Retina (1320x800) |
| `scripts/generate-icons.sh` | Icon/PNG generation pipeline |
| `LICENSE` | Commercial license text |

### Files to modify

| File | What changes |
|------|-------------|
| `api/main.py:3,53,68,74,165,176` | All "Local AI Platform" → "Enclave" |
| `api/static/index.html:6,14,20,23,25,27,29,1425` | Title, CSS comments (Cortex → Enclave), footer |
| `api/static/setup.html:6,432` | Title and eyebrow text |
| `desktop/app.py:3,24,72` | Docstring, APP_DIR path, window title |
| `desktop/setup_py2app.py:2,79,80,81` | Docstring, CFBundle fields |
| `scripts/build_mac.sh:4,29,117,119,121,127,166,172,176,183` | All names, bundle ID, DMG volume |
| `cli/chat.py:3,20` | Docstring, welcome banner |
| `cli/COLOR_SCHEME.md:4,40` | Overview text, header example |
| `README.md` | Full rewrite |
| `CLAUDE.md` | Update project overview section |

---

## Task 1: Create asset directory structure and icon generation script

**Files:**
- Create: `scripts/generate-icons.sh`
- Create: `assets/` directory tree

- [ ] **Step 1: Create the directory structure**

```bash
mkdir -p assets/{logo,icons,social,illustrations,installer,brand}
```

- [ ] **Step 2: Write the icon generation script**

Create `scripts/generate-icons.sh`:

```bash
#!/bin/bash
set -e
# Generate PNG rasters and .icns from the master SVG mark.
# Requires: rsvg-convert (via librsvg) or falls back to sips.
# Usage: ./scripts/generate-icons.sh

cd "$(dirname "$0")/.."

MARK_SVG="assets/logo/enclave-mark.svg"
ICON_DIR="assets/icons"
SOCIAL_SVG="assets/social/social-preview.svg"
SOCIAL_DIR="assets/social"
DMG_SVG="assets/installer/dmg-background.svg"
DMG_DIR="assets/installer"

if [ ! -f "$MARK_SVG" ]; then
    echo "ERROR: $MARK_SVG not found. Create logo SVGs first (Task 2)."
    exit 1
fi

mkdir -p "$ICON_DIR" "$SOCIAL_DIR" "$DMG_DIR"

# ── Rasterizer selection ──────────────────────────────────────────────
if command -v rsvg-convert &>/dev/null; then
    rasterize() {
        local svg="$1" w="$2" h="$3" out="$4"
        rsvg-convert -w "$w" -h "$h" "$svg" -o "$out"
    }
else
    echo "WARNING: rsvg-convert not found. Install librsvg: brew install librsvg"
    echo "Falling back to sips (may not render SVG gradients correctly)."
    rasterize() {
        local svg="$1" w="$2" h="$3" out="$4"
        # sips can't read SVG directly — skip if not available
        echo "  SKIP: $out (rsvg-convert required for SVG rasterization)"
    }
fi

# ── App icon PNGs ─────────────────────────────────────────────────────
echo "Generating app icon PNGs..."
for size in 1024 512 192 180 32 16; do
    rasterize "$MARK_SVG" "$size" "$size" "$ICON_DIR/icon-${size}.png"
    echo "  icon-${size}.png"
done

# ── macOS .icns ───────────────────────────────────────────────────────
echo "Generating macOS .icns..."
ICONSET_DIR=$(mktemp -d)/Enclave.iconset
mkdir -p "$ICONSET_DIR"

if command -v rsvg-convert &>/dev/null; then
    for size in 16 32 128 256 512; do
        rasterize "$MARK_SVG" "$size" "$size" "$ICONSET_DIR/icon_${size}x${size}.png"
        double=$((size * 2))
        rasterize "$MARK_SVG" "$double" "$double" "$ICONSET_DIR/icon_${size}x${size}@2x.png"
    done
    iconutil -c icns "$ICONSET_DIR" -o "$ICON_DIR/icon.icns"
    echo "  icon.icns"
    rm -rf "$ICONSET_DIR"
else
    echo "  SKIP: icon.icns (rsvg-convert required)"
fi

# ── Favicon .ico ──────────────────────────────────────────────────────
echo "Generating favicon.ico..."
if command -v convert &>/dev/null; then
    # ImageMagick available
    convert "$ICON_DIR/icon-16.png" "$ICON_DIR/icon-32.png" "$ICON_DIR/favicon.ico"
    echo "  favicon.ico"
elif [ -f "$ICON_DIR/icon-32.png" ]; then
    # Fallback: just copy the 32px PNG
    cp "$ICON_DIR/icon-32.png" "$ICON_DIR/favicon.ico"
    echo "  favicon.ico (PNG fallback — install ImageMagick for proper .ico)"
else
    echo "  SKIP: favicon.ico (no icon PNGs yet)"
fi

# ── Social preview PNG ────────────────────────────────────────────────
if [ -f "$SOCIAL_SVG" ]; then
    echo "Generating social preview..."
    rasterize "$SOCIAL_SVG" 1280 640 "$SOCIAL_DIR/social-preview.png"
    echo "  social-preview.png"
fi

# ── DMG background PNGs ──────────────────────────────────────────────
if [ -f "$DMG_SVG" ]; then
    echo "Generating DMG backgrounds..."
    rasterize "$DMG_SVG" 660 400 "$DMG_DIR/dmg-background.png"
    rasterize "$DMG_SVG" 1320 800 "$DMG_DIR/dmg-background@2x.png"
    echo "  dmg-background.png"
    echo "  dmg-background@2x.png"
fi

# ── Copy .icns to desktop/ for builds ────────────────────────────────
if [ -f "$ICON_DIR/icon.icns" ]; then
    cp "$ICON_DIR/icon.icns" desktop/icon.icns
    echo "Copied icon.icns → desktop/icon.icns"
fi

echo ""
echo "Done. Generated assets in assets/"
```

- [ ] **Step 3: Make the script executable**

```bash
chmod +x scripts/generate-icons.sh
```

- [ ] **Step 4: Commit**

```bash
git add assets/ scripts/generate-icons.sh
git commit -m "chore: add asset directory structure and icon generation script"
```

---

## Task 2: Create logo SVGs (mark and lockup, all variants)

**Files:**
- Create: `assets/logo/enclave-mark.svg`
- Create: `assets/logo/enclave-lockup.svg`
- Create: `assets/logo/enclave-mark-light.svg`
- Create: `assets/logo/enclave-mark-mono.svg`
- Create: `assets/logo/enclave-lockup-light.svg`

- [ ] **Step 1: Create the primary mark SVG**

Create `assets/logo/enclave-mark.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80" width="80" height="80">
  <!-- Enclave mark: nested rectangles — enclosure, containment, layered security -->
  <rect x="6" y="6" width="68" height="68" rx="6" fill="none" stroke="#00E87B" stroke-width="2.5"/>
  <rect x="18" y="18" width="44" height="44" rx="3" fill="none" stroke="#00E87B" stroke-width="1.5" opacity="0.5"/>
  <rect x="28" y="28" width="24" height="24" rx="2" fill="#00E87B" opacity="0.2"/>
  <rect x="34" y="34" width="12" height="12" rx="1" fill="#00E87B" opacity="0.6"/>
</svg>
```

- [ ] **Step 2: Create the primary lockup SVG**

Create `assets/logo/enclave-lockup.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 80" width="280" height="80">
  <!-- Mark -->
  <rect x="6" y="6" width="68" height="68" rx="6" fill="none" stroke="#00E87B" stroke-width="2.5"/>
  <rect x="18" y="18" width="44" height="44" rx="3" fill="none" stroke="#00E87B" stroke-width="1.5" opacity="0.5"/>
  <rect x="28" y="28" width="24" height="24" rx="2" fill="#00E87B" opacity="0.2"/>
  <rect x="34" y="34" width="12" height="12" rx="1" fill="#00E87B" opacity="0.6"/>
  <!-- Wordmark -->
  <text x="94" y="48" font-family="'JetBrains Mono', 'SF Mono', 'Fira Code', monospace" font-size="24" font-weight="700" fill="#00E87B" letter-spacing="3">ENCLAVE</text>
</svg>
```

- [ ] **Step 3: Create the light-background mark**

Create `assets/logo/enclave-mark-light.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80" width="80" height="80">
  <rect x="6" y="6" width="68" height="68" rx="6" fill="none" stroke="#0a0a0a" stroke-width="2.5"/>
  <rect x="18" y="18" width="44" height="44" rx="3" fill="none" stroke="#0a0a0a" stroke-width="1.5" opacity="0.3"/>
  <rect x="28" y="28" width="24" height="24" rx="2" fill="#0a0a0a" opacity="0.1"/>
  <rect x="34" y="34" width="12" height="12" rx="1" fill="#0a0a0a" opacity="0.4"/>
</svg>
```

- [ ] **Step 4: Create the monochrome mark**

Create `assets/logo/enclave-mark-mono.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80" width="80" height="80">
  <rect x="6" y="6" width="68" height="68" rx="6" fill="none" stroke="#666666" stroke-width="2.5"/>
  <rect x="18" y="18" width="44" height="44" rx="3" fill="none" stroke="#666666" stroke-width="1.5" opacity="0.5"/>
  <rect x="28" y="28" width="24" height="24" rx="2" fill="#666666" opacity="0.15"/>
  <rect x="34" y="34" width="12" height="12" rx="1" fill="#666666" opacity="0.4"/>
</svg>
```

- [ ] **Step 5: Create the light-background lockup**

Create `assets/logo/enclave-lockup-light.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 80" width="280" height="80">
  <rect x="6" y="6" width="68" height="68" rx="6" fill="none" stroke="#0a0a0a" stroke-width="2.5"/>
  <rect x="18" y="18" width="44" height="44" rx="3" fill="none" stroke="#0a0a0a" stroke-width="1.5" opacity="0.3"/>
  <rect x="28" y="28" width="24" height="24" rx="2" fill="#0a0a0a" opacity="0.1"/>
  <rect x="34" y="34" width="12" height="12" rx="1" fill="#0a0a0a" opacity="0.4"/>
  <text x="94" y="48" font-family="'JetBrains Mono', 'SF Mono', 'Fira Code', monospace" font-size="24" font-weight="700" fill="#0a0a0a" letter-spacing="3">ENCLAVE</text>
</svg>
```

- [ ] **Step 6: Verify SVGs render correctly**

```bash
# Quick validation — check all SVGs are well-formed XML
for f in assets/logo/*.svg; do
    xmllint --noout "$f" 2>&1 && echo "OK: $f" || echo "FAIL: $f"
done
```

Expected: all five files report "OK".

- [ ] **Step 7: Commit**

```bash
git add assets/logo/
git commit -m "feat: add Enclave logo mark and lockup SVGs (5 variants)"
```

---

## Task 3: Create LICENSE file

**Files:**
- Create: `LICENSE`

- [ ] **Step 1: Write the LICENSE file**

Create `LICENSE` at the repository root:

```
Enclave — Commercial Software License

Copyright (c) 2026 ohno llc. All rights reserved.

This software and its source code are the proprietary property of ohno llc.

PERMITTED:
- Viewing the source code for evaluation and security review
- Running the software with a valid Individual or Teams license
- Personal and commercial use within the scope of your license tier

NOT PERMITTED:
- Redistribution of the source code or compiled binaries
- Modification and redistribution of the software
- Sublicensing or resale
- Removal of license notices or copyright headers

LICENSE TIERS:
- Individual: single-seat, one-time purchase, all future updates included
- Teams: volume pricing per seat, shared infrastructure, priority support

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
OHNO LLC BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY.

For licensing inquiries: contact ohno llc
```

- [ ] **Step 2: Commit**

```bash
git add LICENSE
git commit -m "chore: add commercial license (ohno llc)"
```

---

## Task 4: Generate macOS app icon and favicon

**Files:**
- Create: `assets/icons/icon-1024.png` (and other sizes)
- Create: `assets/icons/icon.icns`
- Create: `assets/icons/favicon.ico`
- Modify: `desktop/icon.icns`

This task depends on Task 2 (logo SVGs). The mark SVG alone won't produce a proper app icon — it needs a background gradient. We create an icon-specific SVG first.

- [ ] **Step 1: Create the app icon SVG (mark on gradient background)**

Create `assets/icons/icon-source.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0a0a0a"/>
      <stop offset="100%" stop-color="#1a1a2e"/>
    </linearGradient>
  </defs>
  <!-- Background (macOS will apply rounded-rect mask) -->
  <rect width="1024" height="1024" fill="url(#bg)"/>
  <!-- Enclave mark, centered and scaled -->
  <g transform="translate(212, 212) scale(7.5)">
    <rect x="6" y="6" width="68" height="68" rx="6" fill="none" stroke="#00E87B" stroke-width="2.5"/>
    <rect x="18" y="18" width="44" height="44" rx="3" fill="none" stroke="#00E87B" stroke-width="1.5" opacity="0.5"/>
    <rect x="28" y="28" width="24" height="24" rx="2" fill="#00E87B" opacity="0.2"/>
    <rect x="34" y="34" width="12" height="12" rx="1" fill="#00E87B" opacity="0.6"/>
  </g>
</svg>
```

- [ ] **Step 2: Check if rsvg-convert is installed**

```bash
command -v rsvg-convert && echo "rsvg-convert available" || echo "MISSING: run 'brew install librsvg'"
```

If missing, install it:

```bash
brew install librsvg
```

- [ ] **Step 3: Generate all icon PNGs from the source SVG**

```bash
cd /Users/henry/Github/Github_desktop/local-ai-platform

for size in 1024 512 192 180 32 16; do
    rsvg-convert -w $size -h $size assets/icons/icon-source.svg -o assets/icons/icon-${size}.png
    echo "Generated icon-${size}.png"
done
```

Expected: six PNG files in `assets/icons/`.

- [ ] **Step 4: Generate the macOS .icns file**

```bash
ICONSET=$(mktemp -d)/Enclave.iconset
mkdir -p "$ICONSET"

for size in 16 32 128 256 512; do
    rsvg-convert -w $size -h $size assets/icons/icon-source.svg -o "$ICONSET/icon_${size}x${size}.png"
    double=$((size * 2))
    rsvg-convert -w $double -h $double assets/icons/icon-source.svg -o "$ICONSET/icon_${size}x${size}@2x.png"
done

iconutil -c icns "$ICONSET" -o assets/icons/icon.icns
rm -rf "$ICONSET"
echo "Generated icon.icns"
```

Expected: `assets/icons/icon.icns` created.

- [ ] **Step 5: Generate favicon.ico**

```bash
# If ImageMagick is available:
if command -v convert &>/dev/null; then
    convert assets/icons/icon-16.png assets/icons/icon-32.png assets/icons/favicon.ico
else
    cp assets/icons/icon-32.png assets/icons/favicon.ico
    echo "WARNING: favicon.ico is a PNG fallback. Install ImageMagick for proper .ico"
fi
```

- [ ] **Step 6: Copy .icns to desktop/ for builds**

```bash
cp assets/icons/icon.icns desktop/icon.icns
ls -la desktop/icon.icns
```

Expected: `desktop/icon.icns` is no longer 0 bytes.

- [ ] **Step 7: Verify the icon renders**

```bash
# Quick check — open in Preview
open assets/icons/icon-1024.png
```

Expected: a 1024x1024 PNG showing the Enclave mark (green nested rectangles) on a dark gradient background.

- [ ] **Step 8: Commit**

```bash
git add assets/icons/ desktop/icon.icns
git commit -m "feat: generate Enclave app icon (.icns, PNGs, favicon)"
```

---

## Task 5: Rename codebase — "Local AI Platform" / "Cortex" → "Enclave"

**Files:**
- Modify: `api/main.py:3,53,68,74,165,176`
- Modify: `desktop/app.py:3,24,72`
- Modify: `desktop/setup_py2app.py:2,79,80,81`
- Modify: `scripts/build_mac.sh:4,29,103,108,117,119,121,127,166,172,176,183,191-196`
- Modify: `cli/chat.py:3,20`
- Modify: `cli/COLOR_SCHEME.md:4,40`
- Modify: `api/static/setup.html:6,432`

- [ ] **Step 1: Update api/main.py**

Replace all six occurrences:

Line 3: `Local AI Platform - FastAPI Server` → `Enclave - FastAPI Server`
Line 53: `Starting Local AI Platform API` → `Starting Enclave API`
Line 68: `Shutting down Local AI Platform API` → `Shutting down Enclave API`
Line 74: `title="Local AI Platform API"` → `title="Enclave API"`
Line 165: `"message": "Local AI Platform API"` → `"message": "Enclave API"`
Line 176: `"message": "Local AI Platform API"` → `"message": "Enclave API"`

- [ ] **Step 2: Verify api/main.py has no remaining old references**

```bash
grep -n "Local AI Platform\|Cortex" api/main.py
```

Expected: no output (zero matches).

- [ ] **Step 3: Update desktop/app.py**

Line 3: `Local AI Platform — macOS Desktop App` → `Enclave — macOS Desktop App`
Line 24: `APP_DIR = os.path.expanduser("~/.local-ai-platform")` → `APP_DIR = os.path.expanduser("~/.enclave")`
Line 72: `"Local AI Platform"` → `"Enclave"`

- [ ] **Step 4: Update desktop/setup_py2app.py**

Line 2: `py2app build configuration for Local AI Platform` → `py2app build configuration for Enclave`
Line 79: `"CFBundleName": "Local AI Platform"` → `"CFBundleName": "Enclave"`
Line 80: `"CFBundleDisplayName": "Local AI Platform"` → `"CFBundleDisplayName": "Enclave"`
Line 81: `"CFBundleIdentifier": "com.localai.platform"` → `"CFBundleIdentifier": "com.ohno.enclave"`

- [ ] **Step 5: Update scripts/build_mac.sh**

Line 4: `Local AI Platform — macOS Build Pipeline` → `Enclave — macOS Build Pipeline`
Line 29: `APP_NAME="Local AI Platform"` → `APP_NAME="Enclave"`
Line 117: `<string>Local AI Platform</string>` (CFBundleName) → `<string>Enclave</string>`
Line 119: `<string>Local AI Platform</string>` (CFBundleDisplayName) → `<string>Enclave</string>`
Line 121: `<string>com.localai.platform</string>` → `<string>com.ohno.enclave</string>`
Line 127: `<string>Local AI Platform</string>` (CFBundleExecutable) → `<string>Enclave</string>`
Line 166: `--volname "Local AI Platform"` → `--volname "Enclave"`
Line 172: `"dist/LocalAIPlatform.dmg"` → `"dist/Enclave.dmg"` (both occurrences on this line)
Line 176: `hdiutil create -volname "Local AI Platform"` → `hdiutil create -volname "Enclave"`
Line 179: `"dist/LocalAIPlatform.dmg"` → `"dist/Enclave.dmg"`
Line 183: `hdiutil create -volname "Local AI Platform"` → `hdiutil create -volname "Enclave"`
Line 186: `"dist/LocalAIPlatform.dmg"` → `"dist/Enclave.dmg"`
Line 192: `DMG: dist/LocalAIPlatform.dmg` → `DMG: dist/Enclave.dmg`
Line 194: `du -sh "dist/LocalAIPlatform.dmg"` → `du -sh "dist/Enclave.dmg"`

Also update line 77 comment: `# Local AI Platform — macOS Launcher` → `# Enclave — macOS Launcher`

- [ ] **Step 6: Update cli/chat.py**

Line 3: `Local AI Platform - CLI Chat Interface` → `Enclave - CLI Chat Interface`
Line 20: Replace the welcome banner:

```python
    console.print(Panel.fit(
        f"[bold bright_cyan]┌─────────────────────────────────┐[/bold bright_cyan]\n"
        f"[bold bright_cyan]│[/bold bright_cyan] [bold bright_green]▣ ENCLAVE[/bold bright_green]  [dim]v1.0.0[/dim]              [bold bright_cyan]│[/bold bright_cyan]\n"
        f"[bold bright_cyan]│[/bold bright_cyan] [dim]Self-hosted AI inference[/dim]        [bold bright_cyan]│[/bold bright_cyan]\n"
        f"[bold bright_cyan]│[/bold bright_cyan] [dim]by ohno llc[/dim]                     [bold bright_cyan]│[/bold bright_cyan]\n"
        f"[bold bright_cyan]└─────────────────────────────────┘[/bold bright_cyan]\n\n"
        f"[dim]Model:[/dim] [bright_white]{model}[/bright_white]\n"
        f"[dim]Type /help for commands[/dim]",
        border_style="bright_cyan"
    ))
```

- [ ] **Step 7: Update cli/COLOR_SCHEME.md**

Line 4: `The Local AI Platform CLI uses an optimized` → `The Enclave CLI uses an optimized`
Line 40: `Local AI Platform - Chat Interface` → `Enclave - Chat Interface` (inside the code block example)

- [ ] **Step 8: Update api/static/setup.html**

Line 6: `<title>Setup — Local AI Platform</title>` → `<title>Setup — Enclave</title>`
Line 432: `<div class="eyebrow">Local AI Platform</div>` → `<div class="eyebrow">Enclave</div>`

- [ ] **Step 9: Final verification — no remaining old references**

```bash
grep -rn "Local AI Platform\|Cortex" api/main.py desktop/app.py desktop/setup_py2app.py scripts/build_mac.sh cli/chat.py cli/COLOR_SCHEME.md api/static/setup.html
```

Expected: zero matches.

- [ ] **Step 10: Run existing tests to check nothing broke**

```bash
cd /Users/henry/Github/Github_desktop/local-ai-platform
source venv/bin/activate
pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all existing tests pass (the rename only changes string literals and docs, not logic).

- [ ] **Step 11: Commit**

```bash
git add api/main.py desktop/app.py desktop/setup_py2app.py scripts/build_mac.sh cli/chat.py cli/COLOR_SCHEME.md api/static/setup.html
git commit -m "feat: rename Local AI Platform / Cortex → Enclave across codebase"
```

---

## Task 6: Rebrand web dashboard (index.html)

**Files:**
- Modify: `api/static/index.html:6,14,20,23,25,27,29,1425`

- [ ] **Step 1: Update the HTML title**

Line 6: `<title>LOCAL AI PLATFORM</title>` → `<title>ENCLAVE</title>`

- [ ] **Step 2: Update CSS variable comments (Cortex → Enclave)**

Line 14: `/* Cortex Brand — dark mode palette */` → `/* Enclave Brand — dark mode palette */`
Line 20: `/* Cortex Green — primary accent */` → `/* Enclave Terminal Green — primary accent */`
Line 23: `/* Cortex Secondary Green */` → `/* Enclave Secondary Green */`
Line 25: `/* Cortex Green — success/status */` → `/* Enclave Terminal Green — success/status */`
Line 27: `/* Cortex Orange — danger/error */` → `/* Enclave Alert Orange — danger/error */`
Line 29: `/* Cortex Cyan — info accent */` → `/* Enclave Signal Cyan — info accent */`

- [ ] **Step 3: Update the footer**

Line 1425: `CORTEX &mdash; LOCAL AI PLATFORM v1.0.0` → `ENCLAVE v1.0.0 &mdash; by ohno llc`

- [ ] **Step 4: Add inline Enclave mark SVG to the header bar**

Find the header/nav area in `index.html` and add the mark SVG before the title text. The exact insertion point depends on the header structure — look for the main header/title element and prepend this inline SVG:

```html
<svg width="24" height="24" viewBox="0 0 80 80" style="vertical-align: middle; margin-right: 8px;">
  <rect x="6" y="6" width="68" height="68" rx="6" fill="none" stroke="#00E87B" stroke-width="2.5"/>
  <rect x="18" y="18" width="44" height="44" rx="3" fill="none" stroke="#00E87B" stroke-width="1.5" opacity="0.5"/>
  <rect x="28" y="28" width="24" height="24" rx="2" fill="#00E87B" opacity="0.2"/>
  <rect x="34" y="34" width="12" height="12" rx="1" fill="#00E87B" opacity="0.6"/>
</svg>
```

- [ ] **Step 5: Verify no Cortex/Local AI Platform references remain**

```bash
grep -n "Cortex\|LOCAL AI PLATFORM\|Local AI Platform" api/static/index.html
```

Expected: zero matches.

- [ ] **Step 6: Commit**

```bash
git add api/static/index.html
git commit -m "feat: rebrand web dashboard — Cortex → Enclave"
```

---

## Task 7: Create GitHub social preview

**Files:**
- Create: `assets/social/social-preview.svg`
- Create: `assets/social/social-preview.png`

- [ ] **Step 1: Create the social preview SVG (1280x640)**

Create `assets/social/social-preview.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 640" width="1280" height="640">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0a0a0a"/>
      <stop offset="50%" stop-color="#0d1520"/>
      <stop offset="100%" stop-color="#1a1a2e"/>
    </linearGradient>
  </defs>

  <!-- Background -->
  <rect width="1280" height="640" fill="url(#bg)"/>

  <!-- Subtle grid pattern -->
  <defs>
    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
      <rect width="40" height="40" fill="none" stroke="#1a1a2e" stroke-width="0.5" opacity="0.3"/>
    </pattern>
  </defs>
  <rect width="1280" height="640" fill="url(#grid)"/>

  <!-- Center glow -->
  <circle cx="640" cy="280" r="200" fill="#00E87B" opacity="0.03"/>

  <!-- Enclave mark (centered, scaled up) -->
  <g transform="translate(580, 200) scale(1.5)">
    <rect x="6" y="6" width="68" height="68" rx="6" fill="none" stroke="#00E87B" stroke-width="2.5"/>
    <rect x="18" y="18" width="44" height="44" rx="3" fill="none" stroke="#00E87B" stroke-width="1.5" opacity="0.5"/>
    <rect x="28" y="28" width="24" height="24" rx="2" fill="#00E87B" opacity="0.2"/>
    <rect x="34" y="34" width="12" height="12" rx="1" fill="#00E87B" opacity="0.6"/>
  </g>

  <!-- Wordmark -->
  <text x="640" y="370" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="48" font-weight="700" fill="#00E87B" letter-spacing="6">ENCLAVE</text>

  <!-- Tagline -->
  <text x="640" y="420" text-anchor="middle" font-family="'Space Grotesk', 'Inter', sans-serif" font-size="20" fill="#888888">Self-hosted AI inference. CPU-optimized. One price. Forever.</text>

  <!-- Company -->
  <text x="640" y="530" text-anchor="middle" font-family="'Space Grotesk', 'Inter', sans-serif" font-size="14" fill="#555555">by ohno llc</text>
</svg>
```

- [ ] **Step 2: Generate the PNG**

```bash
rsvg-convert -w 1280 -h 640 assets/social/social-preview.svg -o assets/social/social-preview.png
ls -la assets/social/social-preview.png
```

Expected: a PNG file at 1280x640.

- [ ] **Step 3: Commit**

```bash
git add assets/social/
git commit -m "feat: add GitHub social preview image (1280x640)"
```

---

## Task 8: Rewrite README.md

**Files:**
- Modify: `README.md` (full rewrite)

- [ ] **Step 1: Rewrite README.md with Enclave branding**

Replace the entire contents of `README.md` with:

```markdown
<p align="center">
  <img src="assets/logo/enclave-mark.svg" width="80" alt="Enclave">
</p>

<h1 align="center">Enclave</h1>

<p align="center">
  Self-hosted LLM infrastructure with OpenAI-compatible API. CPU-optimized. Buy once, run forever.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0-1a1a2e?style=flat&labelColor=1a1a2e&color=00E87B" alt="Version">
  <img src="https://img.shields.io/badge/macOS-supported-1a1a2e?style=flat&labelColor=1a1a2e&color=00C0E8" alt="macOS">
  <img src="https://img.shields.io/badge/Linux-supported-1a1a2e?style=flat&labelColor=1a1a2e&color=00C0E8" alt="Linux">
  <img src="https://img.shields.io/badge/license-Commercial-1a1a2e?style=flat&labelColor=1a1a2e&color=888888" alt="License">
</p>

---

Enclave runs LLMs on your hardware. OpenAI-compatible API, Ollama backend, zero cloud dependencies. Individual and Teams licenses.

## What it does

- **OpenAI-compatible API** — drop-in replacement. Point your existing code at `localhost:8000`
- **CPU-optimized inference** — GGUF quantized models via Ollama. 7B at 40-50 tok/s, 13B at 25-30 tok/s
- **Model management** — download, configure, and switch between 18+ models from the registry
- **Multi-agent workflows** — YAML-defined step pipelines with role-based model selection
- **Web dashboard** — monitor models, system health, and API status
- **macOS app** — native desktop wrapper with setup wizard
- **Zero telemetry** — no data leaves your machine. No internet required for inference

## Quick start

```bash
# Install
./setup/install.sh

# Start Ollama
ollama serve

# Start API
source venv/bin/activate
python -m api.main

# Verify
curl http://localhost:8000/health
```

API is at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

## Models

```bash
# List available models
python models/download.py --list

# Download a model
python models/download.py dolphin-mixtral

# List installed
ollama list
```

Default quantization: Q4_K_M (best quality/speed balance). See [MODELS.md](MODELS.md) for the full registry.

## API usage

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

Compatible with any OpenAI SDK client.

## Hardware targets

| Machine | RAM | Role | Throughput |
|---------|-----|------|------------|
| Mac M4 Pro | 48GB | Development | 7B @ 50 tok/s |
| MS-01 (Ryzen 9 7945HX) | 64GB | API serving | 34B @ 12 tok/s |
| BD790i (Ryzen 9 7945HX) | 96GB | Research | 70B @ 5 tok/s |

## Licensing

Enclave is commercial software by [ohno llc](https://github.com/hankthebldr).

| Tier | Model |
|------|-------|
| **Individual** | One seat, one-time purchase. All updates included. |
| **Teams** | Volume discount per seat. Priority support. |

See [LICENSE](LICENSE) for terms.

## Documentation

- [MODELS.md](MODELS.md) — model registry and selection
- [CLAUDE.md](CLAUDE.md) — developer guide
- [docs/](docs/) — architecture, deployment, and API reference

---

<sub>by ohno llc</sub>
```

- [ ] **Step 2: Verify the README renders correctly**

```bash
# Check that referenced files exist
test -f assets/logo/enclave-mark.svg && echo "mark: OK" || echo "mark: MISSING"
test -f LICENSE && echo "license: OK" || echo "license: MISSING"
test -f MODELS.md && echo "models: OK" || echo "models: MISSING"
```

Expected: all three report OK.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "feat: rewrite README with Enclave branding"
```

---

## Task 9: Update CLAUDE.md project overview

**Files:**
- Modify: `CLAUDE.md` (first ~10 lines of project overview)

- [ ] **Step 1: Update the project overview section**

In `CLAUDE.md`, replace the Project Overview paragraph:

```
Local AI Platform is a comprehensive self-hosted infrastructure for running uncensored local LLM models
```

→

```
Enclave (by ohno llc) is a comprehensive self-hosted infrastructure for running uncensored local LLM models
```

Also update any other "Local AI Platform" references in CLAUDE.md to "Enclave". There are several — search and replace all occurrences of `Local AI Platform` with `Enclave` throughout the file.

- [ ] **Step 2: Verify**

```bash
grep -c "Local AI Platform" CLAUDE.md
```

Expected: `0` (zero remaining).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md project overview — Enclave branding"
```

---

## Task 10: Create DMG installer background

**Files:**
- Create: `assets/installer/dmg-background.svg`
- Create: `assets/installer/dmg-background.png`
- Create: `assets/installer/dmg-background@2x.png`

- [ ] **Step 1: Create the DMG background SVG (660x400)**

Create `assets/installer/dmg-background.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 660 400" width="660" height="400">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0a0a0a"/>
      <stop offset="50%" stop-color="#0d1520"/>
      <stop offset="100%" stop-color="#1a1a2e"/>
    </linearGradient>
    <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
      <rect width="20" height="20" fill="none" stroke="#1a1a2e" stroke-width="0.5" opacity="0.3"/>
    </pattern>
  </defs>

  <!-- Background -->
  <rect width="660" height="400" fill="url(#bg)"/>
  <rect width="660" height="400" fill="url(#grid)"/>

  <!-- Center glow -->
  <circle cx="330" cy="200" r="150" fill="#00E87B" opacity="0.03"/>

  <!-- ENCLAVE wordmark -->
  <text x="330" y="80" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="24" font-weight="700" fill="#00E87B" letter-spacing="3">ENCLAVE</text>

  <!-- Subtitle -->
  <text x="330" y="110" text-anchor="middle" font-family="'Space Grotesk', sans-serif" font-size="12" fill="#555555">Drag to Applications to install</text>

  <!-- Arrow between icon positions -->
  <line x1="280" y1="230" x2="370" y2="230" stroke="#1a1a2e" stroke-width="2"/>
  <polygon points="370,225 385,230 370,235" fill="#1a1a2e"/>

  <!-- Version -->
  <text x="330" y="360" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="10" fill="#333333">v1.0.0 — by ohno llc</text>
</svg>
```

- [ ] **Step 2: Generate PNG rasters**

```bash
rsvg-convert -w 660 -h 400 assets/installer/dmg-background.svg -o assets/installer/dmg-background.png
rsvg-convert -w 1320 -h 800 assets/installer/dmg-background.svg -o assets/installer/dmg-background@2x.png
ls -la assets/installer/
```

Expected: three files (svg, png, @2x.png).

- [ ] **Step 3: Commit**

```bash
git add assets/installer/
git commit -m "feat: add DMG installer background (660x400 + Retina)"
```

---

## Task 11: Create color palette reference sheet

**Files:**
- Create: `assets/brand/color-palette.svg`

- [ ] **Step 1: Create the palette SVG**

Create `assets/brand/color-palette.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400" width="800" height="400">
  <rect width="800" height="400" fill="#0a0a0a"/>

  <!-- Title -->
  <text x="40" y="40" font-family="'JetBrains Mono', monospace" font-size="16" font-weight="700" fill="#00E87B" letter-spacing="2">ENCLAVE — COLOR SYSTEM</text>

  <!-- Core palette -->
  <text x="40" y="80" font-family="'JetBrains Mono', monospace" font-size="10" fill="#555" letter-spacing="1">CORE</text>
  <rect x="40" y="90" width="80" height="80" rx="8" fill="#0a0a0a" stroke="#333" stroke-width="1"/>
  <text x="80" y="190" text-anchor="middle" font-family="monospace" font-size="9" fill="#888">Void</text>
  <text x="80" y="202" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">#0a0a0a</text>

  <rect x="140" y="90" width="80" height="80" rx="8" fill="#1a1a2e"/>
  <text x="180" y="190" text-anchor="middle" font-family="monospace" font-size="9" fill="#888">Deep</text>
  <text x="180" y="202" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">#1a1a2e</text>

  <rect x="240" y="90" width="80" height="80" rx="8" fill="#141414"/>
  <text x="280" y="190" text-anchor="middle" font-family="monospace" font-size="9" fill="#888">Surface</text>
  <text x="280" y="202" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">#141414</text>

  <rect x="340" y="90" width="80" height="80" rx="8" fill="#222222"/>
  <text x="380" y="190" text-anchor="middle" font-family="monospace" font-size="9" fill="#888">Border</text>
  <text x="380" y="202" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">#222222</text>

  <!-- Accent palette -->
  <text x="40" y="240" font-family="'JetBrains Mono', monospace" font-size="10" fill="#555" letter-spacing="1">ACCENT</text>
  <rect x="40" y="250" width="80" height="80" rx="8" fill="#00E87B"/>
  <text x="80" y="350" text-anchor="middle" font-family="monospace" font-size="9" fill="#888">Terminal Green</text>
  <text x="80" y="362" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">#00E87B</text>

  <rect x="140" y="250" width="80" height="80" rx="8" fill="#00C0E8"/>
  <text x="180" y="350" text-anchor="middle" font-family="monospace" font-size="9" fill="#888">Signal Cyan</text>
  <text x="180" y="362" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">#00C0E8</text>

  <rect x="240" y="250" width="80" height="80" rx="8" fill="#FA582D"/>
  <text x="280" y="350" text-anchor="middle" font-family="monospace" font-size="9" fill="#888">Alert Orange</text>
  <text x="280" y="362" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">#FA582D</text>

  <!-- Text hierarchy -->
  <text x="500" y="240" font-family="'JetBrains Mono', monospace" font-size="10" fill="#555" letter-spacing="1">TEXT</text>
  <rect x="500" y="250" width="80" height="80" rx="8" fill="#E0E0E0"/>
  <text x="540" y="350" text-anchor="middle" font-family="monospace" font-size="9" fill="#888">Primary</text>
  <text x="540" y="362" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">#E0E0E0</text>

  <rect x="600" y="250" width="80" height="80" rx="8" fill="#888888"/>
  <text x="640" y="350" text-anchor="middle" font-family="monospace" font-size="9" fill="#888">Secondary</text>
  <text x="640" y="362" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">#888888</text>

  <rect x="700" y="250" width="80" height="80" rx="8" fill="#555555"/>
  <text x="740" y="350" text-anchor="middle" font-family="monospace" font-size="9" fill="#888">Muted</text>
  <text x="740" y="362" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">#555555</text>
</svg>
```

- [ ] **Step 2: Commit**

```bash
git add assets/brand/
git commit -m "feat: add Enclave color palette reference sheet"
```

---

## Task 12: Create feature header illustrations (all 8)

**Files:**
- Create: `assets/illustrations/art-cpu-inference.svg`
- Create: `assets/illustrations/art-privacy.svg`
- Create: `assets/illustrations/art-api.svg`
- Create: `assets/illustrations/art-models.svg`
- Create: `assets/illustrations/art-fleet.svg`
- Create: `assets/illustrations/art-workflows.svg`
- Create: `assets/illustrations/art-quantization.svg`
- Create: `assets/illustrations/art-rag.svg`

All illustrations follow the same visual language: viewBox 320x180, dark gradient background (Void → Deep at 135deg), thin SVG line art in Terminal Green / Signal Cyan, JetBrains Mono labels, 16:9 aspect ratio.

These are large SVG files. Each one should be created from the brainstorming mockups that were approved in the visual companion session (saved in `.superpowers/brainstorm/70694-1776367188/content/concept-art-expanded.html`). Extract each illustration's `<svg>` from that HTML file, wrap it in a standalone SVG document with proper `xmlns` and `viewBox`, and save to the corresponding file.

- [ ] **Step 1: Read the approved concept art HTML**

```bash
cat .superpowers/brainstorm/70694-1776367188/content/concept-art-expanded.html
```

Use the SVG content within each `.art-card .preview` div as the source for each standalone illustration.

- [ ] **Step 2: Create art-cpu-inference.svg**

Extract the CPU Inference SVG from the concept art HTML. Wrap in a standalone SVG document:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180" width="320" height="180">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0a0a0a"/>
      <stop offset="100%" stop-color="#1a1a2e"/>
    </linearGradient>
    <pattern id="cpuGrid" width="16" height="16" patternUnits="userSpaceOnUse">
      <rect width="14" height="14" x="1" y="1" rx="1" fill="none" stroke="#1a1a2e" stroke-width="0.5"/>
    </pattern>
  </defs>
  <rect width="320" height="180" fill="url(#bg)"/>
  <!-- CPU die grid, pin traces, core highlights — copy from concept art HTML -->
  <!-- (Full SVG body from concept-art-expanded.html, CPU Inference section) -->
</svg>
```

Repeat this pattern for each of the 8 illustrations. The SVG content for each was already authored and approved in the brainstorming session — extract it verbatim.

- [ ] **Step 3: Create art-privacy.svg**

Same pattern. Source: Privacy & Data Sovereignty section from concept art HTML.

- [ ] **Step 4: Create art-api.svg**

Same pattern. Source: OpenAI-Compatible API section.

- [ ] **Step 5: Create art-models.svg**

Same pattern. Source: Model Registry & Management section.

- [ ] **Step 6: Create art-fleet.svg**

Same pattern. Source: Multi-Machine Fleet section.

- [ ] **Step 7: Create art-workflows.svg**

Same pattern. Source: Multi-Agent Workflows section.

- [ ] **Step 8: Create art-quantization.svg**

Same pattern. Source: Quantization & GGUF section.

- [ ] **Step 9: Create art-rag.svg**

Same pattern. Source: RAG & Vector Search section.

- [ ] **Step 10: Validate all SVGs**

```bash
for f in assets/illustrations/*.svg; do
    xmllint --noout "$f" 2>&1 && echo "OK: $f" || echo "FAIL: $f"
done
```

Expected: all 8 files report OK.

- [ ] **Step 11: Commit**

```bash
git add assets/illustrations/
git commit -m "feat: add 8 feature header illustrations for documentation"
```

---

## Task 13: Add favicon and PWA icons to web dashboard

**Files:**
- Modify: `api/static/index.html` (add favicon link)
- Modify: `api/static/setup.html` (add favicon link)
- Copy: `assets/icons/favicon.ico` → `api/static/favicon.ico`
- Copy: `assets/icons/icon-180.png` → `api/static/apple-touch-icon.png`

- [ ] **Step 1: Copy icon assets to static directory**

```bash
cp assets/icons/favicon.ico api/static/favicon.ico
cp assets/icons/icon-180.png api/static/apple-touch-icon.png
cp assets/icons/icon-192.png api/static/icon-192.png
cp assets/icons/icon-512.png api/static/icon-512.png
```

- [ ] **Step 2: Add favicon link tags to index.html**

Add these lines inside the `<head>` tag of `api/static/index.html`, after the `<title>` tag:

```html
<link rel="icon" type="image/x-icon" href="/static/favicon.ico">
<link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png">
```

- [ ] **Step 3: Add favicon link tags to setup.html**

Same two `<link>` tags inside the `<head>` of `api/static/setup.html`.

- [ ] **Step 4: Commit**

```bash
git add api/static/favicon.ico api/static/apple-touch-icon.png api/static/icon-192.png api/static/icon-512.png api/static/index.html api/static/setup.html
git commit -m "feat: add favicon and PWA icons to web dashboard"
```

---

## Task 14: Final verification and .gitignore update

**Files:**
- Modify: `.gitignore` (add `.superpowers/`)

- [ ] **Step 1: Add .superpowers to .gitignore**

Append to `.gitignore`:

```
# Brainstorm session files
.superpowers/
```

- [ ] **Step 2: Run the full verification sweep**

```bash
cd /Users/henry/Github/Github_desktop/local-ai-platform

# 1. No remaining old branding references (excluding docs/plans/specs, README changelog, git history)
echo "=== Old branding check ==="
grep -rn "Local AI Platform\|Cortex" --include="*.py" --include="*.sh" --include="*.html" --include="*.md" \
  --exclude-dir=docs/superpowers --exclude-dir=.superpowers --exclude-dir=.git \
  | grep -v "CLAUDE.md" | grep -v "MEMORY" || echo "Clean: no old references"

# 2. All asset files exist
echo "=== Asset check ==="
for f in \
    assets/logo/enclave-mark.svg \
    assets/logo/enclave-lockup.svg \
    assets/logo/enclave-mark-light.svg \
    assets/logo/enclave-mark-mono.svg \
    assets/logo/enclave-lockup-light.svg \
    assets/icons/icon.icns \
    assets/icons/favicon.ico \
    assets/social/social-preview.png \
    assets/installer/dmg-background.png \
    assets/brand/color-palette.svg \
    LICENSE; do
    test -f "$f" && echo "OK: $f" || echo "MISSING: $f"
done

# 3. All 8 illustrations exist
echo "=== Illustrations check ==="
for art in cpu-inference privacy api models fleet workflows quantization rag; do
    test -f "assets/illustrations/art-${art}.svg" && echo "OK: art-${art}.svg" || echo "MISSING: art-${art}.svg"
done

# 4. icon.icns is not empty
echo "=== Icon size check ==="
ls -la desktop/icon.icns | awk '{print $5, $9}'

# 5. Tests still pass
echo "=== Test suite ==="
source venv/bin/activate
pytest tests/ -v --tb=short 2>&1 | tail -5
```

Expected: all checks pass, all files exist, zero old branding references, tests green.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: add .superpowers to .gitignore"
```

- [ ] **Step 4: View the git log to confirm all commits**

```bash
git log --oneline -15
```

Expected: 13 commits from this plan, all with clear messages.

---

## Task 15: Update GitHub repository metadata

**Prerequisites:** Tasks 1-14 complete and pushed to `origin/master`. Requires `gh` CLI authenticated (`gh auth status` must show logged in as `hankthebldr`).

**Repo:** `hankthebldr/local-ai-platform` (stays — do not rename for MVP).

- [ ] **Step 1: Verify gh CLI is authenticated**

```bash
gh auth status
```

Expected: "Logged in to github.com as hankthebldr".

- [ ] **Step 2: Update repository description**

```bash
gh repo edit hankthebldr/local-ai-platform \
  --description "Enclave — Self-hosted LLM infrastructure with OpenAI-compatible API. CPU-optimized. Buy once, run forever. (by ohno llc)"
```

Expected: command succeeds, no output on success.

- [ ] **Step 3: Set repository topics**

```bash
gh repo edit hankthebldr/local-ai-platform \
  --add-topic enclave \
  --add-topic self-hosted \
  --add-topic llm \
  --add-topic ollama \
  --add-topic openai-compatible \
  --add-topic cpu-inference \
  --add-topic local-ai \
  --add-topic privacy \
  --add-topic ai-inference \
  --add-topic macos
```

- [ ] **Step 4: Disable wiki, enable discussions**

```bash
gh repo edit hankthebldr/local-ai-platform \
  --enable-wiki=false \
  --enable-discussions=true
```

Discussions serve as the community/support channel for the commercial product. Wiki is unused clutter.

- [ ] **Step 5: Upload the social preview image**

Use the GitHub REST API to upload `assets/social/social-preview.png` as the repo's social card:

```bash
# The REST API for social preview requires a multipart upload; gh doesn't have a flag for this yet.
# Manual alternative: open the repo settings page and upload the image
open "https://github.com/hankthebldr/local-ai-platform/settings"
```

Then in the browser: Settings → General → Social preview → Upload an image → select `assets/social/social-preview.png` → Save.

Verify via:

```bash
curl -s -o /dev/null -w "%{http_code}" "https://repository-images.githubusercontent.com/$(gh api repos/hankthebldr/local-ai-platform --jq .id)/social-preview.png"
```

Expected: `200` once image is uploaded.

- [ ] **Step 6: Verify all settings are correct**

```bash
gh repo view hankthebldr/local-ai-platform --json name,description,repositoryTopics,hasWikiEnabled,hasDiscussionsEnabled,homepageUrl
```

Expected JSON output shows:
- description includes "Enclave"
- 10 topics set
- hasWikiEnabled: false
- hasDiscussionsEnabled: true

---

## Task 16: Create GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

Runs lint + test on every push and PR to catch regressions.

- [ ] **Step 1: Create the workflows directory**

```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Write the CI workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

jobs:
  test:
    name: Test (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.12", "3.13"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r setup/requirements-core.txt
          pip install -r setup/requirements-dev.txt

      - name: Run tests
        run: pytest tests/ -v --tb=short

  lint:
    name: Lint
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install linters
        run: |
          python -m pip install --upgrade pip
          pip install black flake8 mypy

      - name: Check formatting (black)
        run: black --check api/ cli/ models/ || echo "::warning::Black formatting issues (non-blocking)"
        continue-on-error: true

      - name: Lint (flake8)
        run: flake8 api/ cli/ models/ --max-line-length=120 --extend-ignore=E501,W503 || echo "::warning::Flake8 issues (non-blocking)"
        continue-on-error: true
```

Note: lint jobs use `continue-on-error` to avoid blocking PRs on style issues during rebrand. Tighten these once the codebase settles.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow for test and lint"
```

- [ ] **Step 4: Push and verify the workflow runs**

```bash
git push origin master
sleep 10
gh run list --limit 3
```

Expected: a `CI` run appears in the list, status `in_progress` or `queued`.

- [ ] **Step 5: Watch the first run complete**

```bash
gh run watch
```

Expected: both `test` jobs pass (lint jobs may show warnings but not fail).

---

## Task 17: Create release workflow for DMG builds

**Files:**
- Create: `.github/workflows/release.yml`

Builds the macOS DMG when a git tag matching `v*.*.*` is pushed, and attaches it to a GitHub Release automatically.

- [ ] **Step 1: Write the release workflow**

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags:
      - "v*.*.*"

jobs:
  build-macos:
    name: Build macOS DMG
    runs-on: macos-14

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install librsvg (for icon generation)
        run: brew install librsvg imagemagick create-dmg

      - name: Regenerate assets
        run: |
          ./scripts/generate-icons.sh
          ls -la assets/icons/icon.icns

      - name: Install build dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r setup/requirements-core.txt

      - name: Build DMG
        run: ./scripts/build_mac.sh

      - name: Verify DMG exists
        run: |
          test -f dist/Enclave.dmg
          ls -la dist/

      - name: Extract version from tag
        id: version
        run: echo "version=${GITHUB_REF#refs/tags/}" >> $GITHUB_OUTPUT

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          name: Enclave ${{ steps.version.outputs.version }}
          body: |
            ## Enclave ${{ steps.version.outputs.version }}

            Self-hosted AI inference. CPU-optimized. By ohno llc.

            ### Download

            Download `Enclave.dmg` below and drag to your Applications folder.

            **Requirements:** macOS 12.0+ (Monterey or later)

            ### License

            Commercial license required to use Enclave. See [LICENSE](https://github.com/hankthebldr/local-ai-platform/blob/master/LICENSE) for terms.

            Contact ohno llc for Individual or Teams license pricing.
          files: |
            dist/Enclave.dmg
          draft: false
          prerelease: false
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add release workflow — build DMG and publish GitHub Release on tag"
```

- [ ] **Step 3: Push**

```bash
git push origin master
```

- [ ] **Step 4: Tag v1.0.0 and trigger the first release**

```bash
git tag -a v1.0.0 -m "Enclave v1.0.0 — initial release"
git push origin v1.0.0
```

- [ ] **Step 5: Watch the release workflow**

```bash
sleep 15
gh run list --workflow=release.yml --limit 1
gh run watch
```

Expected: workflow runs, DMG is built, release is created.

- [ ] **Step 6: Verify the release was published**

```bash
gh release view v1.0.0
```

Expected: release exists with `Enclave.dmg` attached as an asset.

---

## Task 18: Set up GitHub Pages for documentation landing

**Files:**
- Create: `docs/pages/index.html`
- Create: `docs/pages/styles.css`
- Create: `.github/workflows/pages.yml`

Publishes a simple landing/docs page at `https://hankthebldr.github.io/local-ai-platform/` using GitHub Pages. Serves as the product homepage until a proper marketing site is built.

- [ ] **Step 1: Create the pages source directory**

```bash
mkdir -p docs/pages
```

- [ ] **Step 2: Create the landing page HTML**

Create `docs/pages/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Enclave — Self-hosted AI inference</title>
  <meta name="description" content="Self-hosted LLM infrastructure with OpenAI-compatible API. CPU-optimized. Buy once, run forever.">

  <!-- Open Graph -->
  <meta property="og:title" content="Enclave">
  <meta property="og:description" content="Self-hosted AI inference. CPU-optimized. One price. Forever.">
  <meta property="og:image" content="https://hankthebldr.github.io/local-ai-platform/social-preview.png">
  <meta property="og:url" content="https://hankthebldr.github.io/local-ai-platform/">
  <meta property="og:type" content="website">

  <link rel="icon" type="image/x-icon" href="favicon.ico">
  <link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png">
  <link rel="stylesheet" href="styles.css">

  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@300;400;500&display=swap" rel="stylesheet">
</head>
<body>
  <header>
    <div class="container">
      <div class="logo">
        <svg width="32" height="32" viewBox="0 0 80 80">
          <rect x="6" y="6" width="68" height="68" rx="6" fill="none" stroke="#00E87B" stroke-width="2.5"/>
          <rect x="18" y="18" width="44" height="44" rx="3" fill="none" stroke="#00E87B" stroke-width="1.5" opacity="0.5"/>
          <rect x="28" y="28" width="24" height="24" rx="2" fill="#00E87B" opacity="0.2"/>
          <rect x="34" y="34" width="12" height="12" rx="1" fill="#00E87B" opacity="0.6"/>
        </svg>
        <span class="wordmark">ENCLAVE</span>
      </div>
      <nav>
        <a href="#features">Features</a>
        <a href="#download">Download</a>
        <a href="https://github.com/hankthebldr/local-ai-platform">GitHub</a>
      </nav>
    </div>
  </header>

  <main>
    <section class="hero">
      <div class="container">
        <h1>Self-hosted AI inference.<br>CPU-optimized. One price. Forever.</h1>
        <p class="subtitle">Enclave runs LLMs on your hardware. OpenAI-compatible API, Ollama backend, zero cloud dependencies.</p>
        <div class="cta">
          <a href="#download" class="btn-primary">Download v1.0.0</a>
          <a href="https://github.com/hankthebldr/local-ai-platform" class="btn-secondary">View on GitHub</a>
        </div>
      </div>
    </section>

    <section id="features" class="features">
      <div class="container">
        <h2>What it does</h2>
        <div class="grid">
          <div class="card">
            <h3>OpenAI-compatible API</h3>
            <p>Drop-in replacement. Point your existing code at localhost:8000.</p>
          </div>
          <div class="card">
            <h3>CPU-optimized</h3>
            <p>GGUF quantized models via Ollama. 7B at 40-50 tok/s, 13B at 25-30 tok/s.</p>
          </div>
          <div class="card">
            <h3>Zero telemetry</h3>
            <p>No data leaves your machine. No internet required for inference.</p>
          </div>
          <div class="card">
            <h3>Model registry</h3>
            <p>18+ models pre-catalogued. Download, configure, and switch with one command.</p>
          </div>
          <div class="card">
            <h3>Multi-agent workflows</h3>
            <p>YAML-defined step pipelines with role-based model selection.</p>
          </div>
          <div class="card">
            <h3>Native macOS app</h3>
            <p>Desktop wrapper with setup wizard. Linux support via direct install.</p>
          </div>
        </div>
      </div>
    </section>

    <section id="download" class="download">
      <div class="container">
        <h2>Get Enclave</h2>
        <p class="subtitle">Commercial software. Not open source. Source-available with commercial license.</p>
        <div class="license-grid">
          <div class="license">
            <h3>Individual</h3>
            <p>One seat. One-time purchase.<br>All updates included.<br>Personal and commercial use.</p>
            <a href="https://github.com/hankthebldr/local-ai-platform/releases/latest" class="btn-primary">Download DMG</a>
          </div>
          <div class="license">
            <h3>Teams</h3>
            <p>Volume discount per seat.<br>Shared infrastructure.<br>Priority support channel.</p>
            <a href="mailto:contact@ohno.llc?subject=Enclave%20Teams%20License" class="btn-secondary">Contact for pricing</a>
          </div>
        </div>
      </div>
    </section>
  </main>

  <footer>
    <div class="container">
      <p>Enclave v1.0.0 — by ohno llc</p>
      <p><a href="https://github.com/hankthebldr/local-ai-platform">GitHub</a> &middot; <a href="https://github.com/hankthebldr/local-ai-platform/blob/master/LICENSE">License</a> &middot; <a href="https://github.com/hankthebldr/local-ai-platform/discussions">Discussions</a></p>
    </div>
  </footer>
</body>
</html>
```

- [ ] **Step 3: Create the stylesheet**

Create `docs/pages/styles.css`:

```css
:root {
  --void: #0a0a0a;
  --deep: #1a1a2e;
  --surface: #141414;
  --border: #222222;
  --green: #00E87B;
  --cyan: #00C0E8;
  --orange: #FA582D;
  --text-primary: #E0E0E0;
  --text-secondary: #888888;
  --text-muted: #555555;
  --font-mono: "JetBrains Mono", "SF Mono", "Fira Code", monospace;
  --font-sans: "Space Grotesk", "Inter", "Helvetica Neue", sans-serif;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: var(--font-sans);
  background: var(--void);
  color: var(--text-primary);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

.container {
  max-width: 1100px;
  margin: 0 auto;
  padding: 0 24px;
}

/* Header */
header {
  border-bottom: 1px solid var(--border);
  padding: 20px 0;
  position: sticky;
  top: 0;
  background: rgba(10, 10, 10, 0.95);
  backdrop-filter: blur(10px);
  z-index: 10;
}
header .container { display: flex; align-items: center; justify-content: space-between; }
.logo { display: flex; align-items: center; gap: 10px; }
.wordmark {
  font-family: var(--font-mono);
  font-weight: 700;
  letter-spacing: 2px;
  color: var(--green);
}
nav { display: flex; gap: 24px; }
nav a {
  color: var(--text-secondary);
  text-decoration: none;
  font-family: var(--font-mono);
  font-size: 13px;
  transition: color 0.2s;
}
nav a:hover { color: var(--green); }

/* Hero */
.hero {
  padding: 120px 0;
  background: linear-gradient(135deg, var(--void) 0%, #0d1520 100%);
  position: relative;
  overflow: hidden;
}
.hero::before {
  content: "";
  position: absolute;
  inset: 0;
  background-image: linear-gradient(var(--deep) 1px, transparent 1px),
                    linear-gradient(90deg, var(--deep) 1px, transparent 1px);
  background-size: 40px 40px;
  opacity: 0.3;
}
.hero .container { position: relative; }
.hero h1 {
  font-family: var(--font-mono);
  font-size: 48px;
  font-weight: 700;
  line-height: 1.2;
  margin-bottom: 20px;
  letter-spacing: -0.5px;
}
.hero .subtitle {
  font-size: 20px;
  color: var(--text-secondary);
  margin-bottom: 40px;
  max-width: 700px;
}

/* Buttons */
.cta { display: flex; gap: 12px; flex-wrap: wrap; }
.btn-primary, .btn-secondary {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 1px;
  padding: 14px 24px;
  border-radius: 4px;
  text-decoration: none;
  transition: all 0.2s;
  display: inline-block;
}
.btn-primary {
  background: var(--green);
  color: var(--void);
}
.btn-primary:hover { background: #00ff88; }
.btn-secondary {
  border: 1px solid var(--border);
  color: var(--text-primary);
}
.btn-secondary:hover { border-color: var(--green); color: var(--green); }

/* Features */
.features { padding: 100px 0; }
.features h2, .download h2 {
  font-family: var(--font-mono);
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 1px;
  margin-bottom: 40px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
}
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 24px;
  transition: border-color 0.2s;
}
.card:hover { border-color: var(--green); }
.card h3 {
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 700;
  color: var(--green);
  margin-bottom: 10px;
  letter-spacing: 1px;
}
.card p { color: var(--text-secondary); font-size: 14px; }

/* Download */
.download {
  padding: 100px 0;
  background: var(--surface);
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}
.download .subtitle {
  color: var(--text-secondary);
  margin-bottom: 40px;
}
.license-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
@media (max-width: 700px) { .license-grid { grid-template-columns: 1fr; } }
.license {
  background: var(--void);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 32px;
}
.license h3 {
  font-family: var(--font-mono);
  font-size: 18px;
  font-weight: 700;
  color: var(--green);
  margin-bottom: 16px;
  letter-spacing: 1px;
}
.license p {
  color: var(--text-secondary);
  margin-bottom: 24px;
  font-size: 14px;
}

/* Footer */
footer {
  padding: 40px 0;
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}
footer a {
  color: var(--text-secondary);
  text-decoration: none;
}
footer a:hover { color: var(--green); }
footer p { margin: 4px 0; }

/* Mobile */
@media (max-width: 640px) {
  .hero h1 { font-size: 32px; }
  .hero .subtitle { font-size: 16px; }
  nav { gap: 16px; }
  nav a { font-size: 12px; }
}
```

- [ ] **Step 4: Copy brand assets into the pages directory**

GitHub Pages serves from the directory — copy what the HTML references:

```bash
cp assets/social/social-preview.png docs/pages/social-preview.png
cp assets/icons/favicon.ico docs/pages/favicon.ico
cp assets/icons/icon-180.png docs/pages/apple-touch-icon.png
```

- [ ] **Step 5: Create the Pages deploy workflow**

Create `.github/workflows/pages.yml`:

```yaml
name: Deploy Pages

on:
  push:
    branches: [master]
    paths:
      - "docs/pages/**"
      - ".github/workflows/pages.yml"
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/configure-pages@v5

      - name: Upload pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: docs/pages

      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 6: Commit**

```bash
git add docs/pages/ .github/workflows/pages.yml
git commit -m "feat: add GitHub Pages landing site for Enclave"
```

- [ ] **Step 7: Push**

```bash
git push origin master
```

- [ ] **Step 8: Enable GitHub Pages in repository settings**

```bash
# Enable Pages with GitHub Actions as the source
gh api -X POST repos/hankthebldr/local-ai-platform/pages \
  -f 'build_type=workflow' \
  2>/dev/null || echo "Pages already enabled or requires manual setup"

# If the above fails, enable via the browser:
open "https://github.com/hankthebldr/local-ai-platform/settings/pages"
# Then: Source → Deploy from a GitHub Actions workflow → Save
```

- [ ] **Step 9: Watch the Pages workflow run**

```bash
sleep 10
gh run list --workflow=pages.yml --limit 1
gh run watch
```

Expected: workflow succeeds, Pages URL is `https://hankthebldr.github.io/local-ai-platform/`.

- [ ] **Step 10: Verify the page is live**

```bash
sleep 30
curl -s -o /dev/null -w "%{http_code}" "https://hankthebldr.github.io/local-ai-platform/"
```

Expected: `200`.

- [ ] **Step 11: Set the repo homepage URL**

```bash
gh repo edit hankthebldr/local-ai-platform \
  --homepage "https://hankthebldr.github.io/local-ai-platform/"
```

- [ ] **Step 12: Verify the homepage is set**

```bash
gh repo view --json homepageUrl
```

Expected: `{"homepageUrl":"https://hankthebldr.github.io/local-ai-platform/"}`.

---

## Task 19: Create issue and PR templates

**Files:**
- Create: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Create: `.github/ISSUE_TEMPLATE/feature_request.yml`
- Create: `.github/ISSUE_TEMPLATE/license_inquiry.yml`
- Create: `.github/ISSUE_TEMPLATE/config.yml`
- Create: `.github/PULL_REQUEST_TEMPLATE.md`

- [ ] **Step 1: Create the ISSUE_TEMPLATE directory**

```bash
mkdir -p .github/ISSUE_TEMPLATE
```

- [ ] **Step 2: Create bug report template**

Create `.github/ISSUE_TEMPLATE/bug_report.yml`:

```yaml
name: Bug Report
description: Report a defect in Enclave
labels: [bug]
body:
  - type: textarea
    id: description
    attributes:
      label: Description
      description: What happened? What did you expect to happen?
    validations:
      required: true

  - type: textarea
    id: repro
    attributes:
      label: Steps to reproduce
      placeholder: |
        1. Run `...`
        2. Send request to `...`
        3. Observe error in logs
    validations:
      required: true

  - type: input
    id: version
    attributes:
      label: Enclave version
      placeholder: "v1.0.0"
    validations:
      required: true

  - type: dropdown
    id: os
    attributes:
      label: Operating system
      options:
        - macOS 12 (Monterey)
        - macOS 13 (Ventura)
        - macOS 14 (Sonoma)
        - macOS 15 (Sequoia)
        - Linux
        - Other
    validations:
      required: true

  - type: textarea
    id: logs
    attributes:
      label: Logs
      description: Relevant log output (API logs, Ollama logs)
      render: shell
```

- [ ] **Step 3: Create feature request template**

Create `.github/ISSUE_TEMPLATE/feature_request.yml`:

```yaml
name: Feature Request
description: Suggest a new feature or capability
labels: [enhancement]
body:
  - type: textarea
    id: problem
    attributes:
      label: Problem
      description: What problem does this solve?
    validations:
      required: true

  - type: textarea
    id: solution
    attributes:
      label: Proposed solution
    validations:
      required: true

  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives considered
```

- [ ] **Step 4: Create license inquiry template**

Create `.github/ISSUE_TEMPLATE/license_inquiry.yml`:

```yaml
name: License Inquiry
description: Questions about Individual or Teams licensing
labels: [licensing]
body:
  - type: dropdown
    id: tier
    attributes:
      label: Interested tier
      options:
        - Individual
        - Teams
        - Not sure
    validations:
      required: true

  - type: input
    id: seats
    attributes:
      label: Number of seats (Teams only)

  - type: textarea
    id: use-case
    attributes:
      label: Use case
      description: Briefly describe your intended use
```

- [ ] **Step 5: Create issue config**

Create `.github/ISSUE_TEMPLATE/config.yml`:

```yaml
blank_issues_enabled: false
contact_links:
  - name: Discussions
    url: https://github.com/hankthebldr/local-ai-platform/discussions
    about: Ask questions, share ideas, show what you've built
  - name: License Purchase
    url: mailto:contact@ohno.llc
    about: Contact ohno llc for commercial licensing
```

- [ ] **Step 6: Create PR template**

Create `.github/PULL_REQUEST_TEMPLATE.md`:

```markdown
## Summary

<!-- What does this PR change and why? -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Refactor
- [ ] Branding / assets

## Testing

- [ ] `pytest tests/` passes
- [ ] Manual smoke test on local Ollama
- [ ] No breaking changes to the OpenAI-compatible API surface

## License acknowledgement

- [ ] I understand Enclave is commercial software and I am contributing under the terms of the [LICENSE](../LICENSE)
```

- [ ] **Step 7: Commit**

```bash
git add .github/ISSUE_TEMPLATE/ .github/PULL_REQUEST_TEMPLATE.md
git commit -m "chore: add issue templates and PR template"
```

- [ ] **Step 8: Push**

```bash
git push origin master
```

---

## Task 20: Final GitHub verification

- [ ] **Step 1: Run full verification**

```bash
echo "=== Repo metadata ==="
gh repo view --json name,description,repositoryTopics,hasWikiEnabled,hasDiscussionsEnabled,homepageUrl

echo ""
echo "=== Releases ==="
gh release list --limit 3

echo ""
echo "=== Workflows ==="
gh workflow list

echo ""
echo "=== Recent runs ==="
gh run list --limit 5

echo ""
echo "=== Pages URL ==="
curl -s -o /dev/null -w "Pages status: %{http_code}\n" "https://hankthebldr.github.io/local-ai-platform/"

echo ""
echo "=== Issue templates ==="
ls -la .github/ISSUE_TEMPLATE/
```

Expected:
- Description contains "Enclave"
- 10 topics set
- Discussions enabled, wiki disabled
- Homepage URL set to GitHub Pages
- At least one v1.0.0 release with DMG
- Three workflows: CI, Release, Deploy Pages
- Pages returns 200
- Four template files present

- [ ] **Step 2: View the final git log**

```bash
git log --oneline -25
```

Expected: clean commit history from Task 1 through Task 19, all with semantic commit messages.

---

## Summary of what this builds

**Brand assets (Tasks 1-14):** logo SVGs, app icon (`.icns`), favicon, social preview, DMG background, 8 feature illustrations, color palette reference, full codebase rename.

**GitHub configuration (Tasks 15-20):** repo metadata, topics, social preview uploaded, Discussions enabled, CI workflow (test + lint), Release workflow (DMG build + publish on tag), GitHub Pages landing site, issue/PR templates, homepage URL.

**What ships after:** a public repo that looks professional, a downloadable v1.0.0 DMG, a live landing page at `hankthebldr.github.io/local-ai-platform`, and automation that rebuilds the DMG for every future tag.
