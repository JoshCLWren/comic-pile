# Deterministic factory checkpoint handoff

Owner authorization (2026-11-15, #5172): recovery snapshots may be published as
**draft PRs before validation**. These drafts preserve work; they are never
semantic approval, merge readiness, or successful validated delivery.

The trusted wrapper stages the checkpoint writer and handoff controller from
`main` before checking out model-editable source. The writer uses a private Git
index, saves tracked and non-ignored new files every 45 seconds, and takes a
final snapshot when the model exits or the wrapper receives a handled signal.
It never changes the model's index/HEAD or the assigned PR's branch.

New branches identify the original issue, model and run:
`factory/work-checkpoints/issue-4853/kilo-auto-free/43724877464`.
The model component is a path-safe slug, while the full model/runtime identity,
original issue, source branch and base commit remain in commit trailers. When a
PR has no established original issue, `issue-unknown-pr-5152` explicitly records
that gap. Legacy run-only checkpoint names remain recoverable.

At the first saved snapshot the trusted controller opens an idempotent recovery
draft. Issue work targets `main`; repair recovery targets the existing PR branch
while it is open, linking back without changing its owner. Later snapshots update
that same recovery branch. An unchanged tree still retries publication/linking
so a temporary GitHub failure cannot leave a permanently invisible branch.
Normal validated delivery continues through its existing PR and review gates;
the recovery draft is superseded only after incorporation is proven.

`factory-checkpoint-reconcile.yml` runs on completed canonical factory runs and
hourly, with manual `run_id` selection available. It checks out trusted `main`
and reads GitHub objects as data. It never executes recovery code. This separate
runner recovers work after hard cancellation when the writer's exit handler
cannot run. No system can save edits made after the last snapshot if the runner
is destroyed; the periodic snapshot limits that window.

Outcome reporting separates **saved**, **recovery PR published**, and
**validated PR delivery**. A failed or canceled worker stays failed even when its
code has a saved recovery draft. Publication errors are retried independently.

## Retention

There is no age-based deletion of unresolved code. A recovery PR keeps it
visible. Completed-run reconciliation removes a checkpoint only when every path
changed from its initial base has the same blob and mode (including deletions)
at the real delivery destination, or a trusted operator explicitly discards it.
A normal wrapper handoff records the proven destination for later reconciliation.
Running attempts, moved refs, incomplete API/tree data, active owners, holds and
recovery PRs advanced to review are retained. A closed draft alone is insufficient
permission to delete its code.

To explicitly discard an obsolete recovery, close its draft and add this comment
as a repository owner/member/collaborator:
`<!-- factory-checkpoint-discard:v1 -->`.
The next completed-run sweep can retire its branch. Successful incorporation
closes a superseded draft before deleting the checkpoint ref. Unresolved recovery
work is preserved rather than trimmed to an arbitrary count.
