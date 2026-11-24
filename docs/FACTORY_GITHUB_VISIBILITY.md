# Factory GitHub visibility

ComicPile factory work uses GitHub labels as a live dashboard around the canonical factory lease and review markers.

## Labels

Every active factory-owned issue or pull request carries the `factory` label.

Exactly one owner label identifies the worker responsible for the next action:

- `factory:<worker-number>` for active provider slots derived by [.github/scripts/factory_worker_slots.py](https://github.com/JoshCLWren/rotisserie/blob/main/factory/.github/scripts/factory_worker_slots.py);
- `factory:1` through `factory:5` are historical disabled ChatGPT schedules;
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

### Derived observability labels

`factory:merge-conflict` is derived, not authored. The reconciler adds it when GitHub
reports the exact pull-request head as merge-conflicted (`mergeable` false /
`CONFLICTING`, or merge state `dirty`/`DIRTY`) and removes it once GitHub reports a
resolved mergeability. Unresolved mergeability (`null`/`UNKNOWN`, which GitHub returns
briefly while recomputing after a push) leaves the current label untouched so the
reconciler never guesses; the next scheduled sweep settles it, which also catches a
conflict that develops only because the base branch moved. It is maintained for the
same non-draft factory-managed pull requests the enrollment sweep manages, so
manual-only and blocked operator holds are never relabeled.

It is observability, not workflow state:

- it is never a stage, so it stays out of `STAGE_LABELS`, stage precedence,
  `BLOCKED_LABELS`, and queue/claim selection;
- it never blocks or promotes review, CI, readiness, merge drains, or lease
  transitions, and it cannot make a PR selectable or unselectable;
- queue eligibility continues to read GitHub mergeability directly, so the label
  cannot drift into merge authority;
- the status dashboard counts it in the PR pipeline "Conflict" tile while keeping
  it out of its stage list.

There is no `factory:approved` label. Trusted exact-head review is recorded by
the controller's `comic-pile-factory-semantic-review-v1` marker; legacy
`review-v2` markers remain historical compatibility input. **`factory:changes-requested`**
is the blocking repair stage, **`factory:ci`** means review passed and required
checks are being verified, and **`factory:ready`** means every exact-head merge
gate is satisfied. Labels are never review or merge authorization.
`factory:merge-conflict` remains independent observability.

The labels are synchronized automatically from existing factory claim, progress, review, ready, release, and needs-human markers. Issue linkage follows an explicit `Closes #N`, `Fixes #N`, or `Resolves #N` reference, or the canonical standalone `Part of #N.` line (including `Part of #N and governed by #M.`). The canonical factory branch form is `factory/<worker>-<issue>-...`; a branch prefix alone does not replace the explicit linkage contract.

Only marker comments from the repository owner, members, or collaborators are trusted, and only `github-actions[bot]` is a trusted App actor. Greptile findings may route repair work but can never author factory markers, ownership, review verdicts, or readiness. Public commenters and untrusted fork branches cannot spoof factory ownership or stage labels.

Labels are visibility metadata, not merge evidence. A label-only change never counts as substantive factory progress and never overrides exact-head CI, review threads, mergeability, issue scope, or the canonical autonomous factory policy.

## GitHub review filters

GitHub's built-in review filters remain useful, but they report formal GitHub review state rather than the complete factory gate:

- **No reviews** finds pull requests with no submitted formal review.
- **Approved review** requires an `APPROVED` review.
- **Changes requested** requires a `CHANGES_REQUESTED` review.
- **Review required** depends on branch or ruleset requirements that have not yet been satisfied.
- **Reviewed by you**, **Not reviewed by you**, and **Awaiting review from you** are relative to the signed-in GitHub account.

Factory identity is mixed: worker 48 uses its provisioned Mark Cordova App when all three App secrets are present, while other workers use `PR_REBASE_TOKEN`; trusted controller markers remain `github-actions[bot]`. GitHub does not permit an author to approve their own pull request, so approval-oriented filters cannot be the sole factory dashboard. See [worker App identities](../.github/factory-worker-github-apps.md).

> **Greptile integration status:** disabled. The residual-finding rules below
> apply only to existing actionable feedback. Never request, wait for, or
> re-enable Greptile review.

Greptile (`greptile-apps[bot]`) submits `COMMENTED` reviews whose actionable findings live in inline review threads, each with a "Prompt To Fix With AI" block, plus a PR-body summary between `<!-- greptile_comment -->` markers and a `Greptile Review` check run. Greptile findings are high-priority, must-address review feedback:

- **Open Greptile findings (one rule, two implementations).** A review thread is an *open Greptile finding* when it is unresolved, not outdated, its first comment is by Greptile, and neither of these holds: (1) Greptile's latest comment is a reply that accepts the answer: it starts with an acceptance phrase ("You're right", "That addresses", "Good catch", "Makes sense", "Agreed", "Fair point", "Confirmed", and similar) and its first sentence has no contrast word (`but`, `however`, `although`, `though`, `still`, `remain`, `not`, `n't`), so "Thanks for the rebuttal, but the bug remains" stays open; (2) a trusted responder replied after Greptile's latest comment. Trusted responders are repository `OWNER`/`MEMBER`/`COLLABORATOR` accounts and the `github-actions` Bot actor (GraphQL `author.__typename == "Bot"`), which is how the wrapper posts outcomes. Login patterns alone never grant trust, so a look-alike account or a worker App login cannot answer a finding. When a thread has more than 20 comments and none of the last 20 is Greptile's, both implementations read the whole thread before deciding; if that read fails the thread stays open. An answered thread waits for Greptile, which resolves its own threads. The rule lives in `FACTORY_GREPTILE_JQ_DEFS` ([.github/scripts/factory-review-findings.sh](https://github.com/JoshCLWren/rotisserie/blob/main/factory/.github/scripts/factory-review-findings.sh)) and `greptileThreadState` ([.github/scripts/factory-visibility.cjs](https://github.com/JoshCLWren/rotisserie/blob/main/factory/.github/scripts/factory-visibility.cjs)); keep the two identical.
- **Repair routing.** [.github/scripts/factory-visibility.cjs](https://github.com/JoshCLWren/rotisserie/blob/main/factory/.github/scripts/factory-visibility.cjs) keeps a separate reviewer-bot allowlist (`REPAIR_ROUTING_REVIEWER_BOTS`, currently only `greptile-apps[bot]`) that is used only for repair routing. Routing is state-based. Every submitted review (Greptile's `COMMENTED` review, or any other), every new review-thread reply (`pull_request_review_comment: created`, which covers Greptile pushback posted as a plain reply), and every PR-body edit that carries a Greptile summary (`pull_request_target: edited`) recomputes from the live PR: its head, every review-thread page, and the PR-body summary. The PR moves to `factory:changes-requested` when (a) any open Greptile finding exists, or (b) the Greptile summary's "Last reviewed commit" equals the live head and it lists a finding (`alt="P<n>"`) that is unlinked and not answered by a trusted outcome comment posted after that review completed, linked to an open thread, or linked to a thread whose latest trusted answer predates the completion of Greptile's review of that head. That last case is a re-review that still lists the finding. Acknowledged and outdated threads never route. That covers re-reviews that only edit the summary and Greptile replies accepting a rebuttal (the #3890 flapping). Routing only ever adds `factory:changes-requested`; it never un-routes, and a no-op is not written. A trusted `CHANGES_REQUESTED` review still routes without the thread query. The allowlist does not change `trusted()`: Greptile can never author factory markers, ownership, review verdicts, or readiness.
- **Routing concurrency.** Review, review-comment, and PR-body-edit events run in a per-PR concurrency group (`factory-greptile-routing-pr-<n>`, `cancel-in-progress: false`). Every other event keeps the global `factory-issue-pr-state-reconciler` group. GitHub keeps one pending run per group, so the old global group let any burst of events replace a queued Greptile routing run for another PR (run 39140967515). Within one PR's group a newer pending run can still replace an older one. That is safe because the survivor recomputes from the same live state.
- **Greptile outcome gate.** The agent never posts or resolves Greptile replies itself. For every open Greptile finding listed in its mission (thread ids `PRRT_…`, and `GREPTILE_SUMMARY_<slug>` ids for findings listed only in the current-head PR-body summary), it writes a structured outcome to the git-excluded `.factory-greptile-outcomes.json` at the repository root: `{"outcomes":[{"thread_id":"PRRT_…","outcome":"fixed","explanation":"…"},{"thread_id":"PRRT_…","outcome":"rebutted","evidence":"…"}]}`. A `fixed` entry needs an explanation of at least 20 characters and either a fix pushed in this run or a `commit` that is already an ancestor of `HEAD`. A `rebutted` entry needs at least 40 characters of evidence. Right before any ready or review handoff, `greptile_outcome_gate` in [free-model-factory-worker.sh](https://github.com/JoshCLWren/rotisserie/blob/main/factory/.github/scripts/free-model-factory-worker.sh) runs four steps:
  1. It rebuilds the findings file and the open findings from a fresh, complete fetch.
  2. It validates the outcome file against them.
  3. It posts each valid outcome as `github-actions[bot]`: a reply on its thread, or a PR comment for a `GREPTILE_SUMMARY_*` id. The `comic-pile-factory-greptile-outcome-v1` marker carries the thread, outcome, head, and a digest of the text. A reply is skipped only when an identical marker already follows Greptile's latest comment, so a revised answer after Greptile pushback is always posted. Agent text is neutralized so it cannot carry a factory marker.
  4. It compares the open findings with the snapshot taken when the mission was built.

  `FACTORY_GATE_READY` is downgraded to a repair verdict when any open finding lacks a valid outcome or a reply cannot be posted. The reason is appended to the review log. When new findings arrived during the run, the PR is released as `factory:changes-requested` for re-dispatch instead. An incomplete fetch releases it to `factory:review` for another attempt. A repair push that leaves open findings without outcomes is released as `factory:changes-requested` rather than `factory:review`. A repair-stage "no change, ready" handoff is gated the same way. The wrapper never resolves threads.
- **Worker context.** Before every PR-mode agent run, each worker wrapper (OmniRoute, NVIDIA, free-model/Kilo via the shared primitives) calls the trusted [.github/scripts/factory-review-findings.sh](https://github.com/JoshCLWren/rotisserie/blob/main/factory/.github/scripts/factory-review-findings.sh) helper, staged from `main` at startup. It fetches unresolved review threads across every page (author, path, line, body, `isOutdated`, replies, with a notice when replies or pages are truncated), Greptile's top-level review body, the Greptile PR-body summary, and current-head PR-Agent check output, writes them to `/tmp/factory-review-findings-<worker>-pr<number>.md`, and injects that file into the PR mission. Greptile items are listed first and labeled HIGH PRIORITY, each tagged `[OPEN: outcome entry required]` or `[ANSWERED: awaiting Greptile]`, and the mission lists the required thread ids for the outcome file (see the Greptile outcome gate above). The mission build also clears any stale outcome file and snapshots the open findings to `<findings file>.open-before.json`. Other unresolved threads follow the normal fix-or-rebut rule. PR-Agent output (`PR Agent - Review` / `PR-Agent advisory review` check runs) is lower-priority advisory input.
- **Semantic verdict.** The semantic-verdict recovery reviewer must confirm that every Greptile finding was fixed or concretely rebutted and must return `FACTORY_GATE_BLOCKED`, never `FACTORY_GATE_READY`, otherwise. The existing exact-head merge gate still blocks on any unresolved review thread.
- **Pre-push fast checks.** Before committing an agent diff, both persistence paths in [free-model-factory-worker-primitives.sh](https://github.com/JoshCLWren/rotisserie/blob/main/factory/.github/scripts/free-model-factory-worker-primitives.sh) run `factory_run_fast_checks` from the trusted [.github/scripts/factory-fast-checks.sh](https://github.com/JoshCLWren/rotisserie/blob/main/factory/.github/scripts/factory-fast-checks.sh), staged from `main` at startup. Each touched file type gets its checks: `node --check` for `.mjs`/`.cjs`; CI-parity `ruff check .` and `ty check --error-on-warning` plus targeted pytest for `.py`, covering touched `test_*.py` files and `tests/test_<stem>.py` for each touched module; and `pnpm --filter frontend run typecheck` plus `eslint` on the touched files that still exist for `frontend/**/*.ts|tsx|mjs`. Added, modified, and deleted paths all count (renames count as both paths), so deleting a still-imported module still runs the whole-project checks. The toolchain (uv, pnpm) is installed on demand. When a check or the toolchain setup fails, the diff is not committed or pushed: the tree is reset, a `comic-pile-factory-fast-checks-failed-v1` comment with the log tail is posted for the next worker, and an approval from that run is downgraded to repair. A targeted-test failure whose only error is a database connection error does not block, because worker runners have no PostgreSQL (CI still runs those tests). OpenAPI generator or generated-artifact changes also run `node scripts/export_openapi_schema.mjs --check`. Root/frontend package manifests, lockfiles, and workspace manifests trigger the existing frozen install and frontend typecheck. The gate must not be disabled merely to avoid a failure; any incident override requires explicit owner authorization, a durable record, and restoration. The agent timeout reserves `FACTORY_FAST_CHECK_RESERVE_SECONDS` (default 240) for these checks.
- **Live wrapper scope.** The tracked dispatcher calls the reusable [Fixed Model Factory Entry workflow](../.github/workflows/free-model-factory-entry.yml), which runs the current Rotisserie shared worker primitives. The outcome gate and fast checks live in that upstream wrapper path; there is no tracked `free-model-factory-run.yml` caller.
- **Fail-closed pagination.** Every review-thread lookup reads every page. The wrappers' `current_head_review_blockers` gate uses `factory_count_unresolved_review_threads`, which fails the gate when a page is missing, unparseable, or still reports `hasNextPage`. The findings helper also pages through the comments nested in each unresolved thread. A thread whose comments cannot all be fetched is marked INCOMPLETE, and the mission is told not to emit `FACTORY_GATE_READY` until the agent has inspected the threads directly. Repair routing throws, leaving the reconciler run red, rather than treating a truncated listing with no findings seen as "no Greptile findings". It reads each thread's first comment (`comments(first:1)`) plus its 20 most recent comments. Only the comments after Greptile's latest one decide the rule, so that window is exact whenever it contains Greptile's latest comment or a trusted reply. The outcome gate fails closed (no `.open.json`) when thread or comment pagination is incomplete. The review controller already fails closed (`retry`) on truncated thread or comment pages.

The merge drain asks Jev to request CodeRabbit reviews on its existing cadence (a failed request never blocks a merge). CodeRabbit review bodies and inline comments stay advisory: they do not gate factory merges or route factory PRs into repair or worker prompts. Historical GitHub comments remain visible but do not grant factory authorization.

Independent reviewers should submit formal `APPROVE` or `REQUEST_CHANGES` reviews when the identity model permits. Do not add a required-approval branch rule until a reliable independent reviewer identity exists, because factory-authored pull requests cannot self-approve.

## Active heartbeat monitoring

Issue [#1093](https://github.com/JoshCLWren/comic-pile/issues/1093) is retired as the heartbeat/registry: factories never read or write its comments. Active worker identities and capacity are derived from the provider/slot registry at runtime; there is no committed expected-worker JSON or static model roster. Worker lifecycle and terminal outcomes are written to Neon by trusted workflow jobs and logs. <!-- docs-path-check: ignore -->

`.github/workflows/fixed-model-factory-dispatch-recovery.yml` runs every 15 minutes. It records per-worker freshness, last heartbeat timestamp, last run, and the latest classified runtime outcome in the job summary and the `factory-heartbeat-health` JSON artifact. The generated GitHub Pages fleet scoreboard uses the same observations. At 20 minutes an observation becomes stale; missing heartbeats are reported separately. One fresh worker cannot hide stale peers in these diagnostics.

Freshness and provider availability are separate. Weekly quota exhaustion is legitimate and appears as `quota-limited`, alongside stale/missing observation age. Staleness does not prove a crash and does not authorize worker launches or retries. Automatic recovery retains the fleet-wide gate: dispatch the existing quota-aware roster controller only when no active heartbeat is fresh. Per-worker monitoring never changes candidate selection, cooldowns, ownership, or merge authority.

## Historical disabled ChatGPT heartbeat schedules

Issue [#1093](https://github.com/JoshCLWren/comic-pile/issues/1093) is a retired registry and remains non-executable. Factories must never claim, implement, label, close, or comment on it or the watchdog's alert issue.

The five legacy ChatGPT schedules are disabled. Their permanent comments are historical records, excluded from active monitoring. The former heartbeat format and comment IDs are retained for provenance:

| Worker | Call sign | Slot (America/Chicago) | Comment ID |
|---|---|---:|---:|
| `chatgpt-factory-1` | Nova | `:40` | `5260477681` |
| `chatgpt-factory-2` | Booster Gold | `:52` | `5260477944` |
| `chatgpt-factory-3` | Starman | `:04` | `5260478160` |
| `chatgpt-factory-4` | Mister Miracle | `:16` | `5260478414` |
| `chatgpt-factory-5` | Death's Head | `:28` | `5260478724` |

The following template is retained only as a historical example. It is non-operative; no current worker may write these comments:

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

Historically, workers replaced the same comment at run end. That behavior is retired and prohibited; do not create or update heartbeat comments.

The former `.github/workflows/factory-heartbeat-watchdog.yml` workflow is absent. It does not monitor current workers. Do not resurrect disabled schedules or infer active-worker failures from these historical comments. <!-- docs-path-check: ignore -->

No heartbeat write is mandatory or permitted for the retired registry. Current lifecycle telemetry is written only by trusted workflows to Neon and never counts as substantive factory progress, extends a lease, or justifies ending a run.

## Durable GitHub App identity contract

This section states the durable App identity contract that every active factory worker App must satisfy. PR #3142 (worker 48, Mark Cordova) is the first instance; the rules below apply roster-wide.

### One App per active durable worker

The active worker identities are derived from the provider/slot registry, without a committed expected-worker JSON. Existing App identities remain persisted independently; absent or retired provider slots must not receive new credentials.

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
- [factory-visibility.cjs](https://github.com/JoshCLWren/rotisserie/blob/main/factory/.github/scripts/factory-visibility.cjs) `trusted()` / `performedViaUntrustedApp()`

A worker App slug (e.g., `mark-cordova`) with `OWNER`/`MEMBER`/`COLLABORATOR` association is **not trusted** for marker-driven label reconcile, review authorization, or any provenance-critical path. Only `github-actions[bot]` (the `GITHUB_TOKEN` actor) and human owner/member/collaborator comments (with no App) are trusted marker authors.

### Controller provenance remains authoritative

The review controller writes `comic-pile-factory-semantic-review-v1` and `comic-pile-factory-head-contributor-v1` markers as **entire comment bodies**. These markers carry `provenance_complete` for the exact head.

A native-style GitHub `APPROVE` review **does not** satisfy `head_has_authorized_approval` / `approval_can_promote` without controller marker provenance:
- When `provenance_complete == False` (no controller marker for the exact head), the head is fail-closed: **two distinct eligible reviewers** are required, and the producer cannot self-approve.
- When `provenance_complete == True`, **one eligible reviewer** authorizes the head.
- Every factory worker that authored the exact head under review is excluded from the eligible reviewer set, not only the worker that opened the PR. Contributor provenance is the union of controller head-contributor records and the declared branch/body producer.

This contract ensures that worker GitHub Apps can push and create PRs, but they cannot forge review authorization or trusted marker provenance.

