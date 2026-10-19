# Vercel deployment

ComicPile uses Vercel for production only. The production branch is `main`.

## Deployment contract

- A push or merge to `main` may create one production deployment for that exact commit SHA.
- Pull requests and non-production branches must not create Vercel deployments.
- Pull requests are validated locally and through GitHub Actions.
- The React/Vite frontend is built as static output, while `/api/*` and the API documentation routes are served by FastAPI.
- Neon is the production PostgreSQL provider.

`vercel.json` disables Vercel Git deployments. The migration-aware
`.github/workflows/deploy-production.yml` workflow is the only supported deployment path.

The workflow listens for a direct `main` push and also retains factory-completion and scheduled
recovery triggers. A merge performed with the built-in `GITHUB_TOKEN` (`github-actions[bot]`) fires
no push or `workflow_run` event at all, and the `*/5` cron fires only every few hours in practice,
so on its own a factory merge could leave production hours behind `main` (PR #3869, merged as
`1319bc5a` at 12:10 PM CT by Factory Ready Merge Drain, started no deploy).

### Bot merges dispatch the deploy

`workflow_dispatch` is the one event `GITHUB_TOKEN` may raise. Only two paths merge factory PRs in
production, Factory Ready Merge Drain and the Fixed Model Factory Dispatcher's ready drain. Both call
`factory_dispatch_production_deploy` from `.github/scripts/factory-dispatch-production-deploy.sh`,
which runs `gh workflow run deploy-production.yml --ref main -f source=factory-merge`:

- Each drain dispatches once per run, after the last merge (an `EXIT` trap, so a later loop failure
  cannot skip it), and only when that run merged at least one PR. A PR found `MERGED` after
  `gh pr merge` errored (the merge landed anyway, or another actor merged it) also counts, because
  a GITHUB_TOKEN merge by anyone fires no push event. Dedupe makes the extra dispatch harmless.
- A failed `gh workflow run` is retried up to 3 times (3s, then 6s apart, the `dispatch_worker`
  pattern). If every attempt fails, it only warns; the merge stands and the next trigger deploys the
  same `main`. Both jobs run with `actions: write`. `FACTORY_DEPLOY_DISPATCH=off` disables the
  dispatch for an incident.
- The worker wrappers (`free-model-factory-worker-primitives.sh`, `nvidia-factory-worker.sh`,
  `omniroute-factory-worker.sh`) do not merge in production. Workers hand finished PRs to the
  merge controller. `validate-free-model-factories.py` forbids `gh pr merge "$NUMBER"` in the live
  `free-model-factory-worker.sh`, which sources the primitives only up to `ensure_owner_label`, so
  the primitives' standalone merge loop never runs. The NVIDIA and OmniRoute wrappers are not called
  by any workflow. Their `gh pr merge` blocks and the dispatch call after each one are dead code. The
  dispatch calls stay in so the guard test below keeps passing, and they would do the right thing if
  one of those paths were revived.
- `tests/test_factory_deploy_dispatch_after_merge.py` finds every `gh pr merge` or merge-API call
  under `.github/` and `scripts/` and fails when one does not dispatch the deploy. The only
  exemption is `scripts/opencode_pipeline.sh`, which merges locally with the operator's token, so
  its push event deploys normally.

Dispatched runs are named `Deploy Production [source=<source>] <reason>` (`run-name`), so the
Actions list shows whether a run is a manual force-redeploy or a factory-merge dispatch. `source` is
a choice input (`manual`, the default, or `factory-merge`).

### Overlapping runs

Every trigger shares the `vercel-production` concurrency group with `cancel-in-progress: false`:
an in-flight deploy is never cancelled, and at most one run waits, with a newer pending run
replacing an older one. Every run checks out the tip of `main` when it starts and performs an
exact-SHA preflight against Vercel. Once a `READY` production deployment exists for the current
`main` SHA, later automatic triggers, including `source=factory-merge` dispatches, exit without
rerunning migrations or creating another deployment. A manual `workflow_dispatch` (the default
`source=manual`) deliberately bypasses this deduplication as the explicit force-recovery path.

**A queued manual redeploy can be superseded.** `cancel-in-progress: false` does not keep every
pending run. GitHub keeps only the newest one and cancels the older pending run. A manual or forced
redeploy that is waiting behind an in-flight deploy is therefore cancelled when any later trigger
queues (push, `workflow_run`, cron, or a factory-merge dispatch). If that later run is a
deduplicating trigger and the SHA is already `READY`, it skips, and the forced redeploy never
happens. To reduce this, `factory_dispatch_production_deploy` checks for a queued, pending, or waiting
`workflow_dispatch` run whose name starts with `Deploy Production [source=manual]`. If it finds one,
it does not dispatch, because the manual run checks out `main` when it starts and so deploys the merge
anyway. If that lookup fails, it dispatches as before. Two gaps remain: the race between the check
and the dispatch, and the other automatic triggers. If a manual run shows as cancelled with no newer
deploy of its SHA, dispatch it again once the queue is clear.

## Red-deploy freeze

Deploy Production starts with a freeze gate. If the last *attempted* Deploy
Production run on `main` is red, later deploys skip migrations instead of
failing. Gate-blocked, cancelled, skipped, and neutral runs are ignored, so
the gate cannot latch on itself and a cancelled run cannot lift the freeze.

Factory merge drains honor the same freeze so more changes cannot land on a
broken production deploy, except PRs labeled `deploy-fix`. A runs-API error
fails open with a warning rather than freezing.

The repository owner unfreezes a red deploy by dispatching Deploy Production
with `override_freeze=true` and a required `reason` after the fix is on
`main`. `github.actor` must be the repository owner. The reason is logged in
the run summary. Factory workers must not use that override; they can label a
fix PR `deploy-fix` instead. See [Deployment](DEPLOYMENT.md#red-deploy-freeze).

## Deployment retention

Hobby Functions Storage is charged per retained deployment. After a successful
production deploy and `/health` smoke — and also when the exact-SHA preflight
skips a duplicate deploy — Deploy Production runs
`scripts/prune_vercel_deployments.py`.

Keep policy (keep-N=1 production Ready):

1. Never delete the live production alias target (`targets.production`).
2. Delete every other terminal deployment, including the previous READY
   production, leftover preview rows, and ERROR/CANCELED/FAILED records.
   There is no rollback candidate.
3. Leave in-progress deployments untouched.

Deletes use `DELETE /v13/deployments/{dpl_...}` only, in batches of at most 200
with backoff on rate limits. The script never calls `vercel remove comic-pile`
and never deletes the Vercel project. Prune errors are `--fail-soft`: they are
logged clearly and do not fail the migrate/deploy/smoke job.

Dry-run locally (requires `VERCEL_TOKEN`, `VERCEL_PROJECT_ID`, and `VERCEL_ORG_ID`):

```bash
python scripts/prune_vercel_deployments.py --dry-run
```

Manual emergency cleanup, if the automated path cannot run, must keep `--safe`:

```bash
vercel remove comic-pile --safe --yes --scope joshclwrens-projects
```

That CLI form also keeps only the current production alias. Prefer the script
so cleanup stays on `DELETE /v13/deployments/{dpl_...}` and never invokes
`vercel remove comic-pile`.

## Daily release-source sync (Vercel Cron)

ComicPile runs release-source synchronization once per day through Vercel Cron.
The job uses the existing FastAPI function; it does not require another service,
a long-running worker, or a GitHub Actions scheduler.

```json
{
  "crons": [
    { "path": "/api/v1/cron/release-sync", "schedule": "0 9 * * *" }
  ]
}
```

On the Vercel Hobby tier the job may start at any point inside the `09:00` UTC
hour. Do not add a more frequent schedule; once daily is the v1 contract.

### Required `CRON_SECRET`

Set a random `CRON_SECRET` (at least 16 characters) in the Vercel project's
Production environment variables. Vercel automatically sends it to the cron
path as `Authorization: Bearer <CRON_SECRET>`. Never commit the value, put it in
a URL, or copy it into an issue or log.

The endpoint fails closed:

- no usable `CRON_SECRET` in the deployment: `503`, and no work runs;
- missing or incorrect bearer value: `401`, and no work runs;
- correct value: the sync runs.

Merging the cron configuration therefore does not start production
synchronization on its own. The job remains inert until an operator configures
`CRON_SECRET`, which is the intended activation boundary for the Option E
exclusion gate (#3671). The scheduled run delegates to the existing release-sync
service, so durable collection exclusions, confirmed-volume identity checks, and
per-owner ownership rules still apply.

### Concurrency and retry behavior

Vercel may deliver a scheduled invocation more than once or while a previous
invocation is still running. The endpoint takes a transaction-scoped PostgreSQL
advisory lock before touching provider or reader data. If another invocation
holds the lock, the second call exits cleanly with HTTP `200` and:

```json
{
  "success": true,
  "status": "already_running",
  "message": "Release sync skipped: another scheduled run is already active",
  "result": { "status": "already_running" }
}
```

`already_running` is a no-op, not an error. The next daily run reprocesses the
same owners idempotently, and issue adoption converges on canonical ComicVine
identity instead of creating duplicates.

### Manual authenticated test

Use the deployment secret from your shell environment without printing it:

```bash
curl --fail --silent --show-error \
  --header "Authorization: Bearer ${CRON_SECRET}" \
  https://comic-pile.vercel.app/api/v1/cron/release-sync
```

A successful run returns `status: "completed"` plus secret-free counters for
owners, sources, created/reused issues, skipped future or unknown-date issues,
failures, excluded sources/issues, duration, and whether the wall-clock budget
deferred any owners.

### Observability

Each run emits structured `release_sync_cron_*` log events with owner and source
counts, failures, truncation, and duration. Logs and responses never include
`CRON_SECRET`, `COMICVINE_API_KEY`, the database URL, or provider raw secrets.
The response is marked `Cache-Control: no-store`.

The runner stops starting new owners after a bounded wall-clock budget and
reports the remainder as `users_deferred` with `truncated: true`. The next daily
run catches those owners up.

## Live-project verification

The Vercel project must track `main` as its Production Branch. Verify this in **Project Settings → Environments → Production → Branch Tracking**.

After this change is merged:

1. Push or update a non-production branch and confirm that no Vercel deployment is created.
2. Merge a validated change to `main` and confirm that one Production deployment is created.
3. Allow the factory-completion and scheduled recovery triggers to run and confirm they do not
   create another deployment for the same SHA.
4. Confirm the production alias still points to the successful `main` deployment.
5. Confirm older deployments were pruned down to the current production alias
   only (`targets.production`). The previous READY production must be gone.

Do not add Preview credentials, Preview databases, Preview Redis instances, or Preview-specific runtime branches. Disposable service instances used by local development or GitHub Actions are separate from Vercel Preview and remain supported.

During an unsettled production rollout, pruning temporarily retains READY production deployments as well as the incoming build. Vercel can report the BUILDING deployment as `targets.production` before it serves the public alias. Pruning refreshes the protected set before every deletion. Once the production target is READY and no production build remains in progress, the normal keep-N=1 policy resumes.
