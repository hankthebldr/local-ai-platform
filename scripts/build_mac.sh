#!/bin/bash
set -e

echo "=== Local AI Platform — macOS Build Pipeline ==="
echo ""

# Ensure we're in the project root
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

# ── Step 1: Check prerequisites ─────────────────────────────────────
echo "[1/5] Checking prerequisites..."

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found"
    exit 1
fi

echo "  Prerequisites OK"

# ── Step 2: Clean previous build ────────────────────────────────────
echo "[2/5] Cleaning previous build..."
rm -rf build/ dist/
mkdir -p dist

# ── Step 3: Create .app bundle structure ────────────────────────────
echo "[3/5] Building .app bundle..."

APP_NAME="Local AI Platform"
APP_DIR="dist/${APP_NAME}.app"
CONTENTS="${APP_DIR}/Contents"
MACOS="${CONTENTS}/MacOS"
RESOURCES="${CONTENTS}/Resources"

mkdir -p "${MACOS}"
mkdir -p "${RESOURCES}"

# Copy platform code
cp -R api "${RESOURCES}/api"
cp -R plugins "${RESOURCES}/plugins"
cp -R cli "${RESOURCES}/cli"
cp -R models "${RESOURCES}/models"
[ -d data/profiles ] && cp -R data "${RESOURCES}/data" 2>/dev/null || true
[ -f .env ] && cp .env "${RESOURCES}/.env"
[ -f .env.example ] && cp .env.example "${RESOURCES}/.env.example"

# Copy Enclave icon into the bundle
ICON_SRC=""
if [ -f "assets/icons/icon.icns" ]; then
    ICON_SRC="assets/icons/icon.icns"
elif [ -f "desktop/icon.icns" ] && [ -s "desktop/icon.icns" ]; then
    ICON_SRC="desktop/icon.icns"
fi
if [ -n "$ICON_SRC" ]; then
    cp "$ICON_SRC" "${RESOURCES}/icon.icns"
    echo "  Copied icon from ${ICON_SRC}"
else
    echo "  WARNING: No icon.icns found — app will use default icon"
fi

# Create a bundled venv with only runtime deps
# Use Python 3.12 specifically (3.14 is too new for some wheels)
PYTHON_BIN="python3.12"
if ! command -v "$PYTHON_BIN" &>/dev/null; then
    PYTHON_BIN="python3.13"
fi
if ! command -v "$PYTHON_BIN" &>/dev/null; then
    PYTHON_BIN="python3.11"
fi
if ! command -v "$PYTHON_BIN" &>/dev/null; then
    PYTHON_BIN="python3"
fi
echo "  Creating bundled Python environment (${PYTHON_BIN})..."
"${PYTHON_BIN}" -m venv "${RESOURCES}/venv"
"${RESOURCES}/venv/bin/pip" install --quiet --upgrade pip
"${RESOURCES}/venv/bin/pip" install --quiet \
    fastapi==0.109.0 \
    "uvicorn[standard]==0.27.0" \
    pydantic==2.5.3 \
    python-dotenv==1.0.0 \
    python-multipart==0.0.6 \
    requests==2.31.0 \
    PyYAML==6.0.1 \
    psutil==5.9.7 \
    pywebview

echo "  Python environment ready"

# Create launcher script
cat > "${MACOS}/launch.sh" << 'LAUNCHER'
#!/bin/bash
# Local AI Platform — macOS Launcher
DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"

# Activate bundled Python
source "${DIR}/venv/bin/activate"

# Set up environment
export PYTHONPATH="${DIR}"
cd "${DIR}"

# Load .env if present
if [ -f "${DIR}/.env" ]; then
    set -a
    source "${DIR}/.env"
    set +a
fi

# Run the desktop app
exec python "${DIR}/../MacOS/app.py"
LAUNCHER
chmod +x "${MACOS}/launch.sh"

# Copy desktop entry point
cp desktop/app.py "${MACOS}/app.py"

# Create the main executable (calls launch.sh)
cat > "${MACOS}/${APP_NAME}" << 'EXEC'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "${DIR}/launch.sh"
EXEC
chmod +x "${MACOS}/${APP_NAME}"

# Create Info.plist
cat > "${CONTENTS}/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Local AI Platform</string>
    <key>CFBundleDisplayName</key>
    <string>Local AI Platform</string>
    <key>CFBundleIdentifier</key>
    <string>com.localai.platform</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleExecutable</key>
    <string>Local AI Platform</string>
    <key>CFBundleIconFile</key>
    <string>icon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
PLIST

echo "  .app bundle created: ${APP_DIR}"

# ── Step 4: Verify bundle ───────────────────────────────────────────
echo "[4/5] Verifying bundle..."

# Check key files exist
for f in "${RESOURCES}/api/main.py" "${RESOURCES}/plugins" "${RESOURCES}/venv/bin/python3"; do
    if [ ! -e "$f" ]; then
        echo "  ERROR: Missing ${f}"
        exit 1
    fi
done

# Quick import test
"${RESOURCES}/venv/bin/python3" -c "
import sys
sys.path.insert(0, '${RESOURCES}')
import fastapi, uvicorn, yaml, requests, psutil
print('  All runtime imports OK')
"

# ── Step 5: Create DMG ──────────────────────────────────────────────
echo "[5/5] Creating DMG..."

if command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "Local AI Platform" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon "${APP_NAME}.app" 150 200 \
        --app-drop-link 450 200 \
        --no-internet-enable \
        "dist/LocalAIPlatform.dmg" \
        "${APP_DIR}" \
        2>/dev/null || {
            echo "  create-dmg failed, using hdiutil fallback..."
            hdiutil create -volname "Local AI Platform" \
                -srcfolder "${APP_DIR}" \
                -ov -format UDZO \
                "dist/LocalAIPlatform.dmg"
        }
else
    echo "  create-dmg not found, using hdiutil..."
    hdiutil create -volname "Local AI Platform" \
        -srcfolder "${APP_DIR}" \
        -ov -format UDZO \
        "dist/LocalAIPlatform.dmg"
fi

echo ""
echo "=== Build Complete ==="
echo "  App: ${APP_DIR}"
echo "  DMG: dist/LocalAIPlatform.dmg"
echo "  App Size: $(du -sh "${APP_DIR}" | cut -f1)"
echo "  DMG Size: $(du -sh "dist/LocalAIPlatform.dmg" | cut -f1)"
echo ""
echo "To test: open '${APP_DIR}'"
