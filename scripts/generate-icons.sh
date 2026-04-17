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
