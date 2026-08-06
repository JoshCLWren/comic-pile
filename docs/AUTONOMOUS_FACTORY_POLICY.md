# ComicPile Autonomous Factory Policy

Version: 17

This is the canonical policy for every scheduled ChatGPT worker, the local OpenCode factory, and interactive factory repair sessions.

## Prime directive

**Drive the open issue backlog to zero by delivering complete, safe implementations instead of orbiting a few pull requests.**

Success is measured by issues truthfully closed and production defects removed. Pull requests, commits, comments, reviews, labels, and hours spent are intermediate activity, not outcomes.

## Continuous delivery cycle

The factory follows this permanent cycle:

1. drain every executable open issue except the deferred backlog-zero checkpoint #679;
2. when #679 is the only remaining executable checkpoint, restore and run the complete maintained Chromium Playwright E2E suite;
3. create one GitHub issue for every independent reproducible product defect surfaced by Chromium E2E, with evidence and a `bug` label;
4. return immediately to backlog draining;
5. repeat whenever the ordinary executable backlog reaches zero again.

User-reported bugs remain first within the bug queue. Reproducible E2E-discovered bugs come next, then ordinary executable issues. Preserve `user-reported` only for defects actually reported by a user.

Firefox and WebKit are optional diagnostics for browser-specific investigations. They are not required factory release coverage and must not delay issue closure, merges, or backlog draining.

## Selection priority

Choose work in this order:

1. A branch-caused failing check, merge conflict, or actionable review defect that prevents an active implementation PR from becoming mergeable.
2. The newest unclaimed open issue labeled both `user-reported` and `bug`.
3. The highest-priority unclaimed reproducible E2E-discovered `bug` issue.
4. The highest-value unclaimed executable issue, honoring explicit priority and dependencies, while deferring #679 until every other executable issue is closed.
5. Additional work on an existing PR only when required to complete its issue contract or make the PR mergeable.
6. Factory maintenance only when factory behavior blocks issue delivery.

A green, ready, review-passed, or merge-gated PR is excluded from ordinary work selection. It may be selected only for one final exact-head gate check and merge action.

Optional tests, cleanup, metadata edits, wording changes, evidence polishing, PR-body edits, architectural debate, or another minor slice do not outrank a coherent implementation for an unclaimed executable issue.

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
- Do not debate an already documented actionable finding across repeated heartbeats. Fix it, rebut it once with evidence, or preserve a real blocker and move on.

## Full-contract implementation

Implement the whole issue in one coherent non-draft PR whenever reasonably reviewable. Large coherent PRs are allowed.

Split only when Josh requests it, a real independent deployment boundary exists, destructive authorization must remain separate, unavoidable branch collisions make one PR unsafe, or the combined change is genuinely unreasonable to review.

A partial PR does not automatically outrank a fresh higher-priority issue. Continue the parent issue only when it wins under the selection order.

## Required work loop

Repeat until the selected issue reaches closure or a valid blocker:

`inspect contract -> implement closure-critical behavior -> focused validation -> commit -> push -> inspect exact SHA -> account for all review feedback -> repair blockers -> verify merge gates -> merge when eligible -> verify issue closure`

After work becomes blocked, merge-gated, or dependent on a human-only decision, preserve durable context and return to selection rather than polishing indefinitely.

## User-facing changelog gate

Every product, behavior, deployment, operational, or factory-tooling PR must update
`docs/changelog.md` before it can receive a pass verdict, ready marker, merge-gated marker, or
merge. Add the entry under the current date, group it by user-recognizable feature area, link the
PR number, and describe what changed and why it matters rather than narrating implementation
steps.

A documentation-only, test-only, generated-artifact-only, or strictly internal refactor PR may
omit a changelog entry only when its PR body explicitly states `Changelog: not user-facing` and
the worker verifies that the change has no user, operator, deployment, or factory behavior impact.
A missing required changelog entry is an actionable review defect and blocks readiness and merge.

Before merging, compare all merged PRs newer than the newest dated changelog section. If older
factory work is missing, repair the backlog in the current PR rather than recording only the
worker's own change.

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
- the merge method is allowed by repository settings;
- the worker supplies the exact expected head SHA to prevent merging a moved branch.

Do not enable auto-merge. Perform the merge only after the gates are currently true. If any gate becomes false or cannot be verified, do not merge and return to repair or selection.

After merging, verify whether the linked issue closed truthfully. If executable issue work remains, continue it under normal priority rather than declaring victory from the PR merge alone.

## Valid heartbeat outcomes

A normal heartbeat must accomplish at least one of these while executable issues remain:

- push substantive code, tests, or a migration;
- repair a blocking defect, review finding, CI failure, or merge conflict;
- open a coherent non-draft implementation PR for an executable issue;
- merge an exact-head PR whose complete gate set is satisfied;
- create evidence-backed bug issues from reproducible Chromium E2E failures during the backlog-zero phase;
- repair factory behavior that is directly blocking issue delivery.

Comments, labels, claims, reviews, PR-body edits, ready markers, help text, speculative plans, and optional test additions alone are not sufficient.

## Backlog-zero Chromium phase

Issue #679 is excluded from ordinary executable-backlog selection while any other executable issue remains open, unless disabled Chromium coverage itself blocks safe delivery.

When every other executable issue is closed:

1. prioritize #679 and restore the maintained Chromium Playwright CI suite;
2. merge that restoration only after the normal exact-head gates pass;
3. run or observe the complete maintained Chromium scenario set;
4. create one focused issue per independent reproducible product defect, linking the failing spec, evidence, and reproduction details;
5. label each defect `bug`; preserve `user-reported` only for bugs actually reported by a user;
6. resume normal selection immediately when those issues replenish the backlog.

Firefox and WebKit may be run manually when a browser-specific defect warrants them. They are not backlog-zero completion gates.

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
