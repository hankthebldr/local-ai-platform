#!/usr/bin/env bash
# Idempotently create the labels the triage issue emitter applies.
# Run once per repo:  ./scripts/triage-labels.sh [owner/repo]
set -euo pipefail
REPO_ARG=()
[ "${1:-}" != "" ] && REPO_ARG=(--repo "$1")

create() { gh label create "$1" --color "$2" --description "$3" "${REPO_ARG[@]}" --force; }

create "triage:auto"       "ededed" "Auto-filed by the triage system"
create "severity:critical" "b60205" "Triage: critical"
create "severity:high"     "d93f0b" "Triage: high"
create "severity:medium"   "fbca04" "Triage: medium"
create "severity:low"      "0e8a16" "Triage: low"
for c in assertion import_error timeout connection flaky config unhandled unknown; do
  create "category:${c}"   "1d76db" "Triage category: ${c}"
done
echo "triage labels ensured"
