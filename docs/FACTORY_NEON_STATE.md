# Neon-backed factory discovery and coordination

The isolated database supports both a shared discovery cache and an atomic
worker reservation ledger. Neon is authoritative for **transactional factory
worker reservations**; GitHub remains authoritative for live target labels,
review verdicts, required checks, exact heads, and merge authorization.

The dispatcher needs **both** a fresh GitHub ownership check and a successful
Neon transaction to assign work. A Neon conflict or outage does not fall back
to a potentially duplicate claim in trusted dispatcher jobs.

## Provisioning

- Existing Neon project: `comic-pile` (no new project or compute)
- Separate PostgreSQL database: `factory_state`
- Restricted database role: `factory_state_rw`, read/write grants for
  `factory_state.public` only
- Schema versioned at `.github/factory-state-schema.sql`.
- Provisioned against the project's default Neon branch on 2026-11-13.

The trusted factory jobs reuse the **existing** `NEON_API_KEY` Actions secret and
`NEON_PROJECT_ID` Actions variable to retrieve a connection for *only* the
factory role and database. The secret is available only inside the composite
setup step; the DSN is masked and held in a `0600` temporary file on the trusted
runner. The file path, not the connection string, is exported between its steps.

Neither coding-agent workflows nor the local Qwen reviewer use the connection.
Never add the composite action to workflows that execute model-generated code.

## Cached reads and budgets

| Cache key suffix | TTL | Refresh source |
|---|---:|---|
| `open-issues` | 45 seconds | GitHub `issue list` |
| `open-prs` | 45 seconds | GitHub `pr list` |
| `registry-comments` | 120 seconds | Issue #1093 comments, incremental by updated timestamp |

The first heartbeat load visits historical pages once. Subsequent refreshes use
GitHub's `since` query with a one-minute overlap, merging changes by immutable
comment ID. Deletions are not visible through this incremental endpoint; a
rare full refresh may still be needed if an administrator deletes heartbeat
comments, so operational policy should avoid deleting registry history.

A shared Neon refresh lease (75 seconds) prevents most simultaneous jobs from
re-fetching the same source. A cache hit consumes **zero** GitHub REST requests.
Concurrent readers wait up to three seconds for the refreshing job. On a
database failure or prolonged lock contention, the original live GitHub read
remains available. There is no grant of authority from stale data.

## Worker lifecycle and transactional leases

The trusted dispatcher now atomically reserves a worker and every associated
issue/PR target under a PostgreSQL transaction advisory lock. Existing
`factory_state_kv` rows store keys `factory-lease-v1:<repo>:worker:<id>`
and `factory-lease-v1:<repo>:target:<number>`, with one claim UUID and a
15-minute safety expiration. This is **not** the 75-second cache refresh
lock. A failed claim rolls back only its own UUID after verifying GitHub labels;
a verified explicit release clears the whole claim.

The trusted completion collector records recent worker-start/heartbeat changes
from verified GitHub registry comments, while the trusted runtime observer
records classified completion or failure for each immutable Actions run ID.
Events are deduplicated by run/status or source-comment ID/update timestamp.
Agent execution, including the local Qwen code reviewer, never gets database
credentials.

These first-stage leases deliberately retain the live GitHub target checks.
Worker health and stale-run reconciliation still use some GitHub API reads.
Per-item issue/PR projections and event-triggered selective reconciliation are
follow-up work; **do not claim this change alone eliminates broad discovery**.

## Safety and freshness

Discovery results may be up to the TTL old. Every label mutation and every
exact-head review, CI, and merge gate still rechecks current GitHub state at its
mutation boundary. A trusted dispatcher without a Neon connection refuses new
assignments rather than inventing ownership. A cache record never by itself allows a merge. Work selection
can briefly lag a new issue or PR; it must not bypass controls.

The Neon database shares the existing Neon project's compute, so avoid
sub-second polling. JSON snapshots are compact and time-bounded.

## Operational queries

Run these in Neon's SQL editor with database `factory_state`:

```sql
SELECT cache_key, jsonb_array_length(payload) AS records,
       fetched_at, expires_at,
       refresh_owner, refresh_until
FROM public.factory_state_kv
ORDER BY cache_key;
```

```sql
SELECT created_at, event_type, detail
FROM public.factory_state_events
ORDER BY id DESC
LIMIT 30;
```

A healthy dispatcher, completion drain, or status page log should show
`[factory-state] refreshed` or `[factory-state] shared cache hit`.
If it prints `cache read unavailable`, the job is using GitHub's original
read path and must be investigated rather than described as cached.

## Remaining API work

This cache removes redundant shared discovery reads. It does **not** yet ingest
all GitHub events into individual issue/PR rows, nor eliminate all per-PR review
or ready-merge verification calls. Those actions must remain live at the
authoritative mutation boundary. Other workflow-specific full scans should be
measured separately instead of assuming this cache fixes the entire quota.
