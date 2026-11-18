#!/usr/bin/env bash
# tests-for.sh: map changed paths to the test files they select (test-map.txt).
#
# Usage: tests-for.sh PATH...        (or the paths on stdin, one per line)
# Prints one target per line, sorted and unique: test file paths, or the single word
# ALL when any path selects the whole suite or matches no line (fail safe). Prints
# nothing when every path maps to NONE.
#
# Why: a gate whose cost is proportional to the change gets run; a gate that always
# costs twenty minutes gets skipped. The map is the explicit, reviewable link between
# source files and tests, and an unmapped file always means "run everything".
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
MAP="${ADK_TEST_MAP:-$HERE/test-map.txt}"
if [ "$#" -gt 0 ]; then printf '%s\n' "$@"; else cat; fi | python3 -I -c '
import fnmatch, sys
rules = []
with open(sys.argv[1], encoding="utf-8") as f:
    for line in f:
        parts = line.split("#", 1)[0].split()
        if len(parts) >= 2:
            rules.append((parts[0], parts[1:]))
selected = set()
for path in (p.strip() for p in sys.stdin):
    if not path:
        continue
    for glob, targets in rules:
        if fnmatch.fnmatchcase(path, glob):
            for t in targets:
                if t == "SELF":
                    selected.add(path)
                elif t != "NONE":
                    selected.add(t)
            break
    else:
        selected.add("ALL")
print("ALL" if "ALL" in selected else "\n".join(sorted(selected)), end="")
print() if selected else None
' "$MAP"
