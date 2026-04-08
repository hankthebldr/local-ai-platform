#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Local AI Platform — macOS App Builder ==="
echo ""

# Check pywebview
if ! python -c "import webview" 2>/dev/null; then
    echo "Installing pywebview..."
    pip install pywebview
fi

# Check py2app
if ! python -c "import py2app" 2>/dev/null; then
    echo "Installing py2app..."
    pip install py2app
fi

cd "$SCRIPT_DIR"

# Clean previous build
rm -rf build dist

# Build
echo "Building .app bundle..."
python setup_app.py py2app 2>&1

if [ -d "dist/Local AI Platform.app" ]; then
    echo ""
    echo "SUCCESS: dist/Local AI Platform.app"
    echo "Size: $(du -sh dist/*.app | cut -f1)"
    echo ""
    echo "To run: open 'dist/Local AI Platform.app'"
    echo "To create DMG: brew install create-dmg && create-dmg dist/LocalAI.dmg 'dist/Local AI Platform.app'"
else
    echo "BUILD FAILED"
    exit 1
fi
