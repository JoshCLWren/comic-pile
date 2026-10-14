---
name: local-factory-next-task
description: Find the oldest factory-claimable task and start it as a local factory session. Use when the user says find the next task, pick the next issue, what should we work on, start factory work, claim the oldest claimable task, take something from the backlog, or work as a local factory in this repository.
metadata:
  opencode/slash: "true"
---

# Start the oldest claimable task as a local factory

This is the startup half of local factory work; `local-factory-session` covers session
bootstrap, commit provenance, and the review handoff. `github-issue-kanban` remains the
general issue-workflow reference. The canonical copy-paste master prompt is
`prompts/agent-next-task.md`.

## 1. Bootstrap the session first

Follow the `local-factory-session` skill before the first commit: run
`bash scripts/install-git-hooks.sh`, verify whether hooks actually fire (inert
`core.hooksPath`), export `OPENCODE_MODEL`, and plan to verify the `Model:` trailer after
commit #1.

Also: inspect `git status` and preserve any existing user changes.

## 2. Read durable context

- `AGENTS.md`
- `docs/ISSUE_EXECUTION_PROTOCOL.md`
- `docs/AUTONOMOUS_FACTORY_POLICY.md` (factory work — claim leases, review, merge gates)

## 3. Select the task

```bash
make next-task
```

Work on the selected issue unless the user names another. Selection semantics
(`scripts/next_task.py`):

- **Claimable** means: `ralph-status:pending` + `ralph-task`, and none of `duplicate`,
  `ralph-status:{blocked,done,in-progress,in-review}`; not `epic`/`prd`; body has no
  `<!-- factory-execution:manual-only -->` marker; not an acceptance-parent contract; and no
  declared dependency issue left open.
- **Ordering**: highest priority first (`critical` → `high` → `medium` → `low` → unprioritized),
  tie-broken by **lowest issue number — i.e. the oldest claimable task wins within a
  priority band**.

Then read the issue body, any linked plan (`docs/issue-plans/<number>.md`, bounded chunks),
and the named files. If the issue is too large for one implementation pass, split it into
linked task/subtask issues before editing code. If required work turns out to be outside the
issue, create a linked issue instead of widening scope.

## 4. Claim it (two steps — status first, then the atomic factory set)

1. Validate and flip status:

   ```bash
   make start-task ISSUE=<number>
   ```

   This refuses non-pending/non-executable/manual-only/dependency-blocked issues, moves
   `ralph-status:pending` → `ralph-status:in-progress`, and posts the starting-implementation
   comment.

2. Reconcile the **complete** label set in one atomic write (never sequential add/remove), so
   the issue immediately carries truthful factory state for a local session:

   ```bash
   gh api -X POST repos/JoshCLWren/comic-pile/issues/<number>/labels \
     -F "labels[]=ralph-task" -F "labels[]=ralph-status:in-progress" \
     -F "labels[]=ralph-priority:<band>" \
     -F "labels[]=factory" -F "labels[]=factory:building" -F "labels[]=factory:local" \
     -F "labels[]=<preserve every other unrelated label from the issue>"
   ```

   Target set: the issue's existing unrelated labels (priority, `quality-control`,
   `infrastructure`, etc.) + `ralph-status:in-progress` + `factory` + `factory:building` +
   exactly one owner (`factory:local` for a local session). Fetch current labels first
   (`gh issue view <n> --json labels`) so none are dropped.

## 5. Work the issue

- Implement only that issue's scope; add regression tests for changed behavior.
- Fix every failure; never skip tests, never use CI as a local debugger, never suppress.
- Python changes: `bash scripts/check-python-ci-lint.sh` (whole-repo ruff + ty) after the
  last edit and before every push. Frontend changes: `pnpm run lint && pnpm run typecheck &&
  pnpm test && pnpm run build`. Browser behavior: see the relevant e2e skill.
- If blocked: set `ralph-status:blocked` with the exact blocker and stop.
- If ending a turn with work unfinished, update the canonical `<!-- factory-resume:v1 -->`
  comment (head, hypothesis, files touched, checks, next narrow verification, remaining
  action, worker id, UTC timestamp).

## 6. Finish through the handoff

When implementation and gates are done, follow `local-factory-session`: commit with the
`Model:` trailer, push, open a ready-for-review PR linked to the issue, post the
verification comment (files, acceptance evidence, test commands + results), and reconcile
the issue/PR to the fleet pickup state — `ralph-status:in-review` + `factory:review` +
`factory:unowned` (issue) and `factory` + `factory:review` + `factory:unowned` (PR).
Leave the issue open until the PR merges and acceptance criteria are verified.
