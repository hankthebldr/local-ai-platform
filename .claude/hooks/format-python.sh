#!/usr/bin/env bash
# Auto-format Python files after Claude Code edits them.
# Event: PostToolUse. Matcher: Edit|Write|MultiEdit.
# Input: JSON on stdin with .tool_input.file_path.
# Behavior: if file is under api/|cli/|models/|finetuning/|tests/ and ends in .py,
#   run black then ruff check --fix. Silent on success.
#   On formatter error (e.g., syntax error), emit stderr + exit 1 so Claude sees it.

set -euo pipefail

payload="$(cat)"
file="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')"

# Skip if no file_path or not a .py file
[[ -z "$file" ]] && exit 0
[[ "$file" != *.py ]] && exit 0

# Only format files under project source dirs
case "$file" in
  */api/*|*/cli/*|*/models/*|*/finetuning/*|*/tests/*) ;;
  api/*|cli/*|models/*|finetuning/*|tests/*) ;;
  *) exit 0 ;;
esac

# Skip if file doesn't exist (e.g., was deleted)
[[ -f "$file" ]] || exit 0

# Prefer project venv if present
if [[ -x "venv/bin/black" ]]; then
  BLACK="venv/bin/black"
  RUFF="venv/bin/ruff"
else
  BLACK="$(command -v black || true)"
  RUFF="$(command -v ruff || true)"
fi

[[ -z "$BLACK" ]] && exit 0  # black not installed; silent no-op

if ! "$BLACK" --quiet "$file" 2>&1; then
  echo "format-python: black failed on $file" >&2
  exit 1
fi

if [[ -n "$RUFF" ]]; then
  "$RUFF" check --fix --quiet "$file" 2>&1 || true  # ruff non-fatal
fi

exit 0
