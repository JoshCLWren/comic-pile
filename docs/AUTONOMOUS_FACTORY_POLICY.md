# ComicPile Autonomous Factory Policy

Version: 15

This is the canonical policy for every scheduled ChatGPT worker, the local OpenCode factory, and interactive factory repair sessions.

## Prime directive

**Deliver substantive issue implementations without allowing a few existing pull requests to consume the entire factory.**

The issue remains the unit of ownership, but ownership does not mean every worker must orbit the same incomplete or blocked issue. Maintain several distinct substantive implementation branches whenever the executable backlog supports it.

## Selection priority

Choose work in this order:

1. A branch-caused failing check, merge conflict, or actionable review defect that prevents an active implementation PR from becoming mergeable.
2. The newest unclaimed open issue labeled both `user-reported` and `bug`.
3. The highest-value unclaimed executable issue, honoring explicit priority and dependencies.
4. A stale-branch semantic replay only when needed to rescue substantial implementation that would otherwise be lost.
5. Additional work on an existing PR only when required to complete its issue contract or make the PR mergeable.
6. Factory maintenance only when factory behavior blocks delivery.

Optional tests, cleanup, metadata edits, wording changes, evidence polishing, PR-body edits, or another minor slice do not outrank opening a coherent implementation branch for an unclaimed executable issue.

## Throughput floor

When fewer than four substantive implementation PRs are open, workers should prefer opening a coherent PR for a new unclaimed executable issue over embellishing an existing PR.

A substantive implementation PR changes product behavior, correctness, performance, architecture, deployment behavior, data, or meaningful automated coverage required by its issue. Help-text-only changes, PR metadata, comments, labels, reviews, and optional test embellishment do not count toward this floor.

## Anti-loop rules

- A green, ready, review-passed, or Josh-waiting PR is excluded from work selection.
- Do not repeatedly claim an issue whose next required edit is impossible in the current runtime. Preserve the blocker once, then select another executable issue in the same heartbeat.
- Do not create replacement PRs merely because `main` advanced. Replay only when the prior PR is genuinely non-mergeable and its substantial implementation remains needed.
- At most one implementation worker may own an issue unless workers explicitly declare non-overlapping file ownership.
- Do not let one user-reported bug consume every worker. Once one worker has an active implementation lease, peers select the next eligible issue.
- Existing open PRs are not automatically higher priority than unclaimed issues.
- Waiting for CI, Josh, review, a safer runtime, or a merge is not a global stop condition while other substantive executable work exists.

## Ownership and blocked work

Retain responsibility for a claimed issue through implementation, validation, repair, and integration readiness. However, blocked ownership does not reserve the whole worker or the whole factory.

When the owned issue cannot be safely advanced now:

1. preserve concise durable blocker context;
2. do not repeat the same failed claim on every heartbeat;
3. immediately select the highest-value free executable issue;
4. return when the blocker changes or a suitable runtime is available.

Workers may cooperate on one issue only with explicit non-overlapping file ownership. Otherwise, one active implementation lease wins and peers choose different issues.

## Full-contract implementation

Implement the whole issue in one coherent non-draft PR whenever reasonably reviewable. Large coherent PRs are allowed. Split only when Josh requests it, an independent deployment boundary is real, destructive authorization must be separate, unavoidable collisions make one branch unsafe, or the combined change is genuinely unreasonable to review.

A split PR does not automatically outrank a fresh executable issue. Continue the parent issue when it is the highest-value executable choice under the selection policy, not merely because it already has a PR.

## Required work loop

Repeat until the selected issue reaches a valid stop condition:

`inspect contract -> implement closure-critical behavior -> focused test -> commit -> push -> inspect exact SHA and CI -> repair blocking findings`

After the selected issue becomes blocked, ready, or dependent on Josh, return to selection rather than polishing it indefinitely.

## Valid heartbeat outcomes

A normal heartbeat must accomplish at least one of these while executable issues remain:

- push substantive code, tests, or a migration;
- repair a blocking defect or merge conflict;
- open a coherent non-draft implementation PR for an executable issue;
- repair factory behavior that is directly blocking delivery.

Comments, labels, claims, reviews, PR-body edits, ready markers, help text, and optional test additions alone are not sufficient.

## Repository safety

- Never push directly to `main`.
- Never create or convert a draft PR unless Josh explicitly requests a draft.
- Never merge or enable auto-merge without Josh explicitly authorizing that merge.
- Never weaken checks, skip tests, remove meaningful coverage, bypass hooks, or add suppressions merely to make CI green.
- Never manufacture evidence or claim commands ran when they did not.

## Validation and review

Run focused validation that directly exercises each change. Let CI carry the expensive configured matrix. Inspect exact failing jobs and logs, then repair understood defects directly.

Every push invalidates prior review and readiness. Re-fetch the exact SHA, review state, mergeability, and CI before declaring integration readiness.

## Closure truth

Use a closing keyword only when merging the PR will truthfully satisfy the entire issue contract. A ready PR may wait for Josh without monopolizing workers.

Success hierarchy:

- issue truthfully closed;
- complete PR ready to close the issue;
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

Review leases last 45 minutes. Repair and implementation leases last 60 minutes after the latest real progress. Lease expiry permits another worker to continue that issue, but does not require a peer to choose it over a higher-value unclaimed issue.

## Communication

Report meaningful issue-level outcomes. Do not celebrate activity. State the selected issue, substantive change, evidence, and exact blocker when one exists.