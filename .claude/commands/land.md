---
description: Prepare the current feature branch for the owner's merge (gate on the merge tree, reviews, READY bundle).
---

Delegate this to the `git-manager` agent on an explicit model (sonnet). Do not do it inline.

Phase 1 (git-manager): commit explicit paths, merge the integration branch into the feature branch, launch `kit/gate/verify.sh` detached on that exact merge tree in a clean checkout, and return the launch record (log path, gate pid, start epoch, merge commit, tree).

Wait (this session): `bash kit/gate/gate-wait.sh <log> --pid <pid> --after <start>` as one background command.

Phase 2 (a fresh git-manager): with the gate-wait block, the opposite-seat review link for the same head, and the docs audit, assemble the READY bundle and post it on the pull request.

Then tell the owner, once: the pull request, the verdict pair (`VERIFY: PASS`, `exit=0`), the review verdict, and any open decision. The owner merges. If the head or the integration branch moves before the merge, the bundle is stale: recompute the merge tree and gate again unless the tree is identical.
