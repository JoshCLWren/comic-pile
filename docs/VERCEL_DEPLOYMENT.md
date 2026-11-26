# Vercel deployment

ComicPile uses Vercel for production only. The production branch is `main`.

This document describes the checked-in deployment workflow and routing contract. Live Vercel/Neon project settings and successful production probes remain operator verification; documentation reconciliation does not itself prove a fresh deployment.

## Deployment contract

- A push or merge to `main` may create one production deployment for that exact commit SHA.
- Pull requests and non-production branches must not create Vercel deployments.
- Pull requests are validated locally and through GitHub Actions.
- The React/Vite frontend is built as static output. Every deployed `/api/*` operation is served by native Rust (`api/native_roll.rs`); retained v1 paths are compatibility contracts, not a Python runtime. Bare production health/docs paths return 404 from Vercel's explicit legacy-path rule.
- Neon is the production PostgreSQL provider.

`vercel.json` disables Vercel Git deployments. The migration-aware
`.github/workflows/deploy-production.yml` workflow is the only supported deployment path.

The workflow listens for a direct `main` push and also retains factory-completion and scheduled recovery triggers. A merge performed with the built-in `GITHUB_TOKEN` (`github-actions[bot]`) suppresses the normal push event, so `Production Deploy Wakeup` observes completed factory Entry runs and dispatches deployment when `main` advanced. Scheduled recovery remains a fallback.

### Factory merges and deployment wakeup

Factory Ready Merge Drain and the fixed-model dispatcher's ready drain may merge only after the exact-head gates pass. Their shared dispatch helper calls `gh workflow run deploy-production.yml --ref main -f source=factory-merge` once after a run that actually merged a PR. Local/worker merges are also permitted by `docs/AUTONOMOUS_FACTORY_POLICY.md` only after the same gates.

`Production Deploy Wakeup` observes completed Fixed Model Factory Entry runs and dispatches Deploy Production when `main` advanced while the worker ran. The current wakeup workflow calls `gh workflow run` directly without `source=factory-merge`; Deploy Production therefore treats it as a manual force redeploy. This is a known integration discrepancy: the wakeup path does not use the shared helper's factory-merge input. Do not change the workflow or schedule as part of documentation repair; record and repair it through the existing authorized factory/automation process.

Dispatched runs expose their source and reason in the Actions run name. A manual dispatch deliberately bypasses exact-SHA deduplication as the force-recovery path.

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

## Deployment retention and rollback candidate

Hobby Functions Storage is charged per retained deployment. After successful
production deployment and `/api/v2/health` smoke, and when the exact-SHA
preflight skips an already-ready deployment, Deploy Production invokes
`scripts/prune_vercel_deployments.py`.

**Keep-N=2 production READY policy:**

1. Never delete the live production alias target (`targets.production`).
2. Preserve the most recently created **READY production** deployment other
   than the live alias target as the one rollback candidate. A failed,
   canceled, building, or preview deployment must never displace that
   candidate, even if created more recently.
3. Leave in-progress deployments untouched. If an incoming rollout is
   unsettled or the alias target is not READY, retain *all* READY production
   deployments until a subsequent settled prune establishes the safe two.
4. Prune other terminal rows, including older READY production, previews,
   ERROR/CANCELED/FAILED, only after refreshing Vercel's project target and
   deployment list immediately before each deletion. API-level alias-delete
   protection remains a final safeguard.

Prune uses only `DELETE /v13/deployments/{dpl_...}`, batches at most 200,
and retries rate limits. Errors are `--fail-soft` so a completed
migration/deploy/smoke does not become red solely because cleanup failed.

The retained previous READY deployment provides a bounded recovery candidate
in the Vercel dashboard. To verify recoverability without interrupting live
traffic, confirm the prior deployment is still READY, its exact commit SHA
and expected metadata are visible, and the dashboard offers an eligible
production promotion/rollback action. A promotion is **not** automatic:
verify the older application remains compatible with the *current* Neon
schema before deliberately restoring it. A READY deployment is not proof of
schema rollback compatibility; the refinery migration runner has no downgrade path.

For a non-destructive listing (requires `VERCEL_TOKEN`,
`VERCEL_PROJECT_ID` and `VERCEL_ORG_ID`):

```bash
python scripts/prune_vercel_deployments.py --keep-n 2 --dry-run
```

**Do not run** `vercel remove comic-pile --safe` for maintenance: that
CLI cleanup has a different retention policy and would discard our previous
READY rollback candidate. Use the project-scoped script instead. If it cannot
run, stop automatic deletion and investigate the credential/API failure rather
than falling back to a project-level remove operation.

## Daily release-source sync (Vercel Cron)

ComicPile runs release-source synchronization once per day through Vercel Cron.
The same `/api/v1/cron/release-sync` URL is now served by the native Rust handler;
it does not require a Python function, another service, or a long-running worker.

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
`CRON_SECRET`, which is the required authentication boundary for the native
release-source collection-exclusion guard (#3671). The scheduled run delegates to the existing release-sync
service, so durable collection exclusions, confirmed-volume identity checks, and
per-owner ownership rules still apply.

### ComicVine creator-repair cadence (#4623)

The native Rust `GET /api/v2/maintenance/comicvine-metadata-repairs`
endpoint executes a bounded batch synchronously inside its authenticated HTTP
invocation. The Vercel Hobby cron still runs **daily** at 10:00 UTC because a
more frequent Vercel cron schedule is not supported on that plan.

To recover pending and expired leases promptly, the existing free GitHub
Actions runner invokes the same endpoint **four times per hour** in
`.github/workflows/comicvine-metadata-repair.yml`. This schedule is enabled
only from the protected default branch and never runs secret-bearing PR code.
It serializes invocations, checks the HTTP status and the provider configuration
flag, and fails visibly if credentials or the worker are unavailable.

**Required activation:** configure GitHub Actions repository secret
`CRON_SECRET` to the same value already configured in the Vercel production
project. Do not print or commit the value. The workflow deliberately fails
rather than skipping work if the secret is absent or mismatched. After the
production Rust deployment, use the workflow's manual dispatch once, confirm
a successful response and provider configuration, and verify the original
ComicVine identity and backlog in Neon before closing #4623. The built-in
Vercel daily recovery run remains as a fallback.

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
5. After a settled rollout, confirm pruning retained the live production alias
   plus exactly one previous READY production deployment as the rollback candidate.

Do not add Preview credentials, Preview databases, Preview Redis instances, or Preview-specific runtime branches. Disposable service instances used by local development or GitHub Actions are separate from Vercel Preview and remain supported.

During an unsettled production rollout, pruning temporarily retains READY production deployments as well as the incoming build. Vercel can report the BUILDING deployment as `targets.production` before it serves the public alias. Pruning refreshes the protected set before every deletion. Once the production target is READY and no production build remains in progress, the normal keep-N=2 policy resumes.


### Automatic deployment repair

`Production Deploy Recovery` runs after Deploy Production and every 15 minutes.
A real attempted release failure opens or refreshes one GitHub repair issue,
including the failed run and step. Updates preserve active factory leases.
The issue enters the ordinary factory queue as a critical `deploy-fix`; fixes
retain normal exact-head CI and independent review requirements.

A failed release is reported as a reviewed `deploy-fix` repair issue. Repairs
use the ordinary exact-head CI, independent review, and production deployment
gates; there is no red-deploy freeze or override path.
Preflight publishes a run-attempt-specific `deployment-attempt-N` artifact with the
selected checkout SHA before dependency setup. Recovery incidents use that evidence;
historical or expired metadata is explicitly unavailable, never guessed from the
workflow trigger SHA. Missing exact-attempt evidence cannot reconcile a failed CLI
deploy against the live alias.
Only a successful actual deployment with both production probes passing closes
the managed repair issue; live worker leases are left for that worker to finish.

The health probe reports the executable name read from the OS, OS/architecture,
and the package, compiler version and source revision captured during the build.
Deploy Production supplies the exact SHA to the build and checks that revision
in the live response. The compatibility `rust` label alone is not deployment
proof. These fields provide operational evidence, not cryptographic attestation.
