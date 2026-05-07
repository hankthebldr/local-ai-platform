#!/usr/bin/env bash
# Local install + startup verification for Enclave.
#
# Runs the same checks CI runs, plus boots the API briefly to confirm it
# actually starts. Safe to run on a workstation that doesn't have Ollama
# installed yet — Ollama checks are reported but don't fail the script.
#
# Usage: ./scripts/verify_local.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
fail() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo "==> 1/6  venv"
if [ ! -d venv ]; then
    python3 -m venv venv
    ok "created ./venv"
else
    ok "./venv already present"
fi

echo "==> 2/6  install core + dev requirements"
./venv/bin/pip install --upgrade pip --quiet
./venv/bin/pip install -q -r setup/requirements-core.txt -r setup/requirements-dev.txt
ok "deps installed"

echo "==> 3/6  api.main import smoke test"
./venv/bin/python -c "import api.main" >/dev/null 2>&1 \
    || fail "api.main failed to import"
ok "api.main imports"

echo "==> 4/6  API boot + UX-route probe"
[ -f .env ] || cp .env.example .env
LOG=$(mktemp)
ENABLE_API_AUTH=false API_HOST=127.0.0.1 \
    ./venv/bin/python -m api.main >"$LOG" 2>&1 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true; rm -f "$LOG"' EXIT

for _ in $(seq 1 20); do
    if curl -sf -m 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then
        break
    fi
    sleep 0.5
done

if ! curl -sf -m 5 http://127.0.0.1:8000/health >/dev/null; then
    echo "--- api log ---"; cat "$LOG"
    fail "API did not respond on /health"
fi
STATUS=$(curl -s http://127.0.0.1:8000/health | \
    ./venv/bin/python -c "import sys,json; print(json.load(sys.stdin)['status'])")
ok "API /health responding (status=$STATUS)"
[ "$STATUS" = "degraded" ] && warn "  degraded is expected when Ollama is not running"

# Hit every user-facing surface the dashboard exposes. A 200 with a non-empty
# body is the bar: catches static-mount regressions, missing index.html, and
# router include drift before they ship in a DMG.
UX_FAIL=0
for path in / /static/index.html /setup /api/info; do
    body=$(curl -s -m 5 -o /tmp/probe.body -w '%{http_code}' \
        "http://127.0.0.1:8000${path}")
    size=$(wc -c </tmp/probe.body | tr -d ' ')
    if [ "$body" != "200" ] || [ "$size" -lt 16 ]; then
        warn "  UX route ${path} -> HTTP ${body}, ${size} bytes"
        UX_FAIL=1
    else
        ok "  UX route ${path} -> ${body} (${size}B)"
    fi
done
rm -f /tmp/probe.body
[ "$UX_FAIL" = "1" ] && fail "one or more UX routes failed to render"

kill $API_PID 2>/dev/null || true
wait $API_PID 2>/dev/null || true

echo "==> 5/6  CLI --help"
for cli in cli/chat.py cli/query.py cli/workflow.py; do
    ./venv/bin/python "$cli" --help >/dev/null 2>&1 \
        || fail "$cli --help failed"
done
ok "chat/query/workflow CLIs respond to --help"

echo "==> 6/6  pytest (CI filter set)"
./venv/bin/pytest tests/ -q --tb=short \
    -k "not Integration and not TestAuthentication and not TestMultiKeyAuth" \
    -m "not rag" \
    || fail "pytest failed"
ok "test suite passed"

echo
ok "Local verification complete."
if ! command -v ollama >/dev/null 2>&1; then
    warn "Ollama is not installed — inference paths were not exercised."
    warn "Install: curl -fsSL https://ollama.ai/install.sh | sh"
fi
