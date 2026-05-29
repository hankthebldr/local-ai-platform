# Claude Code Configuration Implementation Plan (Part B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure the Claude Code harness for this repo to prevent four recurring pain points (formatting drift, secret leaks, CLAUDE.md drift, MODELS.md sync), plus refresh CLAUDE.md, restructure permissions, add a workflow-engine expert subagent, and install a status line.

**Architecture:** All artifacts live under `.claude/`: hooks as shell scripts in `.claude/hooks/`, subagent definition in `.claude/agents/workflow-engine-expert.md`, hook registrations in a new team-shared `.claude/settings.json`, user-specific overrides in a pruned `.claude/settings.local.json` (gitignored). Hooks consume `$CLAUDE_TOOL_INPUT` JSON on stdin, return control via stdout/stderr + exit codes per Claude Code's hook contract.

**Tech Stack:** Bash, `jq`, `git`, `black`, `ruff`. No new runtime dependencies for the platform itself.

**Spec context:** Part B sections from `docs/superpowers/plans/2026-04-20-workflow-prompt-framework.md` (companion spec) and the brainstorming conversation that produced it.

---

## File Structure

### Created
- `.claude/settings.json` — team-shared harness config (checked in)
- `.claude/hooks/format-python.sh` — PostToolUse formatter
- `.claude/hooks/scan-secrets.sh` — PreToolUse git-commit gatekeeper
- `.claude/hooks/claude-md-drift.sh` — Stop-event doc-drift nudge
- `.claude/hooks/models-md-sync.sh` — PostToolUse MODELS.md reminder
- `.claude/hooks/statusline.sh` — status-line renderer
- `.claude/hooks/secret-allowlist.txt` — regex allowlist for known-safe secret matches
- `.claude/hooks/README.md` — documents each hook
- `.claude/agents/workflow-engine-expert.md` — pre-loaded subagent
- `tests/hooks/test_claude_hooks.sh` — bash integration tests for the four hooks

### Modified
- `CLAUDE.md` — trimmed from 300+ lines to ~150
- `.claude/settings.local.json` — pruned to host-specific entries only
- `.gitignore` — confirm `.claude/settings.local.json` is gitignored (may already be)

---

## Task 1: Create `.claude/settings.json` skeleton

**Files:**
- Create: `.claude/settings.json`

This task puts the baseline team-shared config in place. Hooks and statusLine get registered incrementally in later tasks.

- [ ] **Step 1.1: Create `.claude/settings.json` with minimal valid schema**

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": [
      "Bash(source venv/bin/activate)",
      "Bash(python -m pytest:*)",
      "Bash(python api/main.py:*)",
      "Bash(python cli/*.py:*)",
      "Bash(python models/download.py:*)",
      "Bash(python cli/workflow.py:*)",
      "Bash(black:*)",
      "Bash(ruff:*)",
      "Bash(mypy:*)",
      "Bash(ollama list)",
      "Bash(ollama --version)",
      "Bash(ollama run:*)",
      "Bash(curl http://localhost:*)",
      "Bash(curl -sf http://localhost:*)",
      "Bash(pip install -r setup/requirements-core.txt)",
      "Bash(pip install -r setup/requirements-dev.txt)",
      "Bash(git add:*)",
      "Bash(git commit:*)",
      "Bash(git diff:*)",
      "Bash(git status)",
      "Bash(git status --short)",
      "Bash(git log:*)",
      "Bash(git branch:*)",
      "Bash(git checkout:*)",
      "Bash(gh pr:*)",
      "Bash(gh api repos/*)",
      "Bash(gh run view:*)",
      "WebSearch"
    ],
    "deny": [
      "Bash(git push --force:*)",
      "Bash(git push -f:*)",
      "Bash(rm -rf /:*)",
      "Bash(rm -rf ~:*)",
      "Bash(chmod 777:*)",
      "Read(.env)",
      "Write(.env)",
      "Read(~/.ssh/**)",
      "Read(~/.aws/credentials)"
    ],
    "ask": []
  }
}
```

- [ ] **Step 1.2: Verify JSON is valid**

Run: `jq empty .claude/settings.json && echo "OK"`
Expected: `OK`

- [ ] **Step 1.3: Commit**

```bash
git add .claude/settings.json
git commit -m "feat(claude): add team-shared .claude/settings.json with baseline permissions"
```

---

## Task 2: Hook — `auto-format-python` (PostToolUse)

**Files:**
- Create: `.claude/hooks/format-python.sh`
- Create: `tests/hooks/test_claude_hooks.sh` (new bash test runner; extended in later tasks)
- Modify: `.claude/settings.json` (add hook registration)

- [ ] **Step 2.1: Write `.claude/hooks/format-python.sh`**

```bash
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
```

- [ ] **Step 2.2: Make executable and write a bash test**

Create `tests/hooks/test_claude_hooks.sh`:

```bash
#!/usr/bin/env bash
# Integration tests for .claude/hooks/* scripts.
# Usage: bash tests/hooks/test_claude_hooks.sh

set -u

PASS=0
FAIL=0

assert_exit() {
  local name="$1"; local expected="$2"; local actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "  PASS: $name"
    PASS=$((PASS+1))
  else
    echo "  FAIL: $name (expected exit $expected, got $actual)"
    FAIL=$((FAIL+1))
  fi
}

section() { echo ""; echo "== $1 =="; }

# ── format-python ──────────────────────────────────────────────────────────
section "format-python.sh"

tmp="$(mktemp -d)"
trap "rm -rf $tmp" EXIT

# Test 1: no-op on non-Python file
out="$tmp/README.md"
echo "test" > "$out"
printf '%s' "{\"tool_input\": {\"file_path\": \"$out\"}}" | bash .claude/hooks/format-python.sh
assert_exit "non-Python file no-op" 0 $?

# Test 2: no-op on Python file outside source dirs
out="$tmp/scratch.py"
echo "x=1" > "$out"
printf '%s' "{\"tool_input\": {\"file_path\": \"$out\"}}" | bash .claude/hooks/format-python.sh
assert_exit "Python file outside source dirs no-op" 0 $?

# Test 3: formats a messy Python file under api/
mkdir -p "$tmp/api"
out="$tmp/api/messy.py"
printf 'def foo( x,y  ):\n  return   x+y\n' > "$out"
pushd "$tmp" >/dev/null
printf '%s' "{\"tool_input\": {\"file_path\": \"api/messy.py\"}}" | bash "$OLDPWD/.claude/hooks/format-python.sh"
code=$?
popd >/dev/null
assert_exit "formats Python file under api/" 0 "$code"

# Test 4: empty input — no crash
echo "" | bash .claude/hooks/format-python.sh
assert_exit "empty input no-op" 0 $?

# Test 5: missing file — silent no-op
printf '%s' '{"tool_input": {"file_path": "does_not_exist.py"}}' | bash .claude/hooks/format-python.sh
assert_exit "missing file no-op" 0 $?

echo ""
echo "Total: $((PASS+FAIL)) | Pass: $PASS | Fail: $FAIL"
exit $FAIL
```

- [ ] **Step 2.3: Run tests and verify**

```bash
chmod +x .claude/hooks/format-python.sh tests/hooks/test_claude_hooks.sh
bash tests/hooks/test_claude_hooks.sh
```

Expected: 5/5 pass.

- [ ] **Step 2.4: Register the hook in `.claude/settings.json`**

Add a `hooks` key to `.claude/settings.json`:

```json
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/format-python.sh"
          }
        ]
      }
    ]
  },
```

Verify JSON is valid: `jq empty .claude/settings.json`

- [ ] **Step 2.5: Commit**

```bash
git add .claude/hooks/format-python.sh tests/hooks/test_claude_hooks.sh .claude/settings.json
git commit -m "feat(claude): add auto-format-python PostToolUse hook"
```

---

## Task 3: Hook — `pre-commit-secret-scan` (PreToolUse)

**Files:**
- Create: `.claude/hooks/scan-secrets.sh`
- Create: `.claude/hooks/secret-allowlist.txt`
- Modify: `tests/hooks/test_claude_hooks.sh` (add secret scan tests)
- Modify: `.claude/settings.json` (add PreToolUse hook)

- [ ] **Step 3.1: Create `.claude/hooks/secret-allowlist.txt`**

```
# Regex patterns (one per line) that should NOT trigger the secret scanner.
# Lines starting with # are comments.
# Examples:
# ^AKIAEXAMPLE1234567890$           # known-safe AWS test key
# sk-test_[A-Za-z0-9]+              # Stripe test keys
```

(Ship it with only comments; users add their own.)

- [ ] **Step 3.2: Write `.claude/hooks/scan-secrets.sh`**

```bash
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
  hit="$(printf '%s' "$diff" | grep -nE "$pat" || true)"
  [[ -z "$hit" ]] && continue
  # Check against allowlist
  if [[ -n "$allowlist" ]]; then
    while IFS= read -r allow; do
      [[ -z "$allow" ]] && continue
      hit="$(printf '%s' "$hit" | grep -vE "$allow" || true)"
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
```

- [ ] **Step 3.3: Add bash tests for `scan-secrets.sh`**

Append to `tests/hooks/test_claude_hooks.sh` before the final `echo "Total..."` line:

```bash
# ── scan-secrets ──────────────────────────────────────────────────────────
section "scan-secrets.sh"

tmp_repo="$(mktemp -d)"
(
  cd "$tmp_repo"
  git init -q
  git config user.email t@t.test
  git config user.name Test
  mkdir -p .claude/hooks
  cp "$OLDPWD/.claude/hooks/scan-secrets.sh" .claude/hooks/
  cp "$OLDPWD/.claude/hooks/secret-allowlist.txt" .claude/hooks/
)

# Test 1: non-commit command is a no-op
printf '%s' '{"tool_input": {"command": "ls -la"}}' | bash .claude/hooks/scan-secrets.sh
assert_exit "non-commit command no-op" 0 $?

# Test 2: commit with no staged changes is a no-op
pushd "$tmp_repo" >/dev/null
printf '%s' '{"tool_input": {"command": "git commit -m x"}}' | bash .claude/hooks/scan-secrets.sh >/dev/null
code=$?
popd >/dev/null
assert_exit "empty staged diff no-op" 0 "$code"

# Test 3: commit with clean staged changes passes
pushd "$tmp_repo" >/dev/null
echo "hello world" > benign.txt
git add benign.txt
printf '%s' '{"tool_input": {"command": "git commit -m x"}}' | bash .claude/hooks/scan-secrets.sh >/dev/null
code=$?
git reset -q HEAD
popd >/dev/null
assert_exit "benign staged diff passes" 0 "$code"

# Test 4: staging a GitHub token gets blocked
pushd "$tmp_repo" >/dev/null
echo "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1234567890" > leaked.txt
git add leaked.txt
printf '%s' '{"tool_input": {"command": "git commit -m x"}}' | bash .claude/hooks/scan-secrets.sh >/dev/null 2>&1
code=$?
git reset -q HEAD
rm -f leaked.txt
popd >/dev/null
assert_exit "GitHub token blocked" 2 "$code"

# Test 5: staging a .env file gets blocked
pushd "$tmp_repo" >/dev/null
echo "MY_VAR=abc" > .env
git add .env
printf '%s' '{"tool_input": {"command": "git commit -m x"}}' | bash .claude/hooks/scan-secrets.sh >/dev/null 2>&1
code=$?
git rm -f --cached .env >/dev/null 2>&1
rm -f .env
popd >/dev/null
assert_exit ".env file blocked" 2 "$code"

# Test 6: staging .env.example is fine
pushd "$tmp_repo" >/dev/null
echo "MY_VAR=example" > .env.example
git add .env.example
printf '%s' '{"tool_input": {"command": "git commit -m x"}}' | bash .claude/hooks/scan-secrets.sh >/dev/null
code=$?
git reset -q HEAD
rm -f .env.example
popd >/dev/null
assert_exit ".env.example allowed" 0 "$code"

rm -rf "$tmp_repo"
```

- [ ] **Step 3.4: Run tests**

```bash
chmod +x .claude/hooks/scan-secrets.sh
bash tests/hooks/test_claude_hooks.sh
```

Expected: 11/11 pass (5 format-python + 6 scan-secrets).

- [ ] **Step 3.5: Register in `.claude/settings.json`**

Add a `PreToolUse` entry to the `hooks` block:

```json
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/scan-secrets.sh"
          }
        ]
      }
    ],
```

(Place it alongside the existing `PostToolUse` entry inside `hooks`.)

Verify: `jq empty .claude/settings.json`

- [ ] **Step 3.6: Commit**

```bash
git add .claude/hooks/scan-secrets.sh .claude/hooks/secret-allowlist.txt tests/hooks/test_claude_hooks.sh .claude/settings.json
git commit -m "feat(claude): add pre-commit secret scanner (blocks AWS/GitHub/Anthropic keys + .env)"
```

---

## Task 4: Hook — `claude-md-drift-nudge` (Stop)

**Files:**
- Create: `.claude/hooks/claude-md-drift.sh`
- Modify: `tests/hooks/test_claude_hooks.sh` (add drift tests)
- Modify: `.claude/settings.json` (register Stop hook)

- [ ] **Step 4.1: Write `.claude/hooks/claude-md-drift.sh`**

```bash
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
```

- [ ] **Step 4.2: Add bash tests for drift hook**

Append to `tests/hooks/test_claude_hooks.sh`:

```bash
# ── claude-md-drift ───────────────────────────────────────────────────────
section "claude-md-drift.sh"

tmp_repo="$(mktemp -d)"
(
  cd "$tmp_repo"
  git init -q
  git config user.email t@t.test
  git config user.name Test
  mkdir -p .claude/hooks api/services
  cp "$OLDPWD/.claude/hooks/claude-md-drift.sh" .claude/hooks/
  echo "# CLAUDE.md" > CLAUDE.md
  echo "print('ok')" > api/services/foo.py
  git add -A && git commit -q -m init
)

# Test 1: no changes → silent no-op
pushd "$tmp_repo" >/dev/null
out="$(bash .claude/hooks/claude-md-drift.sh 2>/dev/null || true)"
popd >/dev/null
if [[ -z "$out" ]]; then echo "  PASS: no changes silent"; PASS=$((PASS+1)); else echo "  FAIL: no changes emitted '$out'"; FAIL=$((FAIL+1)); fi

# Test 2: edited api/services without CLAUDE.md → nudges
pushd "$tmp_repo" >/dev/null
echo "print('changed')" >> api/services/foo.py
out="$(bash .claude/hooks/claude-md-drift.sh 2>/dev/null || true)"
popd >/dev/null
if [[ "$out" == *"systemMessage"* ]] && [[ "$out" == *"api/services/foo.py"* ]]; then
  echo "  PASS: nudges on service edit"; PASS=$((PASS+1))
else
  echo "  FAIL: no nudge; got '$out'"; FAIL=$((FAIL+1))
fi

# Test 3: edited api/services AND CLAUDE.md → silent (doc was updated)
pushd "$tmp_repo" >/dev/null
echo "new section" >> CLAUDE.md
out="$(bash .claude/hooks/claude-md-drift.sh 2>/dev/null || true)"
popd >/dev/null
if [[ -z "$out" ]]; then echo "  PASS: silent when CLAUDE.md also touched"; PASS=$((PASS+1)); else echo "  FAIL: emitted '$out'"; FAIL=$((FAIL+1)); fi

rm -rf "$tmp_repo"
```

- [ ] **Step 4.3: Run tests**

```bash
chmod +x .claude/hooks/claude-md-drift.sh
bash tests/hooks/test_claude_hooks.sh
```

Expected: 14/14 pass.

- [ ] **Step 4.4: Register in `.claude/settings.json`**

Add inside `hooks`:

```json
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/claude-md-drift.sh"
          }
        ]
      }
    ],
```

- [ ] **Step 4.5: Commit**

```bash
git add .claude/hooks/claude-md-drift.sh tests/hooks/test_claude_hooks.sh .claude/settings.json
git commit -m "feat(claude): add CLAUDE.md drift nudge on Stop event"
```

---

## Task 5: Hook — `models-md-sync-nudge` (PostToolUse)

**Files:**
- Create: `.claude/hooks/models-md-sync.sh`
- Modify: `tests/hooks/test_claude_hooks.sh`
- Modify: `.claude/settings.json`

- [ ] **Step 5.1: Write `.claude/hooks/models-md-sync.sh`**

```bash
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
```

- [ ] **Step 5.2: Add bash tests**

Append to `tests/hooks/test_claude_hooks.sh`:

```bash
# ── models-md-sync ────────────────────────────────────────────────────────
section "models-md-sync.sh"

tmp_repo="$(mktemp -d)"
(
  cd "$tmp_repo"
  git init -q
  git config user.email t@t.test
  git config user.name Test
  mkdir -p .claude/hooks models
  cp "$OLDPWD/.claude/hooks/models-md-sync.sh" .claude/hooks/
  echo "MODEL_REGISTRY = {'a': {'name': 'A', 'ollama': 'a'}}" > models/download.py
  echo "# MODELS.md" > MODELS.md
  git add -A && git commit -q -m init
)

# Test 1: edit unrelated file → silent
pushd "$tmp_repo" >/dev/null
printf '%s' '{"tool_input": {"file_path": "README.md"}}' | bash .claude/hooks/models-md-sync.sh >/dev/null
code=$?
popd >/dev/null
assert_exit "unrelated file no-op" 0 "$code"

# Test 2: edit models/download.py without touching MODELS.md → nudge
pushd "$tmp_repo" >/dev/null
echo "MODEL_REGISTRY['b'] = {'name': 'B', 'ollama': 'b'}" >> models/download.py
out="$(printf '%s' '{"tool_input": {"file_path": "models/download.py"}}' | bash .claude/hooks/models-md-sync.sh 2>/dev/null)"
popd >/dev/null
if [[ "$out" == *"systemMessage"* ]] && [[ "$out" == *"MODELS.md"* ]]; then
  echo "  PASS: nudges on registry edit"; PASS=$((PASS+1))
else
  echo "  FAIL: no nudge; got '$out'"; FAIL=$((FAIL+1))
fi

# Test 3: edit both download.py and MODELS.md → silent
pushd "$tmp_repo" >/dev/null
echo "extra" >> MODELS.md
out="$(printf '%s' '{"tool_input": {"file_path": "models/download.py"}}' | bash .claude/hooks/models-md-sync.sh 2>/dev/null)"
popd >/dev/null
if [[ -z "$out" ]]; then echo "  PASS: silent when MODELS.md also touched"; PASS=$((PASS+1)); else echo "  FAIL: emitted '$out'"; FAIL=$((FAIL+1)); fi

rm -rf "$tmp_repo"
```

- [ ] **Step 5.3: Run tests — 17/17 pass**

```bash
chmod +x .claude/hooks/models-md-sync.sh
bash tests/hooks/test_claude_hooks.sh
```

- [ ] **Step 5.4: Register in `.claude/settings.json`** — add this script to the existing `PostToolUse` entry so both it and format-python run on Edit|Write|MultiEdit:

```json
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/format-python.sh" },
          { "type": "command", "command": ".claude/hooks/models-md-sync.sh" }
        ]
      }
    ],
```

- [ ] **Step 5.5: Commit**

```bash
git add .claude/hooks/models-md-sync.sh tests/hooks/test_claude_hooks.sh .claude/settings.json
git commit -m "feat(claude): add MODELS.md sync nudge when MODEL_REGISTRY changes"
```

---

## Task 6: Status Line

**Files:**
- Create: `.claude/hooks/statusline.sh`
- Modify: `.claude/settings.json`

- [ ] **Step 6.1: Write `.claude/hooks/statusline.sh`**

```bash
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
```

- [ ] **Step 6.2: Make executable + smoke test**

```bash
chmod +x .claude/hooks/statusline.sh
printf '{"model": {"display_name": "claude-opus-4-7"}}' | bash .claude/hooks/statusline.sh
```

Expected: a single colored status line with branch, venv, ollama, model, cwd segments.

- [ ] **Step 6.3: Register in `.claude/settings.json`**

Add a top-level key:

```json
  "statusLine": {
    "type": "command",
    "command": ".claude/hooks/statusline.sh"
  }
```

- [ ] **Step 6.4: Commit**

```bash
git add .claude/hooks/statusline.sh .claude/settings.json
git commit -m "feat(claude): add status line with branch/venv/ollama/model/cwd"
```

---

## Task 7: Subagent — `workflow-engine-expert`

**Files:**
- Create: `.claude/agents/workflow-engine-expert.md`

- [ ] **Step 7.1: Create `.claude/agents/workflow-engine-expert.md`**

```markdown
---
name: workflow-engine-expert
description: |
  Use PROACTIVELY when the user asks to modify api/services/workflow_engine.py,
  api/services/step_executor.py, api/services/prompt_composer.py,
  api/services/model_adapters.py, api/services/hook_bus.py, api/hooks/**,
  api/models/workflow_models.py, workflows/*.yaml, or when designing a new
  workflow, adding a built-in hook, adding a model-family adapter, or debugging
  workflow step execution. This agent has the full workflow engine design and
  v2 YAML schema pre-loaded.
tools: Read, Edit, Write, Glob, Grep, Bash
model: inherit
---

You are the Enclave workflow-engine expert. You know the framework's architecture,
contracts, and invariants cold. Your job is to make correct, minimal, idiomatic
changes to the workflow engine without breaking v1 compatibility.

## Architecture at a glance

The pipeline in `step_executor.py`:

```
resolve inputs → compose prompt → adapt for family → [before_step hooks]
 → [transform_prompt hooks] → model call → [after_step hooks]
 → [validate_output hooks] → success → write outputs
                           → failure → [on_failure hooks] → retry or fail
```

Key modules:
- `api/services/hook_bus.py` — `HookContext`, `HookResult`, `HookBus`, `@register_hook`
- `api/services/prompt_composer.py` — `ComposedPrompt`, `PromptComposer` (5-part Jinja)
- `api/services/model_adapters.py` — `ModelAdapter`, `resolve_adapter`, 6 family adapters
- `api/services/step_executor.py` — orchestrates the lifecycle
- `api/services/workflow_engine.py` — builds per-step `HookBus`, wires `model_resolver`
- `api/hooks/builtins/*.py` — six default hooks
- `api/hooks/custom/*.py` — user drop-ins, auto-discovered
- `api/models/workflow_models.py` — v1 `system_prompt` and v2 `StepPrompt` both supported
- `prompts/roles/*.md` + `prompts/templates/five_part.jinja` — composer inputs

## Hard rules

1. **Never break v1 legacy workflows.** `AgentStep` accepts either `system_prompt` (v1) or `prompt` (v2). Any executor change must continue to handle v1.
2. **New workflows declare `schema_version: 2`.** Older workflows without the field default to v1.
3. **Adapters are family-level, not per-model.** Add a new adapter only if an existing model family isn't covered.
4. **Hooks are declarative in YAML when possible.** Built-ins live in `api/hooks/builtins/`; project-specific custom hooks go in `api/hooks/custom/` and auto-discover.
5. **Output schemas validate structure only.** Enclave's uncensored-model stance means content filtering is never added.
6. **Model escalation is real.** `RetryWithFeedbackHook(escalate_to=<role>)` triggers an actual model swap via `model_resolver.resolve(role=<role>)` when the resolver is available.

## The 6 lifecycle stages (in order)

1. `before_workflow` — once per workflow run, not per step
2. `before_step` — fires before every step's model call (good for token budgeting)
3. `transform_prompt` — last chance to mutate `ctx.prompt` (e.g. few-shot injection)
4. `after_step` — fires after the model call regardless of validation outcome (good for logging)
5. `validate_output` — gate: all must return `continue` for success. First rejection routes to `on_failure`.
6. `on_failure` — decides `retry` (optionally with feedback) or `fail`. Respects `max_attempts`.

## YAML schema v2 quick reference

```yaml
id: my-workflow
schema_version: 2
context:
  project: "..."
schemas:
  my_schema: { type: object, required: [...], properties: {...} }
steps:
  - id: step1
    role: reasoning             # or explicit model: "mistral:latest"
    prompt:
      role_ref: senior_data_architect    # or role_inline: "You are..."
      task: "Do the thing"
      constraints: ["JSON only"]
    inputs: [seed.files]
    outputs: [result]
    output_schema: { $ref: "#/schemas/my_schema" }
    hooks:
      validate_output:
        - json_schema: {}
        - refusal_detector: { use_family_defaults: true }
      on_failure:
        - retry_with_feedback: { max_attempts: 2, escalate_to: reasoning }
```

## Built-in hook catalog

| Hook | Stage | Purpose |
|---|---|---|
| `json_schema` | validate_output | Parse + validate against `output_schema`; sets `ctx.parsed` |
| `refusal_detector` | validate_output | Flag model refusals so retry can reframe |
| `token_budget` | before_step | Truncate Context section (never Task or Constraints) |
| `output_logger` | after_step | JSONL append to `data/logs/workflow_runs.jsonl` |
| `few_shot_injector` | transform_prompt | Inject examples from `prompts/examples/<step_id>/*.json` |
| `retry_with_feedback` | on_failure | Retry with validation feedback + optional model escalation |

## Reference docs

- Implementation plan: `docs/superpowers/plans/2026-04-20-workflow-prompt-framework.md`
- Original engine design: `docs/plans/2026-04-06-multi-agent-workflow-engine-design.md`

## Your operating mode

- Read the relevant files before editing. The framework is small but interconnected; skimming loses nuance.
- Follow TDD: for non-trivial changes, write the failing test first in `tests/unit/` (unit) or `tests/hooks/` (built-in hooks) or `tests/integration/` (pipeline).
- Keep commits small and scoped. One feature or bugfix per commit.
- When unsure whether a change should be a built-in hook vs custom hook, default to custom — built-ins need broad applicability.
```

- [ ] **Step 7.2: Commit**

```bash
git add .claude/agents/workflow-engine-expert.md
git commit -m "feat(claude): add workflow-engine-expert subagent with pre-loaded framework context"
```

---

## Task 8: CLAUDE.md Refresh

**Files:**
- Modify: `CLAUDE.md` (trim from 300+ to ~150 lines)

- [ ] **Step 8.1: Read current `CLAUDE.md` and back up mentally** — don't delete outright. Identify what maps to the new structure.

- [ ] **Step 8.2: Replace `CLAUDE.md` with the refreshed version**

```markdown
# CLAUDE.md

Guidance for Claude Code working on this repo.

## Project

Enclave — self-hosted local LLM platform, CPU-first, privacy-first. Fleet:
Mac M4 Pro 48GB (dev) · MS-01 64GB (API) · BD790i 96GB (flagship).
Authoritative model catalog: [MODELS.md](./MODELS.md).

## Core workflow

1. **Always activate venv first:** `source venv/bin/activate`
2. Edit code → auto-formatter runs (via hook) → commit.
3. Run API: `python api/main.py` (port 8000). Ollama: `ollama serve` (11434).
4. Run tests: `pytest tests/ --ignore=tests/e2e -v`

## Architecture boundaries

```
FastAPI (api/main.py, routers/, services/) → Ollama (or vLLM/llama.cpp later)
```

Key files by responsibility:
- `api/routers/` — HTTP surface, one file per concern (chat, completions, workflows, …)
- `api/services/` — business logic (ollama, workflow engine, prompt composer, model adapters)
- `api/services/step_executor.py` + `workflow_engine.py` — **multi-agent workflow engine** (see workflow-engine-expert subagent)
- `api/hooks/builtins/` — declarative workflow hooks (json_schema, retry, etc.)
- `api/hooks/custom/` — project-specific hooks, auto-discovered
- `models/download.py` — `MODEL_REGISTRY` (must stay in sync with MODELS.md)
- `cli/` — Rich-based CLI tools (chat, workflow, benchmark)
- `workflows/*.yaml` — declarative multi-agent workflow definitions

## Don't touch without care

- `api/main.py` — production API surface, CORS/middleware lives here
- `api/services/workflow_engine.py`, `step_executor.py` — core engine (use workflow-engine-expert agent)
- `Dockerfile`, `docker-compose.yml` — deployment
- `.env` — **never commit** (secret scan hook blocks it)
- `MODELS.md` — authoritative model doc; update whenever `MODEL_REGISTRY` changes

## Common tasks

- **Add a model:** edit `MODEL_REGISTRY` in `models/download.py` → update `MODELS.md` (sync hook will remind you).
- **Add a workflow:** `workflows/<name>.yaml` using `schema_version: 2`. See spec in `docs/superpowers/plans/2026-04-20-workflow-prompt-framework.md`.
- **Add a built-in hook:** new file in `api/hooks/builtins/<name>.py`. Declare `name`, `stage`, `__call__(ctx) -> HookResult`. Test in `tests/hooks/`.
- **Add a project-specific hook:** drop a `.py` in `api/hooks/custom/` using `@register_hook`. Auto-discovered.
- **Add a model-family adapter:** extend `api/services/model_adapters.py` and register a substring pattern.

## Release track

Current: **0.1.x** — Foundation. Workflow prompt framework shipped in PR #11.

Roadmap:
- `0.2.x` — streaming, vLLM/llama.cpp backends, Web UI
- `0.3.x` — fine-tuning (Axolotl/Unsloth)
- `0.4.x` — full RAG integration (langchain + chroma already partially in place)
- `1.0.0` — auth, ≥70% test coverage, Docker/K8s, Prometheus, structured logging

See [historical PROJECT_PLAN.md](../../historical/PROJECT_PLAN.md) for detail (pre-1.0 plan; the current track lives in `CHANGELOG.md` and `CLAUDE.md`).

## Pointers

- Enterprise-readiness gaps: [ENTERPRISE_DEPLOYMENT_GAPS.md](./ENTERPRISE_DEPLOYMENT_GAPS.md)
- Workflow engine design: `docs/plans/2026-04-06-multi-agent-workflow-engine-design.md`
- Prompt framework plan: `docs/superpowers/plans/2026-04-20-workflow-prompt-framework.md`
- Claude Code config plan (this file's supporting hooks): `docs/superpowers/plans/2026-04-22-claude-code-config.md`
- Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md

## Conventions

- **Quantization:** Q4_K_M default, Q5_K_M for quality, Q3_K_M for 70B+.
- **Performance targets:** 7B≈40-50 t/s, 13B≈25-30 t/s, 34B≈10-15 t/s, 70B≈3-5 t/s on the fleet.
- **Uncensored-first:** dolphin-mixtral, dolphin-mistral, nous-hermes2-mixtral, yi-34b, wizardlm-uncensored, mythomax.
- **OpenAI-compatible API surface:** clients can switch between Ollama/vLLM/llama.cpp backends transparently.
- **No telemetry. No cloud. All data local.**
```

- [ ] **Step 8.3: Verify it's reasonable length**

```bash
wc -l CLAUDE.md
```

Expected: ≤ 160 lines.

- [ ] **Step 8.4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): trim CLAUDE.md from 300+ to ~150 lines; sharpen architecture pointers"
```

---

## Task 9: Permissions Restructure

**Files:**
- Modify: `.claude/settings.local.json` (prune)
- Modify: `.gitignore` (ensure `settings.local.json` is ignored)

`.claude/settings.json` was created in Task 1 as the team-shared baseline. Now prune the pre-existing `.claude/settings.local.json` to only host-specific entries.

- [ ] **Step 9.1: Inspect current `.claude/settings.local.json`**

```bash
cat .claude/settings.local.json
```

You'll see 60+ allow entries including Linux paths (`/home/henry/...`), broken `for ... do test -f` fragments from prior sessions, duplicates. This file is user-specific and should contain only host-specific permissions.

- [ ] **Step 9.2: Replace `.claude/settings.local.json` with a pruned version**

```json
{
  "permissions": {
    "allow": [
      "Bash(/Users/henry/.claude/plugins/cache/superpowers/**)",
      "Bash(bash /Users/henry/.claude/plugins/cache/superpowers/**)",
      "Bash(/Users/henry/Github/Github_desktop/local-ai-platform/.claude/hooks/*)"
    ],
    "deny": [],
    "ask": []
  }
}
```

(Adjust the first two entries if your machine's path to Claude Code plugins differs.)

- [ ] **Step 9.3: Ensure `.gitignore` excludes `settings.local.json`**

Check:
```bash
grep "settings.local.json" .gitignore
```

If missing, add:
```bash
echo "# Claude Code user-specific overrides" >> .gitignore
echo ".claude/settings.local.json" >> .gitignore
```

- [ ] **Step 9.4: Commit**

```bash
git add .gitignore .claude/settings.local.json
git commit -m "chore(claude): prune settings.local.json to host-specific entries; gitignore user overrides"
```

If `.claude/settings.local.json` was already tracked and now needs to be untracked:
```bash
git rm --cached .claude/settings.local.json
git commit -m "chore(claude): stop tracking settings.local.json (moved to .gitignore)"
```

---

## Task 10: Documentation + Final Verification

**Files:**
- Create: `.claude/hooks/README.md`

- [ ] **Step 10.1: Write `.claude/hooks/README.md`**

```markdown
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
```

- [ ] **Step 10.2: Re-run all hook tests**

```bash
bash tests/hooks/test_claude_hooks.sh
```

Expected: 17/17 pass.

- [ ] **Step 10.3: Validate `.claude/settings.json` once more**

```bash
jq empty .claude/settings.json && echo "settings.json: OK"
jq empty .claude/settings.local.json && echo "settings.local.json: OK"
```

- [ ] **Step 10.4: Sanity check — trigger each hook manually**

```bash
# format-python
printf '{"tool_input": {"file_path": "api/services/step_executor.py"}}' | bash .claude/hooks/format-python.sh && echo "format-python: OK"

# scan-secrets (should pass since no git commit command)
printf '{"tool_input": {"command": "ls"}}' | bash .claude/hooks/scan-secrets.sh && echo "scan-secrets (no-op): OK"

# claude-md-drift (silent if CLAUDE.md is up to date with other changes)
bash .claude/hooks/claude-md-drift.sh && echo "claude-md-drift: ran"

# models-md-sync
printf '{"tool_input": {"file_path": "README.md"}}' | bash .claude/hooks/models-md-sync.sh && echo "models-md-sync (no-op): OK"

# statusline
printf '{"model": {"display_name": "claude-opus-4-7"}}' | bash .claude/hooks/statusline.sh
```

- [ ] **Step 10.5: Commit**

```bash
git add .claude/hooks/README.md
git commit -m "docs(claude): document hook library and testing in .claude/hooks/README.md"
```

---

## Self-Review Against Spec

- [x] **B.1 Goals — four hook pain points:** Tasks 2-5 ship all four hooks.
- [x] **B.2 Hooks:** auto-format-python (Task 2), scan-secrets (Task 3), claude-md-drift (Task 4), models-md-sync (Task 5). All wired in `.claude/settings.json`.
- [x] **B.3 Subagent `workflow-engine-expert`:** Task 7 with file-glob-anchored description.
- [x] **B.4 Status Line:** Task 6 with 30s cached Ollama check.
- [x] **B.5 CLAUDE.md refresh:** Task 8, trimmed to ≤160 lines.
- [x] **B.6 Permissions restructure:** Task 1 (team `.claude/settings.json`) + Task 9 (pruned user `.claude/settings.local.json`).

**Placeholder scan:** No "TBD", "TODO", "fill in details", or unspecified test bodies. Each shell test lists exact assertions and expected exit codes.

**Type consistency:** All four hooks read the same `$payload` stdin JSON shape. All four return 0 for pass and either 1 (warn) or 2 (block) per Claude Code's hook contract.

**Scope check:** This is a single coherent plan (one config-and-automation domain). No decomposition needed.

**Testing strategy:** Bash-based integration tests in `tests/hooks/test_claude_hooks.sh` covering each hook with synthetic stdin payloads (5 + 6 + 3 + 3 = 17 tests). No new runtime dependencies for the platform itself.
