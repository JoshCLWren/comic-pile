# Release Writer: direct Neon publication

## Post-incident status

**Reactivated after the October 20, 2026 incident**, with automatic execution
limited to exactly one merged pull request per release-writer run. The previous
unbounded historical reconciliation and hourly scans remain removed. The writer
publishes straight to Neon without invoking the ComicPile Vercel API. PR #3989
stopped the original workflow; PR #3991 installed the isolated direct-Neon
publisher.

## Workflow

Release writing is internal GitHub Actions automation, not a user-facing API client.
A trusted `pull_request_target` closed event processes only merged PRs using
`main` code. Manual dispatch requires an exact merged PR number. Factory merges
performed with `GITHUB_TOKEN` do not emit `pull_request_target`, so the writer
also reacts to `Factory Ready Merge Drain` and `Fixed Model Factory Dispatcher`
`workflow_run` completions by dispatching exact-PR release-writer runs for
recently merged PRs (bounded lookback, not a historical reconciliation).

Recovery after a missed event, a failed generation, or a failed persistence step
is driven by `Deploy Production` completions rather than by a schedule. The
trusted `recover` job reads the live production `/api/v2/health` identity, keeps
only merged PRs contained in the deployed revision, and selects the oldest one
with no release-ledger row. It dispatches exactly one `workflow_dispatch` run for
that PR, so a failed or missed writer event is retried on the next successful
deployment without manual refresh and without announcing undeployed work. The
bounded publication delay is therefore **one successful production deployment
plus one complete writer run**; a failed write is retried by the next deployment.

Each PR gets its own release-writer concurrency group so a later merge cannot
replace an earlier pending PR. Single-writer publication is preserved by the
trusted Neon publish transaction: source identity rows are locked/checked and
inserted with `ON CONFLICT DO NOTHING`, so duplicate dispatches are idempotent.
The recovery selector reuses the same two ledger source identities and fails
closed on ambiguous provenance; repeated discovery never duplicates or rewrites
a correct entry.

1. An unprivileged generate job invokes the restricted OpenCode agent. The
   release_writer.py helper validates content and classification and writes
   one local JSON candidate. No Neon credential or Vercel release token is
   supplied to the agent.
2. The candidate is transferred between jobs as a short-lived GitHub Actions
   artifact containing release content and public merge metadata only.
3. A separate trusted persist job rechecks the PR number and merge SHA against
   GitHub, re-proves that the merge is still contained in the live production
   revision before loading any database credential, reclassifies a complete
   test-only diff as internal, validates public/internal provenance and
   reader-facing content again, and connects directly to production Neon
   PostgreSQL using a DSN obtained through the Neon management API.
4. Parameterized SQL inserts a record only when both stable source identities
   are unused. Exact retries are no-ops; conflicting PR or SHA identities
   fail without overwriting records (even retracted ones).

No Vercel invocation or ComicPile HTTP API is needed to check/write releases.
The public What's New read API continues to read the releases table.

Recovery reads accept both REST paths and absolute GitHub API URLs: discovery
builds absolute URLs and must never prefix `GITHUB_API_BASE` a second time. A
double prefix produced the unresolvable host `api.github.comhttps` and silently
stranded release notes (issue #5693). Request failures name only a coarse URL
kind (`GitHub API URL`, `production health URL`), never the raw URL or token,
and a failed selection emits an `::error::` annotation plus a step summary that
lists the still-missing PRs.

## Secrets and scope

The existing production migration configuration NEON_API_KEY (repository secret)
and NEON_PROJECT_ID (repository variable) is available only in the trusted
persistence job. The DSN is masked and never added to agent prompts, artifacts,
logs or the generate job. NVIDIA_API_KEY remains in the generation job.

The current integration uses the existing production neondb_owner connection.
Before reactivating, prefer replacing it with a dedicated release-table-only
Postgres role; the new code requires SELECT and INSERT on releases plus sequence
usage. No Neon branch, clone, migration or database mutation is involved here.

Legacy RELEASE_API_URL and RELEASE_WRITER_TOKEN are not configured in the new
production writer workflow. Their helper fallback remains only for older
unit tests and backwards compatibility, not the GitHub Actions path.

## Operating constraints

Do not restore the September 22 backfill, a schedule, or broad source
reconciliation. The merge-drain `workflow_run` recovery is a bounded lookback
(30 minutes, at most 20 PRs) that dispatches exact PR numbers; deployment-driven
recovery inspects at most 72 hours and three pages of merged PRs and stages at
most one source per run. Neither is a historical scan. Generation and trusted
persistence are separate jobs; the latter runs only after generation succeeds
and deployment is re-proven. The factory completion dispatcher remains disabled
to prevent duplicate releases from the same merged PR.

Exact source checks, content validation, conflict handling, idempotent retries,
and isolation of model and database credentials are required. A production
publish run must be inspected separately after activation to confirm runtime
health and the published source record.

Public releases must have reader-visible classification evidence and
honor linked-issue scope fences. Internal-only changes are recorded with
internal visibility. A staged candidate does not count as published:
only a successful trusted Neon transaction establishes durability.
