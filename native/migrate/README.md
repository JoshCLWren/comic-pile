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
- Empty database: baseline runs and `alembic_version` is stamped with the head.
- Alembic database whose `alembic_version` equals the baseline head
  (production): the baseline is recorded in `refinery_schema_history` as adopted
  and nothing is executed, by running the embedded runner with
  `Target::FakeVersion(1)` guarded by `alembic_version` so refinery records its
  own checksum/name for the baseline. Any other revision or unmanaged schema is
  refused.
- CI (`rust-roll.yml`) builds an Alembic database and a Rust database and fails
  on any normalized `pg_dump` difference
  (`scripts/check_rust_migration_parity.py`).
