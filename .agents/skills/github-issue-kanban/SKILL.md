---
name: github-issue-kanban
description: Use GitHub Issues as the Comic Pile kanban and execution queue. Trigger whenever the user asks an agent to do the next task, pick the next issue, work from the backlog, update issue status, plan issue work, or keep GitHub work synchronized. Use this skill before editing code for any issue-driven task in this repository.
---

# GitHub issue workflow

Use GitHub Issues as the only backlog and status source of truth. Do not maintain
a parallel Markdown kanban. Local plan files are implementation references, not
a second status system.

## Select work

If the user assigned an issue or PR, verify that target and work on it. Otherwise,
use the current local-factory selection procedure from the Rotisserie
`local-factory-next-task` skill and
[docs/AUTONOMOUS_FACTORY_POLICY.md](../../../docs/AUTONOMOUS_FACTORY_POLICY.md).
The old `make next-task` / `make start-task` targets do not exist; do not invent
replacement flags or bypass the controller's ownership checks.

Before editing:

1. Read `AGENTS.md`, the selected issue/PR and
   [docs/ISSUE_EXECUTION_PROTOCOL.md](../../../docs/ISSUE_EXECUTION_PROTOCOL.md).
2. For factory work, read the autonomous policy, GitHub visibility contract and
   the latest canonical resume packet.
3. Confirm dependencies, manual-only holds, live leases and file ownership.
4. Preserve unrelated working-tree changes.

## Start work

Use the canonical claim marker and atomic label replacement defined by the
current factory policy. An issue or PR must have exactly one truthful stage and
one next-action owner; do not use add-only or sequential remove/add calls.

Implement only the authorized scope. If required work is outside it, record the
specific blocker in the existing issue/PR handoff. The Rust-cutover backlog
freeze prohibits new issues, sub-issues and work splits without an explicit
interactive owner instruction.

Issue work normally produces a ready-for-review PR. After local verification,
commit and push through the applicable delivery path. Follow the exact-head CI
and independent-review procedure in
[local-factory-session](https://github.com/JoshCLWren/rotisserie/blob/main/factory/.agents/skills/local-factory-session/SKILL.md).
Do not leave completed issue work only in a local working tree, and do not treat
a PR link with pending CI as ordinary completion.

For local factory delivery, continue through actual independent review, gated
merge, authorized deployment and real acceptance. Start an eligible local
reviewer instead of waiting for scheduled pickup; record actual identity and
exact-head evidence. Read only ACP checkpoints/model-selection metadata and final
reports/verdicts, never full logs or transcripts.

For any Python change, local verification must include `ruff check .` and
`ty check --error-on-warning` against the whole repository. `bash scripts/lint.sh`
is an additional syntax/ignore/frontend ESLint check and does not run that pair.
The former
`bash scripts/check-python-ci-lint.sh` target has been removed. Path-filtered
ruff or ty is not a valid CI substitute.

## Keep status synchronized

Use the lifecycle in [docs/ISSUE_EXECUTION_PROTOCOL.md](../../../docs/ISSUE_EXECUTION_PROTOCOL.md)
and the factory label state machine:

| State | Issue status / factory stage |
| --- | --- |
| Ready to implement | `ralph-status:pending` / unclaimed executable work |
| Actively editing | `ralph-status:in-progress` / `factory:building` |
| Checks running or complete | `ralph-status:validation` / `factory:ci` |
| Exact head needs review | `ralph-status:in-review` / `factory:review` |
| Actionable findings | `factory:changes-requested` |
| Every merge gate satisfied | `ralph-status:in-review` / `factory:ready` |
| Cannot proceed | `ralph-status:blocked` / `factory:blocked` |
| Verified complete | `ralph-status:done` after truthful closure |

Reconcile the complete label set atomically and preserve unrelated labels. When
blocked, leave the issue open and record the exact decision or external condition
in the canonical handoff.

Before closure, add the required verification comment: changed files,
acceptance evidence, commands and results, local versus CI evidence, merge SHA or
PR number, and any authorized follow-up. Close only after the issue contract is
actually satisfied.

If claimed work remains unfinished when releasing ownership, switching work or
ending the turn, update one `<!-- factory-resume:v1 -->` comment in place with
the current head, hypothesis, files touched, checks, next narrow verification,
remaining action, worker ID and UTC timestamp.

## Issue hierarchy

Use GitHub issue links for hierarchy. Epic/PRD and manual-only work is not
ordinary autonomous selection work. Put `Part of #NUMBER` and
`Depends on #NUMBER` in issue bodies where those relationships are authorized.
Do not create child tickets or split a large issue during the backlog freeze
without explicit owner direction.

## Rules for cheaper agents

- Do not select a new task when the user assigned an existing one.
- Do not bypass live ownership or factory holds.
- Do not close an issue without a verification comment.
- Do not skip tests, weaken gates or use CI as a local debugger.
- Do not push Python changes after only path-filtered ruff or pytest. Run the
  whole-repository ruff/ty pair.
- If the work cannot safely finish in the current runtime, preserve the blocker
  and hand off instead of manufacturing partial completion evidence.
