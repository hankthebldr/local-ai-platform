#!/usr/bin/env bash
# Claude Code status line: branch ● venv ● ollama ● model ● cwd
# Input: JSON on stdin with .model.display_name
# Output: single ANSI-colored line to stdout

set -u

payload="$(cat)"
model="$(printf '%s' "$payload" | jq -r '.model.display_name // "?"')"

# Branch (yellow if dirty)
branch="$(git branch --show-current 2>/dev/null || echo -)"
if [[ "$branch" != "-" ]]; then
  if [[ -n "$(git status --porcelain 2>/dev/null | head -1)" ]]; then
    branch_seg="\033[33m$branch\033[0m"
  else
    branch_seg="\033[90m$branch\033[0m"
  fi
else
  branch_seg="\033[90m-\033[0m"
fi

# Venv (red if off)
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  venv_seg="\033[32mvenv:on\033[0m"
else
  venv_seg="\033[31mvenv:off\033[0m"
fi

# Ollama (green if up, red if down) — cached 30s to keep statusline fast
cache="/tmp/claude-statusline-ollama-${USER:-user}"
if [[ -f "$cache" ]] && [[ $(( $(date +%s) - $(stat -f %m "$cache" 2>/dev/null || stat -c %Y "$cache" 2>/dev/null || echo 0) )) -lt 30 ]]; then
  ollama_status="$(cat "$cache")"
else
  if curl -sf --max-time 1 http://localhost:11434/api/tags >/dev/null 2>&1; then
    ollama_status="up"
  else
    ollama_status="down"
  fi
  printf '%s' "$ollama_status" > "$cache" 2>/dev/null || true
fi
if [[ "$ollama_status" == "up" ]]; then
  ollama_seg="\033[32mollama:up\033[0m"
else
  ollama_seg="\033[31mollama:down\033[0m"
fi

# Model (dim)
model_seg="\033[90m$model\033[0m"

# Cwd basename (dim)
cwd_seg="\033[90m$(basename "$PWD")\033[0m"

printf '%b %b %b %b %b %b %b %b %b\n' \
  "$branch_seg" "\033[90m●\033[0m" \
  "$venv_seg" "\033[90m●\033[0m" \
  "$ollama_seg" "\033[90m●\033[0m" \
  "$model_seg" "\033[90m●\033[0m" \
  "$cwd_seg"
