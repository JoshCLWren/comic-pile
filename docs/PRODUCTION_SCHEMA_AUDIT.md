# Production Schema Audit (#4735)

Scheduled, **read-only** comparison of production Neon PostgreSQL against the
canonical Alembic fixture at
`native/roll-service/tests/fixtures/schema/public_schema.sql`.
`alembic current` only proves the migrated stamp; this audit proves actual
schema equivalence through `pg_dump --schema-only` normalized with the
established `scripts/export_roll_test_schema.py` logic plus order-insensitive
statement comparison (`scripts/production_schema_audit.py`).

## What it proves

- A scheduled run against unchanged production schema succeeds and emits a
  minimal diagnostic (counts plus changed object names, and a bounded,
  redacted diff artifact on mismatch).
- A deliberate schema change (added/dropped column, index, or constraint)
  is reliably detected; see `tests/test_production_schema_audit.py`, which
  covers both synthetic mutations and a throwaway-PostgreSQL round-trip.
- Owner/grant/extension-version/ordering noise is normalized deliberately
  without masking real table/column/index/constraint/function changes.
  Function bodies are compared verbatim.

## Required external prerequisite: least-privilege role and secret

> **Live scheduled acceptance is pending this setup.** This repository does
> not create roles or secrets, and no production write or Neon branch is
> performed. The audit will fail closed until the owner provisions the role
> below and stores its direct URL in the repository secret
> `PRODUCTION_SCHEMA_AUDIT_DATABASE_URL`.

Provision a **dedicated read-only role** on the production database (for
example via the Neon SQL editor as the project owner). The statements below
are a starting point, to be adapted to the actual Neon's ownership model:

```sql
CREATE ROLE schema_audit LOGIN PASSWORD '<strong-generated-password>' CONNECTION LIMIT 2;
ALTER ROLE schema_audit SET default_transaction_read_only = on;
ALTER ROLE schema_audit SET statement_timeout = '60s';
ALTER ROLE schema_audit SET lock_timeout = '30s';

GRANT CONNECT ON DATABASE "<production-db>" TO schema_audit;
GRANT USAGE ON SCHEMA public TO schema_audit;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO schema_audit;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO schema_audit;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO schema_audit;
```

- The role gets **no** write grants, **no** `BYPASSRLS`, **no** superuser,
  and **no** ownership of application objects. The audit script additionally
  refuses to run as `postgres`/`neondb_owner` and enforces a read-only,
  time-bounded session, but those are defense-in-depth, not substitutes for
  least-privilege grants.
- Store the role's **direct (non-pooled)** connection string — `pg_dump`
  needs session state that the pooled endpoint does not provide — as the
  GitHub repository secret `PRODUCTION_SCHEMA_AUDIT_DATABASE_URL`:
  `postgresql://schema_audit:<password>@<direct-host>/<db>?sslmode=require`.
- Do **not** reuse `NEON_DIRECT_DATABASE_URL` (owner credential) or any
  application-writer credential for this audit. The script reads the URL
  only from the environment, transports it through `PG*` variables, and
  never places the DSN or password in `argv`, logs, summaries, or artifacts.
- The workflow (`.github/workflows/production-schema-audit.yml`) runs weekly
  on schedule plus manual dispatch, with `contents: read` permissions, a
  trusted checkout (`persist-credentials: false`), and **no**
  `pull_request_target`, so untrusted branch code never runs with the secret
  in scope. It fails closed when the secret is absent.

### Verified role-provisioning contract (throwaway Postgres 16)

The provisioning SQL above was applied verbatim to a throwaway
`postgres:16-alpine` container loaded with the canonical fixture, and the
audit entry point (`scripts/production_schema_audit.py`, not just the
comparison helpers) was run against it with the dedicated role:

- unchanged fixture-loaded database → exit `0`, minimal diagnostic
  (`added: 0; removed: 0; changed: 0`), empty diff artifact;
- `ALTER TABLE … ADD COLUMN` + `CREATE INDEX` → exit `1`, targeted output
  (`added: INDEX ix_audit_probe…`, `changed: TABLE threads`), bounded diff
  artifact, **no** role password in stdout, stderr, or the artifact;
- `postgres` / `neondb_owner` credentials → exit `2`
  (`refusing to run with an admin/owner database user`);
- missing `PRODUCTION_SCHEMA_AUDIT_DATABASE_URL` → exit `2` (fail closed);
- the `schema_audit` role cannot execute DDL or `INSERT`
  (`cannot execute … in a read-only transaction`).

This round trip is locked in as a regression test:
`tests/test_production_schema_audit.py::test_documented_least_privilege_role_round_trip`
(skipped only when docker or pg_dump is unavailable). The Neon production
role must still be created by the project owner as described above; the
throwaway evidence proves the grants and session settings are sufficient
and that nothing else is needed.

## Closing #4735: remaining owner action

The scheduled audit is live code on `main` but cannot prove production until
the owner completes this one-time sequence:

1. Run the provisioning SQL above against production Neon as the project
   owner (adapt the database name; the grants must cover the current
   `public`-schema objects and all future ones via
   `ALTER DEFAULT PRIVILEGES … GRANT SELECT ON TABLES TO schema_audit` if
   the owner wants the audit to survive future migrations without re-granting).
2. Store the role's **direct** URL as the repository secret
   `PRODUCTION_SCHEMA_AUDIT_DATABASE_URL`.
3. Confirm the next weekly run (Monday 06:00 UTC) or an owner-authorized
   `workflow_dispatch` run completes with exit `0`. That run is the
   acceptance evidence for "CI scheduled run succeeds against unchanged
   production schema". No factory or agent may provision the role, create
   the secret, or connect to production to obtain it.

## Known prod-only extensions

**No extension is ignored by default.** The allowlist
(`PROD_ONLY_EXTENSION_ALLOWLIST` in `scripts/export_roll_test_schema.py`)
ships empty. The canonical fixture intentionally contains exactly one
extension, `pg_trgm` (created by migration `c40080000001`). If a production
dump shows platform extensions (for example `pg_stat_statements` or Neon
platform extensions) that are preinstalled outside Alembic, the audit will
report them as `EXTENSION` drift. Each such extension must then be reviewed
and, only if genuinely platform-managed, added to the allowlist **by exact
name** with a rationale comment — never via a blanket extension/function
ignore. Function, constraint, index, and table drift is never allowlisted.

## Fixture update process

When the audit (or CI's `--check` for `make roll-test-schema`) reports
expected drift, confirm the difference is real and intended, then:

1. Run `make roll-test-schema` against a database migrated to the Alembic
   head (`DATABASE_URL`).
2. Commit the regenerated `public_schema.sql`; the fixture is never edited
   by hand.
3. Push; CI regenerates and diffs, and the next scheduled audit re-checks
   production against the updated fixture.
