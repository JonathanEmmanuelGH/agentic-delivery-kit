#!/usr/bin/env bash
# test-role-guard.sh: offline harness for role-guard.sh and role-claim.sh.
# A session may read before it claims a role; it may not edit or run mutating
# commands. A claimed role is scoped (role-scopes.conf) and never unlocks secrets.
set -u
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
. "$HERE/harness-lib.sh"
GUARD="$HERE/role-guard.sh"
HARNESS_TMP="$(mktemp -d)"
trap 'rm -rf "$HARNESS_TMP"' EXIT
export ADK_ROLE_DIR="$HARNESS_TMP/roles"
PROJECT="$HARNESS_TMP/project"
mkdir -p "$PROJECT"
git -C "$PROJECT" init -q -b draft
export CLAUDE_PROJECT_DIR="$PROJECT"

# r WANT TOOL JSON_INPUT [SESSION]
r() { payload "$2" "$3" "$PROJECT" "${4:-$HARNESS_SESSION}" | expect_rc "$1" "[${4:-$HARNESS_SESSION}] $2 $3" "$GUARD"; }
# b WANT COMMAND [SESSION]
b() { r "$1" Bash "$(bash_input "$2")" "${3:-}"; }
edit() { printf '{"file_path": "%s", "old_string": "a", "new_string": "b"}' "$1"; }

# --- before any claim: reading only ----------------------------------------------------------
r 0 Read '{"file_path": "src/app.py"}'
r 0 Grep '{"pattern": "def ", "path": "src"}'
r 0 Glob '{"pattern": "**/*.py"}'
r 0 Agent '{"prompt": "x"}'
r 0 mcp__tracker__get_issue '{"id": "1"}'
b 0 'ls -la'
b 0 'git status'
b 0 'git log --oneline -3 | head -2'
b 0 'git diff 2>/dev/null'
b 0 'grep -rn TODO src'
b 0 'find . -name "*.py"'
b 0 'git branch -a'
r 2 Edit "$(edit src/app.py)"
r 2 Write '{"file_path": "src/new.py", "content": "x"}'
r 2 mcp__tracker__create_issue '{"title": "x"}'
r 2 SomeFutureTool '{}'
b 2 'touch src/new.py'
b 2 'echo hi > file.txt'
b 2 'git commit -m x'
b 2 'git branch new-branch'
b 2 'find . -name "*.pyc" -delete'
b 2 'sort -o out.txt in.txt'
b 2 'ls $(pwd)'
b 2 'FOO=1 ls'
b 2 'python3 -c "print(1)"'
b 2 'git config user.email x@example.invalid'

# --- claiming ------------------------------------------------------------------------------
b 0 'bash kit/hooks/role-claim.sh worker'
test -f "$ADK_ROLE_DIR/$HARNESS_SESSION" && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: marker not written"; }
[ "$(stat -c %a "$ADK_ROLE_DIR/$HARNESS_SESSION" 2>/dev/null)" = 600 ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: marker mode is not 600"; }
r 0 Edit "$(edit src/app.py)"
b 0 'touch src/new.py'
b 0 'git commit -m x'

# a claim is per session: another session is still read-only
r 2 Edit "$(edit src/app.py)" other-session

# only the bare claim command counts
b 2 'cd /tmp && bash kit/hooks/role-claim.sh worker' sneaky-1
r 2 Edit "$(edit src/app.py)" sneaky-1
b 2 'bash kit/hooks/role-claim.sh worker; touch x' sneaky-2
r 2 Edit "$(edit src/app.py)" sneaky-2
b 0 'bash kit/hooks/role-claim.sh superuser' sneaky-3
r 2 Edit "$(edit src/app.py)" sneaky-3

# --- scopes -------------------------------------------------------------------------------------
b 0 'bash kit/hooks/role-claim.sh orchestrator' orch
r 0 Write '{"file_path": "orders/LIB-009.json", "content": "{}"}' orch
r 2 Edit "$(edit src/app.py)" orch
b 0 'bash kit/hooks/role-claim.sh docs' docs
r 0 Edit "$(edit docs/guide.md)" docs
r 0 Edit "$(edit README.md)" docs
r 2 Edit "$(edit src/app.py)" docs
b 0 'bash kit/hooks/role-claim.sh reviewer' rev
r 2 Edit "$(edit README.md)" rev
b 2 'touch x' rev
b 0 'git diff' rev

# --- a role never unlocks credential files --------------------------------------------------
r 2 Read '{"file_path": ".env"}'
r 2 Edit "$(edit .env)"
r 2 Write '{"file_path": "deploy/server.key", "content": "x"}'

# --- marker integrity ---------------------------------------------------------------------------
cp "$ADK_ROLE_DIR/$HARNESS_SESSION" "$ADK_ROLE_DIR/loose" && chmod 644 "$ADK_ROLE_DIR/loose"
r 2 Edit "$(edit src/app.py)" loose
ln -s "$ADK_ROLE_DIR/$HARNESS_SESSION" "$ADK_ROLE_DIR/linked"
r 2 Edit "$(edit src/app.py)" linked
cp "$ADK_ROLE_DIR/$HARNESS_SESSION" "$ADK_ROLE_DIR/stale" && chmod 600 "$ADK_ROLE_DIR/stale" && touch -d '3 days ago' "$ADK_ROLE_DIR/stale"
r 2 Edit "$(edit src/app.py)" stale

# --- malformed payloads ---------------------------------------------------------------------
printf 'garbage' | expect_rc 0 'non-JSON input is allowed (seatbelt)' "$GUARD"
printf '{"session_id":"a","session_id":"b","tool_name":"Edit","tool_input":{}}' | expect_rc 2 'duplicate key refused' "$GUARD"
printf '{"session_id":"../escape","tool_name":"Read","tool_input":{}}' | expect_rc 2 'unsafe session id refused' "$GUARD"
printf '{"tool_name":"Read","tool_input":{}}' | expect_rc 2 'missing session id refused' "$GUARD"

# --- the claim script itself ------------------------------------------------------------------
bash "$HERE/role-claim.sh" worker >/dev/null 2>&1 && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: role-claim.sh worker"; }
bash "$HERE/role-claim.sh" nobody >/dev/null 2>&1 && { FAIL=$((FAIL + 1)); echo "FAIL: role-claim.sh accepted an unknown role"; } || PASS=$((PASS + 1))

summary "role-guard"
