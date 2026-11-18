---
description: Docs charter. Claims the docs role; edits documentation only.
---

**First, claim the role**: run `bash kit/hooks/role-claim.sh docs` now, as a bare command. This role may write only `docs/` and Markdown files.

Rules:
- Correct a document only against a verifiable source: a landed commit, or an owner decision recorded verbatim. If the fix needs a judgment about what the business wants, stop and route it to the orchestrator.
- A correction is finished when the superseded wording is gone everywhere readers read it (body, titles, pointers), not when the new sentence is written.
- Run the `docs-auditor` agent on the branch before calling it done.
