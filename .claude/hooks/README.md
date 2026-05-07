# `.claude/hooks/`

Shell scripts invoked by the Claude Code harness per `.claude/settings.json`. All
hooks read a JSON payload on stdin and signal outcomes via stdout/stderr + exit codes.

| Script | Event | Matcher | Purpose |
|---|---|---|---|
| `format-python.sh` | PostToolUse | `Edit\|Write\|MultiEdit` | Runs black + ruff on touched `.py` files |
| `scan-secrets.sh` | PreToolUse | `Bash` | Blocks `git commit` with secret patterns in staged diff |
| `claude-md-drift.sh` | Stop | — | Nudges when architectural files change without CLAUDE.md update |
| `models-md-sync.sh` | PostToolUse | `Edit\|Write\|MultiEdit` | Nudges when `MODEL_REGISTRY` changes without MODELS.md update |
| `statusline.sh` | (statusLine) | — | Renders `branch ● venv ● ollama ● model ● cwd` |

## Files

- `secret-allowlist.txt` — regex allowlist for known-safe matches (examples, test keys).
- `README.md` — this file.

## Testing

```bash
bash tests/hooks/test_claude_hooks.sh
```

Runs integration tests against each hook with synthetic stdin payloads. All hooks
must pass before modifying `.claude/settings.json`.

## Exit codes

- `0` — allow
- `1` — warn (stderr shown to Claude, non-blocking)
- `2` — block (stdout JSON `{decision: "block", reason: "..."}` shown to user)
