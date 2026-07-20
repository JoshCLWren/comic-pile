---
name: github-issue-kanban
description: Use GitHub Issues as the Comic Pile kanban and execution queue. Trigger whenever the user asks an agent to do the next task, pick the next issue, work from the backlog, update issue status, plan issue work, or keep GitHub work synchronized. Use this skill before editing code for any issue-driven task in this repository.
compatibility: Requires git, gh CLI authentication, and the repository's GitHub remote.
---

# GitHub issue workflow

Use GitHub Issues as the only backlog and status source of truth. Do not maintain a parallel Markdown kanban. Local plan files are implementation references for large issues, not a second status system.

## Select work

From the repository root, run:

```bash
make next-task
```

Use the issue selected by that command unless the user explicitly names another issue. The selector prefers open issues with `ralph-status:pending`, highest `ralph-priority:*`, and no unresolved issue dependencies. Epics, blocked issues, issues already in progress/review, duplicates, and issues with unresolved dependencies are not selected.

Then read only the selected issue body, the files it names, `AGENTS.md`, and `docs/ISSUE_EXECUTION_PROTOCOL.md`. Do not load every issue comment. If the issue points to `docs/issue-plans/<number>.md`, read that plan in bounded chunks.

## Start work

Before editing code:

1. Confirm the issue is open and still eligible.
2. Confirm dependencies are closed or explicitly non-blocking.
3. Move the issue to active work:

   ```bash
   gh issue edit ISSUE --remove-label "ralph-status:pending" --add-label "ralph-status:in-progress"
   gh issue comment ISSUE --body "Starting implementation from the repository issue workflow."
   ```

4. Make the smallest complete change within the issue scope.
5. If required work is outside the issue, create a linked issue before expanding scope.

## Keep status synchronized

Use these labels:

| State | Label |
| --- | --- |
| Ready to implement | `ralph-status:pending` |
| Actively editing | `ralph-status:in-progress` |
| Code complete and checks running/passed | `ralph-status:in-review` |
| Cannot proceed | `ralph-status:blocked` |
| Completed | `ralph-status:done` |

When blocked, leave the issue open, replace the active label with `ralph-status:blocked`, and comment with the exact blocker and required decision. Do not silently move to another issue.

When implementation is complete, run all required checks locally. Then move to review:

```bash
gh issue edit ISSUE --remove-label "ralph-status:in-progress" --add-label "ralph-status:in-review"
gh issue comment ISSUE --body-file /path/to/verification-comment.md
```

The verification comment must include changed files, acceptance criteria evidence, commands and results, and follow-up issue numbers.

Only after all checks and acceptance criteria pass:

```bash
gh issue edit ISSUE --remove-label "ralph-status:in-review" --add-label "ralph-status:done"
gh issue close ISSUE --reason completed
```

## Issue hierarchy

Use GitHub issue links for hierarchy:

- Epic: broad outcome; never selected as the next coding task.
- Task: independently executable implementation unit.
- Subtask: narrow prerequisite linked to its parent task.

Put `Part of #NUMBER` and `Depends on #NUMBER` in issue bodies. Add `epic`, `ralph-task`, or `ralph-subtask` labels so the selector can distinguish planning work from executable work.

## Rules for cheaper agents

- Do not use the old `docs/ISSUE_KANBAN.md` as status authority.
- Do not dump issue comment history into context.
- Do not begin work on an issue without updating its status label.
- Do not close an issue without a verification comment.
- Do not skip tests or use CI as a debugger.
- If the issue is too large for one run, split it into linked GitHub tasks/subtasks before coding.
