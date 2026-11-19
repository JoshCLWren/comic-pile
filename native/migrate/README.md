# comicpile-migrate

Rust database migration runner (successor to Alembic, which is frozen).

```sh
MIGRATE_DATABASE_URL=postgresql://... cargo run --locked -- up
```

- `migrations/0001_baseline.sql` is a cleaned `pg_dump --schema-only` of the
  Alembic head `s54350000001` (`make roll-test-schema` regenerates it). Never
  edit an applied migration; append `0002_*.sql` etc. and register it in
  `MIGRATIONS` in `src/lib.rs`.
- Empty database: baseline runs and `alembic_version` is stamped with the head.
- Alembic database whose `alembic_version` equals the baseline head
  (production): the baseline is recorded in `schema_migrations` as adopted and
  nothing is executed. Any other revision or unmanaged schema is refused.
- CI (`rust-roll.yml`) builds an Alembic database and a Rust database and fails
  on any normalized `pg_dump` difference (`scripts/check_rust_migration_parity.py`).
