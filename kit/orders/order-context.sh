#!/usr/bin/env bash
# order-context.sh: build a compact Markdown context file for one validated work order.
#
# Usage: order-context.sh ORDER.json [--head REF] [--out FILE] [--max-bytes N]
#
# Why: every agent that touches an order (worker, reviewer, git manager) would otherwise
# re-read the same files to rebuild the same picture, and an agent's cost is its number of
# calls times the size of its context. One small file, built once per order and once more
# per candidate head, is handed to each of them instead.
#
# Everything comes from the git object store (never the working tree), so the file
# describes exactly base_sha and, with --head, exactly that commit:
#   1. header     id, seat, model, status, base, and with --head the head, tree and merge base
#   2. fields     objective, allowed and forbidden paths, required cases, verification
#   3. scope      with --head: changed paths outside allowed_paths or inside forbidden_paths
#   4. diff stat  with --head: name-status and stat of base...head
#   5. excerpts   the source_refs line ranges at base, trimmed to fit --max-bytes
#
# Exit codes: 0 written, 2 usage, 3 invalid order, 4 unknown base or head.
set -euo pipefail
usage() { echo "usage: order-context.sh ORDER.json [--head REF] [--out FILE] [--max-bytes N]" >&2; exit 2; }
[ $# -ge 1 ] || usage
ORDER=$1; shift
HEAD_REF=""; OUT=""; MAX_BYTES=24000
while [ $# -gt 0 ]; do
  case "$1" in
    --head|--out|--max-bytes)
      [ $# -ge 2 ] || usage
      case "$1" in --head) HEAD_REF=$2 ;; --out) OUT=$2 ;; --max-bytes) MAX_BYTES=$2 ;; esac
      shift 2 ;;
    *) usage ;;
  esac
done
[[ "$MAX_BYTES" =~ ^[1-9][0-9]{0,11}$ ]] || usage
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(git rev-parse --show-toplevel)"
[[ "$ORDER" = /* ]] || ORDER="$PWD/$ORDER"
[[ -z "$OUT" || "$OUT" = /* ]] || OUT="$PWD/$OUT"
bash "$HERE/validate-work-order.sh" "$ORDER" >/dev/null || exit 3

exec python3 -I - "$ROOT" "$ORDER" "$HEAD_REF" "$OUT" "$MAX_BYTES" <<'PY'
import fnmatch
import json
import subprocess
import sys
from pathlib import Path

root, order_name, head_ref, out_name, cap_text = sys.argv[1:]
cap = int(cap_text)
order_path = Path(order_name)
DIFF = ["--no-renames", "--no-ext-diff", "--no-textconv"]


def git(*args):
    return subprocess.run(["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          check=True).stdout.decode("utf-8", "replace")


def commit(ref):
    r = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"], cwd=root,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.stdout.decode().strip() if r.returncode == 0 else None


order = json.loads(order_path.read_text(encoding="utf-8"))
base = commit(order["base_sha"])
head = commit(head_ref) if head_ref else None
if base is None or (head_ref and head is None):
    print("order-context: unknown base or head commit", file=sys.stderr)
    sys.exit(4)

if out_name:
    out_path = Path(out_name)
else:
    suffix = f"-{head[:12]}" if head else ""
    out_path = order_path.parent / f"{order['id']}{suffix}.context.md"

lines = ["# ORDER CONTEXT", "", "## 1. HEADER", f"- id: {order['id']}", f"- seat: {order['seat']}",
         f"- model: {order['model']}", f"- status: {order['status']}", f"- base_sha: {base}"]
if head:
    lines += [f"- head: {head}", f"- head_tree: {git('rev-parse', head + '^{tree}').strip()}",
              f"- merge_base: {git('merge-base', base, head).strip()}"]
lines += ["", "## 2. ORDER FIELDS"]
for key in ("objective", "allowed_paths", "forbidden_paths", "required_cases", "verification", "evidence_to_post"):
    lines += [f"### {key}", json.dumps(order[key], ensure_ascii=False)]
fixed = "\n".join(lines) + "\n\n"

if head:
    changed = [p for p in git("diff", *DIFF, "--name-only", f"{base}...{head}").splitlines() if p]
    outside = [f"- `{p}`" for p in changed
               if not any(fnmatch.fnmatchcase(p, g) for g in order["allowed_paths"])
               or any(fnmatch.fnmatchcase(p, g) for g in order["forbidden_paths"])]
    fixed += "## 3. OUT OF SCOPE PATHS\n" + ("\n".join(outside) if outside else "none") + "\n\n"
    fixed += "## 4. NAME-STATUS AND STAT\n" + git("diff", *DIFF, "--name-status", f"{base}...{head}")
    fixed += git("diff", *DIFF, "--stat", f"{base}...{head}") + "\n"


def excerpt(ref):
    path, span = ref["file"], ref["lines"]
    title = f"### {path} {span}\n"
    try:
        text = git("show", f"{base}:{path}").splitlines()
    except subprocess.CalledProcessError:
        return title + f"MISSING at {base[:12]}: {path}\n"
    first, _, last = span.partition("-")
    first, last = int(first), int(last or first)
    if first < 1 or last < first or last > len(text):
        return title + f"MISSING at {base[:12]}: {path} {span} (file has {len(text)} lines)\n"
    return title + "\n".join(f"{n}: {text[n - 1]}" for n in range(first, last + 1)) + "\n"


body = "## 5. SOURCE EXCERPTS\n"
for ref in order["source_refs"]:
    part = excerpt(ref)
    if len((fixed + body + part).encode("utf-8")) > cap:
        body += f"### {ref['file']} {ref['lines']}\nTRIMMED to fit {cap} bytes: git show {base[:12]}:{ref['file']}\n"
        continue
    body += part
document = fixed + body
if len(document.encode("utf-8")) > cap:
    document = document.encode("utf-8")[:cap].decode("utf-8", "ignore") + "\n[TRUNCATED]\n"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(document, encoding="utf-8")
print(out_path)
PY
