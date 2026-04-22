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
