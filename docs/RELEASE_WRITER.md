# Release Writer: direct Neon publication

## Post-incident status

**Reactivated after the October 20, 2026 incident**, with automatic execution
limited to one exact PR for merge/manual events and four independent sources
per recovery run. Successful `Deploy Production` completions and a three-hour
retry recover missed or failed merge events from a bounded 72-hour lookback;
the previous unbounded historical reconciliation and hourly release-writer scans
remain removed. The writer publishes straight to Neon without invoking the
ComicPile Vercel release API. PR #3989 stopped the original workflow; PR #3991
installed the isolated direct-Neon publisher.

## Workflow

Release writing is internal GitHub Actions automation, not a user-facing API client.
A trusted `pull_request_target` closed event considers only merged PRs using
`main` code. Manual dispatch requires an exact merged PR number. A successful
`Deploy Production` completion or scheduled retry discovers up to four missing ledger sources
from merged PRs in the last 72 hours. Each run is serialized through the
`release-writer` concurrency group.

1. A trusted discovery job reads the healthy native production build revision
   and uses Git ancestry to exclude merged sources that are not actually live.
   It selects at most four sources whose exact repository, PR number and merge SHA
   are absent from the ledger (one for exact events). Exact existing rows are
   idempotent no-ops; conflicting or partial provenance fails closed. A failed
   deployment does not start discovery. A bounded Actions cache records only
   attempted merge SHAs and timestamps before generation. Never-attempted sources
   take priority, then the least recently attempted; the cache is a scheduling
   hint, not publication evidence or a source of credentials. If the cache is
   evicted or an attempt-hint file is invalid, hints are lost and recovery falls
   back to oldest-first ordering by merge time.
2. Each unprivileged generate matrix job invokes the restricted OpenCode agent
   for one selected source, with at most two running in parallel. The release_writer.py helper validates content and
   classification and writes one local JSON candidate. No Neon credential or
   Vercel release token is supplied to the agent. Test-only changes cannot be
   published as public reader updates.
3. Each candidate is transferred between jobs as a per-PR short-lived GitHub
   Actions artifact containing release content and public merge metadata only.
   Matrix fail-fast is disabled: a failed generation does not cancel other
   generations or prevent their persistence. A missing artifact fails before
   credentials are loaded.
4. A separate trusted persist job rechecks the PR number and merge SHA against
   GitHub, validates public/internal provenance and reader-facing content
   again, and verifies that the merge SHA is still in the actual live production
   revision immediately before loading the database credential. A public
   candidate whose complete bounded diff is test-only is rewritten as a durable
   internal record, so it neither reaches readers nor blocks newer missing
   sources by failing the same recovery selection repeatedly. The deployment
   recheck closes the rollback/failed-deployment window during model generation.
5. Parameterized SQL inserts a record only when both stable source identities
   are unused. Exact retries are no-ops; conflicting PR or SHA identities
   fail without overwriting records (even retracted ones).

An exact source attempt has at most 70 minutes of job execution; a full
four-source batch has at most 130 minutes of job execution (10 minutes for
discovery, two waves of 45-minute generation and two waves of 15-minute
persistence). The three-hour retry drains a quiet final deployment independently
of later merges. With healthy runners/services, no older queue, and at most
four missing sources, the next scheduled attempt finishes within three hours
plus 130 minutes. Larger backlogs drain in batches and failed sources rotate
behind unattempted sources. GitHub scheduling/runner delays, sustained overload,
cache eviction, and external failures can exceed this target; no successful
publication is claimed for those cases. Missing sources approaching the 72-hour
lookback expiry emit a workflow warning for explicit reconciliation. An exact
manual dispatch can recover an older source; no manual refresh is the only
recovery path.

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
unbounded source reconciliation. The deployment-triggered and three-hour
scheduled 72-hour lookback are bounded recovery mechanisms. Generation and
trusted persistence remain separate jobs; each persistence matrix entry requires
its own staged candidate, even when a sibling generation fails. The factory completion dispatcher remains disabled
to prevent duplicate releases from the same merged PR.

Exact source checks, live-deployment checks at selection and publication,
content validation, conflict handling, idempotent retries, and isolation of
model and database credentials are required. A production publish run must be
inspected separately after activation to confirm runtime health and the
published source record.

Public releases must have reader-visible classification evidence and honor
linked-issue scope fences. Internal-only factory, CI, test-only and refactoring
changes are recorded with internal visibility. In particular, a model's
unsupported public classification of a complete test-only diff is converted to
a durable internal outcome rather than rejected and retried indefinitely. A
staged candidate does not count as published: only a successful trusted Neon
transaction establishes durability.
