#!/usr/bin/env bash
# test-gate-wait.sh: offline harness for gate-wait.sh and tests-for.sh.
set -u
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
. "$HERE/../hooks/harness-lib.sh"
WAIT="$HERE/gate-wait.sh"
SELECT="$HERE/tests-for.sh"
HARNESS_TMP="$(mktemp -d)"
trap 'rm -rf "$HARNESS_TMP"' EXIT

w() { # w WANT LABEL LOG [ARGS...]
  local want=$1 label=$2 got
  shift 2
  bash "$WAIT" "$@" --interval 1 --timeout 5 >"$HARNESS_TMP/out" 2>&1
  got=$?
  if [ "$got" = "$want" ]; then PASS=$((PASS + 1)); else
    FAIL=$((FAIL + 1)); echo "FAIL: $label (want $want, got $got)"; sed 's/^/    /' "$HARNESS_TMP/out"; fi
}
log() { printf '%b' "$2" > "$HARNESS_TMP/$1"; echo "$HARNESS_TMP/$1"; }

OK_BODY='PHASE START lint\nPHASE END lint rc=0 elapsed=1s\nVERIFY: PASS\nexit=0\n'
w 0 "pass" "$(log pass.log "$OK_BODY")"
grep -q '^GATE-WAIT: PASS' "$HARNESS_TMP/out" && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: verdict line"; }
grep -q 'sha256=[0-9a-f]\{64\}' "$HARNESS_TMP/out" && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: sha256 reported"; }
w 0 "scoped pass" "$(log scoped.log 'VERIFY: PASS (scoped: 2 test files)\nexit=0\n')"
w 1 "fail verdict" "$(log fail.log 'PHASE END tests rc=1 elapsed=2s\nVERIFY: FAIL (phases: tests)\nexit=1\n')"
w 1 "pass line with exit 1" "$(log mixed.log 'VERIFY: PASS\nexit=1\n')"
w 1 "exit 0 without a pass line" "$(log nopass.log 'tests ok\nexit=0\n')"
w 1 "pass and exit 0 but a phase failed" "$(log phase.log 'PHASE END lint rc=2 elapsed=1s\nVERIFY: PASS\nexit=0\n')"
w 5 "still running (--once)" "$(log running.log 'PHASE START tests\n')" --once
w 5 "no trailing newline is not finished" "$(log partial.log 'VERIFY: PASS\nexit=0')" --once
w 5 "missing log is running" "$HARNESS_TMP/absent.log" --once
w 4 "timeout" "$(log slow.log 'PHASE START tests\n')"
w 3 "aborted: the gate pid is gone" "$(log dead.log 'PHASE START tests\n')" --pid 999999999
OLD="$(log old.log "$OK_BODY")"
touch -d '1 hour ago' "$OLD"
w 5 "an old log is never a verdict (--after)" "$OLD" --after "$(date +%s)" --once
w 2 "usage: bad number" "$OLD" --pid abc
w 2 "usage: unknown flag" "$OLD" --bogus

# --- tests-for.sh selection ---------------------------------------------------------
s() { # s EXPECTED LABEL PATH...
  local want=$1 label=$2 got
  shift 2
  got="$(bash "$SELECT" "$@" | tr '\n' ' ' | sed 's/ $//')"
  if [ "$got" = "$want" ]; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); echo "FAIL: $label: got '$got', want '$want'"; fi
}
s "demo-app/tests/test_loans.py" "loans maps to its tests" demo-app/library/loans.py
s "demo-app/tests/test_fees.py demo-app/tests/test_loans.py" "fees maps to two files" demo-app/library/fees.py
s "demo-app/tests/test_views.py" "a changed test selects itself" demo-app/tests/test_views.py
s "" "docs select nothing" README.md kit/seats/README.md
s "ALL" "an unmapped path selects everything" demo-app/library/new_module.py
s "ALL" "the package init selects everything" demo-app/library/__init__.py demo-app/library/loans.py
s "demo-app/tests/test_loans.py" "paths on stdin work" < <(printf 'demo-app/library/loans.py\n')

summary "gate-wait and tests-for"
