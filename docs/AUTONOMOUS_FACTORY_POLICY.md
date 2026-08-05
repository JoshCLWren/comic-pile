# ComicPile Autonomous Factory Policy

Version: 16

This is the canonical policy for every scheduled ChatGPT worker, the local OpenCode factory, and interactive factory repair sessions.

## Prime directive

**Drive the open issue backlog to zero by delivering complete, safe implementations instead of orbiting a few pull requests.**

Success is measured by issues closed and production defects removed. Pull requests, commits, comments, reviews, labels, and hours spent are intermediate activity, not outcomes.

## Continuous delivery cycle

The factory follows this permanent cycle:

1. drain all executable open issues;
2. when the executable backlog reaches zero, restore and run the full configured end-to-end test coverage;
3. create a GitHub issue for every reproducible defect surfaced by E2E, with evidence and a `bug` label;
4. return immediately to backlog draining;
5. repeat whenever the backlog reaches zero again.

User-reported bugs remain first within the bug queue. Reproducible E2E-discovered bugs come next, then ordinary executable issues. E2E failures must never disappear into logs, comments, or informal notes.

## Selection priority

Choose work in this order:

1. A branch-caused failing check, merge conflict, or actionable review defect that prevents an active implementation PR from becoming mergeable.
2. The newest unclaimed open issue labeled both `user-reported` and `bug`.
3. The highest-priority unclaimed reproducible E2E-discovered `bug` issue.
4. The highest-value unclaimed executable issue, honoring explicit priority and dependencies.
5. Additional work on an existing PR only when required to complete its issue contract or make it mergeable.
6. Factory maintenance only when factory behavior blocks issue delivery.

A green, ready, review-passed, or merge-gated PR is excluded from ordinary work selection. It may be selected only for the final exact-head gate check and merge action described below.

Optional tests, cleanup, metadata edits, wording changes, evidence polishing, PR-body edits, architectural debate, or another minor slice do not outrank opening a coherent implementation branch for an unclaimed executable issue.

## Concurrency and throughput floor

At most one implementation worker may own an issue unless workers explicitly declare non-overlapping file ownership.

Once one worker has a valid lease on the highest-priority issue, peers select the next eligible issue. Do not let one broad issue, one user-reported bug, or one PR consume the whole factory.

When fewer than four substantive implementation PRs are open and executable unclaimed issues exist, idle workers must prefer opening coherent implementations for separate issues over embellishing existing PRs.

A substantive implementation PR changes product behavior, correctness, performance, architecture, deployment behavior, data, or meaningful automated coverage required by its issue. Comments, labels, reviews, PR metadata, help text, and optional test embellishment do not count toward this floor.

## Anti-loop rules

- Existing open PRs are not automatically higher priority than unclaimed issues.
- A green, ready, review-passed, or merge-gated PR must not consume repeated heartbeats.
- Do not repeatedly claim work whose next required edit is impossible in the current runtime. Preserve the blocker once, release active execution, and select another executable issue.
- Do not create replacement PRs merely because `main` advanced. Replay only when the prior PR is genuinely non-mergeable and substantial implementation would otherwise be lost.
- Waiting for CI, review, a merge, a safer runtime, or external availability is not a global stop condition while other executable work exists.
- Do not debate an already documented actionable finding across repeated heartbeats. Fix it, rebut it once with evidence, or mark the work blocked and move on.

## Full-contract implementation

Implement the whole issue in one coherent non-draft PR whenever reasonably reviewable. Large coherent PRs are allowed.

Split only when Josh requests it, a real independent deployment boundary exists, destructive authorization must remain separate, unavoidable branch collisions make one PR unsafe, or the combined change is genuinely unreasonable to review.

A partial PR does not automatically outrank a fresh higher-priority issue. Continue the parent issue only when it wins under the selection order.

## Required work loop

Repeat until the selected issue reaches closure or a valid blocker:

`inspect contract -> implement closure-critical behavior -> focused validation -> commit -> push -> inspect exact SHA -> account for all review feedback -> repair blockers -> verify merge gates -> merge when eligible -> verify issue closure`

After work becomes blocked, merge-gated, or dependent on a human decision, preserve durable context and return to selection rather than polishing indefinitely.

## Review-feedback gate

Before posting a pass verdict, ready marker, merge-gated marker, or statement that no blocking correctness issue remains, the worker must inspect the exact current head SHA and:

1. fetch review submissions and all current inline review threads;
2. ignore only clearly non-actionable status noise such as review-rate-limit notices, summaries, release notes, or optional finishing-touch advertisements;
3. classify every actionable finding as fixed, demonstrably outdated because of a specific later code change, or rebutted with concrete technical evidence;
4. respond to or resolve every actionable current thread;
5. refuse pass, readiness, or merge while an unresolved actionable correctness, security, ownership, data-integrity, concurrency, recovery, migration, or test-validity finding remains.

A worker's own review conclusion does not silently override existing human or bot feedback.

Every push invalidates prior review, readiness, and merge eligibility. Re-fetch the exact SHA, current review threads, mergeability, and CI after every push.

## Gated autonomous merges

Workers may merge a PR without asking again only after all of these gates are satisfied for the exact current head SHA:

- the PR is open, non-draft, and mergeable with no conflict;
- every required CI check has completed successfully;
- all actionable current review findings are fixed, demonstrably outdated, or rebutted with evidence;
- focused validation appropriate to the change has passed or exact-head CI provides that configured boundary;
- the PR truthfully completes its declared scope and does not hide required issue work behind avoidable follow-ups;
- merging will not violate ownership, migration, deployment, security, or data-safety constraints;
- the merge method is one allowed by repository settings;
- the worker supplies the exact expected head SHA to prevent merging a moved branch.

Do not enable auto-merge. Perform the merge only after the gates are currently true. If any gate becomes false or cannot be verified, do not merge and return to repair or selection.

After merging, verify whether the linked issue closed truthfully. If executable issue work remains, continue it under normal priority rather than declaring victory from the PR merge alone.

## Valid heartbeat outcomes

A normal heartbeat must accomplish at least one of these while executable issues remain:

- push substantive code, tests, or a migration;
- repair a blocking defect, review finding, CI failure, or merge conflict;
- open a coherent non-draft implementation PR for an executable issue;
- merge an exact-head PR whose complete gate set is satisfied;
- create evidence-backed bug issues from reproducible E2E failures during the backlog-zero phase;
- repair factory behavior that is directly blocking issue delivery.

Comments, labels, claims, reviews, PR-body edits, ready markers, help text, speculative plans, and optional test additions alone are not sufficient.

## Backlog-zero E2E phase

The full E2E restoration issue and PR stay deferred while executable product issues remain unless the disabled E2E state itself prevents safe delivery.

When no executable open issues remain:

1. prioritize the work required to restore the full configured E2E matrix;
2. merge that restoration only after the normal exact-head gates pass;
3. run or observe the full configured matrix;
4. create one focused issue per independent reproducible defect, linking failure evidence and affected specs;
5. label each defect `bug`; preserve `user-reported` only for bugs actually reported by a user;
6. resume normal selection immediately when those issues replenish the backlog.

Infrastructure failures that do not demonstrate product defects should be repaired as E2E infrastructure work rather than mislabeled as product bugs.

## Ownership and blocked work

Retain responsibility for a claimed issue through implementation, validation, repair, merge readiness, gated merge, and closure verification. Blocked ownership does not reserve the whole worker or the whole factory.

When owned work cannot safely advance now:

1. preserve concise durable blocker context;
2. release active execution when appropriate;
3. immediately select the highest-value free executable issue;
4. return when the blocker changes.

## Repository safety

- Never push directly to `main`.
- Never create or convert a draft PR unless Josh explicitly requests a draft.
- Never enable auto-merge.
- Never merge unless every gate in this policy is verified for the exact current head SHA.
- Never weaken checks, skip tests, remove meaningful coverage, bypass hooks, or add suppressions merely to make CI green.
- Never manufacture evidence or claim commands ran when they did not.
- Never mutate factory schedules or topology. Only Josh or an interactive session acting on Josh's direct instruction may do so.

## Closure truth

Use a closing keyword only when merging the PR will truthfully satisfy the entire issue contract.

Success hierarchy:

- issue truthfully closed and verified after merge;
- complete exact-head PR safely merged;
- complete PR gate-verified and awaiting only an external condition;
- blocking defect repaired or coherent implementation materially advanced;
- coherent new implementation PR opened from the backlog;
- optional PR polishing while executable issues remain: policy failure.

## Markers and leases

Use the existing canonical marker schemas:

- issue claim: `<!-- comic-pile-factory-implement-claim-v3:issue-<n>:<worker>:<epoch>:attempt-<n> -->`
- issue progress: `<!-- comic-pile-factory-implement-progress-v3:issue-<n>:<worker>:<epoch> -->`
- review claim: `<!-- comic-pile-factory-review-claim-v2:<sha>:<worker>:<epoch> -->`
- review pass verdict: `<!-- comic-pile-factory-review-v2:<sha>:pass -->`
- review changes-required verdict: `<!-- comic-pile-factory-review-v2:<sha>:changes-required -->`
- repair claim: `<!-- comic-pile-factory-fix-claim-v3:<sha>:<worker>:<epoch>:attempt-<n> -->`
- repair progress: `<!-- comic-pile-factory-fix-progress-v3:<sha>:<worker>:<epoch> -->`
- ready: `<!-- comic-pile-factory-ready-v2:<sha> -->`
- needs human: `<!-- comic-pile-factory-needs-human-v2:<sha-or-issue> -->`
- released: `<!-- comic-pile-factory-claim-released-v3:<target>:<worker>:<epoch>:<reason> -->`

Review leases last 45 minutes. Repair and implementation leases last 60 minutes after the latest real progress. Lease expiry permits another worker to continue that issue but does not require a peer to choose it over higher-priority work.

## Communication

Report meaningful issue-level outcomes. State the selected issue, substantive change, evidence, merge result when applicable, and exact blocker. Do not celebrate activity for its own sake.
