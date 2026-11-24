# Production-to-local database copy

ComicPile has no supported user-scoped JSON clone/remapping CLI. The old
`scripts.clone_prod_to_local` command and `clone-prod-export` / `clone-prod-import`
Make targets were removed. Do not recreate or invoke them.

For an authorized full-database copy, use the maintained PostgreSQL backup and
restore scripts. This copies the **entire database**, including account rows and
password hashes; it is not a safe default for ordinary local development. Prefer
registering a synthetic local account through the UI instead.

## Prerequisites

- PostgreSQL client tools (`pg_dump`, `psql`) compatible with the server.
- Explicit owner authorization to export production data.
- A fresh, empty, loopback local PostgreSQL database for the import.
- A secure temporary location for the dump. Never commit or upload it.

## 1. Export with the production URL

The backup script reads `.env` from its checkout. Use a temporary secure checkout
or securely prepared `.env` containing the authorized production `DATABASE_URL`;
do not overwrite a developer's normal local configuration inadvertently.

For a standard Neon URL, use `pg_dump`'s URL support directly because the shell
backup script requires an explicit `host:port` and does not strip query
parameters:

```bash
mkdir -p backups/postgres
pg_dump --dbname="$NEON_DIRECT_DATABASE_URL" --no-owner --no-acl \
  | gzip > "backups/postgres/postgres_backup_neondb_$(date +%Y%m%d_%H%M%S).sql.gz"
gzip -t backups/postgres/postgres_backup_neondb_*.sql.gz
```

For an explicitly formatted `host:port` URL without query parameters,
`make backup-postgres` remains available. Either path produces a gzip-compressed
plain SQL dump. Treat it as production credentials and reader data. Gzip
integrity is not a restore rehearsal.

## 2. Prepare an empty local target

Create a fresh empty local database. Use a separate checkout or securely prepared
`.env` whose `DATABASE_URL` points at that loopback target.

The restore script refuses every non-loopback host and has no override. It pipes
the dump into `psql`; it does not drop/recreate the target. Because the dump has
no `--clean`/`--if-exists`, importing into a non-empty target will produce
duplicate-object errors. Let the dump create the schema in the empty target; run
the migration planner afterward instead of migrating before restore.

## 3. Restore into the empty loopback database

```bash
make restore-postgres FILE=backups/postgres/postgres_backup_<database>_<timestamp>.sql.gz
set -a; . ./.env; set +a
cargo run --locked -p comicpile-migrate -- plan
```

Review the destination and type `yes` only after confirming it is the disposable
local database. If the planner reports pending work, apply forward migrations
before serving the copied data.

## 4. Secure and verify the copy

- Keep the dump and any pre-copy backup private and access-controlled.
- Do not expect production passwords to be appropriate for local use. The dump
  contains password hashes and auth state; never expose the copied database on a
  network or use it as a shared test service.
- Verify counts and representative screens locally, then delete the copy and
  dump when the authorized task is complete.
- Never point an import, test or application process at production for destructive
  verification.

See [`DATABASE_SAVE_LOAD.md`](DATABASE_SAVE_LOAD.md) for backup rotation, restore
limitations and production disaster-recovery boundaries.
