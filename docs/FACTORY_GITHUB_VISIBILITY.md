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

## External heartbeat watchdog

Registry issue [#1093](https://github.com/JoshCLWren/comic-pile/issues/1093) is operational telemetry, not executable backlog work. Factories must never claim, implement, label, or close the registry or the watchdog's alert issue.

Each scheduled factory owns one permanent registry comment:

| Worker | Call sign | Slot (America/Chicago) | Comment ID |
|---|---|---:|---:|
| `chatgpt-factory-1` | Nova | `:40` | `5260477681` |
| `chatgpt-factory-2` | Booster Gold | `:52` | `5260477944` |
| `chatgpt-factory-3` | Starman | `:04` | `5260478160` |
| `chatgpt-factory-4` | Mister Miracle | `:16` | `5260478414` |
| `chatgpt-factory-5` | Death's Head | `:28` | `5260478724` |

At run start, replace only the assigned comment with:

```text
<!-- factory-heartbeat:v1 worker=<WORKER_ID> -->
## 🏭 Factory <WORKER_NUMBER> · <CALL_SIGN>
Scheduled slot: `<SLOT>` America/Chicago
Last run started: `<current UTC timestamp>`
Last run completed: `<previous completion timestamp or not yet reported>`
Worked on: selecting work
Outcome: running
Updated by: `<WORKER_ID>`
```

At run end, replace the same comment again, preserving the start timestamp and recording the current UTC completion timestamp, actual PR or issue, and truthful outcome. Do not create additional heartbeat comments.

The independent `.github/workflows/factory-heartbeat-watchdog.yml` workflow checks every 15 minutes. It reports a worker after 135 minutes without an update or after 90 minutes continuously marked `Outcome: running`. It maintains at most one alert issue and closes that alert when all five workers recover.

Heartbeat writes are mandatory telemetry but never substantive factory progress. They do not satisfy a heartbeat outcome, outrank delivery work, extend a lease, justify ending a run, or excuse a missing implementation. If the update fails, retry once through another available GitHub path, preserve the telemetry failure in the user-visible update when material, and continue delivery.

## Durable GitHub App identity contract

This section states the durable App identity contract that every active factory worker App must satisfy. PR #3142 (worker 48, Mark Cordova) is the first instance; the rules below apply roster-wide.

### One App per active durable worker

The canonical roster of active durable workers is `.github/factory-expected-workers.json` (`expected_workers` array). Each active worker gets exactly one GitHub App identity. Retired workers (`retired_workers`) keep their persisted mapping but never receive new credentials.

The provenance key is the **worker number** (e.g., `48`). All mapping, bootstrap, and credential logic keys off this number.

### Faker bootstrap is explicit and one-time

- **Version**: Faker `40.40.0` exactly (enforced at runtime).
- **Locale**: `en_US`.
- **Constructor**: a brand-new `Faker()` / `Faker(en_US)` instance per worker (not a shared instance).
- **Seed**: `seed_instance(worker_number + 100)`.
- **First call**: `name()` → persisted as `display_name`.
- **Collision fallback**: if the first `name()` is taken as a GitHub App name at creation time, call `name()` exactly once more on the **same seeded instance**, persist that second name as `display_name`, and stop. Do not keep calling Faker.
- **Never re-roll**: The `display_name` is written once to `.github/factory-worker-github-apps.json`. Subsequent reads load the persisted name; Faker is never invoked again for that worker.

### Persisted mapping never re-rolls

`.github/factory-worker-github-apps.json` stores:
- `worker` (provenance key)
- `display_name` (bootstrapped once)
- `app_id`, `app_login`, `installation_id` (null until Josh creates the App)
- `profile`: must contain "Autonomous ComicPile Factory worker"
- Model and worker number appear **only in human-readable PR text**, never in the App profile or metadata

### Trusted marker authors: `github-actions[bot]` only

`TRUSTED_FACTORY_APP_SLUGS == {"github-actions"}` and `TRUSTED_MARKER_APP_SLUGS == frozenset({"github-actions"})`.

**Worker Apps are excluded from every trusted-marker author path**, including:
- `factory_review_policy.performed_via_untrusted_app`
- `factory_work_policy.comment_is_trusted`
- `stale_pr_decay.comment_is_trusted`
- `factory-revocation-fence.comment_is_trusted`
- `factory-visibility.cjs` `trusted()` / `performedViaUntrustedApp()`

A worker App slug (e.g., `mark-cordova`) with `OWNER`/`MEMBER`/`COLLABORATOR` association is **not trusted** for marker-driven label reconcile, review authorization, or any provenance-critical path. Only `github-actions[bot]` (the `GITHUB_TOKEN` actor) and human owner/member/collaborator comments (with no App) are trusted marker authors.

### Controller provenance remains authoritative

The review controller writes `comic-pile-factory-semantic-review-v1` and `comic-pile-factory-head-contributor-v1` markers as **entire comment bodies**. These markers carry `provenance_complete` for the exact head.

A native-style GitHub `APPROVE` review **does not** satisfy `head_has_authorized_approval` / `approval_can_promote` without controller marker provenance:
- When `provenance_complete == False` (no controller marker for the exact head), the head is fail-closed: **two distinct eligible reviewers** are required, and the producer cannot self-approve.
- When `provenance_complete == True`, **one eligible reviewer** authorizes the head.
- The producer (worker that opened the PR) is **always excluded** from the eligible reviewer set, regardless of provenance.

This contract ensures that worker GitHub Apps can push and create PRs, but they cannot forge review authorization or trusted marker provenance.

