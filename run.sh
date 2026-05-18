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
# Embedding model for the RAG pipeline (Documents tab + memory).
# Small (~280MB) and uses the same Ollama service — keeps the API container
# slim by avoiding the sentence-transformers + torch fallback path.
DEFAULT_EMBED_MODEL="${ENCLAVE_DEFAULT_EMBED_MODEL:-nomic-embed-text}"
FIRST_RUN_MARKER="$PROJECT_ROOT/data/.docker-first-run-complete"
DASHBOARD_URL="http://localhost:8000"
# Open WebUI moved to an opt-in compose override (docker-compose.webui.yml,
# port 8081). It's only printed below if the operator has explicitly
# brought up that override.
WEBUI_URL="http://localhost:8081"

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

# ── 4. First-run starter models ──────────────────────────────────────
# Pull a chat model (for the dashboard chat box and OpenAI-compat API)
# and an embedding model (for the Documents tab + memory RAG pipeline).
if [ ! -f "$FIRST_RUN_MARKER" ]; then
    step "First run — pulling chat starter: $DEFAULT_MODEL (~2 GB, one time)"
    CHAT_OK=0
    if "${DC[@]}" exec -T ollama ollama pull "$DEFAULT_MODEL"; then
        ok "Chat model ready: $DEFAULT_MODEL"
        CHAT_OK=1
    else
        warn "Chat model pull failed — you can retry from the dashboard."
    fi

    step "First run — pulling embed model: $DEFAULT_EMBED_MODEL (~280 MB, one time)"
    EMBED_OK=0
    if "${DC[@]}" exec -T ollama ollama pull "$DEFAULT_EMBED_MODEL"; then
        ok "Embed model ready: $DEFAULT_EMBED_MODEL"
        EMBED_OK=1
    else
        warn "Embed model pull failed — Documents tab and memory RAG will be unavailable."
    fi

    if [ "$CHAT_OK$EMBED_OK" = "11" ]; then
        mkdir -p "$(dirname "$FIRST_RUN_MARKER")"
        date -u +"%Y-%m-%dT%H:%M:%SZ" > "$FIRST_RUN_MARKER"
    fi
else
    ok "Starter models already initialized (delete $FIRST_RUN_MARKER to re-pull)"
fi

# ── 5. Status block ──────────────────────────────────────────────────
echo ""
echo "${BOLD}${GREEN}Enclave is running.${RESET}"
echo ""
echo "  ${BOLD}Open in your browser:${RESET}"
echo "      Enclave SPA    ${CYAN}${DASHBOARD_URL}${RESET}"
echo "      API docs       ${DIM}${DASHBOARD_URL}/docs${RESET}"
# Only mention :8081 if Open WebUI is actually running.
if "${DC[@]}" ps --services 2>/dev/null | grep -q '^webui$'; then
  echo "      Open WebUI     ${DIM}${WEBUI_URL}  (opt-in override)${RESET}"
fi
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
