#!/usr/bin/env bash
# validate-work-order.sh: validate JSON work orders and refuse conflicting open lanes.
#
# Usage:
#   validate-work-order.sh ORDER.json        validate one order, and check it against its siblings
#   validate-work-order.sh --all DIRECTORY   validate every order in DIRECTORY and print a table
#
# Two orders that are both open (reserved, active or review) conflict when their
# allowed_paths overlap, or when both declare a database migration: one migration
# in flight repository-wide, and no two agents ever own the same path at once.
#
# Exit codes: 0 valid and no conflict, 1 lane conflict (REFUSED), 2 malformed or usage.
# Warns (stderr, no failure) when base_sha is not an ancestor of ADK_INTEGRATION_REF
# (default origin/main, then main, then HEAD).
#
# JSON on purpose: a hand-rolled YAML parser would silently misread nested fields, and
# the schema is enforced with the Python standard library only (no jsonschema install).
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SCHEMA="$HERE/work-order.schema.json"
if [ "$#" -eq 2 ] && [ "$1" = "--all" ]; then MODE="all"; TARGET="$2"
elif [ "$#" -eq 1 ] && [ "$1" != "--all" ]; then MODE="one"; TARGET="$1"
else echo "usage: $0 ORDER.json | $0 --all DIRECTORY" >&2; exit 2; fi
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd -P)"
set +e
python3 -I - "$ROOT" "$MODE" "$TARGET" "$SCHEMA" <<'PY'
import datetime as dt
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT, MODE, TARGET, SCHEMA = sys.argv[1:]
with open(SCHEMA, encoding="utf-8") as f:
    schema = json.load(f)
props = schema["properties"]
REQUIRED = set(schema["required"])
SEATS = set(props["seat"]["enum"])
MODELS = set(props["model"]["enum"])
STATUSES = set(props["status"]["enum"])
OPEN = {"reserved", "active", "review"}
ID = re.compile(props["id"]["pattern"])
SHA = re.compile(props["base_sha"]["pattern"])
LINES = re.compile(props["source_refs"]["items"]["properties"]["lines"]["pattern"])
DATE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")


class Invalid(Exception):
    pass


def bad(msg):
    raise Invalid(msg)


def date(value, name):
    if not isinstance(value, str) or not DATE.fullmatch(value):
        bad(f"{name} must be a date-time")
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        bad(f"{name} must be a date-time")


def glob(value):
    if not isinstance(value, str) or not value or value.startswith("/") or "\x00" in value:
        bad(f"malformed glob: {value!r}")
    if any(p in {"", ".", ".."} for p in value.split("/")) or value.count("[") != value.count("]"):
        bad(f"malformed glob: {value!r}")


def strings(value, name, minimum=0):
    if not isinstance(value, list) or len(value) < minimum or not all(isinstance(x, str) and x for x in value):
        bad(f"{name} must be an array of non-empty strings" + (" with at least one item" if minimum else ""))


def validate(d):
    if not isinstance(d, dict):
        bad("top level must be an object")
    if set(d) != REQUIRED:
        missing, extra = sorted(REQUIRED - set(d)), sorted(set(d) - REQUIRED)
        bad("fields must match the schema" + (f"; missing: {', '.join(missing)}" if missing else "")
            + (f"; unknown: {', '.join(extra)}" if extra else ""))
    if not isinstance(d["id"], str) or not ID.fullmatch(d["id"]):
        bad("bad id")
    if d["seat"] not in SEATS:
        bad(f"unknown seat {d['seat']!r}")
    if d["model"] not in MODELS:
        bad(f"unknown model {d['model']!r}: every order pins a model")
    if not isinstance(d["base_sha"], str) or not SHA.fullmatch(d["base_sha"]):
        bad("bad base_sha")
    if not isinstance(d["objective"], str) or not d["objective"]:
        bad("objective must be a non-empty string")
    if not isinstance(d["source_refs"], list):
        bad("source_refs must be an array")
    for ref in d["source_refs"]:
        if (not isinstance(ref, dict) or set(ref) != {"file", "lines"} or not isinstance(ref["file"], str)
                or not ref["file"] or not isinstance(ref["lines"], str) or not LINES.fullmatch(ref["lines"])):
            bad("bad source_refs entry")
    strings(d["allowed_paths"], "allowed_paths", 1)
    strings(d["forbidden_paths"], "forbidden_paths")
    for item in d["allowed_paths"] + d["forbidden_paths"]:
        glob(item)
    cases = d["required_cases"]
    if not isinstance(cases, dict) or set(cases) != {"positive", "negative"}:
        bad("required_cases must contain exactly positive and negative")
    strings(cases["positive"], "required_cases.positive")
    strings(cases["negative"], "required_cases.negative")
    strings(d["verification"], "verification")
    strings(d["evidence_to_post"], "evidence_to_post")
    if not isinstance(d["migration"], bool):
        bad("migration must be a boolean")
    if d["status"] not in STATUSES:
        bad("bad status")
    date(d["created"], "created")
    date(d["expires"], "expires")


def load(path):
    if path.suffix.lower() != ".json":
        bad("work orders are JSON files")
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        bad(f"invalid JSON: {e}")
    validate(data)
    return data


def ignored(path):
    return path.name.startswith("README") or path.name.endswith((".bak", ".context.md", ".md", ".txt"))


def sample(pattern):
    return re.sub(r"\*\*|\*|\?|\[[^]]+\]", "x", pattern)


def fixed_prefix(pattern):
    return pattern.split("*", 1)[0].split("?", 1)[0].split("[", 1)[0].rstrip("/")


def overlaps(a, b):
    if a == b or fnmatch.fnmatchcase(sample(a), b) or fnmatch.fnmatchcase(sample(b), a):
        return True
    x, y = fixed_prefix(a), fixed_prefix(b)
    return bool(x and y and (x == y or x.startswith(y + "/") or y.startswith(x + "/")))


def integration_ref():
    for ref in ([os.environ["ADK_INTEGRATION_REF"]] if os.environ.get("ADK_INTEGRATION_REF") else []) + ["origin/main", "main", "HEAD"]:
        if subprocess.run(["git", "rev-parse", "-q", "--verify", f"{ref}^{{commit}}"], cwd=ROOT,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return ref
    return None


def ancestor(sha, ref):
    return subprocess.run(["git", "merge-base", "--is-ancestor", sha, ref], cwd=ROOT,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def collect(directory):
    p = Path(directory)
    if not p.is_dir():
        bad(f"{p}: not a directory")
    items, errors = [], []
    for path in sorted(x for x in p.iterdir() if x.is_file() and not ignored(x)):
        try:
            items.append((path, load(path)))
        except Invalid as e:
            errors.append(f"{path.name}: {e}")
    return items, errors


def checks(items):
    ref = integration_ref()
    for _, o in items:
        if ref and o["status"] in OPEN and not ancestor(o["base_sha"], ref):
            print(f"WARN: {o['id']}: base_sha is not an ancestor of {ref}", file=sys.stderr)
    refused = []
    for i, (_, one) in enumerate(items):
        if one["status"] not in OPEN:
            continue
        for _, two in items[i + 1:]:
            if two["status"] not in OPEN:
                continue
            if one["migration"] and two["migration"]:
                refused.append(f"migration lane conflict: {one['id']} and {two['id']}")
            pairs = [(a, b) for a in one["allowed_paths"] for b in two["allowed_paths"] if overlaps(a, b)]
            if pairs:
                refused.append(f"path lane conflict: {one['id']} and {two['id']} ({pairs[0][0]} vs {pairs[0][1]})")
    for line in refused:
        print(f"REFUSED: {line}", file=sys.stderr)
    return 1 if refused else 0


try:
    if MODE == "all":
        items, errors = collect(TARGET)
        code = checks(items)
        print("id | seat | model | status | migration | allowed paths")
        for _, o in items:
            print(f"{o['id']} | {o['seat']} | {o['model']} | {o['status']} | {str(o['migration']).lower()} | {', '.join(o['allowed_paths'])}")
    else:
        target = Path(TARGET)
        order = load(target)
        items, errors = collect(target.parent)
        if target.resolve() not in {p.resolve() for p, _ in items}:
            items.append((target, order))
        code = checks(items)
        if code == 0:
            print(f"OK: {order['id']}")
    for e in errors:
        print(f"MALFORMED: {e}", file=sys.stderr)
    if errors:
        code = 2
except Invalid as e:
    print(f"MALFORMED: {e}", file=sys.stderr)
    code = 2
sys.exit(code)
PY
STATUS=$?
set -e
if [ "$STATUS" -gt 2 ]; then echo "MALFORMED: validator failed to run (python3 exit $STATUS)" >&2; exit 2; fi
exit "$STATUS"
