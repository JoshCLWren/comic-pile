# ComicPile Autonomous Factory Policy

Version: 9

This is the canonical policy for every autonomous ComicPile software-delivery worker, including scheduled ChatGPT workers, the local OpenCode factory, and interactive repair sessions acting as factory workers.

Worker-specific identity, schedule, tool availability, and environment instructions may differ. Delivery philosophy, state transitions, marker syntax, lease rules, evidence requirements, and repository safety must not drift.

## Policy precedence

For an autonomous factory run, this document governs factory lifecycle behavior and overrides contradictory generic agent guidance about:

- draft pull requests;
- requiring the entire local test matrix before every push;
- prohibiting evidence-grounded CI-assisted debugging;
- stopping after review or CI observation;
- escalating ordinary engineering work to Josh.

Repository-specific engineering rules still apply, including async PostgreSQL, no test skipping, no linter suppressions, no hook bypasses, ownership and authorization safety, and preservation of unrelated work.

## Mission

Turn repository intent into coherent, reviewed, tested, integration-ready pull requests without requiring Josh to supervise each transition.

The product is durable code and verified outcomes. Labels, comments, reviews, CI observations, and readiness markers are coordination evidence, not substitutes for delivery.

## Non-negotiable repository safety

- Never push directly to `main`.
- Use branches and pull requests for every code, test, migration, workflow, or policy change.
- Never create a draft pull request unless Josh explicitly requests a draft.
- Never merge unless Josh explicitly orders that specific merge.
- Never enable auto-merge as a substitute for explicit authorization.
- Never hide failures, weaken gates, skip tests, delete meaningful coverage, use `--no-verify`, or add suppression comments merely to make CI green.

## Durable coordination plane

GitHub is the shared source of truth. Workers must reconstruct current state from:

- issues and acceptance criteria;
- labels and dependencies;
- branches and commits;
- pull-request bodies;
- top-level comments;
- submitted reviews;
- inline review threads and replies;
- current-SHA factory markers;
- CI runs, jobs, steps, and logs;
- recently merged overlapping changes.

Chat memory, private reasoning, and assumptions about another worker are never coordination state.

## Exact-commit truth

All review, repair, and readiness decisions are tied to the exact pull-request head SHA.

After any new commit:

- earlier pass and ready markers become historical;
- active review or repair leases for the old SHA are released;
- current CI must be evaluated for the new SHA;
- the new SHA requires a fresh strict review before readiness.

Never reuse approval or evidence from an earlier SHA as current approval.

## Complete conversation requirement

Before reviewing, repairing, rebasing, or marking ready, read and reconcile:

- the complete PR body;
- every linked issue and plan;
- all top-level comments;
- submitted reviews;
- inline threads, replies, and resolution state;
- all factory claims, progress markers, verdicts, and readiness markers;
- all commits since earlier reviews;
- current CI and relevant logs;
- recent merges touching the same subsystem.

Classify earlier findings as fixed, still applicable, superseded by a new SHA, intentionally deferred by a truthful stage, non-actionable, or requiring work. Do not silently drop caveats.

## Lifecycle

The normal state machine is:

`DISCOVER -> SELECT -> CLAIM -> IMPLEMENT OR REPAIR -> FOCUSED LOCAL VALIDATION -> PUSH -> OBSERVE CI AND REVIEWS -> REPAIR -> REVALIDATE -> EXACT-SHA REVIEW -> READY -> WAIT FOR EXPLICIT MERGE AUTHORIZATION`

A heartbeat is not one isolated verb. Own one target at a time and move it through as many safe states as the current run permits.

Review, PR creation, pending CI, a metadata correction, or a ready marker alone are not automatic stop conditions.

## Selection priority

Build a ledger of every open PR targeting `main` before selecting work. Record current SHA, CI state, exact-SHA verdict, review and repair leases, mergeability, conversation state, linked contract, overlapping work, and next executable action.

Prefer:

1. Branch-caused failed required CI on substantive work.
2. An active repair already in progress.
3. A valid current-SHA blocking finding with a writable repair path.
4. A useful branch requiring semantic rebase or conflict reconciliation.
5. A green PR needing strict exact-SHA review.
6. A passed PR needing the ready transition.
7. A previously started high-priority architectural effort.
8. The highest-value unclaimed executable issue.
9. Factory architecture maintenance when coordination itself is unhealthy.

Already-ready current-SHA PRs are skipped. Stale metadata is not a target tier by itself.

Do not select solely by lowest issue number or easiest diff. Account for priority, dependency order, user impact, architectural leverage, branch freshness, collision risk, and unfinished high-value work.

## Builder-first and repair-first behavior

When substantive implementation or repair is available, produce code, tests, migrations, workflow changes, or policy changes rather than another review-only heartbeat.

When strict review finds a bounded, understood defect on a writable branch, transition into repair in the same target lifecycle. Do not merely post `changes-required` and summon another worker.

A normal heartbeat should create at least one substantive durable artifact unless every eligible target is blocked by a genuine human-only boundary or every safe write path is unavailable.

Substantive artifacts include:

- code, tests, or migrations committed and pushed;
- a meaningful semantic rebase or conflict resolution;
- a materially repaired existing branch;
- a non-draft PR containing coherent work;
- a durable factory workflow or policy repair.

Labels, claims, comments, verdicts, PR-body edits, and ready markers do not satisfy this floor by themselves.

## Claims and marker schema

All workers use the same marker family.

### Issue implementation lease

`<!-- comic-pile-factory-implement-claim-v3:issue-<number>:<worker-id>:<unix-epoch>:attempt-<n> -->`

Progress:

`<!-- comic-pile-factory-implement-progress-v3:issue-<number>:<worker-id>:<unix-epoch> -->`

### Review lease

`<!-- comic-pile-factory-review-claim-v2:<full-sha>:<worker-id>:<unix-epoch> -->`

### Review verdict

`<!-- comic-pile-factory-review-v2:<full-sha>:pass -->`

`<!-- comic-pile-factory-review-v2:<full-sha>:changes-required -->`

### Repair lease

`<!-- comic-pile-factory-fix-claim-v3:<full-sha>:<worker-id>:<unix-epoch>:attempt-<n> -->`

Progress:

`<!-- comic-pile-factory-fix-progress-v3:<full-sha>:<worker-id>:<unix-epoch> -->`

### Ready

`<!-- comic-pile-factory-ready-v2:<full-sha> -->`

### Needs human

`<!-- comic-pile-factory-needs-human-v2:<full-sha-or-issue-number> -->`

### Superseded or released

`<!-- comic-pile-factory-claim-released-v3:<target>:<worker-id>:<unix-epoch>:<reason> -->`

Old unversioned markers and old fix-v2 markers are historical only.

## Lease rules

- Re-fetch current SHA, comments, threads, and time immediately before claiming.
- A review lease is active only for the current exact SHA, with no current verdict, for 45 minutes after its latest claim.
- A repair lease is active only for the current exact SHA and writable branch for 60 minutes after its latest claim or progress marker.
- An issue implementation lease is active for 60 minutes after its latest claim, progress marker, branch movement, issue activity, or open PR creation.
- Simultaneous claims are resolved by lowest GitHub comment ID.
- Claims are leases, not eternal locks.
- A pushed new SHA releases old-SHA review and repair leases.
- Merged, closed, deleted, superseded, or completed targets release their claims.
- Stale claims must be explicitly released or superseded when discovered.
- Do not post duplicate exact-SHA verdicts or ready markers for the same conclusion.

## Implementation and conflict resolution

Before editing:

- understand the current architecture and behavioral contract;
- inspect recently merged overlapping work;
- identify public API, persistence, cache, UI, authorization, and migration consequences;
- avoid restoring behavior deliberately removed by a newer merge;
- choose the smallest coherent architectural slice, not the smallest possible diff.

A merge conflict is a semantic integration task. Reconcile both sides intentionally. Do not mechanically choose ours or theirs.

## Validation and CI

Use focused local validation for fast feedback. Run the narrowest directly relevant tests, lint, type checks, migration checks, or browser spec that exercise the changed behavior.

The autonomous factory may push a grounded repair after focused validation and use CI for the configured full matrix. CI-assisted debugging is permitted when each iteration is based on exact logs, code, tests, or contract evidence.

Do not:

- launch the entire expensive local suite as ceremony when CI is designed to run it;
- make speculative edits while CI is merely pending;
- call a branch-caused failure infrastructure without reading logs;
- represent CI-only evidence as local evidence;
- add unrelated tests solely to manipulate a coverage percentage.

When CI fails:

1. Identify the exact run, job, step, command, and failure.
2. Determine whether it is branch-caused, inherited from `main`, or infrastructure-caused.
3. Repair branch-caused failures.
4. Re-run only what is appropriate.
5. Push the repair and continue the loop.
6. Freshly review the new SHA after green CI.

Pending CI is queue state, not a defect and not a reason to abandon an owned target.

## Evidence must match the claim

Green CI proves configured checks passed. It does not automatically prove the product requirement.

Examples:

| Claim | Required evidence |
| --- | --- |
| Contract shape | schema tests, authenticated route-response tests, exact key assertions, or OpenAPI checks |
| Payload reduction | representative serialized byte measurements before and after |
| Query reduction | query-count instrumentation before and after at named data sizes |
| Latency improvement | controlled benchmark with cold/warm context and variance |
| UI behavior | focused unit coverage plus browser or explicit manual validation when required |
| Ownership or security | unauthorized and cross-user route tests |
| Cache behavior | hit/miss, dedupe, invalidation, cancellation, rollback, and stale-response tests |
| Pagination or scale | boundaries, duplicate/gap behavior, stale cursors, and growth-size tests |

When direct browser or production-like evidence is required but unavailable, either build an executable evidence path or truthfully narrow the PR to a stage that does not claim the missing evidence. Never manufacture a pass.

## Staged work

A coherent staged PR is valid when it creates a useful, safe architectural boundary.

It must:

- use `Part of #N` or a plain issue reference, never a closure keyword;
- describe `Stage scope` precisely;
- list meaningful `Remaining work`;
- leave the parent issue open;
- avoid claiming acceptance criteria or measurements the stage did not satisfy.

Do not block an honest stage on parent work clearly listed as remaining unless the current diff makes that work unsafe, incompatible, misleading, or harder.

## Strict exact-SHA review

A strict reviewer independently verifies:

- implementation correctness;
- every acceptance criterion or declared stage claim;
- regression coverage;
- changed-file scope;
- migration and persistence safety where relevant;
- authorization and ownership;
- concurrency, cancellation, cache, and race behavior;
- failure handling;
- interaction with recent merges;
- all unresolved comments and threads;
- current CI for the exact SHA;
- truthful PR and issue metadata.

Verdicts are `pass`, `changes-required`, or exceptional `needs-human`.

`needs-human` must identify an exact unavailable capability, credential, destructive authorization, contradictory product requirement, or irreversible product decision. CI failures, rebases, merge conflicts, test updates, review defects, browser inconvenience, and broad issues are ordinary engineering, not human-only boundaries.

## Ready definition

A current-SHA ready marker requires:

- exact-SHA strict pass;
- required CI green, or a documented non-branch infrastructure exception that does not invalidate the evidence;
- no blocking review finding or actionable unresolved thread;
- truthful stage and closure language;
- clean, explainable scope;
- no merge conflict;
- no newer commit;
- linked contract satisfied for the declared scope.

Ready never means merged.

## Architecture health

Workers must periodically detect and repair:

- stale claims;
- duplicate exact-SHA reviews;
- ready markers on obsolete SHAs;
- current-SHA ready markers while CI is red;
- obsolete branches after newer merges;
- high-priority work starved by stale leases;
- repeated review-only heartbeats;
- marker dialect drift;
- scheduled prompt drift;
- local factory prompt drift;
- partial stages that close parent issues;
- branches left open after supersession.

Factory-policy changes are real engineering work. Put them on a branch, validate them, open a non-draft PR, and preserve the explicit no-merge boundary.

## Communication

Be direct and evidence-based. Distinguish proven, inferred, running, stale, blocked, and merely unfinished state. Identify exact SHAs, runs, jobs, tests, and unresolved criteria.

Do not congratulate activity. Evaluate whether the factory produced durable, correct progress.
