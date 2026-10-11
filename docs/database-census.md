# Database census

Read-only storage, index, and query census for issue #3217 (DB scale 01, part of
#the #3216 campaign). It establishes a reproducible baseline before any storage
claim is made or any index is dropped.

The census never changes application behavior, never collects external provider
data, and never runs against a database that was not explicitly supplied on the
command line.

## Layers

- `app/repositories/database_census_repository.py` owns every SQL statement.
- `app/services/database_census_service.py` orchestrates, bounds samples, and
  redacts. It builds no SQL.
- `scripts/database_census.py` is the command.
- `scripts/generate_census_fixtures.py` writes deterministic synthetic fixtures.

## Safety properties

| Property | How it is enforced |
|---|---|
| Read-only | `SET TRANSACTION READ ONLY` is the first statement of the census transaction; PostgreSQL rejects any write even if every other guard failed. |
| Bounded runtime | `SET LOCAL statement_timeout` (default 30s), `SET LOCAL lock_timeout` (1s), and `SET LOCAL idle_in_transaction_session_timeout`. |
| Bounded samples | `--sample-limit` (default 10) caps every workload sample. |
| No mutation modes | `contains_mutation()` rejects any statement containing a mutating or session-changing keyword, including through a CTE or a trailing statement. `CENSUS_QUERIES` is covered by a regression test, so `EXPLAIN ANALYZE` can never run on a write. |
| Synthetic by default | Without `--database-url` the command emits synthetic data and opens no connection. |
| No secrets or user data | No query selects titles, notes, payloads, credentials, or reader ids. Bind parameter values are replaced with `<sample-value>`; `user_id` and `session_id` never appear in the measured sections. |
| No transaction residue | The census transaction is always rolled back. |

## Report format

Reports are versioned by `report_version` (`database-census/v1`) so consumers
detect schema drift.

```text
report_version
metadata        collected_at, postgresql_version, statement_timeout_seconds,
                sample_limit, read_only_transaction
storage         measured table bytes (total/table/index) and TOAST bytes
tables          measured_rows  <- exact COUNT(*)
                estimated_rows <- pg_class.reltuples, reported separately
                estimate_available, estimate_delta
indexes         full catalog with key columns, predicate, uniqueness,
                constraint backing and deferrability
                potential_redundant_indexes (flagged, never removal verdicts)
snapshots       payload distribution by version, session-state presence,
                workload_growth for latest undo and reorder
queries         EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) plans, redacted
constraints     primary/foreign/unique inventory with deferrability
```

Measured bytes and planner estimates are always separate fields. An index
estimate of `-1` from PostgreSQL means "never analyzed" and is reported as
`estimated_rows: null` with `estimate_available: false` rather than as a number.

### Potential redundancy is not a removal verdict

An index is flagged when another index on the same table shares its predicate
and access method and its key is a prefix of the flagged index's key. Every
flag carries `classification: "potential_redundant"` and
`confirmed_safe_removal: false`, plus the `reasons` that block a removal
(`backs_primary_key`, `enforces_uniqueness`, `backs_constraint:*`,
`constraint_is_deferrable`, `has_predicate`, `has_recorded_scans`).

The census cannot see planner statistics age, replication lag, or which index a
future workload needs. Confirming a safe removal requires a
`DROP INDEX ... CONCURRENTLY` rehearsal on a local clone, which is out of scope
for this issue.

## Reproducible commands

```bash
# Synthetic report (default; opens no connection)
python -m scripts.database_census --output /tmp/census-synthetic.json

# Deterministic fixtures committed under docs/
python -m scripts.generate_census_fixtures --output-dir docs/database-census/fixtures

# Explicitly supplied database; always read-only and bounded
python -m scripts.database_census \
  --database-url 'postgresql+asyncpg://USER:PASSWORD@HOST:5432/DATABASE' \
  --timeout 30 --sample-limit 10 --output /tmp/census.json
```

Creating this tooling does not authorize running it against production. Supply
a local or explicitly approved clone URL.

## Sanitized example output

`fixtures/census_small_library_2_users.json` (2 readers, 10 threads, 50 issues,
20 snapshots of which 18 are legacy full-state and 2 are delta) abridged:

```json
{
  "report_version": "database-census/v1",
  "synthetic": true,
  "metadata": {
    "collected_at": "2026-01-01T00:00:00+00:00",
    "postgresql_version": "synthetic",
    "read_only_transaction": true,
    "scenario": "small_library_2_users",
    "user_count": 2,
    "thread_count": 10,
    "shared_provider_identity_count": 6
  },
  "tables": {
    "threads": { "measured_rows": 10, "estimated_rows": 10, "estimate_delta": 0 }
  },
  "snapshots": {
    "by_version": [
      {
        "version": "1",
        "measured_rows": 18,
        "avg_payload_bytes": 8192,
        "total_payload_bytes": 147456
      }
    ],
    "workload_growth": {
      "sampled_readers": 2,
      "latest_undo": [
        {
          "sample_rank": 1,
          "session_snapshot_rows": 18,
          "thread_state_bytes": 8192,
          "session_state_bytes": 512,
          "event_type": "roll"
        }
      ],
      "reorder": {
        "reorder_event_rows": 2,
        "distinct_threads_moved": 5,
        "queue_move_bytes": 32
      },
      "note": "Rows and payload bytes only. No hardware-specific latency pass/fail claim is made or implied."
    }
  },
  "queries": {
    "queue_listing": {
      "query": "SELECT t.id, t.queue_position, t.issues_remaining FROM threads t WHERE t.user_id = :user_id AND t.status = 'active' AND t.queue_position >= 1 ORDER BY t.queue_position, t.id LIMIT :page_size",
      "parameters": { "user_id": "<sample-value>", "page_size": "<sample-value>" }
    }
  }
}
```

The three committed fixtures cover the required matrix:

| Fixture | Readers | Threads | Issues | Snapshots (legacy/delta) | Shared provider identities |
|---|---|---|---|---|---|
| `census_small_library_2_users.json` | 2 | 10 | 50 | 20 (18/2) | 6 |
| `census_large_library_100_users.json` | 100 | 2500 | 15000 | 7500 (750/6750) | 300 |
| `census_mixed_legacy_delta_snapshots.json` | 25 | 500 | 3000 | 4000 (2500/1500) | 75 |

Fixture byte counts are a declared modelling assumption
(`bytes-per-row` constants in `scripts/generate_census_fixtures.py`), not a
measurement of any real database. A measured baseline comes from running the
command against a local clone.

## Latency claims

The census reports rows and payload bytes for the latest undo and reorder
workloads. It deliberately makes no hardware-specific pass/fail latency claim:
the measured database, its storage tier, and its concurrent load are not
comparable across environments.

## Tests

```bash
pytest tests/test_database_census_service.py
pytest tests/test_database_census_cli.py
pytest tests/test_generate_census_fixtures.py
```

The service tests run against a real PostgreSQL database and assert that a
write inside the census transaction is rejected, that `statement_timeout` and
`transaction_read_only` are actually set, and that seeded reader values never
appear in a report.