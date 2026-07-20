# Agent Next-Task Prompt

Work on the next task in this repository.

## Before editing

1. Read `AGENTS.md`.
2. Read `docs/ISSUE_EXECUTION_PROTOCOL.md`.
3. Inspect `git status` and preserve all existing user changes.
4. Run `make next-task`.
5. Read the selected GitHub issue and any linked local plan.
6. If the issue is too large for one implementation pass, split it into linked GitHub task/subtask issues before editing code.

## While working

- Move the selected issue from `ralph-status:pending` to `ralph-status:in-progress`.
- Implement only that issue's scope.
- Add regression tests for changed behavior.
- Fix failures; never skip tests or use CI as a debugger.
- If required work is outside the issue, create a linked GitHub issue before expanding scope.
- If blocked, mark the issue `ralph-status:blocked`, explain the exact blocker, and stop.
- Do not use `docs/ISSUE_KANBAN.md` as a status source.
- Do not discard, reset, or overwrite unrelated working-tree changes.

## Before finishing

- Run all required local checks from `AGENTS.md` and the selected issue.
- Move the issue to `ralph-status:in-review`.
- Add a GitHub comment listing changed files, acceptance-criteria evidence, test commands, and results.
- Only after everything passes, mark the issue `ralph-status:done` and close it.
- Do not commit or push unless explicitly requested by the user.

Begin by running `make next-task`.
