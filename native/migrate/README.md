# comicpile-migrate

Rust database migration runner (successor to Alembic, which is frozen), backed by
[refinery](https://crates.io/crates/refinery).

```sh
MIGRATE_DATABASE_URL=postgresql://... cargo run --locked -- up
```

- `migrations/V1__baseline.sql` is a cleaned `pg_dump --schema-only` of the
  Alembic head `i5378deferred01` (`make roll-test-schema` regenerates it). That
  revision is a no-op schema repair on top of `c44050000002`, so the baseline
  SQL is unchanged. Never edit an applied migration; append `V2__*.sql` etc.
- `migrations/V2__queue_exclusion_groups.sql` adds the queue-exclusion group
  schema introduced for container bulk remove/restore in Queue (#5435), bringing
  the schema to the current Alembic head `m54i537800001`.
- `BASELINE_ALEMBIC_HEAD` in `src/lib.rs` is the current Alembic head and must
  stay in sync with Alembic/parity checks. Each new Alembic revision must be
  mirrored by a new refinery migration (or a regenerated baseline) before the
  pin advances.
- Empty database: all migrations run and `alembic_version` is stamped with the
  current head.
- Alembic database whose `alembic_version` is at the baseline schema head
  (`c44050000002`/`i5378deferred01`): V1 is recorded as adopted and V2 runs.
  Alembic database already at the queue-exclusion or merged head: both migrations
  are recorded as adopted without executing, using refinery's own
  `Target::FakeVersion` guarded by `alembic_version`. Any other revision or
  unmanaged schema is refused.
- Stale external-identity status checks predating the deferred-repair revision
  are repaired idempotently before the current head is stamped.
- CI (`rust-roll.yml`) builds an Alembic database and a Rust database and fails
  on any normalized `pg_dump` difference
  (`scripts/check_rust_migration_parity.py`). <!-- docs-path-check: ignore -->
