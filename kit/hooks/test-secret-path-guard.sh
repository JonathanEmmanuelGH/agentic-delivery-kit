#!/usr/bin/env bash
# test-secret-path-guard.sh: offline harness for secret-path-guard.sh.
# The file tools (Read, Edit, Write, Grep, Glob, NotebookEdit) must never open a
# credential-shaped path, whatever role the session holds.
set -u
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
. "$HERE/harness-lib.sh"
GUARD="$HERE/secret-path-guard.sh"
HARNESS_TMP="$(mktemp -d)"
trap 'rm -rf "$HARNESS_TMP"' EXIT
CWD="$HARNESS_TMP/project"
mkdir -p "$CWD"

# t WANT TOOL JSON_INPUT
t() { payload "$2" "$3" "$CWD" | expect_rc "$1" "$2 $3" "$GUARD"; }

# --- allowed --------------------------------------------------------------------------
t 0 Read '{"file_path": "src/app.py"}'
t 0 Read '{"file_path": ".env.example"}'
t 0 Read '{"file_path": "docs/environment.md"}'
t 0 Read '{"file_path": "/home/someone/project/.venv/bin/activate"}'
t 0 Edit '{"file_path": "config/settings.py", "old_string": "a", "new_string": "b"}'
t 0 Write '{"file_path": "notes/keys-and-values.md", "content": "x"}'
t 0 Grep '{"pattern": "TOKEN", "path": "src"}'
t 0 Grep '{"pattern": "TOKEN", "glob": "*.py"}'
t 0 Glob '{"pattern": "**/*.py"}'
t 0 Glob '{"pattern": "**/*"}'
t 0 WebFetch '{"url": "https://example.invalid/.env"}'

# --- blocked: dotenv shapes ---------------------------------------------------------------
t 2 Read '{"file_path": ".env"}'
t 2 Read '{"file_path": "backend/.env"}'
t 2 Read '{"file_path": "/srv/app/.env.production"}'
t 2 Read '{"file_path": ".env.local"}'
t 2 Read '{"file_path": ".env-staging"}'
t 2 Read '{"file_path": ".env~"}'
t 2 Read '{"file_path": "deploy/prod.env"}'
t 2 Read '{"file_path": "BACKEND/.ENV"}'
t 2 Edit '{"file_path": ".env", "old_string": "a", "new_string": "b"}'
t 2 Write '{"file_path": "config/.env.test", "content": "x"}'
t 2 NotebookEdit '{"notebook_path": "secrets.env", "new_source": "x"}'

# --- blocked: keys and credential stores ------------------------------------------------------
t 2 Read '{"file_path": "certs/server.pem"}'
t 2 Read '{"file_path": "tls/private.key"}'
t 2 Read '{"file_path": "~/.ssh/id_rsa"}'
t 2 Read '{"file_path": "~/.ssh/config"}'
t 2 Read '{"file_path": "~/.aws/credentials"}'
t 2 Read '{"file_path": "~/.netrc"}'
t 2 Read '{"file_path": "~/.codex/auth.json"}'
t 2 Read '{"file_path": "credentials.json"}'
t 2 Read '{"file_path": "/proc/1234/environ"}'

# --- blocked: search tools aimed at secrets -------------------------------------------------
t 2 Grep '{"pattern": "TOKEN", "path": ".env"}'
t 2 Grep '{"pattern": "TOKEN", "glob": ".env*"}'
t 2 Grep '{"pattern": "BEGIN", "glob": "*.{pem,key}"}'
t 2 Glob '{"pattern": "**/.env*"}'
t 2 Glob '{"pattern": "*.pem", "path": "certs"}'
t 2 Glob '{"pattern": "**/id_rsa*"}'

# --- a configured secret directory ----------------------------------------------------------
export ADK_SECRET_DIRS="$HARNESS_TMP/vault"
t 2 Read "{\"file_path\": \"$HARNESS_TMP/vault/settings.json\"}"
t 0 Read "{\"file_path\": \"$HARNESS_TMP/vaulted/settings.json\"}"
unset ADK_SECRET_DIRS

# --- malformed payloads -----------------------------------------------------------------
printf 'garbage' | expect_rc 0 'non-JSON input is allowed (seatbelt)' "$GUARD"
printf '{"tool_name":"Read","tool_name":"Read","tool_input":{"file_path":".env"}}' | expect_rc 2 'duplicate key refused' "$GUARD"

summary "secret-path-guard"
