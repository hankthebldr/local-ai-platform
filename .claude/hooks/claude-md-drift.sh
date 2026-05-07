#!/usr/bin/env bash
# Nudge Claude when architectural files changed but CLAUDE.md didn't.
# Event: Stop. Non-blocking — emits a systemMessage advisory only.

set -u

# Architectural files whose changes usually warrant a CLAUDE.md update
watched=(
  "api/services/"
  "api/routers/"
  "workflows/"
  "models/download.py"
  "setup/requirements-core.txt"
)

changed="$(git diff --name-only HEAD 2>/dev/null || true)"
# Also include staged-but-not-committed changes
staged="$(git diff --name-only --cached 2>/dev/null || true)"
all_changed="$(printf '%s\n%s\n' "$changed" "$staged" | sort -u | grep -v '^$' || true)"

[[ -z "$all_changed" ]] && exit 0

touched_watched=""
claude_md_touched=0

while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  if [[ "$f" == "CLAUDE.md" ]]; then
    claude_md_touched=1
    continue
  fi
  for prefix in "${watched[@]}"; do
    case "$f" in
      "$prefix"*)
        touched_watched="${touched_watched}${f}\n"
        break
        ;;
    esac
  done
done <<< "$all_changed"

# If CLAUDE.md was touched in session, we're good
[[ "$claude_md_touched" -eq 1 ]] && exit 0
# If no watched files touched, nothing to nudge about
[[ -z "$touched_watched" ]] && exit 0

# Emit advisory
summary="$(printf '%b' "$touched_watched" | head -5 | tr '\n' ',' | sed 's/,$//')"
jq -n --arg files "$summary" \
  '{systemMessage: ("Heads up: touched architectural files without updating CLAUDE.md: \($files). If public patterns changed, update CLAUDE.md in the same session.")}'
exit 0
