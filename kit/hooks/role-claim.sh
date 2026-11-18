#!/usr/bin/env bash
# role-claim.sh: claim a role for this Claude Code session.
#
# The claim itself is written by the PreToolUse role guard (role-guard.sh), which sees
# this exact command BEFORE it runs and records "<role> <timestamp>" under the session id
# the harness put in the hook payload. A plain shell therefore cannot forge a claim for
# another session. This script only validates the argument and says what happened, so a
# charter can run it as its first instruction:
#
#     bash kit/hooks/role-claim.sh worker
#
# It must be that bare command: no cd, no &&, no pipes. Roles come from role-scopes.conf.
set -u
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SCOPES="${ADK_ROLE_SCOPES:-$HERE/role-scopes.conf}"
ROLES="$(sed -e 's/#.*//' "$SCOPES" | awk 'NF { print $1 }' | tr '\n' ' ')"
role="${1:-}"
case " $ROLES " in
  *" $role "*) ;;
  *) echo "usage: bash kit/hooks/role-claim.sh <role>   (one of: $ROLES)" >&2; exit 1 ;;
esac
echo "role claimed: $role. The role guard recorded it for this session if this shell runs under Claude Code hooks."
echo "Outside a hooked session nothing was recorded: the guard trusts only its own payload."
