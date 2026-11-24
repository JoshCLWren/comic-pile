# Release Writer: direct Neon publication

## Post-incident status

**Reactivated after the October 20, 2026 incident**, with automatic execution
limited to exactly one merged pull request per run. Successful `Deploy Production`
completions recover missed or failed merge events from a bounded 72-hour lookback;
the previous unbounded historical reconciliation and hourly release-writer scans
remain removed. The writer publishes straight to Neon without invoking the
ComicPile Vercel release API. PR #3989 stopped the original workflow; PR #3991
installed the isolated direct-Neon publisher.

## Workflow

Release writing is internal GitHub Actions automation, not a user-facing API client.
A trusted `pull_request_target` closed event considers only merged PRs using
`main` code. Manual dispatch requires an exact merged PR number. A successful
`Deploy Production` completion also discovers the oldest missing ledger source
from merged PRs in the last 72 hours. Each run is serialized through the
`release-writer` concurrency group.

1. A trusted discovery job reads the healthy native production build revision
   and uses Git ancestry to exclude merged sources that are not actually live.
   It selects at most one source whose exact repository, PR number and merge SHA
   are absent from the ledger. Exact existing rows are idempotent no-ops;
   conflicting or partial provenance fails closed. A failed deployment does not
   start discovery.
2. An unprivileged generate job invokes the restricted OpenCode agent for only
   that selected source. The release_writer.py helper validates content and
   classification and writes one local JSON candidate. No Neon credential or
   Vercel release token is supplied to the agent. Test-only changes cannot be
   published as public reader updates.
3. The candidate is transferred between jobs as a short-lived GitHub Actions
   artifact containing release content and public merge metadata only.
4. A separate trusted persist job rechecks the PR number and merge SHA against
   GitHub, validates public/internal provenance and reader-facing content
   again, and verifies that the merge SHA is still in the actual live production
   revision immediately before loading the database credential. This closes
   the rollback/failed-deployment window during model generation.
5. Parameterized SQL inserts a record only when both stable source identities
   are unused. Exact retries are no-ops; conflicting PR or SHA identities
   fail without overwriting records (even retracted ones).

For one missing deployed source with no older writer run queued, its automatic
post-deployment attempt has at most 70 minutes of job execution: 10 minutes for
discovery, 45 for generation and 15 for persistence. GitHub runner queueing and
external-service failures are not disguised as successful publication. A missed
or failed attempt is retried by a later successful deployment completion while
its source remains in the 72-hour lookback; no manual refresh or redispatch is
the only recovery path. Multiple missing sources drain one per run, oldest first.

No Vercel release mutation or ComicPile release-write API is used. Only the
read-only production health endpoint supplies the deployed revision. The public
What's New read API continues to read the releases table.

## Secrets and scope

The existing production migration configuration NEON_API_KEY (repository secret)
and NEON_PROJECT_ID (repository variable) is available only in the trusted
discovery and persistence jobs. Discovery uses the DSN for one read-only source
lookup; persistence uses it for the validated insert. The DSN is scoped to those
steps, masked, and never added to agent prompts, artifacts, logs or the generate
job. NVIDIA_API_KEY remains in the generation job.

The current integration uses the existing production neondb_owner connection.
Before reactivating, prefer replacing it with a dedicated release-table-only
Postgres role; the new code requires SELECT and INSERT on releases plus sequence
usage. No Neon branch, clone, migration or database mutation is involved here.

Legacy RELEASE_API_URL and RELEASE_WRITER_TOKEN are not configured in the new
production writer workflow. Their helper fallback remains only for older
unit tests and backwards compatibility, not the GitHub Actions path.

## Operating constraints

Do not restore the September 22 backfill, an hourly release-writer schedule, or
unbounded source reconciliation. The deployment-triggered 72-hour lookback is
the bounded recovery mechanism; it does not change any automation schedule.
Generation and trusted persistence are separate jobs; the latter runs only
after generation succeeds. The factory completion dispatcher remains disabled
to prevent duplicate releases from the same merged PR.

Exact source checks, live-deployment checks at selection and publication,
content validation, conflict handling, idempotent retries, and isolation of
model and database credentials are required. A production publish run must be
inspected separately after activation to confirm runtime health and the
published source record.

Public releases must have reader-visible classification evidence and honor
linked-issue scope fences. Internal-only factory, CI, test-only and refactoring
changes are recorded with internal visibility. A staged candidate does not
count as published: only a successful trusted Neon transaction establishes
durability.
