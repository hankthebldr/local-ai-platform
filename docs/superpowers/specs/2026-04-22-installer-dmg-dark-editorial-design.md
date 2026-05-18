# Installer DMG — Dark Editorial Background

**Date:** 2026-04-22
**Status:** Approved design
**Scope:** macOS installer DMG only

## Problem

The shipped `Enclave.dmg` uses macOS's default white window chrome with no
background art. A dark-styled background asset exists at
`assets/installer/dmg-background.{svg,png,@2x.png}` but `scripts/build_mac.sh`
never passes `--background` to `create-dmg`, so the asset is dead code. The
current SVG is also sparse (wordmark + hairline arrow + tagline) and doesn't
match the fidelity of the brand system in `assets/logo/` and
`assets/brand/color-palette.svg`.

## Goal

Ship a dark, editorial DMG background that uses the Enclave brand vocabulary,
and wire it into the build so it actually appears when a user mounts the DMG.

## Non-goals

- App icon redesign.
- In-app welcome/first-run screen.
- Light-mode DMG variant (macOS DMGs don't adapt to system appearance).
- Signing / notarization changes.

## Design

### Canvas

660×400pt. The current `scripts/build_mac.sh` passes `--window-size 600 400`
and the existing background asset is 660×400 — these have never agreed. We
standardize on **660×400** to match the asset (the extra horizontal room is
useful for the editorial headline) and update the window size accordingly.

### Composition (top to bottom)

1. **Brand row** — small nested-square mark + `ENCLAVE` wordmark, left-aligned
   at (40, 36). Mark reuses the geometry from `assets/logo/enclave-lockup.svg`.
   Wordmark in JetBrains Mono 13px, weight 700, letter-spacing 3, `#e8eaf0`.
2. **Hairline divider** — 1px line at y=75 from x=40 to x=620, stroke
   `#1a2030`.
3. **Headline** — single line at (40, 115), 24px, weight 600, Space Grotesk
   with SF Pro Display fallback: `Your models.` in `#e8eaf0` followed by
   `Your machine.` in Enclave green `#00E87B`.
4. **Sub-caption** — (40, 140), SF Pro Text 12px, `#6b7689`:
   `Drag Enclave.app into Applications to install.`
5. **Install row** — kept at y=200 (matches existing `create-dmg` coordinates:
   app icon at (150, 200), Applications alias at (450, 200)). Background is
   empty at those positions except a faint green radial vignette centered at
   (330, 220), 2.5% opacity, to add depth behind the icons.
6. **Footer** — bottom-right at (620, 370), JetBrains Mono 9px, `#3a4560`,
   letter-spacing 2: `v{VERSION}`.

### Palette

| Token           | Hex        | Use                     |
|-----------------|------------|-------------------------|
| `bg-top`        | `#07080b`  | Background gradient top |
| `bg-bottom`     | `#0f1118`  | Background gradient bot |
| `accent`        | `#00E87B`  | Highlight half of headline, footer separator |
| `text-primary`  | `#e8eaf0`  | Headline primary, wordmark |
| `text-muted`    | `#6b7689`  | Sub-caption             |
| `text-quiet`    | `#3a4560`  | Footer                  |
| `hairline`      | `#1a2030`  | Divider                 |

All values match the existing brand system (`assets/brand/color-palette.svg`).

### Typography

- `JetBrains Mono` (wordmark, footer) — already committed in
  `assets/logo/enclave-lockup.svg` via `font-family`.
- `Space Grotesk` with `SF Pro Display` fallback (headline).
- `SF Pro Text` (sub-caption).

Fonts are referenced by name in the SVG. macOS renders JetBrains Mono only if
installed; the SVG→PNG rasterization must happen on a host that has it.
Alternative: embed the wordmark as outlined paths so the PNG is
font-independent. Plan step will evaluate whether the build host has the font
and fall back to outlining if not.

## Files

**Modified:**

- `assets/installer/dmg-background.svg` — replaced with editorial composition.
- `assets/installer/dmg-background.png` — re-exported at 660×400.
- `assets/installer/dmg-background@2x.png` — re-exported at 1320×800.
- `scripts/build_mac.sh`:
  - `--window-size 660 400` (was `600 400`).
  - Add `--background "assets/installer/dmg-background.png"` to the
    `create-dmg` invocation.
  - `hdiutil` fallback: no background support — leave bare. Acceptable because
    `create-dmg` is the primary path and the fallback is for hosts without it.
  - Stamp the running `VERSION` into the SVG footer before raster export so
    the DMG artwork always matches `CFBundleShortVersionString`.

**Added:**

- `assets/installer/explorations/a-vault.svg`
- `assets/installer/explorations/b-terminal.svg`
- `assets/installer/explorations/c-editorial.svg`

Retained as reference artifacts for future iteration / brand documentation.
Committed, not gitignored.

## Build integration

Pseudocode for the version-stamping step (to be flesh-out in the plan):

```bash
SRC="assets/installer/dmg-background.svg"
TMP="$(mktemp -t enclave-dmg-bg.XXXXXX.svg)"
sed "s/{VERSION}/${VERSION}/g" "$SRC" > "$TMP"
# export 1x + 2x via rsvg-convert or qlmanage
rsvg-convert -w 660  -h 400  "$TMP" -o assets/installer/dmg-background.png
rsvg-convert -w 1320 -h 800  "$TMP" -o assets/installer/dmg-background@2x.png
```

Build host already relies on `rsvg-convert` or Inkscape for icon generation
(see `scripts/generate-icons.sh`) — reuse that toolchain.

## Testing

- Local verification: `./scripts/build_mac.sh && open dist/Enclave.dmg`.
  Confirm the mounted DMG window shows the dark editorial background, with the
  app icon and Applications alias correctly positioned over the install row.
- Visual diff: rendered `dmg-background.png` committed for review.
- CI: `.github/workflows/release.yml` already builds the DMG; no new CI steps
  needed beyond ensuring the SVG → PNG toolchain is present on the runner.

## Risks

- **Font availability on the build host.** If JetBrains Mono / Space Grotesk
  aren't installed, the rasterized PNG falls back to system defaults and looks
  off. Mitigation: outline-convert text nodes before export, or bundle fonts
  alongside the SVG for the build step.
- **Window size change affects existing DMG layout coords.** We keep icon
  positions at (150, 200) and (450, 200); the window height doesn't change,
  only the width grew 600→660. Icons stay visually in roughly the same places.
- **hdiutil fallback loses the background.** Acceptable degradation — the
  fallback only fires when `create-dmg` is missing on a dev machine, not in
  release.

## References

- Existing exploration files: `assets/installer/explorations/`
- Brand system spec: `docs/superpowers/specs/2026-04-16-enclave-brand-system-design.md`
- Build script: `scripts/build_mac.sh`
