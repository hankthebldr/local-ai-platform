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
  echo "# repo" > README.md
  git add README.md
  git commit -q -m init
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

echo ""
echo "Total: $((PASS+FAIL)) | Pass: $PASS | Fail: $FAIL"
exit $FAIL
