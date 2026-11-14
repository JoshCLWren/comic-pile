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


## Operational state and decision projections

The trusted factory now maintains decision state, not just JSON discovery
snapshots. It is created non-destructively by the idempotent DDL inside
.github/scripts/factory_state_operations.py, using the existing
factory_state database and factory_state_rw role. No model/agent runner
receives a connection.

| Relation | Purpose |
| --- | --- |
| factory_model_health | Exact source/model availability, last verified run, cooldown, sticky 410 retirement |
| factory_provider_budget | Account-scope throttle/quota cooldown, optional explicit concurrency cap and daily budget |
| factory_provider_reservation | Capacity reservation tied to the existing worker/target claim UUID and its renewal/release |
| factory_pr_stage_retry | Per-PR, exact-head, exact-stage retry not-before timestamps |
| factory_check_projection | Advisory CI/review outcomes recorded by trusted workflow-run events |
| factory_worker_metrics | Attempts, persisted useful work, completed and failed runs for source-preserving worker ranking |
| factory_runtime_event_keys | Idempotence for the two trusted terminal-run collectors |
| factory_reconciliation_cursor | Last target-reconciliation watermark and coalesced event-driven dispatch wakeups |

The authoritative product gates remain on GitHub. The Neon check projection
**does not grant an approval or green CI**, and merge scripts must still verify
the live exact head, required checks, ownership and review as previously.

### Selection and release

The trusted dispatcher initializes this schema and backfills the last trusted
model outcome for each source/model from the existing registry on its first
run. Future terminal outcomes project provider/model health directly.
factory-model-discovery.yml contributes catalog absence evidence without
changing the checked-in roster. An expired absence can be probed again,
while explicit retired 410 markers remain sticky.

During a worker claim, the existing per-repository advisory lock now also
reserves provider capacity in the **same SQL transaction** as the
worker and issue/PR leases. Releases and verified lease renewals update
the provider reservation under the same ownership token. Aborted
assignments cannot leave a leaked provider-capacity reservation.

Daily metered-source usage is computed from trusted
worker_assigned events in Neon, with the old live GitHub run-list path
available only on a DB read failure. Quota/throttle observations are scoped
to the provider account, except independent OmniRoute model routes. No
unpublished provider concurrency limit is guessed: null means unconfigured.
Checked-in source dispatch caps are still enforced under the atomic lease.

Workers returning a classified failure update the model/provider circuit
breaker from trusted job logs, not untrusted comments. An unchanged PR head
and stage can briefly cool down a failed repair; a new SHA is immediately
eligible. Failed review providers have a bounded backoff. A coalesced
Factory Check Projection Ingest workflow may wake the existing dispatcher
on a relevant completed check, no more frequently than once per two minutes.
This workflow never checks out or executes PR-head code.

A model's successful execution is not the same as a completed product issue.
Productivity rankings use persisted useful work evidence and retain
source-diverse dispatch positions. They are advisory scheduling decisions,
not permission to bypass policy or assigned-work eligibility.

### Operational inspection

The trusted dispatcher prints the one-time backfill count and health-based
worker exclusions. The operational CLI can be used with the restricted
factory DSN on a trusted runner:

    python3 .github/scripts/factory_state_operations.py bootstrap
    python3 .github/scripts/factory_state_operations.py stats

Check the actual DB with these bounded queries:

    SELECT source, model, status, cooldown_until, last_outcome
    FROM public.factory_model_health ORDER BY updated_at DESC LIMIT 30;

    SELECT source, cooldown_until, quota_reset_at, concurrency_limit,
           usage_day, daily_used
    FROM public.factory_provider_budget ORDER BY source;

    SELECT scope, checkpoint, checked_at, changed_count
    FROM public.factory_reconciliation_cursor ORDER BY checked_at DESC LIMIT 20;

A DB outage must not turn missing data into healthy evidence. New claims still
require the existing transactional Neon lease and GitHub ownership check.
The read-only projections have bounded fallbacks, but neither missing cache
nor a late webhook is grounds to merge.
