#!/bin/bash
set -e

echo "=== Enclave — macOS Build Pipeline ==="
echo ""

# Ensure we're in the project root
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

# Resolve a version string for CFBundle{Short}VersionString.
# Priority: explicit ENCLAVE_VERSION env > git tag > short SHA > "0.0.0-dev".
# Strips a leading "v" so "v1.1.0" → "1.1.0" (CFBundle expects no prefix).
if [ -n "${ENCLAVE_VERSION:-}" ]; then
    BUILD_VERSION="${ENCLAVE_VERSION#v}"
elif command -v git &>/dev/null && git -C "$PROJECT_ROOT" rev-parse --git-dir &>/dev/null; then
    GIT_DESC="$(git -C "$PROJECT_ROOT" describe --tags --always --dirty 2>/dev/null || echo "")"
    if [ -n "$GIT_DESC" ]; then
        BUILD_VERSION="${GIT_DESC#v}"
    else
        BUILD_VERSION="0.0.0-dev"
    fi
else
    BUILD_VERSION="0.0.0-dev"
fi
# CFBundleShortVersionString must be numeric-only (X.Y.Z). Strip any trailing
# "-N-gSHA-dirty" suffix that git describe adds between tags.
BUILD_SHORT_VERSION="$(echo "$BUILD_VERSION" | sed -E 's/-[0-9]+-g[0-9a-f]+(-dirty)?$//')"
echo "  Building Enclave version: ${BUILD_VERSION} (short: ${BUILD_SHORT_VERSION})"

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

APP_NAME="Enclave"
APP_DIR="dist/${APP_NAME}.app"
CONTENTS="${APP_DIR}/Contents"
MACOS="${CONTENTS}/MacOS"
RESOURCES="${CONTENTS}/Resources"

mkdir -p "${MACOS}"
mkdir -p "${RESOURCES}"

# Copy platform code + runtime data dirs. These mirror the Dockerfile
# COPY set (post-PR #43) so the .app surfaces every tab the same way the
# docker stack does. Without agents/, workflows/, prompts/ the matching
# tabs render empty even though the API serves correctly.
cp -R api "${RESOURCES}/api"
cp -R plugins "${RESOURCES}/plugins"
cp -R cli "${RESOURCES}/cli"
cp -R models "${RESOURCES}/models"
cp -R agents "${RESOURCES}/agents"
cp -R workflows "${RESOURCES}/workflows"
cp -R prompts "${RESOURCES}/prompts"
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

# Install runtime deps. Use requirements-rag.txt (which extends -core via -r)
# so the bundled venv carries chromadb + sentence-transformers — needed for
# the Documents tab and memory RAG. Previous core-only installs left the
# Documents tab returning 503 in the shipped .app.
"${RESOURCES}/venv/bin/pip" install --quiet -r setup/requirements-rag.txt
# pywebview is a desktop-only dep; not in either requirements file.
"${RESOURCES}/venv/bin/pip" install --quiet pywebview

echo "  Python environment ready"

# Create launcher script
cat > "${MACOS}/launch.sh" << 'LAUNCHER'
#!/bin/bash
# Enclave — macOS Launcher
DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
USER_DATA="${HOME}/.local-ai-platform"

# Activate bundled Python
source "${DIR}/venv/bin/activate"

# Set up environment — user data lives in ~/.local-ai-platform, NOT inside the bundle
export PYTHONPATH="${DIR}"
export DATA_CONFIG_DIR="${USER_DATA}/config"
export RAG_DATA_DIR="${USER_DATA}/rag"
mkdir -p "${USER_DATA}/config" "${USER_DATA}/logs"

# Load user's .env from ~/.local-ai-platform/.env (NOT from the bundle — secrets stay user-side)
if [ -f "${USER_DATA}/.env" ]; then
    set -a
    source "${USER_DATA}/.env"
    set +a
fi

cd "${DIR}"

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

# Create Info.plist (version stamped from BUILD_VERSION resolved above)
cat > "${CONTENTS}/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Enclave</string>
    <key>CFBundleDisplayName</key>
    <string>Enclave</string>
    <key>CFBundleIdentifier</key>
    <string>com.enclave.app</string>
    <key>CFBundleVersion</key>
    <string>${BUILD_VERSION}</string>
    <key>CFBundleShortVersionString</key>
    <string>${BUILD_SHORT_VERSION}</string>
    <key>CFBundleExecutable</key>
    <string>Enclave</string>
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
        --volname "Enclave" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon "${APP_NAME}.app" 150 200 \
        --app-drop-link 450 200 \
        --no-internet-enable \
        "dist/Enclave.dmg" \
        "${APP_DIR}" \
        2>/dev/null || {
            echo "  create-dmg failed, using hdiutil fallback..."
            hdiutil create -volname "Enclave" \
                -srcfolder "${APP_DIR}" \
                -ov -format UDZO \
                "dist/Enclave.dmg"
        }
else
    echo "  create-dmg not found, using hdiutil..."
    hdiutil create -volname "Enclave" \
        -srcfolder "${APP_DIR}" \
        -ov -format UDZO \
        "dist/Enclave.dmg"
fi

echo ""
echo "=== Build Complete ==="
echo "  App: ${APP_DIR}"
echo "  DMG: dist/Enclave.dmg"
echo "  App Size: $(du -sh "${APP_DIR}" | cut -f1)"
echo "  DMG Size: $(du -sh "dist/Enclave.dmg" | cut -f1)"
echo ""
echo "To test: open '${APP_DIR}'"
