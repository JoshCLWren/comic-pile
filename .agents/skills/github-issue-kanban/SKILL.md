---
name: github-issue-kanban
description: Use GitHub Issues as the Comic Pile kanban and execution queue. Trigger whenever the user asks an agent to do the next task, pick the next issue, work from the backlog, update issue status, plan issue work, or keep GitHub work synchronized. Use this skill before editing code for any issue-driven task in this repository.
---

# GitHub issue workflow

Use GitHub Issues as the only backlog and status source of truth. Do not maintain a parallel Markdown kanban. Local plan files are implementation references for large issues, not a second status system.

## Select work

Inspect the open issue queue, live claims, dependencies, and existing PR completion work with the GitHub CLI/API. Apply the selection priority in `docs/AUTONOMOUS_FACTORY_POLICY.md`; this checkout has no `make next-task` or `make start-task` target. Use the issue explicitly assigned by the user or selected by that policy. Epics, PRDs, manual-only issues, blocked work, live-owned work, and unresolved dependencies are not ordinary autonomous candidates.

Then read the selected issue body, the files it names, `AGENTS.md`, and
`docs/ISSUE_EXECUTION_PROTOCOL.md`. For factory work, also read
[docs/AUTONOMOUS_FACTORY_POLICY.md](../../../docs/AUTONOMOUS_FACTORY_POLICY.md) and the latest canonical resume packet. Do not load unrelated
comment history. If the issue points to `docs/issue-plans/<number>.md`, read that plan in bounded
chunks.

## Start work

Before editing code:

1. Confirm the issue is open and still eligible.
2. Confirm dependencies are closed or explicitly non-blocking.
3. Move the issue to active work. For factory work, replace the complete label set atomically so
   it contains `factory`, `factory:building`, and exactly one owner label without exposing an
   intermediate contradictory state:

   ```bash
   gh api --method PUT repos/JoshCLWren/comic-pile/issues/ISSUE/labels \
     --input /path/to/complete-truthful-label-set.json
   gh issue comment ISSUE --body "Starting implementation from the repository issue workflow."
   ```

   Build the JSON label set from the issue's current unrelated labels plus the complete target
   Ralph status, factory stage, and factory owner. Do not use add-only or sequential label calls.

4. Make the smallest complete change within the issue scope.
5. If required work is outside the issue, **do not create a new issue or split the parent**. Record the specific blocker or needed follow-up in the existing issue's canonical resume comment and ask the owner/interactive coordinator for an explicit scope decision. Only an owner-directed interactive session may authorize creating a child ticket during the Rust cutover. Do not create speculative bug, CI, test, or feature tickets simply to clear the current task.

Issue work is expected to produce a pull request. After local verification, commit the
implementation, push the branch, and open a ready-for-review PR linked to the issue. Do not
leave completed issue work only in the local working tree. Use a draft PR only when the user
explicitly requests one. After pushing, follow the **CI completion after every push**
section in [local-factory-session](https://github.com/JoshCLWren/rotisserie/blob/main/factory/.agents/skills/local-factory-session/SKILL.md): monitor the exact
head through required CI, repair failures locally, and report the actual result. A PR
link with "CI pending" is not an ordinary completion boundary.

Continue authorized local factory delivery through actual independent review,
gated merge, deployment and real acceptance. Do not wait for scheduled review
when an eligible local reviewer can run: follow
[the Codex Crouton adapter](https://github.com/JoshCLWren/rotisserie/blob/main/factory/.agents/skills/crouton-factory-codex/SKILL.md) and
[the executable ACP review path](https://github.com/JoshCLWren/rotisserie/blob/main/factory/docs/LOCAL_FACTORY_REVIEW.md).
Record the actual independent reviewer/model/session and exact head; manually
use the canonical `factory:review` + `factory:local` lease only during active
local review, then release it. Never invent a controller approval. Read only
ACP checkpoints/model-selection metadata and final reports/verdicts, not logs.
Preserve CI, independence, ownership, merge and production authorization gates.

For any Python tooling change, local verification must include the exact CI pair
`ruff check .` **and** `ty check --error-on-warning` against the whole repo, plus
`bash scripts/lint.sh` and the focused tooling tests. Path-filtered ruff or ty is
not a valid CI substitute. Ruff-only or pytest-only is not enough: CI fails the
required type-check job on ty warnings, including `redundant-cast`.
Do not recast a value after `isinstance` has already narrowed it.

## Keep status synchronized

Use these labels:

| State | Label |
| --- | --- |
| Ready to implement | `ralph-status:pending` |
| Actively editing | `ralph-status:in-progress` |
| Code complete and checks running/passed | `ralph-status:in-review` |
| Cannot proceed | `ralph-status:blocked` |
| Completed | `ralph-status:done` |

When blocked, leave the issue open, atomically reconcile the complete truthful label set with `ralph-status:blocked` and the appropriate factory state/owner, and comment with the exact blocker and required decision. Preserve a resume packet, release active ownership when appropriate, and return to selection for the next executable item under the autonomous policy; do not leave an active lease stranded.

When implementation is complete, run all required checks locally. Then move to review:

```bash
gh api --method PUT repos/JoshCLWren/comic-pile/issues/ISSUE/labels \
  --input /path/to/complete-truthful-review-label-set.json
gh issue comment ISSUE --body-file /path/to/verification-comment.md
```

Build the replacement label set from the issue's current unrelated labels plus the complete target Ralph status, factory stage, and owner. Never transition labels with sequential remove/add calls. The verification comment must include changed files, acceptance-criteria evidence, commands and results, and only owner-authorized follow-up issue numbers.

After the PR merges and acceptance criteria and issue closure are verified:

```bash
gh api --method PUT repos/JoshCLWren/comic-pile/issues/ISSUE/labels \
  --input /path/to/complete-done-label-set.json
gh issue close ISSUE --reason completed
```

If claimed work remains unfinished when releasing ownership, switching work, reaching a runtime
limit, or ending the turn, create or update one `<!-- factory-resume:v1 -->` comment in place. Keep
it compact: current head, hypothesis, files touched, passed/failed checks, next narrow verification,
remaining action, worker ID, and UTC timestamp. A takeover worker must verify the recorded head and
discard or update stale claims before acting.

## Issue hierarchy

Use GitHub issue links for hierarchy:

- Epic: broad outcome; never selected as the next coding task.
- Task: independently executable implementation unit.
- Subtask: narrow prerequisite linked to its parent task.

Put `Part of #NUMBER` and `Depends on #NUMBER` in issue bodies. Add `epic`, `ralph-task`, or `ralph-subtask` labels so the selector can distinguish planning work from executable work.

## Rules for cheaper agents

- Do not dump issue comment history into context.
- Do not begin work on an issue without updating its status label.
- Do not close an issue without a verification comment.
- Do not skip tests or use CI as a debugger.
- Do not push Python changes after only path-filtered `ruff` or pytest. Run `ruff check .` and `ty check --error-on-warning`; ty warnings fail CI. Path-filtered ruff or ty is not a valid CI substitute.
- If the issue is too large for one run, preserve the remaining scope in the existing issue or PR handoff. Do not split it or create linked tasks/subtasks without explicit owner authorization for that exact creation.
