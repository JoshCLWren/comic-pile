# ComicPile Autonomous Factory Policy

Version: 11

This is the canonical policy for every scheduled ChatGPT worker, the local OpenCode factory, and interactive factory repair sessions.

## Prime directive

**Finish the issue. Do not stop at a commit, PR, review, CI run, or ready marker.**

The issue is the unit of ownership. A heartbeat is merely time available to advance that issue. Use all available time and tools to move the owned issue toward truthful closure.

## No early exit

After every commit, push, review, repair, CI result, rebase, or PR update, immediately ask:

> Is there executable work remaining for this owned issue that I can safely do now?

If yes, continue working in the same heartbeat.

The following are never valid reasons to stop by themselves:

- one substantive commit was pushed;
- one PR was opened or updated;
- focused tests passed;
- CI is pending, queued, or green;
- a review was completed;
- a ready marker was posted;
- a bounded slice was completed;
- a `Remaining work` list was written;
- the diff became large;
- the next task is harder than the first task.

A worker may end only when one of these is true:

1. the issue is complete and the PR truthfully closes it;
2. the PR is integration-ready and no additional issue work can safely proceed before Josh merges it;
3. a genuine human-only decision, credential, permission, destructive authorization, or unavailable external system blocks the next executable action;
4. all safe write paths actually failed;
5. continued work would exceed a clearly stated, evidence-based safety boundary.

Before ending, explicitly verify that no remaining acceptance criterion can be implemented now. Merely naming remaining work proves the opposite and requires continuing.

## Own an issue, not a PR

Once an issue is claimed, stay with it through implementation, tests, review feedback, CI failures, rebases, conflicts, follow-up fixes, integration readiness, and post-merge remaining work until the issue closes or a genuine human-only blocker exists.

Do not release ownership because a lease hour elapsed, a new heartbeat started, one PR merged, or another issue looks easier. A merged partial PR does not release the parent issue.

Workers may cooperate on one issue only with explicit non-overlapping file ownership. Five workers do not imply five unrelated issues.

## Implement the full contract

Implement the whole issue in one coherent non-draft PR whenever reasonably reviewable. Large coherent PRs are allowed. Difficult work, broad diffs, and high line counts are not reasons to split.

Split only when Josh requests it, an independent deployment boundary is real, unavoidable collisions make one branch unsafe, destructive authorization must be separate, or the combined change is genuinely unreasonable to review. If a split is unavoidable, keep issue ownership and continue the next slice immediately when safe.

Do not use the words `stage`, `foundation`, or `remaining work` to justify avoidable partial delivery. A partial PR is coordination, not completion.

## No planning PRs

Never open planning-only, architecture-only, inventory-only, or implementation-plan PRs unless documentation is the issue's explicit deliverable.

Planning belongs in scratch work or concise issue comments. Documentation may accompany or follow implementation, but it may not substitute for code, tests, migrations, or executable evidence. Writing extensive documentation instead of implementing is a policy failure.

## Selection priority

Choose work in this order:

1. exact branch-caused CI failure or review defect on an owned issue;
2. executable work needed to close an issue already represented by an open or recently merged PR;
3. conflict or rebase repair on an owned issue;
4. strict current-SHA review and repair of an owned issue;
5. highest-value unclaimed executable issue;
6. factory maintenance only when factory behavior blocks delivery.

Do not start a new issue while an owned issue has executable remaining work.

## Required work loop

Repeat this loop until a valid stop condition exists:

`inspect issue contract -> choose next closure-critical change -> implement -> focused test -> commit -> push -> inspect exact SHA and CI -> repair if needed -> choose next closure-critical change`

Do not wait passively for broad CI when independent issue work can continue safely on the same branch. Do not make speculative edits to code covered by pending evidence, but continue unrelated acceptance criteria that do not depend on that result.

## Repository safety

- Never push directly to `main`.
- Never create or convert a draft PR unless Josh explicitly requests it.
- Never merge or enable auto-merge without Josh explicitly ordering that specific merge.
- Never weaken checks, skip tests, remove meaningful coverage, bypass hooks, or add suppressions merely to make CI green.
- Never manufacture evidence or claim commands ran when they did not.

## Validation and repair

Run focused tests, lint, type checks, migration checks, or browser specs that directly exercise each change. Let CI carry the expensive configured matrix.

Inspect exact failing jobs and logs. Repair understood defects directly. CI failures, merge conflicts, review findings, browser inconvenience, and the need to write more code are ordinary engineering, not human blockers.

Every push invalidates prior review and readiness. Re-fetch the exact SHA, complete conversation, mergeability, and CI before declaring readiness.

## Closure truth

Use a closing keyword only when merging the PR will truthfully satisfy the entire issue contract. Otherwise keep the issue open, but continue implementing rather than ending with a status report.

Success hierarchy:

- issue truthfully closed: highest value;
- complete PR ready to close the issue: high value;
- branch repaired and full issue materially advanced: positive value;
- one isolated commit or review: minor evidence only;
- planning PR, avoidable split, or stopping with executable work remaining: policy failure.

## Markers and leases

Use the existing canonical marker schemas:

- issue claim: `<!-- comic-pile-factory-implement-claim-v3:issue-<n>:<worker>:<epoch>:attempt-<n> -->`
- issue progress: `<!-- comic-pile-factory-implement-progress-v3:issue-<n>:<worker>:<epoch> -->`
- review claim: `<!-- comic-pile-factory-review-claim-v2:<sha>:<worker>:<epoch> -->`
- verdict: `<!-- comic-pile-factory-review-v2:<sha>:pass -->` or `changes-required`
- repair claim: `<!-- comic-pile-factory-fix-claim-v3:<sha>:<worker>:<epoch>:attempt-<n> -->`
- repair progress: `<!-- comic-pile-factory-fix-progress-v3:<sha>:<worker>:<epoch> -->`
- ready: `<!-- comic-pile-factory-ready-v2:<sha> -->`
- needs human: `<!-- comic-pile-factory-needs-human-v2:<sha-or-issue> -->`
- released: `<!-- comic-pile-factory-claim-released-v3:<target>:<worker>:<epoch>:<reason> -->`

Review leases last 45 minutes. Repair and implementation leases last 60 minutes after the latest real progress. Lease expiry permits another worker to continue the same issue; it does not make the issue optional.

## Communication

Report only meaningful issue-level outcomes. Do not celebrate activity. Do not end with a `Remaining work` recital when that work is executable. Either continue doing it or state the exact valid stop condition preventing it.
