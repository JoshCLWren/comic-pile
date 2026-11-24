# Database Save/Load Guide

Backup, restore, and schema migration for Comic Pile's PostgreSQL database.

The Python-era JSON export/import scripts and the in-process startup snapshot
writer were removed with the Python application. The maintained mechanism is
PostgreSQL-native `pg_dump`/`psql` through the scripts below, plus the Rust
migration runner for schema changes.

## PostgreSQL native backups (recommended)

Both scripts read `.env` from the repository root and accept
`postgresql+asyncpg://`, `postgresql+psycopg://`, `postgresql://`, and
`postgres://` URLs.

### Quick start

```bash
# Create a compressed backup (default dir: backups/postgres, keeps 10)
make backup-postgres

# List backups
make list-postgres-backups

# Restore a specific backup
make restore-postgres FILE=backups/postgres/postgres_backup_YYYYMMDD_HHMMSS.sql.gz
```

### Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | required, from `.env` | Source/target database |
| `BACKUP_DIR` | `backups/postgres` | Output directory |
| `MAX_BACKUPS` | `10` | Rotation count kept by the backup script |

Backups are gzip-compressed `pg_dump` output named
`postgres_backup_<timestamp>.sql.gz`. Treat them as production data: they
contain reader libraries and account rows. Do not commit or upload them.

### Manual restore procedure

```bash
# Stop the app dev servers first (Ctrl-C in the make dev terminal)

# Decompress and restore into the configured database
gunzip -c backups/postgres/postgres_backup_YYYYMMDD_HHMMSS.sql.gz \
  | psql "postgresql://comicpile:comicpile_password@localhost:5435/comicpile"

# Re-apply migrations to confirm the schema is current
set -a; . ./.env; set +a
make migrate
```

Restoring over a live database replaces its contents. Use a disposable
database for rehearsals; see [`prod-clone-workflow.md`](prod-clone-workflow.md)
before loading production data locally.

### Prerequisites

`pg_dump` and `psql` must be installed and match or exceed the server's major
version.

```bash
# Ubuntu/Debian
sudo apt-get install postgresql-client

# macOS
brew install postgresql@16

# RHEL/CentOS
sudo dnf install postgresql
```

### Disaster recovery

```bash
# 1. Stop application traffic
# 2. Back up the current (possibly broken) database first
make backup-postgres

# 3. Restore the last known-good backup
make restore-postgres FILE=backups/postgres/<last-good>.sql.gz

# 4. Verify migrations report no pending work
set -a; . ./.env; set +a
cargo run --locked -p comicpile-migrate -- plan
```

### Troubleshooting

```bash
# Is the database reachable?
pg_isready -h localhost -p 5435 -U comicpile -d comicpile

# Verify an archive is intact
gzip -t backups/postgres/postgres_backup_YYYYMMDD_HHMMSS.sql.gz

# Check disk space
df -h .
```

- `ERROR: .env file not found` — run from a repository checkout that has `.env`.
- `ERROR: DATABASE_URL not set in .env` — add it (see `.env.example`).
- Authentication failures — the scripts derive `PGUSER`/`PGPASSWORD` from
  `DATABASE_URL`; URL-encoded passwords must stay encoded.
- Permission failures — check ownership of `backups/postgres`.

## Schema migrations

Schema changes are append-only SQL under `native/migrate/migrations/`, applied
by the Rust refinery runner. Alembic is retired; do not recreate an `alembic/`
tree.

```bash
# Append a migration: native/migrate/migrations/V<n>__description.sql

# Apply migrations
set -a; . ./.env; set +a
make migrate            # cargo run --locked -p comicpile-migrate -- up

# Verify no work remains (non-zero exit when migrations are pending)
cargo run --locked -p comicpile-migrate -- plan

# Target another database (for example a direct Neon URL)
MIGRATE_DATABASE_URL="postgresql://..." cargo run --locked -p comicpile-migrate -- up
```

The runner reads `MIGRATE_DATABASE_URL`, falling back to `DATABASE_URL`, and
strips SQLAlchemy `+asyncpg`/`+psycopg` suffixes.

There is no downgrade path. To roll back an applied migration, restore a
pre-migration backup (above) or write a new forward migration. The production
deploy workflow runs `up` and then `plan` against Neon before deploying.

## Related commands

```bash
make migrate                 # apply migrations
make backup-postgres         # pg_dump backup
make restore-postgres FILE=… # restore a backup
make list-postgres-backups   # list backups
make prod-migrate            # apply migrations to Neon production
make dev                     # frontend + native API
```

## Production-to-local copies

Use [`prod-clone-workflow.md`](prod-clone-workflow.md) for the sanctioned
export/import path when reproducing production data locally. It covers Neon
export, safe local restore, and cleanup, and replaces the old ad-hoc JSON
export/import instructions.
