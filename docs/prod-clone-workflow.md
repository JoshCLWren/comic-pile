# Production-to-local data clone workflow

This workflow copies one Comic Pile user's data from the production PostgreSQL
database into a local development database. The export is read-only, the import
remaps every exported ID, and authentication secrets are never copied.

## Prerequisites

- A working local checkout with the project virtual environment installed.
- The Railway CLI authenticated to the production project, or a production
  PostgreSQL URL supplied through `CLONE_PROD_DB_URL`.
- A local PostgreSQL database with the current schema. Run migrations first:

```bash
make migrate
```

The local database URL can be supplied with `--local-db-url`, or the script can
use the normal application database configuration.

## Export production data

The default export command obtains `DATABASE_PUBLIC_URL` from the Railway
Postgres service. Always review the redacted target and confirm the username
before proceeding.

```bash
python -m scripts.clone_prod_to_local export \
  --username YOUR_PRODUCTION_USERNAME \
  --output prod_backup.json
```

For an explicit connection URL:

```bash
CLONE_PROD_DB_URL='postgresql+asyncpg://USER:PASSWORD@HOST:5432/DB' \
python -m scripts.clone_prod_to_local export \
  --username YOUR_PRODUCTION_USERNAME \
  --output prod_backup.json
```

The output is a private (`0600`) JSON file. It contains user-scoped
collections, threads, issues, dependencies, reading orders, sessions, events,
snapshots, and reviews. It does not contain `password_hash`, revoked tokens,
failed-login records, or database credentials.

## Validate without writing

Run the import in dry-run mode before changing the local database:

```bash
python -m scripts.clone_prod_to_local import \
  --file prod_backup.json \
  --dry-run \
  --local-db-url 'postgresql+asyncpg://USER:PASSWORD@localhost:5435/comic_pile'
```

Dry-run validates the schema and all exported foreign-key references, prints
the records that would be imported, and performs no database writes.

## Import into local development

The normal import creates a backup of the destination user's current data,
then replaces that user's clone data in one transaction. A failed import is
rolled back. Use an explicit backup path when you need a predictable location:

```bash
python -m scripts.clone_prod_to_local import \
  --file prod_backup.json \
  --backup local_before_clone.json \
  --local-db-url 'postgresql+asyncpg://USER:PASSWORD@localhost:5435/comic_pile'
```

Type `yes` at the confirmation prompt after checking the destination. For
non-interactive automation, add `--yes` only after validating the file:

```bash
python -m scripts.clone_prod_to_local import \
  --file prod_backup.json \
  --dry-run \
  --yes
```

After a successful import, sign in with the imported username. The imported
user has no production password hash, so set a local password through the
normal registration or administrative workflow rather than expecting the
production password to work.

## Safety checklist

1. Confirm the export target is production and the username is correct.
2. Keep export and pre-import backup files private; do not commit them.
3. Run `--dry-run` against the intended local database.
4. Keep the pre-import backup until the clone has been verified.
5. Confirm thread counts, reading orders, sessions, and reviews in the local UI.

The command never mutates production. It only reads production during export;
the import connects to the local database URL supplied by configuration or
`--local-db-url`.
