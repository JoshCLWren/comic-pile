# comicpile-migrate

`comicpile-migrate` is the Rust/refinery database migration runner used by local
development, CI and the production deployment workflow. Alembic is retired; do
not recreate an `alembic/` tree or edit an applied migration.

## Commands

The runner reads `MIGRATE_DATABASE_URL`, falling back to `DATABASE_URL`. It
accepts `postgresql://`, `postgres://`, and the historical
`postgresql+asyncpg://` / `postgresql+psycopg://` forms and strips the driver
suffix before connecting.

```sh
# Apply every pending embedded migration.
MIGRATE_DATABASE_URL=postgresql://... cargo run --locked -p comicpile-migrate -- up

# Report whether work is pending without applying it.
# Exit 0 means current; exit 10 means pending; other nonzero codes are failures.
MIGRATE_DATABASE_URL=postgresql://... cargo run --locked -p comicpile-migrate -- plan
```

`make migrate` runs `up`. The production workflow runs `up` before deployment
and uses `plan` to verify that no migration remains pending.

## Migration ownership

- Migrations are append-only files under `native/migrate/migrations/`.
- `V1__baseline.sql` reproduces the schema at the retired Alembic baseline. V2
  adopts the queue-exclusion schema that was already present in supported
  Alembic-managed databases. Later migrations are ordinary refinery migrations.
- The runner still reads `alembic_version` solely to adopt a supported historical
  database safely. An empty database runs all migrations; a database at a
  supported Alembic head adopts the covered versions and applies newer Rust-only
  migrations. Unknown or unmanaged schema states fail closed.
- Refinery records applied versions and checksums in
  `public.refinery_schema_history`. A session advisory lock serializes concurrent
  runners.
- `MIGRATE_LOCK_TIMEOUT` and `MIGRATE_STATEMENT_TIMEOUT` optionally bound lock
  waits and statement execution for deployment automation.

## Validation

CI applies every embedded migration to a fresh disposable PostgreSQL database,
reruns the runner to prove idempotence, and exercises the production runner. Use
a disposable database for local migration tests; never point these commands at
production.

See [deployment](../docs/DEPLOYMENT.md) and
[database save/load and recovery](../docs/DATABASE_SAVE_LOAD.md) for the operator
workflow.
