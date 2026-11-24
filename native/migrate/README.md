# comicpile-migrate

Rust database migration runner (successor to the retired Alembic tooling; the
runner still recognizes production databases stamped by the historical
`alembic_version` table), backed by
[refinery](https://crates.io/crates/refinery).

```sh
MIGRATE_DATABASE_URL=postgresql://... cargo run --locked -- up
```

- `migrations/V1__baseline.sql` is a checked-in `pg_dump --schema-only` of the
  historical Alembic head `i5378deferred01`. That
  revision is a no-op schema repair on top of `c44050000002`, so the baseline
  SQL is unchanged. Never edit an applied migration; append `V2__*.sql` etc.
- `migrations/V2__queue_exclusion_groups.sql` adds the queue-exclusion group
  schema introduced for container bulk remove/restore in Queue (#5435), bringing
  the schema to the historical Alembic head `m54i537800001`.
- `BASELINE_ALEMBIC_HEAD` in `src/lib.rs` records that historical head; new
  schema changes are append-only refinery migrations, never new Alembic
  revisions.
- Empty database: all migrations run and `alembic_version` is stamped with the
  current head.
- Database whose `alembic_version` is at the baseline schema head
  (`c44050000002`/`i5378deferred01`): V1 is recorded as adopted and V2 runs.
  Database already at the queue-exclusion or merged head: both migrations
  are recorded as adopted without executing, using refinery's own
  `Target::FakeVersion` guarded by `alembic_version`. Any other revision or
  unmanaged schema is refused.
- Stale external-identity status checks predating the deferred-repair revision
  are repaired idempotently before the current head is stamped.
- CI (`rust-roll.yml`) applies the migrations to a disposable test database and
  runs the workspace tests against it.
