#!/usr/bin/env bash
# Walk each Enclave surface and record WebM videos of the interactions.
# Output goes to playwright-results/videos/.
#
# Usage:
#   scripts/record-demos.sh                # record everything
#   scripts/record-demos.sh feature_name   # record one feature only
#
# Prereqs: stack up + Playwright installed (see tests/playwright/README.md).

set -euo pipefail

BASE_URL="${ENCLAVE_PLAYWRIGHT_BASE_URL:-http://localhost:8000}"
OUT_DIR="${ENCLAVE_PLAYWRIGHT_RECORD_DIR:-playwright-results/videos}"

if ! curl -sS -o /dev/null -m 3 "${BASE_URL}/health"; then
  echo "✗ Stack not reachable at ${BASE_URL}. Bring it up first:"
  echo "    source scripts/host-preset.sh && docker compose up -d"
  exit 2
fi

rm -rf "${OUT_DIR}" && mkdir -p "${OUT_DIR}"

filter="${1:-}"
PYTEST_ARGS=(
  tests/playwright/demos
  -v --no-header --tb=line
  -p no:cacheprovider
)
if [ -n "$filter" ]; then
  PYTEST_ARGS+=(-k "$filter")
fi

echo "▸ Recording demos to ${OUT_DIR}"
ENCLAVE_PLAYWRIGHT_RECORD=1 \
ENCLAVE_PLAYWRIGHT_RECORD_DIR="${OUT_DIR}" \
  pytest "${PYTEST_ARGS[@]}"

echo
echo "▸ Videos:"
find "${OUT_DIR}" -type f -name '*.webm' | while read -r v; do
  size="$(du -h "$v" | awk '{print $1}')"
  echo "  ${size}  ${v}"
done
