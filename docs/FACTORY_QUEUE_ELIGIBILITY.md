# Factory queue eligibility

Canonical reference for executable-eligibility and lease reconciliation across
the ComicPile work-selection paths (issue #3039).

## Authoritative roles

| Selector | File | Serves | Owns fixed-model dispatch? |
|---|---|---|---|
| Fixed-model controller | `.github/scripts/factory-work-controller.py` (+ `factory_work_policy.py`) | Fixed-model factory workers (`factory:6`–`factory:79`) | **Yes — sole owner** |
| Ralph selector | `scripts/next_task.py` | Local/Ralph agents working the pending queue | No (advisory for its own queue) |
| Rotisserie adopter | `.github/scripts/factory_rotisserie_adopter.py` | Read-only host-translation shadow of the same rules | No (never assigns work) |

The controller's dispatcher (`assign`, `reconcile`, `release`,
`conflict-recovery`, `stale`, `explain`) is the only path that may create a
fixed-model lease. `scripts/next_task.py` never creates factory leases, never
suppresses on canonical PRs (it has no PR view), and must agree with the
controller on every static rule below. The Rotisserie adopter must agree too:
its `_human_gate` is the same static rule set. When any path disagrees, the
controller plus this document win; file a bug and fix the shared module, not a
copy.

## Shared semantics

The pure rules live in `scripts/factory_eligibility.py`. All three consumers
import that module; `factory_work_policy` re-exports only `is_manual_only`,
`is_acceptance_parent`, and `parse_declared_dependencies` for callers that
already hold the policy module. Agreement is pinned by
`tests/test_factory_eligibility.py`
(`test_selectors_agree_with_shared_semantics`) and
`tests/test_factory_rotisserie_adopter.py`
(`test_human_gate_uses_the_structured_manual_only_contract`).

Static exclusions, in evaluation order:

1. Not open.
2. Non-executable product numbers (registry, watchdog, protected set).
3. `epic` / `prd` labels, or a body-declared product-acceptance parent
   (acceptance language **plus** a checkbox child graph; either half alone
   stays executable).
4. The structured manual-only directive (see below).
5. Blocked labels (`factory:blocked`, `ralph-status:blocked`, `wontfix`,
   `invalid`, `duplicate`).
6. Terminal labels (`ralph-status:done`, `factory:ready`).
7. An active factory lease (`factory:<worker>` / `factory:local`).
8. Unresolved explicit dependencies (declared target still open).
9. An open canonical PR already owning the issue (controller only).
10. No-diff retry budget exhausted (bounded rolling window, never permanent).

Dynamic gates applied on top by the controller: worker WIP caps, review
backlog backpressure, Rotisserie intake authorization, live GitHub dependency
blockers, and lease liveness. `explain` reports every gate it can observe
except lease liveness and the per-worker strike-retry exclusion, which is
evaluated at assignment time for a specific worker. `reconcile` repairs
contradictory labels and releases provably stale leases automatically; no
hand-authored release comment is ever required.

## Manual-only directive contract

Autonomous execution is excluded **only** by a standalone HTML-comment
directive on its own line, outside fenced code blocks and inline code spans:

```html
<!-- factory-execution:manual-only -->
```

Raw substring matching is not the contract. Merely discussing the marker in
prose, or quoting it in code (backticks, fenced blocks), never excludes an
issue — that brittleness caused the Factory-41 misread on #3039, where
release-note prose mentioning the marker was mistaken for the directive. To
mention the marker without triggering exclusion, wrap it in code spans or
omit the `<!-- -->` delimiters.

One deliberate exception: `factory_post_merge_closure.py` keeps the broader
substring guard. That path decides whether merge automation may *close* an
issue, so it stays maximally conservative and never becomes more permissive
than the execution contract. Do not tighten it to the structured rule without
a separate decision.

## `ralph-task` / `ralph-status:pending` scope

These two labels are **Ralph-selector metadata, not universal execution
metadata**. `scripts/next_task.py` requires them because it serves the local
Ralph queue. The fixed-model controller never requires them and selects on
factory labels instead. An issue without `ralph-task` can be perfectly
eligible for fixed-model dispatch while being invisible to `next_task`, and
that is by design.

## Comment trust

Marker trust is not an eligibility rule. `factory_work_policy.comment_is_trusted`
is the single gate used by every lease-activity, no-diff, and strike-reset scan:
it accepts a trusted `OWNER`/`MEMBER`/`COLLABORATOR` association **or** a
workflow-posted comment (`performed_via_github_app.slug == github-actions`),
matching [`FACTORY_GITHUB_VISIBILITY.md`](FACTORY_GITHUB_VISIBILITY.md). Nothing
in `scripts/factory_eligibility.py` reads comment provenance; eligibility reads
issue state, labels, and body only.

## Queue diagnostics

To ask why a specific issue is or is not eligible:

```bash
# Authoritative controller view (static verdict + live dynamic gates):
python3 .github/scripts/factory-work-controller.py explain --issue 3039
python3 .github/scripts/factory-work-controller.py explain --issue 3039 --json

# Ralph-queue view (static rules + Ralph metadata only):
python3 scripts/next_task.py explain 3039
```

Both commands are read-only and share `explain_issue_eligibility`, so the
report cannot drift from what dispatch enforces. The controller report also
names the open canonical PR that owns the issue, the worker-WIP and
review-backlog counts against their limits, Rotisserie intake authorization,
and any live open dependency blocker. The `next_task` report explicitly lists
what it could not evaluate — canonical open-PR suppression is a controller-only
gate.

Historical claim/release comments are an append-only audit log. If `explain`
reports a stale lease, run `reconcile`; do not hand-author release comments.
