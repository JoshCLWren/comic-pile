# Migration rehearsal (#3554)

Migration changes are rehearsed against a **throwaway Postgres container/database** populated with checked-in, **prod-shaped synthetic/anonymized fixtures**. This catches data-dependent upgrade and downgrade failures before merge and before production mutation.

## Safety boundaries

- **Never use Neon branches, clones, snapshots, or production credentials** for rehearsal or fixture generation. The throwaway database is the only database touched.
- **Never copy production data** (no raw `pg_dump` of prod, no PII, credentials, comic titles, or emails) into fixtures, CI artifacts, or logs.
- Fixtures live under `tests/fixtures/migration_rehearsal/` and contain synthetic/anonymized edge-case rows only.
- Rehearsal scripts refuse obvious Neon/preview URLs and require an explicit disposable database URL.

## What the rehearsal does

Given the fixture at `tests/fixtures/migration_rehearsal/prod_shaped/` (see `manifest.json` for `base_revision`):

1. Reset the throwaway database schema.
2. `alembic upgrade <fixture base_revision>`.
3. Load `seed.sql` (prod-shaped edge-case data valid at that revision).
4. `alembic upgrade head` (records duration; fails if a migration safety budget is exceeded).
5. `alembic downgrade <base>` (PR base revision or `-1` per new revision, depending on context) unless explicitly skipped.
6. `alembic upgrade head` again (records duration).

Step 4 exercises data-dependent failures on historical/prod-shaped rows (including the reviewed dangling ContinuityRule allowlist case from #3359/#3495). Steps 5–6 exercise rollback and re-apply of the migrations under test.

## Running locally

Prerequisites: disposable Postgres 16 (same major version as production), project Python environment with Alembic/runtime deps (`uv sync` or equivalent), and `psql` on `PATH`.

Start a throwaway container:

```bash
docker run --rm -d --name comic-pile-mig-rehearsal \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=comic_pile_rehearsal \
  -p 55432:5432 postgres:16

# wait until ready
until docker exec comic-pile-mig-rehearsal pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
```

Run the rehearsal:

```bash
export DATABASE_URL='postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/comic_pile_rehearsal'
export MIGRATION_REHEARSAL_DATABASE_URL="$DATABASE_URL"

# Full fixture rehearsal (upgrade from fixture revision, downgrade cycle, upgrade again)
python3 scripts/rehearse_migrations.py --database-url "$MIGRATION_REHEARSAL_DATABASE_URL"

# PR-style rehearsal against a base ref (downgrades new migrations / PR base)
python3 scripts/rehearse_migrations.py \
  --database-url "$MIGRATION_REHEARSAL_DATABASE_URL" \
  --base-ref origin/main

# Explicit downgrade target or step count
python3 scripts/rehearse_migrations.py --database-url "$MIGRATION_REHEARSAL_DATABASE_URL" --base <revision>
python3 scripts/rehearse_migrations.py --database-url "$MIGRATION_REHEARSAL_DATABASE_URL" --downgrade-steps 1

# Write timing metadata
python3 scripts/rehearse_migrations.py \
  --database-url "$MIGRATION_REHEARSAL_DATABASE_URL" \
  --timing-json /tmp/migration-rehearsal-timing.json
```

Cleanup:

```bash
docker stop comic-pile-mig-rehearsal
```

## Updating the fixture

The fixture has three parts:

- `tests/fixtures/migration_rehearsal/prod_shaped/manifest.json` — `base_revision` (Alembic revision the seed is shaped for) and description.
- `tests/fixtures/migration_rehearsal/prod_shaped/seed.sql` — synthetic/anonymized data rows loaded after migrating to `base_revision`.
- `scripts/generate_migration_rehearsal_fixture.py` — regeneration helper.

### When to update

- A migration introduces new tables/columns/constraints that the seed must satisfy at or after `base_revision`.
- New edge cases are needed (adversarial NULLs, duplicates/conflicts, extreme/legacy values, representative volume) to cover data-dependent failure modes.
- The fixture `base_revision` is intentionally advanced (regenerate against the new revision).

### Regeneration workflow

1. Start a disposable Postgres 16 container (no Neon/prod).
2. Point `DATABASE_URL`/`--database-url` at it.
3. If `seed.sql` is still compatible with `base_revision`, regenerate/dump deterministically:

```bash
python3 scripts/generate_migration_rehearsal_fixture.py \
  --database-url 'postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/mig_fixture_gen'
```

4. If the seed needs new or changed rows, edit `seed.sql` (or generate via a throwaway DB), load it at `base_revision`, verify `scripts/rehearse_migrations.py` passes, then re-run the generator to normalize the dump.
5. Commit the updated `manifest.json`, `seed.sql`, and any generator changes together.

### Fixture content guidelines

- Multiple users, threads with dependencies, reading plans with `nodes_json`, CBL source-linked/adopted-shape plans, snoozed and blocked threads, NULL-heavy legacy rows.
- Adversarial data-dependent cases (e.g. values that would violate a new `NOT NULL`/unique/check constraint or break a backfill) must be represented when relevant so migrations are proven safe or fail closed in rehearsal.
- Keep data synthetic/anonymized. No real user records, tokens, emails, titles, or credentials.

## CI and deploy integration

- **CI (`migration-rehearsal`)**: runs on pull requests/pushes with a throwaway Postgres service container and the checked-in fixture. It is part of the required CI gate.
- **Deploy Production**: when pending Alembic migrations are detected, deploy rehearses them against a throwaway Postgres container populated with the prod-shaped fixture and records migration timing **before** running `alembic upgrade head` on production. A rehearsal failure aborts before production mutation; deploys with no pending migrations incur no extra rehearsal cost.

## Regression: #3359 / #3495

The fixture includes the reviewed dangling `ContinuityRule` allowlist case (test user 23199, rule IDs 1715192/1715241/1715291/1715333/1715578/1715620 referencing missing issue IDs 1117318/1117522/1117685) at revision `m5d300000001`. Upgrading through `c25530000001` must skip/report these rows and succeed (post-#3495 behavior). Running the same data through the pre-#3495 migration logic would abort; the focused regression test and rehearsal fixture guard this failure mode.
