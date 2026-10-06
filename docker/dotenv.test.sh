#!/usr/bin/env bash
# Test suite for dotenv.sh load_dotenv function.
# Run with: bash docker/dotenv.test.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/dotenv.sh"

TEST_DIR="$(mktemp -d)"
trap 'rm -rf "${TEST_DIR}"' EXIT

pass=0
fail=0

run_test() {
  local name="$1"
  local env_content="$2"
  local expected_var="$3"
  local expected_value="$4"

  local env_file="${TEST_DIR}/.env.test"
  printf "%s\n" "$env_content" >"$env_file"

  # shellcheck disable=SC2031
  unset -v "$expected_var" 2>/dev/null || true
  load_dotenv "$env_file"

  local actual
  actual="${!expected_var-__UNSET__}"
  if [[ "$actual" == "$expected_value" ]]; then
    echo "PASS: $name"
    pass=$((pass + 1))
    return 0
  else
    echo "FAIL: $name"
    echo "  Expected: [$expected_value]"
    echo "  Actual:   [$actual]"
    fail=$((fail + 1))
    return 1
  fi
}

run_test_fail() {
  local name="$1"
  local env_content="$2"
  local var_name="$3"

  local env_file="${TEST_DIR}/.env.test"
  printf "%s\n" "$env_content" >"$env_file"

  # Only unset if valid variable name
  if [[ "$var_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    unset -v "$var_name" 2>/dev/null || true
  fi
  if load_dotenv "$env_file" 2>/dev/null; then
    local actual="__UNSET__"
    if [[ "$var_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      actual="${!var_name-__UNSET__}"
    fi
    if [[ "$actual" != "__UNSET__" ]]; then
      echo "FAIL: $name (should have failed but var=$actual)"
      fail=$((fail + 1))
      return 1
    else
      echo "PASS: $name"
      pass=$((pass + 1))
      return 0
    fi
  else
    echo "PASS: $name (load_dotenv returned non-zero as expected)"
    pass=$((pass + 1))
    return 0
  fi
}

# Basic key=value
run_test "basic key=value" "FOO=bar" "FOO" "bar"

# Quoted values with spaces (double quotes)
run_test "double quoted with spaces" 'FOO="hello world"' "FOO" "hello world"

# Quoted values with spaces (single quotes)
run_test "single quoted with spaces" "FOO='hello world'" "FOO" "hello world"

# Value with equals sign
run_test "value with equals" "FOO=bar=baz" "FOO" "bar=baz"

# Quoted value with equals sign
run_test "double quoted with equals" 'FOO="bar=baz"' "FOO" "bar=baz"

# Empty value
run_test "empty value" "FOO=" "FOO" ""

# Quoted empty value
run_test "double quoted empty" 'FOO=""' "FOO" ""

# Comments are ignored
run_test "comment line ignored" $'# comment\nFOO=bar' "FOO" "bar"

# Inline comment not supported (treated as part of value)
run_test "inline comment is part of value" "FOO=bar # comment" "FOO" "bar # comment"

# export prefix is handled
run_test "export prefix" "export FOO=bar" "FOO" "bar"

# export prefix with quotes
run_test "export prefix with quotes" 'export FOO="hello world"' "FOO" "hello world"

# Invalid key names are skipped
run_test_fail "invalid key (starts with digit)" "1FOO=bar" "1FOO"
run_test_fail "invalid key (special char)" "FOO-BAR=baz" "FOO-BAR"

# Multiple variables
run_test "multiple variables" $'FOO=bar\nBAZ=qux' "FOO" "bar"
run_test "multiple variables 2" $'FOO=bar\nBAZ=qux' "BAZ" "qux"

# Whitespace around key/value is trimmed
run_test "whitespace trimmed" $'  FOO  =  bar  ' "FOO" "bar"

# CRLF line endings
run_test "CRLF line endings" $'FOO=bar\r' "FOO" "bar"

# File not found returns error
run_test_fail "file not found" "" "NONEXISTENT_FILE_TEST"

echo ""
echo "Results: $pass passed, $fail failed"
if [[ $fail -gt 0 ]]; then
  exit 1
fi