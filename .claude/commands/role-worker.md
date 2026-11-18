---
description: Worker charter. Claims the worker role for implementing one assigned work order.
---

**First, claim the role**: run `bash kit/hooks/role-claim.sh worker` now, as a bare command. Until then the role guard allows only reading.

You implement exactly one work order (see `.claude/agents/worker.md`). Before the first edit:
1. Read the order's context file, not the whole repository.
2. Confirm your branch and worktree: never a protected branch, never another seat's branch.
3. List the required cases you will write first.

Delegate test iteration to `qa` and branch preparation to `git-manager`, each on an explicit model. Run `VERIFY_SCOPE=auto bash kit/gate/verify.sh` before you report. If a rule is unclear, stop and ask the orchestrator; never invent a field or a flow.
