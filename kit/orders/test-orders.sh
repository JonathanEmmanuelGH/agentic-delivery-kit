#!/usr/bin/env bash
# test-orders.sh: offline harness for validate-work-order.sh and order-context.sh,
# run in a throwaway git repository.
set -u
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
. "$HERE/../hooks/harness-lib.sh"
VALIDATE="$HERE/validate-work-order.sh"
CONTEXT="$HERE/order-context.sh"
KIT_ROOT="$(cd -- "$HERE/../.." && pwd -P)"
HARNESS_TMP="$(mktemp -d)"
trap 'rm -rf "$HARNESS_TMP"' EXIT
REPO="$HARNESS_TMP/repo"
mkdir -p "$REPO/src" "$REPO/tests"
cd "$REPO" || exit 1
git init -q -b draft
g() { git -c user.name=harness -c user.email=harness@example.invalid "$@"; }
printf 'line one\nline two\nline three\n' > src/app.py
printf 'def test_x():\n    pass\n' > tests/test_app.py
g add src/app.py tests/test_app.py && g commit -q -m base
BASE="$(git rev-parse HEAD)"

# order DIR NAME [FIELD=JSON_VALUE ...]: write a valid order, with overrides.
order() {
  local dir=$1 name=$2
  shift 2
  mkdir -p "$dir"
  python3 - "$dir/$name" "$BASE" "$@" <<'PY'
import json, sys
path, base, *overrides = sys.argv[1:]
o = {
    "id": "APP-001", "seat": "claude-dev", "model": "sonnet", "base_sha": base,
    "objective": "Add a greeting.", "source_refs": [{"file": "src/app.py", "lines": "1-2"}],
    "allowed_paths": ["src/app.py", "tests/test_app.py"], "forbidden_paths": ["kit/*"],
    "required_cases": {"positive": ["greets"], "negative": ["refuses empty name"]},
    "verification": ["kit/gate/verify.sh"], "evidence_to_post": ["VERIFY line", "exit line"],
    "migration": False, "status": "active",
    "created": "2026-01-05T10:00:00Z", "expires": "2026-01-12T10:00:00Z",
}
for item in overrides:
    key, value = item.split("=", 1)
    if value == "DELETE":
        o.pop(key)
    else:
        o[key] = json.loads(value)
with open(path, "w", encoding="utf-8") as f:
    json.dump(o, f, indent=2)
PY
}

v() { # v WANT LABEL ARGS...
  local want=$1 label=$2 got
  shift 2
  bash "$VALIDATE" "$@" >"$HARNESS_TMP/out" 2>&1
  got=$?
  if [ "$got" = "$want" ]; then PASS=$((PASS + 1)); else
    FAIL=$((FAIL + 1)); echo "FAIL: $label (want $want, got $got)"; sed 's/^/    /' "$HARNESS_TMP/out"; fi
}
contains() { if grep -qF -- "$2" "$3"; then PASS=$((PASS + 1)); else FAIL=$((FAIL + 1)); echo "FAIL: $1"; fi; }

# --- one order --------------------------------------------------------------------------
order o1 a.json;                                      v 0 "valid order" o1/a.json
order o2 a.json 'objective=DELETE';                   v 2 "missing field" o2/a.json
order o3 a.json 'extra="x"';                          v 2 "unknown field" o3/a.json
order o4 a.json 'seat="intern"';                      v 2 "unknown seat" o4/a.json
order o5 a.json 'model="whatever-is-default"';        v 2 "unpinned model" o5/a.json
order o6 a.json 'base_sha="abc"';                     v 2 "short base sha" o6/a.json
order o7 a.json 'allowed_paths=["/etc/passwd"]';      v 2 "absolute glob" o7/a.json
order o8 a.json 'allowed_paths=["src/../kit"]';       v 2 "dot-dot glob" o8/a.json
order o9 a.json 'allowed_paths=[]';                   v 2 "empty allowed paths" o9/a.json
order o10 a.json 'created="yesterday"';               v 2 "bad date" o10/a.json
order o11 a.json 'migration="no"';                    v 2 "migration must be boolean" o11/a.json
order o12 a.json 'required_cases={"positive": []}';   v 2 "cases need both lists" o12/a.json
order o13 a.json 'id="app-1"';                        v 2 "bad id" o13/a.json
mkdir -p o14 && printf 'id: APP-001\n' > o14/a.yaml;  v 2 "non-JSON order" o14/a.yaml
v 2 "usage" --all

# --- lanes --------------------------------------------------------------------------------
order lanes1 a.json; order lanes1 b.json 'id="APP-002"' 'allowed_paths=["src/*"]'
v 1 "overlapping open orders are refused" lanes1/a.json
v 1 "--all refuses the same conflict" --all lanes1
contains "the conflict is named" "path lane conflict: APP-001 and APP-002" "$HARNESS_TMP/out"

order lanes2 a.json; order lanes2 b.json 'id="APP-002"' 'allowed_paths=["src/*"]' 'status="landed"'
v 0 "a landed order frees its paths" --all lanes2

order lanes3 a.json 'migration=true'; order lanes3 b.json 'id="APP-002"' 'allowed_paths=["docs/x.md"]' 'migration=true'
v 1 "two open migrations are refused" --all lanes3

order lanes4 a.json; order lanes4 b.json 'id="APP-002"' 'allowed_paths=["docs/*"]' 'status="review"'
v 0 "disjoint open orders coexist" --all lanes4
contains "the table lists both" "APP-002 | claude-dev | sonnet | review" "$HARNESS_TMP/out"

order lanes5 a.json; printf '{"id": 1}\n' > lanes5/broken.json
v 2 "a malformed sibling is reported" --all lanes5

order lanes6 a.json 'base_sha="0000000000000000000000000000000000000000"'
v 0 "a base outside history only warns" lanes6/a.json
contains "the warning is printed" "WARN: APP-001" "$HARNESS_TMP/out"

# --- order context -------------------------------------------------------------------------
order ctx a.json 'source_refs=[{"file": "src/app.py", "lines": "2-3"}, {"file": "src/gone.py", "lines": "1"}]'
bash "$CONTEXT" ctx/a.json >"$HARNESS_TMP/out" 2>&1 && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: context build"; cat "$HARNESS_TMP/out"; }
CTX="ctx/APP-001.context.md"
contains "header" "- base_sha: $BASE" "$CTX"
contains "fields" '["src/app.py", "tests/test_app.py"]' "$CTX"
contains "excerpt" "3: line three" "$CTX"
contains "missing excerpt is named" "MISSING at" "$CTX"
v 0 "the context file does not upset the validator" --all ctx

g switch -q -c feature/greeting
printf 'hello\n' >> src/app.py
mkdir -p kit && printf 'x\n' > kit/tool.sh
g add src/app.py kit/tool.sh && g commit -q -m change
bash "$CONTEXT" ctx/a.json --head HEAD --out "$HARNESS_TMP/head.md" >/dev/null 2>&1 && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: context with head"; }
contains "out of scope path flagged" '- `kit/tool.sh`' "$HARNESS_TMP/head.md"
if grep -qF -- '- `src/app.py`' "$HARNESS_TMP/head.md"; then FAIL=$((FAIL + 1)); echo "FAIL: in-scope path flagged"; else PASS=$((PASS + 1)); fi
contains "stat section" "## 4. NAME-STATUS AND STAT" "$HARNESS_TMP/head.md"

bash "$CONTEXT" ctx/a.json --max-bytes 600 --out "$HARNESS_TMP/small.md" >/dev/null 2>&1
[ "$(wc -c < "$HARNESS_TMP/small.md")" -le 620 ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: byte cap"; }

bash "$CONTEXT" ctx/a.json --head no-such-ref >/dev/null 2>&1; [ $? -eq 4 ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: unknown head exit 4"; }
bash "$CONTEXT" o2/a.json >/dev/null 2>&1; [ $? -eq 3 ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: invalid order exit 3"; }
bash "$CONTEXT" >/dev/null 2>&1; [ $? -eq 2 ] && PASS=$((PASS + 1)) || { FAIL=$((FAIL + 1)); echo "FAIL: usage exit 2"; }

# --- the repository's own example orders -------------------------------------------------------
cd "$KIT_ROOT" || exit 1
v 0 "the example orders validate" --all orders/examples

summary "orders"
