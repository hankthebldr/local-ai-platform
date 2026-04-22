#!/usr/bin/env bash
# Scan staged git diff for secrets before `git commit`.
# Event: PreToolUse. Matcher: Bash.
# Input: JSON on stdin with .tool_input.command.
# Behavior: if command starts with `git commit`, scan `git diff --cached` for
#   common secret patterns. Block (exit 2 + JSON) on hit, allow otherwise.
#
# Allowlist: .claude/hooks/secret-allowlist.txt (regex per line; blank / # lines ignored)

set -u

payload="$(cat)"
cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty')"

# Only gate real `git commit` invocations
case "$cmd" in
  "git commit"|"git commit "*|"/usr/bin/git commit"*|"git "*" commit"*) : ;;
  *) exit 0 ;;
esac

# No staged changes — nothing to scan (git commit will fail anyway, let it)
if ! git diff --cached --quiet 2>/dev/null; then
  : # has staged changes — proceed
else
  exit 0
fi

diff="$(git diff --cached 2>/dev/null || true)"
staged_files="$(git diff --cached --name-only 2>/dev/null || true)"

# Reject staging .env (but allow .env.example / .env.sample etc.)
while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  case "$(basename "$f")" in
    .env) MATCH_KIND="staged .env file"; MATCH_DETAIL="$f"; break ;;
  esac
done <<< "$staged_files"

# If we already matched on .env, emit and block
if [[ -n "${MATCH_KIND:-}" ]]; then
  jq -n --arg kind "$MATCH_KIND" --arg detail "$MATCH_DETAIL" \
    '{decision: "block", reason: ("Secret scan blocked commit: \($kind): \($detail). Run `git restore --staged \($detail)` or add an exception to .claude/hooks/secret-allowlist.txt.")}'
  exit 2
fi

# Build allowlist regex (union of non-blank non-# lines)
allowlist="$(grep -v '^\s*#' .claude/hooks/secret-allowlist.txt 2>/dev/null | grep -v '^\s*$' || true)"

# Pattern library
declare -a PATTERNS=(
  'AKIA[0-9A-Z]{16}'
  'aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}'
  'gh[pousr]_[0-9A-Za-z]{36}'
  'sk-ant-[A-Za-z0-9_-]{95}'
  'sk-[A-Za-z0-9]{48}'
  '-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----'
  '(api[_-]?key|secret|password|token)\s*[:=]\s*["'\'']([^"'\'']{16,})["'\'']'
)

for pat in "${PATTERNS[@]}"; do
  hit="$(printf '%s' "$diff" | grep -nE -e "$pat" || true)"
  [[ -z "$hit" ]] && continue
  # Check against allowlist
  if [[ -n "$allowlist" ]]; then
    while IFS= read -r allow; do
      [[ -z "$allow" ]] && continue
      hit="$(printf '%s' "$hit" | grep -vE -e "$allow" || true)"
    done <<< "$allowlist"
  fi
  [[ -z "$hit" ]] && continue
  # We have a real hit — block
  first_line="$(printf '%s' "$hit" | head -1 | cut -c1-200)"
  jq -n --arg pat "$pat" --arg line "$first_line" \
    '{decision: "block", reason: ("Secret scan blocked commit: pattern /\($pat)/ matched.\nLine: \($line)\nUnstage the file, or add an exception regex to .claude/hooks/secret-allowlist.txt.")}'
  exit 2
done

exit 0
