# The seat model

A *seat* is a place work is done from: one tool, one kind of model, one set of branches,
one worktree. Seats are how several AI coding agents share one codebase without stepping
on each other or on the human who owns it.

| Seat | Who sits there | Writes | Never |
|---|---|---|---|
| Owner | the human | decisions, merges, releases | delegates a merge |
| Orchestrator | one Claude Code session on the strongest model | work orders, docs | writes code |
| Challenger | a second orchestration opinion (Claude or Codex) | findings | edits anything |
| Claude dev | Claude Code workers on pinned models | code, tests, migrations (in turn) | edits a Codex branch |
| Codex dev | OpenAI Codex workers on pinned models | code, tests, migrations (in turn) | edits a Claude branch |
| Codex tooling | Codex, for CI and launch tooling | its own scripts | touches the domain core |

## Rules that make it work

1. **One receiver.** Every owner message goes to the orchestrator, which keeps one ledger
   of decisions (timestamp plus the owner's words, verbatim). Two sessions asking the owner
   the same question get two answers; one receiver gets one.
2. **Work orders, not chat.** Delegation happens through a JSON work order
   (`kit/orders/work-order.schema.json`): seat, pinned model, base commit, allowed and
   forbidden paths, required positive and negative cases, the evidence to post.
3. **Disjoint lanes.** Two open orders never share a path, and only one database migration
   is in flight repository-wide. `validate-work-order.sh --all` refuses the conflict
   mechanically.
4. **Opposite-seat review.** A Claude head is reviewed by Codex and a Codex head by Claude,
   on the exact head, posted on the pull request. Different models miss different things.
5. **Pinned models.** Every agent definition and every dispatch names its model. An agent
   that silently inherits the orchestrator's model multiplies cost for no gain.
   Risk decides the tier: permissions, money rules, migrations, concurrency, guards and the
   gate get the strongest reviewer; ordinary work gets the standard tier.
6. **The owner merges.** No agent merges into or pushes a protected branch. The command
   guard enforces it locally, because a private repository on a free plan has no
   server-side branch protection.
7. **Evidence, not assertions.** A result is reported with what proves it: the gate's
   `VERIFY:` and `exit=` lines from a log with a known sha256, the head SHA a review is
   bound to, the pid whose working directory was checked. Each claim is marked observed or
   inferred.
8. **Ask when unclear.** When a rule is ambiguous, the agent stops and the question goes to
   the owner as a short decision block. A guess that becomes policy is the failure mode.

## One contract, two seats

The Claude agent definitions in `.claude/agents/*.md` are the source of truth.
`sync-codex-agents.py --write` renders the Codex role contracts in `.codex/agents/*.toml`
(model mapped per tier, sandbox read-only unless the agent writes), and
`sync-codex-agents.py --check` fails the gate on any drift, any unclassified agent, or any
Claude-only phrase leaking into a Codex contract. The manifest records why an agent stays
Claude-only.

## Agents and commands shipped here

- Agents: `orchestrator`, `challenger`, `worker`, `reviewer`, `git-manager`,
  `docs-auditor`, `qa` (in `.claude/agents/`).
- Commands: `/verify`, `/land`, and the role charters `/role-orchestrator`,
  `/role-worker`, `/role-docs`, `/role-reviewer` (in `.claude/commands/`). Each charter's
  first instruction claims the role, which unlocks the role guard for that session.

They live at the repository root (not under `kit/seats/`) so Claude Code picks them up
when the repository is opened; copy them into your own project's `.claude/`.
