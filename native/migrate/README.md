# comicpile-migrate

Rust database migration runner (successor to Alembic, which is frozen).

```sh
MIGRATE_DATABASE_URL=postgresql://... cargo run --locked -- up
```

- `migrations/0001_baseline.sql` is a cleaned `pg_dump --schema-only` of the
  Alembic head `i5378deferred01` (`make roll-test-schema` regenerates it). That
  revision is a no-op schema repair on top of `c44050000002`, so the baseline
  SQL is unchanged. Never
  edit an applied migration; append `0002_*.sql` etc. and register it in
  `MIGRATIONS` in `src/lib.rs`.
- `BASELINE_ALEMBIC_HEAD` in `src/lib.rs` is the current Alembic head reached by
  the full migration chain and must stay in sync with Alembic/parity checks.
- Empty database: all migrations run and `alembic_version` is stamped with the
  current head.
- Alembic database whose `alembic_version` equals the baseline schema head
  (`c44050000002`): baseline is recorded as adopted and later migrations run.
  Alembic database already at the current head: all migrations are adopted.
  Any other revision or unmanaged schema is refused.
- CI (`rust-roll.yml`) builds an Alembic database and a Rust database and fails
  on any normalized `pg_dump` difference (`scripts/check_rust_migration_parity.py`).
