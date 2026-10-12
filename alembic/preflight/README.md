# Migration preflight manifests

Each JSON file in this directory is named `<revision>.json` and encodes the
machine-enforced safety preconditions for one risky Alembic migration. The
gates that consume them live in `scripts/migration_safety.py` and are wired
into CI (`migration-safety`) and `deploy-production.yml`.

Full policy and schema reference: `docs/MIGRATION_SAFETY.md`.

A manifest is required whenever a migration's source contains:

- a uniqueness enforcement (`op.create_unique_constraint`, `unique=True`, or
  `CREATE UNIQUE ...` via `op.execute`) → `risks: ["unique-constraint"]` plus
  at least one `preflight_checks` entry proving existing rows satisfy the new
  invariant;
- data mutation (`op.execute` with INSERT/UPDATE/DELETE/TRUNCATE, or
  `op.bulk_insert`) → `risks: ["data-migration"]` plus a `data_migration`
  section with `idempotent: true`, a deterministic `dry_run_sql` SELECT, and
  optionally `reconciliation_sql`;
- a destructive change (`op.drop_column`, `op.drop_table`) → `risks:
  ["destructive"]` plus a `destructive` section naming the `table.column`
  target and the expand/contract tracking issue. The static gate additionally
  fails while application code under `app/` still references the dropped
  column.

Every `sql` value must be a single read-only `SELECT` statement. A violated
precondition blocks merge (static gate) or deploy (read-only production
preflight) and reports the concrete violated condition; production is left
unchanged.
