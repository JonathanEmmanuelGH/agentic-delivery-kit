#!/usr/bin/env python3
"""Baseline secret scanner over the tracked files of a git repository.

Why a baseline and not a plain grep: real repositories carry known, harmless
matches (test fixtures, documentation). Flagging them on every run trains people
to ignore the output. The known set is recorded in a baseline and the scan
reports only what is NEW; a regression is what you want to hear about.

It never prints a secret: findings are reported by RULE, FILE, LINE and the
LENGTH of the match. The baseline is value-free too (rule, file, count), so it
cannot become an index of where the secrets are.

Usage (through secret-scan.sh):
  secret-scan.sh                    compare with the baseline (gate mode)
  secret-scan.sh --list             every finding, redacted, baseline included
  secret-scan.sh --self-test        prove each rule still matches its sample
  secret-scan.sh --update-baseline  re-bless the current state (review by name first)

Exit codes: 0 no new findings, 1 new findings or a tracked credential file, 2 usage.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard import path_reason  # noqa: E402  (same predicate as the hooks)

BASELINE = os.environ.get("ADK_SCAN_BASELINE", "kit/hooks/secret-scan-baseline.txt")

RULES = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("api-key-sk", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("assigned-secret", re.compile(
        r"(?i)\b(password|passwd|secret|api[_-]?key|token|access[_-]?key)\b\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']")),
    ("url-credentials", re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]{3,}@")),
]


def samples():
    """Positive and negative samples, assembled at runtime so this file holds none."""
    a = "A" * 16
    body = "x" * 40
    return {
        "private-key": ("-----BEGIN " + "RSA PRIVATE KEY-----", "-----BEGIN PUBLIC KEY-----"),
        "aws-access-key": ("id = AKIA" + a, "AKIA" + "a" * 16),
        "github-token": ("ghp" + "_" + body, "ghp_short"),
        "slack-token": ("xox" + "b-" + "1234567890-abcdef", "xoxz-1234567890"),
        "api-key-sk": ("sk" + "-" + "q" * 24, "sk-short"),
        "jwt": ("eyJ" + "h" * 12 + ".eyJ" + "p" * 12 + "." + "s" * 12, "eyJonly"),
        "assigned-secret": ("pass" + "word = '" + "hunter2hunter2" + "'", "password = os.environ['NAME']"),
        "url-credentials": ("postgres://user:" + "pw123" + "@db.example.invalid/x", "https://example.invalid/a@b"),
    }


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], stdout=subprocess.PIPE, check=True).stdout
    return [p.decode("utf-8", "replace") for p in out.split(b"\0") if p]


def scan():
    findings, credential_files = [], []
    for path in tracked_files():
        if path == BASELINE:
            continue
        reason = path_reason(path)
        if reason:
            credential_files.append((path, reason))
            continue
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        for lineno, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            for rule, rx in RULES:
                for m in rx.finditer(line):
                    findings.append((rule, path, lineno, len(m.group(0))))
    return findings, credential_files


def load_baseline():
    counts = Counter()
    if os.path.exists(BASELINE):
        with open(BASELINE, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if line:
                    rule, path, count = line.split("\t")
                    counts[(rule, path)] = int(count)
    return counts


def self_test():
    failures = 0
    table = samples()
    for rule, rx in RULES:
        good, bad = table[rule]
        if not rx.search(good):
            print(f"SELF-TEST FAIL: {rule} does not match its positive sample")
            failures += 1
        if rx.search(bad):
            print(f"SELF-TEST FAIL: {rule} matches its negative sample")
            failures += 1
    if set(table) != {r for r, _ in RULES}:
        print("SELF-TEST FAIL: every rule needs exactly one sample pair")
        failures += 1
    for name, want in ((".env", True), (".env.example", False), ("id_rsa", True), ("app.py", False)):
        if bool(path_reason(name)) != want:
            print(f"SELF-TEST FAIL: path predicate on {name}")
            failures += 1
    print(f"secret-scan self-test: {len(RULES)} rules, {failures} failures")
    return 1 if failures else 0


def main(argv):
    mode = argv[1] if len(argv) > 1 else "--check"
    if mode not in ("--check", "--list", "--self-test", "--update-baseline"):
        print(__doc__, file=sys.stderr)
        return 2
    if mode == "--self-test":
        return self_test()
    findings, credential_files = scan()
    for path, reason in credential_files:
        print(f"TRACKED CREDENTIAL FILE: {path} ({reason}): remove it from the index")
    current = Counter((rule, path) for rule, path, _, _ in findings)
    if mode == "--update-baseline":
        with open(BASELINE, "w", encoding="utf-8") as f:
            f.write("# rule<TAB>file<TAB>count. Value-free on purpose. Re-bless only after review by name.\n")
            for (rule, path), n in sorted(current.items()):
                f.write(f"{rule}\t{path}\t{n}\n")
        print(f"baseline updated: {len(current)} entries")
        return 1 if credential_files else 0
    baseline = load_baseline()
    new = 0
    for rule, path, lineno, length in findings:
        known = current[(rule, path)] <= baseline.get((rule, path), 0)
        if mode == "--list" or not known:
            print(f"{'known' if known else 'NEW'}: {rule} {path}:{lineno} [redacted, {length} chars]")
        new += 0 if known else 1
    print(f"secret-scan: {len(findings)} findings, {new} new, {len(credential_files)} tracked credential files")
    return 1 if new or credential_files else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
