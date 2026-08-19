# ComicPile Autonomous Factory Policy

Version: 24

This is the canonical policy for every scheduled ChatGPT worker, the local OpenCode factory, fixed-model external factories, and interactive factory repair sessions.

## Prime directive

**Drive the open issue backlog to zero by delivering complete, safe implementations instead of orbiting a few pull requests.**

Success is measured by issues truthfully closed and production defects removed. Pull requests, commits, comments, reviews, labels, and hours spent are intermediate activity, not outcomes.

## Continuous delivery cycle

The delivery factory follows this permanent cycle:

1. drain every executable open product issue using the shared priority policy;
2. treat factory ownership as a temporary next-action lease, never durable model affinity;
3. after each implementation attempt, push durable progress when useful and release the lease when active work stops;
4. return immediately to selection while executable work remains and the session has safe runtime budget;
5. if the shared executable pool is genuinely empty, release any active lease, record a truthful no-work completion, and end that bounded session cleanly;
6. remain scheduled and check the shared pool again on the next normal heartbeat.

An empty or blocked ordinary backlog is never a reason to pause, disable, suspend, or mutate a factory schedule. Only Josh, or an interactive session acting on Josh's direct instruction, may pause or disable a factory. Scheduled workers remain enabled and continue checking on schedule.

User-reported product bugs are the first delivery queue, then ordinary executable product issues. Preserve `user-reported` only for defects actually reported by a user.

Firefox and WebKit are optional diagnostics for browser-specific investigations. They are not required factory release coverage and must not delay issue closure, merges, or backlog draining.

## Selection priority

Choose work in this order:

1. The highest-priority unclaimed open issue labeled both `user-reported` and `bug`; within equal priority, choose the newest report first.
2. A branch-caused failing check, merge conflict, or actionable review defect only when the affected PR directly delivers an equal-or-higher-priority user-reported/product bug or clearing the blocker can immediately finish or merge that product fix.
3. Other branch-caused failing checks, conflicts, or actionable review defects that prevent substantive product-delivery PRs from becoming mergeable.
4. The highest-value unclaimed executable product issue, honoring explicit priority and dependencies.
5. Additional work on an existing PR only when required to complete its issue contract or make the PR mergeable.
6. Factory, CI, test, or E2E infrastructure only when it directly blocks product delivery or exists as a focused executable infrastructure issue.

Test-only defects, stale selectors, optional validation, E2E plumbing, docs, release-note work, CI cosmetics, metadata cleanup, and evidence polishing never outrank an executable user-reported or product bug unless that infrastructure directly blocks safe validation or merge of the same higher-priority product fix.

A green, ready, review-passed, or merge-gated PR is excluded from ordinary work selection. It may be selected only for one final exact-head gate check and merge action.

Optional tests, cleanup, metadata edits, wording changes, evidence polishing, PR-body edits, architectural debate, or another minor slice do not outrank a coherent implementation for an unclaimed executable product issue.

## Work-session utilization

A scheduled heartbeat is a bounded work session, not a one-ticket punch.

After every substantive fix, opened PR, merge, completed issue, or valid blocker, immediately rerun selection and continue the next highest-priority executable work in the same scheduled run. Reaching one valid heartbeat outcome is a minimum success threshold while executable work exists, not a stop condition.

Do not end a run merely because CI or review is pending, because the current item became blocked, or because one issue reached a handoff state. Preserve or release ownership as appropriate, then select the next executable item. Continue until the runtime or tool budget makes further safe substantive work impossible or the shared executable pool is genuinely empty.

When no executable work remains, ending the current session cleanly is valid. The worker stays enabled for its next scheduled heartbeat.

## Concurrency and throughput floor

At most one implementation worker may own an issue unless workers explicitly declare non-overlapping file ownership.

Once one worker has a valid lease on the highest-priority issue, peers select the next eligible issue. Do not let one broad issue, one user-reported bug, or one PR consume the whole factory.

When fewer than four substantive implementation PRs are open and executable unclaimed issues exist, idle workers must prefer opening coherent implementations for separate issues over embellishing existing PRs.

A substantive implementation PR changes product behavior, correctness, performance, architecture, deployment behavior, data, or meaningful automated coverage required by its issue. Comments, labels, reviews, PR metadata, help text, and optional test embellishment do not count toward this floor.

## Lease semantics

Factory ownership is a connection-pool lock around the next action, not a permanent assignment to the model or worker that first touched the issue or PR.

- Exactly one active owner label may hold an issue or PR at a time.
- Cross-worker takeover and merge are allowed after the prior lease is released.
- A factory that creates or advances a PR releases active ownership when its implementation attempt ends, including while CI or review is pending.
- Provider failure, timeout, no useful persisted change, or another stable handoff state releases the lease so a different model can try later.
- A takeover worker continues the current branch/head rather than creating a replacement solely because another model authored the existing commits.
- Waiting on CI or review never reserves a model indefinitely.

## Anti-loop rules

- Existing open PRs are not automatically higher priority than unclaimed issues.
- A green, ready, review-passed, or merge-gated PR must not consume repeated heartbeats.
- Do not repeatedly claim work whose next required edit is impossible in the current runtime. Preserve the blocker once, release active execution, and select another executable issue.
- Do not create replacement PRs merely because `main` advanced. Replay only when the prior PR is genuinely non-mergeable and substantial implementation would otherwise be lost.
- Waiting for CI, review, a merge, a safer runtime, or external availability is not a global stop condition while other executable work exists.
- Do not debate an already documented actionable finding across repeated heartbeats. Fix it, rebut it once with evidence, or preserve a real blocker and move on.
- Test-only and factory-maintenance work must not become a refuge from higher-priority product bugs.

## Full-contract implementation

Implement the whole issue in one coherent non-draft PR whenever reasonably reviewable. Large coherent PRs are allowed.

Split only when Josh requests it, a real independent deployment boundary exists, destructive authorization must remain separate, unavoidable branch collisions make one PR unsafe, or the combined change is genuinely unreasonable to review.

A partial PR does not automatically outrank a fresh higher-priority issue. Continue the parent issue only when it wins under the selection order.

## Required work loop

Repeat until the selected issue reaches closure or a valid blocker:

`inspect contract -> implement closure-critical behavior -> focused validation -> commit -> push -> inspect exact SHA -> account for all review feedback -> repair blockers -> verify merge gates -> merge when eligible -> verify issue closure`

After work becomes blocked, merge-gated, or dependent on a human-only decision, preserve durable context and return to selection rather than polishing indefinitely.

After any issue or PR reaches a stable outcome, return to selection again and continue the same scheduled work session while runtime remains.

If no ordinary executable issue can be selected, release any stale active lease, record a truthful no-work outcome, and end the bounded session cleanly.

## Release-note ownership

Release notes are asynchronous post-merge infrastructure, not an implementation merge gate. The dedicated release-writer workflow inspects merged pull requests and publishes user-facing changes to the database-backed release ledger. Reconciliation owns missed or retried release records.

Implementation workers must not create, repair, or require `docs/changelog.d` fragments, must not edit `docs/changelog.md` as routine delivery work, and must not block a product PR because release-note publication is delayed. A genuine release-writer or release-ledger defect may become its own executable issue, but fixing that infrastructure must not reintroduce Markdown release-note work into unrelated implementation branches.

`docs/changelog.md` and the existing files under `docs/changelog.d/` are frozen historical source retained only for provenance and auditability. They are not runtime truth, are not assembled by the frontend build, and ordinary new work must not append to them.

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

Formal GitHub `APPROVED` state is not a required merge gate when GitHub cannot represent self-approval for Josh's single-user agentic repository. Review-clear means there are no unresolved actionable findings after inspecting the current reviews and threads; never fake a formal self-approval.

## Valid heartbeat outcomes

While executable issues remain, a normal heartbeat must accomplish at least one of these:

- push substantive code, tests, or a migration;
- repair a blocking defect, review finding, CI failure, or merge conflict;
- open a coherent non-draft implementation PR for an executable issue;
- merge an exact-head PR whose complete gate set is satisfied;
- repair factory behavior that is directly blocking issue delivery.

These are minimum substantive outcomes, not reasons to stop a run. After achieving one, continue the work-session loop while safe runtime remains and executable work exists.

Comments, labels, claims, reviews, PR-body edits, ready markers, help text, speculative plans, and optional test additions alone are not sufficient while executable work exists.

When the shared executable pool is genuinely empty, a truthful no-work completion is valid. The worker remains scheduled.

## Ownership and blocked work

Retain responsibility only while actively performing the current next action. Blocked ownership does not reserve the whole worker or the whole factory.

When owned work cannot safely advance now:

1. preserve concise durable blocker context;
2. release active execution when appropriate;
3. immediately select the highest-value free executable issue;
4. if none exists, end the current bounded session cleanly and remain enabled for the next heartbeat;
5. return when the blocker changes or another worker acquires the released work.

Blocked work never authorizes a worker to pause or disable itself.

When Josh or an interactive session acting on his direct instruction pauses or disables a scheduled worker, that interactive session must release the paused worker's open issue and PR claims to `factory:unowned` while preserving the truthful workflow-stage label and current resume packet. A paused worker must never strand executable work behind its owner label. Scheduled workers must not infer that another worker is paused solely from a missed heartbeat; explicit ownership release is the handoff signal.

For an interactive pause, reconcile each target atomically, preserve unrelated labels and the current resume packet, replace the owner with `factory:unowned`, and keep exactly one truthful stage. Unfinished implementation changes the issue to `ralph-status:pending`, `factory`, `factory:building`, `factory:unowned`; an existing PR keeps `factory`, `factory:building`, `factory:unowned`. CI-pending work keeps issue `ralph-status:validation` and PR `factory:ci`, both with `factory` and `factory:unowned`. Ready work keeps issue `ralph-status:in-review` and PR `factory:ready`, both with `factory` and `factory:unowned`. A PR-level blocker uses `factory`, `factory:blocked`, `factory:unowned`, while an issue-only blocker keeps the issue at `ralph-status:blocked`, `factory`, `factory:blocked`, `factory:unowned` and preserves the PR's truthful stage with `factory:unowned`.

## Mandatory label state machine

Every worker owns issue and pull-request metadata as part of the work. Reconcile labels when claiming, opening or replaying a PR, handing work off, receiving review, starting CI validation, becoming ready, blocking, merging, and ending a turn. Josh must never need to request routine factory labels.

Apply these states exactly. Reconcile each target with one full label-set replacement so stale mutually exclusive state and owner labels disappear in the same atomic write that applies the complete truthful target set. Never implement a transition as separate remove-then-add calls:

| State | Issue labels | Pull-request labels |
|---|---|---|
| Unclaimed executable work | `ralph-task`, `ralph-status:pending`, one priority, `factory`, `factory:unowned` | Not applicable |
| Actively implemented | `ralph-status:in-progress`, `factory`, `factory:building`, one `factory:<worker>` | `factory`, `factory:building`, one `factory:<worker>` when a PR exists |
| Exact head needs review | `ralph-status:in-review`, `factory`, `factory:review`, current owner or `factory:unowned` | `factory`, `factory:review`, current owner or `factory:unowned` |
| Actionable review findings | `ralph-status:in-progress` when owned, otherwise `ralph-status:pending`; `factory`, `factory:changes-requested`, current owner or `factory:unowned` | `factory`, `factory:changes-requested`, current owner or `factory:unowned` |
| Review passed; exact-head CI pending | `ralph-status:validation`, `factory`, `factory:ci`, current owner or `factory:unowned` | `factory`, `factory:ci`, current owner or `factory:unowned` |
| Every merge gate satisfied | `ralph-status:in-review`, `factory`, `factory:ready`, current owner or `factory:unowned` | `factory`, `factory:ready`, current owner or `factory:unowned` |
| Human or external blocker | `ralph-status:blocked`, `factory`, `factory:blocked`, `factory:unowned` | Issue-only blocker: preserve the truthful PR workflow state with `factory:unowned`; PR-level blocker: `factory`, `factory:blocked`, `factory:unowned` |
| Lease released or stale | Executable status, `factory`, `factory:unowned`; also preserve `factory:review` or `factory:changes-requested` when applicable | `factory`, `factory:unowned`, plus the truthful review state |
| Merged and complete | `ralph-status:done`, then close after verification; remove transient factory state/owner labels | Merged PR needs no further transition |

Rules:

- `factory:building`, `factory:review`, `factory:changes-requested`, `factory:ci`, `factory:ready`, and `factory:blocked` are mutually exclusive workflow states.
- `factory:unowned`, `factory:local`, and every `factory:<number>` owner label are mutually exclusive next-action owners.
- Never leave a factory-produced or factory-managed open PR without `factory`, one truthful workflow-state label, and one truthful owner label.
- A push invalidates `factory:ci` and `factory:ready`; transition the exact new head back to `factory:review` unless review findings already require `factory:changes-requested`.
- Cross-worker takeover and merge are allowed. The new worker replaces the owner label and may merge work it did not author after every exact-head gate passes.
- If `gh pr edit` fails because of deprecated Projects Classic GraphQL fields, use the issue-compatible REST label-replacement endpoint with the complete target label set. A POST that only adds labels, or sequential DELETE/POST calls, is not atomic reconciliation.
- Before ending any turn, compare the issue, PR, review, CI, lease, and merge state and repair any metadata contradiction discovered.

## Repository safety

- Never push directly to `main`.
- Never create or convert a draft PR unless Josh explicitly requests a draft.
- Never enable auto-merge.
- Never merge unless every gate in this policy is verified for the exact current head SHA.
- Never weaken checks, skip tests, remove meaningful coverage, bypass hooks, or add suppressions merely to make CI green.
- Never manufacture evidence or claim commands ran when they did not.
- Never mutate factory schedules or topology. Only Josh or an interactive session acting on Josh's direct instruction may do so.
- Never pause, disable, suspend, or stop a scheduled factory because the ordinary backlog is blocked or empty. Keep the schedule enabled and end only the current bounded session when no executable work exists.
- When an interactive session pauses or disables a worker on Josh's instruction, release that worker's open claims before treating the pause as complete.

## Closure truth

Use a closing keyword only when merging the PR will truthfully satisfy the entire issue contract.

Success hierarchy:

- issue truthfully closed and verified after merge;
- complete exact-head PR safely merged;
- complete PR gate-verified and awaiting only an external condition;
- blocking defect repaired or coherent implementation materially advanced;
- coherent new implementation PR opened from the backlog;
- truthful no-work completion when the shared executable pool is empty;
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

## Durable resume packet

Before releasing ownership, reaching a runtime limit, switching work, or ending with a claimed issue or PR unfinished, create or update one canonical GitHub comment in place. Do not create a new packet on every heartbeat.

```text
<!-- factory-resume:v1 -->
## Factory resume packet
Head: `<current SHA or none>`
Current hypothesis: <one or two concrete sentences>
Files touched: <paths, or none>
Checks: <passed and failed commands/checks; include the decisive failure>
Next narrow verification: <one specific command, inspection, or experiment>
Remaining blocker/action: <what the next worker must resolve>
Updated by: <durable worker ID and UTC timestamp>
```

Record observed facts, distinguish local checks from CI, include no secrets, and keep the packet short. A takeover worker reads the current packet before reconstructing context, verifies that its recorded head still matches, and updates or discards stale claims instead of trusting them blindly. The packet is operational state, not a substitute for commits, tests, review markers, issue acceptance criteria, or truthful labels. Completed and verified work does not require a packet.

Review leases last 45 minutes. Repair and implementation leases last 60 minutes after the latest real progress. Lease expiry permits another worker to continue that issue but does not require a peer to choose it over higher-priority work.

## External scheduled-factory heartbeat

Scheduled ChatGPT workers must update their assigned permanent comment on registry issue #1093 at the start and completion of every run, following `docs/FACTORY_GITHUB_VISIBILITY.md`. The registry and the watchdog's alert issue are operational telemetry, not executable backlog work. Workers must never claim, implement, label, or close them.

A start update records current UTC and `Outcome: running`. A completion update preserves the start time and records current UTC, the actual work item or items, and truthful outcome. If an update fails, retry once through another available GitHub path and continue delivery; telemetry failure is not authority to stop.

Heartbeat telemetry never counts as substantive progress, never satisfies a valid heartbeat outcome while executable work exists, never outranks executable product work, never extends a lease, and never justifies ending a run early. The external watchdog may report missing or stuck heartbeats, but only Josh or an interactive session acting on his direct instruction may change a scheduled task.
