#!/usr/bin/env bash
# Boot Enclave the same way the macOS DMG does — pywebview window + bundled
# API server — so desktop-only regressions surface locally before they ship.
#
# Differences from the DMG path:
#   - Uses ./venv (your dev venv) instead of a freshly bundled one
#   - Uses your repo files directly (no .app copy)
#   - Honors $ENCLAVE_DESKTOP_URL to override the URL the window opens
#
# Usage: ./scripts/start_desktop.sh
#
# Prereqs:
#   - venv exists with setup/requirements-core.txt installed
#   - pywebview installed (added on demand if missing)
#   - Ollama installed (started automatically if not running)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[\xe2\x9c\x93]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[\xe2\x9c\x97]${NC} $1"; exit 1; }

if [[ "$(uname -s)" != "Darwin" ]]; then
    warn "start_desktop.sh is designed for macOS (the DMG target)."
    warn "On Linux the pywebview window may use GTK; YMMV."
fi

# 1. venv
if [ ! -d venv ]; then
    fail "./venv missing. Run ./setup/install.sh or ./scripts/verify_local.sh first."
fi
# shellcheck source=/dev/null
source venv/bin/activate

# 2. pywebview (desktop-only dep, not in requirements-core.txt)
if ! python -c "import webview" >/dev/null 2>&1; then
    warn "pywebview not installed; installing into ./venv ..."
    pip install --quiet pywebview
fi
ok "venv + pywebview ready"

# 3. Ollama
if ! command -v ollama >/dev/null 2>&1; then
    warn "ollama not installed — the desktop app will still launch, but"
    warn "model inference will fail until you install it (https://ollama.ai)."
elif ! curl -sf -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
    warn "ollama not running; starting in background"
    ollama serve >/tmp/ollama-desktop.log 2>&1 &
    OLLAMA_PID=$!
    trap 'kill $OLLAMA_PID 2>/dev/null || true' EXIT
    for _ in $(seq 1 20); do
        curl -sf -m 1 http://localhost:11434/api/tags >/dev/null 2>&1 && break
        sleep 0.5
    done
    ok "ollama started (pid $OLLAMA_PID)"
else
    ok "ollama already running"
fi

# 4. Tip: which window URL will open
SETUP_FLAG="${HOME}/.enclave/setup_complete"
if [ -f "$SETUP_FLAG" ]; then
    echo "  First-run setup already complete \xe2\x86\x92 dashboard at /"
else
    echo "  First-run detected \xe2\x86\x92 desktop window will open the setup wizard at /setup"
    echo "  (Touch ${SETUP_FLAG} to skip the wizard on next launch.)"
fi

# 5. Hand off to desktop/app.py — identical to what the DMG launcher runs.
echo
ok "Launching native window via desktop/app.py ..."
exec python desktop/app.py
