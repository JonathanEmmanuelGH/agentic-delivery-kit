#!/usr/bin/env bash
# verify.sh: the single verification gate.
#
# One command decides whether a tree is mergeable, so "it passed" means the same thing
# for every agent and for the human. It runs these phases in order:
#
#   lint       bash -n on every shell script, a syntax parse of every Python file,
#              JSON validity, no typographic dashes; shellcheck and ruff when installed
#   secrets    secret-scan.sh --self-test, then the baseline scan of tracked files
#   harnesses  every kit/**/test-*.sh (guards, gate, orders, seat sync)
#   orders     validate-work-order.sh --all on orders/examples (lane conflicts)
#   tests      the demo app's unit tests: all of them, or the change-scoped selection
#
# The final two lines are the verdict a human merges on, and nothing else counts:
#   VERIFY: PASS            (or VERIFY: PASS (scoped: ...) / VERIFY: FAIL (phases: ...))
#   exit=<n>
# A PASS line without exit=0, or exit=0 without a PASS line, is not evidence.
#
# Environment:
#   VERIFY_SCOPE=full|auto   full (default) runs every test; auto selects tests from the
#                            paths changed against VERIFY_BASE through tests-for.sh
#   VERIFY_BASE=<ref>        base for auto (default: merge-base with origin/main or main)
#   VERIFY_FAIL_FAST=1       stop at the first failing phase
#
# Long gates are run detached with the output in a uniquely named log, then awaited
# with gate-wait.sh; never inside a tool call's timeout.
set -uo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd -- "$HERE/../.." && pwd -P)"
cd "$ROOT" || exit 2
export PYTHONDONTWRITEBYTECODE=1
SCOPE="${VERIFY_SCOPE:-full}"
FAIL_FAST="${VERIFY_FAIL_FAST:-0}"
FAILED=()
QUALIFIER=""

phase() { # phase NAME FUNCTION
  local name=$1 fn=$2 start rc
  if [ "$FAIL_FAST" = 1 ] && [ "${#FAILED[@]}" -gt 0 ]; then
    echo "PHASE SKIP $name (fail fast)"
    return
  fi
  start=$(date +%s)
  echo "PHASE START $name"
  "$fn"
  rc=$?
  echo "PHASE END $name rc=$rc elapsed=$(( $(date +%s) - start ))s"
  [ "$rc" -eq 0 ] || FAILED+=("$name")
}

tracked() { git ls-files -- "$@" 2>/dev/null; }

lint() {
  local rc=0 f
  while IFS= read -r f; do bash -n "$f" || { echo "LINT: bash -n failed: $f"; rc=1; }; done < <(tracked '*.sh')
  tracked '*.py' | python3 -I -c '
import ast, sys
bad = 0
for path in sys.stdin.read().split():
    try:
        ast.parse(open(path, encoding="utf-8").read(), path)
    except SyntaxError as e:
        print(f"LINT: syntax error: {path}:{e.lineno}: {e.msg}"); bad = 1
sys.exit(bad)' || rc=1
  tracked '*.json' | python3 -I -c '
import json, sys
bad = 0
for path in sys.stdin.read().split():
    try:
        json.load(open(path, encoding="utf-8"))
    except ValueError as e:
        print(f"LINT: invalid JSON: {path}: {e}"); bad = 1
sys.exit(bad)' || rc=1
  # House rule: no typographic dashes (U+2013, U+2014) in any tracked text.
  git ls-files -z | python3 -I -c '
import sys
bad = 0
for path in sys.stdin.buffer.read().decode("utf-8", "replace").split("\0"):
    if not path:
        continue
    try:
        text = open(path, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError):
        continue
    for n, line in enumerate(text.splitlines(), 1):
        if "–" in line or "—" in line:
            print(f"LINT: typographic dash: {path}:{n}"); bad = 1
sys.exit(bad)' || rc=1
  if command -v shellcheck >/dev/null 2>&1; then
    tracked '*.sh' | xargs -r shellcheck -S error || rc=1
  else
    echo "LINT: shellcheck not installed (skipped)"
  fi
  if command -v ruff >/dev/null 2>&1; then
    ruff check --quiet --select E9,F63,F7,F82 . || rc=1
  else
    echo "LINT: ruff not installed (skipped)"
  fi
  return $rc
}

secrets() {
  bash kit/hooks/secret-scan.sh --self-test && bash kit/hooks/secret-scan.sh
}

harnesses() {
  local rc=0 h hrc
  while IFS= read -r h; do
    bash "$h"
    hrc=$?
    echo "HARNESS $h rc=$hrc"
    [ "$hrc" -eq 0 ] || rc=1
  done < <(tracked 'kit/*test-*.sh' | sort)
  return $rc
}

orders() {
  bash kit/orders/validate-work-order.sh --all orders/examples
}

select_tests() {
  local base changed
  base="${VERIFY_BASE:-}"
  if [ -z "$base" ]; then
    for ref in origin/main main; do
      if git rev-parse -q --verify "$ref^{commit}" >/dev/null; then base=$(git merge-base HEAD "$ref"); break; fi
    done
  fi
  if [ -z "$base" ]; then echo "ALL"; return; fi
  changed=$( { git diff --name-only "$base"; git ls-files --others --exclude-standard; } | sort -u)
  [ -n "$changed" ] || return 0
  printf '%s\n' "$changed" | bash "$HERE/tests-for.sh"
}

TEST_MODULES=()
tests() {
  local args=()
  if [ "${#TEST_MODULES[@]}" -gt 0 ]; then
    args=("${TEST_MODULES[@]}")
  else
    args=(discover -s tests -t .)
  fi
  ( cd demo-app && python3 -m unittest "${args[@]}" )
}

no_tests() { echo "tests: no test selected for the changed paths"; }

phase lint lint
phase secrets secrets
phase harnesses harnesses
phase orders orders

if [ "$SCOPE" = "auto" ]; then
  selection="$(select_tests)"
  if [ "$selection" = "ALL" ]; then
    QUALIFIER=" (auto: full suite selected)"
    phase tests tests
  elif [ -z "$selection" ]; then
    QUALIFIER=" (scoped: no tests selected)"
    phase tests no_tests
  else
    while IFS= read -r t; do
      t="${t#demo-app/}"; t="${t%.py}"; TEST_MODULES+=("${t//\//.}")
    done <<< "$selection"
    QUALIFIER=" (scoped: ${#TEST_MODULES[@]} test files)"
    phase tests tests
  fi
elif [ "$SCOPE" = "full" ]; then
  phase tests tests
else
  echo "unknown VERIFY_SCOPE=$SCOPE (use full or auto)"
  FAILED+=("scope")
fi

if [ "${#FAILED[@]}" -eq 0 ]; then
  echo "VERIFY: PASS$QUALIFIER"
  echo "exit=0"
  exit 0
fi
echo "VERIFY: FAIL (phases: ${FAILED[*]})"
echo "exit=1"
exit 1
