# GitHub Issue Execution Protocol

This document is the mandatory operating procedure for agents executing GitHub issues in Comic Pile, including DeepSeek running through Cline.

## Source of truth

- The GitHub issue is the source of truth for the task scope, acceptance criteria, and implementation plan.
- `docs/ISSUE_KANBAN.md` is the source of truth for backlog priority, status, and dependencies.
- `AGENTS.md` is mandatory. Its test, async PostgreSQL, lint, and no-suppression rules override convenience.

## Before changing code

1. Read the complete GitHub issue, all comments, `AGENTS.md`, this protocol, and `docs/ISSUE_KANBAN.md`.
2. If the issue is marked **Planning required**, do not edit application code. Obtain and post the required implementation plan first.
3. Confirm every dependency listed on the issue and board is complete or explicitly marked non-blocking.
4. Inspect the named files and existing tests before editing.
5. Move the issue's row in `docs/ISSUE_KANBAN.md` from Ready/Planned/Queued to In progress. Do not claim work is in progress without making this edit.
6. Do not broaden scope. If a discovered bug is required to complete the issue, add it to the issue and board before implementing it. If it is unrelated, leave it untouched and report it.

## Planning gate

For issues marked **Planning required** on the kanban:

1. GLM 5.2 must post a plan comment before implementation begins.
2. The plan must name files to inspect/change, explain the current data flow, identify likely failure or design risks, describe implementation steps, list regression tests, and provide exact local verification commands.
3. The plan must explicitly state whether database migrations, API schema changes, authorization checks, or frontend/backend contract changes are required.
4. The plan must include a rollback or containment strategy for risky schema or behavior changes.
5. Only after the plan is posted and accepted may the issue move to its execution column and DeepSeek begin code changes.

## While implementing

- Implement the smallest complete change that satisfies every acceptance criterion.
- Do not delete, weaken, skip, quarantine, or conditionally disable tests.
- Do not use `--no-verify`, `# noqa`, `# type: ignore`, or equivalent suppressions.
- Do not use CI as a debugger.
- Preserve unrelated working-tree changes.
- Follow the repository's async-only PostgreSQL rule in application code.
- Add regression coverage for the reported failure, not only the happy path.
- Update documentation when behavior, API contracts, or user-visible workflows change.

## Required verification

For frontend or E2E work, run all applicable commands locally:

```bash
cd frontend && pnpm run lint
cd frontend && pnpm run typecheck
cd frontend && pnpm run build
cd frontend && pnpm test
cd frontend && pnpm run build && REUSE_EXISTING_SERVER=true npx playwright test --project=chromium
```

The Playwright command requires the backend running on port 9000. Start it with:

```bash
.venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 9000
```

For backend work, run the focused tests first and then the relevant broader suite:

```bash
pytest <focused-test-file-or-test>
pytest
```

Do not move an issue to Validation while any required command is failing or has not been run.

## Kanban handoff states

1. **In progress**: code changes are actively being made.
2. **Validation**: implementation is complete and all required local checks are running or complete; no further design work remains.
3. **Done**: only after all checks pass, acceptance criteria are verified, documentation is updated, and the GitHub issue is closed with a completion comment.

When moving a row, preserve its issue link, priority, dependency, and done criteria. Do not silently change priority or dependencies.

## Required final comment on the GitHub issue

Before closing the issue, add a concise comment containing:

- What changed, with file paths.
- Which acceptance criteria were verified.
- Tests and commands run, including their result.
- Any follow-up issue numbers.

Then close the GitHub issue as completed and move its row to Done in `docs/ISSUE_KANBAN.md`. A local implementation without this handoff is incomplete.
