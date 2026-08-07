# Production-to-local data clone workflow

This workflow copies one ComicPile user's data from the production PostgreSQL database into a local development database. Production PostgreSQL is hosted by Neon. The export is read-only, the import remaps every exported ID, and authentication secrets are never copied.

## Prerequisites

- A working local checkout with the project virtual environment installed.
- A production Neon PostgreSQL URL supplied through `CLONE_PROD_DB_URL` or `--db-url`.
- A local PostgreSQL database with the current schema. Run migrations first:

```bash
make migrate
```

The local database URL can be supplied with `--local-db-url`, or the script can use the normal application database configuration.

## Export production data

Always pass the production Neon database URL explicitly with `CLONE_PROD_DB_URL` or `--db-url`. Railway is retired and is not a supported production source.

```bash
CLONE_PROD_DB_URL='postgresql+asyncpg://USER:PASSWORD@HOST:5432/DB' \
python -m scripts.clone_prod_to_local export \
  --username YOUR_PRODUCTION_USERNAME \
  --output prod_backup.json
```

You can provide the same value directly with `--db-url` instead of using the environment variable. Review the redacted target before confirming the export.

The output is a private (`0600`) JSON file. It contains user-scoped threads, issues, dependencies, reading orders, sessions, events, and snapshots. It does not contain `password_hash`, revoked tokens, failed-login records, or database credentials.

## Validate without writing

Run the import in dry-run mode before changing the local database:

```bash
python -m scripts.clone_prod_to_local import \
  --file prod_backup.json \
  --dry-run \
  --local-db-url 'postgresql+asyncpg://USER:PASSWORD@localhost:5435/comic_pile'
```

Dry-run validates the schema and all exported foreign-key references, reports the per-table record counts that would be imported, and performs no database writes.

## Import into local development

A normal import replaces that user's clone data in one transaction, and a failed import is rolled back. The CLI currently creates a timestamped destination backup by default; use `--backup` when you need a predictable path:

```bash
python -m scripts.clone_prod_to_local import \
  --file prod_backup.json \
  --backup local_before_clone.json \
  --local-db-url 'postgresql+asyncpg://USER:PASSWORD@localhost:5435/comic_pile'
```

Type `yes` at the confirmation prompt after checking the destination. For non-interactive automation, add `--yes` only after validating the file and confirming that the resolved destination is a local development database.

After a successful import, sign in with the imported username. The imported user has no production password hash, so set a local password through the normal registration or administrative workflow rather than expecting the production password to work.

## Safety checklist

1. Confirm the explicit Neon export target is production and the username is correct.
2. Keep export and pre-import backup files private; do not commit them.
3. Run `--dry-run` against the intended local database.
4. Confirm the resolved import target is a local development database before allowing writes.
5. Keep the pre-import backup until the clone has been verified.
6. Confirm thread counts, reading orders, and sessions in the local UI.

The command must never mutate production. Export is the only operation that should connect to production, and import must target a local development database supplied by configuration or `--local-db-url`.
