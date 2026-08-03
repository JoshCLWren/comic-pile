# ComicPile Autonomous Factory Policy

Version: 10

This is the canonical policy for every autonomous ComicPile software-delivery worker, including scheduled ChatGPT workers, the local OpenCode factory, and interactive factory repair sessions.

## Prime directive

**Finish what you start. Success is measured by issues closed, not pull requests opened.**

A worker owns an issue, not a PR. Once an issue is claimed, stay with it through implementation, review feedback, CI failures, rebases, follow-up repairs, and integration readiness until the issue is closed or a genuine human-only decision blocks it.

## Mission

Turn one selected issue into complete, reviewed, tested, integration-ready software with the fewest coherent PRs reasonably possible.

Planning, architecture notes, reviews, comments, labels, CI observations, PR bodies, and readiness markers are supporting evidence. They are not the product. The product is working code, tests, migrations, and an issue that can truthfully close.

## Repository safety

- Never push directly to `main`.
- Use a branch and non-draft PR for code, tests, migrations, workflow, or policy changes.
- Never create a draft pull request unless Josh explicitly requests a draft.
- Never merge unless Josh explicitly orders that specific merge.
- Never enable auto-merge as a substitute for explicit authorization.
- Never weaken checks, skip tests, delete meaningful coverage, bypass hooks, or add suppressions merely to make CI green.

## Issue ownership

Before selecting new work, reconstruct current GitHub state and prefer finishing already-started issues.

When a worker claims an issue:

- the issue is the durable unit of ownership;
- an open PR is only one state inside that ownership lifecycle;
- the worker must continue executable remaining work instead of declaring a stage complete and selecting another issue;
- review feedback, failed CI, merge conflicts, and follow-up defects stay with the same issue;
- ownership ends only when the issue is closed, Josh explicitly redirects the work, or a genuine human-only blocker is documented.

Multiple workers may cooperate on one large issue when their file ownership is non-overlapping and coordination is explicit. Five workers do not imply five unrelated active issues.

## Closure-first selection

Select work in this order:

1. A branch-caused failure or repair on an issue already in progress.
2. Remaining executable work required to close an issue with an open or recently merged partial PR.
3. A green PR for an owned issue that needs strict review or repair.
4. A ready PR awaiting Josh's explicit merge authorization.
5. The highest-value unclaimed executable issue.
6. Factory maintenance only when factory behavior itself blocks delivery.

Do not start a new issue while an owned issue has executable remaining work. Already-ready PRs are not new implementation targets, but their parent issues remain targets when work still remains after merge.

## One coherent PR by default

Implement the full issue in one coherent PR whenever reasonably reviewable.

Large coherent PRs are allowed and preferred over chains of tiny foundation PRs. Do not split merely to reduce line count, create a tidy stage boundary, or avoid difficult implementation work.

Split only when at least one is true:

- Josh explicitly requests it;
- a feature flag or independent deployment boundary is required;
- unavoidable branch collisions would make one PR unsafe;
- the combined change would be genuinely unreasonable to review;
- a destructive or irreversible decision must be authorized separately.

When a split is unavoidable, keep ownership of the parent issue and immediately continue the next required slice. A partial PR is not completion.

## No planning PRs

Do not open planning-only, architecture-only, inventory-only, or implementation-plan PRs unless the issue itself explicitly requests documentation as the deliverable.

Planning belongs in private scratch work, an issue comment, or directly alongside implementation. Documentation must support shipped behavior, not replace it. Writing extensive docs instead of implementing executable work is a policy failure.

Do not create a PR whose primary result is `Stage scope`, `Remaining work`, a migration plan, an architecture proposal, or a future implementation checklist.

## Closure score

Use this outcome hierarchy when choosing between actions:

- issue truthfully closed: highest value;
- actionable review feedback repaired: high value;
- branch restored to green and complete: high value;
- coherent implementation materially advanced toward closure: positive value;
- PR opened: minor coordination value;
- review, marker, label, or comment without implementation: no delivery value;
- planning-only PR or avoidable staged split: negative value;
- abandoning an executable owned issue for a new issue: severe failure.

## Lifecycle

The normal state machine is:

`DISCOVER -> SELECT ISSUE -> CLAIM ISSUE -> IMPLEMENT FULL CONTRACT -> FOCUSED VALIDATION -> PUSH -> REVIEW -> REPAIR -> CI DEBUG LOOP -> FRESH-SHA REVIEW -> READY -> WAIT FOR EXPLICIT MERGE -> VERIFY ISSUE CLOSURE OR CONTINUE REMAINING WORK`

A heartbeat is not one isolated verb. Move the owned issue through as many states as possible.

PR creation, review completion, pending CI, green CI, a ready marker, or one merged slice are not automatic stop conditions while the issue remains open and executable work remains.

## Durable progress floor

A normal heartbeat must produce substantive progress toward closing the owned issue unless every eligible issue is genuinely human-blocked or every safe write path is unavailable.

Substantive progress includes:

- code, tests, or migration committed and pushed;
- a materially repaired branch;
- a semantic rebase or conflict resolution;
- a coherent non-draft PR that implements the issue contract;
- durable factory code or policy repair when the factory itself is the target.

Labels, claims, comments, verdicts, PR-body edits, and ready markers do not satisfy this floor by themselves.

## Exact-commit truth

All review, repair, and readiness decisions are tied to the exact pull-request head SHA.

After every push, re-fetch the new SHA, full diff, conversation, mergeability, and CI. Earlier approval and ready markers become historical. Freshly review every new SHA before readiness.

## Repair-first behavior

When strict review finds a bounded, understood defect on a writable branch, repair it in the same issue lifecycle. Do not merely post `changes-required` and summon another worker.

CI failures, rebases, merge conflicts, test updates, review defects, browser inconvenience, and broad issues are ordinary engineering, not human-only boundaries.

## Validation and evidence

Run focused local validation that directly exercises the change when tools permit. CI-assisted debugging is permitted when each repair is grounded in exact logs, code, tests, or the issue contract.

Green CI is necessary but not sufficient. Match evidence to the claim:

| Claim | Evidence |
| --- | --- |
| Contract shape | schema, route, OpenAPI, or exact-key tests |
| Query reduction | query-count instrumentation before and after |
| Payload reduction | representative serialized byte measurements |
| Latency improvement | controlled benchmark with context and variance |
| UI behavior | focused unit and browser evidence where required |
| Ownership/security | unauthorized and cross-user tests |
| Cache behavior | dedupe, invalidation, rollback, cancellation, and stale-response tests |

Do not invent PASS claims. Do not use missing optional evidence as an excuse to replace implementation with documentation.

## Claims and marker schema

Issue implementation claim:

`<!-- comic-pile-factory-implement-claim-v3:issue-<number>:<worker-id>:<unix-epoch>:attempt-<n> -->`

Issue progress:

`<!-- comic-pile-factory-implement-progress-v3:issue-<number>:<worker-id>:<unix-epoch> -->`

Review claim:

`<!-- comic-pile-factory-review-claim-v2:<full-sha>:<worker-id>:<unix-epoch> -->`

Review verdict:

`<!-- comic-pile-factory-review-v2:<full-sha>:pass -->`

`<!-- comic-pile-factory-review-v2:<full-sha>:changes-required -->`

Repair claim:

`<!-- comic-pile-factory-fix-claim-v3:<full-sha>:<worker-id>:<unix-epoch>:attempt-<n> -->`

Repair progress:

`<!-- comic-pile-factory-fix-progress-v3:<full-sha>:<worker-id>:<unix-epoch> -->`

Ready:

`<!-- comic-pile-factory-ready-v2:<full-sha> -->`

Needs human:

`<!-- comic-pile-factory-needs-human-v2:<full-sha-or-issue-number> -->`

Released:

`<!-- comic-pile-factory-claim-released-v3:<target>:<worker-id>:<unix-epoch>:<reason> -->`

## Lease rules

- Re-fetch current SHA, comments, threads, and time immediately before claiming.
- A review lease is active for 45 minutes after its latest claim.
- A repair lease is active for 60 minutes after its latest claim or progress marker.
- An issue implementation lease is active for 60 minutes after its latest claim, progress marker, branch movement, issue activity, or PR creation.
- Simultaneous claims are resolved by lowest GitHub comment ID.
- A pushed new SHA releases old-SHA review and repair leases.
- A PR merge does not release issue ownership when the parent issue still has executable remaining work.

## Ready definition

A PR is ready only when the exact SHA has passed strict review, required CI is green or a documented non-branch exception is understood, actionable threads are resolved, scope is coherent, the branch is conflict-free, and the PR truthfully satisfies its declared contract.

Ready never means the parent issue is finished when remaining work still exists.

## Human escalation

Use `needs-human` only for missing credentials or permissions, destructive authorization, contradictory product requirements, unavailable external access, or irreversible product decisions.

Do not escalate ordinary implementation difficulty, large diffs, CI failures, review defects, merge conflicts, or the need to write more code.

## Communication

Report issue-level progress. State whether the issue will close, what remains before closure, and why any split was unavoidable.

Do not congratulate activity. Evaluate whether the factory finished what it started.
