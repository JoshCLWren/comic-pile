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

The trusted completion collector records verified worker starts and
success/failure *signals* from registry comments. These terminal signals are
not liveness heartbeats and never extend a lease. The controller renews
unexpired leases only for workers it independently verifies have active
GitHub Actions runs, and clears token-matching Neon claims after verified
GitHub label release. Pre-session abort cleanup configures the restricted Neon
connection in its own trusted runner before touching GitHub labels. If the
connection is unavailable, it refuses a split release; the lease can expire
and be reconciled safely instead. A separate post-session cleanup job runs
inside the same per-worker concurrency lock after every executing worker exits,
checks live GitHub target ownership, and releases the matching Neon claim.
This also handles retries where the worker already removed its owner labels.
Both trusted cleanup jobs refuse to release labels if the Neon connection is
unavailable. The coding/model job receives no Neon key or DSN. The worker Entry
independently runs a trusted, non-model post-worker
job to classify the finished factory-job log and persist the immutable
completion/failure event. It separately dispatches the capacity Completion
Drain. The outcome recorder does not share the drain's dispatcher concurrency
lock, so capacity backlogs cannot postpone durable event recording. The
runtime observer remains an idempotent backup when workflow_run notifications
are delivered. Agent execution, including the local Qwen reviewer, never
gets database credentials.

These first-stage leases deliberately retain the live GitHub target checks.
Worker health and stale-run reconciliation still use some GitHub API reads.
Per-item issue/PR projections and event-triggered selective reconciliation are
follow-up work; **do not claim this change alone eliminates broad discovery**.

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

The first trusted webhook bootstraps each missing complete issue/PR snapshot
once under per-kind advisory locks, without repeated full scans across concurrent
events. Webhook events read one live target *inside* the advisory transaction,
ensuring equal-timestamp deliveries cannot reorder authoritative state.

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

Issue/PR events now update individual Neon projections and a live listing
reconciles drift every 30 minutes. Exact-head checks and merge verification
remain live GitHub operations. Those actions must remain live at the
authoritative mutation boundary. Other workflow-specific full scans should be
measured separately instead of assuming this cache fixes the entire quota.
