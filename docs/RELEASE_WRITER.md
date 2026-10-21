# Release Writer: direct Neon publication

## Incident status

**DISABLED since October 20, 2026.** Previously the writer repeatedly queried the
ComicPile release-source endpoint through Vercel, including unnecessary scans
back to September 22. The emergency stop in PR #3989 remains in force.
This refactor does not restart release-writing automation.

## Workflow

Release writing is internal GitHub Actions automation, not a user-facing API client.
When separately reauthorized, it must process one exact merged PR per run.

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

## Reactivation conditions

Both workflow jobs still have unconditional if: ${{ false }} guards.
Do not remove them without fresh, explicit authorization and passing CI.

Verify the exact-PR source check, content validation, conflict handling,
no-op retry behavior, model credential isolation, and direct PostgreSQL
insert in a controlled test before any production write.

Manual workflows must receive a specific merged PR number. Do not restore
the old September 22 backfill or any unbounded reconciliation loop.
The separate factory dispatcher must also remain stopped while the
incident is open.

Public releases must have reader-visible classification evidence and
honor linked-issue scope fences. Internal-only changes are recorded with
internal visibility. A staged candidate does not count as published:
only a successful trusted Neon transaction establishes durability.
