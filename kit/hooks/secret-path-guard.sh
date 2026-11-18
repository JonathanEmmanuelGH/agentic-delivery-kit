#!/usr/bin/env bash
# secret-path-guard.sh: Claude Code PreToolUse hook. Payload on stdin; exit 0 allows, exit 2 blocks.
# The logic lives in guard.py (one parser, shared predicates); this wrapper only fails
# closed when python3 is missing, because a guard that cannot classify must not allow.
set -u
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
command -v python3 >/dev/null 2>&1 || { echo "BLOCKED by secret-path-guard: python3 is required to classify tool calls" >&2; exit 2; }
exec python3 -I "$HERE/guard.py" path
