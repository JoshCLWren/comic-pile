# GitHub Issue Execution Protocol

This document is the mandatory operating procedure for agents executing GitHub issues in Comic Pile, including DeepSeek running through local agent tooling.

## Autonomous factory policy

Workers operating as part of the autonomous software-delivery factory must also read and follow [`docs/AUTONOMOUS_FACTORY_POLICY.md`](AUTONOMOUS_FACTORY_POLICY.md).

For autonomous factory runs, that policy is the canonical source for lifecycle, claim leases, exact-SHA review, readiness, draft-PR prohibition, CI-assisted repair loops, and escalation boundaries. It overrides contradictory generic instructions in this file or `AGENTS.md` about requiring the entire local matrix before every push, never using CI for evidence-grounded debugging, or opening draft PRs.

Repository engineering rules still apply. Factory workers may not skip tests, weaken gates, bypass hooks, add linter suppressions, violate async PostgreSQL requirements, or misrepresent CI evidence as local evidence.

## Source of truth

- The GitHub issue is the source of truth for task scope and acceptance criteria.
- When an issue links a local plan file, that file is the source of truth for implementation details. GitHub contains a compact pointer to it.
- GitHub Issues, labels, issue links, and issue bodies are the source of truth for backlog priority, status, and dependencies.
- `make next-task` is the canonical local helper for selecting the next executable issue.
- `AGENTS.md` is mandatory for repository engineering constraints.
- `docs/AUTONOMOUS_FACTORY_POLICY.md` is mandatory and takes precedence for autonomous factory lifecycle behavior.

## Before changing code

1. Read the selected GitHub issue body, `AGENTS.md`, and this protocol. Autonomous factory workers must also read `docs/AUTONOMOUS_FACTORY_POLICY.md`.
2. Read the complete durable PR or issue conversation required by the factory policy. Do not blindly dump irrelevant history into model context, but do not omit top-level comments, submitted reviews, inline threads, claims, verdicts, current CI, or commits that affect the contract.
3. If the issue links a local plan file, read that file in bounded chunks and treat it as authoritative.
4. If the issue is marked **Planning required**, do not edit application code. Create the local plan file first.
5. Confirm every dependency listed on the issue and board is complete or explicitly marked non-blocking.
6. Inspect the named files and existing tests before editing.
7. Claim work using the current factory lease protocol before implementation. For non-factory agents, replace `ralph-status:pending` with `ralph-status:in-progress` before editing.
8. Do not broaden scope. If a discovered bug is required to complete the issue, document and include it coherently. If it is unrelated, preserve it and report it without contaminating the branch.

## Planning gate

For issues marked **Planning required** in the issue workflow:

1. The planning agent must create a local plan file at `docs/issue-plans/<issue-number>.md` before implementation begins.
2. The plan must name files to inspect or change, explain the current data flow, identify likely failure or design risks, describe implementation steps, list regression tests, and provide exact local verification commands.
3. The plan must explicitly state whether database migrations, API schema changes, authorization checks, or frontend/backend contract changes are required.
4. The plan must include a rollback or containment strategy for risky schema or behavior changes.
5. Add a compact GitHub comment pointing to the local plan file. Do not paste a large duplicate plan into the issue thread.
6. Only after the plan file exists and is linked from the issue may implementation begin.

## While implementing

- Implement the smallest coherent change that satisfies the complete issue or a truthful staged slice.
- Do not delete, weaken, skip, quarantine, or conditionally disable tests.
- Do not use `--no-verify`, `# noqa`, `# type: ignore`, or equivalent suppressions.
- Preserve unrelated working-tree changes.
- Follow the repository's async-only PostgreSQL rule in application code.
- Add regression coverage for the reported failure, not only the happy path.
- Update documentation when behavior, API contracts, or user-visible workflows change.
- Inspect recently merged overlapping work before resolving conflicts or rebasing. Conflict resolution is semantic integration, not mechanical ours/theirs selection.

### CI usage

Ordinary one-shot agents should complete the relevant local verification before handing off work.

Autonomous factory workers follow the canonical factory policy: run focused local validation that directly exercises the change, push a grounded repair, let CI execute the configured broader matrix, inspect exact job logs, and iterate only from evidence. They must not make speculative remote edits or call branch-caused failures infrastructure without investigation.

## Required verification

Run the checks appropriate to the behavioral risk and acceptance contract.

For frontend or E2E work, available commands include:

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

For backend work, run focused tests first and broaden when useful:

```bash
pytest <focused-test-file-or-test>
pytest
```

A non-factory agent must not move an issue to Validation while required local commands are failing or omitted.

An autonomous factory worker may rely on the configured CI matrix for expensive broad verification after focused local validation, but must preserve exact evidence and continue the repair loop until the branch has a trustworthy outcome.

## Pull-request rules

- Open pull requests ready for review by default.
- Never create a draft pull request unless Josh explicitly requests a draft.
- A staged pull request must use `Part of #N` or a plain reference, describe `Stage scope`, list `Remaining work`, and leave the parent issue open.
- Do not use closure keywords or full-completion language for an incomplete stage.
- Never merge without Josh's explicit authorization for that merge.

## Issue handoff states

1. **In progress**: code changes are actively being made.
2. **Validation**: implementation is complete and the applicable local and CI checks are running or complete. No further design work remains for the declared scope.
3. **Integration ready**: the exact PR SHA passed strict review, required checks are green, blocking feedback is resolved, metadata is truthful, and no merge conflict exists.
4. **Done**: only after the authorized PR is merged, acceptance criteria are verified, documentation is updated, and the GitHub issue is correctly closed.

When updating an issue, preserve its priority, dependencies, and acceptance criteria. Do not silently change priority or dependencies.

## Required final comment on the GitHub issue

Before closing the issue, add a concise comment containing:

- What changed, with file paths.
- Which acceptance criteria were verified.
- Tests and commands run, including their result and whether evidence was local or CI-derived.
- Any follow-up issue numbers or remaining staged work.

Then add `ralph-status:done`, close the issue as completed, and include the final verification comment. A local implementation without this durable handoff is incomplete.
