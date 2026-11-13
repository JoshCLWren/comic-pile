# Neon-backed factory discovery state and event projections

This isolated database is a shared discovery cache with event-maintained
issue/PR projections. It never authorizes a GitHub label mutation, review,
required check, or merge. Ownership changes still require live GitHub validation.

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

## Event-fed target projections

A trusted `Factory Target Projection Ingest` workflow receives GitHub
`issues` and `pull_request_target` events and stores each changed target in
the existing `factory_state_kv` table under
`factory-projection-v1:<repo>:<issue|pr>:<number>`.

The webhook job checks out **main**, never the PR head, runs no model-generated
code, and uses the existing restricted `factory_state_rw` Neon connection.
It normalizes GitHub webhook fields into the same shape used by the controller
(`number`, labels, timestamps, and for PRs head SHA, draft and merge metadata).
Closed targets are tombstoned, not returned as work.

Once bootstrapped, the dispatcher reads projected open issues and PRs from Neon
instead of repeatedly running broad GitHub lists. A full GitHub discovery
snapshot rechecks each kind every **30 minutes** when the dispatcher next
needs the data, repairing missing webhooks, stale labels, and missed closures.
Snapshot writes use a transaction lock shared with webhook writes, timestamp
ordering, and a full-snapshot watermark to avoid overwriting newer events.
Only changed target rows produce reconciliation events.

If Neon is not configured or a projection read fails, the existing shared
GitHub discovery cache remains as a fallback. Exact-head CI/review/merge and
label ownership checks are still performed live at mutation boundaries.

## Safety and freshness

Discovery results may be up to the TTL old. Every lease acquisition and every
exact-head review, CI, and merge gate still rechecks current GitHub state at its
mutation boundary. A cache record never by itself allows a merge. Work selection
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

This cache removes redundant shared discovery reads. It now ingests issue/PR webhook events and repairs projections on a 30-minute
cadence, but **does not** eliminate per-PR review, CI, or ready-merge checks. Those actions must remain live at the
authoritative mutation boundary. Other workflow-specific full scans should be
measured separately instead of assuming this cache fixes the entire quota.
