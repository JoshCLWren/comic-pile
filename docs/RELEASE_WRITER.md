# Release Writer: direct Neon publication

## Post-incident status

**Reactivated after the October 20, 2026 incident**, with automatic execution
limited to exactly one merged pull request per event. The previous unbounded
historical reconciliation and hourly scans remain removed. The writer publishes
straight to Neon without invoking the ComicPile Vercel API. PR #3989 stopped
the original workflow; PR #3991 installed the isolated direct-Neon publisher.

## Workflow

Release writing is internal GitHub Actions automation, not a user-facing API client.
A trusted `pull_request_target` closed event processes only merged PRs using
`main` code. Manual dispatch requires an exact merged PR number. Each run is
serialized through the `release-writer` concurrency group.

1. An unprivileged generate job invokes the restricted OpenCode agent. The
   release_writer.py helper validates content and classification and writes
   one local JSON candidate. No Neon credential or Vercel release token is
   supplied to the agent.
2. The candidate is transferred between jobs as a short-lived GitHub Actions
   artifact containing release content and public merge metadata only.
3. A separate trusted persist job rechecks the PR number and merge SHA against
   GitHub, validates public/internal provenance and reader-facing content
   again, and connects directly to production Neon PostgreSQL using a DSN
   obtained through the Neon management API.
4. Parameterized SQL inserts a record only when both stable source identities
   are unused. Exact retries are no-ops; conflicting PR or SHA identities
   fail without overwriting records (even retracted ones).

No Vercel invocation or ComicPile HTTP API is needed to check/write releases.
The public What's New read API continues to read the releases table.

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

Do not restore the September 22 backfill, an hourly schedule, or broad source
reconciliation. Generation and trusted persistence are separate jobs; the
latter runs only after generation succeeds. The factory completion dispatcher
remains disabled to prevent duplicate releases from the same merged PR.

Exact source checks, content validation, conflict handling, idempotent retries,
and isolation of model and database credentials are required. A production
publish run must be inspected separately after activation to confirm runtime
health and the published source record.

Public releases must have reader-visible classification evidence and
honor linked-issue scope fences. Internal-only changes are recorded with
internal visibility. A staged candidate does not count as published:
only a successful trusted Neon transaction establishes durability.
