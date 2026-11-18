#!/usr/bin/env bash
# gate-wait.sh: wait for a detached gate's verdict and print one compact block.
#
# Usage: gate-wait.sh LOG [--pid PID] [--after EPOCH] [--timeout SECONDS] [--interval SECONDS] [--once]
#
# A gate is FINISHED only when its log ends with a newline-terminated exit=<n> line.
# PASS needs both a final "VERIFY: PASS" line and exit=0, and no PHASE END with rc other
# than 0. Everything else is FAIL. Why so strict: a piped test runner can report exit 0 on
# red, a launcher's pid is not the gate's pid, and a log path reused from an earlier run
# shows an old verdict. So:
#   --pid    the gate's real pid: if it dies without the final line, the verdict is ABORTED
#   --after  the launch time: a log not modified since then is an old run, never a verdict
#
# Exit codes: 0 PASS, 1 FAIL, 2 usage, 3 ABORTED, 4 TIMEOUT, 5 RUNNING (with --once).
# The block names the log's byte count and sha256, so the evidence can be checked later.
set -u

usage() { echo "usage: gate-wait.sh LOG [--pid PID] [--after EPOCH] [--timeout S] [--interval S] [--once]" >&2; exit 2; }
numeric() { [[ "$1" =~ ^(0|[1-9][0-9]{0,11})$ ]]; }

[ $# -ge 1 ] || usage
LOG=$1; shift
PID=""; AFTER=""; TIMEOUT=10800; INTERVAL=15; ONCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --pid|--after|--timeout|--interval)
      [ $# -ge 2 ] && numeric "$2" || usage
      case "$1" in --pid) PID=$2 ;; --after) AFTER=$2 ;; --timeout) TIMEOUT=$2 ;; --interval) INTERVAL=$2 ;; esac
      shift 2 ;;
    --once) ONCE=1; shift ;;
    *) usage ;;
  esac
done

finished() {
  [ -f "$LOG" ] || return 1
  if [ -n "$AFTER" ] && [ "$(stat -c %Y -- "$LOG")" -lt "$AFTER" ]; then return 1; fi
  [ "$(tail -c 1 -- "$LOG" | od -An -t x1 | tr -d ' ')" = "0a" ] || return 1
  tail -n 1 -- "$LOG" | grep -qE '^exit=[0-9]+$'
}

report() { # report VERDICT CODE
  local verify="none" exitline="none" bytes=0 sha="none" phases=0 bad=0 first_bad=""
  if [ -f "$LOG" ]; then
    verify=$(sed 's/\x1b\[[0-9;]*m//g' -- "$LOG" | grep -E '^VERIFY: ' | tail -n 1)
    exitline=$(tail -n 1 -- "$LOG" | grep -E '^exit=[0-9]+$' || true)
    bytes=$(stat -c %s -- "$LOG")
    sha=$(sha256sum -- "$LOG" | cut -d' ' -f1)
    phases=$(grep -cE '^PHASE END .* rc=[0-9]+ ' -- "$LOG")
    bad=$(grep -cE '^PHASE END .* rc=[1-9][0-9]* ' -- "$LOG")
    first_bad=$(grep -m1 -E '^PHASE END .* rc=[1-9][0-9]* ' -- "$LOG" || true)
  fi
  echo "GATE-WAIT: $1"
  echo "verify: ${verify:-none}"
  echo "exit: ${exitline:-none}"
  echo "log: $LOG bytes=$bytes sha256=$sha"
  echo "phases: $phases ended, $bad with rc other than 0"
  [ -n "$first_bad" ] && echo "first-failed-phase: $first_bad"
  exit "$2"
}

START=$(date +%s)
while :; do
  if finished; then
    verify=$(grep -E '^VERIFY: ' -- "$LOG" | tail -n 1)
    last=$(tail -n 1 -- "$LOG")
    if [[ "$verify" == "VERIFY: PASS"* && "$last" == "exit=0" ]] && ! grep -qE '^PHASE END .* rc=[1-9]' -- "$LOG"; then
      report PASS 0
    fi
    report FAIL 1
  fi
  [ "$ONCE" -eq 1 ] && report RUNNING 5
  if [ -n "$PID" ] && ! kill -0 "$PID" 2>/dev/null; then
    finished && continue
    report ABORTED 3
  fi
  [ $(( $(date +%s) - START )) -ge "$TIMEOUT" ] && report TIMEOUT 4
  sleep "$INTERVAL"
done
