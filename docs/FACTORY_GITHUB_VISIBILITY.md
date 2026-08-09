# Factory GitHub visibility

ComicPile factory work uses GitHub labels as a live dashboard around the canonical factory lease and review markers.

## Labels

Every active factory-owned issue or pull request carries the `factory` label.

Exactly one owner label identifies the worker responsible for the next action:

- `factory:1` through `factory:5` for the scheduled ChatGPT factories;
- `factory:local` for the local OpenCode factory;
- `factory:unowned` when no worker currently owns the next action.

Exactly one stage label describes the current state:

- `factory:building`: implementation or repair is actively underway;
- `factory:review`: the exact current pull-request head needs review or re-review;
- `factory:changes-requested`: actionable review findings block progress;
- `factory:ci`: review passed and required exact-head checks are being verified;
- `factory:ready`: every exact-head merge gate is satisfied;
- `factory:blocked`: a genuine human, credential, or external blocker remains.

Every transition replaces the complete label set atomically. Preserve unrelated labels, remove all
stale owner and stage labels, and apply the single truthful owner and stage in one REST label-set
replacement. Sequential remove/add calls and add-only POST requests are not reconciliation because
other workers can observe contradictory intermediate state.

The labels are synchronized automatically from existing factory claim, progress, review, ready, release, and needs-human markers. Pull requests on `factory/*` branches are also recognized automatically. A linked issue claim supplies the initial pull-request owner when the branch name starts with `factory/<issue-number>-...`.

Only marker comments from the repository owner, members, or collaborators are trusted. Formal review transitions are accepted from trusted collaborators and CodeRabbit. Public commenters and untrusted fork branches cannot spoof factory ownership or stage labels.

Labels are visibility metadata, not merge evidence. A label-only change never counts as substantive factory progress and never overrides exact-head CI, review threads, mergeability, issue scope, or the canonical autonomous factory policy.

## GitHub review filters

GitHub's built-in review filters remain useful, but they report formal GitHub review state rather than the complete factory gate:

- **No reviews** finds pull requests with no submitted formal review.
- **Approved review** requires an `APPROVED` review.
- **Changes requested** requires a `CHANGES_REQUESTED` review.
- **Review required** depends on branch or ruleset requirements that have not yet been satisfied.
- **Reviewed by you**, **Not reviewed by you**, and **Awaiting review from you** are relative to the signed-in GitHub account.

The current factories authenticate as `JoshCLWren`, and their pull requests are also authored as `JoshCLWren`. GitHub does not permit an author to approve their own pull request, so the approval-oriented filters cannot be the sole factory dashboard with the current identity model.

CodeRabbit currently submits `COMMENTED` reviews even when it reports actionable comments. The visibility workflow therefore maps a CodeRabbit review body reporting one or more actionable comments to `factory:changes-requested`, while preserving GitHub's real formal review state.

If factory pull requests later use a separate GitHub App or machine-user identity, independent reviewers should submit formal `APPROVE` or `REQUEST_CHANGES` reviews. At that point the built-in review filters can become a stronger first-class view. Do not add a required-approval branch rule until a reliable independent reviewer identity exists, because the present single-account setup would deadlock factory-authored pull requests.
