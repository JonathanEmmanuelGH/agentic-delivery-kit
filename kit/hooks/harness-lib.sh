#!/usr/bin/env bash
# harness-lib.sh: tiny assertion helpers shared by the guard harnesses. Sourced, not run.
# Every harness runs offline with bash and python3 only, in a private temporary directory.

# lastpipe: `payload ... | expect_rc ...` runs expect_rc in this shell, so the counters
# it updates survive the pipeline (a script has job control off, which lastpipe needs).
shopt -s lastpipe
PASS=0
FAIL=0
HARNESS_SESSION="${HARNESS_SESSION:-harness-session-1}"

# payload TOOL JSON_INPUT [CWD] [SESSION]: print a hook payload.
payload() {
  python3 -c 'import json,sys
print(json.dumps({"session_id": sys.argv[4], "tool_name": sys.argv[1],
                  "tool_input": json.loads(sys.argv[2]), "cwd": sys.argv[3]}))' \
    "$1" "$2" "${3:-$PWD}" "${4:-$HARNESS_SESSION}"
}

# bash_input COMMAND: the tool_input object of a Bash call.
bash_input() {
  python3 -c 'import json,sys; print(json.dumps({"command": sys.argv[1]}))' "$1"
}

# expect_rc WANT LABEL GUARD_SCRIPT < payload
expect_rc() {
  local want=$1 label=$2 guard=$3 got
  bash "$guard" >/dev/null 2>"$HARNESS_TMP/stderr"
  got=$?
  if [ "$got" = "$want" ]; then
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
    printf 'FAIL: %s (want %s, got %s): %s\n' "$label" "$want" "$got" "$(head -c 300 "$HARNESS_TMP/stderr")"
  fi
}

# summary NAME: print the result line and exit with the right code.
summary() {
  printf '%s: %d passed, %d failed\n' "$1" "$PASS" "$FAIL"
  [ "$FAIL" -eq 0 ]
}
