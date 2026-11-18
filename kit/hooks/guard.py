#!/usr/bin/env python3
"""Guard core for the Claude Code PreToolUse hooks in this kit.

One file, three modes (argv[1]):

  command  the command guard for the Bash tool (protected branches, force-push,
           dangerous git verbs, environment dumps, credential files)
  role     the role guard (nothing but reading until the session claims a role)
  path     the secret-path guard for file tools (Read, Edit, Write, Grep, Glob)

Hook contract (Claude Code): the tool call arrives as JSON on stdin; exit 0
allows it, exit 2 blocks it and the text on stderr is shown to the agent.

Design rules, learned the hard way:

* Match the ACTION, not the name of a wrapper. A command line is split into
  segments on ; && || | & and newlines, every segment is tokenized, and rules
  test tokens in command position. `git -C other add -A` is caught; reading
  `cat scripts/push-notes.md` is not.
* Fail closed on what cannot be classified: a `$VAR` in command position, an
  unknown git verb (it may be an alias for push), quoting that does not parse.
  Over-blocking is the safe direction; the agent is told to write the command
  to a file and run it by path only for quoting refusals.
* A claimed role widens what a session may DO, never what it may READ: the
  credential-path predicate is checked before any role logic.
* Input that is not JSON at all is allowed (a seatbelt, not a vault: a guard
  that wedges every session on a harness hiccup gets disabled). JSON that
  repeats a key or lacks required fields is refused.

What this cannot do, stated so nobody trusts it further than it goes: it sees
one command string, never the contents of a script it runs; a heredoc or
here-string fed to an interpreter is opaque; `grep -r` over a tree that holds a
dotenv file reads it; a process that already loaded secrets carries them in its
environment. The harnesses assert these residuals so a change is visible.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time

ALLOW, BLOCK = 0, 2
HERE = os.path.dirname(os.path.abspath(__file__))


class Refuse(Exception):
    """A payload that is JSON but not a well-formed tool call."""


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------

def _no_duplicate_keys(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise Refuse("payload repeats a JSON key")
    return dict(pairs)


def read_payload(raw: str):
    raw = raw.strip()
    if not raw:
        return None
    try:
        data = json.loads(raw, object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        raise Refuse("payload is not a JSON object")
    name = data.get("tool_name")
    if not isinstance(name, str) or not name.strip():
        raise Refuse("payload has no tool_name")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        raise Refuse("tool_input is not an object")
    return data


# ---------------------------------------------------------------------------
# Credential-shaped paths (shared by every mode)
# ---------------------------------------------------------------------------

SAFE_DOTENV = {".env.example", ".env.sample", ".env.template", ".env.dist"}
KEY_NAME_GLOBS = (
    "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.kdbx",
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
    ".netrc", "_netrc", ".pgpass", ".git-credentials", "credentials.json",
    ".npmrc", ".pypirc",
)
PATH_GLOBS = (
    "*/.ssh/*", "*/.aws/credentials", "*/.aws/config", "*/.docker/config.json",
    "*/.codex/auth.json", "*/.config/gh/hosts.yml", "*/.kube/config",
    "*/.gnupg/*", "/proc/*/environ",
)
REDIRECT_PREFIX = re.compile(r"^[0-9]*(?:&>>?|>>?\|?|<<?<?)&?")


def is_dotenv_name(name: str) -> bool:
    n = name.lower()
    if n in SAFE_DOTENV:
        return False
    return n == ".env" or n.startswith((".env.", ".env-", ".env~")) or n.endswith(".env")


def secret_dirs():
    out = []
    for d in os.environ.get("ADK_GUARDED_DIRS", "").split(":"):
        d = d.strip()
        if d:
            out.append(os.path.normpath(os.path.expanduser(d)))
    return out


def normalize_path(raw: str, cwd: str | None = None) -> str:
    p = raw.strip()
    m = REDIRECT_PREFIX.match(p)
    if m:
        p = p[m.end():]
    if p.startswith("--") and "=" in p:
        p = p.split("=", 1)[1]
    if p.startswith("@"):
        p = p[1:]
    if p.startswith("file://"):
        p = p[len("file://"):]
    p = p.strip("'\"")
    if not p or p.startswith("-"):
        return ""
    p = os.path.expanduser(p)
    if cwd and not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.normpath(p)


def path_reason(raw: str, cwd: str | None = None):
    p = normalize_path(raw, cwd)
    if not p:
        return None
    name = os.path.basename(p)
    lname = name.lower()
    if is_dotenv_name(lname):
        return f"dotenv file ({name})"
    for g in KEY_NAME_GLOBS:
        if fnmatch.fnmatchcase(lname, g):
            return f"credential-shaped file ({name})"
    probe = p.lower() if p.startswith("/") else "/" + p.lower()
    for g in PATH_GLOBS:
        if fnmatch.fnmatchcase(probe, g):
            return f"credential store ({g})"
    for d in secret_dirs():
        if p == d or p.startswith(d.rstrip("/") + "/"):
            return f"configured secret directory ({d})"
    return None


def _expand_braces(pattern: str, limit: int = 64):
    m = re.search(r"\{([^{}]*)\}", pattern)
    if not m or limit <= 0:
        return [pattern]
    out = []
    for alt in m.group(1).split(","):
        out.extend(_expand_braces(pattern[:m.start()] + alt + pattern[m.end():], limit - 1))
    return out


def pattern_reason(pattern: str, cwd: str | None = None):
    """Could this glob pattern match a credential-shaped path?"""
    if not pattern:
        return None
    for alt in _expand_braces(pattern):
        for fill in ("", "x", ".x"):
            sample = re.sub(r"\*\*|\*|\?|\[[^]]*\]", fill, alt)
            r = path_reason(sample, cwd)
            if r:
                return f"{r} via pattern {pattern}"
    return None


# ---------------------------------------------------------------------------
# Shell segmentation
# ---------------------------------------------------------------------------

def _balanced(cmd: str, start: int):
    """Body of a $( ... ) starting after the opening paren; returns (body, end)."""
    depth, i, q = 1, start, None
    while i < len(cmd):
        c = cmd[i]
        if q:
            if c == "\\" and q == '"':
                i += 2
                continue
            if c == q:
                q = None
        elif c in "'\"":
            q = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return cmd[start:i], i + 1
        i += 1
    return cmd[start:], len(cmd)


def split_command(cmd: str):
    """Split a command line into simple-command segments.

    Returns (segments, substitutions). Substitution bodies ($(...), backticks,
    <(...), >(...)) are returned separately and analysed as commands of their own.
    """
    segs, subs, cur = [], [], []
    i, n, q = 0, len(cmd), None

    def flush():
        s = "".join(cur).strip()
        if s:
            segs.append(s)
        cur.clear()

    while i < n:
        c = cmd[i]
        if q == "'":
            cur.append(c)
            if c == "'":
                q = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            cur.append(cmd[i:i + 2])
            i += 2
            continue
        if c == "$" and cmd.startswith("$(", i):
            body, j = _balanced(cmd, i + 2)
            subs.append(body)
            cur.append(cmd[i:j])
            i = j
            continue
        if c == "$" and cmd.startswith("${", i):
            j = cmd.find("}", i)
            j = n if j < 0 else j + 1
            cur.append(cmd[i:j])
            i = j
            continue
        if c == "`":
            j = cmd.find("`", i + 1)
            j = n if j < 0 else j
            subs.append(cmd[i + 1:j])
            cur.append(cmd[i:j + 1])
            i = j + 1
            continue
        if q == '"':
            cur.append(c)
            if c == '"':
                q = None
            i += 1
            continue
        if c in "'\"":
            q = c
            cur.append(c)
            i += 1
            continue
        if c in "<>" and cmd.startswith("(", i + 1):
            body, j = _balanced(cmd, i + 2)
            subs.append(body)
            cur.append(" ")
            i = j
            continue
        if c == "#" and (not cur or cur[-1][-1:].isspace()):
            j = cmd.find("\n", i)
            i = n if j < 0 else j
            continue
        if c in ";|&\n()":
            prev = cur[-1][-1:] if cur else ""
            if c == "&" and ((prev and prev in "<>") or cmd.startswith(">", i + 1)):
                cur.append(c)
                i += 1
                continue
            if c == "|" and prev == ">":
                cur.append(c)
                i += 1
                continue
            flush()
            i += 1
            continue
        cur.append(c)
        i += 1
    flush()
    return segs, subs


def tokens_of(segment: str):
    try:
        return shlex.split(segment, comments=False, posix=True)
    except ValueError:
        return None


KEYWORDS = {"!", "{", "}", "then", "do", "else", "elif", "if", "while", "until",
            "fi", "done", "esac", "time"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def strip_prefix(toks):
    toks = list(toks)
    while toks and (toks[0] in KEYWORDS or ASSIGNMENT.match(toks[0])):
        toks.pop(0)
    return toks


SIMPLE_WRAPPERS = {"nohup", "builtin", "exec", "setsid", "stdbuf", "nice", "ionice", "unbuffer"}


def unwrap(toks):
    """Peel wrappers (sudo, env, nohup, timeout, xargs, command) so rules see the
    real program. Returns (tokens, env_dump)."""
    while toks:
        w = os.path.basename(toks[0])
        if w in ("sudo", "doas"):
            toks = toks[1:]
            while toks and toks[0].startswith("-"):
                opt = toks.pop(0)
                if opt in ("-u", "-g", "-C", "-D", "-h", "-p", "-U", "-r", "-t") and toks:
                    toks.pop(0)
        elif w == "env":
            toks = toks[1:]
            while toks and (toks[0].startswith("-") or ASSIGNMENT.match(toks[0])):
                opt = toks.pop(0)
                if opt in ("-S", "--split-string") and toks:
                    inner = tokens_of(toks.pop(0)) or []
                    toks = inner + toks
                elif opt in ("-u", "--unset", "-C", "--chdir") and toks:
                    toks.pop(0)
            if not toks:
                return [], True
        elif w == "command":
            toks = toks[1:]
            while toks and toks[0].startswith("-"):
                if toks.pop(0) in ("-v", "-V"):
                    return [], False
        elif w == "timeout":
            toks = toks[1:]
            while toks and toks[0].startswith("-"):
                if toks.pop(0) in ("-s", "-k", "--signal", "--kill-after") and toks:
                    toks.pop(0)
            if toks:
                toks.pop(0)
        elif w == "xargs":
            toks = toks[1:]
            while toks and toks[0].startswith("-"):
                if toks.pop(0) in ("-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a") and toks:
                    toks.pop(0)
        elif w in SIMPLE_WRAPPERS:
            toks = toks[1:]
            while toks and toks[0].startswith("-"):
                if toks.pop(0) in ("-n", "-c") and w in ("nice", "ionice") and toks:
                    toks.pop(0)
        else:
            break
    return toks, False


# ---------------------------------------------------------------------------
# Command rules
# ---------------------------------------------------------------------------

def protected_branches():
    return set(os.environ.get("ADK_PROTECTED_BRANCHES", "main master develop").split())


EXISTENCE_ONLY = {"test", "[", "[[", "ls", "stat", "rm", "shred", "unlink"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "php"}
PRINTERS = {"echo", "printf", "print"}
SECRET_VAR = re.compile(r"(TOKEN|SECRET|PASSW(OR)?D|API_?KEY|PRIVATE_?KEY|CREDENTIAL|ACCESS_?KEY)", re.I)
EMBEDDED_SECRET = re.compile(
    r"(?<![\w.-])(\.env(?:\.[\w-]+)?|[\w-]+\.pem|id_rsa\w*|id_ed25519\w*|[\w-]+\.key)(?![\w-])")

GIT_VERBS = {
    "add", "am", "apply", "archive", "bisect", "blame", "branch", "bundle", "cat-file",
    "check-ignore", "check-ref-format", "checkout", "cherry", "cherry-pick", "clean",
    "clone", "commit", "commit-tree", "config", "count-objects", "describe", "diff",
    "diff-index", "diff-tree", "fetch", "for-each-ref", "format-patch", "fsck", "gc",
    "grep", "hash-object", "help", "init", "log", "ls-files", "ls-remote", "ls-tree",
    "maintenance", "merge", "merge-base", "mktree", "mv", "name-rev", "notes", "pull",
    "push", "range-diff", "read-tree", "rebase", "reflog", "remote", "reset", "restore",
    "rev-list", "rev-parse", "revert", "rm", "shortlog", "show", "show-ref",
    "sparse-checkout", "stash", "status", "submodule", "switch", "symbolic-ref", "tag",
    "update-index", "update-ref", "var", "verify-commit", "verify-tag", "version",
    "whatchanged", "worktree", "write-tree",
}
GIT_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
INTEGRATING = {"commit", "merge", "pull", "rebase", "cherry-pick", "revert", "am", "reset"}


def current_branch(cwd):
    if not cwd or not os.path.isdir(cwd):
        return None
    try:
        r = subprocess.run(["git", "-C", cwd, "symbolic-ref", "--quiet", "--short", "HEAD"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
                           text=True)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def git_parse(toks, cwd):
    i, gcwd = 1, cwd
    while i < len(toks) and toks[i].startswith("-"):
        o = toks[i]
        if o in GIT_OPTS_WITH_ARG:
            if i + 1 >= len(toks):
                return None, [], gcwd, "dangling git option"
            v = toks[i + 1]
            if o == "-C":
                gcwd = os.path.normpath(os.path.join(gcwd or "", os.path.expanduser(v))) if gcwd or os.path.isabs(v) else None
            if o in ("-c", "--config-env") and v.lower().startswith("alias."):
                return None, [], gcwd, "a git alias defined inline hides the real verb"
            i += 2
        else:
            i += 1
    if i >= len(toks):
        return None, [], gcwd, None
    return toks[i], toks[i + 1:], gcwd, None


def _positionals(args, with_arg=()):
    pos, i = [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            break
        if a.startswith("-"):
            if a in with_arg:
                i += 1
        else:
            pos.append(a)
        i += 1
    return pos


def push_rules(args, gcwd):
    out, pos, i = [], [], 0
    prot = protected_branches()
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if name in ("--force", "--force-with-lease", "--force-if-includes"):
                out.append("force-push is never allowed")
            elif name in ("--mirror", "--all", "--branches"):
                out.append(f"git push {name} pushes every branch, protected ones included")
            elif name in ("--delete", "--prune"):
                out.append(f"git push {name} deletes remote refs")
            elif name in ("--repo", "--push-option", "--receive-pack", "--exec") and "=" not in a:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            if "f" in a[1:]:
                out.append("force-push is never allowed")
            if "d" in a[1:]:
                out.append("git push -d deletes remote refs")
            if a == "-o":
                i += 1
        else:
            pos.append(a)
        i += 1
    refspecs = pos[1:]
    branch = None
    for r in refspecs:
        if r.startswith("+"):
            out.append("a +refspec is a force-push")
        src, sep, dst = r.lstrip("+").partition(":")
        if sep and not src:
            out.append(f"the refspec {r} deletes a remote branch")
        target = (dst if sep else src).removeprefix("refs/heads/")
        if target == "HEAD":
            branch = branch or current_branch(gcwd)
            target = branch or ""
        if target in prot:
            out.append(f"push to the protected branch {target}: only the owner's merge moves it")
    if not refspecs:
        branch = current_branch(gcwd)
        if branch is None:
            out.append("cannot tell which branch a bare git push would publish; name the branch")
        elif branch in prot:
            out.append(f"bare git push from the protected branch {branch}")
    return out


def git_rules(toks, cwd):
    verb, args, gcwd, err = git_parse(toks, cwd)
    if err:
        return [err]
    if verb is None:
        return []
    prot = protected_branches()
    out = []
    if verb not in GIT_VERBS:
        return [f"unknown git verb or alias '{verb}': this guard only allows verbs it can classify"]
    if verb == "push":
        out += push_rules(args, gcwd)
    if verb == "add":
        for a in args:
            if a in (".", "-A", "--all", "-u", "--update", ":/", "*", "--no-ignore-removal") or (
                    a.startswith("-") and not a.startswith("--") and ("A" in a or "u" in a)):
                out.append(f"blind staging (git add {a}): stage explicit paths")
                break
    if verb == "commit":
        skip = False
        for a in args:
            if skip:
                skip = False
                continue
            if a in ("-m", "-F", "-C", "-c", "--message", "--file"):
                skip = True
                continue
            if a == "--all" or (a.startswith("-") and not a.startswith("--") and "a" in a[1:]):
                out.append("git commit -a stages blindly: stage explicit paths")
                break
    if verb in INTEGRATING:
        fast_forward_sync = verb in ("merge", "pull") and "--ff-only" in args
        branch = current_branch(gcwd)
        if branch in prot and not fast_forward_sync:
            out.append(f"git {verb} on the protected branch {branch}: work on a feature branch; the owner merges")
    if verb == "reset" and "--hard" in args:
        out.append("git reset --hard discards work: use git stash or a new branch")
    if verb == "clean" and any(a == "--force" or (a.startswith("-") and not a.startswith("--") and "f" in a) for a in args):
        out.append("git clean -f deletes untracked files")
    if verb in ("checkout", "switch"):
        # `git checkout main -- file` restores a file from main; it does not switch.
        if "--" not in args and any(p in prot for p in _positionals(args)):
            out.append(f"git {verb} of a protected branch: the owner's merge is the only thing that moves it")
        tail = args[args.index("--") + 1:] if "--" in args else []
        if verb == "checkout" and ("." in tail or args == ["."]):
            out.append("git checkout . discards every uncommitted change")
    if verb == "restore" and "." in args and "--staged" not in args:
        out.append("git restore . discards every uncommitted change")
    if verb == "branch":
        destructive = {"-D", "-d", "--delete", "-m", "-M", "--move", "-f", "--force", "-c", "-C", "--copy"}
        if any(a in destructive for a in args) and any(p in prot for p in _positionals(args)):
            out.append("deleting, moving or forcing a protected branch")
    if verb in ("update-ref", "symbolic-ref"):
        if any(a.removeprefix("refs/heads/") in prot and a.startswith("refs/heads/") for a in args):
            out.append(f"git {verb} on a protected ref")
    if verb == "config" and any(a.lower().startswith("alias.") for a in args) and len(_positionals(args)) >= 2:
        out.append("defining a git alias hides the verb from this guard")
    return out


def gh_rules(toks):
    args = toks[1:]
    if args[:2] == ["pr", "merge"]:
        return ["gh pr merge: only the owner merges"]
    if args[:2] == ["repo", "delete"]:
        return ["gh repo delete is an owner decision"]
    if args[:2] == ["repo", "edit"] and any(a.startswith("--visibility") for a in args):
        return ["changing repository visibility is an owner decision"]
    if args[:2] == ["repo", "create"] and "--public" in args:
        return ["creating a public repository is an owner decision"]
    if args[:1] == ["api"]:
        method, writes, path, fields = "GET", False, "", []
        i = 1
        while i < len(args):
            a = args[i]
            if a in ("-X", "--method") and i + 1 < len(args):
                method = args[i + 1].upper()
                i += 2
                continue
            if a.startswith("--method="):
                method = a.split("=", 1)[1].upper()
            elif a in ("-f", "-F", "--field", "--raw-field", "--input") and i + 1 < len(args):
                writes = True
                fields.append(args[i + 1])
                i += 2
                continue
            elif not a.startswith("-") and not path:
                path = a
            i += 1
        if writes and method == "GET":
            method = "POST"
        if method != "GET":
            if re.search(r"(git/refs|/merges\b|/pulls/[0-9]+/merge|/branches/[^/]+/protection|/rulesets)", path):
                return [f"gh api {method} {path}: refs, merges and protection are owner-only"]
            if any(f.split("=", 1)[0] in ("private", "visibility") for f in fields):
                return ["changing repository visibility is an owner decision"]
    return []


def secret_rules(prog, toks, cwd):
    if prog in EXISTENCE_ONLY:
        return []
    if prog == "git":
        verb, _, _, _ = git_parse(toks, cwd)
        if verb in ("check-ignore", "rm", "ls-files"):
            return []
    out = []
    skip = False
    for t in toks[1:]:
        if skip:
            skip = False
            continue
        if prog == "git" and t in ("-m", "--message"):
            skip = True
            continue
        r = path_reason(t, cwd)
        if r:
            out.append(f"{prog} would open a {r}: existence checks only (test -f, ls, stat, git check-ignore)")
    if prog in INTERPRETERS:
        for t in toks[1:]:
            for m in EMBEDDED_SECRET.finditer(t):
                if m.group(1).lower() not in SAFE_DOTENV:
                    out.append(f"{prog} code names a credential-shaped file ({m.group(1)})")
    if prog in PRINTERS:
        for t in toks[1:]:
            for var in re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", t):
                if SECRET_VAR.search(var):
                    out.append(f"printing ${var} would expose a secret; check presence instead: "
                               f"[ -n \"${var}\" ] && echo set")
    return out


def env_dump_rules(prog, toks):
    args = toks[1:]
    if prog == "printenv":
        return ["printenv prints environment values; check one variable by presence instead"]
    if prog == "set" and not args:
        return ["a bare set prints every variable with its value"]
    if prog in ("declare", "typeset", "export", "readonly"):
        names = [a for a in args if not a.startswith(("-", "+"))]
        if not names or any(a.startswith("-") and "p" in a[1:] for a in args):
            return [f"{prog} without a NAME (or with -p) prints variables with their values"]
    return []


def analyze(cmd: str, cwd: str | None, depth: int = 0):
    if depth > 5:
        return ["command nests too deeply to classify"]
    reasons = []
    segs, subs = split_command(cmd)
    for body in subs:
        reasons += analyze(body, cwd, depth + 1)
    for seg in segs:
        toks = tokens_of(seg)
        if toks is None:
            reasons.append("quoting this guard cannot parse (QUOTING): write the command to a file and run it by path")
            continue
        toks = strip_prefix(toks)
        toks, dump = unwrap(toks)
        if dump:
            reasons.append("a bare env prints every variable with its value")
            continue
        if not toks:
            continue
        word = toks[0]
        if word.startswith("$") or "`" in word or "$(" in word:
            reasons.append("the command word cannot be resolved before it runs ($VAR or a substitution in command position)")
            continue
        prog = os.path.basename(word)
        if prog == "cd":
            target = toks[1] if len(toks) > 1 else os.path.expanduser("~")
            if "$" in target or target == "-":
                cwd = None
            else:
                target = os.path.expanduser(target)
                cwd = os.path.normpath(os.path.join(cwd or "", target)) if (cwd or os.path.isabs(target)) else None
            continue
        reasons += secret_rules(prog, toks, cwd)
        reasons += env_dump_rules(prog, toks)
        if prog in SHELLS:
            for k, t in enumerate(toks[1:], start=1):
                if t.startswith("-") and not t.startswith("--") and "c" in t[1:]:
                    if k + 1 < len(toks):
                        reasons += analyze(toks[k + 1], cwd, depth + 1)
                    break
        if prog == "eval":
            reasons += analyze(" ".join(toks[1:]), cwd, depth + 1)
        if prog == "git":
            reasons += git_rules(toks, cwd)
        if prog == "gh":
            reasons += gh_rules(toks)
    return reasons


# ---------------------------------------------------------------------------
# Read-only classification (role guard, before a role is claimed)
# ---------------------------------------------------------------------------

READONLY_PROGS = {
    "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "pwd", "echo",
    "which", "type", "file", "stat", "du", "df", "tree", "diff", "cmp", "sort", "uniq",
    "cut", "tr", "date", "whoami", "id", "uname", "basename", "dirname", "realpath",
    "readlink", "test", "[", "true", "false", "jq", "column", "nl", "find", "git",
    "md5sum", "sha256sum", "comm", "paste", "fold", "od",
}
READONLY_GIT = {"status", "log", "diff", "show", "rev-parse", "ls-files", "ls-tree",
                "cat-file", "merge-base", "blame", "shortlog", "describe", "for-each-ref",
                "rev-list", "show-ref", "check-ignore", "grep"}
FIND_WRITES = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}


def is_read_only(cmd: str) -> bool:
    if "$" in cmd or "`" in cmd:
        return False
    stripped = re.sub(r"[0-9]?>\s*/dev/null|2>&1", "", cmd)
    if ">" in stripped or "<(" in stripped:
        return False
    segs, subs = split_command(cmd)
    if subs or not segs:
        return False
    for seg in segs:
        toks = tokens_of(seg)
        if not toks or ASSIGNMENT.match(toks[0]):
            return False
        toks = [t for t in toks if not re.fullmatch(r"[0-9]?>/dev/null|2>&1|>|/dev/null", t)]
        prog = toks[0]
        if prog not in READONLY_PROGS:
            return False
        if prog == "find" and any(t in FIND_WRITES for t in toks):
            return False
        if prog == "sort" and any(t == "-o" or t.startswith("--output") for t in toks):
            return False
        if prog == "git":
            verb, args, _, err = git_parse(toks, None)
            if err or verb is None:
                return False
            if verb in ("branch", "tag", "remote"):
                if any(not a.startswith("-") or a not in ("-a", "-r", "-v", "-vv", "--list", "-l") for a in args):
                    return False
            elif verb == "config":
                if not args or args[0] not in ("--get", "--get-all", "--list", "-l"):
                    return False
            elif verb not in READONLY_GIT:
                return False
    return True


# ---------------------------------------------------------------------------
# Role markers
# ---------------------------------------------------------------------------

SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
CLAIM = re.compile(r"^bash\s+(\S*kit/hooks/role-claim\.sh)\s+([a-z][a-z-]{0,31})\s*$")


def load_scopes():
    path = os.environ.get("ADK_ROLE_SCOPES") or os.path.join(HERE, "role-scopes.conf")
    scopes = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].split()
            if line:
                scopes[line[0]] = line[1:]
    return scopes


def role_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.environ.get("ADK_ROLE_DIR") or os.path.join(base, "agentic-kit", "roles")


def read_marker(session_id, roles):
    path = os.path.join(role_dir(), session_id)
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or (st.st_mode & 0o777) != 0o600:
        return None
    ttl = int(os.environ.get("ADK_ROLE_TTL_MIN", "1440")) * 60
    if time.time() - st.st_mtime > ttl:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            role = f.read().split()[0]
    except (OSError, IndexError):
        return None
    return role if role in roles else None


def write_marker(session_id, role):
    d = role_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    st = os.lstat(d)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise Refuse(f"role directory {d} is not a directory owned by this user")
    tmp = os.path.join(d, f".{session_id}.{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"{role} {int(time.time())}\n")
    os.replace(tmp, os.path.join(d, session_id))


def project_root(payload):
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    try:
        r = subprocess.run(["git", "-C", root, "rev-parse", "--show-toplevel"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return root


def in_scope(path, globs, root):
    if not path:
        return False
    absolute = os.path.normpath(os.path.join(root, path))
    rel = os.path.relpath(absolute, root)
    probe = absolute if rel.startswith("..") else rel
    return any(fnmatch.fnmatchcase(probe, g) for g in globs)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

READ_TOOLS = {"read", "grep", "glob", "ls", "websearch", "webfetch", "todowrite", "task",
              "agent", "skill", "toolsearch", "askuserquestion", "exitplanmode", "bashoutput"}
EDIT_TOOLS = {"edit", "write", "multiedit", "notebookedit"}
READ_MCP_LEAF = re.compile(r"^(get|list|read|search|fetch|query|describe)")


def block(guard, reason):
    print(f"BLOCKED by {guard}: {reason}", file=sys.stderr)
    return BLOCK


def mode_command(payload):
    if payload["tool_name"].strip().lower() != "bash":
        return ALLOW
    cmd = payload["tool_input"].get("command")
    if not isinstance(cmd, str):
        raise Refuse("Bash call without a command string")
    reasons = list(dict.fromkeys(analyze(cmd, payload.get("cwd"))))
    if reasons:
        hint = "" if any("QUOTING" in r for r in reasons) else " Stop and report; do not work around it."
        return block("command-guard", "; ".join(reasons) + "." + hint)
    return ALLOW


def file_reasons(tool, ti, cwd):
    reasons = []
    if tool in EDIT_TOOLS or tool == "read":
        for key in ("file_path", "notebook_path"):
            if isinstance(ti.get(key), str):
                r = path_reason(ti[key], cwd)
                if r:
                    reasons.append(r)
    elif tool == "grep":
        if isinstance(ti.get("path"), str):
            r = path_reason(ti["path"], cwd)
            reasons += [r] if r else []
        if isinstance(ti.get("glob"), str):
            r = pattern_reason(ti["glob"], cwd)
            reasons += [r] if r else []
    elif tool == "glob":
        pattern = ti.get("pattern") if isinstance(ti.get("pattern"), str) else ""
        base = ti.get("path") if isinstance(ti.get("path"), str) else ""
        r = pattern_reason(os.path.join(base, pattern) if base else pattern, cwd)
        reasons += [r] if r else []
    return reasons


def mode_path(payload):
    tool = payload["tool_name"].strip().lower()
    reasons = file_reasons(tool, payload["tool_input"], payload.get("cwd"))
    if reasons:
        return block("secret-path-guard", "; ".join(reasons)
                     + ". Never open credential files with any tool; existence checks only.")
    return ALLOW


def mode_role(payload):
    tool = payload["tool_name"].strip().lower()
    ti = payload["tool_input"]
    sid = payload.get("session_id")
    if not isinstance(sid, str) or not SESSION_ID.match(sid):
        raise Refuse("payload has no usable session_id")
    secret = file_reasons(tool, ti, payload.get("cwd"))
    if secret:
        return block("role-guard", "; ".join(secret) + " (no role unlocks credential files)")
    scopes = load_scopes()
    if tool == "bash":
        cmd = ti.get("command")
        if not isinstance(cmd, str):
            raise Refuse("Bash call without a command string")
        m = CLAIM.match(cmd.strip())
        if m and not re.search(r"[;&|<>$`()\n]", cmd):
            if m.group(2) in scopes:
                write_marker(sid, m.group(2))
            return ALLOW
    role = read_marker(sid, scopes)
    if tool in READ_TOOLS:
        return ALLOW
    if tool.startswith("mcp__") and READ_MCP_LEAF.match(tool.rsplit("__", 1)[-1]):
        return ALLOW
    if tool == "bash" and is_read_only(ti["command"]):
        return ALLOW
    if role is None:
        return block("role-guard", "no role claimed for this session. Run your charter first "
                     "(/role-worker, /role-orchestrator, /role-docs, /role-reviewer); it claims the role with "
                     "`bash kit/hooks/role-claim.sh <role>` as a bare command. Until then only reading is allowed.")
    globs = scopes.get(role, [])
    if tool in EDIT_TOOLS:
        path = ti.get("file_path") or ti.get("notebook_path")
        if not in_scope(path if isinstance(path, str) else "", globs, project_root(payload)):
            return block("role-guard", f"role '{role}' may not write {path}; its scope is {' '.join(globs) or 'read-only'}")
        return ALLOW
    if not globs:
        return block("role-guard", f"role '{role}' is read-only")
    return ALLOW


MODES = {"command": mode_command, "path": mode_path, "role": mode_role}


def main(argv):
    if len(argv) != 2 or argv[1] not in MODES:
        print("usage: guard.py command|path|role < payload.json", file=sys.stderr)
        return BLOCK
    try:
        payload = read_payload(sys.stdin.read())
        if payload is None:
            return ALLOW
        return MODES[argv[1]](payload)
    except Refuse as e:
        return block(f"{argv[1]}-guard", str(e))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
