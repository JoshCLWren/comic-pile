# Database save/load and recovery

ComicPile uses PostgreSQL-native `pg_dump` / `psql` for backup and restore and
the Rust refinery runner for schema changes. The Python JSON import/export and
startup snapshot tools were removed with the Python application.

## Backup

`make backup-postgres` loads `.env`, reads `DATABASE_URL`, writes a compressed
plain-text dump and keeps the newest `MAX_BACKUPS` files (default 10). Its shell
URL parser requires an explicit `host:port` and does not remove query parameters,
so use the direct `pg_dump` command below for standard Neon URLs.

```bash
make backup-postgres
make list-postgres-backups
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | required from `.env` | Source database |
| `BACKUP_DIR` | `backups/postgres` | Output directory |
| `MAX_BACKUPS` | `10` | Rotated backup count |

The script names files
`postgres_backup_<database>_<YYYYMMDD_HHMMSS>.sql.gz`. For the local `comicpile`
database, for example:

```text
backups/postgres/postgres_backup_comicpile_20261124_164700.sql.gz
```

Backups contain reader libraries and account rows. Treat them as production
data: never commit or upload them. The script verifies gzip integrity but that
is not a substitute for a restore rehearsal.

For a standard Neon URL (often no explicit port and with `?sslmode=...` query
parameters), use `pg_dump`'s URL support directly instead of the shell parser:

```bash
mkdir -p backups/postgres
pg_dump --dbname="$NEON_DIRECT_DATABASE_URL" --no-owner --no-acl \
  | gzip > "backups/postgres/postgres_backup_neondb_$(date +%Y%m%d_%H%M%S).sql.gz"
gzip -t backups/postgres/postgres_backup_neondb_*.sql.gz
```

Keep the URL in the environment, not in source, logs or issue comments. The
result is the same plain-text gzip format accepted by the local restore script.

`pg_dump` and `psql` must be installed and match or exceed the server's major
version. On Debian/Ubuntu, install `postgresql-client`; on macOS, install the
matching PostgreSQL client package.

## Restore into an empty local database

`make restore-postgres` is deliberately restricted to loopback/local PostgreSQL
hosts. It refuses Neon, Vercel or any other non-loopback target and has no
override. It pipes the dump into `psql`; it does **not** drop/recreate the target
database, and the backup is not created with `--clean`/`--if-exists`. Restoring
over an existing schema therefore produces duplicate-object errors rather than
replacing its contents.

Use an empty disposable/local database for restore:

```bash
# 1. Stop local app/dev servers that use the target.
# 2. Create an empty target database with your local PostgreSQL tooling.
# 3. Point DATABASE_URL in .env at that empty loopback database.
# 4. Restore the selected file.
make restore-postgres FILE=backups/postgres/postgres_backup_comicpile_YYYYMMDD_HHMMSS.sql.gz

# 5. Confirm the schema is current.
set -a; . ./.env; set +a
cargo run --locked -p comicpile-migrate -- plan
```

For a manual local restore, the equivalent pipe is:

```bash
gunzip -c backups/postgres/postgres_backup_comicpile_YYYYMMDD_HHMMSS.sql.gz \
  | psql "postgresql://comicpile:comicpile_password@localhost:5435/comicpile"
```

That command has the same empty-target requirement. Use
[`prod-clone-workflow.md`](prod-clone-workflow.md) for the sanctioned production
export to a fresh local database.

## Production disaster recovery

Do not use `make restore-postgres` against production: it rejects non-loopback
hosts by design. Production recovery must use the authorized Neon/Vercel operator
procedure and a verified backup or point-in-time restore target. Preserve the
current possibly broken database before any destructive action, verify schema
compatibility with the deployed revision, and keep reader data out of ad-hoc
local scripts.

The maintained production deployment workflow does not restore dumps. It runs
the migration planner, applies pending migrations when required, deploys the
exact `main` SHA and verifies production probes. There is no automatic database
downgrade.

## Schema migrations

Schema changes are append-only SQL under `native/migrate/migrations/`, applied by
the Rust refinery runner. Alembic is retired; do not recreate an `alembic/` tree
or edit an applied migration.

```bash
set -a; . ./.env; set +a
make migrate

# Exit 0: current. Exit 10: pending. Other nonzero: failed closed.
cargo run --locked -p comicpile-migrate -- plan

# Explicit alternate target, such as a direct Neon URL:
MIGRATE_DATABASE_URL="postgresql://..." cargo run --locked -p comicpile-migrate -- up
```

The runner reads `MIGRATE_DATABASE_URL`, falling back to `DATABASE_URL`, and
strips historical `+asyncpg` / `+psycopg` suffixes. Production startup requires
TLS. See [`native/migrate/README.md`](../native/migrate/README.md).

There is no downgrade command. Roll back an applied schema change with a new
forward migration or an authorized pre-migration backup restore. A previous
Vercel deployment is not proof of compatibility with the current Neon schema.

## Troubleshooting

- `.env` missing or `DATABASE_URL` unset: run from a configured checkout.
- Restore refuses the host: the script permits only loopback/local targets.
- Duplicate-object errors: the target was not empty; use a fresh disposable
  database instead of treating the dump as a replacement archive.
- Authentication failures: URL-encoded credentials must remain encoded; the
  scripts derive `PGUSER` / `PGPASSWORD` from `DATABASE_URL`.
- Permission failures: check ownership of `backups/postgres`.
- Migration planner exit 10: pending migrations remain; apply them before serving
  the new application revision.
