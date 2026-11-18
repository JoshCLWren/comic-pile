# Migration rehearsal (issue #3554)

Alembic migrations are rehearsed against a **throwaway Postgres container**
loaded with a synthetic, prod-shaped fixture before they can reach production.
No Neon branches, clones or snapshots are used, no production credentials are
involved, and no raw production dump is ever loaded.

## What runs

`scripts/migration_rehearsal.py` runs, fail-closed and timed per step:

1. `alembic upgrade head` on an empty disposable database;
2. load the fixture from `scripts/generate_migration_fixture.py`
   (multiple users, threads with dependencies, reading plans with
   `nodes_json`, CBL-adopted plans, snoozed/blocked threads, NULL-heavy legacy
   rows, adversarial values; all synthetic, `example.invalid` emails);
3. `alembic downgrade <base-revision>` (the base Alembic head of the PR, or
   `-1`; a full downgrade to `base` is impossible because history-preserving
   migrations are intentionally irreversible);
4. `alembic upgrade head` again.

The first failing step aborts the run (exit 1). `--budget-seconds` also fails
the rehearsal when total step time exceeds the migration safety budget. The
runner pins `DATABASE_URL` to the disposable database for the run because
`alembic/env.py` otherwise prefers an ambient `DATABASE_URL`.

## Where it runs

- **Pull requests:** `.github/workflows/migration-rehearsal.yml` runs on
  `pull_request` only, and only when `alembic/**`, `app/models/**` or the
  rehearsal tooling change. It does not run on push to main. The base revision
  is the Alembic head at the PR's merge base. Because it is path-filtered it is
  a status check on matching PRs, not a gate for unrelated PRs; do not add it to
  required checks in branch protection (a path-skipped required check blocks
  unrelated PRs).
- **Deploy:** `.github/workflows/deploy-production.yml` runs the rehearsal on a
  local `postgres:16` container only when production has pending migrations,
  before `alembic upgrade head` touches production. Timing is written to the
  job summary. A failure aborts the deploy before any production mutation.

## Running locally

```bash
docker run -d --rm --name rehearsal -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=rehearsal -p 55432:5432 postgres:16
python scripts/migration_rehearsal.py \
  --database-url postgresql://postgres:postgres@127.0.0.1:55432/rehearsal \
  --apply-fixture --base-revision -1 --budget-seconds 300
docker stop rehearsal
```

Use the revision your branch started from as `--base-revision` to roll back
only your new migrations.

## Updating the fixture

Edit the row builders in `scripts/generate_migration_fixture.py`. Rows must
stay synthetic and satisfy live CHECK/NOT NULL constraints. When a migration
adds a constraint or `NOT NULL` column, add a violating or NULL historical row
that the migration must repair so the rehearsal exercises the data-dependent
failure mode. Never add real user data. Production diagnostics used to choose
fixture shapes must be aggregate counts only (no row values, emails or titles).

## #3359 regression coverage

The failure from #3359 (dangling `ContinuityRule` rows aborting
`c25530000001`) is reproduced and its #3495 fix verified in
`tests/test_roll_cutover_migration.py`: reviewed dangling rules are skipped and
reported; any other dangling rule still aborts the migration.
