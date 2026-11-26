# Agent Next-Task Prompt

Work on the next eligible task in this repository.

## Before editing

1. Read `AGENTS.md`.
2. Read `docs/ISSUE_EXECUTION_PROTOCOL.md`.
3. For factory work, read `docs/AUTONOMOUS_FACTORY_POLICY.md` and the current canonical resume packet.
4. Inspect `git status` and preserve all existing user changes.
5. Inspect the open GitHub issue queue, live claims, dependencies, and PR work with the GitHub CLI/API. Apply the selection priority in the autonomous policy; this checkout has no `make next-task` or `make start-task` target.
6. Read the selected issue, every durable comment that affects its contract, the exact PR head/CI/reviews when a PR exists, and any linked local plan.
7. Do not create or split issues without explicit owner authorization for that exact creation. Record out-of-scope discoveries in the existing issue or PR handoff.

## While working

- Claim the selected work through the current factory lease protocol before editing. Replace the complete label set atomically with the truthful Ralph status, `factory`, one workflow stage, and exactly one owner label; never use sequential remove/add calls.
- Implement only the selected issue's scope and add regression tests for changed behavior.
- Fix failures; never skip tests, weaken gates, or use CI as a debugger.
- For any Python tooling change, run `ruff check .` and `ty check --error-on-warning` against the whole repository after the last edit, plus `bash scripts/lint.sh` and the focused tooling tests. Path-filtered Ruff or ty is not a valid CI substitute.
- If required work is outside the issue, preserve the blocker in the existing issue or PR and ask the owner/interactive coordinator for a scope decision. Do not create a linked issue or expand scope on your own.
- If blocked, preserve a concise durable blocker, release or reconcile ownership truthfully, and return to selection for the next executable item under the autonomous policy. Do not leave an active lease stranded.
- Do not use the archived Markdown kanban as a status source.
- Do not discard, reset, or overwrite unrelated working-tree changes.
- Before ending with claimed work unfinished, update the canonical `<!-- factory-resume:v1 -->` comment with the current head, hypothesis, files touched, checks, next narrow verification, remaining action, worker ID, and UTC timestamp.

## Before finishing

- Run the required focused local checks from `AGENTS.md` and the selected issue; leave full suites and aggregate coverage to CI.
- Reconcile the issue and PR labels atomically for the truthful review, CI, changes-requested, ready, or blocked state.
- Add a GitHub verification comment listing changed files, acceptance-criteria evidence, commands and results, and only owner-authorized follow-up issue numbers.
- Follow the applicable delivery process: commit and push implementation work, open or update a ready-for-review PR linked to the issue, inspect the new exact head and every review thread, and repair findings. Use a draft PR only when the user explicitly requests one.
- Leave the issue in review while its PR is open. Mark it `ralph-status:done` and close it only after the PR merges and the issue acceptance criteria and closure are verified.

Begin by inspecting the GitHub queue and current factory claims.
