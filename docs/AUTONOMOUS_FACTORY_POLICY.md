# ComicPile Autonomous Factory Policy

Version: 27

This is the canonical policy for every scheduled ChatGPT worker, the local OpenCode factory, fixed-model external factories, and interactive factory repair sessions.

## Prime directive

**Drive the open issue backlog to zero by delivering complete, safe implementations instead of orbiting a few pull requests.**

Success is measured by issues truthfully closed and production defects removed. Pull requests, commits, comments, reviews, labels, and hours spent are intermediate activity, not outcomes.

For original owner-requested engineering objectives, follow [`docs/OBJECTIVE_FIRST_ENGINEERING_CONTRACT.md`](OBJECTIVE_FIRST_ENGINEERING_CONTRACT.md): do not redefine the finish line through a self-authored issue, partial PR, shadow-only phase, or a ready-to-merge milestone. A runnable objective is done only after merged, deployed, and end-to-end verified on the real intended path; issue-level closure may be narrower than the owner's objective.

## Continuous delivery cycle

The delivery factory follows this permanent cycle:

1. drain every executable open product issue using the shared priority policy;
2. treat factory ownership as a temporary next-action lease, never durable model affinity;
3. after each implementation attempt, push durable progress when useful and release the lease when active work stops;
4. return immediately to selection while executable work remains and the session has safe runtime budget;
5. if the shared executable pool is genuinely empty, release any active lease, record a truthful no-work completion, and end that bounded session cleanly;
6. remain scheduled and check the shared pool again on the next normal heartbeat.

An empty or blocked ordinary backlog is never a reason to pause, disable, suspend, or mutate a factory schedule. Only Josh, or an interactive session acting on Josh's direct instruction, may pause or disable a factory. Scheduled workers remain enabled and continue checking on schedule.

User-reported product bugs are the first delivery queue. Reproducible E2E-discovered product bugs come after them, then ordinary executable product issues. Preserve `user-reported` only for defects actually reported by a user.

Firefox and WebKit are optional diagnostics for browser-specific investigations. They are not required factory release coverage and must not delay issue closure, merges, or backlog draining.

## Selection priority

Issues labeled `epic` or `prd` are not ordinary autonomous factory candidates. An issue whose body contains `<!-- factory-execution:manual-only -->` is also excluded from autonomous selection even if its other labels would normally make it executable. Use the marker for coordination, architecture, integrated acceptance, destructive-authorization, and similar human/interactive gates. Narrow corrective child issues remain executable when they have an explicit frozen contract, including children inside a domain under an architecture hold. A factory implements that frozen contract exactly, does not reinterpret the governing architecture, and does not lift or close the hold.

Choose work in this order:

1. The highest-priority unclaimed open issue labeled both `user-reported` and `bug`; within equal priority, choose the newest report first.
2. A branch-caused failing check, merge conflict, or actionable review defect only when the affected PR directly delivers an equal-or-higher-priority user-reported/product bug or clearing the blocker can immediately finish or merge that product fix.
3. Other branch-caused failing checks, conflicts, or actionable review defects that prevent substantive product-delivery PRs from becoming mergeable.
4. The highest-priority unclaimed reproducible E2E-discovered product `bug` issue.
5. The highest-value unclaimed executable product issue, honoring explicit priority and dependencies.
6. Additional work on an existing PR only when required to complete its issue contract or make the PR mergeable.
7. Factory, CI, test, or E2E infrastructure only when it directly blocks product delivery or exists as a focused executable infrastructure issue.

Test-only defects, stale selectors, optional validation, E2E plumbing, docs, release-note work, CI cosmetics, metadata cleanup, and evidence polishing never outrank an executable user-reported or product bug unless that infrastructure directly blocks safe validation or merge of the same higher-priority product fix.

A green, ready, review-passed, or merge-gated PR is excluded from ordinary work selection. It may be selected only for one final exact-head gate check and merge action.

Optional tests, cleanup, metadata edits, wording changes, evidence polishing, PR-body edits, architectural debate, or another minor slice do not outrank a coherent implementation for an unclaimed executable product issue.

## Jev completion-action selection

The production dispatcher may use the dedicated Jev decision model to choose
**which already-eligible PR completion action** a worker executes next. This
supersedes the narrower ordinary-issue-only surface recorded in #4428: Jev may
now rank CI repair, review findings, merge conflicts, and review work.

Deterministic policy remains authoritative and owns every hard constraint:

- Action types are **derived** from the existing stage machine, never inferred
  by the model: `merge-conflict`, `ci-repair`, `review-findings`, `review`.
  `ci-repair` is offered only when trusted check metadata shows an actual
  failure; pending CI is not an executable action.
- Only ordinary lane-3 PR actions are promotable. Main-breakage, user-reported,
  `factory:ready`, blocked, draft, and owned work never move. Promotion is
  confined to the contiguous run of ordinary completion candidates containing
  the chosen action, so a decision can never jump protected or issue positions.
- WIP and review-backlog limits continue to gate *new PR creation*; they do not
  prevent ranking existing completion work.
- Leases, review independence, dependencies, exact-head CI, semantic review, and
  provider/spend limits are unchanged.
- The model sees only trusted normalized metadata (stage, priority, merge state,
  age, linked issue, exact-head reference). Issue/PR bodies, comments, diffs, and
  logs are never sent.
- One bounded `choice` request per dispatch pass. Missing key, provider failure,
  low probability margin, invalid response, or a stale/missing exact-head
  reference fall back to deterministic order without blocking dispatch.
- The chosen action and exact head are validated against an authoritative PR
  read immediately before the lease is written. A changed head or action discards
  the recommendation and reselects from canonical order.
- The deterministic baseline is recorded alongside the chosen action, and the
  controller logs whether the actual lease differed from the deterministic pick
  after all filters. Jev selection is provenance on the lease
  (`source=jev`, `action=<type>`, `head=<sha>`); the worker independently
  validates the action against its live stage and checked-out head before
  including it in the coding prompt.

## Work-session utilization

A scheduled heartbeat is a bounded work session, not a one-ticket punch.

After every substantive fix, opened PR, merge, completed issue, or valid blocker, immediately rerun selection and continue the next highest-priority executable work in the same scheduled run. Reaching one valid heartbeat outcome is a minimum success threshold while executable work exists, not a stop condition.

Do not end a run merely because CI or review is pending, because the current item became blocked, or because one issue reached a handoff state. Preserve or release ownership as appropriate, then select the next executable item. Continue until the runtime or tool budget makes further safe substantive work impossible or the shared executable pool is genuinely empty.

When no executable work remains, ending the current session cleanly is valid. The worker stays enabled for its next scheduled heartbeat.

## Concurrency and throughput floor

At most one implementation worker may own an issue unless workers explicitly declare non-overlapping file ownership.

Once one worker has a valid lease on the highest-priority issue, peers select the next eligible issue. Do not let one broad issue, one user-reported bug, or one PR consume the whole factory.

When fewer than four substantive implementation PRs are open and executable unclaimed issues exist, idle workers must prefer opening coherent implementations for separate issues over embellishing existing PRs.

OmniRoute's shared free coding pool cannot absorb a full roster tick. Fixed-model Entry sessions that smoke or run `auto/coding:free` are limited to at most three concurrent in-flight units (active Entry runs plus equivalent fixed-model leases). Dispatcher, completion drain, and capacity refill must refuse new Entry assignments when that cap is exhausted. The four-PR throughput floor remains the selection preference; it does not override the free-pool cap.

A substantive implementation PR changes product behavior, correctness, performance, architecture, deployment behavior, data, or meaningful automated coverage required by its issue. Comments, labels, reviews, PR metadata, help text, and optional test embellishment do not count toward this floor.

## Lease semantics

Factory ownership is a connection-pool lock around the next action, not a permanent assignment to the model or worker that first touched the issue or PR.

- Exactly one active owner label may hold an issue or PR at a time.
- Cross-worker takeover and merge are allowed after the prior lease is released.
- A factory that creates or advances a PR releases active ownership when its implementation attempt ends, including while CI or review is pending.
- Provider failure, timeout, no useful persisted change, or another stable handoff state releases the lease so another worker can try later. Review independence is based on factory identity and exact-head provenance, not on requiring a different model; OmniRoute may route both workers through the same upstream model.
- Review independence excludes every factory worker that authored the exact head under review, not only the worker that opened the PR. Factory pushes share one Git identity, so contributor identity comes from the controller-authored `comic-pile-factory-head-contributor-v1` record written at every push or repair, unioned with the declared branch/body producer and with every other record on the same pull request, because repairs stack onto the previous head instead of rewriting it. A head is authorized by one independent reviewer only when a record exists for that exact head; when one does not, it fails closed to two distinct eligible reviewers instead of assuming the apparent reviewer is independent. Queue selection excludes recorded contributors from semantic-review assignment so a head reaches another eligible reviewer on its own; refusing a contributor's verdict is a backstop, not the routing mechanism.
- A controller claim is not durable until the worker reaches an executable session. Smoke, executor-selection, credential, and other pre-session failures release the owner to `factory:unowned` immediately, preserve the truthful stage, and post `comic-pile-factory-claim-released-v3`. Do not wait for the 900s stale-lease TTL.
- Exact-head review assignments use the multi-provider Entry path (`nvidia`, `opencode-free`, `openrouter-free`, `kilo-auto`) while OmniRoute is dark; they must not smoke `auto/reasoning:free` or `auto/coding:free`.
- UPDATE (2026-10-17): `opencode-free` now rotates among all live, provably free OpenCode 2 models at execution time, independent of OmniRoute and advisory TSV model pins. Free slots keep durable worker identities; `big-pickle` is one eligible free model, not an incentive to add duplicate fixed factories. A nonzero catalog price always disqualifies a model and the bounded model smoke remains mandatory.
- INCIDENT (2026-09-06): OmniRoute is disabled (`FACTORY_OMNIROUTE_ENABLED=off` by default) after repeated free-pool instability. `auto/coding:free`, `auto/reasoning:free`, and `auto/best-free` are all OmniRoute routes and must not run. Service is restored through the pre-OmniRoute-only multi-provider Entry path (`nvidia`, `opencode-free`, `openrouter-free`, `kilo-auto`) with a separate multi-provider concurrency budget. do not restore the temporary `auto/best-free` capacity bridge. While OmniRoute is dark, `openrouter-free` retains pinned lanes; `opencode-free` uses live free-model rotation. Both prove execution with bounded smoke/session, rather than requiring pre-existing historical health evidence. `opencode-free` pins must stay on OpenCode free-roster ids (`big-pickle`, `*-free`, muse-spark variants); `openrouter-free` pins must stay on OpenRouter free-tier ids (`*:free` or `openrouter/free`) — never paid/stealth models. Re-enable OmniRoute only after Josh confirms gateway health by setting `FACTORY_OMNIROUTE_ENABLED=on` (live kill switch for worker refuse, lane configure, catalog discovery, and capacity).
- A takeover worker continues the current branch/head rather than creating a replacement solely because another model authored the existing commits.
- Waiting on CI or review never reserves a model indefinitely.

## Fixed-model roster discovery and retirement

The factory roster `.github/free-model-factories.tsv` supplies durable worker IDs, scheduling buckets and legacy/provider-specific metadata. For `opencode-free` the model column is advisory; an execution-time catalog lookup and free-only policy select the actual model. NVIDIA, OpenRouter, and other fixed provider pins retain their existing semantics.

`.github/workflows/factory-model-discovery.yml` runs on a six-hour schedule and on `workflow_dispatch`. It discovers live models with OpenCode CLI semantics (`opencode models opencode`, `opencode models nvidia`, and `opencode models openrouter` when OpenRouter pins exist), wrapping `scripts/opencode-model-catalog.sh` when present. NVIDIA catalog presence is judged only by that OpenCode nvidia list — never prune a NVIDIA pin solely because integrate.api.nvidia.com omitted it. Sticky `#1093` `factory-model-retired-410:v1` comments with `Source: nvidia` are the durable "turned off" signal the NVIDIA probe already fail-closes on. Discovery consumes those markers and retires matching bare model ids from the roster even when `opencode models nvidia` still lists them.

`opencode-free` eligibility matches `validate-free-model-factories.py` (`big-pickle`, `*-free`, muse-spark free/contributor-free) and/or explicit cost `0/0` from a verbose catalog. Paid Zen models are never proposed for `opencode-free` lanes. `kilo-auto` and healthy `big-pickle` slots stay unless the OpenCode catalog itself drops them.

The scheduled discovery workflow now audits live OpenCode Free models without allocating or retiring worker slots. New free models, including `big-pickle`, join the runtime rotation directly, so model catalog churn does not create a roster PR or duplicate factory identities. Catalog reports remain available for operators. For fixed providers, the workflow can still open a retirement PR when a pinned model disappears or a NVIDIA 410 marker proves permanent retirement. The generic planner retains its legacy manual add/retire capabilities, but the scheduled workflow calls `--dynamic-opencode-free --no-add-unused-free`. Permanent retirement evidence for other providers stays effective.

Both discovery and the factory runner install the current OpenCode 2 release from `@opencode/cli@latest` using `.github/scripts/install-opencode-v2.sh`; the installer enforces the V2 major version but deliberately pins no exact release. The TSV now defines durable capacity/worker identities for OpenCode Free, not the complete set of models runnable by those slots. Discovery's roster-sync PR continues to reconcile legacy roster metadata, but it is not a prerequisite for execution of newly available free OpenCode models.

Operator flow: fixed OpenCode Free workers directly select and smoke models from the live catalog. Scheduled **Factory Model Discovery** reports free entries, but opens a PR only for non-dynamic fixed-provider retirement. Any generated retirement PR must pass `validate-free-model-factories.py` and CI before merging. To audit locally use `python3 .github/scripts/factory_model_retirement.py plan --dynamic-opencode-free --no-add-unused-free --catalog-json tests/fixtures/opencode-catalog/keep-present.json`.

Required secrets on the runner: `OPENCODE_ZEN_API_KEY` (exported as `OPENCODE_API_KEY` for Zen list auth), `NVIDIA_API_KEY` when NVIDIA pins must be listed, `OPENROUTER_API_KEY` when OpenRouter pins exist, and `PR_REBASE_TOKEN` so the retirement PR triggers pull-request workflows. A recorded `--catalog-json` fixture is the CI substitute when the `opencode` binary is unavailable.

## Anti-loop rules

- Existing open PRs are not automatically higher priority than unclaimed issues.
- A green, ready, review-passed, or merge-gated PR must not consume repeated heartbeats.
- Do not repeatedly claim work whose next required edit is impossible in the current runtime. Preserve the blocker once, release active execution, and select another executable issue.
- Do not create replacement PRs merely because `main` advanced. Replay only when the prior PR is genuinely non-mergeable and substantial implementation would otherwise be lost.
- Waiting for CI, review, a merge, a safer runtime, or external availability is not a global stop condition while other executable work exists.
- Do not debate an already documented actionable finding across repeated heartbeats. Fix it, rebut it once with evidence, or preserve a real blocker and move on.
- Test-only and factory-maintenance work must not become a refuge from higher-priority product bugs.

## Full-contract implementation

Choose PR size according to reviewability, conflict exposure, deployment and rollback boundaries, and total time to the requested working behavior. Both small atomic PRs and larger coherent PRs are acceptable; neither is an objective in itself.

A split is valid when it improves reviewability, reduces conflict/rollback risk, or accelerates end-to-end delivery. Keep the original owner objective tracked and name the still-missing behavior in every partial PR and handoff. Do not substitute a prerequisite, scaffold, or observation-only implementation for the requested active capability.

A partial PR does not automatically outrank a fresh higher-priority issue. Continue the parent issue only when it wins under the selection order. If deferred, leave a durable objective-preserving handoff. Do not introduce shadow modes, disabled-by-default flags, dark launches, or extra approval phases unless Josh explicitly requested them or a pre-existing applicable policy mandates them. Preserve all real security, data-integrity, independent review, CI, claim, and deploy controls.

## Required work loop

Repeat until the selected issue reaches closure or a valid blocker:

`inspect contract -> implement closure-critical behavior -> focused validation -> commit -> push -> inspect exact SHA -> account for all review feedback -> repair blockers -> verify merge gates -> merge when eligible -> verify issue closure`

Python focused validation must include the exact CI pair `ruff check .` and
`ty check --error-on-warning` against the whole repo
(`bash scripts/check-python-ci-lint.sh`). Path-filtered ruff or ty is not a valid CI substitute.
Re-run that pair after every later Python edit and before every Python push.
A lint run from before the last edit does not count.

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
2. ignore only clearly non-actionable status noise such as review-rate-limit notices, generic summaries, release notes, or optional finishing-touch advertisements (Greptile's PR-body summary and findings are never noise; see below);
3. classify every actionable finding as fixed, demonstrably outdated because of a specific later code change, or rebutted with concrete technical evidence;
4. respond to or resolve every actionable current thread;
5. refuse pass, readiness, or merge while an unresolved actionable correctness, security, ownership, data-integrity, concurrency, recovery, migration, or test-validity finding remains.

A worker's own review conclusion does not silently override existing human or bot feedback.

### Greptile findings are high priority

Greptile is an optional source of review feedback. Josh disabled it on 2026-10-30;
OSS review credits may be available intermittently. No worker may require a
Greptile review, check, confidence score (including 5/5), or acknowledgement to
advance a PR. Disabled integration, exhausted credits, quota notices, and stale
scores do not block delivery or justify repeatedly requesting reviews. Do not
automatically re-enable it or consume newly available credits. Independent
exact-head factory semantic/acceptance review, contributor-independence rules,
required CI, and the actionable-feedback gate remain mandatory, including for
Rust cutover PRs. Fetch GitHub's existing review data even when Greptile is off;
incomplete GitHub review data still fails closed. Existing actionable findings
must still be fixed or rebutted; disabling the integration does not dismiss them.
A trusted evidence-backed outcome permits independent review to proceed without
waiting for Greptile to return.

Josh directed on 2026-10-18 that Greptile (`greptile-apps[bot]`) findings be held in high regard. They are must-address review feedback, not advisory noise:

- the worker wrapper fetches unresolved review threads, the Greptile review body and PR-body summary, and current-head PR-Agent check output before every PR-mode run, and injects them into the mission with Greptile items first and labeled HIGH PRIORITY;
- every open Greptile finding must be fixed in code on the PR branch, or answered with a concrete, evidence-backed rebuttal (cite file and line, test output, or spec). The agent records each outcome (`fixed` with an explanation, or `rebutted` with evidence) in the git-excluded `.factory-greptile-outcomes.json`, and the trusted wrapper posts those outcomes as the replies on each thread;
- workers never resolve Greptile threads; Greptile resolves its own. A thread is open until Greptile accepts the answer without pushback or a trusted responder (a repository owner, member, or collaborator, or the wrapper as the `github-actions` Bot) has replied after Greptile's latest comment. Worker App logins are never trusted responders;
- the wrapper refuses `FACTORY_GATE_READY` while any open current-head Greptile finding lacks a valid outcome, and re-dispatches the PR when new Greptile findings arrive during the run. A worker or semantic reviewer must not emit a pass verdict while any Greptile finding is neither fixed nor rebutted;
- open Greptile findings, including findings listed only in a Greptile PR-body summary for the current head, route the PR to `factory:changes-requested` (see `docs/FACTORY_GITHUB_VISIBILITY.md`). Greptile remains untrusted for factory markers, ownership, and readiness;
- PR-Agent check output is lower-priority advisory input: fix the real defects it finds, but it does not block on its own.

### Pre-push fast checks

A worker diff is pushed only after the trusted pre-push fast checks pass for the files it touches: `node --check` for `.mjs`/`.cjs`, CI-parity ruff and ty plus targeted pytest for `.py`, and the frontend typecheck plus eslint for `frontend/**/*.ts|tsx|mjs`. On failure the wrapper does not push. It resets the tree and leaves a `comic-pile-factory-fast-checks-failed-v1` comment for the next worker (see `docs/FACTORY_GITHUB_VISIBILITY.md`). Agents should run the same checks themselves before ending a run.

Every push invalidates prior review, readiness, and merge eligibility. Re-fetch the exact SHA, current review threads, mergeability, and CI after every push.

Implementation delivery is a separate mechanical prerequisite to semantic approval and merge.
Implementation issues must change behavioral source, build, or workflow content; docs, tests,
comments, docstrings, and formatting alone do not qualify. An explicit `Issue type: docs-only`
(or another supported non-implementation declaration) permits the declared documentary output.
The controller reconstructs complete old/new files from the immutable head and original PR patch
so changes inside long comments and docstrings cannot borrow executable context. Missing or
truncated source evidence fails closed. Independent exact-head acceptance review still judges
issue-specific runnable tests, including explicitly reused existing tests, and actual correctness.
Post-merge closure runs the same delivery policy, leaves non-delivered issues open, and reopens
known non-deliveries prematurely closed by GitHub keywords. It never infers completion from a
source filename alone.

Bash comparison uses shfmt's typed syntax tree; CSS and JavaScript/TypeScript use
Tree-sitter syntax trees, and Python uses its native AST. Parser positions and comments
are excluded while literal/heredoc input remains data. The pinned `factory-syntax`
dependency group is included in local development installs; control-plane workflows
install the same pins through `.github/actions/factory-syntax`. No parser downloads occur
while inspecting PR content, and a missing parser fails closed with an actionable retry.

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

- The issue/PR state reconciler enrolls open, non-draft repository PRs missing
  factory metadata on open/reopen/unlabel events and every 15 minutes. Contributor
  fork PRs participate in the same review, repair, CI, and merge lifecycle as
  factory and local PRs. Dependabot and Renovate are excluded. It preserves unrelated labels and an
  existing owner/stage, defaults missing ownership to `factory:unowned`, and uses
  exact-head trusted review markers when recovering a missing stage; otherwise
  it requests `factory:review`. Green CI alone never establishes readiness.
- A contributor PR, Josh-authored manual PR, or local factory PR follows the same review,
  repair handoff, exact-head CI, and merge-drain stages. Branches named
  `local/*`, `agent/*`, and `chatgpt/*` are eligible when enrolled with
  `factory`. The controller checks the PR's verified GitHub author and exact
  head commit for the local `Model:` trailer; missing trailers on verified
  Josh-authored human commits are attributed to `human`. A PR whose author
  cannot be established does not receive fabricated model provenance.
  Keep manual-only PRs out of this workflow with
  `<!-- factory-execution:manual-only -->`.
- A head advanced outside the numbered-worker wrapper (an owner-pushed merge or
  rebase, a local agent, or trusted repository automation) has no
  controller-authored author marker. The review controller repairs that
  automatically during the ordinary review pass, so such a head is reviewable
  exactly like a wrapper-pushed one: it attests the exact-head author from the
  wrapper's own contributor record when there is one, otherwise from the pull
  request's verified GitHub author and the head commit's `Model:` trailer (or
  `human` when the trailer is absent), and never invents a numbered-worker
  identity. A controller-authored exact-head attestation counts as complete
  provenance, so one independent approval authorizes the head, the same as for a
  wrapper push. For a head that will not receive another review pass, reconcile
  it explicitly with
  `python3 .github/scripts/factory-review-controller.py reconcile-provenance --pr N`
  from trusted main, or the `Factory Provenance Reconcile` workflow for the same
  effect as `github-actions[bot]`; the command releases the head to
  `factory:review`. `--head` optionally pins the exact SHA and fails closed on a
  moved head.
- If an approved review cannot record trusted author/reviewer provenance because
  its staged roster is missing or invalid, or a provenance write fails, the
  controller preserves the approval and parks the PR and linked issue at
  `factory:blocked` with no active owner. Its redacted diagnostic identifies the
  infrastructure failure. Repair the trusted bundle or write access before
  reconciling the exact head; do not assign another semantic review of unchanged
  code to work around a controller failure.
- `factory:local` remains an active local-work lease, not an opt-out from
  enrollment. A local session MUST release that lease to `factory:unowned`
  when it opens a ready-for-review PR or finishes a repair; the fleet never
  steals an actively edited local checkout. Review findings hand off as
  `factory:changes-requested`, and independent workers can pick up the PR
  once the lease is released.
- The manual/local review controller follows only explicit `Closes #N`,
  `Fixes #N`, or `Resolves #N` references when reconciling a linked issue;
  casual issue mentions do not create ownership or issue mutations.
- `factory:building`, `factory:review`, `factory:changes-requested`, `factory:ci`, `factory:ready`, and `factory:blocked` are mutually exclusive workflow states.
- `factory:unowned`, `factory:local`, and every `factory:<number>` owner label are mutually exclusive next-action owners.
- Never leave a factory-produced or factory-managed open PR without `factory`, one truthful workflow-state label, and one truthful owner label.
- A push invalidates `factory:ci` and `factory:ready`; transition the exact new head back to `factory:review` unless review findings already require `factory:changes-requested`.
- Cross-worker takeover and merge are allowed. The new worker replaces the owner label and may merge work it did not author after every exact-head gate passes.
- If `gh pr edit` fails because of deprecated Projects Classic GraphQL fields, use the issue-compatible REST label-replacement endpoint with the complete target label set. A POST that only adds labels, or sequential DELETE/POST calls, is not atomic reconciliation.
- Derived observability labels (currently `factory:merge-conflict`, from GitHub mergeability) are projections, never stages. They never satisfy the workflow-state or owner requirement and never enter `STAGE_LABELS`, stage precedence, `BLOCKED_LABELS`, or queue selection. There is no `factory:approved` label.
- Before ending any turn, compare the issue, PR, review, CI, lease, and merge state and repair any metadata contradiction discovered.

## Repository safety

- Contributor fork PRs enter the normal factory lifecycle automatically. A
  credentialed factory worker never checks out or executes fork source, even for
  review. The worker resolves the fork head through the base repository's
  `refs/pull/<n>/head`, refuses `checkout_target` for an external head repository,
  and reviews fork source only as a bounded data snapshot with every model tool
  and integration hard-denied. Review the exact head; never assume the fork branch
  exists on the base repository and never create a same-named base branch.
- Fork repairs never run in the credentialed worker. The worker writes a trusted
  dispatch receipt and starts `.github/workflows/factory-fork-execution.yml`, which
  has read-only permissions, no inherited secrets, and no registry publishing.
  Contributor dependencies, tests, hooks, and the anonymous Kilo repair run only
  on that secretless runner. Its result is data: `.github/workflows/factory-fork-persistence.yml`
  runs trusted `main` code, validates workflow identity, the receipt, the live
  lease, the exact head, and a single descendant commit, imports the bundle into a
  bare quarantine without checkout, and only then pushes to the existing fork head
  with maintainer edit access. Preserve contributor commits and authorship; never
  execute artifact code on the persistence host.
- Fork CI runs on `pull_request` with read-only credentials and no registry
  publishing. Metadata-only `pull_request_target` workflows use trusted default
  branch code and never execute the fork checkout with their write token.
  Enrollment does not attest provenance, approve code, or bypass exact-head gates.

- Fixed-model PR creation must use `PR_REBASE_TOKEN`, like git pushes. Keep the
  workflow token for controller comments and labels; creating the PR with that
  token attributes it to `github-actions[bot]`, which can leave Actions awaiting
  approval and causes CodeRabbit to skip initial review.
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

## Product acceptance for PRDs and epics

Child closure is evidence of progress, not sufficient evidence that a product epic's acceptance scenarios work. Parent PRD and epic issues require an explicit product-acceptance stage before they may be marked complete.

Integrated parent product acceptance is human/interactive controlled. Autonomous factories do not select parent PRD/epic issues as ordinary work and do not issue the deciding product-acceptance verdict. Factories may implement explicitly scoped child issues and produce focused evidence for later acceptance.

See [`docs/PRODUCT_ACCEPTANCE_PROTOCOL.md`](PRODUCT_ACCEPTANCE_PROTOCOL.md) for the full acceptance workflow, comment structure, and regression targets.

Key rules for factory workers:

- Do not select or claim a parent issue labeled `epic` or `prd`.
- Do not select or claim any issue containing `<!-- factory-execution:manual-only -->`.
- Under an architecture hold, implement only an explicitly authorized narrow child with frozen requirements. Do not reinterpret the architecture, broaden the child, lift the hold, or close the parent.
- Child closure alone does not satisfy parent acceptance.
- Factories may provide tests, Chromium/E2E evidence, API evidence, and other child-level artifacts for the later interactive acceptance run.
- A factory must not post the final `<!-- product-acceptance:v1 -->` verdict as the deciding authority, mark the parent `ralph-status:done`, or close the parent.
- Duplicate factory PRs that attempt to close already-delivered child work do not satisfy product acceptance.

## Adaptive stale-PR decay guard (ADR)

### Context

Factory PRs converge quickly: P25 at 1.27h, P50 at 2.80h, P75 at 7.37h, P90 at 11.58h, max at 37.96h. Long-lived implementation attempts indicate failed convergence. The existing semantic strike policy does not cover this failure mode — CI churn, transient model/provider failures, merge/rebase churn, worker handoffs, stale reviews, and no-diff handoffs do not consume strikes.

### Decision

Define staleness relative to a rolling population of the **last 100 eligible successfully merged Factory PRs**. The implementation calculates PR lifetime from `created_at` (never `updated_at`):
- For merged PRs: `merged_at - created_at`
- For open PRs: `now - created_at`

The threshold uses a robust distribution-derived rule: **`2 × P90`** as the default candidate, compared with a median/MAD formulation. The final formula uses the more conservative (larger) of the two, subject to a documented lower floor of **1 hour** and a cold-start fallback of **24 hours** when fewer than 10 merged PRs exist.

### Expiration behavior

When an autonomous Factory implementation PR crosses the stale threshold:
1. Release/reset the linked issue to unowned executable implementation from current `main`
2. Close/cancel that PR implementation attempt
3. Persist a trusted controller marker/comment (`comic-pile-factory-stale-expiration-v1`) recording the observed age, baseline sample, formula, and threshold
4. Ensure the stale branch/PR cannot immediately re-enter repair/review loops
5. Preserve enough provenance to audit why the attempt was expired

The mutation order is deliberate. Resetting the issue while its canonical PR is still
open is safe because the open PR suppresses duplicate issue intake. Writing the
marker last keeps a partial GitHub failure retryable instead of recording a false
completed expiration.

Staleness is an **attempt-level circuit breaker**, just like semantic strike exhaustion. It must not close the underlying product issue unless a separate terminal condition applies.

### Relationship to semantic strikes

- **Semantic strikes:** repeated evidence that an implementation is substantively wrong
- **Stale decay:** evidence that an implementation has failed to converge in normal Factory time, regardless of cause
- Neither mechanism increments or masquerades as the other

### Scope/eligibility

Only autonomous Factory implementation PRs should participate. Exclude Dependabot, manual/Codex work, infrastructure PRs, and other non-product automation. The baseline population uses the same Factory-implementation definition as the PRs being guarded.

### Implementation

The `stale_pr_decay.py` module in `.github/scripts/` provides:
- `get_staleness_baseline()` — builds the rolling population baseline
- `is_stale_attempt()` — checks if a PR age exceeds the threshold
- `process_stale_prs()` — evaluates and expires stale PRs
- `StalePRGuard` — configurable guard class
- `build_stale_expiration_marker()` / `parse_stale_marker()` — durable marker support
- `get_staleness_observability()` — logging summary

The controller exposes a `stale` subcommand: `factory-work-controller.py stale [--dry-run]`.
The fixed-model dispatcher invokes `stale` once per serialized dispatch tick,
after the ready-PR merge drain and before new assignments are selected.

## Semantic review strike policy

A factory implementation attempt gets three substantive semantic repair cycles. A cycle is counted once per distinct PR head that receives a trusted controller-authored `verdict-repair` semantic review marker. Mirrored comments, duplicate markers for the same head, stale-head results, CI failures, merge conflicts, provider failures, and no-diff handoffs do not consume this semantic strike budget.

On a fourth distinct semantic repair verdict, cancel that implementation attempt instead of repairing it again: persist the fourth review findings, close the PR, return the linked issue to unowned executable implementation, and record a `comic-pile-factory-strike-reset-v1` marker on the issue. When producer provenance is known, that producer is ineligible to receive the first clean implementation retry. The exclusion is one-shot and is spent only after a different factory posts a real implementation claim for the retried issue.

This is an attempt-level circuit breaker, not an issue-level failure. The issue remains valid work unless a separate terminal blocker applies.

## Review infrastructure retry cooldown

For an unchanged PR head and stage, three trusted release records for transient
model interruption, review-agent failure, head-read failure, pre-session assignment-read
failure, missing/conflicting verdicts, or authoritative-diff read failure
suppress further assignments for a rolling 30 minutes. The existing generation
retry gate enforces the cap without labeling infrastructure failures as human
blockers or semantic strikes. A real new head, changed stage, or newly developed
merge conflict gets a fresh budget. Expired failures drop out automatically.
Release markers retain the reason, worker, timestamp, exact SHA, stage, and
conflict state; dispatcher logs show suppressed generations and counts by reason.
Kilo JSON telemetry stays intact; only assistant-text events enter the verdict
channel. Tool output and fenced examples cannot authorize an approval. Untrusted comments do not
count, and one PR's failures do not suppress other work.

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
- merge closure: `<!-- comic-pile-factory-merge-closure-v1:pr-<pr>:issue-<issue> -->`
- unreadable-dependency warning: `<!-- comic-pile-factory-dependency-unreadable-v1:pr-<pr>:issue-<issue> -->`
- product acceptance: `<!-- product-acceptance:v1 -->`
- stale expiration: `<!-- comic-pile-factory-stale-expiration-v1:pr-<pr>:issue-<issue>:age-<s>:sample-<n>:formula-<f>:threshold-<t> -->`
- head contributor: `<!-- comic-pile-factory-head-contributor-v1:pr-<pr>:head-<sha>:worker-<n>:epoch-<s> -->`

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
