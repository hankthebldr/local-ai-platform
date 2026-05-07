#!/usr/bin/env bash
# Enclave — one-command Docker launcher for non-developers.
#
# Prerequisite:
#   Docker Desktop (macOS / Windows) or Docker Engine (Linux).
#   https://www.docker.com/products/docker-desktop/
#
# Usage:
#   ./run.sh                 # bring stack up, pull starter model on first run, open browser
#   SKIP_BROWSER=1 ./run.sh  # don't auto-open the browser
#   ENCLAVE_DEFAULT_MODEL=qwen2.5:3b ./run.sh   # use a different starter model

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

DEFAULT_MODEL="${ENCLAVE_DEFAULT_MODEL:-llama3.2:3b}"
FIRST_RUN_MARKER="$PROJECT_ROOT/data/.docker-first-run-complete"
DASHBOARD_URL="http://localhost:8000"
WEBUI_URL="http://localhost:8080"

if [ -t 1 ]; then
    BOLD=$'\e[1m'; DIM=$'\e[2m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RED=$'\e[31m'; CYAN=$'\e[36m'; RESET=$'\e[0m'
else
    BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; CYAN=""; RESET=""
fi

step() { echo "${BOLD}${CYAN}==>${RESET} $*"; }
ok()   { echo "  ${GREEN}✓${RESET} $*"; }
warn() { echo "  ${YELLOW}!${RESET} $*"; }
fail() { echo "  ${RED}✗${RESET} $*" >&2; }

# ── 1. Docker present? ───────────────────────────────────────────────
step "Checking Docker"
if ! command -v docker >/dev/null 2>&1; then
    fail "Docker is not installed."
    cat <<EOF

  Install Docker, then re-run this script:
    macOS / Windows : https://www.docker.com/products/docker-desktop/
    Linux           : https://docs.docker.com/engine/install/

EOF
    exit 1
fi
ok "Docker CLI: $(docker --version | head -n1)"

if ! docker info >/dev/null 2>&1; then
    fail "Docker daemon is not running."
    echo ""
    echo "  Start Docker Desktop, wait for it to finish loading, then re-run ./run.sh"
    echo ""
    exit 1
fi
ok "Docker daemon is running"

# Pick compose flavor (v2 plugin vs legacy v1)
if docker compose version >/dev/null 2>&1; then
    DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    DC=(docker-compose)
else
    fail "Neither 'docker compose' nor 'docker-compose' is available."
    echo "  Update Docker Desktop or install the compose plugin."
    exit 1
fi

# ── 2. Bring the stack up ────────────────────────────────────────────
step "Starting Enclave stack (ollama + api + webui)"
"${DC[@]}" up -d

# ── 3. Wait for API health ───────────────────────────────────────────
step "Waiting for API at $DASHBOARD_URL"
HEALTHY=0
for i in $(seq 1 90); do
    if curl -sf -m 2 "$DASHBOARD_URL/health" >/dev/null 2>&1; then
        HEALTHY=1
        break
    fi
    sleep 1
done
if [ "$HEALTHY" -ne 1 ]; then
    fail "API did not become healthy within 90s."
    echo ""
    echo "  Inspect logs:   ${DC[*]} logs api"
    echo "  Inspect ollama: ${DC[*]} logs ollama"
    exit 1
fi
ok "API is healthy"

# ── 4. First-run starter model ───────────────────────────────────────
if [ ! -f "$FIRST_RUN_MARKER" ]; then
    step "First run — pulling starter model: $DEFAULT_MODEL (~2 GB, one time)"
    if "${DC[@]}" exec -T ollama ollama pull "$DEFAULT_MODEL"; then
        ok "Model ready: $DEFAULT_MODEL"
        mkdir -p "$(dirname "$FIRST_RUN_MARKER")"
        date -u +"%Y-%m-%dT%H:%M:%SZ" > "$FIRST_RUN_MARKER"
    else
        warn "Starter model pull failed — you can retry from the dashboard."
    fi
else
    ok "Starter model already initialized (delete $FIRST_RUN_MARKER to re-pull)"
fi

# ── 5. Status block ──────────────────────────────────────────────────
echo ""
echo "${BOLD}${GREEN}Enclave is running.${RESET}"
echo ""
echo "  ${BOLD}Open in your browser:${RESET}"
echo "      Dashboard      ${CYAN}${DASHBOARD_URL}${RESET}"
echo "      Chat (WebUI)   ${CYAN}${WEBUI_URL}${RESET}"
echo "      API docs       ${DIM}${DASHBOARD_URL}/docs${RESET}"
echo ""
echo "  ${BOLD}Manage:${RESET}"
echo "      Status         ${DIM}${DC[*]} ps${RESET}"
echo "      Tail logs      ${DIM}${DC[*]} logs -f${RESET}"
echo "      Stop           ${DIM}./stop.sh${RESET}"
echo "      Reset all data ${DIM}./stop.sh --reset${RESET}"
echo ""

# ── 6. Best-effort browser open ──────────────────────────────────────
if [ "${SKIP_BROWSER:-0}" != "1" ]; then
    if command -v open >/dev/null 2>&1; then
        open "$DASHBOARD_URL" >/dev/null 2>&1 || true
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$DASHBOARD_URL" >/dev/null 2>&1 || true
    fi
fi
