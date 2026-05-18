#!/usr/bin/env bash
# Run the Playwright E2E suite against the live compose stack.
#
# Usage:
#   scripts/run-playwright.sh                # smoke suite (no @slow)
#   scripts/run-playwright.sh --slow         # include the workflow-execution test
#   scripts/run-playwright.sh --headed       # visible browser, debug-friendly
#   scripts/run-playwright.sh --headed --slow --slowmo=300
#
# Exit codes:
#   0  — suite passed
#   1  — one or more tests failed
#   2  — stack not reachable (didn't run any tests)

set -euo pipefail

BASE_URL="${ENCLAVE_PLAYWRIGHT_BASE_URL:-http://localhost:8000}"
REPORT_DIR="${ENCLAVE_PLAYWRIGHT_REPORT_DIR:-playwright-results}"

# ── Preflight: stack must be up ────────────────────────────────────────────
echo "▸ Checking ${BASE_URL}/health …"
if ! curl -sS -o /dev/null -m 3 "${BASE_URL}/health"; then
  echo "✗ Stack not reachable at ${BASE_URL}. Bring it up first:"
  echo "    docker compose up -d"
  exit 2
fi
echo "✓ Stack reachable."

# ── Preflight: browser binary present ──────────────────────────────────────
if ! python -c "import playwright" >/dev/null 2>&1; then
  echo "✗ Playwright Python not installed. Run:"
  echo "    pip install -r setup/requirements-playwright.txt"
  echo "    playwright install chromium"
  exit 2
fi

# ── Marker selection ───────────────────────────────────────────────────────
PYTEST_MARKER='not slow'
EXTRA_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --slow)   PYTEST_MARKER='' ;;
    --all)    PYTEST_MARKER='' ;;
    *)        EXTRA_ARGS+=("$arg") ;;
  esac
done

mkdir -p "${REPORT_DIR}"

# ── Run ────────────────────────────────────────────────────────────────────
CMD=(pytest tests/playwright -v --tracing=retain-on-failure --output="${REPORT_DIR}")
if [ -n "${PYTEST_MARKER}" ]; then
  CMD+=(-m "${PYTEST_MARKER}")
fi
CMD+=("${EXTRA_ARGS[@]}")

echo "▸ Running: ${CMD[*]}"
"${CMD[@]}"
rc=$?

echo
echo "▸ Report dir: ${REPORT_DIR}/"
exit ${rc}
