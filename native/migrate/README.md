# comicpile-migrate

Native Rust migration runner backed by [refinery](https://crates.io/crates/refinery). Alembic is retired; new schema changes are append-only SQL under `migrations/`.

```sh
MIGRATE_DATABASE_URL=postgresql://... cargo run --locked -p comicpile-migrate -- up
MIGRATE_DATABASE_URL=postgresql://... cargo run --locked -p comicpile-migrate -- plan
```

The runner reads `MIGRATE_DATABASE_URL`, falling back to `DATABASE_URL`, and strips supported SQLAlchemy `+asyncpg`/`+psycopg` URL prefixes. `plan` exits 0 when no migrations are pending and 10 when work remains; other failures exit non-zero with a sanitized message.

## Migration history

- `V1__baseline.sql` reproduces the former Alembic baseline schema.
- `V2__queue_exclusion_groups.sql` is the last schema change covered by the Alembic adoption stamp.
- `V3` and later migrations are Rust-only and always execute on an adopted Alembic database.
- Never edit an applied migration. Append `V<n>__description.sql` and let refinery embed it at build time.

The runner adopts supported Alembic-managed databases by recording V1/V2 as already applied without executing them, guarded by `alembic_version`. The historical heads `c44050000002` and `i5378deferred01` adopt V1 and run V2; `m54i537800001` adopts both. Any other revision, or a non-empty schema without `alembic_version`, is refused. An empty database is initialized by running all migrations and stamping the historical Alembic head. A session advisory lock serializes concurrent migration runs.

CI applies the committed Rust migrations to disposable PostgreSQL databases. There is no Alembic parity build, `make roll-test-schema` target, or Python migration runtime.

See `docs/DATABASE_SAVE_LOAD.md` for backup/restore and `docs/DEPLOYMENT.md` for the production plan-then-conditional-up workflow.
