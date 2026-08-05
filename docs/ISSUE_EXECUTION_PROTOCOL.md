# GitHub Issue Execution Protocol

This document is the mandatory operating procedure for agents executing GitHub issues in Comic Pile, including local OpenCode agents.

## Autonomous factory policy

Workers operating as part of the autonomous software-delivery factory must also read and follow [`docs/AUTONOMOUS_FACTORY_POLICY.md`](AUTONOMOUS_FACTORY_POLICY.md).

For autonomous factory runs, that policy is the canonical source for backlog selection, lifecycle, claim leases, exact-SHA review, gated merges, draft-PR prohibition, CI-assisted repair loops, Chromium backlog-zero E2E, and escalation boundaries. It overrides contradictory generic instructions in this file or `AGENTS.md`.

Repository engineering rules still apply. Factory workers may not skip tests, weaken gates, bypass hooks, add linter suppressions, violate async PostgreSQL requirements, or misrepresent CI evidence as local evidence.

## Source of truth

- The GitHub issue is the source of truth for scope and acceptance criteria.
- GitHub issues, labels, links, bodies, and durable comments are the source of truth for priority, status, dependencies, claims, and blockers.
- A linked local plan file is authoritative for implementation details.
- `AGENTS.md` is mandatory for repository engineering constraints.
- `docs/AUTONOMOUS_FACTORY_POLICY.md` is mandatory and takes precedence for autonomous factory lifecycle behavior.

## Before changing code

1. Read the selected issue, relevant `AGENTS.md`, this protocol, and the autonomous policy when applicable.
2. Read all durable context that affects the contract, including top-level comments, submitted reviews, current inline review threads, claims, verdicts, commits, and current CI.
3. Confirm dependencies are complete or explicitly non-blocking.
4. Inspect the named files, surrounding data flow, and existing tests before editing.
5. Claim work using the current factory lease protocol before implementation.
6. Do not broaden scope. Include a discovered defect only when it is required for coherent issue completion. Preserve unrelated defects as separate issues.

## Planning gate

For issues explicitly marked **Planning required**:

1. Create `docs/issue-plans/<issue-number>.md` before implementation.
2. Identify files, current flow, risks, implementation steps, tests, verification commands, migrations, authorization changes, API contract changes, and rollback strategy.
3. Add a compact GitHub comment linking the plan.
4. Begin implementation only after the plan exists.

Do not create planning-only pull requests unless the issue itself requests documentation.

## While implementing

- Implement the full issue in one coherent PR whenever reasonably reviewable.
- Split only under the exceptions in the autonomous policy.
- Do not delete, weaken, skip, quarantine, or conditionally disable meaningful tests.
- Do not use `--no-verify`, `# noqa`, `# type: ignore`, or equivalent suppressions to force green.
- Preserve unrelated working-tree changes.
- Follow the repository's async-only PostgreSQL rule in application code.
- Add regression coverage for the reported failure and important failure paths.
- Resolve conflicts semantically after inspecting overlapping work.

## Validation

Run focused checks that directly exercise the change. Let configured CI carry expensive broad validation when the autonomous policy permits it.

Common frontend checks include:

```bash
cd frontend && pnpm run lint
cd frontend && pnpm run typecheck
cd frontend && pnpm run build
cd frontend && pnpm test
```

Common backend checks include:

```bash
pytest <focused-test-file-or-test>
pytest
```

Chromium Playwright is the required browser E2E target when browser validation is required. Firefox and WebKit are optional diagnostics for browser-specific investigations.

The deferred backlog-zero E2E lifecycle is tracked by #679. Autonomous workers must not prioritize #679 while any other executable issue remains open, unless disabled Chromium coverage itself blocks safe delivery.

## Review feedback

Every push invalidates prior review and readiness.

Before pass, readiness, or merge, inspect the exact current head SHA, submitted reviews, and every current inline review thread. Each actionable finding must be fixed, demonstrably outdated by a specific later change, or rebutted with concrete evidence. Non-actionable status noise such as summaries, rate-limit notices, release notes, and optional finishing-touch suggestions does not block readiness.

An unresolved actionable correctness, security, ownership, data-integrity, migration, concurrency, recovery, or test-validity finding blocks readiness and merge.

## Pull-request rules

- Open pull requests ready for review by default.
- Never create a draft pull request unless Josh explicitly requests a draft.
- Use a closure keyword only when merge will truthfully satisfy the complete issue.
- Do not use `Stage scope` or `Remaining work` to justify avoidable splitting.
- PR metadata, comments, labels, and review prose are not substitutes for implementation.

## Merge rules

Autonomous factory workers may merge after every gate in `docs/AUTONOMOUS_FACTORY_POLICY.md` is verified for the exact current head SHA.

The worker must verify that the PR is open, non-draft, conflict-free, mergeable, green on every required check, complete for its declared scope, safe to integrate, and free of unresolved actionable review findings. The merge operation must include the exact expected head SHA.

Never enable auto-merge. Never merge a moved or unverified head.

Non-factory agents require Josh's explicit authorization before merging unless he has already granted equivalent standing authorization in the active conversation.

## Issue lifecycle

1. **In progress**: implementation is actively advancing.
2. **Validation**: focused checks and exact-head CI are running or complete.
3. **Integration ready**: exact-head review, required checks, feedback accounting, mergeability, and metadata are complete.
4. **Done**: the PR has merged, acceptance criteria are verified, and the issue is truthfully closed.

A green or ready PR must not monopolize a worker. When another executable issue exists, preserve state and return to backlog selection.

## Required final issue comment

Before closing an issue, add a concise durable comment containing:

- what changed, with relevant file paths;
- which acceptance criteria were verified;
- tests and commands run, including whether evidence was local or CI-derived;
- the merge SHA or PR number;
- any legitimate follow-up issue numbers.

Then close the issue as completed only when the contract is actually satisfied.
