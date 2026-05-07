#!/usr/bin/env bash
# Nudge when models/download.py MODEL_REGISTRY changed without MODELS.md update.
# Event: PostToolUse. Matcher: Edit|Write|MultiEdit.
# Non-blocking — emits a systemMessage advisory only.

set -u

payload="$(cat)"
file="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')"

# Normalize to relative path under repo root
case "$file" in
  *"/models/download.py") : ;;
  "models/download.py") : ;;
  *) exit 0 ;;
esac

# Check whether MODEL_REGISTRY was touched by the most recent diff on that file
if ! git diff HEAD -- models/download.py 2>/dev/null | grep -qE '^[+-].*MODEL_REGISTRY|^[+-].*"name":|^[+-].*"ollama":'; then
  exit 0
fi

# If MODELS.md has also been touched in this session, silent
if git diff --name-only HEAD 2>/dev/null | grep -q '^MODELS.md$'; then
  exit 0
fi
if git diff --name-only --cached 2>/dev/null | grep -q '^MODELS.md$'; then
  exit 0
fi

jq -n '{systemMessage: "MODEL_REGISTRY changed in models/download.py — remember to update MODELS.md (authoritative per CLAUDE.md)."}'
exit 0
