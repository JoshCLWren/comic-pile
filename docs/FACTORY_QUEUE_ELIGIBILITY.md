# Factory queue eligibility

Canonical reference for executable-eligibility and lease reconciliation across
the ComicPile work-selection paths (issue #3039).

## Authoritative roles

| Selector | File | Serves | Owns fixed-model dispatch? |
|---|---|---|---|
| Fixed-model controller | `.github/scripts/factory-work-controller.py` (+ `factory_work_policy.py`) | Fixed-model factory workers (`factory:6`–`factory:79`) | **Yes — sole owner** |
| Ralph selector | `scripts/next_task.py` | Local/Ralph agents working the pending queue | No (advisory for its own queue) |

The controller's dispatcher (`assign`, `reconcile`, `release`,
`conflict-recovery`, `stale`, `explain`) is the only path that may create a
fixed-model lease. `scripts/next_task.py` never creates factory leases, never
suppresses on canonical PRs (it has no PR view), and must agree with the
controller on every static rule below. When the two disagree, the controller
plus this document win; file a bug and fix the shared module, not a copy.

## Shared semantics

The pure rules live in `scripts/factory_eligibility.py` and are re-exported
through `.github/scripts/factory_work_policy.py`. Both selectors delegate to
them; agreement is pinned by `tests/test_factory_eligibility.py`
(`test_selectors_agree_with_shared_semantics`).

Static exclusions, in evaluation order:

1. Not open.
2. Non-executable product numbers (registry, watchdog, protected set).
3. `epic` / `prd` labels, or a body-declared product-acceptance parent
   (acceptance language **plus** a checkbox child graph; either half alone
   stays executable).
4. The structured manual-only directive (see below).
5. Blocked labels (`factory:blocked`, `ralph-status:blocked`, `wontfix`,
   `invalid`, `duplicate`).
6. Terminal labels (`ralph-status:done`).
7. An active factory lease (`factory:<worker>` / `factory:local`).
8. Unresolved explicit dependencies (declared target still open).
9. An open canonical PR already owning the issue (controller only).
10. No-diff retry budget exhausted (bounded rolling window, never permanent).

Dynamic gates applied on top by the controller: worker WIP caps, review
backlog backpressure, live GitHub dependency blockers, and lease liveness.
`reconcile` repairs contradictory labels and releases provably stale leases
automatically; no hand-authored release comment is ever required.

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

## `ralph-task` / `ralph-status:pending` scope

These two labels are **Ralph-selector metadata, not universal execution
metadata**. `scripts/next_task.py` requires them because it serves the local
Ralph queue. The fixed-model controller never requires them and selects on
factory labels instead. An issue without `ralph-task` can be perfectly
eligible for fixed-model dispatch while being invisible to `next_task`, and
that is by design.

## Trust tiers for comments

- **Governance signals** (heartbeat resolution, review bodies, model-health
  telemetry): `comment_is_trusted` — owner/member/collaborator prose or
  workflow-posted comments.
- **Machine markers** (lease activity, no-diff accounting, strike-reset
  scans): `machine_marker_is_trusted` — workflow-posted only
  (`github-actions` app). A bare OWNER/MEMBER/COLLABORATOR association also
  arises from token-authenticated API calls, so marker-shaped text with only
  that association is ignored instead of moving leases or consuming retry
  budgets. Explicit human authorization is a separate human-interpreted
  signal, never a marker-shaped comment.

## Queue diagnostics

To ask why a specific issue is or is not eligible:

```bash
# Authoritative controller view (static verdict + live dynamic gates):
python3 .github/scripts/factory-work-controller.py explain --issue 3039
python3 .github/scripts/factory-work-controller.py explain --issue 3039 --json

# Ralph-queue view (static rules + Ralph metadata only):
python3 scripts/next_task.py explain 3039
```

Historical claim/release comments are an append-only audit log. If `explain`
reports a stale lease, run `reconcile`; do not hand-author release comments.
