#!/usr/bin/env bash
# test-secret-scan.sh: offline harness for secret-scan.sh in a throwaway git repository.
# Every secret-shaped fixture is assembled at runtime, so this file holds none.
set -u
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
. "$HERE/harness-lib.sh"
SCAN="$HERE/secret-scan.sh"
HARNESS_TMP="$(mktemp -d)"
trap 'rm -rf "$HARNESS_TMP"' EXIT
REPO="$HARNESS_TMP/repo"
mkdir -p "$REPO/src"
cd "$REPO" || exit 1
git init -q -b draft
g() { git -c user.name=harness -c user.email=harness@example.invalid "$@"; }
export ADK_SECRET_BASELINE="baseline.txt"

check() { # check WANT_RC LABEL [ARGS...]
  local want=$1 label=$2 got
  shift 2
  bash "$SCAN" "$@" >"$HARNESS_TMP/out" 2>&1
  got=$?
  if [ "$got" = "$want" ]; then PASS=$((PASS + 1)); else
    FAIL=$((FAIL + 1)); echo "FAIL: $label (want $want, got $got)"; sed 's/^/    /' "$HARNESS_TMP/out"; fi
}
contains() { # contains LABEL TEXT
  if grep -qF -- "$2" "$HARNESS_TMP/out"; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); echo "FAIL: $1"; fi
}
lacks() { # lacks LABEL TEXT
  if grep -qF -- "$2" "$HARNESS_TMP/out"; then FAIL=$((FAIL + 1)); echo "FAIL: $1"; else PASS=$((PASS + 1)); fi
}

check 0 "self-test passes" --self-test
check 2 "unknown flag is a usage error" --bogus

printf 'def add(a, b):\n    return a + b\n' > src/clean.py
g add src/clean.py && g commit -q -m clean
check 0 "clean repository passes"

KEY="AKIA$(printf 'Q%.0s' $(seq 16))"
printf 'aws_id = "%s"\n' "$KEY" > src/config.py
g add src/config.py && g commit -q -m "add config"
check 1 "a new finding fails the scan"
contains "the finding names rule and file" "NEW: aws-access-key src/config.py:1"
lacks "the value is never printed" "$KEY"

check 0 "update-baseline re-blesses the current state" --update-baseline
check 0 "baselined finding passes"
lacks "baseline is value-free" "$KEY"
if grep -qF -- "$KEY" baseline.txt; then FAIL=$((FAIL + 1)); echo "FAIL: baseline holds the value"; else PASS=$((PASS + 1)); fi
check 0 "--list shows known findings and passes" --list
contains "--list marks known findings" "known: aws-access-key src/config.py:1"

printf 'backup_id = "%s"\n' "$KEY" >> src/config.py
g add src/config.py && g commit -q -m "second copy"
check 1 "a second occurrence in the same file is new"

g rm -q --cached src/config.py && g commit -q -m "drop config"
check 0 "removed finding passes"

PEM_HEAD="-----BEGIN $(printf 'EC PRIVATE') KEY-----"
printf '%s\nabc\n' "$PEM_HEAD" > src/notes.txt
g add src/notes.txt && g commit -q -m notes
check 1 "a private key header is found"
g rm -q --cached src/notes.txt && g commit -q -m "drop notes"

mkdir -p deploy && printf 'PLACEHOLDER=1\n' > deploy/app.env
g add -f deploy/app.env && g commit -q -m "tracked dotenv"
check 1 "a tracked credential-shaped file fails"
contains "the tracked file is named" "TRACKED CREDENTIAL FILE: deploy/app.env"
g rm -q --cached deploy/app.env && g commit -q -m "untrack"
check 0 "after untracking, the scan passes"

printf 'binary\0%s\n' "$KEY" > src/blob.bin
g add src/blob.bin && g commit -q -m blob
check 0 "binary files are skipped"

summary "secret-scan"
