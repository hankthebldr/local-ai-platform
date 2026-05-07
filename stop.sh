#!/usr/bin/env bash
# Enclave — stop the Docker stack started by ./run.sh
#
# Usage:
#   ./stop.sh           # stop containers, keep models + chat history
#   ./stop.sh --reset   # also delete all volumes (models, chat history, logs)

set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

if docker compose version >/dev/null 2>&1; then
    DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    DC=(docker-compose)
else
    echo "Docker Compose not found — nothing to stop." >&2
    exit 0
fi

if [ "${1:-}" = "--reset" ]; then
    echo "Stopping Enclave and removing volumes (models, chat history, logs will be deleted)..."
    "${DC[@]}" down -v
    rm -f "$PROJECT_ROOT/data/.docker-first-run-complete"
    echo "Done. Next ./run.sh will be a clean first run."
else
    echo "Stopping Enclave..."
    "${DC[@]}" down
    echo "Done. Data preserved — ./run.sh restarts where you left off."
fi
