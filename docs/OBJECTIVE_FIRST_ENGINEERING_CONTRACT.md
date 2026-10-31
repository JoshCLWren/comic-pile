# Objective-First Engineering Execution Contract

Owner decisions: 2026-10-31. Applies to interactive ChatGPT engineering sessions,
local factory sessions, scheduled factory workers, and their implementation/review
handoffs. Read alongside `AGENTS.md`, `docs/ISSUE_EXECUTION_PROTOCOL.md`, and
`docs/AUTONOMOUS_FACTORY_POLICY.md`.

## Prime directive

**Own the user's requested outcome, not merely the next PR.** A well-tested PR,
an issue, a plan, a successful smoke test, or a handoff is progress, not proof
that the requested capability works. Do not quietly replace the requested
behavior with a safer, smaller, or observation-only artifact.

This contract governs *delivery interpretation*. It does not waive established
security, authorization, data-integrity, production-safety, architecture,
ownership/claim, CI, independent review, or deployment requirements. Existing
factory selection, product priorities, leases, and PR merge rules remain
authoritative in their respective domains.

## 1. Preserve the owner's objective

Before implementation, express the request as a concrete observable result:
what should the system **actually do**, for whom, and in which environment?
Keep that statement visible through issues, PRs, reviews, and handoffs.

- A direct, explicit owner decision about product behavior outranks an earlier
  assistant-authored issue, plan, acceptance checklist, or design preference.
  An assistant must not manufacture authority by inserting its own staging or
  narrower scope into a GitHub issue and later calling that issue the owner's
  instruction. If an issue conflicts with a later direct owner decision,
  reconcile the issue or flag a genuine constraint; do not silently follow the
  stale assistant-authored limitation.
- Existing hard technical, authorization, safety, and release requirements
  still apply. A new product decision does not authorize bypassing them.
- Issue contracts govern an independently executable **piece of work**. When
  the owner's objective spans issues or PRs, the original objective remains
  open until the integrated capability meets its own acceptance criteria.
  Closing a child issue never silently closes the broader objective.
- If a request is sufficiently clear to implement, proceed. Ask only when a
  missing decision materially affects the desired behavior, authorization,
  or a non-reversible risk.

## 2. Choose PR boundaries for total delivery speed

The agent chooses PR size based on **reviewability, conflict exposure,
deployment independence, rollback scope, and time to a working outcome**.

- Small, atomic PRs are welcome; a coherent larger PR is also welcome.
  Neither is an achievement in isolation. Do not force a large PR to satisfy
  an anti-incrementalism slogan, nor create small PRs merely to produce activity.
- Prefer vertical increments that integrate usable behavior. Infrastructure
  prerequisites and scaffolding are legitimate when they are necessary for
  the requested result, but they must have a concrete dependency and a
  continuation path; they are not an unrequested substitute for activation.
- If work must be split, record how each PR advances the owner's outcome,
  which behavior remains missing, the next executable action, and the active
  tracking issue. Do not label a partial PR as completion of the original goal.
- Optimize for end-to-end delivery while honoring the factory's established
  priority ordering, other workers' claims, concurrency, and review gates.
  Work on a lower-priority objective may be deferred, but its remaining
  acceptance criteria must not disappear.

## 3. No invented deployment modes or approval phases

Do not add **shadow-only operation, dark launch, feature flags, disabled-by-default
activation, extra manual approval, prototype-only delivery, or artificial rollout
stages** unless the owner expressly requests them or an **already applicable
repository/operational policy** requires them.

- An assistant-authored issue or plan is not sufficient evidence that the
  owner requested a shadow phase. Do not add a new staging requirement and
  then cite it as a pre-existing rule.
- When staging is genuinely required by an existing policy, state which rule
  applies, what release condition will end the stage, and how the real
  behavior will be activated. Do not leave activation as an unspecified
  future project.
- Within established technical safeguards, accept reasonable reversible
  engineering risk. Use deterministic authorization, scope restrictions,
  bounded expenditure, observability, rollback, timeouts, and safe failure
  handling **around the real behavior**, rather than disabling that behavior.
- For an actual unmitigated blocker (for example irreversible data loss or a
  required release gate that cannot pass), report the specific evidence,
  preserve progress, and hand off the required repair. Do not call a simulation
  or non-activated implementation complete.

## 4. Refactor in proportion to the objective

Refactor adjacent code when it materially improves maintainability,
testability, clarity, or correctness **without significantly expanding scope**.
Preserve established architectural boundaries and remove replaced dead paths
when the change makes them obsolete and the required migration proof is met.

Do not accumulate speculative architectural redesigns or defer a necessary
repair just because it is not directly user-visible. Structural health is an
engineering quality requirement; needless scope expansion is not.

## 5. Verify the outcome, not only its ingredients

For a deployed capability, **done** requires:

1. The requested behavior is implemented behind the intended real entry
   point, not only in a parallel endpoint, test harness, or shadow path.
2. Required focused tests, exact-head CI, independent semantic/acceptance
   review, merge safety, and existing deployment gates pass.
3. The change is **merged and deployed/activated** in its intended environment.
4. An end-to-end check demonstrates the **requested behavior actually occurs**
   in that environment, including its real caller and meaningful success path.
   A readiness probe, smoke test of an unused endpoint, CI green, or a deployed
   commit alone is insufficient.
5. The originally requested acceptance criteria are met, and an honest
   closing record identifies the deployed revision and verification evidence.

For documentation, policies, or other non-runtime deliverables, replace
"deployed behavior" with **merged/activated in the actual location where
agents or users consume the artifact**, and verify the references,
consistency, and required acceptance checks. Do not pretend a policy-only
change altered running software.

Productivity experiments need the real requested decision path to operate
before claiming the *experiment is active*. Evidence that the experiment
improves productivity is a separate measured result unless the owner requested
proven improvement as the original completion criterion.

## 6. Implement instead of orbiting the work

Default loop: **inspect -> implement -> run focused verification -> repair ->
commit/push -> exact-head CI/review -> repair -> merge/deploy -> real end-to-end
verification -> close objective**.

Fix concrete failures. Do not replace implementation with new issue grooming,
summary prose, repeated reports, optional review cosmetics, or speculative
guardrails. Comply with existing factory lease, priority and independent review
rules; do not self-authorize a merge that requires another reviewer.

## 7. Session boundaries are handoffs, not scope reductions

When runtime, tool access, an active claim, review, or CI prevents completing
the objective in the current session:

- Persist the **maximum coherent, independently reviewable work** possible.
  Do not invent a prerequisite phase solely because the session is bounded.
- Leave a durable handoff with: **original owner objective**, completed
  functionality, exact remaining behavior, issue/PR/branch/head SHA, owner and
  lease state, CI/review/deployment status, reproduction or test evidence,
  concrete blocker, and the **next executable action**.
- Release or reconcile ownership according to the factory lease protocol.
  The next worker must resume the actual objective, not treat the handoff's
  intermediate scope as the product finish line.
- Never claim unseen work is already merged, deployed, or verified; never
  promise asynchronous completion without a real scheduled execution path.

## 8. Mandatory PR and completion review

Every substantial implementation PR should make these facts easy to audit:

| Field | Required evidence |
| --- | --- |
| **Owner objective** | Original requested operational behavior, with any later owner decisions |
| **This PR delivers** | Specific working behavior or necessary dependency and why this boundary was chosen |
| **Still missing** | Exact remainder of the owner objective, or `none` |
| **Safety/rollout basis** | Existing policy or explicit owner request for staging, if any; otherwise active behavior |
| **Validation** | Focused tests, exact-head CI/review, deployment and real-path verification, each clearly labeled as complete/pending/unavailable |

An independent reviewer should ask **two separate questions**:
(1) Is the implementation correct and safe under existing engineering rules?
(2) Does it deliver its stated scope, and is anyone falsely declaring the
owner's broader objective complete?

A child implementation PR may pass its own gates while the larger objective
remains unfinished. Only declare the **original objective** done when the
outcome proof in section 5 exists. Never use a PR merge, checkmark, follow-up
issue, or a polished handoff to disguise that distinction.

## Example: Jev in ComicPile

Owner intent: try Jev to help factories decide what work to perform.

An assistant-authored requirement to run Jev in shadow mode does **not**
authorize stopping at observation-only behavior. A fitting active experiment
would preserve deterministic eligibility, protected priorities, claims, and
CI/review rules while using Jev's bounded recommendations for genuinely
interchangeable work and falling back safely on unavailable/uncertain results.
Then verify a real factory dispatch actually used the ranking. Measuring
long-term productivity is valuable follow-on evidence, not a fabricated
prerequisite to running the requested experiment.

This example is an interpretation of the owner's intent, not authorization
to bypass the existing factory safety and review requirements or merge a
specific implementation without its gates.
