#!/bin/bash
set -e

echo "=== Local AI Platform — macOS Build Pipeline ==="
echo ""

# Ensure we're in the project root
cd "$(dirname "$0")/.."

# ── Step 1: Check prerequisites ─────────────────────────────────────
echo "[1/4] Checking prerequisites..."

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found"
    exit 1
fi

if ! python3 -c "import py2app" 2>/dev/null; then
    echo "Installing py2app..."
    pip install py2app
fi

if ! command -v create-dmg &>/dev/null; then
    echo "Installing create-dmg..."
    if command -v brew &>/dev/null; then
        brew install create-dmg
    else
        echo "ERROR: create-dmg not found. Install via: brew install create-dmg"
        exit 1
    fi
fi

echo "  Prerequisites OK"

# ── Step 2: Clean previous build ────────────────────────────────────
echo "[2/4] Cleaning previous build..."
rm -rf build/ dist/

# ── Step 3: Build .app with py2app ──────────────────────────────────
echo "[3/4] Building .app bundle..."
python3 desktop/setup_py2app.py py2app

if [ ! -d "dist/Local AI Platform.app" ] && [ ! -d "dist/app.app" ]; then
    echo "ERROR: py2app failed to produce .app bundle"
    exit 1
fi

# Rename if py2app used the script name
if [ -d "dist/app.app" ]; then
    mv "dist/app.app" "dist/Local AI Platform.app"
fi

echo "  .app bundle created"

# ── Step 4: Create DMG ──────────────────────────────────────────────
echo "[4/4] Creating DMG..."

create-dmg \
    --volname "Local AI Platform" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon "Local AI Platform.app" 150 200 \
    --app-drop-link 450 200 \
    --no-internet-enable \
    "dist/LocalAIPlatform.dmg" \
    "dist/Local AI Platform.app" \
    2>/dev/null || {
        # Fallback: create DMG with hdiutil if create-dmg fails
        echo "  create-dmg failed, using hdiutil fallback..."
        hdiutil create -volname "Local AI Platform" \
            -srcfolder "dist/Local AI Platform.app" \
            -ov -format UDZO \
            "dist/LocalAIPlatform.dmg"
    }

echo ""
echo "=== Build Complete ==="
echo "  DMG: dist/LocalAIPlatform.dmg"
echo "  Size: $(du -sh "dist/LocalAIPlatform.dmg" | cut -f1)"
