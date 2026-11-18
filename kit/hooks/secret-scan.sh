#!/usr/bin/env bash
# secret-scan.sh: baseline secret scan over the tracked files of the repository that
# contains the current directory. See secret_scan.py for the rules, the baseline format
# and the exit codes.
# Usage: secret-scan.sh [--list | --self-test | --update-baseline]
# ADK_SCAN_BASELINE overrides the baseline path (relative to the repository root).
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [ "${1:-}" = "--self-test" ]; then
  exec python3 -I "$HERE/secret_scan.py" --self-test
fi
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
export ADK_SCAN_BASELINE="${ADK_SCAN_BASELINE:-$(realpath --relative-to="$ROOT" "$HERE")/secret-scan-baseline.txt}"
exec python3 -I "$HERE/secret_scan.py" "$@"
